# tags.py

"""
Curated TRON entity intelligence database.

This database is intentionally kept separate from the live TronScan
API. Only verified public TRON addresses should be added here.

TRON addresses normally begin with "T".

Do NOT add guessed addresses.
"""

KNOWN_TAGS = {

    # ============================================================
    # VERIFIED TRON EXCHANGES
    # ============================================================
    #
    # Example structure:
    #
    # "TRON_ADDRESS": {
    #     "type": "exchange",
    #     "name": "Binance",
    #     "network": "TRON",
    #     "source": "Verified public blockchain source",
    #     "confidence": 95
    # },


    # ============================================================
    # VERIFIED TRON MIXERS / OBSTRUCTION SERVICES
    # ============================================================


    # ============================================================
    # VERIFIED SANCTIONED TRON ADDRESSES
    # ============================================================


    # ============================================================
    # VERIFIED HIGH-RISK ENTITIES
    # ============================================================
}


# Normalize addresses for case-insensitive lookup.
_KNOWN_TAGS_LOWER = {
    address.strip().lower(): tag
    for address, tag in KNOWN_TAGS.items()
}


def is_tagged(address):
    """
    Look up a TRON address in the curated intelligence database.

    Args:
        address (str): TRON address.

    Returns:
        dict | None:
            The tag information if the address is known,
            otherwise None.
    """

    if not address:
        return None

    normalized_address = address.strip().lower()

    if not normalized_address:
        return None

    return _KNOWN_TAGS_LOWER.get(normalized_address)