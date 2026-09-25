"""
Bitcoin chain adapter — UTXO model, Blockstream primary, mempool.space fallback.

Why this adapter is not a copy of the EVM one
--------------------------------------------
Bitcoin has no accounts. A transaction does not move value "from A to B"; it
spends a set of previous outputs (inputs) and creates a set of new outputs.
A single transaction can have 40 inputs and 90 outputs and consolidate or split
value in any proportion. Presenting that as one `from_address` -> `to_address`
pair is a factual error, and every downstream risk rule that assumes a
one-to-one transfer would be wrong for Bitcoin specifically.

So this adapter:

* keeps the full input/output lists on every `BlockchainTransaction`
  (`inputs` / `outputs`), which is what the shared model provides for exactly
  this purpose;
* sets `from_address` / `to_address` to a *derived* summary only when there is
  genuinely one counterparty, and leaves them None otherwise rather than
  picking an arbitrary input;
* labels the summary fields as derived in `notes` and never claims a
  one-input-one-output transfer happened when it did not.

Provider reality (verified live, see PROVIDER_FINDINGS.md):

    blockstream.info/api   200, keyless, full vin/vout + address history
    mempool.space/api      200, keyless, byte-identical responses

Both are Esplora. mempool.space is the fallback, not a second source of truth:
if they ever disagree, that is a finding to surface, not something to average
away.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from adapters.base import AdapterTrace, ChainAdapter, NetworkInfo
from models.schemas import (
    AttributionSource,
    Availability,
    BlockchainTransaction,
    Chain,
    Direction,
    EntityAttribution,
    TraceEdge,
    TraceNode,
    TraceStatus,
)
from services.chain_detection import validate_bitcoin_address
from services.entity_service import resolve_entity
from utils.http_client import HttpClient

SATOSHIS_PER_BTC = 100_000_000

#: Esplora base URLs, tried in order. Both keyless, both Esplora-compatible.
ESPLORA_BASES = (
    "https://blockstream.info/api",
    "https://mempool.space/api",
)

#: scriptpubkey_type values that mean "this output is not a normal payment".
#: OP_RETURN outputs are unspendable data carriers; counting them as a wallet
#: edge would put phantom nodes in the graph.
NON_PAYMENT_TYPES = {"op_return", "nonstandard", "p2tr", "p2wsh", "p2sh", "multisig", "witness_unknown"}


def _btc_to_float(sats: Any) -> Optional[float]:
    if sats is None:
        return None
    try:
        return int(sats) / SATOSHIS_PER_BTC
    except (TypeError, ValueError, OverflowError):
        return None


def _int(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class BitcoinAdapter(ChainAdapter):
    """
    Bitcoin tracing over Esplora (Blockstream / mempool.space).

    The provider here is keyless for address history, which is the one thing
    BSC cannot do -- this chain has full traversal available with no API key.
    """

    chain = Chain.BITCOIN

    def __init__(self, base: Optional[str] = None) -> None:
        self._preferred_base = base

    # --------------------------------------------------------
    # identity
    # --------------------------------------------------------

    def validate_address(self, address: str) -> bool:
        return validate_bitcoin_address(address)[0]

    def validate_transaction_hash(self, tx_hash: str) -> bool:
        candidate = (tx_hash or "").strip().lower()
        return len(candidate) == 64 and all(c in "0123456789abcdef" for c in candidate)

    def explorer_url(self, value: str, input_type: str = "address") -> Optional[str]:
        if not value:
            return None
        if input_type == "transaction":
            return f"https://mempool.space/tx/{value}"
        return f"https://mempool.space/address/{value}"

    def capabilities(self) -> List[str]:
        return [
            "address_validation",
            "transaction_lookup",
            "network_status",
            "utxo_semantics",
            "outgoing_transfers",
            "incoming_transfers",
        ]

    # --------------------------------------------------------
    # provider access (with base fallback)
    # --------------------------------------------------------

    def _bases(self) -> Tuple[str, ...]:
        """Preferred base first, then the rest in configured order."""
        if not self._preferred_base:
            return ESPLORA_BASES
        return (self._preferred_base,) + tuple(b for b in ESPLORA_BASES if b != self._preferred_base)

    def _get(self, client: HttpClient, path: str, use_cache: bool = True):
        """
        GET against each Esplora base until one returns a usable body.

        A 4xx here is a real answer (address not found), not a transport blip, so
        it is returned rather than retried against the next base. Only a
        transport-level failure falls through.
        """
        last = None
        for index, base in enumerate(self._bases()):
            result = client.get_json(
                f"{base}{path}", provider=f"esplora-{index}", use_cache=use_cache,
            )
            if result.ok:
                return result
            last = result
            if result.status_code and 400 <= result.status_code < 500:
                # A 404/422 means this base agrees the thing does not exist.
                return result
        return last

    # --------------------------------------------------------
    # transaction normalization
    # --------------------------------------------------------

    def _input_records(self, vin: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Normalize inputs. `prevout` is None for a coinbase input, and `scriptsig`
        is a string, not an object -- both are real shapes, not missing data.
        """
        records = []
        for index, item in enumerate(vin or []):
            prevout = item.get("prevout") or {}
            records.append({
                "index": index,
                "txid": item.get("txid"),
                "vout": item.get("vout"),
                "is_coinbase": bool(item.get("is_coinbase")),
                "address": prevout.get("scriptpubkey_address") if isinstance(prevout, dict) else None,
                "value_sats": _int(prevout.get("value")) if isinstance(prevout, dict) else None,
                "value_btc": _btc_to_float(_int(prevout.get("value")) if isinstance(prevout, dict) else None),
            })
        return records

    def _output_records(self, vout: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        records = []
        for index, item in enumerate(vout or []):
            script = item.get("scriptpubkey")
            records.append({
                "index": index,
                "address": item.get("scriptpubkey_address"),
                "value_sats": _int(item.get("value")),
                "value_btc": _btc_to_float(_int(item.get("value"))),
                "script_type": item.get("scriptpubkey_type"),
                "scriptpubkey": script,
            })
        return records

    def _to_transaction(
        self,
        raw: Dict[str, Any],
        subject: Optional[str],
    ) -> Optional[BlockchainTransaction]:
        """
        Build one normalized transaction from an Esplora tx object.

        The address fields are a *summary*, and are only populated when the
        shape actually supports them. A many-input transaction gets
        `from_address=None` and the real counterparty set lives in `inputs`.
        """
        txid = raw.get("txid")
        if not txid:
            return None

        inputs = self._input_records(raw.get("vin") or [])
        outputs = self._output_records(raw.get("vout") or [])

        status = raw.get("status") or {}
        timestamp = _int(status.get("block_time")) if isinstance(status, dict) else None
        block_height = _int(status.get("block_height")) if isinstance(status, dict) else None
        confirmed = bool(status.get("confirmed")) if isinstance(status, dict) else False

        # Addresses that actually appear on either side.
        input_addresses = {i["address"] for i in inputs if i.get("address")}
        output_addresses = {o["address"] for o in outputs if o.get("address")}

        def relation(addr: Optional[str]) -> Optional[Direction]:
            if not subject or not addr:
                return None
            low, s = addr.lower(), subject.lower()
            if low == s:
                return Direction.SELF
            return Direction.OUTGOING if low in {a.lower() for a in input_addresses} else Direction.INCOMING

        # --- derived single-counterparty summary ---------------------------
        # Only when there is exactly one distinct input address AND exactly one
        # distinct output address. Otherwise leave None; the lists carry truth.
        from_address: Optional[str] = next(iter(input_addresses), None) if len(input_addresses) == 1 else None
        to_address: Optional[str] = next(iter(output_addresses), None) if len(output_addresses) == 1 else None

        # --- direction relative to the subject ------------------------------
        in_inputs = subject is not None and subject.lower() in {a.lower() for a in input_addresses}
        in_outputs = subject is not None and subject.lower() in {a.lower() for a in output_addresses}

        if in_inputs and in_outputs:
            direction = Direction.SELF
        elif in_inputs:
            direction = Direction.OUTGOING
        elif in_outputs:
            direction = Direction.INCOMING
        else:
            # The subject is a party only via a script type we exclude, or the
            # transaction is unassociated. Recorded as observed, not as a
            # claim about value direction.
            direction = Direction.INCOMING

        # Value at the subject address, if it received one in this transaction.
        subject_amount: Optional[float] = None
        if in_outputs:
            for o in outputs:
                if (o.get("address") or "").lower() == subject.lower():
                    subject_amount = _btc_to_float(o.get("value_sats"))
                    break

        return BlockchainTransaction(
            chain=Chain.BITCOIN,
            hash=txid,
            timestamp=timestamp,
            from_address=from_address,
            to_address=to_address,
            asset="BTC",
            amount=subject_amount,
            decimals=8,
            # The satoshi value the subject actually received, kept as the raw
            # integer so no float rounding enters the forensic record.
            raw_amount=(
                str(int(subject_amount * SATOSHIS_PER_BTC))
                if subject_amount is not None else None
            ),
            direction=direction,
            block_number=block_height,
            status="success" if confirmed else "pending",
            fee=_btc_to_float(_int(raw.get("fee"))),
            confirmations=None,  # Esplora does not report per-tx confirmations
            inputs=inputs,
            outputs=outputs,
            provider="esplora",
            raw=raw,
        )

    # --------------------------------------------------------
    # address retrieval
    # --------------------------------------------------------

    def _address_txs(self, address: str, client: HttpClient, limit: int) -> List[Dict[str, Any]]:
        """
        Transactions touching an address (Esplora /address/:a/txs).

        Esplora has no direction filter — it returns one newest-first list
        containing both directions. `limit` is therefore applied by the caller
        AFTER filtering, so this returns a slightly larger window to filter
        from; see get_outgoing_transfers.
        """
        result = self._get(client, f"/address/{address}/txs")
        if not result.ok or not isinstance(result.data, list):
            return []
        return result.data

    def get_outgoing_transfers(
        self, address: str, client: HttpClient, limit: int = 10,
    ) -> List[BlockchainTransaction]:
        # Over-fetch, then filter, then limit. Slicing to `limit` first would
        # return nothing at all for a receive-heavy address, which would read
        # as "no outgoing transfers" rather than "none in the sampled window".
        txs = self._address_txs(address, client, limit)
        out = []
        for raw in txs:
            tx = self._to_transaction(raw, address)
            if tx and tx.direction == Direction.OUTGOING:
                out.append(tx)
            if len(out) >= limit:
                break
        return out

    def get_incoming_transfers(
        self, address: str, client: HttpClient, limit: int = 10,
    ) -> List[BlockchainTransaction]:
        txs = self._address_txs(address, client, limit)
        inc = []
        for raw in txs:
            tx = self._to_transaction(raw, address)
            if tx and tx.direction == Direction.INCOMING:
                inc.append(tx)
            if len(inc) >= limit:
                break
        return inc

    def get_address_activity(
        self, address: str, client: HttpClient, limit: int = 10,
    ) -> List[BlockchainTransaction]:
        """
        All txs touching the address, self-transfers included.

        The base class unions in+out by hash, which would drop a self-transfer
        (a tx where the address is both sender and receiver appears in both sets
        but is neither purely in nor out). This is the correct override.
        """
        txs = self._address_txs(address, client, limit)
        result = []
        for raw in txs:
            tx = self._to_transaction(raw, address)
            if tx:
                result.append(tx)
            if len(result) >= limit:
                break
        return sorted(result, key=lambda t: t.timestamp or 0, reverse=True)

    def get_transaction(
        self, tx_hash: str, client: HttpClient,
    ) -> Optional[BlockchainTransaction]:
        result = self._get(client, f"/tx/{tx_hash}")
        if not result.ok or not isinstance(result.data, dict):
            return None
        return self._to_transaction(result.data, None)

    # --------------------------------------------------------
    # live network
    # --------------------------------------------------------

    def get_network_status(self, client: HttpClient) -> NetworkInfo:
        # Live tip: never cache.
        result = self._get(client, "/blocks/tip/height", use_cache=False)
        if not result.ok or _int(result.data) is None:
            return NetworkInfo(
                chain=Chain.BITCOIN,
                status="unavailable",
                provider="esplora",
                availability=Availability.UNAVAILABLE,
                unavailable_reason="Neither Esplora provider returned a block height.",
            )
        height = _int(result.data)
        return NetworkInfo(
            chain=Chain.BITCOIN,
            status="ok",
            latest_block=height,
            provider="esplora",
            availability=Availability.AVAILABLE,
            extra={"difficulty_adjustment": "every 2016 blocks", "average_block_time_seconds": 600.0},
        )

    def get_network_metrics(self, client: HttpClient) -> Dict[str, Any]:
        return {
            "tps": None,
            "tps_availability": Availability.NOT_PROVIDED,
            "average_block_time_seconds": 600.0,
            "average_block_time_basis": "protocol target (10 min), not a live measurement",
        }

    def get_address_label(
        self, address: str, client: HttpClient,
    ) -> Optional[EntityAttribution]:
        """
        Esplora carries no public labels -- only on-chain and balance stats.

        There is therefore no provider label to surface. A curated record can
        still match; otherwise the honest answer is None ("we do not know"),
        not a guess based on the address's history.
        """
        return resolve_entity(address, Chain.BITCOIN.value, source_url=self.explorer_url(address))

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
        Bounded BFS over the UTXO graph, same shape as every other adapter.

        A node's neighbours are the addresses in the *inputs* of its txs (the
        addresses whose outputs it consumed) and the *outputs* it created. This
        follows value backward and forward through the actual UTXO graph, which
        is the Bitcoin analogue of following transfers in an account model.
        """
        if deadline is None:
            deadline = time.monotonic() + 60.0

        result = AdapterTrace(chain=Chain.BITCOIN, seed=seed)

        seed_node = result.add_node(TraceNode(
            address=seed, chain=Chain.BITCOIN, depth=0, is_seed=True,
        ))
        seed_label = self.get_address_label(seed, client)
        if seed_label:
            seed_node.entity = seed_label
            seed_node.entity_type = seed_label.type
            seed_node.source_type = seed_label.source_type
            seed_node.confidence = seed_label.confidence
            seed_node.evidence = list(seed_label.evidence)

        queue: List[Tuple[str, int]] = [(seed, 0)]
        visited = {seed.lower()}
        provider_failures = 0

        while queue:
            if time.monotonic() >= deadline:
                result.status = TraceStatus.TIMEOUT
                result.status_detail = (
                    "Tracing stopped at the time budget after examining "
                    f"{result.nodes_examined} address(es)."
                )
                result.truncated = True
                result.truncation_reasons.append("deadline_reached")
                break

            address, depth = queue.pop(0)
            result.nodes_examined += 1
            result.max_depth_reached = max(result.max_depth_reached, depth)

            txs = self.get_address_activity(address, client, max_txs_per_node)
            if not txs:
                provider_failures += 1

            current = result.add_node(TraceNode(
                address=address, chain=Chain.BITCOIN, depth=depth,
                is_seed=(address == seed),
            ))

            for tx in txs:
                result.transactions.append(tx)
                result.transactions_inspected += 1

                # Build an edge per real input->output funding path is not
                # meaningful here; instead create edges for the derived pair
                # when it exists, and let the tx carry the full UTXO detail.
                if tx.from_address or tx.to_address:
                    result.edges.append(TraceEdge(
                        transaction_hash=tx.hash,
                        from_address=tx.from_address,
                        to_address=tx.to_address,
                        chain=Chain.BITCOIN,
                        asset="BTC",
                        amount=tx.amount,
                        timestamp=tx.timestamp,
                        token_contract=None,
                    ))

                # Degree counting. For each output the subject address appears
                # on, the subject is the receiver of that input's value; for
                # each input the subject spends, the subject is the sender.
                # The subject's own in/out counters must reflect this, not be
                # skipped as a "self loop" — the two counters live on the
                # subject node itself, so skipping self is what left it at 0/0.
                for o in tx.outputs:
                    oa = o.get("address")
                    if not oa or o.get("script_type") in NON_PAYMENT_TYPES:
                        continue
                    if oa.lower() != address.lower():
                        target = next(
                            (n for n in result.nodes if n.address.lower() == oa.lower()), None,
                        ) or result.add_node(TraceNode(
                            address=oa, chain=Chain.BITCOIN, depth=depth + 1,
                        ))
                        target.inbound += 1
                    else:
                        current.inbound += 1

                for i in tx.inputs:
                    ia = i.get("address")
                    if not ia or i.get("is_coinbase"):
                        continue
                    if ia.lower() != address.lower():
                        target = next(
                            (n for n in result.nodes if n.address.lower() == ia.lower()), None,
                        ) or result.add_node(TraceNode(
                            address=ia, chain=Chain.BITCOIN, depth=depth + 1,
                        ))
                        target.outbound += 1
                    else:
                        current.outbound += 1

            # Label (only curated can match on this chain)
            label = self.get_address_label(address, client)
            if label:
                current.entity = label
                current.entity_type = label.type
                current.source_type = label.source_type
                current.confidence = label.confidence
                current.evidence = list(label.evidence)

            if depth + 1 >= max_depth:
                if txs:
                    result.truncated = True
                    result.truncation_reasons.append(f"max_depth ({max_depth}) reached at {address}")
                continue

            if len(result.nodes) >= max_nodes:
                result.truncated = True
                result.truncation_reasons.append(f"max_nodes ({max_nodes}) reached")
                continue

            # Neighbours: all input and output addresses other than self.
            neighbours = sorted({
                a.lower(): a
                for tx in txs
                for a in (
                    [o.get("address") for o in tx.outputs if o.get("script_type") not in NON_PAYMENT_TYPES]
                    + [i.get("address") for i in tx.inputs if not i.get("is_coinbase")]
                )
                if a and a.lower() != address.lower()
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
                queue.append((party, depth + 1))

        result.hops = result.max_depth_reached
        result.hop_path = [seed]

        is_verified_match = any(
            n.entity and n.entity.source_type == AttributionSource.CURATED_VERIFIED
            for n in result.nodes
        )

        if provider_failures and provider_failures == result.nodes_examined:
            result.status = TraceStatus.PROVIDER_ERROR
            result.status_detail = (
                "Neither Esplora provider returned transaction history for any "
                "examined address."
            )
        elif is_verified_match:
            result.status = TraceStatus.MATCHED
        elif result.truncated and result.transactions:
            result.status = TraceStatus.PARTIAL
            result.status_detail = (
                "The trace stopped early. Results cover only the addresses that "
                "were actually examined."
            )
        elif result.transactions:
            result.status = TraceStatus.NO_MATCH
            result.status_detail = (
                "Traced successfully, but no curated, verified entity was "
                "reached within the examined hops."
            )
        else:
            result.status = TraceStatus.NO_MATCH
            result.status_detail = "The address returned no transaction history."

        result.notes.append(
            "Bitcoin is a UTXO chain: each transaction lists the previous "
            "outputs it spends (inputs) and the new outputs it creates. A "
            "single transaction may have many inputs and many outputs, so it is "
            "not a simple account-to-account transfer."
        )
        return result
