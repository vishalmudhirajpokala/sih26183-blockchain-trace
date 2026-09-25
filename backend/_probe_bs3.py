import time
from utils.http_client import HttpClient

a = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"
c = HttpClient(deadline=time.monotonic() + 60)


def brief(v):
    """Collapse a nested party/token object to the fields that matter."""
    if not isinstance(v, dict):
        return v
    out = {k: v.get(k) for k in (
        "hash", "address_hash", "type", "symbol", "name", "decimals",
        "reputation",
    ) if v.get(k) is not None}
    if "token" in v and isinstance(v["token"], dict):
        out["token.address_hash"] = v["token"].get("address_hash")
        out["token.symbol"] = v["token"].get("symbol")
        out["token.decimals"] = v["token"].get("decimals")
    if "token_info" in v and isinstance(v["token_info"], dict):
        out["token_info"] = {
            k: v["token_info"].get(k) for k in ("symbol", "decimals", "type")
        }
    return out


for label, path, params in [
    ("token-transfers?from", "/addresses/%s/token-transfers" % a, {"filter": "from"}),
    ("transactions?from", "/addresses/%s/transactions" % a, {"filter": "from"}),
]:
    r = c.get_json(
        "https://eth.blockscout.com/api/v2" + path,
        params=params, provider="probe", use_cache=False,
    )
    items = (r.data or {}).get("items") or []
    print("=" * 60)
    print(label, "n =", len(items))
    for it in items[:2]:
        print("  keys:", sorted(it.keys()))
        print("  token :", brief(it.get("token")))
        print("  total :", brief(it.get("total")))
        print("  from  :", brief(it.get("from")))
        print("  to    :", brief(it.get("to")))
        print("  ts    :", repr(it.get("timestamp")))

# The address endpoint -- what the label parser actually reads.
r = c.get_json(
    "https://eth.blockscout.com/api/v2/addresses/" + a,
    provider="probe", use_cache=False,
)
d = r.data or {}
print("=" * 60)
print("address keys:", sorted(d.keys()))
print("  name        :", d.get("name"))
print("  ens_domain  :", d.get("ens_domain_name"))
print("  is_contract :", d.get("is_contract"))
print("  is_verified :", d.get("is_verified"))
print("  public_tags :", d.get("public_tags"))
print("  private_tags:", d.get("private_tags"))
c.close()
