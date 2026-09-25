import time
from utils.http_client import HttpClient
a = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"
c = HttpClient(deadline=time.monotonic()+60)
r = c.get_json("https://eth.blockscout.com/api/v2/addresses/%s/token-transfers" % a,
                params={"filter":"from"}, provider="probe", use_cache=False)
items = r.data.get("items") or []
print("n =", len(items))
for it in items[:3]:
    tok = it.get("token") or {}
    ti = tok.get("token_info") or tok.get("tokenInfo") or {}
    print("----")
    print("  transaction_hash:", it.get("transaction_hash"))
    print("  tx_hash         :", it.get("tx_hash"))
    print("  block_number    :", it.get("block_number"))
    print("  timestamp       :", it.get("timestamp"))
    print("  total           :", it.get("total"))
    print("  to(hash)        :", (it.get("to") or {}).get("hash") if isinstance(it.get("to"), dict) else it.get("to"))
    print("  token.type      :", tok.get("type"))
    print("  token.address   :", tok.get("address_hash") or tok.get("address"))
    print("  token_info keys :", sorted(ti.keys()) if ti else None)
    print("  symbol/decimals :", ti.get("symbol"), ti.get("decimals"))
c.close()
