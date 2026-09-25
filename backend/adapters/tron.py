"""
TRON chain adapter.

Refactors the logic that previously lived in `trace.py` onto the `ChainAdapter`
interface. The provider-fallback order, the TRC-20/TRX amount handling and the
TRON Base58Check validation are preserved; the traversal is rewritten as an
explicit breadth-first work queue so the documented limits are real limits
rather than the advisory ones they were before.

Two defects in the previous traversal are fixed here, not carried forward:

*   The TRX loop had no deadline check. The TRC-20 loop checked; the TRX loop
    did not, so a trace could run past its own advertised timeout.
*   Incoming transfers were fetched but only for fan-in counting, and TronGrid
    was always queried with `only_from=true`. Both directions are now real
    traversal edges.

Provider order is unchanged: TronScan when `TRONSCAN_API_KEY` is present,
TronGrid otherwise or when TronScan fails. Nothing here invents a value -- an
absent amount is None, not 0.0.
"""

from __future__ import annotations

import hashlib
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from adapters.base import AdapterTrace, ChainAdapter, NetworkInfo
from models.schemas import (
    Availability,
    BlockchainTransaction,
    Chain,
    Direction,
    EntityAttribution,
    TraceNode,
    TraceEdge,
    TraceStatus,
)
from services.chain_detection import validate_tron_address, validate_tron_txid
from services.entity_service import resolve_entity
from utils.http_client import HttpClient

# ============================================================
# PROVIDER ENDPOINTS
# ============================================================

TRONSCAN_TX_URL = "https://apilist.tronscanapi.com/api/transaction"
TRONSCAN_TRC20_URL = "https://apilist.tronscanapi.com/api/token_trc20/transfers"
TRONSCAN_BASE_URL = "https://tronscan.org/#/address/"
TRONSCAN_TX_BASE_URL = "https://tronscan.org/#/transaction/"

TRONGRID_BASE_URL = "https://api.trongrid.io"
TRONGRID_TRX_URL = f"{TRONGRID_BASE_URL}/v1/accounts/{{address}}/transactions"
TRONGRID_TRC20_URL = f"{TRONGRID_BASE_URL}/v1/accounts/{{address}}/transactions/trc20"
TRONGRID_BLOCK_URL = f"{TRONGRID_BASE_URL}/wallet/getnowblock"

# Behavioural thresholds. These are heuristics, not facts about a wallet.
RAPID_HOP_SECONDS = 300
FAN_OUT_THRESHOLD = 3
FAN_IN_THRESHOLD = 3

SUN_PER_TRX = 1_000_000


# ============================================================
# EXTRACTION HELPERS
#
# Carried across from trace.py. These tolerate several provider field namings
# because TronScan and TronGrid genuinely disagree on casing and structure; that
# is a real difference between the two APIs, not guesswork.
# ============================================================


def _tronscan_headers() -> Dict[str, str]:
    from config import TRONSCAN_API_KEY
    return {"TRON-PRO-API-KEY": TRONSCAN_API_KEY} if TRONSCAN_API_KEY else {}


def _trongrid_headers() -> Dict[str, str]:
    from config import TRONGRID_API_KEY
    return {"TRON-PRO-API-KEY": TRONGRID_API_KEY} if TRONGRID_API_KEY else {}


def extract_timestamp(transaction: Any) -> Optional[int]:
    """
    Pull a unix-seconds timestamp out of a provider object.

    Handles unix seconds, unix milliseconds, numeric strings and ISO-8601,
    then recurses into nested objects. Returns None rather than guessing when
    no timestamp is present.
    """
    if not isinstance(transaction, dict):
        return None

    for field in (
        "timestamp", "block_timestamp", "blockTimestamp", "block_ts",
        "transactionTime", "transaction_time", "time", "datetime", "date",
        "created_at", "createdAt",
    ):
        value = transaction.get(field)
        if value is None or value == "":
            continue

        if isinstance(value, (int, float)):
            try:
                stamp = float(value)
                if stamp > 10_000_000_000:
                    stamp /= 1000
                if stamp > 0:
                    return int(stamp)
            except (ValueError, TypeError, OverflowError):
                continue

        if isinstance(value, str):
            cleaned = value.strip()
            if not cleaned:
                continue
            try:
                stamp = float(cleaned)
                if stamp > 10_000_000_000:
                    stamp /= 1000
                if stamp > 0:
                    return int(stamp)
            except (ValueError, TypeError, OverflowError):
                pass
            try:
                iso_value = cleaned[:-1] + "+00:00" if cleaned.endswith("Z") else cleaned
                return int(datetime.fromisoformat(iso_value).timestamp())
            except (ValueError, TypeError, OverflowError):
                pass

    for key in (
        "transaction", "transactionInfo", "trigger_info", "triggerInfo",
        "block", "block_info", "blockInfo",
    ):
        nested = transaction.get(key)
        if isinstance(nested, dict):
            found = extract_timestamp(nested)
            if found is not None:
                return found

    for value in transaction.values():
        if isinstance(value, dict):
            found = extract_timestamp(value)
            if found is not None:
                return found

    return None


