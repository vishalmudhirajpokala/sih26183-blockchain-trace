from models.schemas import Chain
from services.trace_orchestrator import run_investigation
r = run_investigation("0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", preferred_chain=Chain.ETHEREUM, max_depth=1, max_nodes=4, max_txs_per_node=2, deadline_seconds=75)
for t in r.transactions:
    print(f"{t.hash[:20]:22} {t.timestamp} {t.amount} {t.asset}")
assert all(t.hash for t in r.transactions), "EMPTY HASH"
assert all(t.timestamp for t in r.transactions), "MISSING TIMESTAMP"
print("OK: all Ethereum tx hashes and timestamps populated")
