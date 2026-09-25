"""
The investigation orchestrator — chain-agnostic by construction.

This is the module that makes the product multi-chain. It knows how to:
  detect what a user pasted -> pick the adapter -> run a bounded trace ->
  resolve entity attribution -> score risk -> assemble one `TraceResult`.

It does NOT know what a TronGrid response looks like, what a Blockscout field is
called, or how Bitcoin's UTXO model differs from an account model. Those live
behind `ChainAdapter`. The only chain-specific thing in this file is a comment
explaining that a UTXO chain's `from`/`to` summary may be absent — and even
that is a property of the normalized model, not of a provider.

Everything here is verifiable: the result carries which providers were called,
how many requests they took, whether the trace was truncated and why.
"""

from __future__ import annotations

import time
from typing import List, Optional, Tuple

from config import (
    MAX_TRACE_DEPTH,
    MAX_TRACE_NODES,
    MAX_TXS_PER_NODE,
    TRACE_DEADLINE_SECONDS,
)
from models.schemas import (
    Chain,
    InputType,
    TraceMetadata,
    TraceResult,
    TraceStatus,
)
from services import risk_engine
from services.chain_detection import detect_chain
from services.chain_registry import get_adapter
from utils.http_client import HttpClient, RequestCache

__all__ = ["run_investigation", "detect_only", "DetectionError"]


class DetectionError(ValueError):
    """The input is not something any supported chain recognizes."""

    def __init__(self, message: str, detection: Optional[dict] = None) -> None:
        super().__init__(message)
        self.detection = detection or {}


def detect_only(raw_input: str, preferred_chain: Optional[Chain] = None) -> dict:
    """
    Identify an input without running a trace.

    The Trace Console calls this on every keystroke (debounced) so it can show
    the detected chain and whether the input is even valid before the user
    commits to a full multi-hop investigation.
    """
    return detect_chain(raw_input, preferred_evm=preferred_chain)


def _resolve_input(
    raw_input: str, preferred_chain: Optional[Chain],
) -> Tuple[Chain, InputType, str]:
    """
    Validate the input and pin it to exactly one chain.

    Raises DetectionError rather than guessing. A forensic tool that silently
    picks a chain when the format is ambiguous would produce a confident,
    wrong report — for a 0x address, which is valid on three networks at once.
    """
    detection = detect_chain(raw_input, preferred_evm=preferred_chain)

    if not detection.get("valid"):
        reason = detection.get("reason") or "unrecognized input"
        raise DetectionError(
            f"Input is not a valid address or transaction hash on any supported "
            f"chain: {reason}",
            detection,
        )

    chain = Chain(detection["chain"])
    input_type = InputType(detection["input_type"])
    return chain, input_type, detection["normalized_input"]


def run_investigation(
    raw_input: str,
    preferred_chain: Optional[Chain] = None,
    max_depth: Optional[int] = None,
    max_nodes: Optional[int] = None,
    max_txs_per_node: Optional[int] = None,
    deadline_seconds: Optional[int] = None,
) -> TraceResult:
    """
    Run a complete investigation and return one normalized result.

    The returned `TraceResult` is the same object shape for every chain: the
    frontend, the report generator and the database layer never branch on chain
    to interpret it.
    """
    started = time.time()
    deadline_monotonic = time.monotonic() + (deadline_seconds or TRACE_DEADLINE_SECONDS)

    depth = MAX_TRACE_DEPTH if max_depth is None else max_depth
    node_cap = MAX_TRACE_NODES if max_nodes is None else max_nodes
    tx_cap = MAX_TXS_PER_NODE if max_txs_per_node is None else max_txs_per_node

    # --- 1. detect -------------------------------------------------------
    chain, input_type, normalized = _resolve_input(raw_input, preferred_chain)
    adapter = get_adapter(chain)

    # --- 2. validate against the chosen adapter --------------------------
    # detect_chain is format-level; the adapter owns the authoritative check
    # for its own chain. They can disagree (e.g. a bad Base58Check checksum on
    # an address that merely looks like TRON), and the adapter is right.
    if input_type == InputType.ADDRESS:
        if not adapter.validate_address(normalized):
            return _failed(
                chain, normalized, input_type, started, depth, node_cap,
                TraceStatus.INVALID_INPUT,
                f"The input is not a valid {chain.display_name} address "
                f"(it matched the format but failed validation).",
            )
    else:
        if not adapter.validate_transaction_hash(normalized):
            return _failed(
                chain, normalized, input_type, started, depth, node_cap,
                TraceStatus.INVALID_INPUT,
                f"The input is not a valid {chain.display_name} transaction hash.",
            )

    # --- 3. trace --------------------------------------------------------
    client = HttpClient(
        cache=RequestCache(),
        deadline=deadline_monotonic,
    )

    try:
        if input_type == InputType.ADDRESS:
            adapter_trace = adapter.trace(
                normalized, client,
                max_depth=depth,
                max_nodes=node_cap,
                max_txs_per_node=tx_cap,
                deadline=deadline_monotonic,
            )
        else:
            adapter_trace = _trace_from_hash(
                adapter, normalized, client, depth, node_cap, tx_cap,
                deadline_monotonic,
            )
    finally:
        usage, cache_stats = client.usage_summary()
        client.close()

    # --- 4. assemble -----------------------------------------------------
    result = TraceResult(
        chain=chain,
        seed=normalized,
        input_type=input_type,
        status=adapter_trace.status,
        status_detail=adapter_trace.status_detail,
        nodes=adapter_trace.nodes,
        edges=adapter_trace.edges,
        transactions=adapter_trace.transactions,
        hop_path=adapter_trace.hop_path,
        hops=adapter_trace.hops,
    )

    result.evidence_notes.extend(adapter_trace.notes)
    result.evidence_notes.append(
        f"Provider cache for this investigation: {cache_stats['hits']} hit(s), "
        f"{cache_stats['misses']} miss(es). The cache is per-investigation by "
        f"design, so a repeated trace re-fetches current chain state."
    )

    seed_node = result.node_for(normalized)
    if seed_node:
        result.seed_entity = seed_node.entity

    # The strongest attribution reached anywhere in the trace.
    result.entity = _strongest_entity(result)

    # --- 5. risk ---------------------------------------------------------
    result.risk = risk_engine.assess(result)

    # --- 6. metadata -----------------------------------------------------
    completed = time.time()
    result.metadata = TraceMetadata(
        started_at=started,
        completed_at=completed,
        duration_ms=int((completed - started) * 1000),
        depth_limit=depth,
        node_limit=node_cap,
        max_depth_reached=adapter_trace.max_depth_reached,
        nodes_examined=adapter_trace.nodes_examined,
        transactions_inspected=adapter_trace.transactions_inspected,
        provider_usage=usage,
        truncated=adapter_trace.truncated,
        truncation_reasons=adapter_trace.truncation_reasons,
    )

    return result


