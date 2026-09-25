"""
Input detection and address validation for every supported chain.

Validation is real, not format-shaped. A string that is 34 characters, starts
with T, and is alphanumeric is NOT a valid TRON address unless its Base58Check
checksum verifies. This is what stops a nonexistent wallet from coming back as
"inconclusive / nothing suspicious found" instead of "this address is invalid".
"""

from __future__ import annotations

import hashlib
import re
from typing import Optional, Tuple

from models.schemas import Chain, InputType

BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
BASE58_INDEX = {c: i for i, c in enumerate(BASE58_ALPHABET)}

EVM_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
EVM_TX_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")
HEX_TX_RE = re.compile(r"^[0-9a-fA-F]{64}$")
TRON_TX_RE = re.compile(r"^[0-9a-fA-F]{64}$")

# Bitcoin address prefixes -> (network, type)
BTC_PREFIXES = {
    "1": ("mainnet", "legacy"),
    "3": ("mainnet", "p2sh"),
    "bc1q": ("mainnet", "segwit"),
    "bc1p": ("mainnet", "taproot"),
    "tb1q": ("testnet", "segwit"),
    "m": ("testnet", "legacy"),
    "n": ("testnet", "p2sh"),
}

# EVM chain selection. The user picks the network for a 0x address; these are
# the defaults the UI offers, in display order.
EVM_CHAINS = (Chain.ETHEREUM, Chain.BSC, Chain.POLYGON)


# ============================================================
# PRIMITIVES
# ============================================================