def _first(transaction: Dict[str, Any], *keys) -> Optional[Any]:
    for key in keys:
        value = transaction.get(key)
        if value not in (None, ""):
            return value
    return None


#: TRON's Base58 alphabet, same as Bitcoin's — the two differ in the version
#: byte they encode, not in the encoding itself.
_B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _b58encode(raw: bytes) -> str:
    number = int.from_bytes(raw, "big")
    out = ""
    while number:
        number, remainder = divmod(number, 58)
        out = _B58_ALPHABET[remainder] + out
    pad = 0
    for byte in raw:
        if byte:
            break
        pad += 1
    return "1" * pad + out


def _hex_to_base58(value: str) -> Optional[str]:
    """
    TRON's 21-byte hex address (0x41 + 20 bytes) into its Base58Check form.

    TronGrid serves addresses as hex inside `raw_data`; every other TRON
    surface serves the same address as base58. Normalising to base58 at the
    adapter boundary is what lets the graph join the two — a trace that mixed
    the two encodings would show the same wallet as two unconnected nodes.
    Returns None on anything that is not decodable rather than guessing.
    """
    if not isinstance(value, str) or not value:
        return None

    text = value[2:] if value.lower().startswith("0x") else value
    if len(text) != 42:
        return None

    try:
        payload = bytes.fromhex(text)
    except ValueError:
        return None

    if len(payload) != 21 or payload[0] != 0x41:
        return None

    checksum = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    return _b58encode(payload + checksum)


