"""
Round-trip proof for the normalized data model.

`TraceResult.to_dict()` is the wire contract and the stored record. The reports
center re-renders a PDF from a stored result via `from_dict`, so if the two are
not exact inverses, a re-rendered dossier silently differs from the original —
or worse, raises partway through and the investigator never gets a document.

This asserts the inverse on a *populated* result, not an empty one. An empty
result round-trips trivially; the interesting cases are populated enums,
nested optionals, and the UTXO input/output structures Bitcoin produces.
"""

import json
import sys

sys.path.insert(0, ".")

from models.schemas import (  # noqa: E402
    AttributionSource,
    BlockchainTransaction,
    Chain,
    Direction,
    EntityAttribution,
    EntityType,
    InputType,
    RiskAssessment,
    RiskIndicator,
    RiskLevel,
    Severity,
    TraceEdge,
    TraceMetadata,
    TraceNode,
    TraceResult,
    TraceStatus,
    VerificationStatus,
)


def populated() -> TraceResult:
    """A result exercising every optional, nested, and enum-bearing field."""
    return TraceResult(
        chain=Chain.ETHEREUM,
        seed="0x" + "ab" * 20,
        input_type=InputType.ADDRESS,
        status=TraceStatus.PARTIAL,
        status_detail="depth limit reached",
        nodes=[
            TraceNode(
                address="0x" + "ab" * 20,
                chain=Chain.ETHEREUM,
                entity=EntityAttribution(
                    name="A named entity",
                    type=EntityType.EXCHANGE,
                    source_type=AttributionSource.PUBLIC_PROVIDER,
                    confidence=70,
                    evidence=["provider label"],
                    source_url="https://example.org/label",
                    verification_status=VerificationStatus.UNVERIFIED,
                    verified_at="2026-01-01T00:00:00Z",
                    notes="a note",
                ),
                entity_type=EntityType.EXCHANGE,
                source_type=AttributionSource.PUBLIC_PROVIDER,
                confidence=70,
                evidence=["node evidence"],
                depth=0, inbound=1, outbound=2, is_seed=True,
            ),
            # A node with NO entity, to prove None survives as None.
            TraceNode(address="0x" + "cd" * 20, chain=Chain.ETHEREUM, depth=1),
        ],
        edges=[
            TraceEdge(
                transaction_hash="0x" + "ef" * 32,
                from_address="0x" + "ab" * 20,
                to_address="0x" + "cd" * 20,
                chain=Chain.ETHEREUM,
                asset="ETH", amount=0.75, timestamp=1767225600,
                risk_flags=["large_transfer"], token_contract=None,
            ),
        ],
        transactions=[
            BlockchainTransaction(
                chain=Chain.ETHEREUM,
                hash="0x" + "ef" * 32,
                timestamp=1767225600,
                from_address="0x" + "ab" * 20,
                to_address="0x" + "cd" * 20,
                asset="ETH", amount=0.75, decimals=18,
                raw_amount="750000000000000000",
                direction=Direction.OUTGOING,
                block_number=21000000,
                status="success", fee=0.001, confirmations=1000,
                provider="blockscout",
            ),
        ],
        hop_path=["0x" + "ab" * 20, "0x" + "cd" * 20],
        hops=1,
        seed_entity=EntityAttribution(
            name="Seed", type=EntityType.UNKNOWN,
            source_type=AttributionSource.NONE,
        ),
        entity=EntityAttribution(
            name="Seed", type=EntityType.UNKNOWN,
            source_type=AttributionSource.NONE,
        ),
        risk=RiskAssessment(
            risk_score=35,
            risk_level=RiskLevel.MEDIUM,
            indicators=[
                RiskIndicator(
                    code="large_transfer", name="Large transfer",
                    severity=Severity.MEDIUM, weight=15,
                    evidence="0.75 ETH moved in one transfer.",
                    related_addresses=["0x" + "cd" * 20],
                    related_transactions=["0x" + "ef" * 32],
                    timestamp=1767225600, amount=0.75, source="chain_txs",
                ),
            ],
            assessment="A statement about the retrieved data.",
            score_breakdown={"large_transfer": 15},
        ),
        report="/reports/trace_abc.pdf",
        report_id="trace_abc",
        metadata=TraceMetadata(
            investigation_id="inv-123",
            started_at=1767225600.0,
            completed_at=1767225610.0,
            duration_ms=10000,
            depth_limit=3, node_limit=25, max_depth_reached=1,
            nodes_examined=2, transactions_inspected=1,
            truncated=True,
            truncation_reasons=["node limit reached"],
        ),
        evidence_notes=["an evidence note"],
    )


def main() -> int:
    original = populated()
    first = original.to_dict()
    rebuilt = TraceResult.from_dict(first)
    second = rebuilt.to_dict()

    # A dict compare, so a difference anywhere is named, not just a bool.
    if first != second:
        for key in sorted(set(first) | set(second)):
            a, b = first.get(key), second.get(key)
            if a != b:
                print(f"MISMATCH  {key}\n  before: {json.dumps(a, default=str)[:400]}"
                      f"\n  after:  {json.dumps(b, default=str)[:400]}")
        print("FAIL: to_dict/from_dict is not an exact inverse")
        return 1

    # And again, to prove the second round trip is stable too.
    if TraceResult.from_dict(second).to_dict() != second:
        print("FAIL: round trip is not idempotent on the second pass")
        return 1

    # Prove it survives actual JSON, not just Python dicts.
    via_json = TraceResult.from_dict(json.loads(json.dumps(first, default=str))).to_dict()
    if via_json != first:
        print("FAIL: does not survive a JSON round trip")
        return 1

    print("PASS  to_dict -> from_dict -> to_dict is exact, idempotent, JSON-safe")
    print(f"      {len(first['nodes'])} nodes, {len(first['edges'])} edges, "
          f"{len(first['transactions'])} transactions, "
          f"{len(first['risk']['indicators'])} indicator(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