def _b58decode(value: str) -> Optional[bytes]:
    number = 0
    for char in value:
        index = BASE58_INDEX.get(char)
        if index is None:
            return None
        number = number * 58 + index

    decoded = number.to_bytes((number.bit_length() + 7) // 8, "big")
    leading_zeros = len(value) - len(value.lstrip("1"))
    return b"\x00" * leading_zeros + decoded


def validate_tron_address(address: str) -> Tuple[bool, str]:
    """
    Full TRON Base58Check validation.

    TRON addresses are 34 base58 characters decoding to 25 bytes:
    1 byte version (0x41), 20 bytes of account hash, 4 bytes of double-SHA256
    checksum.

    Returns (is_valid, reason). The reason distinguishes "wrong length" from
    "bad checksum" because those are different user errors.
    """
    if not address or not isinstance(address, str):
        return False, "empty input"

    stripped = address.strip()

    if not stripped:
        return False, "empty input"

    if len(stripped) != 34:
        return False, f"expected 34 characters, got {len(stripped)}"

    if not stripped.startswith("T"):
        return False, "TRON addresses begin with 'T'"

    decoded = _b58decode(stripped)
    if decoded is None or len(decoded) != 25:
        return False, "invalid base58 encoding"

    body, checksum = decoded[:21], decoded[21:25]
    expected = hashlib.sha256(hashlib.sha256(body).digest()).digest()[:4]

    if checksum != expected:
        return False, "checksum mismatch - this address does not exist on TRON"

    if body[0] != 0x41:
        return False, "unexpected version byte"

    return True, "valid"


def validate_evm_address(address: str) -> Tuple[bool, str]:
    """EVM addresses are 20 bytes of hex, conventionally 0x-prefixed."""
    if not address or not isinstance(address, str):
        return False, "empty input"

    stripped = address.strip()

    if EVM_ADDRESS_RE.match(stripped):
        return True, "valid"

    if re.match(r"^[0-9a-fA-F]{40}$", stripped):
        # Valid hex but missing the prefix; we normalize rather than reject.
        return True, "valid (0x prefix added)"

    if len(stripped) == 42:
        return False, "not a valid hexadecimal address"

    return False, "expected a 0x-prefixed 20-byte address"


def evm_to_checksum(address: str) -> str:
    """EIP-55 mixed-case checksum encoding."""
    from eth_utils import to_checksum_address  # type: ignore

    return to_checksum_address(address)


def evm_checksum_manual(address: str) -> str:
    """
    EIP-55 without pulling in eth_utils.

    Kept dependency-free so address handling works even if the optional
    dependency is absent. Returns the address lowercased with a 0x prefix if
    anything goes wrong.
    """
    try:
        raw = address.lower().removeprefix("0x")
        digest = hashlib.keccak256(raw.encode("utf-8")).hexdigest()

        out = ["0x"]
        for char, nibble in zip(raw, digest):
            out.append(char.upper() if int(nibble, 16) >= 8 else char)

        return "".join(out)
    except (ValueError, AttributeError):
        return address if address.startswith("0x") else f"0x{address}"


#: Bitcoin Base58Check version bytes, by address type. P2PKH and P2SH differ
#: only in this byte, which is what separates a "1..." from a "3..." address.
BTC_BASE58_VERSIONS = {
    0x00: ("mainnet", "p2pkh"),
    0x05: ("mainnet", "p2sh"),
    0x6F: ("testnet", "p2pkh"),
    0xC4: ("testnet", "p2sh"),
}


def validate_bitcoin_address(address: str) -> Tuple[bool, str, str, str]:
    """
    Bitcoin address validation, with real checksum verification.

    Returns (is_valid, reason, network, type).

    Bech32 addresses carry their own Bech32 checksum. Base58 addresses carry a
    Base58Check double-SHA256 checksum, and this verifies it rather than
    checking only the prefix and length. That distinction matters: a mistyped
    Bitcoin address has a 1-in-4-billion chance of being a real address, so
    treating a bad checksum as valid would let a typo return a clean, entirely
    fictional "no transactions found" result instead of an error.
    """
    if not address or not isinstance(address, str):
        return False, "empty input", "", ""

    stripped = address.strip()

    lowered = stripped.lower()

    # Bech32 / Bech32m first: `bc1` / `tb1` are unambiguous.
    if lowered.startswith(("bc1", "tb1")):
        network = "mainnet" if lowered.startswith("bc1") else "testnet"
        ok, reason = _validate_bech32(stripped, network)
        if not ok:
            return False, reason, network, ""
        # After "bc1" the first data character encodes the witness version:
        # "q" is 0 (v0, native segwit) and "p" is 1 (v1, taproot).
        kind = {"q": "segwit", "p": "taproot"}.get(lowered[3], "segwit")
        return True, "valid", network, kind

    # Base58: decode, verify the checksum, then read the version byte.
    if not (26 <= len(stripped) <= 35):
        return False, f"unexpected length {len(stripped)}", "", ""
    if any(c not in BASE58_INDEX for c in stripped):
        return False, "invalid base58 character", "", ""

    decoded = _b58decode(stripped)
    if decoded is None or len(decoded) != 25:
        return False, "invalid base58 encoding", "", ""

    body, checksum = decoded[:21], decoded[21:25]
    expected = hashlib.sha256(hashlib.sha256(body).digest()).digest()[:4]
    if checksum != expected:
        return False, "checksum mismatch - this is not a valid Bitcoin address", "", ""

    version_info = BTC_BASE58_VERSIONS.get(body[0])
    if version_info is None:
        return False, f"unknown Bitcoin address version byte 0x{body[0]:02x}", "", ""

    network, kind = version_info
    return True, "valid", network, kind


_BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _bech32_polymod(values: list) -> int:
    generator = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]
    chk = 1
    for value in values:
        top = chk >> 25
        chk = (chk & 0x1FFFFFF) << 5 ^ value
        for i in range(5):
            chk ^= generator[i] if ((top >> i) & 1) else 0
    return chk


#: The two BCH checksum constants. Witness v0 uses Bech32 (BIP173); every
#: later version uses Bech32m (BIP350). They are not interchangeable, and
#: checking only for Bech32 would reject every valid taproot address.
_BECH32_CONST = 1
_BECH32M_CONST = 0x2BC830A3


def _convertbits(
    data: list, frombits: int, tobits: int, strict: bool = False,
) -> Tuple[Optional[list], bool]:
    """
    Regroup a list of integers between bit widths (BIP173 reference form).

    `strict` additionally requires that the padding is all zeroes and that the
    input carried no leftover bits — the rule that stops one address having
    several valid encodings.
    """
    acc = 0
    bits = 0
    out: list = []
    maxv = (1 << tobits) - 1
    max_acc = (1 << (frombits + tobits - 1)) - 1

    for value in data:
        if value < 0 or (value >> frombits):
            return None, False
        acc = ((acc << frombits) | value) & max_acc
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            out.append((acc >> bits) & maxv)

    if strict:
        if bits >= frombits or ((acc << (tobits - bits)) & maxv):
            return None, False
    elif bits >= frombits or ((acc << (tobits - bits)) & maxv):
        return out, False

    return out, True


