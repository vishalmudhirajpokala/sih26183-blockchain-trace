"""
Token identity for EVM chains: who is this token *really*?

WHY THIS EXISTS
---------------

An ERC-20 contract says what it is. `symbol()` and `name()` are functions the
token's own author wrote, they are not enforced by anything, and anyone can
deploy a contract that returns "USDT" from both. This is the oldest and still
most effective token trick there is, and it is a direct attack on exactly the
product this is: a tool whose entire claim is "I will tell you who received
the money" is worthless, or worse than worthless, if it will also tell you
that a scammer's contract is Tether.

So no on-chain string is trusted here. Every symbol and name is either
confirmed against a registry of addresses verified by reading the chain, or
carried as an unverified self-report and labelled as one.

THE REGISTRY IS EARNED, NOT REMEMBERED
--------------------------------------

Every entry below was read off the chain with `eth_call` against
`symbol()`, `name()` and `decimals()`, and the stored symbol is the value the
contract actually returns -- not what the asset is conventionally called.

That distinction is not pedantry. Polygon USDT at
`0xc2132D05D31c914a87C6611C10748AEb04B58e8F` returns the symbol **"USDT0"**,
not "USDT", because it was upgraded. A registry written from memory would have
recorded it as "USDT", and then the spoofing check below would have read the
token's honest self-report as an impostor and flagged the real Polygon USDT as
a fake. A wrong "fix" that cries wolf on the genuine article teaches every
reader to ignore the warning, which is worse than having none.

The same applies to bridged variants: `0x2791Bca1...` on Polygon returns
"USDC" and is a legitimate bridge asset, so it is registered as a verified
USDC-family address. It is not an impostor, and the registry is where that
distinction is recorded.

TRON IS DELIBERATELY ABSENT
---------------------------

TRC-20 decimal and symbol handling is untouched by this module and by every
change made alongside it. The registry is EVM-only, and the adapter calls below
are EVM-only. If a TRON label is wrong, it is a separate finding and it should
be fixed on its own evidence rather than swept into an EVM change.
"""

import re
import unicodedata
from typing import Any, Dict, Optional, Tuple

from models.schemas import Chain


#: Verified token identities, keyed by chain then lowercased contract address.
#:
#: `symbol` and `name` are what the contract returns on chain, read via
#: `eth_call`. `decimals` is likewise read, not assumed: BSC USDT is 18 and
#: Ethereum USDT is 6, and a tool that hardcoded either would misreport the
#: other by a factor of a trillion.
#:
#: `aliases` lists every symbol string this address legitimately answers to, so
#: an honest self-report after an upgrade (USDT -> USDT0) is recognised rather
#: than flagged as spoofing.
VERIFIED_TOKENS: Dict[Chain, Dict[str, Dict[str, Any]]] = {
    Chain.ETHEREUM: {
        "0xdac17f958d2ee523a2206206994597c13d831ec7": {
            "symbol": "USDT", "name": "Tether USD", "decimals": 6,
            "aliases": ("USDT",),
        },
        "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": {
            "symbol": "USDC", "name": "USD Coin", "decimals": 6,
            "aliases": ("USDC",),
        },
        "0x6b175474e89094c44da98b954eedeac495271d0f": {
            "symbol": "DAI", "name": "Dai Stablecoin", "decimals": 18,
            "aliases": ("DAI",),
        },
        "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2": {
            "symbol": "WETH", "name": "Wrapped Ether", "decimals": 18,
            "aliases": ("WETH",),
        },
    },
    Chain.BSC: {
        "0x55d398326f99059ff775485246999027b3197955": {
            "symbol": "USDT", "name": "Tether USD", "decimals": 18,
            "aliases": ("USDT",),
        },
        "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d": {
            "symbol": "USDC", "name": "USD Coin", "decimals": 18,
            "aliases": ("USDC",),
        },
        "0xe9e7cea3dedca5984780bafc599bd69add087d56": {
            "symbol": "BUSD", "name": "BUSD Token", "decimals": 18,
            "aliases": ("BUSD",),
        },
    },
    Chain.POLYGON: {
        # Returns "USDT0" on chain, not "USDT". Recorded as read.
        "0xc2132d05d31c914a87c6611c10748aeb04b58e8f": {
            "symbol": "USDT0", "name": "USDT0", "decimals": 6,
            "aliases": ("USDT0", "USDT"),
        },
        # Bridged USDC. Reports "USDC", and is legitimate -- registered so the
        # spoof check does not mistake a real bridge asset for a fake.
        "0x2791bca1f2de4661ed88a30c99a7a9449aa84174": {
            "symbol": "USDC", "name": "USD Coin (PoS)", "decimals": 6,
            "aliases": ("USDC", "USDC.e"),
        },
        "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359": {
            "symbol": "USDC", "name": "USD Coin", "decimals": 6,
            "aliases": ("USDC",),
        },
    },
}