def _trace_from_hash(
    adapter, tx_hash: str, client: HttpClient,
    depth: int, node_cap: int, tx_cap: int, deadline: float,
):
    """
    Expand a transaction hash into a small graph.

    A hash has no address history to walk, so this fetches the transaction and
    its direct counterparties only. It is deliberately a shallower operation
    than an address trace, and says so in the notes rather than pretending to be
    equivalent.
    """
    from adapters.base import AdapterTrace
    from models.schemas import (
        AttributionSource,
        TraceEdge,
        TraceNode,
        TraceStatus,
    )

    result = AdapterTrace(chain=adapter.chain, seed=tx_hash)

    tx = adapter.get_transaction(tx_hash, client)
    if tx is None:
        result.status = TraceStatus.NO_MATCH
        result.status_detail = (
            f"No {adapter.chain.display_name} transaction was found with this hash "
            f"on the providers queried. The hash may belong to a different chain, "
            f"or the transaction may not exist."
        )
        return result

    result.status = TraceStatus.NO_MATCH
    result.status_detail = (
        f"Fetched transaction {tx_hash[:16]}…. This is a single-transaction view: "
        f"a hash has no address history to traverse, so the graph shows only its "
        f"direct counterparties. Enter a counterparty address for a multi-hop trace."
    )
    result.notes.append(
        "A transaction hash produces a one-hop view, not an address trace. "
        "For multi-hop tracing, start from an address."
    )

    seed_node = result.add_node(TraceNode(
        address=tx_hash, chain=adapter.chain, depth=0, is_seed=True,
    ))
    seed_node.entity = None

    result.transactions.append(tx)
    result.transactions_inspected = 1
    result.nodes_examined = 1
    result.max_depth_reached = 0

    if tx.from_address or tx.to_address:
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

    # UTXO chains expose many counterparties in inputs/outputs; account chains
    # have exactly the two. Reading both keeps this chain-agnostic.
    counterparties = []
    for party in (tx.from_address, tx.to_address):
        if party:
            counterparties.append(party)
    for record in list(tx.inputs) + list(tx.outputs):
        party = record.get("address")
        if party and party not in counterparties:
            counterparties.append(party)

    for index, party in enumerate(counterparties[:max(1, node_cap - 1)]):
        node = result.add_node(TraceNode(
            address=party, chain=adapter.chain, depth=1,
        ))
        label = adapter.get_address_label(party, client)
        if label:
            node.entity = label
            node.entity_type = label.type
            node.source_type = label.source_type
            node.confidence = label.confidence
            node.evidence = list(label.evidence)

    if adapter.chain.is_evm or adapter.chain == Chain.TRON:
        result.hops = 0
    result.hop_path = [tx_hash]

    return result


def _strongest_entity(result: TraceResult):
    """
    The best attribution found anywhere in the trace.

    Ranked by provenance tier first and confidence second, so a curated record
    always outranks a provider label regardless of how confident the label is.
    """
    tier_rank = {
        "curated_verified": 3,
        "public_provider": 2,
        "heuristic": 1,
        "none": 0,
    }
    best = None
    best_key = (-1, -1)
    for node in result.nodes:
        entity = node.entity
        if not entity:
            continue
        key = (tier_rank.get(entity.source_type.value, 0), entity.confidence)
        if key > best_key:
            best_key = key
            best = entity
    return best


def _failed(
    chain: Chain, seed: str, input_type: InputType, started: float,
    depth: int, node_cap: int, status: TraceStatus, detail: str,
) -> TraceResult:
    """
    A result for a run that never reached a provider.

    Returned rather than raised so the client always receives the same shape,
    with the reason carried in the status. A failed trace is still a trace
    record, and in an investigation log its absence would be misleading.
    """
    completed = time.time()
    return TraceResult(
        chain=chain,
        seed=seed,
        input_type=input_type,
        status=status,
        status_detail=detail,
        metadata=TraceMetadata(
            started_at=started,
            completed_at=completed,
            duration_ms=int((completed - started) * 1000),
            depth_limit=depth,
            node_limit=node_cap,
        ),
    )
