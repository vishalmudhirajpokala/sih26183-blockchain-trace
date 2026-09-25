"""Probe the Bitcoin providers for real, keyless address-history capability."""
import time
from utils.http_client import HttpClient

c = HttpClient(deadline=time.monotonic() + 90)

# A well-known, permanently reused Bitcoin address (Genesis coinbase, block 0).
ADDR = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"

CHECKS = [
    ("blockstream tip", "GET", "https://blockstream.info/api/blocks/tip/height", None),
    ("mempool tip", "GET", "https://mempool.space/api/blocks/tip/height", None),
    ("bs address", "GET", f"https://blockstream.info/api/address/{ADDR}", None),
    ("bs txs", "GET", f"https://blockstream.info/api/address/{ADDR}/txs", None),
    ("bs utxo", "GET", f"https://blockstream.info/api/address/{ADDR}/utxo", None),
    ("mempool addr", "GET", f"https://mempool.space/api/address/{ADDR}", None),
    # Does the Esplora address endpoint carry a public label?
    ("bs address detail", "GET", f"https://blockstream.info/api/address/{ADDR}", None),
]

for label, method, url, params in CHECKS:
    if method == "GET":
        r = c.get_json(url, params=params, provider=f"probe-{label}", use_cache=False)
    else:
        r = c.post_json(url, body=params, provider=f"probe-{label}", use_cache=False)
    d = r.data
    n = len(d) if isinstance(d, list) else ("dict" if isinstance(d, dict) else None)
    print(f"{label:20} ok={r.ok!s:5} code={r.status_code} n={n} err={r.error}")
    if isinstance(d, dict):
        keys = sorted(d.keys())
        print("     keys:", keys[:14])
        for k in ("chain_stats", "mempool_stats", "address", "tx_count", "funded_txo_sum", "spent_txo_sum"):
            if k in d:
                v = d[k]
                print(f"     {k}:", v if not isinstance(v, dict) else {kk: v[kk] for kk in list(v)[:6]})
    if isinstance(d, list) and d and isinstance(d[0], dict):
        print("     item keys:", sorted(d[0].keys())[:16])

print()
print("--- a real tx to see vin/vout shape ---")
r = c.get_json("https://blockstream.info/api/tx/4a5e1e4baab89f3a32518a88c31bc87f618f76673e2cc77ab2127b7afdeda33b",
               provider="probe-tx", use_cache=False)
d = r.data or {}
print("ok=", r.ok, "keys:", sorted(d.keys()) if isinstance(d, dict) else None)
if isinstance(d, dict):
    print("status:", d.get("status"), "fee:", d.get("fee"), "size:", d.get("size"), "weight:", d.get("weight"))
    print("vin[0] keys :", sorted((d.get("vin") or [{}])[0].keys()))
    print("vin[0]      :", json_short := {k: v for k, v in ((d.get("vin") or [{}])[0]).items() if k in ("txid", "vout", "prevout", "scriptsig", "sequence")})
    print("vout[0] keys:", sorted((d.get("vout") or [{}])[0].keys()))
    v0 = (d.get("vout") or [{}])[0]
    print("vout[0]     :", {"scriptpubkey_type": v0.get("scriptpubkey_type"), "value": v0.get("value"),
                           "scriptpubkey_address": (v0.get("scriptpubkey") or {}).get("address")})

c.close()
