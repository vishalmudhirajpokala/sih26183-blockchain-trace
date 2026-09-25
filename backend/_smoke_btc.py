"""Live smoke test for the Bitcoin adapter."""
import time

from adapters.bitcoin import BitcoinAdapter
from utils.http_client import HttpClient

# A long-lived, heavily-used address with a mix of inputs and outputs.
ADDR = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"

a = BitcoinAdapter()
print("capabilities:", a.capabilities())
print("valid addr  :", a.validate_address(ADDR))
print("valid txid  :", a.validate_transaction_hash(
    "4a5e1e4baab89f3a32518a88c31bc87f618f76673e2cc77ab2127b7afdeda33b"))
print("bad addr    :", a.validate_address("0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"))

client = HttpClient(deadline=time.monotonic() + 90)

print("\n--- network status ---")
ni = a.get_network_status(client)
print("  ", ni.to_dict())

print("\n--- single tx (genesis coinbase) ---")
tx = a.get_transaction("4a5e1e4baab89f3a32518a88c31bc87f618f76673e2cc77ab2127b7afdeda33b", client)
if tx:
    print("  hash  :", tx.hash[:24])
    print("  status:", tx.status, "block:", tx.block_number, "ts:", tx.timestamp)
    print("  from  :", tx.from_address, "-> to:", tx.to_address)
    print("  amount:", tx.amount, "BTC   fee:", tx.fee)
    print("  inputs :", len(tx.inputs), "outputs:", len(tx.outputs))
    print("  in[0]  :", tx.inputs[0] if tx.inputs else None)
    print("  out[0] :", {k: v for k, v in tx.outputs[0].items() if k != "scriptpubkey"} if tx.outputs else None)
else:
    print("  None returned")

print("\n--- trace from the Genesis address (depth 1) ---")
t0 = time.time()
r = a.trace(ADDR, client, max_depth=1, max_nodes=5, max_txs_per_node=3)
print(f"  status   : {r.status.value}  ({time.time()-t0:.1f}s)")
print("  detail   :", r.status_detail)
print(f"  nodes={len(r.nodes)} edges={len(r.edges)} txs={len(r.transactions)} examined={r.nodes_examined}")
print("  truncated:", r.truncated, r.truncation_reasons)
for tx in r.transactions[:3]:
    print(f"   tx {tx.hash[:20]}.. {tx.amount} BTC {tx.direction.value:9} "
          f"in={len(tx.inputs)} out={len(tx.outputs)} block={tx.block_number}")
for n in r.nodes[:5]:
    print(f"   node d={n.depth} {n.address[:20]} in={n.inbound} out={n.outbound} seed={n.is_seed}")

usage, cache = client.usage_summary()
print("  usage:", [(u.provider, u.ok, u.status_code) for u in usage][:8])
print("  cache:", cache)
client.close()