#: Every symbol string that belongs to a verified asset on some chain.
#:
#: This is the "reserved names" list. A contract outside the registry that
#: claims one of these is asserting it is an asset we know the real address of,
#: on this chain, and it is not it. That assertion is the thing worth warning
#: about, and it is cheap to check.
RESERVED_SYMBOLS: Dict[Chain, frozenset] = {
    chain: frozenset(
        alias
        for entry in tokens.values()
        for alias in entry.get("aliases", ())
    )
    for chain, tokens in VERIFIED_TOKENS.items()
}


# Unicode categories that must never survive into displayed text.
#
# Cf covers format characters, which is where the genuinely dangerous ones live:
# U+200B-200F zero-width and directional marks, U+202A-202E bidi overrides,
# U+2066-2069 isolates, and U+E0000-E007F tag characters. A token symbol of
# "US\u200bDT" renders to the eye as "USDT" and copies as "USDT" on most
# systems, which is the whole point. Cc/Cs/Co/Cn are control, surrogate, private
# use and unassigned.
_INVISIBLE_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn"})

#: Whitespace is legitimate inside a token name ("USD Coin"), so it is allowed
#: explicitly after the category filter rather than by weakening the filter.
_LEGAL_SPACE = frozenset({" "})


def sanitize_onchain_text(value: Any) -> Tuple[str, bool]:
    """
    Strip characters from a token-supplied string that must not be displayed.

    Returns `(clean_text, had_hidden_characters)`.

    The second value is not a diagnostic to be discarded. The presence of
    invisible characters in a symbol is, on its own, a spoofing signal: there
    is no legitimate reason for a token name to contain a zero-width space or a
    bidirectional override, and a scammer who knows his symbol will not match a
    filter will reach for exactly these. So the characters are removed from what
    the reader sees *and* their presence is reported upward, because hiding the
    evidence while quietly cleaning the string would leave the reader with a
    tidy label and no idea why it should be doubted.
    """
    if value is None:
        return "", False

    text = value if isinstance(value, str) else str(value)

    # Normalising first means a decomposed sequence cannot be reassembled into
    # an invisible character after the filter has already run.
    text = unicodedata.normalize("NFKC", text)

    kept: list = []
    hidden = False
    for char in text:
        if char in _LEGAL_SPACE:
            kept.append(char)
            continue
        if unicodedata.category(char) in _INVISIBLE_CATEGORIES:
            hidden = True
            continue
        kept.append(char)

    return "".join(kept).strip(), hidden