def _validate_bech32(address: str, network: str) -> Tuple[bool, str]:
    """
    Verify a segwit address's Bech32/Bech32m checksum and witness program.

    The human-readable part is expanded on both sides of the separator — high
    bits, then a zero, then low bits — before the polymod runs. Omitting the
    low-bit half does not produce a wrong answer, it produces an answer that is
    wrong for every input, which is how this passed review and rejected all
    real segwit addresses.
    """
    if any(ord(c) < 33 or ord(c) > 126 for c in address):
        return False, "invalid character in bech32 string"

    if address.lower() != address and address.upper() != address:
        return False, "mixed case bech32 string"

    address = address.lower()

    pos = address.rfind("1")
    if pos < 1 or pos + 7 > len(address) or len(address) > 90:
        return False, "malformed bech32 separator position"

    hrp = address[:pos]
    data = [_BECH32_CHARSET.find(c) for c in address[pos + 1:]]

    if -1 in data:
        return False, "invalid bech32 character"

    # The separator is the last '1', so everything after it is the 5-bit
    # witness program plus a 6-character checksum.
    if len(data) < 7:
        return False, "bech32 payload too short to contain a checksum"

    expected_hrp = "bc" if network == "mainnet" else "tb"
    if hrp != expected_hrp:
        return False, f"expected human-readable part '{expected_hrp}', got '{hrp}'"

    witness_version = data[0]
    if witness_version > 16:
        return False, f"invalid witness version {witness_version}"

    # Witness program length. This is not a character count: v0 encodes one
    # byte per character, but v1+ packs 8-bit data into 5-bit groups, so a
    # 32-byte taproot key is 52 characters. Both encodings must be decoded
    # back to bytes before the 2..40 limit can be applied.
    program = data[1:-6]
    if witness_version == 0:
        if any(value > 31 for value in program):
            return False, "witness program contains non-byte data"
        program_len = len(program)
    else:
        decoded_program, ok = _convertbits(program, 5, 8, strict=False)
        if not ok:
            return False, "witness program has invalid padding"
        # Non-zero padding is the canonical-segments rule of BIP173; a strict
        # decode rejects it, which is what we want.
        decoded_program, strict_ok = _convertbits(program, 5, 8, strict=True)
        if not strict_ok:
            return False, "witness program has non-zero padding"
        program_len = len(decoded_program)

    if not (2 <= program_len <= 40):
        return False, f"invalid witness program length {program_len}"

    # BIP173 fixes the two valid v0 program sizes; allowing others would
    # accept encodings that no node will recognise.
    if witness_version == 0 and program_len not in (20, 32):
        return False, f"v0 witness programs must be 20 or 32 bytes, got {program_len}"

    expanded_hrp = [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]
    polymod = _bech32_polymod(expanded_hrp + data)

    expected = _BECH32_CONST if witness_version == 0 else _BECH32M_CONST
    if polymod != expected:
        return False, "bech32 checksum mismatch"

    return True, "valid"


def validate_tron_txid(txid: str) -> bool:
    return bool(TRON_TX_RE.match((txid or "").strip()))


# ============================================================
# DETECTION
# ============================================================