def _tag_from(value: Any) -> Optional[str]:
    """TronScan nests a party tag either as a bare string or as a small object."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, dict):
        for key in ("from_address_tag", "to_address_tag", "name", "tag", "label"):
            inner = value.get(key)
            if isinstance(inner, str) and inner.strip():
                return inner.strip()
    return None


def extract_token_amount(transfer: Dict[str, Any]) -> Dict[str, Any]:
    """
    Symbol, decimals, raw integer amount and scaled amount from a TRC-20 record.

    `amount` is None when the provider gave no usable integer, and `raw_amount`
    keeps the provider's original string so a reader can re-scale it themselves.
    """
    token_info = transfer.get("tokenInfo")
    if not isinstance(token_info, dict):
        token_info = transfer.get("token_info")
    if not isinstance(token_info, dict):
        token_info = {}

    symbol = _first(token_info, "tokenAbbr", "tokenAbbrName", "symbol", "name")

    decimals = token_info.get("tokenDecimal")
    if decimals is None:
        decimals = token_info.get("decimals")

    raw_amount = None
    trigger_info = transfer.get("trigger_info")
    if isinstance(trigger_info, dict):
        parameter = trigger_info.get("parameter")
        if isinstance(parameter, dict):
            raw_amount = parameter.get("value")
    if raw_amount is None:
        raw_amount = _first(transfer, "quant", "value", "amount")

    amount: Optional[float] = None
    decimals_int: Optional[int] = None
    if raw_amount not in (None, ""):
        try:
            if decimals is not None:
                decimals_int = int(decimals)
                amount = int(raw_amount) / (10 ** decimals_int)
            else:
                amount = int(raw_amount)
        except (ValueError, TypeError, OverflowError):
            amount = None

    return {
        "token": symbol,
        "amount": amount,
        "raw_amount": None if raw_amount is None else str(raw_amount),
        "decimals": decimals_int,
    }


def calculate_rapid_hop(previous: Optional[int], current: Optional[int]) -> bool:
    """
    True when two transactions are within 5 minutes of each other.

    A behavioural heuristic. Two transfers 5 minutes apart is common for
    ordinary activity, so this is an INFO-level signal and never on its own a
    finding of wrongdoing.
    """
    if previous is None or current is None:
        return False
    return abs(current - previous) <= RAPID_HOP_SECONDS


# ============================================================
# ADAPTER
# ============================================================


class TronAdapter(ChainAdapter):
    """TRON via TronScan (keyed) with a TronGrid fallback."""

    chain = Chain.TRON

    def __init__(self) -> None:
        from config import TRONGRID_API_KEY, TRONSCAN_API_KEY
        self._tronscan_key = TRONSCAN_API_KEY
        self._trongrid_key = TRONGRID_API_KEY

    # --------------------------------------------------------
    # identity
    # --------------------------------------------------------

    def validate_address(self, address: str) -> bool:
        return validate_tron_address(address)[0]

    def validate_transaction_hash(self, tx_hash: str) -> bool:
        return validate_tron_txid(tx_hash)

    def explorer_url(self, value: str, input_type: str = "address") -> Optional[str]:
        if not value:
            return None
        base = TRONSCAN_TX_BASE_URL if input_type == "transaction" else TRONSCAN_BASE_URL
        return f"{base}{value}"

    def capabilities(self) -> List[str]:
        return [
            "address_validation",
            "transaction_lookup",
            "outgoing_transfers",
            "incoming_transfers",
            "network_status",
            "entity_labels",      # tags ride along with transfer records
            "behavioral_signals",  # rapid-hop, fan-in/out
        ]

    # --------------------------------------------------------
    # provider access
    # --------------------------------------------------------

    def _tronscan_get(self, client: HttpClient, url: str, params: Dict[str, Any]):
        if not self._tronscan_key:
            return None
        return client.get_json(
            url, params=params, headers=_tronscan_headers(), provider="tronscan",
        )

    def _trongrid_get(self, client: HttpClient, url: str, params: Dict[str, Any]):
        return client.get_json(
            url, params=params, headers=_trongrid_headers(), provider="trongrid",
        )

    # --------------------------------------------------------
    # transaction retrieval
    # --------------------------------------------------------

    def _to_transaction(
        self,
        record: Dict[str, Any],
        kind: str,
        provider: str,
        direction: Direction,
        subject: str,
    ) -> Optional[BlockchainTransaction]:
        """Map a normalized transfer record onto the shared transaction model."""
        if not isinstance(record, dict):
            return None

        from_address = _first(record, "from_address", "fromAddress", "from")
        to_address = _first(record, "to_address", "toAddress", "to")

        if not (from_address and to_address):
            return None

        # A contract call has a sender and a target but moves no native TRX
        # between them. Emitting it as a transfer would put a fabricated value
        # and a fabricated counterparty edge into the graph. The TRC-20 path
        # reports the actual token movement this call represents.
        if kind != "trc20" and record.get("is_native_transfer") is False:
            return None

        tx_hash = _first(
            record, "transaction_id", "transactionId", "txID", "txid", "hash",
        )
        if not tx_hash:
            return None

        subject_key = (subject or "").lower()
        self_transfer = from_address.lower() == subject_key == (to_address or "").lower()

        if kind == "trc20":
            token = extract_token_amount(record)
            asset = token["token"]
            amount = token["amount"]
            raw_amount = token["raw_amount"]
            decimals = token["decimals"]
            contract = record.get("contract_address") or (
                (record.get("tokenInfo") or {}).get("address")
                if isinstance(record.get("tokenInfo"), dict) else None
            )
        else:
            asset = "TRX"
            raw_amount = _first(record, "value", "amount")
            amount = None
            decimals = 0
            contract = None
            if raw_amount not in (None, ""):
                try:
                    amount = int(raw_amount) / SUN_PER_TRX
                except (ValueError, TypeError, OverflowError):
                    amount = None

        return BlockchainTransaction(
            chain=self.chain,
            hash=tx_hash,
            timestamp=extract_timestamp(record),
            from_address=from_address,
            to_address=to_address,
            asset=asset,
            token_contract=contract,
            amount=amount,
            decimals=decimals,
            raw_amount=None if raw_amount is None else str(raw_amount),
            direction=Direction.SELF if self_transfer else direction,
            block_number=_first(record, "block_number", "blockNumber", "block"),
            status="success" if record.get("confirmed", True) else "unknown",
            confirmations=None,
            provider=provider,
            raw=record,
        )

    def _fetch_trc20(
        self, address: str, client: HttpClient, limit: int, incoming: bool,
    ) -> Tuple[List[BlockchainTransaction], List[Dict[str, Any]], bool]:
        """
        TRC-20 transfers in one direction.

        Returns (transactions, raw records, provider_reached). The third value
        separates "the provider answered and this address has no history" from
        "the provider could not be reached" — the caller needs both to report
        an honest status.

        The raw records are kept because TronScan attaches the party tags
        there and a normalized model drops fields it does not model.
        """
        direction = Direction.INCOMING if incoming else Direction.OUTGOING

        # --- TronScan (keyed) ---------------------------------------------
        if self._tronscan_key:
            params: Dict[str, Any] = {"limit": limit, "sort": "-block_timestamp"}
            params["toAddress" if incoming else "fromAddress"] = address

            result = self._tronscan_get(client, TRONSCAN_TRC20_URL, params)

            if result.ok and isinstance(result.data, dict):
                records = result.data.get("token_transfers")
                if not isinstance(records, list):
                    records = result.data.get("data") or []
                if isinstance(records, list) and records:
                    txs = [
                        tx for tx in (
                            self._to_transaction(
                                record, "trc20", "tronscan", direction, address,
                            )
                            for record in records
                        ) if tx is not None
                    ]
                    return txs, records, True
                # An empty 200 is not proof the address is empty. TronScan
                # indexes transfers on its own schedule and can lag TronGrid,
                # and a plan without the right permission degrades to an
                # empty list rather than an error. Falling through to TronGrid
                # is the difference between "no token transfers" and "no token
                # transfers on this index".

        # --- TronGrid fallback --------------------------------------------
        params = {
            "limit": limit,
            "only_confirmed": "true",
            "order_by": "block_timestamp,desc",
            "only_to" if incoming else "only_from": "true",
        }
        result = self._trongrid_get(
            client, TRONGRID_TRC20_URL.format(address=address), params,
        )

        if not result.ok or not isinstance(result.data, dict):
            return [], [], False

        records = result.data.get("data") or []
        txs = [
            tx for tx in (
                self._to_transaction(
                    self._normalize_trongrid_trc20(record),
                    "trc20", "trongrid", direction, address,
                )
                for record in records if isinstance(record, dict)
            )
            if tx is not None
        ]
        return txs, records, True

    @staticmethod
    def _normalize_trongrid_trx(record: Dict[str, Any]) -> Dict[str, Any]:
        """
        TronGrid's native-TRX shape into the field names the model expects.

        Verified against `GET /v1/accounts/{a}/transactions`: the response has
        `txID` and `block_timestamp` at the top level, but **no** top-level
        `from`/`to` — those keys are present and null. The actual parties live
        inside `raw_data.contract[0].parameter.value`, keyed by contract type
        (`owner_address` for a TransferContract, `receiver_address` for a
        DelegateResourceContract, and so on) and encoded as **hex**, not base58.

        Reading only the top level makes every record look like a transfer with
        no counterparty, so the transaction is dropped and a busy account
        reports as empty. This is the silent-failure pattern again: no error,
        just less data that looks correct.
        """
        if not isinstance(record, dict):
            return record

        if record.get("from") and record.get("to"):
            return record

        contracts = (record.get("raw_data") or {}).get("contract")
        if not isinstance(contracts, list) or not contracts:
            return record

        value = (contracts[0].get("parameter") or {}).get("value")
        if not isinstance(value, dict):
            return record

        owner = value.get("owner_address")
        if not owner:
            return record

        # The counterparty key varies by contract type. Take the first party
        # that is present and is not the owner; for some contract types
        # (resource delegation) there is genuinely no counterparty transfer,
        # and the caller reports it as such rather than inventing one.
        party_keys = (
            "to_address", "receiver_address", "owner_address",
            "to_address_", "contract_address",
        )
        counterparty = None
        for key in party_keys:
            candidate = value.get(key)
            if candidate and candidate != owner:
                counterparty = candidate
                break

        normalized = dict(record)
        normalized["from_address"] = _hex_to_base58(owner)
        normalized["to_address"] = (
            _hex_to_base58(counterparty) if counterparty else None
        )
        normalized.setdefault("transaction_id", record.get("txID"))

        # Only TransferContract moves native TRX between two accounts. A
        # DelegateResource or TriggerSmartContract has an owner and a
        # receiver but no value transfer between them.
        contract_type = (contracts[0].get("type") or "").lower()
        normalized["is_native_transfer"] = contract_type == "transfercontract"
        if not normalized["is_native_transfer"]:
            # Keep the counterparty for reference, but do not let a resource
            # delegation masquerade as a payment.
            normalized["to_address"] = (
                normalized["to_address"] if contract_type == "transfercontract"
                else None
            )

        amount = value.get("amount")
        if amount is not None:
            normalized["value"] = amount
        return normalized

    @staticmethod
    def _normalize_tronscan_trx(record: Dict[str, Any]) -> Dict[str, Any]:
        """
        TronScan's native-transaction shape into the field names the model uses.

        Verified against `GET /api/transaction`: the sender is `ownerAddress`
        and the receiver is `toAddress`, neither of which any key in
        `_to_transaction` looks for. The value is `contractData.amount` (in
        SUN) and the hash is `hash`, not `txID`.

        `contractType` is load-bearing. Type 1 is a TransferContract and moves
        TRX. Type 31 is a TriggerSmartContract — a *call into* a token
        contract, whose `toAddress` is the token contract, not a recipient of
        funds. Treating a contract call as a TRX transfer would invent a
        counterparty and a value that never moved, so those are marked and the
        caller can exclude them. The TRC-20 path already reports the real token
        transfer that the call represents.
        """
        if not isinstance(record, dict):
            return record

        normalized = dict(record)
        normalized["from_address"] = record.get("ownerAddress")
        normalized["to_address"] = record.get("toAddress")
        normalized["transaction_id"] = record.get("hash") or record.get("txID")

        contract_data = record.get("contractData")
        if isinstance(contract_data, dict):
            normalized["value"] = contract_data.get("amount")
        if record.get("amount") not in (None, ""):
            normalized["value"] = record.get("amount")

        contract_type = record.get("contractType")
        normalized["contract_type"] = contract_type
        # Only a TransferContract (1) actually moves native TRX between two
        # accounts. Anything else is a contract invocation.
        normalized["is_native_transfer"] = contract_type == 1
        return normalized

    def _fetch_trx(
        self, address: str, client: HttpClient, limit: int, incoming: bool,
    ) -> Tuple[List[BlockchainTransaction], List[Dict[str, Any]], bool]:
        """
        Native TRX transfers in one direction.

        Returns (transactions, raw records, provider_reached) — see
        `_fetch_trc20` for why the third value exists.
        """
        direction = Direction.INCOMING if incoming else Direction.OUTGOING

        if self._tronscan_key:
            params = {
                "limit": limit,
                "sort": "-timestamp",
                "toAddress" if incoming else "fromAddress": address,
            }
            result = self._tronscan_get(client, TRONSCAN_TX_URL, params)

            if result.ok and isinstance(result.data, dict):
                records = result.data.get("data") or []
                if isinstance(records, list) and records:
                    txs = [
                        tx for tx in (
                            self._to_transaction(
                                self._normalize_tronscan_trx(record),
                                "trx", "tronscan", direction, address,
                            )
                            for record in records
                        )
                        if tx is not None
                    ]
                    return txs, records, True
                # Same rule as the TRC-20 path: a keyed provider answering 200
                # with an empty list is a weak negative, not a confirmed one.
                # TronGrid is the authority on whether an address moved funds.

        params = {
            "limit": limit,
            "only_confirmed": "true",
            "only_to" if incoming else "only_from": "true",
            "order_by": "block_timestamp,desc",
        }
        result = self._trongrid_get(
            client, TRONGRID_TRX_URL.format(address=address), params,
        )

        if not result.ok or not isinstance(result.data, dict):
            return [], [], False

        records = result.data.get("data") or []
        txs = [
            tx for tx in (
                self._to_transaction(
                    self._normalize_trongrid_trx(record),
                    "trx", "trongrid", direction, address,
                )
                for record in records if isinstance(record, dict)
            )
            if tx is not None
        ]
        return txs, records, True

    @staticmethod
    def _normalize_trongrid_trc20(transfer: Dict[str, Any]) -> Dict[str, Any]:
        """TronGrid's TRC-20 shape into TronScan's field names."""
        token_info = transfer.get("token_info")
        if not isinstance(token_info, dict):
            token_info = {}

        return {
            "from_address": _first(transfer, "from", "from_address", "fromAddress"),
            "to_address": _first(transfer, "to", "to_address", "toAddress"),
            "transaction_id": _first(transfer, "transaction_id", "txID", "hash"),
            "block_timestamp": transfer.get("block_timestamp"),
            "tokenInfo": {
                "symbol": _first(token_info, "symbol", "name", "tokenAbbr"),
                "decimals": _first(token_info, "decimals", "tokenDecimal"),
                "address": _first(token_info, "address", "contract_address"),
            },
            "value": _first(transfer, "value", "quant"),
            "contract_address": _first(
                token_info, "address", "contract_address",
            ) or transfer.get("contract_address"),
            "confirmed": transfer.get("confirmed", True),
        }

    def get_outgoing_transfers(
        self, address: str, client: HttpClient, limit: int = 10,
    ) -> List[BlockchainTransaction]:
        trc20, _, _ = self._fetch_trc20(address, client, limit, incoming=False)
        trx, _, _ = self._fetch_trx(address, client, limit, incoming=False)
        return _dedupe_and_sort(trc20 + trx)

    def get_incoming_transfers(
        self, address: str, client: HttpClient, limit: int = 10,
    ) -> List[BlockchainTransaction]:
        trc20, _, _ = self._fetch_trc20(address, client, limit, incoming=True)
        trx, _, _ = self._fetch_trx(address, client, limit, incoming=True)
        return _dedupe_and_sort(trc20 + trx)

    def get_transaction(
        self, tx_hash: str, client: HttpClient,
    ) -> Optional[BlockchainTransaction]:
        """
        One transaction by hash.

        TronGrid's v1 transaction-info endpoint is the only keyless route to a
        single TRON transaction, so it is used directly rather than by scanning
        an address.
        """
        result = client.get_json(
            f"{TRONGRID_BASE_URL}/v1/transactions/{tx_hash}",
            headers=_trongrid_headers(),
            provider="trongrid",
        )

        if not result.ok or not isinstance(result.data, dict):
            return None

        payload = result.data.get("data") or []
        if not payload:
            return None

        record = payload[0]
        raw_contract = record.get("raw_data") or {}
        contract = raw_contract.get("contract") or []

        # A plain TRX transfer is type TransferContract. Anything else
        # (TriggerSmartContract and friends) is a contract call, not a value
        # transfer, so it must not be reported as one.
        transfer_contract = contract[0] if contract else {}
        params = transfer_contract.get("parameter") or {}
        value = transfer_contract.get("parameter", {}).get("value") or {}

        if transfer_contract.get("type") != "TransferContract":
            return BlockchainTransaction(
                chain=self.chain,
                hash=tx_hash,
                timestamp=record.get("block_timestamp"),
                from_address=None,
                to_address=None,
                asset=None,
                amount=None,
                status="success" if record.get("confirmed", True) else "unknown",
                provider="trongrid",
                raw=record,
                # A contract call is a transaction but not a transfer; saying so
                # is more honest than omitting it.
                direction=Direction.SELF,
            )

        return BlockchainTransaction(
            chain=self.chain,
            hash=tx_hash,
            timestamp=record.get("block_timestamp"),
            from_address=_first(value, "from_address", "fromAddress"),
            to_address=_first(value, "to_address", "toAddress"),
            asset="TRX",
            amount=(int(value["amount"]) / SUN_PER_TRX)
            if str(value.get("amount", "")).lstrip("-").isdigit() else None,
            raw_amount=value.get("amount"),
            decimals=0,
            block_number=raw_contract.get("ref_block_number"),
            status="success" if record.get("confirmed", True) else "unknown",
            provider="trongrid",
            raw=record,
        )

    # --------------------------------------------------------
    # network
    # --------------------------------------------------------

    def get_network_status(self, client: HttpClient) -> NetworkInfo:
        result = client.post_json(
            TRONGRID_BLOCK_URL,
            body={},
            headers=_trongrid_headers(),
            provider="trongrid",
            use_cache=False,   # live endpoint: never serve a cached block height
        )

        if not result.ok or not isinstance(result.data, dict):
            return NetworkInfo(
                chain=self.chain,
                status="unavailable",
                provider="trongrid",
                availability=Availability.UNAVAILABLE,
                unavailable_reason=result.error or "TronGrid did not respond",
            )

        block_header = result.data.get("block_header") or {}
        raw_data = result.data.get("block_header", {}).get("raw_data") or {}

        block_number = block_header.get("number")
        block_hash = block_header.get("blockID")
        timestamp = raw_data.get("timestamp")

        return NetworkInfo(
            chain=self.chain,
            status="ok" if block_number is not None else "unknown",
            latest_block=block_number,
            latest_block_hash=block_hash,
            latest_block_timestamp=(int(timestamp) // 1000)
            if isinstance(timestamp, (int, float)) else None,
            provider="trongrid",
            availability=Availability.AVAILABLE
            if block_number is not None else Availability.UNAVAILABLE,
            unavailable_reason=None if block_number is not None
            else "TronGrid returned no block number",
        )

    def get_latest_blocks(self, client: HttpClient, limit: int = 5) -> List[Dict[str, Any]]:
        """TronGrid has no keyless recent-block list; this reports that plainly."""
        return []

    def get_network_metrics(self, client: HttpClient) -> Dict[str, Any]:
        """
        Only metrics a provider actually exposes.

        TPS is deliberately absent: nothing keyless measures it, and a made-up
        throughput number is exactly the kind of fake live data this project
        must not show.
        """
        return {
            "tps": None,
            "tps_availability": Availability.NOT_PROVIDED,
            "mempool_size": None,
            "mempool_availability": Availability.NOT_PROVIDED,
            "average_block_time_seconds": 3,
            "average_block_time_availability": Availability.AVAILABLE,
        }

    # --------------------------------------------------------
    # entity intelligence
    # --------------------------------------------------------

    def get_address_label(
        self, address: str, client: HttpClient,
    ) -> Optional[EntityAttribution]:
        """
        TronScan exposes party tags inside transfer records, not as a standalone
        keyless address-label endpoint. So a label can only be obtained while
        tracing; the tracer calls `resolve_entity` with the tags it collected.
        """
        return None

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
        Breadth-first, bounded, with an explicit work queue.

        The previous implementation recursed depth-first with a visited set but
        no node cap, so a fan-out address could fan out without bound. Here
        `max_nodes` and `max_depth` are enforced at the point of enqueue, and
        every stop reason is recorded in `truncation_reasons` so a partial
        result is never presented as a complete one.
        """
        if deadline is None:
            deadline = time.monotonic() + 60.0

        result = AdapterTrace(chain=self.chain, seed=seed)

        if not self._tronscan_key and not self._trongrid_key:
            result.status = TraceStatus.PROVIDER_ERROR
            result.status_detail = (
                "No TRON provider key configured. Set TRONSCAN_API_KEY or "
                "TRONGRID_API_KEY in the backend environment."
            )
            return result

        # Seed.
        seed_node = result.add_node(TraceNode(
            address=seed, chain=self.chain, depth=0, is_seed=True,
        ))
        seed_entity = resolve_entity(
            seed, self.chain.value,
            source_url=self.explorer_url(seed),
        )
        if seed_entity:
            seed_node.entity = seed_entity
            seed_node.entity_type = seed_entity.type
            seed_node.source_type = seed_entity.source_type
            seed_node.confidence = seed_entity.confidence
            seed_node.evidence = list(seed_entity.evidence)
            result.notes.append(
                f"Seed address classified as {seed_entity.name} "
                f"({seed_entity.source_type.value})."
            )

        # (address, depth, previous_timestamp) work queue.
        queue: List[Tuple[str, int, Optional[int]]] = [(seed, 0, None)]
        visited = {seed.lower()}

        provider_failures = 0
        matched_entity: Optional[EntityAttribution] = None

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

            address, depth, previous_timestamp = queue.pop(0)
            result.nodes_examined += 1
            result.max_depth_reached = max(result.max_depth_reached, depth)

            # --- fetch both directions -------------------------------------
            txs: List[BlockchainTransaction] = []
            raw_tag_records: List[Dict[str, Any]] = []
            got_data = False
            reached_provider = False

            for incoming in (False, True):
                trc20, trc20_raw, rc20_ok = self._fetch_trc20(
                    address, client, max_txs_per_node, incoming,
                )
                trx, trx_raw, rtx_ok = self._fetch_trx(
                    address, client, max_txs_per_node, incoming,
                )
                txs.extend(trc20)
                txs.extend(trx)
                raw_tag_records.extend(trc20_raw)
                raw_tag_records.extend(trx_raw)
                reached_provider = reached_provider or rc20_ok or rtx_ok
                if trc20 or trx:
                    got_data = True

            txs = _dedupe_and_sort(txs)[:max_txs_per_node]

            # "Reached the provider and it has no history" and "could not reach
            # the provider" are opposite findings, and collapsing them would let
            # an outage print as a clean wallet. Only the second is a failure.
            if not reached_provider:
                provider_failures += 1
                result.notes.append(
                    f"Could not reach any TRON provider for {address}; no "
                    f"history could be retrieved for this address."
                )
            elif not got_data:
                result.notes.append(
                    f"Provider reached; {address} has no transfer history."
                )

            current = result.add_node(TraceNode(
                address=address, chain=self.chain, depth=depth,
                is_seed=(address == seed),
            ))

            for tx in txs:
                result.transactions.append(tx)
                result.transactions_inspected += 1

                for party, key in ((tx.from_address, "from"), (tx.to_address, "to")):
                    if not party:
                        continue
                    target = next(
                        (n for n in result.nodes if n.address.lower() == party.lower()),
                        None,
                    )
                    if target is None:
                        target = result.add_node(TraceNode(
                            address=party, chain=self.chain, depth=depth + 1,
                        ))
                    if key == "from":
                        target.outbound += 1
                    else:
                        target.inbound += 1

                result.edges.append(_edge_from(tx))

                # --- behavioural signals ----------------------------------
                rapid = calculate_rapid_hop(previous_timestamp, tx.timestamp)
                if rapid:
                    result.notes.append(
                        f"Rapid movement: {tx.from_address} -> {tx.to_address} "
                        f"within {RAPID_HOP_SECONDS}s "
                        f"(tx {tx.hash})."
                    )

            # --- entity resolution from collected tags --------------------
            public = _collect_tag(address, raw_tag_records)
            entity = resolve_entity(
                address, self.chain.value, public_label=public,
                source_url=self.explorer_url(address),
            )
            if entity:
                current.entity = entity
                current.entity_type = entity.type
                current.source_type = entity.source_type
                current.confidence = entity.confidence
                current.evidence = list(entity.evidence)
                if matched_entity is None or (
                    entity.source_type.value == "curated_verified"
                    and matched_entity.source_type.value != "curated_verified"
                ):
                    matched_entity = entity

            # --- enqueue neighbours --------------------------------------
            if depth + 1 >= max_depth:
                if txs:
                    result.truncated = True
                    result.truncation_reasons.append(
                        f"max_depth ({max_depth}) reached at {address}"
                    )
                continue

            if len(result.nodes) >= max_nodes:
                result.truncated = True
                result.truncation_reasons.append(
                    f"max_nodes ({max_nodes}) reached"
                )
                continue

            neighbours = sorted({
                party.lower(): party
                for tx in txs for party in (tx.from_address, tx.to_address)
                if party and party.lower() != address.lower()
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
                # Deterministic ordering: newest transfer first.
                party_tx = next(
                    (tx for tx in txs if party in (tx.from_address, tx.to_address)),
                    None,
                )
                queue.append((party, depth + 1, party_tx.timestamp if party_tx else None))

        # --- finalize -----------------------------------------------------
        result.hops = result.max_depth_reached
        result.hop_path = _shortest_path(result, seed, matched_entity)

        # A "match" is a claim that a KNOWN ENTITY was reached. A block
        # explorer's own label is not that: it is PUBLIC_PROVIDER, the same
        # tier as a keyword guess, and promoting it to MATCHED would tell an
        # analyst that a sanctioned exchange was identified when all we
        # actually have is one explorer's annotation. Only a curated, verified
        # record earns the word "match".
        is_verified_match = (
            matched_entity is not None
            and matched_entity.source_type == AttributionSource.CURATED_VERIFIED
        )

        if provider_failures and provider_failures == result.nodes_examined:
            result.status = TraceStatus.PROVIDER_ERROR
            result.status_detail = (
                "Every provider request failed or returned nothing. This is a "
                "provider problem, not a finding about the wallet."
            )
        elif is_verified_match:
            result.status = TraceStatus.MATCHED
        elif result.truncated and result.transactions:
            result.status = TraceStatus.PARTIAL
            result.status_detail = (
                "The trace stopped early. Results below cover only the "
                "addresses that were actually examined."
            )
        elif result.transactions:
            result.status = TraceStatus.NO_MATCH
            result.status_detail = (
                "Traced successfully, but no curated, verified entity was "
                "reached within the examined hops."
                + (
                    f" A public provider label was seen for {matched_entity.name}; "
                    "it is recorded on that node but is not a confirmed match."
                    if matched_entity is not None else ""
                )
            )
        else:
            result.status = TraceStatus.NO_MATCH
            result.status_detail = (
                "The seed address is valid but returned no transfer history."
            )

        if matched_entity is not None:
            result.notes.append(
                f"Reached {matched_entity.name} after {result.max_depth_reached} "
                f"hop(s). Attribution tier: {matched_entity.source_type.value}."
                + (
                    ""
                    if is_verified_match
                    else " This is a provider label, not a verified identification."
                )
            )

        return result


# ============================================================
# MODULE HELPERS
# ============================================================


def _dedupe_and_sort(
    txs: List[BlockchainTransaction],
) -> List[BlockchainTransaction]:
    """
    Deduplicate by hash plus direction and order newest first.

    A single TRON transaction can carry many TRC-20 transfers, so the hash
    alone is not a key: two different token moves in one transaction are two
    distinct facts and both belong in the report.
    """
    seen = set()
    unique = []
    for tx in txs:
        key = (tx.hash, tx.from_address, tx.to_address, tx.asset, tx.raw_amount)
        if key in seen:
            continue
        seen.add(key)
        unique.append(tx)
    return sorted(unique, key=lambda t: t.timestamp or 0, reverse=True)


def _edge_from(tx: BlockchainTransaction) -> TraceEdge:
    return TraceEdge(
        transaction_hash=tx.hash,
        from_address=tx.from_address,
        to_address=tx.to_address,
        chain=tx.chain,
        asset=tx.asset,
        amount=tx.amount,
        timestamp=tx.timestamp,
        token_contract=tx.token_contract,
    )


def _collect_tag(address: str, records: List[Dict[str, Any]]) -> Optional[str]:
    """
    Find a TronScan party tag for `address` among fetched transfer records.

    TronScan attaches `from_address_tag` / `to_address_tag` per transfer. An
    address can carry different tags in different records; the first non-empty
    one wins, and which record it came from is not claimed.
    """
    target = (address or "").lower()
    for record in records:
        if not isinstance(record, dict):
            continue

        sender = _first(record, "from_address", "fromAddress", "from")
        if sender and sender.lower() == target:
            tag = _tag_from(record.get("from_address_tag"))
            if tag:
                return tag

        recipient = _first(record, "to_address", "toAddress", "to")
        if recipient and recipient.lower() == target:
            tag = _tag_from(record.get("to_address_tag"))
            if tag:
                return tag

        tag = record.get("toAddressTag") or record.get("fromAddressTag")
        if isinstance(tag, str) and tag.strip():
            return tag.strip()

    return None


def _shortest_path(result: AdapterTrace, seed: str, entity) -> List[str]:
    """
    A defensible path: BFS over the collected edges from the seed to whichever
    node was classified.
    """
    if entity is None or not entity.name:
        return [seed]

    target = next(
        (n for n in result.nodes if n.entity is not None and n.entity.name == entity.name),
        None,
    )
    if target is None or target.address == seed:
        return [seed] if target is None else [seed]

    adjacency: Dict[str, List[str]] = {}
    for edge in result.edges:
        if edge.from_address and edge.to_address:
            adjacency.setdefault(edge.from_address.lower(), []).append(edge.to_address)
            adjacency.setdefault(edge.to_address.lower(), []).append(edge.from_address)

    queue: List[List[str]] = [[seed]]
    seen = {seed.lower()}

    while queue:
        path = queue.pop(0)
        for neighbour in adjacency.get(path[-1].lower(), []):
            if neighbour.lower() in seen:
                continue
            extended = path + [neighbour]
            if neighbour.lower() == target.address.lower():
                return extended
            seen.add(neighbour.lower())
            queue.append(extended)

    return [seed, target.address]