def _normalise_symbol(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


class TokenVerdict:
    """
    The outcome of checking one transfer's token contract against the registry.

    `tier` is the word that matters, and it is one of:

      "verified"    the address is in the registry for this chain. The registry's
                    values are used, not the contract's self-report.
      "spoofed"     the contract claims a reserved symbol for this chain but is
                    not the verified address for it. Displayed as a warning and
                    never as the real asset.
      "unverified"  a real contract, no claim on a reserved name. Its symbol is
                    shown because it is the only information available, labelled
                    as a self-report.
    """

    __slots__ = ("symbol", "name", "decimals", "tier", "contract", "claimed_symbol",
                 "hidden_characters")

    def __init__(
        self,
        symbol: str,
        name: str,
        decimals: Optional[int],
        tier: str,
        contract: Optional[str],
        claimed_symbol: Optional[str] = None,
        hidden_characters: bool = False,
    ) -> None:
        self.symbol = symbol
        self.name = name
        self.decimals = decimals
        self.tier = tier
        self.contract = contract
        self.claimed_symbol = claimed_symbol
        self.hidden_characters = hidden_characters

    @property
    def is_verified(self) -> bool:
        return self.tier == "verified"

    @property
    def is_spoofed(self) -> bool:
        return self.tier == "spoofed"

    def display_symbol(self) -> str:
        """
        What to put in an asset column.

        A spoofed token is never rendered under the name it claims. The claimed
        symbol stays visible, because it is the evidence, but it is marked, so
        the number beside it cannot be read as dollars.
        """
        if self.tier == "spoofed":
            return f"UNVERIFIED (claims {self.claimed_symbol})"
        if self.tier == "unverified" and self.hidden_characters:
            return f"{self.symbol} (unverified)"
        if self.tier == "unverified":
            return f"{self.symbol} (unverified)"
        return self.symbol

    def note(self) -> str:
        """
        A sentence explaining the tier, for the evidence list.

        Empty for a verified token: there is nothing to warn about, and padding
        every ordinary USDT transfer with a paragraph about how it was verified
        would bury the transfers that actually need the reader's attention.
        """
        if self.tier == "verified":
            return ""
        if self.tier == "spoofed":
            text = (
                f"Token {self.contract} reports its symbol as "
                f"{self.claimed_symbol!r}, but that is not the verified "
                f"{self.claimed_symbol} contract on this chain. Amounts in this "
                f"row are denominated in an asset of unknown value and must not "
                f"be read as {self.claimed_symbol}."
            )
            if self.hidden_characters:
                text += (
                    " Its symbol also contains invisible or directional unicode "
                    "characters, which no legitimate token name needs."
                )
            return text
        text = (
            f"Token {self.contract} is not in the verified registry. Its symbol "
            f"and decimals are the contract's own claims about itself and have "
            f"not been confirmed."
        )
        if self.hidden_characters:
            text += (
                " Its symbol contains invisible or directional unicode characters, "
                "which is itself a spoofing indicator."
            )
        return text

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "decimals": self.decimals,
            "tier": self.tier,
            "contract": self.contract,
            "claimed_symbol": self.claimed_symbol,
            "hidden_characters": self.hidden_characters,
        }


def classify_token(
    chain: Chain,
    contract: Optional[str],
    reported_symbol: Optional[str] = None,
    reported_name: Optional[str] = None,
    reported_decimals: Optional[int] = None,
) -> TokenVerdict:
    """
    Decide what a token contract actually is, and how far to trust what it says.

    `reported_*` are the values a provider returned. They are per-transfer and
    per-contract -- every transfer carries its own token address, and this
    function is called once per transfer, so a symbol can never be inherited
    from a neighbouring transfer or from the subject of the trace.

    What this function does *not* do is believe them.
    """
    clean_symbol, symbol_hidden = sanitize_onchain_text(reported_symbol)
    clean_name, name_hidden = sanitize_onchain_text(reported_name)
    hidden = symbol_hidden or name_hidden

    registry = VERIFIED_TOKENS.get(chain) or {}
    key = (contract or "").strip().lower()

    # 1. The address is a verified asset. The registry wins over the contract.
    if key in registry:
        entry = registry[key]
        return TokenVerdict(
            symbol=entry["symbol"],
            name=entry["name"],
            decimals=entry["decimals"],
            tier="verified",
            contract=contract,
            claimed_symbol=clean_symbol or None,
            hidden_characters=hidden,
        )

    claimed = _normalise_symbol(clean_symbol)
    reserved = RESERVED_SYMBOLS.get(chain) or frozenset()
    reserved_normalised = {_normalise_symbol(s) for s in reserved}

    # 2. Claims a reserved name, is not the verified address for it.
    if claimed and claimed in reserved_normalised:
        return TokenVerdict(
            symbol=clean_symbol or "UNKNOWN",
            name=clean_name,
            decimals=reported_decimals,
            tier="spoofed",
            contract=contract,
            claimed_symbol=clean_symbol or None,
            hidden_characters=hidden,
        )

    # 3. Some other contract. Its own report, clearly marked as its own report.
    return TokenVerdict(
        symbol=clean_symbol or "UNKNOWN",
        name=clean_name,
        decimals=reported_decimals,
        tier="unverified",
        contract=contract,
        claimed_symbol=clean_symbol or None,
        hidden_characters=hidden,
    )


def is_verified_contract(chain: Chain, address: Optional[str]) -> bool:
    """
    True when this address is a known token contract on this chain.

    Used to decide whether a node in the graph is infrastructure. It is a
    registry lookup and costs nothing; it is deliberately *not* the same test as
    "is this a contract", which needs `eth_getCode` and is only asked about the
    subject.
    """
    key = (address or "").strip().lower()
    return bool(key) and key in (VERIFIED_TOKENS.get(chain) or {})
