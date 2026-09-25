"""Why does an Ethereum trace report the asset as 'ETHERFUN'?

Dumps the raw Blockscout token-transfer records so the symbol can be traced
back to the exact field it came from. Never assume a provider's schema.
"""
import json

from utils.http_client import HttpClient, RequestCache

ADDR = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"
URL = f"https://eth.blockscout.com/api/v2/addresses/{ADDR}/token-transfers"

client = HttpClient(cache=RequestCache(), deadline=None)
resp = client.get_json(URL, provider="blockscout", use_cache=False)
print("ok:", resp.ok, "status:", resp.status_code, "err:", resp.error)
data = resp.data or {}

print("top-level keys:", sorted(data.keys()))
items = data.get("items") or []
print("items:", len(items))

for it in items[:6]:
    print()
    print("item keys:", sorted(it.keys()))
    tok = it.get("token") or {}
    print("  token.type      :", tok.get("type"))
    print("  token.symbol    :", repr(tok.get("symbol")))
    print("  token.name      :", repr(tok.get("name")))
    print("  token.decimals  :", tok.get("decimals"))
    print("  token.address   :", tok.get("address_hash"))
    print("  token_info      :", repr(it.get("token_info")))
    print("  total           :", it.get("total"))
    tx = it.get("transaction") or {}
    print("  tx hash         :", (tx.get("hash") or "")[:20])
    print("  tx method       :", tx.get("method"))

client.close()
