"""Diagnose the TRON provider_error: replay the adapter's calls with full error text."""
from services.chain_registry import get_adapter
from models.schemas import Chain
from utils.http_client import HttpClient, RequestCache

ADDR = "TCDo8KbRTPMHHU6B2VfPPSdWQPhmAZJKaY"
adapter = get_adapter(Chain.TRON)
client = HttpClient(cache=RequestCache(), deadline=None)

print("adapter:", type(adapter).__name__)
print("validate:", adapter.validate_address(ADDR))
print("unavailable_reason:", adapter.unavailable_reason())
print("capabilities:", adapter.capabilities())
print()

for name in ("get_network_status", "get_outgoing_transfers", "get_incoming_transfers"):
    fn = getattr(adapter, name, None)
    if fn is None:
        print(f"{name}: NOT IMPLEMENTED")
        continue
    try:
        out = fn(ADDR, client)
        data = getattr(out, "data", out)
        print(f"{name}: ok -> {str(data)[:220]}")
    except Exception as exc:
        print(f"{name}: RAISED {type(exc).__name__}: {exc}")

print()
print("--- raw request with the error surfaced ---")
for url in [
    f"https://api.trongrid.io/v1/accounts/{ADDR}/transactions?limit=3",
    f"https://api.trongrid.io/v1/accounts/{ADDR}/transactions/trc20?limit=3",
]:
    try:
        r = client.get(url, use_cache=False)
        print(f"GET {url[-60:]}: {r.status_code if hasattr(r, 'status_code') else r}")
    except Exception as exc:
        print(f"GET {url[-60:]}: {type(exc).__name__}: {exc}")

client.close()
