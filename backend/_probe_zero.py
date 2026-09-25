"""Are zero-value records real transfers, or contract calls being drawn as edges?

A forensic graph must not draw a value-transfer arrow for a call that moved
nothing. This prints every field that distinguishes the two.
"""
from utils.http_client import HttpClient, RequestCache

ADDR = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"
URL = f"https://eth.blockscout.com/api/v2/addresses/{ADDR}/transactions"

client = HttpClient(cache=RequestCache(), deadline=None)
resp = client.get_json(URL, provider="blockscout", use_cache=False)
items = (resp.data or {}).get("items") or []
print("ok:", resp.ok, "items:", len(items))

zero = 0
for it in items:
    try:
        value = int(it.get("value") or 0)
    except (TypeError, ValueError):
        value = None
    if value:
        continue
    zero += 1
    print()
    print("hash        :", it.get("hash"))
    print("value       :", it.get("value"))
    print("method      :", it.get("method"))
    print("type        :", it.get("type"))
    print("status      :", it.get("status"))
    print("result      :", it.get("result"))
    print("from        :", it.get("from", {}).get("hash"))
    print("to          :", (it.get("to") or {}).get("hash"))
    print("token_transfers:", len(it.get("token_transfers") or []))
    print("decoded_input:", str(it.get("raw_input"))[:66])

print()
print("zero-value transactions:", zero, "of", len(items))
client.close()
