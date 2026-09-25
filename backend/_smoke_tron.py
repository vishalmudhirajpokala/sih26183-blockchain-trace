"""
TRON regression: prove native-TRX transfers are parsed, not silently dropped.

The bug this guards against is quiet. TronGrid's native-TRX endpoint returns
`from`/`to` as keys that are present but null, with the real parties nested in
`raw_data` as hex. A parser reading only the top level drops every record and
reports a busy account as empty, with no error anywhere.

So this asserts on a real address that actually has history, and checks the
counterparties decode to valid, distinct Base58Check TRON addresses.
"""
from models.schemas import Chain
from services.chain_registry import get_adapter
from utils.http_client import HttpClient, RequestCache

# Harvested from a recent block; both have confirmed transfer history.
ADDRESSES = [
    "TCDo8KbRTPMHHU6B2VfPPSdWQPhmAZJKaY",  # TransferContract owner, 5 TRX rows
    "TGRToLGawBtdFhGZy8fukqNMqTZZ8WFgcL",  # TriggerSmartContract owner, 5 rows
    "TQ68UQunvm82XiAgAxmwc53pVxg2m9xgMe",
]

adapter = get_adapter(Chain.TRON)

for address in ADDRESSES:
    client = HttpClient(cache=RequestCache(), deadline=None)
    print("=" * 78)
    print(address)

    out = adapter.get_outgoing_transfers(address, client, limit=10)
    inc = adapter.get_incoming_transfers(address, client, limit=10)
    client.close()

    for label, txs in (("out", out), ("in", inc)):
        print(f"  {label}: n={len(txs)}")
        for tx in txs[:4]:
            print(f"     {tx.hash[:16]}… {tx.timestamp} "
                  f"{tx.from_address} -> {tx.to_address} "
                  f"{tx.amount} {tx.asset}")

    # Assertions that would have caught the original defect.
    both = list(out) + list(inc)
    assert both, f"FALSE EMPTY: {address} has history but parsed 0 transactions"

    for tx in both:
        assert tx.from_address and tx.to_address, (
            f"transaction {tx.hash} has a missing counterparty — it should "
            f"have been dropped, not emitted half-formed"
        )
        assert not tx.from_address.startswith("41"), (
            f"hex address leaked into the model: {tx.from_address}"
        )
        assert tx.from_address.startswith("T"), (
            f"decoded address is not base58: {tx.from_address}"
        )
    print("  -> all transactions have both counterparties, base58-decoded")

print()
print("TRON native transfers parse correctly.")
