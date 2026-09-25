"""
Detection regression: TRON and Bitcoin Base58Check must not collide.

Every case here is a real address (or a deliberately corrupted one). The
genesis address is the important case: it is exactly 34 characters, the same
length as every TRON address, so a length- or prefix-based detector sends it to
the wrong chain and reports a real Bitcoin wallet as nonexistent.
"""
from services.chain_detection import detect_chain

CASES = [
    # (input, expected_chain, expected_valid, note)
    # TRON addresses harvested live from a recent block's contracts.
    ("TCDo8KbRTPMHHU6B2VfPPSdWQPhmAZJKaY", "tron", True, "real TRON TransferContract owner"),
    ("TA5fD7115xMjn43n8LKDXuXehuab52rS34", "tron", True, "real TRON UnDelegateResource owner"),
    ("TGRToLGawBtdFhGZy8fukqNMqTZZ8WFgcL", "tron", True, "real TRON TriggerSmartContract owner"),
    # Bitcoin addresses harvested live from the genesis address's own outputs.
    ("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", "bitcoin", True, "Bitcoin P2PKH, 34 chars"),
    ("1BxhqQFFp925uMXgEtgTBBdCZxBwVFAw13", "bitcoin", True, "Bitcoin P2PKH, real"),
    ("bc1qp8lhysjtd0uuv4lj2fcf2u5jjz37qnn7j3pvan", "bitcoin", True, "Bitcoin v0 P2WPKH"),
    ("bc1pk37vzt3ulx72pqxvpk66uja5txg83l688vcru8je969xygc863tqluq64c", "bitcoin", True, "Bitcoin v1 P2TR"),
    # Corrupted checksums must be rejected, not accepted.
    ("TCDo8KbRTPMHHU6B2VfPPSdWQPhmAZJKaZB", "tron", False, "TRON w/ broken checksum"),
    ("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNZ", "bitcoin", False, "Bitcoin w/ broken checksum"),
    ("1BxhqQFFp925uMXgEtgTBBdCZxBwVFAw14", "bitcoin", False, "Bitcoin P2PKH bad checksum"),
    # Bech32 corruption must be caught by the Bech32 checksum.
    ("bc1qp8lhysjtd0uuv4lj2fcf2u5jjz37qnn7j3pvao", "bitcoin", False, "bech32 bad checksum"),
    # Too short to be any Base58Check address.
    ("TXLAQ63Xg1NAzckPwKHvzw", None, False, "22 chars, too short for any address"),
    ("not-an-address", None, False, "not base58 length"),
    ("0x0000000000000000000000000000000000000000", "ethereum", True, "EVM burn address"),
]

failures = 0
print("=" * 92)
print(f"{'input':46} {'chain':9} {'valid':6} {'type':9} note")
print("=" * 92)
for value, want_chain, want_valid, note in CASES:
    d = detect_chain(value)
    got_chain = d["chain"]
    got_valid = d["valid"]
    ok = (got_chain == want_chain) and (got_valid == want_valid)
    if not ok:
        failures += 1
    print(f"{'OK ' if ok else 'FAIL'} {value:41} {str(got_chain):9} "
          f"{str(got_valid):6} {str(d['address_type']):9} {note}")
    if not ok:
        print(f"       expected chain={want_chain} valid={want_valid}; got reason={d['reason']!r}")

print()
print(f"{len(CASES) - failures}/{len(CASES)} passed")
raise SystemExit(1 if failures else 0)
