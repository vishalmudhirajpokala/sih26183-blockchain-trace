"""
EVM chain adapter — one implementation serving Ethereum, BNB Smart Chain and
Polygon.

The three networks differ in data availability, not in transaction semantics, so
one class parameterised by chain id is the right shape. What differs is wired
through `_EVM_CHAIN_CONFIG`: explorer URLs, RPC endpoints, and above all
whether address history is available at all.

Capability reality (see PROVIDER_FINDINGS.md, all rows probed live):

    Ethereum  Blockscout keyless  -> full transfers, token transfers, labels
    Polygon    Blockscout keyless  -> full transfers, token transfers, labels
    BSC        nothing keyless     -> network status only

BSC is the awkward one. `bnb.blockscout.com` is 404, Routescan answers "chain
not supported", and Etherscan V2 requires a paid plan for chain 56. Rather than
return a plausible empty list, the adapter raises the honest answer: the
capability is unavailable and says so, so the UI can prompt for a key instead
of showing a wallet as "no transactions found".
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from adapters.base import AdapterTrace, ChainAdapter, NetworkInfo
from models.schemas import (
    AttributionSource,
    Availability,
    BlockchainTransaction,
    Chain,
    Direction,
    EntityAttribution,
    EntityType,
    TraceEdge,
    TraceNode,
    TraceStatus,
    VerificationStatus,
)
from services.chain_detection import validate_evm_address
from services.entity_service import classify_public_label, resolve_entity
from utils.http_client import HttpClient

NATIVE_ASSET = {
    Chain.ETHEREUM: "ETH",
    Chain.BSC: "BNB",
    Chain.POLYGON: "POL",
}


@dataclass(frozen=True)
class EVMChainConfig:
    chain: Chain
    chain_id: int
    currency_symbol: str
    explorer_name: str
    address_url: str
    tx_url: str
    blockscout_base: Optional[str] = None
    rpc_urls: Tuple[str, ...] = ()
    #: Whether an address-history provider exists without an API key.
    keyless_address_history: bool = True


_EVM_CHAIN_CONFIG: Dict[Chain, EVMChainConfig] = {
    Chain.ETHEREUM: EVMChainConfig(
        chain=Chain.ETHEREUM,
        chain_id=1,
        currency_symbol="ETH",
        explorer_name="etherscan",
        address_url="https://etherscan.io/address/",
        tx_url="https://etherscan.io/tx/",
        blockscout_base="https://eth.blockscout.com/api/v2",
        rpc_urls=("https://ethereum-rpc.publicnode.com",),
    ),
    Chain.BSC: EVMChainConfig(
        chain=Chain.BSC,
        chain_id=56,
        currency_symbol="BNB",
        explorer_name="bscscan",
        address_url="https://bscscan.com/address/",
        tx_url="https://bscscan.com/tx/",
        blockscout_base=None,          # confirmed 404
        rpc_urls=(
            "https://bsc-dataseed.binance.org",
            "https://bsc-rpc.publicnode.com",
        ),
        keyless_address_history=False,  # confirmed: no keyless provider
    ),
    Chain.POLYGON: EVMChainConfig(
        chain=Chain.POLYGON,
        chain_id=137,
        currency_symbol="POL",
        explorer_name="polygonscan",
        address_url="https://polygonscan.com/address/",
        tx_url="https://polygonscan.com/tx/",
        blockscout_base="https://polygon.blockscout.com/api/v2",
        rpc_urls=("https://polygon.drpc.org", "https://1rpc.io/matic"),
    ),
}

ETHERSCAN_V2_URL = "https://api.etherscan.io/v2/api"

#: The canonical EVM burn address. A mint shows up as a transfer whose counterparty
#: is 0x000…0, which is NOT a wallet and must never be walked into or counted as
#: a funding source. It is kept on the transaction (the event really happened)
#: but excluded from the address graph.
BURN_ADDRESS = "0x0000000000000000000000000000000000000000"

# ERC-20 Transfer(address,address,uint256) topic. Used to read token transfers
# straight off the chain when no explorer index is available.
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


def get_config(chain: Chain) -> EVMChainConfig:
    return _EVM_CHAIN_CONFIG[chain]


# ============================================================
# NORMALIZATION HELPERS
# ============================================================


def _party(value: Any) -> Optional[str]:
    """Blockscout embeds a party as an object; Etherscan uses a flat hash."""
    if isinstance(value, dict):
        return value.get("hash") or value.get("address")
    if isinstance(value, str) and value:
        return value
    return None


def _wei_to_native(wei: Any) -> Optional[float]:
    if wei in (None, ""):
        return None
    try:
        return int(wei) / 10**18
    except (ValueError, TypeError, OverflowError):
        return None


def _int(value: Any) -> Optional[int]:
    """
    Best-effort integer parse, including hex and ISO-8601 timestamps.

    Providers are inconsistent about types: Etherscan sends timestamps as
    decimal strings, Blockscout sends ISO-8601 with microseconds, and JSON-RPC
    returns hex. All three must land in the same int-seconds field, and a value
    that cannot be parsed becomes None -- never a guess.
    """
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("0x") or text.startswith("0X"):
            try:
                return int(text, 16)
            except ValueError:
                return None
        try:
            return int(text)
        except ValueError:
            pass
        return _iso_to_epoch(text)
    if isinstance(value, float):
        return int(value)
    return None


def _iso_to_epoch(text: str) -> Optional[int]:
    """Blockscout timestamps are ISO-8601; normalize to integer epoch seconds."""
    candidate = text.replace("Z", "+00:00")
    for parser in (datetime.fromisoformat,):
        try:
            parsed = parser(candidate)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp())
    return None


class EVMAdapter(ChainAdapter):
    """Ethereum-family tracing over Blockscout, with Etherscan V2 when keyed."""

    def __init__(self, chain: Chain) -> None:
        if chain not in _EVM_CHAIN_CONFIG:
            raise ValueError(f"{chain} is not an EVM chain")
        self.chain = chain
        self.config = _EVM_CHAIN_CONFIG[chain]

    # --------------------------------------------------------
    # identity
    # --------------------------------------------------------

    def validate_address(self, address: str) -> bool:
        return validate_evm_address(address)[0]

    def validate_transaction_hash(self, tx_hash: str) -> bool:
        candidate = (tx_hash or "").strip()
        return candidate.startswith("0x") and len(candidate) == 66

    def explorer_url(self, value: str, input_type: str = "address") -> Optional[str]:
        if not value:
            return None
        if input_type == "transaction":
            return f"{self.config.tx_url}{value}"
        return f"{self.config.address_url}{value}"

    def capabilities(self) -> List[str]:
        caps = [
            "address_validation",
            "transaction_lookup",
            "network_status",
            "evm_semantics",
        ]
        if self._address_history_available():
            caps += ["outgoing_transfers", "incoming_transfers", "entity_labels"]
        return caps

    def _address_history_available(self) -> bool:
        from config import ETHERSCAN_API_KEY
        if ETHERSCAN_API_KEY:
            return True
        return self.config.keyless_address_history and self.config.blockscout_base is not None

    def unavailable_reason(self) -> Optional[str]:
        """Why address history is missing, in words a user can act on."""
        if self._address_history_available():
            return None
        return (
            f"No keyless transaction-history provider for {self.config.chain.display_name}. "
            f"Public RPC nodes cannot index an address without an archival node. "
            f"Set ETHERSCAN_API_KEY (and a plan covering chain {self.config.chain_id}) "
            f"to enable tracing on this network."
        )

    # --------------------------------------------------------
    # provider access
    # --------------------------------------------------------

    def _blockscout(self, client: HttpClient, path: str, params: Optional[Dict] = None):
        if not self.config.blockscout_base:
            return None
        return client.get_json(
            f"{self.config.blockscout_base}{path}",
            params=params,
            provider=f"blockscout-{self.chain.value}",
        )

    def _etherscan(
        self, client: HttpClient, action: str, params: Optional[Dict] = None,
    ):
        """
        Etherscan V2. Serves all three EVM chains from one key.

        Etherscan answers HTTP 200 with `status: "0"` for application-level
        errors, so `ok` alone is not enough — the payload is checked too.
        """
        from config import ETHERSCAN_API_KEY

        if not ETHERSCAN_API_KEY:
            return None

        query = {
            "chainid": self.config.chain_id,
            "module": "account",
            "action": action,
            **(params or {}),
            "apikey": ETHERSCAN_API_KEY,
        }
        return client.get_json(
            ETHERSCAN_V2_URL, params=query, provider="etherscan-v2",
        )

    def _rpc(
        self, client: HttpClient, method: str, params: Optional[List] = None,
    ) -> Optional[Any]:
        """
        Public JSON-RPC with a fallback URL.

        Public dataseed nodes only keep recent state: `eth_getCode` and
        `eth_blockNumber` work, but historical state at an old block will not.
        Nothing here depends on archival access.
        """
        body = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or [],
            "id": 1,
        }

        for index, url in enumerate(self.config.rpc_urls):
            result = client.post_json(
                url, body=body,
                provider=f"rpc-{self.chain.value}-{index}",
                # Live chain height. Caching it would serve a stale tip as
                # though it were current.
                use_cache=False,
            )
            if result.ok and isinstance(result.data, dict) and "result" in result.data:
                return result.data["result"]
        return None

    # --------------------------------------------------------
    # transaction retrieval
    # --------------------------------------------------------

    def _native_from_blockscout(self, item: Dict[str, Any], subject: str) -> Optional[BlockchainTransaction]:
        """
        Normalize a Blockscout transaction item — but only if it is one.

        `.../transactions` does not return only transfers. It returns every
        transaction the address touched, and most of them on a busy contract
        are contract CALLS that moved no currency at all. Verified live against
        eth.blockscout.com: a trace of a well-known address returned records
        with `type: 2` (contract call), `value: "0"`, `token_transfers: []` and
        calldata that decodes to plain ASCII messages ("!AAA! ! open to all
        bounty", "setContenthash"). None of those transferred ETH.

        Drawing a value edge for them is the same defect seen on TRON, where a
        TriggerSmartContract's `toAddress` is the token contract rather than a
        recipient: the graph would assert a payment that never happened, and a
        `large_transfer` indicator would even be scored against 0.0. This is
        traceable to "moved value" nodes on the subject's behalf, so a call is
        not that.

        Two ways a record qualifies as real value movement:
          native value > 0        a direct transfer
          token_transfers present an ERC-20 hop inside the same transaction

        A genuine self-send of 0 (donation to self, contract deploy funding) is
        still dropped here, and correctly: it moved nothing either.
        """
        sender = _party(item.get("from"))
        recipient = _party(item.get("to"))
        tx_hash = item.get("hash")

        if not (sender and recipient and tx_hash):
            return None

        value = _wei_to_native(item.get("value"))
        fee_wei = item.get("fee") or item.get("transaction_burnt_fee")
        fee_native = _wei_to_native(fee_wei)

        # Etherscan reports fees in gas units; Blockscout does not always.
        if fee_native is None and item.get("gas_used") and item.get("gas_price"):
            try:
                fee_native = int(item["gas_used"]) * int(item["gas_price"]) / 10**18
            except (ValueError, TypeError):
                fee_native = None

        # A call that moved nothing is not a transfer. A transaction that
        # carries token transfers IS value movement for this address, so it
        # stays even when its native value is zero.
        is_call = _int(item.get("type")) == 2
        has_token_transfers = bool(item.get("token_transfers"))
        if is_call and not (value or 0) > 0 and not has_token_transfers:
            return None

        lower_subject = (subject or "").lower()
        self_transfer = sender.lower() == lower_subject == recipient.lower()

        return BlockchainTransaction(
            chain=self.chain,
            hash=tx_hash,
            # A block number is not a timestamp. Blockscout omits `timestamp` on
            # some list views, and the honest answer there is no timestamp, not
            # a back-filled guess from the block height.
            timestamp=_int(item.get("timestamp")),
            from_address=sender,
            to_address=recipient,
            asset=self.config.currency_symbol,
            amount=value,
            decimals=18,
            raw_amount=item.get("value"),
            direction=Direction.SELF if self_transfer else (
                Direction.OUTGOING if sender.lower() == lower_subject else Direction.INCOMING
            ),
            block_number=_int(item.get("block_number")),
            status=item.get("result") or item.get("status") or "unknown",
            fee=fee_native,
            confirmations=_int(item.get("confirmations")),
            provider=f"blockscout-{self.chain.value}",
            raw=item,
        )

    def _token_from_blockscout(self, item: Dict[str, Any], subject: str) -> Optional[BlockchainTransaction]:
        """
        Normalize a Blockscout token-transfer item.

        Field names here are non-obvious and were verified against the live API,
        not assumed:

          transaction_hash  the tx id (NOT `tx_hash` -- reading the wrong key
                            silently dropped every ERC-20 transfer, since a
                            missing hash made the whole record unparseable)
          total             a nested object, not a number: {value, decimals}
          token             carries symbol/name/decimals inline for list views,
                            under `token_info` on some deployments
          to == 0x0…0     a burn. The zero address is a real destination and is
                            preserved as-is; it is not an error to drop.
        """
        token = item.get("token") or {}
        token_info = token.get("token_info") or token.get("tokenInfo") or {}

        # `total` is {value, decimals}; the value lives under "value".
        total = item.get("total")
        if isinstance(total, dict):
            raw_amount = total.get("value")
            decimals = _int(total.get("decimals"))
        else:
            raw_amount = total if total is not None else item.get("value")
            decimals = None

        if decimals is None:
            decimals = _int(token_info.get("decimals") or token.get("decimals"))
        symbol = token_info.get("symbol") or token.get("symbol")
        if symbol is None and decimals is None:
            # An NFT or an unidentified token with no decimals: there is no
            # meaningful fiat-denominated amount, so it is not a value transfer
            # and is left out of the value graph.
            return None

        sender = _party(item.get("from"))
        recipient = _party(item.get("to"))
        tx_hash = (
            item.get("transaction_hash")
            or item.get("tx_hash")
            or (item.get("transaction") or {}).get("hash")
        )

        if not (sender and recipient and tx_hash and raw_amount is not None):
            return None

        amount: Optional[float] = None
        if decimals is not None:
            try:
                amount = int(raw_amount) / (10**decimals)
            except (ValueError, TypeError, OverflowError):
                amount = None

        lower_subject = (subject or "").lower()
        self_transfer = sender.lower() == lower_subject == recipient.lower()

        return BlockchainTransaction(
            chain=self.chain,
            hash=tx_hash,
            timestamp=_int(item.get("timestamp")),
            from_address=sender,
            to_address=recipient,
            asset=symbol,
            token_contract=token.get("address_hash") or token.get("address") or _party(token),
            amount=amount,
            decimals=decimals,
            raw_amount=str(raw_amount),
            direction=Direction.SELF if self_transfer else (
                Direction.OUTGOING if sender.lower() == lower_subject else Direction.INCOMING
            ),
            block_number=_int(item.get("block_number")),
            status="success",
            provider=f"blockscout-{self.chain.value}",
            raw=item,
        )

    def _from_etherscan(
        self, record: Dict[str, Any], subject: str, native: bool,
    ) -> Optional[BlockchainTransaction]:
        sender = record.get("from")
        recipient = record.get("to")
        tx_hash = record.get("hash")

        if not (sender and recipient and tx_hash):
            return None

        lower_subject = (subject or "").lower()
        self_transfer = sender.lower() == lower_subject == recipient.lower()

        if native:
            asset = self.config.currency_symbol
            decimals: Optional[int] = 18
            contract = None
            amount = _wei_to_native(record.get("value"))
            raw_amount = record.get("value")
        else:
            asset = record.get("tokenSymbol")
            decimals = _int(record.get("tokenDecimal"))
            contract = record.get("contractAddress")
            raw_amount = record.get("value")
            amount = None
            if decimals is not None and raw_amount is not None:
                try:
                    amount = int(raw_amount) / (10**decimals)
                except (ValueError, TypeError, OverflowError):
                    amount = None

        return BlockchainTransaction(
            chain=self.chain,
            hash=tx_hash,
            timestamp=_int(record.get("timeStamp")),
            from_address=sender,
            to_address=recipient,
            asset=asset,
            token_contract=contract,
            amount=amount,
            decimals=decimals,
            raw_amount=None if raw_amount is None else str(raw_amount),
            direction=Direction.SELF if self_transfer else (
                Direction.OUTGOING if sender.lower() == lower_subject else Direction.INCOMING
            ),
            block_number=_int(record.get("blockNumber")),
            status="success" if record.get("isError") == "0" else "failed",
            fee=_wei_to_native(
                _int(record.get("gasUsed")) * _int(record.get("gasPrice"))
                if record.get("gasUsed") and record.get("gasPrice") else None
            ),
            confirmations=_int(record.get("confirmations")),
            provider="etherscan-v2",
            raw=record,
        )

    def get_outgoing_transfers(
        self, address: str, client: HttpClient, limit: int = 10,
    ) -> List[BlockchainTransaction]:
        return self._address_transfers(address, client, limit, incoming=False)

    def get_incoming_transfers(
        self, address: str, client: HttpClient, limit: int = 10,
    ) -> List[BlockchainTransaction]:
        return self._address_transfers(address, client, limit, incoming=True)

    def _address_transfers(
        self, address: str, client: HttpClient, limit: int, incoming: bool,
    ) -> List[BlockchainTransaction]:
        """
        Native + token transfers in one direction, newest first.

        Returns [] when no provider exists for this chain. Callers must consult
        `unavailable_reason()` to distinguish "no history" from "cannot look".
        """
        if not self._address_history_available():
            return []

        # --- Etherscan V2 (keyed; the only route to BSC) --------------------
        if self.config.blockscout_base is None:
            return self._etherscan_transfers(address, client, limit, incoming)

        return self._blockscout_transfers(address, client, limit, incoming)

    def _blockscout_transfers(
        self, address: str, client: HttpClient, limit: int, incoming: bool,
    ) -> List[BlockchainTransaction]:
        direction = "to" if incoming else "from"
        results: List[BlockchainTransaction] = []

        # Token transfers: a native-only view misses almost all real activity
        # on these chains, since most value moves as ERC-20.
        token_result = self._blockscout(
            client, f"/addresses/{address}/token-transfers",
            {"filter": direction},
        )
        if token_result.ok and isinstance(token_result.data, dict):
            for item in (token_result.data.get("items") or []):
                tx = self._token_from_blockscout(item, address)
                if tx:
                    results.append(tx)

        native_result = self._blockscout(
            client, f"/addresses/{address}/transactions",
            {"filter": direction},
        )
        if native_result.ok and isinstance(native_result.data, dict):
            for item in (native_result.data.get("items") or []):
                tx = self._native_from_blockscout(item, address)
                if tx:
                    results.append(tx)

        return _dedupe(results)[:limit]

    def _etherscan_transfers(
        self, address: str, client: HttpClient, limit: int, incoming: bool,
    ) -> List[BlockchainTransaction]:
        results: List[BlockchainTransaction] = []

        for action, native in (("tokentx", False), ("txlist", True)):
            result = self._etherscan(client, action, {
                "address": address,
                "page": 1,
                "offset": limit,
                "sort": "desc",
            })
            if not result.ok or not isinstance(result.data, dict):
                continue
            if str(result.data.get("status")) != "1":
                continue
            for record in (result.data.get("result") or []):
                tx = self._from_etherscan(record, address, native)
                if tx:
                    results.append(tx)

        return _dedupe(results)[:limit]

    def get_transaction(
        self, tx_hash: str, client: HttpClient,
    ) -> Optional[BlockchainTransaction]:
        if self.config.blockscout_base:
            result = self._blockscout(client, f"/transactions/{tx_hash}")
            if result.ok and isinstance(result.data, dict) and result.data.get("hash"):
                tx = self._native_from_blockscout(
                    result.data, _party(result.data.get("from")) or "",
                )
                if tx:
                    tx.timestamp = _int(result.data.get("timestamp"))
                    return tx

        from config import ETHERSCAN_API_KEY

        if ETHERSCAN_API_KEY:
            result = self._etherscan(client, "txlist", {"txid": tx_hash})
            if result.ok and isinstance(result.data, dict) and str(result.data.get("status")) == "1":
                records = result.data.get("result") or []
                if records:
                    return self._from_etherscan(records[0], "", native=True)

        return None

    # --------------------------------------------------------
    # network
    # --------------------------------------------------------

    def get_network_status(self, client: HttpClient) -> NetworkInfo:
        result = self._blockscout(client, "/stats")
        block_number = None
        block_hash = None

        if result and result.ok and isinstance(result.data, dict):
            block_number = _int(result.data.get("total_blocks"))
            block_hash = result.data.get("hash") or None
            provider = f"blockscout-{self.chain.value}"
        else:
            provider = f"rpc-{self.chain.value}"

        if block_number is None:
            raw = self._rpc(client, "eth_blockNumber")
            block_number = _int(raw)

        if block_number is None:
            return NetworkInfo(
                chain=self.chain,
                status="unavailable",
                provider=provider,
                availability=Availability.UNAVAILABLE,
                unavailable_reason="No public RPC node responded for this network.",
            )

        return NetworkInfo(
            chain=self.chain,
            status="ok",
            latest_block=block_number,
            latest_block_hash=block_hash,
            provider=provider,
            availability=Availability.AVAILABLE,
            extra={
                "chain_id": self.config.chain_id,
                "native_asset": self.config.currency_symbol,
                "address_history": self._address_history_available(),
                "address_history_unavailable_reason": self.unavailable_reason(),
            },
        )

    def get_network_metrics(self, client: HttpClient) -> Dict[str, Any]:
        """
        Only what a provider actually reports.

        Block time is a chain constant, not a live measurement, and is labelled
        as such. TPS is not derivable from a single `eth_blockNumber` call and
        is reported as not provided rather than estimated.
        """
        return {
            "chain_id": self.config.chain_id,
            "native_asset": self.config.currency_symbol,
            "tps": None,
            "tps_availability": Availability.NOT_PROVIDED,
            "average_block_time_seconds": {
                Chain.ETHEREUM: 12.0,
                Chain.BSC: 0.75,
                Chain.POLYGON: 2.0,
            }[self.chain],
            "average_block_time_basis": "chain constant, not a live measurement",
        }

    # --------------------------------------------------------
    # entity intelligence
    # --------------------------------------------------------

    def probe_activity(self, address: str, client: HttpClient) -> Dict[str, Any]:
        """
        Has this address ever been used on *this* EVM network?

        A 0x address is valid on Ethereum, BSC and Polygon simultaneously, so
        the format proves nothing and the only way to resolve it is to ask each
        network's own indexer. This is one cheap request per chain.

        Blockscout's `/addresses/{address}` answers 200 for an address it has
        seen and 404 for one it has not, so the 404 is a genuine negative. The
        200 body carries boolean evidence flags rather than counters -- there is
        no `tx_count` on this endpoint -- so activity is read from those.

        If the body does not contain a single one of the fields below, the shape
        is not one this code understands, and the answer is `unavailable`. That
        matters more than it looks: reading absent fields as zeroes once made a
        heavily used address look like an empty chain, which is precisely the
        false all-clear that must never happen.
        """
        chain = self.chain.value

        if self.config.blockscout_base:
            result = self._blockscout(client, f"/addresses/{address}")
            if result is None:
                return {"chain": chain, "status": "unavailable", "detail": None}
            if not result.ok:
                # 404 here means the indexer has never heard of the address,
                # which is a real negative rather than an outage.
                status = "no_activity" if result.status_code == 404 else "unavailable"
                return {"chain": chain, "status": status, "detail": None}

            payload = result.data
            if not isinstance(payload, dict):
                return {"chain": chain, "status": "unavailable", "detail": None}

            signals = (
                "has_token_transfers",
                "has_tokens",
                "has_logs",
                "is_contract",
                "coin_balance",
            )
            if not any(k in payload for k in signals):
                return {
                    "chain": chain,
                    "status": "unavailable",
                    "detail": "indexer response shape not recognised",
                }

            token_transfers = bool(payload.get("has_token_transfers"))
            holds_tokens = bool(payload.get("has_tokens"))
            is_contract = bool(payload.get("is_contract"))
            balance = _int(payload.get("coin_balance")) or 0
            activity = token_transfers or holds_tokens or is_contract or balance > 0

            reasons = []
            if token_transfers:
                reasons.append("token transfers")
            if holds_tokens:
                reasons.append("token holdings")
            if is_contract:
                reasons.append("contract")
            if balance > 0:
                reasons.append("native balance")

            return {
                "chain": chain,
                "status": "activity" if activity else "no_activity",
                "detail": ("Blockscout reports " + ", ".join(reasons)) if reasons else "no activity reported by Blockscout",
            }

        result = self._etherscan(client, "txlist", {"startblock": 0, "endblock": 99999999, "page": 1, "offset": 1, "sort": "desc"})
        if result is None:
            return {
                "chain": chain,
                "status": "unavailable",
                "detail": "no indexer configured for this network",
            }
        if not result.ok:
            status = "no_activity" if result.status_code == 404 else "unavailable"
            return {"chain": chain, "status": status, "detail": None}

        payload = result.data
        rows = payload if isinstance(payload, list) else (payload or {}).get("result")
        if not isinstance(rows, list):
            return {"chain": chain, "status": "unavailable", "detail": None}

        return {
            "chain": chain,
            "status": "activity" if rows else "no_activity",
            "detail": "reported by Etherscan",
        }

    def get_address_label(
        self, address: str, client: HttpClient,
    ) -> Optional[EntityAttribution]:
        """
        Blockscout address metadata: ENS name, contract name, public tags.

        These are provider annotations. They are recorded as PUBLIC_PROVIDER and
        never upgraded to verified, because a block explorer label is a claim by
        that explorer, not an independent confirmation.
        """
        if not self.config.blockscout_base:
            return resolve_entity(
                address, self.chain.value, source_url=self.explorer_url(address),
            )

        result = self._blockscout(client, f"/addresses/{address}")
        if not result.ok or not isinstance(result.data, dict):
            return resolve_entity(
                address, self.chain.value, source_url=self.explorer_url(address),
            )

        payload = result.data

        # A curated record outranks anything the explorer says.
        curated = resolve_entity(
            address, self.chain.value, source_url=self.explorer_url(address),
        )
        if curated and curated.source_type == AttributionSource.CURATED_VERIFIED:
            return curated

        name = payload.get("name") or payload.get("ens_domain_name")
        is_contract = bool(payload.get("is_contract"))
        verified = bool(payload.get("is_verified"))

        evidence: List[str] = []
        if payload.get("ens_domain_name"):
            evidence.append(f"ENS domain: {payload['ens_domain_name']}")
        if name:
            evidence.append(f"Explorer contract name: {name}")
        if is_contract:
            evidence.append("Address is a deployed contract.")
        if verified:
            evidence.append("Source code is verified on the explorer.")

        tag_texts: List[str] = []
        for tag_source in (payload.get("public_tags"), payload.get("private_tags")):
            for tag in tag_source or []:
                if isinstance(tag, dict) and tag.get("label"):
                    tag_texts.append(tag["label"])
        if tag_texts:
            evidence.append(f"Explorer tags: {', '.join(sorted(set(tag_texts)))}")

        if not evidence:
            # Nothing known. Returning None is the honest answer; an empty
            # attribution object with a 0 confidence would be indistinguishable
            # from a label that simply had no text.
            return curated

        entity_type = classify_public_label(name) or (
            EntityType.SERVICE if is_contract else EntityType.UNKNOWN
        )
        if tag_texts:
            entity_type = classify_public_label(" ".join(tag_texts)) or entity_type

        return EntityAttribution(
            name=name or (tag_texts[0] if tag_texts else None),
            type=entity_type,
            source_type=AttributionSource.PUBLIC_PROVIDER,
            # A verified contract with a public tag is the strongest signal
            # available without a curated record; an unnamed EOA is the weakest.
            confidence=70 if (is_contract and verified) else 40,
            evidence=evidence,
            source_url=self.explorer_url(address),
            verification_status=VerificationStatus.UNVERIFIED,
            notes="Explorer-provided metadata. Not independently verified by BlockTrace.",
        )

    # --------------------------------------------------------
    # tracing
    # --------------------------------------------------------

    def trace(
        self,
        seed: str,
        client: HttpClient,
        max_depth: int = 3,
        max_nodes: int = 25,
        max_txs_per_node: int = 5,
        deadline: Optional[float] = None,
    ) -> AdapterTrace:
        """
        Same bounded breadth-first traversal as every other adapter.

        The engine above this method is identical across chains; only the
        provider calls underneath differ. That is the whole point of the
        interface — adding a chain must not require touching this loop's
        callers.
        """
        if deadline is None:
            deadline = time.monotonic() + 60.0

        result = AdapterTrace(chain=self.chain, seed=seed)

        if not self._address_history_available():
            result.status = TraceStatus.INCONCLUSIVE
            result.status_detail = self.unavailable_reason()
            result.notes.append(
                f"Network status for {self.config.chain.display_name} is still "
                f"available; only address history requires a key."
            )
            return result

        seed_node = result.add_node(TraceNode(
            address=seed, chain=self.chain, depth=0, is_seed=True,
        ))
        seed_label = self.get_address_label(seed, client)
        if seed_label:
            seed_node.entity = seed_label
            seed_node.entity_type = seed_label.type
            seed_node.source_type = seed_label.source_type
            seed_node.confidence = seed_label.confidence
            seed_node.evidence = list(seed_label.evidence)

        # (address, depth, timestamp of the edge that reached it)
        queue: List[Tuple[str, int, Optional[int]]] = [(seed, 0, None)]
        visited = {seed.lower()}
        matched: Optional[EntityAttribution] = None
        provider_failures = 0

        while queue:
            if time.monotonic() >= deadline:
                result.status = TraceStatus.TIMEOUT
                result.status_detail = (
                    "Tracing stopped at the configured time budget after "
                    f"examining {result.nodes_examined} address(es)."
                )
                result.truncated = True
                result.truncation_reasons.append("deadline_reached")
                break

            address, depth, _reached_at = queue.pop(0)
            result.nodes_examined += 1
            result.max_depth_reached = max(result.max_depth_reached, depth)

            txs = self.get_address_activity(address, client, max_txs_per_node)
            if not txs:
                provider_failures += 1

            current = result.add_node(TraceNode(
                address=address, chain=self.chain, depth=depth,
                is_seed=(address == seed),
            ))

            for tx in txs:
                result.transactions.append(tx)
                result.transactions_inspected += 1
                result.edges.append(TraceEdge(
                    transaction_hash=tx.hash,
                    from_address=tx.from_address,
                    to_address=tx.to_address,
                    chain=tx.chain,
                    asset=tx.asset,
                    amount=tx.amount,
                    timestamp=tx.timestamp,
                    token_contract=tx.token_contract,
                ))

                for party, key in ((tx.from_address, "from"), (tx.to_address, "to")):
                    if not party:
                        continue
                    # A mint or burn has a zero counterparty. It is real on the
                    # transaction but is not an address to route funds onward
                    # from, so it is not counted or enqueued as a node.
                    if party.lower() == BURN_ADDRESS:
                        continue
                    target = next(
                        (n for n in result.nodes if n.address.lower() == party.lower()),
                        None,
                    ) or result.add_node(TraceNode(
                        address=party, chain=self.chain, depth=depth + 1,
                    ))
                    if key == "from":
                        target.outbound += 1
                    else:
                        target.inbound += 1

            label = self.get_address_label(address, client)
            if label:
                current.entity = label
                current.entity_type = label.type
                current.source_type = label.source_type
                current.confidence = label.confidence
                current.evidence = list(label.evidence)
                if matched is None or (
                    label.source_type == AttributionSource.CURATED_VERIFIED
                    and matched.source_type != AttributionSource.CURATED_VERIFIED
                ):
                    matched = label

            if depth + 1 >= max_depth:
                if txs:
                    result.truncated = True
                    result.truncation_reasons.append(
                        f"max_depth ({max_depth}) reached at {address}"
                    )
                continue

            if len(result.nodes) >= max_nodes:
                result.truncated = True
                result.truncation_reasons.append(f"max_nodes ({max_nodes}) reached")
                continue

            neighbours = sorted({
                party.lower(): party
                for tx in txs for party in (tx.from_address, tx.to_address)
                if party and party.lower() != address.lower()
                and party.lower() != BURN_ADDRESS
            }.values())

            for party in neighbours:
                if party.lower() in visited:
                    continue
                if len(result.nodes) + len(queue) >= max_nodes:
                    result.truncated = True
                    result.truncation_reasons.append(
                        f"max_nodes ({max_nodes}) reached; "
                        f"{len(neighbours)} candidate address(es) not examined"
                    )
                    break
                visited.add(party.lower())
                party_tx = next(
                    (t for t in txs if party.lower() in (
                        (t.from_address or "").lower(), (t.to_address or "").lower(),
                    )),
                    None,
                )
                queue.append((party, depth + 1, party_tx.timestamp if party_tx else None))

        result.hops = result.max_depth_reached
        # The seed alone until an entity is reached; the orchestrator computes
        # the real path once it owns the graph.
        result.hop_path = [seed]

        # A "match" means a KNOWN ENTITY was reached, not that an explorer
        # carries a label. An ENS name or a public tag is PUBLIC_PROVIDER --
        # the same tier as a keyword guess -- and calling it a match would tell
        # an analyst an entity was identified on one explorer's say-so. Only a
        # curated, verified record earns that word.
        is_verified_match = (
            matched is not None
            and matched.source_type == AttributionSource.CURATED_VERIFIED
        )
        label_caveat = (
            f" A public provider label was seen for {matched.name}; it is "
            "recorded on that node but is not a confirmed match."
            if matched is not None and not is_verified_match else ""
        )

        if provider_failures and provider_failures == result.nodes_examined:
            result.status = TraceStatus.PROVIDER_ERROR
            result.status_detail = (
                "Every provider request failed or returned nothing. This is a "
                "provider problem, not a finding about the address."
            )
        elif is_verified_match:
            result.status = TraceStatus.MATCHED
        elif result.truncated and result.transactions:
            result.status = TraceStatus.PARTIAL
            result.status_detail = (
                "The trace stopped early. Results cover only the addresses that "
                f"were actually examined.{label_caveat}"
            )
        elif result.transactions:
            result.status = TraceStatus.NO_MATCH
            result.status_detail = (
                "Traced successfully, but no curated, verified entity was "
                f"reached within the examined hops.{label_caveat}"
            )
        else:
            result.status = TraceStatus.NO_MATCH
            result.status_detail = "The address returned no transaction history."

        return result


def _dedupe(txs: List[BlockchainTransaction]) -> List[BlockchainTransaction]:
    """
    Deduplicate and order newest-first.

    Sorting falls back to block height when a provider gives no timestamp.
    Etherscan's token-transfer list omits `timeStamp`, and sorting those on 0
    would leave them in provider order rather than newest-first.
    """
    seen = set()
    unique = []
    for tx in txs:
        key = (tx.hash, tx.from_address, tx.to_address, tx.asset, tx.raw_amount)
        if key in seen:
            continue
        seen.add(key)
        unique.append(tx)
    return sorted(
        unique,
        key=lambda t: (t.timestamp or 0, t.block_number or 0),
        reverse=True,
    )
