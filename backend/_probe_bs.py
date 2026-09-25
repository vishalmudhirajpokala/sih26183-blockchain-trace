import json, time
from utils.http_client import HttpClient
a = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"
c = HttpClient(deadline=time.monotonic()+60)
for path, params in [
    ("/addresses/%s/token-transfers" % a, {"filter":"from"}),
    ("/addresses/%s/token-transfers" % a, {"filter":"to"}),
    ("/addresses/%s/transactions" % a, {"filter":"from"}),
    ("/addresses/%s/internal-transactions" % a, {}),
]:
    r = c.get_json("https://eth.blockscout.com/api/v2"+path, params=params, provider="probe", use_cache=False)
    d = r.data if isinstance(r.data, dict) else {}
    items = d.get("items") or []
    print(f"{path.split('/')[-1]:22} filter={params.get('filter','-'):5} ok={r.ok} n={len(items)} err={r.error}")
    if items:
        it = items[0]
        print("    keys:", sorted(it.keys())[:18])
        print("    from:", it.get("from"), "to:", it.get("to"))
        print("    total:", it.get("total"), "token:", json.dumps(it.get("token"))[:200])
c.close()