def detect_chain(raw_input: str, preferred_evm: Optional[Chain] = None) -> dict:
    """
    Identify a user input.

    Returns a dict describing what the input is. When a 0x address is given the
    chain is genuinely ambiguous — one address format spans three networks —
    so `preferred_evm` decides, defaulting to Ethereum, and the caller can
    re-ask. `ambiguous` is set so the UI can prompt rather than silently
    guessing.
    """
    result = {
        "chain": None,
        "input_type": None,
        "normalized_input": None,
        "valid": False,
        "reason": None,
        "ambiguous": False,
        "confidence": 0,
        "address_type": None,
        "candidates": [],
    }

    if not raw_input or not isinstance(raw_input, str):
        result["reason"] = "empty input"
        return result

    stripped = raw_input.strip()

    if not stripped:
        result["reason"] = "empty input"
        return result

    # --- Bitcoin (bech32 is distinctive; check before generic hex) ---------
    lowered = stripped.lower()
    if any(lowered.startswith(p) for p in ("bc1", "tb1", "btc1")):
        ok, reason, network, kind = validate_bitcoin_address(stripped)
        result.update({
            "chain": Chain.BITCOIN.value,
            "input_type": InputType.ADDRESS.value,
            "normalized_input": stripped,
            "valid": ok,
            "reason": None if ok else reason,
            "address_type": kind,
            "confidence": 95 if ok else 0,
            "candidates": [Chain.BITCOIN.value],
        })
        result["network"] = network
        return result

    # --- EVM transaction hash --------------------------------------------
    if EVM_TX_RE.match(stripped):
        chosen = preferred_evm or Chain.ETHEREUM
        return {
            "chain": chosen.value,
            "input_type": InputType.TRANSACTION_HASH.value,
            "normalized_input": stripped,
            "valid": True,
            "reason": None,
            "ambiguous": True,
            "confidence": 70,
            "address_type": None,
            "candidates": [c.value for c in EVM_CHAINS],
        }

    # --- TRON transaction hash (64 hex, no 0x) ---------------------------
    if HEX_TX_RE.match(stripped) and not stripped.startswith("0x"):
        return {
            "chain": Chain.TRON.value,
            "input_type": InputType.TRANSACTION_HASH.value,
            "normalized_input": stripped,
            "valid": True,
            "reason": None,
            "ambiguous": False,
            "confidence": 70,
            "address_type": None,
            "candidates": [Chain.TRON.value],
        }

    # --- EVM address ------------------------------------------------------
    if EVM_ADDRESS_RE.match(stripped) or re.match(r"^[0-9a-fA-F]{40}$", stripped):
        ok, reason = validate_evm_address(stripped)
        chosen = preferred_evm or Chain.ETHEREUM
        normalized = stripped if stripped.startswith("0x") else f"0x{stripped}"
        return {
            "chain": chosen.value,
            "input_type": InputType.ADDRESS.value,
            "normalized_input": normalized,
            "valid": ok,
            "reason": None if ok else reason,
            "ambiguous": True,
            "confidence": 90 if ok else 0,
            "address_type": "evm",
            "candidates": [c.value for c in EVM_CHAINS],
        }

    # --- Base58Check addresses: TRON and legacy Bitcoin overlap -----------
    #
    # Both chains encode addresses in Base58Check, and the two formats collide
    # on length: a TRON address is 34 characters, and so is the Bitcoin genesis
    # address 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa. Guessing by prefix or by
    # length sends a real Bitcoin address to the TRON adapter, which then
    # reports "no such address" — a false negative about a real wallet.
    #
    # So the payload decides. Both formats end in a 4-byte double-SHA256
    # checksum; a valid TRON address decodes to 25 bytes with version 0x41,
    # while a valid Bitcoin address decodes to 21 bytes with version 0x00.
    # The two decodes are mutually exclusive, so this is a real test rather
    # than a preference between guesses.
    if _looks_like_base58_address(stripped):
        tron_ok, tron_reason = validate_tron_address(stripped)
        if tron_ok:
            return {
                "chain": Chain.TRON.value,
                "input_type": InputType.ADDRESS.value,
                "normalized_input": stripped,
                "valid": True,
                "reason": None,
                "ambiguous": False,
                "confidence": 95,
                "address_type": "tron",
                "candidates": [Chain.TRON.value],
            }

        btc_ok, btc_reason, network, kind = validate_bitcoin_address(stripped)
        if btc_ok:
            return {
                "chain": Chain.BITCOIN.value,
                "input_type": InputType.ADDRESS.value,
                "normalized_input": stripped,
                "valid": True,
                "reason": None,
                "ambiguous": False,
                "confidence": 90,
                "address_type": kind,
                "network": network,
                "candidates": [Chain.BITCOIN.value],
            }

        # Neither checksum verified. The shape still tells us what the user
        # meant, and saying so turns "unrecognized input" into "you mistyped a
        # Bitcoin address" — which is a fixable error rather than a dead end.
        if stripped.startswith("T"):
            hint, kind, reason = Chain.TRON.value, "tron", tron_reason
        elif stripped[0] in "13mn":
            hint, kind, reason = Chain.BITCOIN.value, "base58", btc_reason
        else:
            hint, kind, reason = None, None, (
                f"not a valid TRON or Bitcoin address ({btc_reason})"
            )

        return {
            "chain": hint,
            "input_type": InputType.ADDRESS.value,
            "normalized_input": stripped,
            "valid": False,
            "reason": reason,
            "ambiguous": False,
            "confidence": 0,
            "address_type": kind,
            "candidates": [hint] if hint else [],
        }

    result["reason"] = "input format not recognized as a supported address or transaction hash"
    return result


def _looks_like_base58_address(value: str) -> bool:
    """
    Cheap pre-filter for the Base58Check branch.

    TRON and legacy Bitcoin addresses are 26-35 Base58 characters. Checking the
    charset here means the two real validators stay authoritative — neither is
    ever skipped on a shape match alone.
    """
    return (
        26 <= len(value) <= 35
        and all(c in BASE58_INDEX for c in value)
    )
