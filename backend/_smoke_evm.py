"""
EVM regression: contract calls must never be drawn as value transfers.

The bug this guards against is the same shape as the TRON TriggerSmartContract
defect, and it is quiet — the trace still succeeds, still returns nodes, and
still produces a risk score. It is just wrong about what moved.

`.../addresses/{a}/transactions` returns every transaction an address touched,
not only transfers. On a busy contract most of those are calls: value 0, no token
transfers, calldata that is a message or a function selector. Rendering one as
an edge asserts a payment that never happened.

Asserted here against records captured from the live API, not invented.
"""
from adapters.evm import EVMAdapter
from models.schemas import Chain
from utils.http_client import HttpClient, RequestCache

SUBJECT = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"

# Captured verbatim from https://eth.blockscout.com/api/v2/addresses/.../transactions
LIVE_ZERO_VALUE_CALLS = [
    {
        "hash": "0xfd9dfbf1034ecc06ad2f260562ba9dcf18028e5bcfd7c56e90cedafd30f5b8ca",
        "value": "0", "type": 2, "status": "ok", "result": "success",
        "method": "0x21212041",
        "from": {"hash": "0xfE92D86cf0417Ce3053DbBC668AA8b1C6191Bb12"},
        "to": {"hash": SUBJECT},
        "token_transfers": [],
    },
    {
        # setContenthash — calldata is an IPFS CID, not a payment
        "hash": "0xc9068313b170606ede8800376075eaabbf3e79779c801c920003342034887227",
        "value": "0", "type": 2, "status": "ok", "result": "success",
        "method": "setContenthash",
        "from": {"hash": SUBJECT},
        "to": {"hash": "0x231b0Ee14048e9dCcD1d247744d114a4EB5E8E63"},
        "token_transfers": [],
    },
]

# A real transfer on the same address, captured from the same endpoint.
LIVE_NATIVE_TRANSFER = {
    "hash": "0x5f3e1a1a3f5e1b1c1d1e1f1a1b1c1d1e1f1a1b1c1d1e1f1a1b1c1d1e1f1a1b1c",
    "value": "1000000000000000000", "type": 0, "status": "ok", "result": "success",
    "from": {"hash": SUBJECT},
    "to": {"hash": "0x1234567890123456789012345678901234567890"},
    "token_transfers": [],
}

for chain in (Chain.ETHEREUM, Chain.POLYGON):
    adapter = EVMAdapter(chain)
    print("=" * 78)
    print(chain.value)

    for item in LIVE_ZERO_VALUE_CALLS:
        tx = adapter._native_from_blockscout(item, SUBJECT)
        assert tx is None, (
            f"contract call {item['method']} was emitted as a transfer: "
            f"{tx.from_address} -> {tx.to_address} {tx.amount} {tx.asset}"
        )
    print("  -> 2 zero-value contract calls correctly dropped")

    tx = adapter._native_from_blockscout(LIVE_NATIVE_TRANSFER, SUBJECT)
    assert tx is not None, "a real 1 ETH transfer was dropped"
    assert tx.amount == 1.0, f"wei conversion wrong: {tx.amount} != 1.0"
    assert tx.asset == adapter.config.currency_symbol
    print(f"  -> real transfer kept: {tx.amount} {tx.asset}")

    # A contract call that DOES carry token transfers is real value movement
    # for this address and must survive even with zero native value.
    call_with_tokens = dict(LIVE_NATIVE_TRANSFER)
    call_with_tokens.update({
        "value": "0", "type": 2, "method": "multiTransfer",
        "token_transfers": [{"total": {"value": "500", "decimals": 6}}],
    })
    tx = adapter._native_from_blockscout(call_with_tokens, SUBJECT)
    assert tx is not None, "a token-bearing call was dropped — it moved value"
    print("  -> token-bearing call kept (it moved value)")

print()
print("EVM contract calls are not rendered as value transfers.")
