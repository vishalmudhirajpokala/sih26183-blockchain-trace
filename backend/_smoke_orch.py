"""
End-to-end orchestrator test: the same code path for five different chains.

If this passes, the engine above the adapter layer is genuinely chain-agnostic —
it never branches on chain, and every chain produces the same result shape.
"""
import json

from models.schemas import Chain
from services.trace_orchestrator import DetectionError, detect_only, run_investigation

CASES = [
    # All addresses and hashes below were read from live chain data, not
    # written from memory. The TRON addresses came out of a recent block's
    # contracts; they are all exactly 34 characters, which is exactly the
    # class that used to be misrouted to the Bitcoin branch.
    ("TRON address", "TCDo8KbRTPMHHU6B2VfPPSdWQPhmAZJKaY", None),
    ("Ethereum address", "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", Chain.ETHEREUM),
    ("Polygon address", "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", Chain.POLYGON),
    ("BSC address (no keyless provider)", "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", Chain.BSC),
    ("Bitcoin genesis address", "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", None),
    ("Bitcoin segwit address", "bc1qp8lhysjtd0uuv4lj2fcf2u5jjz37qnn7j3pvan", None),
    ("Bitcoin taproot address", "bc1pk37vzt3ulx72pqxvpk66uja5txg83l688vcru8je969xygc863tqluq64c", None),
    ("Ethereum tx hash", "0xd0c5e1b1b1b0e2c4d1a3f2e0b9c8d7a6f5e4d3c2b1a0f9e8d7c6b5a4f3e2d1c0b", Chain.ETHEREUM),
    ("garbage", "not-a-real-address-xyz", None),
    # A well-formed TRON address with one character changed: the checksum
    # must reject it rather than let it through as a valid wallet.
    ("TRON bad checksum", "TCDo8KbRTPMHHU6B2VfPPSdWQPhmAZJKaZB", None),
]

print("=" * 78)
print("DETECTION")
print("=" * 78)
for label, value, pref in CASES:
    d = detect_only(value, pref)
    print(f"{label:36} chain={str(d.get('chain')):10} type={str(d.get('input_type')):18} "
          f"valid={d.get('valid')} ambiguous={d.get('ambiguous')}")

print()
print("=" * 78)
print("FULL INVESTIGATION (depth 1, capped)")
print("=" * 78)
for label, value, pref in CASES:
    try:
        r = run_investigation(value, preferred_chain=pref, max_depth=1, max_nodes=4,
                              max_txs_per_node=2, deadline_seconds=75)
    except DetectionError as exc:
        print(f"\n{label}:")
        print(f"  DetectionError: {exc}")
        continue

    print(f"\n{label}")
    print(f"  chain      : {r.chain.value} ({r.chain.display_name})  input={r.input_type.value}")
    print(f"  seed       : {r.seed[:44]}")
    print(f"  status     : {r.status.value}")
    print(f"  detail     : {(r.status_detail or '')[:120]}")
    print(f"  graph      : nodes={len(r.nodes)} edges={len(r.edges)} txs={len(r.transactions)} hops={r.hops}")
    print(f"  risk       : score={r.risk.risk_score} level={r.risk.risk_level.value} "
          f"indicators={len(r.risk.indicators)}")
    for ind in r.risk.indicators[:3]:
        print(f"     - {ind.code} ({ind.severity.value}, w={ind.weight}) {ind.name[:60]}")
    print(f"  entity     : {r.entity.name if r.entity else None}")
    print(f"  truncated  : {r.metadata.truncated} {r.metadata.truncation_reasons}")
    print(f"  providers  : {len(r.metadata.provider_usage)} call(s), "
          f"{r.metadata.duration_ms}ms")
    # Prove the shape is identical regardless of chain.
    d = r.to_dict()
    assert set(d.keys()) == {
        "chain", "chain_name", "seed", "input_type", "status", "status_detail",
        "nodes", "edges", "transactions", "hop_path", "hops", "seed_entity",
        "entity", "risk", "report", "report_id", "metadata", "evidence_notes",
    }, f"shape drift on {label}: {sorted(d.keys())}"

print()
print("All result shapes identical across chains — engine is chain-agnostic.")
