# trace.py

import os
import time
from datetime import datetime

import requests
from dotenv import load_dotenv
from tags import is_tagged


load_dotenv()


# ============================================================
# TRONSCAN API
# ============================================================

TRONSCAN_TX_URL = (
    "https://apilist.tronscanapi.com/api/transaction"
)

TRONSCAN_TRC20_URL = (
    "https://apilist.tronscanapi.com/api/token_trc20/transfers"
)

TRONSCAN_API_KEY = os.getenv(
    "TRONSCAN_API_KEY"
)


# ============================================================
# TRACE CONFIGURATION
# ============================================================

HTTP_TIMEOUT_SECONDS = 10
OVERALL_TIMEOUT_SECONDS = 60
MAX_TRANSACTIONS_PER_HOP = 5

RAPID_HOP_SECONDS = 300

FAN_OUT_THRESHOLD = 3
FAN_IN_THRESHOLD = 3


# ============================================================
# ENTITY CLASSIFICATION
# ============================================================

def classify_tag(tag):
    """
    Classify a public TronScan entity label.

    Curated verified addresses from tags.py
    are checked before this fallback layer.
    """

    if not tag:
        return None

    tag_lower = str(tag).lower()

    # --------------------------------------------------------
    # EXCHANGES
    # --------------------------------------------------------

    exchange_keywords = [
        "binance",
        "coinbase",
        "kraken",
        "okx",
        "bybit",
        "kucoin",
        "bitfinex",
        "gate.io",
        "gateio",
        "huobi",
        "bitget",
    ]

    for exchange in exchange_keywords:
        if exchange in tag_lower:
            return {
                "type": "exchange",
                "name": tag,
                "network": "TRON",
                "source_type": "tronscan_public",
            }

    # --------------------------------------------------------
    # MIXERS / OBSTRUCTION
    # --------------------------------------------------------

    mixer_keywords = [
        "tornado",
        "mixer",
        "mixing",
    ]

    for mixer in mixer_keywords:
        if mixer in tag_lower:
            return {
                "type": "mixer",
                "name": tag,
                "network": "TRON",
                "source_type": "tronscan_public",
            }

    # --------------------------------------------------------
    # SANCTIONS
    # --------------------------------------------------------

    sanctioned_keywords = [
        "sanction",
        "ofac",
    ]

    for keyword in sanctioned_keywords:
        if keyword in tag_lower:
            return {
                "type": "sanctioned",
                "name": tag,
                "network": "TRON",
                "source_type": "tronscan_public",
            }

    # --------------------------------------------------------
    # HIGH-RISK PUBLIC LABELS
    # --------------------------------------------------------

    high_risk_keywords = [
        "scam",
        "fraud",
        "phishing",
        "hack",
        "hacker",
        "exploit",
        "blacklist",
        "stolen",
        "malicious",
    ]

    for keyword in high_risk_keywords:
        if keyword in tag_lower:
            return {
                "type": "high_risk",
                "name": tag,
                "network": "TRON",
                "source_type": "tronscan_public",
            }

    return None


# ============================================================
# ADDRESS CLASSIFICATION
# ============================================================

def classify_address(address, tronscan_tag=None):
    """
    Classify a TRON address.

    Priority:
    1. Curated verified local intelligence
    2. TronScan public tag
    3. Unknown
    """

    if not address:
        return None

    # --------------------------------------------------------
    # 1. CURATED VERIFIED DATABASE
    # --------------------------------------------------------

    local_tag = is_tagged(address)

    if local_tag:
        return {
            **local_tag,
            "source_type": "curated_verified",
        }

    # --------------------------------------------------------
    # 2. TRONSCAN PUBLIC LABEL
    # --------------------------------------------------------

    if tronscan_tag:
        public_classification = classify_tag(
            tronscan_tag
        )

        if public_classification:
            return public_classification

    # --------------------------------------------------------
    # 3. UNKNOWN
    # --------------------------------------------------------

    return None


# ============================================================
# HTTP HEADERS
# ============================================================

def get_headers():
    headers = {}

    if TRONSCAN_API_KEY:
        headers["TRON-PRO-API-KEY"] = TRONSCAN_API_KEY

    return headers


# ============================================================
# TIMESTAMP EXTRACTION
# ============================================================

def extract_timestamp(transaction):
    """
    Extract a transaction timestamp from TronScan data.

    Supports:
    - Unix seconds
    - Unix milliseconds
    - numeric strings
    - ISO-8601 datetime strings
    - nested transaction objects
    - nested block objects
    - nested trigger information
    """

    if not isinstance(transaction, dict):
        return None

    # --------------------------------------------------------
    # COMMON TIMESTAMP FIELD NAMES
    # --------------------------------------------------------

    possible_fields = [
        "timestamp",
        "block_timestamp",
        "blockTimestamp",
        "transactionTime",
        "transaction_time",
        "time",
        "datetime",
        "date",
        "created_at",
        "createdAt",
    ]

    # --------------------------------------------------------
    # CHECK DIRECT FIELDS
    # --------------------------------------------------------

    for field in possible_fields:

        value = transaction.get(field)

        if value is None or value == "":
            continue

        # ----------------------------------------------------
        # NUMERIC TIMESTAMP
        # ----------------------------------------------------

        if isinstance(value, (int, float)):

            try:
                timestamp = float(value)

                # Milliseconds → seconds
                if timestamp > 10_000_000_000:
                    timestamp /= 1000

                if timestamp > 0:
                    return timestamp

            except (
                ValueError,
                TypeError,
                OverflowError,
            ):
                continue

        # ----------------------------------------------------
        # STRING TIMESTAMP
        # ----------------------------------------------------

        if isinstance(value, str):

            value_clean = value.strip()

            if not value_clean:
                continue

            # -----------------------------------------------
            # Numeric string
            # -----------------------------------------------

            try:
                timestamp = float(value_clean)

                # Milliseconds → seconds
                if timestamp > 10_000_000_000:
                    timestamp /= 1000

                if timestamp > 0:
                    return timestamp

            except (
                ValueError,
                TypeError,
                OverflowError,
            ):
                pass

            # -----------------------------------------------
            # ISO-8601 datetime
            # -----------------------------------------------

            try:
                iso_value = value_clean

                if iso_value.endswith("Z"):
                    iso_value = iso_value[:-1] + "+00:00"

                parsed = datetime.fromisoformat(
                    iso_value
                )

                return parsed.timestamp()

            except (
                ValueError,
                TypeError,
                OverflowError,
            ):
                pass

    # --------------------------------------------------------
    # CHECK COMMON NESTED OBJECTS
    # --------------------------------------------------------

    nested_objects = [
        transaction.get("transaction"),
        transaction.get("transactionInfo"),
        transaction.get("trigger_info"),
        transaction.get("triggerInfo"),
        transaction.get("block"),
        transaction.get("block_info"),
        transaction.get("blockInfo"),
    ]

    for nested in nested_objects:

        if not isinstance(nested, dict):
            continue

        result = extract_timestamp(nested)

        if result is not None:
            return result

    # --------------------------------------------------------
    # RECURSIVE SEARCH
    # --------------------------------------------------------

    for value in transaction.values():

        if isinstance(value, dict):

            result = extract_timestamp(value)

            if result is not None:
                return result

    return None


# ============================================================
# TRANSACTION EVIDENCE EXTRACTION
# ============================================================

def extract_transaction_evidence(transaction):
    """
    Extract transaction-level forensic evidence.

    Missing fields remain None rather than being fabricated.
    """

    if not isinstance(transaction, dict):
        return {
            "transaction_hash": None,
            "transaction_id": None,
            "block_number": None,
            "transaction_timestamp": None,
        }

    # --------------------------------------------------------
    # TRANSACTION HASH / ID
    # --------------------------------------------------------

    transaction_hash = (
        transaction.get("transaction_id")
        or transaction.get("transactionId")
        or transaction.get("transaction_hash")
        or transaction.get("transactionHash")
        or transaction.get("hash")
        or transaction.get("txID")
        or transaction.get("txid")
    )

    transaction_id = (
        transaction.get("transaction_id")
        or transaction.get("transactionId")
        or transaction.get("txID")
        or transaction.get("txid")
    )

    # --------------------------------------------------------
    # BLOCK NUMBER
    # --------------------------------------------------------

    block_number = (
        transaction.get("block")
        or transaction.get("blockNumber")
        or transaction.get("block_number")
    )

    # --------------------------------------------------------
    # TIMESTAMP
    # --------------------------------------------------------

    transaction_timestamp = extract_timestamp(
        transaction
    )

    return {
        "transaction_hash": transaction_hash,
        "transaction_id": transaction_id,
        "block_number": block_number,
        "transaction_timestamp": transaction_timestamp,
    }


# ============================================================
# RAPID-HOP DETECTION
# ============================================================

def calculate_rapid_hop(
    previous_timestamp,
    current_timestamp,
):
    if previous_timestamp is None:
        return False

    if current_timestamp is None:
        return False

    time_difference = abs(
        current_timestamp
        - previous_timestamp
    )

    return (
        time_difference
        <= RAPID_HOP_SECONDS
    )


# ============================================================
# TOKEN AMOUNT EXTRACTION
# ============================================================

def extract_token_amount(transfer):

    token_info = transfer.get(
        "tokenInfo",
        {},
    )

    token_symbol = (
        token_info.get("tokenAbbr")
        or token_info.get("tokenAbbrName")
        or token_info.get("symbol")
    )

    decimals = token_info.get(
        "tokenDecimal"
    )

    if decimals is None:
        decimals = token_info.get(
            "decimals"
        )

    raw_amount = None

    trigger_info = transfer.get(
        "trigger_info",
        {},
    )

    parameter = trigger_info.get(
        "parameter",
        {},
    )

    raw_amount = parameter.get(
        "value"
    )

    if raw_amount is None:
        raw_amount = transfer.get(
            "quant"
        )

    amount = None

    try:

        if raw_amount is not None:

            if decimals is not None:

                amount = (
                    int(raw_amount)
                    /
                    (
                        10
                        **
                        int(decimals)
                    )
                )

            else:

                amount = int(
                    raw_amount
                )

    except (
        ValueError,
        TypeError,
        OverflowError,
    ):

        amount = None

    return {
        "token": token_symbol,
        "amount": amount,
        "raw_amount": raw_amount,
        "decimals": decimals,
    }


# ============================================================
# TRC20 FAN-IN DETECTION
# ============================================================

def detect_trc20_fan_in(
    address,
    deadline,
):
    """
    Detect whether multiple unique wallets
    sent TRC20 tokens into this address.

    Behavioral indicator only.
    It does NOT establish fraudulent activity.
    """

    try:

        remaining = (
            deadline
            - time.monotonic()
        )

        if remaining <= 0:

            return {
                "fan_in": False,
                "incoming_senders": [],
                "incoming_count": 0,
            }

        response = requests.get(
            TRONSCAN_TRC20_URL,
            params={
                "toAddress": address,
                "limit": MAX_TRANSACTIONS_PER_HOP,
            },
            headers=get_headers(),
            timeout=min(
                HTTP_TIMEOUT_SECONDS,
                remaining,
            ),
        )

        response.raise_for_status()

        data = response.json()

    except (
        requests.exceptions.Timeout,
        requests.exceptions.RequestException,
        ValueError,
    ):

        return {
            "fan_in": False,
            "incoming_senders": [],
            "incoming_count": 0,
        }

    transfers = data.get(
        "token_transfers",
        [],
    )

    if not transfers:

        transfers = data.get(
            "data",
            [],
        )

    senders = set()

    for transfer in transfers:

        sender = (
            transfer.get("from_address")
            or transfer.get("fromAddress")
        )

        if not sender:
            continue

        if sender.lower() == address.lower():
            continue

        senders.add(
            sender.lower()
        )

    incoming_count = len(
        senders
    )

    fan_in = (
        incoming_count
        >= FAN_IN_THRESHOLD
    )

    if fan_in:

        print(
            "\n!!! FAN-IN DETECTED !!!"
        )

        print(
            "Wallet:",
            address,
        )

        print(
            "Unique incoming senders:",
            incoming_count,
        )

    return {
        "fan_in": fan_in,
        "incoming_senders": list(
            senders
        ),
        "incoming_count": incoming_count,
    }


# ============================================================
# TRACE WALLET
# ============================================================

def trace_wallet(
    address,
    depth=0,
    max_depth=5,
    _deadline=None,
    _visited=None,
    _path=None,
    _previous_timestamp=None,
):

    # ========================================================
    # API KEY CHECK
    # ========================================================

    if not TRONSCAN_API_KEY:

        return {
            "matched": False,
            "reason": "api_error",
            "detail": (
                "TRONSCAN_API_KEY is missing "
                "from .env"
            ),
        }

    # ========================================================
    # INITIALIZE STATE
    # ========================================================

    if _deadline is None:

        _deadline = (
            time.monotonic()
            + OVERALL_TIMEOUT_SECONDS
        )

    if _visited is None:
        _visited = set()

    if _path is None:
        _path = [address]

    normalized_address = (
        address.strip().lower()
    )

    if normalized_address in _visited:

        return {
            "matched": False,
            "reason": "already_visited",
            "detail": (
                "Address was already examined."
            ),
        }

    _visited.add(
        normalized_address
    )

    # ========================================================
    # TIMEOUT CHECK
    # ========================================================

    if time.monotonic() >= _deadline:

        return {
            "matched": False,
            "reason": "timeout",
            "detail": (
                "Overall tracing timeout reached."
            ),
        }

    # ========================================================
    # DEPTH CHECK
    # ========================================================

    if depth >= max_depth:

        return {
            "matched": False,
            "reason": "depth_exceeded",
            "detail": (
                f"Maximum depth of "
                f"{max_depth} reached."
            ),
        }

    # ========================================================
    # BEHAVIORAL STATE
    # ========================================================

    fan_out = False
    fan_in = False
    rapid_hops = False
    high_risk_entity = False

    # ========================================================
    # INCOMING FAN-IN
    # ========================================================

    fan_in_data = detect_trc20_fan_in(
        address,
        _deadline,
    )

    fan_in = fan_in_data.get(
        "fan_in",
        False,
    )

    # ========================================================
    # TRC20 OUTGOING TRANSFERS
    # ========================================================

    try:

        remaining = (
            _deadline
            - time.monotonic()
        )

        if remaining <= 0:

            return {
                "matched": False,
                "reason": "timeout",
                "detail": "No time remaining.",
            }

        response = requests.get(
            TRONSCAN_TRC20_URL,
            params={
                "fromAddress": address,
                "limit": MAX_TRANSACTIONS_PER_HOP,
            },
            headers=get_headers(),
            timeout=min(
                HTTP_TIMEOUT_SECONDS,
                remaining,
            ),
        )

        response.raise_for_status()

        data = response.json()

    except requests.exceptions.Timeout as e:

        return {
            "matched": False,
            "reason": "timeout",
            "detail": str(e),
            "fan_in": fan_in,
        }

    except requests.exceptions.RequestException as e:

        return {
            "matched": False,
            "reason": "api_error",
            "detail": str(e),
            "fan_in": fan_in,
        }

    except ValueError:

        return {
            "matched": False,
            "reason": "api_error",
            "detail": "invalid_json_response",
            "fan_in": fan_in,
        }

    transfers = data.get(
        "token_transfers",
        [],
    )

    if not transfers:

        transfers = data.get(
            "data",
            [],
        )

    print(
        f"\nFound {len(transfers)} TRC20 transfers "
        f"at depth {depth}."
    )

    # ========================================================
    # FAN-OUT
    # ========================================================

    destinations = set()

    for transfer in transfers:

        destination = (
            transfer.get("to_address")
            or transfer.get("toAddress")
        )

        if destination:

            destinations.add(
                destination.lower()
            )

    if len(destinations) >= FAN_OUT_THRESHOLD:

        fan_out = True

        print(
            "!!! FAN-OUT DETECTED !!!",
            address,
            "->",
            len(destinations),
            "unique destinations",
        )

    # ========================================================
    # INSPECT TRC20 TRANSFERS
    # ========================================================

    for transfer in transfers[
        :MAX_TRANSACTIONS_PER_HOP
    ]:

        if time.monotonic() >= _deadline:

            return {
                "matched": False,
                "reason": "timeout",
                "detail": (
                    "Overall tracing timeout reached."
                ),
                "fan_in": fan_in,
                "fan_out": fan_out,
            }

        # ----------------------------------------------------
        # ADDRESSES
        # ----------------------------------------------------

        from_address = transfer.get(
            "from_address"
        )

        to_address = transfer.get(
            "to_address"
        )

        if not from_address:

            from_address = transfer.get(
                "fromAddress"
            )

        if not to_address:

            to_address = transfer.get(
                "toAddress"
            )

        if not to_address:
            continue

        # ----------------------------------------------------
        # TRANSACTION EVIDENCE
        # ----------------------------------------------------

        transaction_evidence = (
            extract_transaction_evidence(
                transfer
            )
        )

        # ----------------------------------------------------
        # TIMESTAMP
        # ----------------------------------------------------

        current_timestamp = extract_timestamp(
            transfer
        )

        rapid_hop = calculate_rapid_hop(
            _previous_timestamp,
            current_timestamp,
        )

        if rapid_hop:

            rapid_hops = True

            print(
                "!!! RAPID HOP DETECTED !!!"
            )

        # ----------------------------------------------------
        # TRONSCAN TAGS
        # ----------------------------------------------------

        from_tag_info = transfer.get(
            "from_address_tag",
            {},
        )

        to_tag_info = transfer.get(
            "to_address_tag",
            {},
        )

        from_tag = None
        to_tag = None

        if isinstance(
            from_tag_info,
            dict,
        ):

            from_tag = (
                from_tag_info.get(
                    "from_address_tag"
                )
                or from_tag_info.get(
                    "name"
                )
                or from_tag_info.get(
                    "tag"
                )
            )

        elif isinstance(
            from_tag_info,
            str,
        ):

            from_tag = from_tag_info

        if isinstance(
            to_tag_info,
            dict,
        ):

            to_tag = (
                to_tag_info.get(
                    "to_address_tag"
                )
                or to_tag_info.get(
                    "name"
                )
                or to_tag_info.get(
                    "tag"
                )
            )

        elif isinstance(
            to_tag_info,
            str,
        ):

            to_tag = to_tag_info

        # ----------------------------------------------------
        # TOKEN INFORMATION
        # ----------------------------------------------------

        token_data = extract_token_amount(
            transfer
        )

        token_symbol = token_data[
            "token"
        ]

        amount = token_data[
            "amount"
        ]

        raw_amount = token_data[
            "raw_amount"
        ]

        decimals = token_data[
            "decimals"
        ]

        # ----------------------------------------------------
        # CONTRACT
        # ----------------------------------------------------

        trigger_info = transfer.get(
            "trigger_info",
            {},
        )

        contract_address = (
            trigger_info.get(
                "contract_address"
            )
            if isinstance(
                trigger_info,
                dict,
            )
            else None
        )

        if not contract_address:

            contract_address = transfer.get(
                "contract_address"
            )

        # ----------------------------------------------------
        # RISK FLAG
        # ----------------------------------------------------

        risk_transaction = transfer.get(
            "riskTransaction",
            False,
        )

        # ----------------------------------------------------
        # SENDER CLASSIFICATION
        # ----------------------------------------------------

        sender_classification = classify_address(
            from_address,
            from_tag,
        )

        if sender_classification:

            print(
                "!!! TRC20 SENDER MATCH !!!",
                from_address,
                sender_classification.get(
                    "name"
                ),
            )

            if (
                sender_classification.get(
                    "type"
                )
                == "high_risk"
            ):

                high_risk_entity = True

        # ----------------------------------------------------
        # DESTINATION CLASSIFICATION
        # ----------------------------------------------------

        recipient_classification = classify_address(
            to_address,
            to_tag,
        )

        # ====================================================
        # DESTINATION FOUND
        # ====================================================

        if recipient_classification:

            print(
                "!!! TRC20 DESTINATION MATCH !!!"
            )

            print(
                "Address:",
                to_address,
            )

            print(
                "Entity:",
                recipient_classification.get(
                    "name"
                ),
            )

            print(
                "Type:",
                recipient_classification.get(
                    "type"
                ),
            )

            print(
                "Source:",
                recipient_classification.get(
                    "source_type"
                ),
            )

            print(
                "Transaction:",
                transaction_evidence.get(
                    "transaction_hash"
                ),
            )

            if (
                recipient_classification.get(
                    "type"
                )
                == "high_risk"
            ):

                high_risk_entity = True

            return {
                "matched": True,
                "tag": recipient_classification,

                "hops": depth + 1,

                "path": (
                    _path
                    + [to_address]
                ),

                "token": token_symbol,
                "amount": amount,
                "raw_amount": raw_amount,
                "decimals": decimals,

                "contract_address": (
                    contract_address
                ),

                "from_address": from_address,
                "to_address": to_address,

                "risk_transaction": (
                    risk_transaction
                ),

                "rapid_hops": rapid_hops,
                "fan_out": fan_out,
                "fan_in": fan_in,

                "high_risk_entity": (
                    high_risk_entity
                ),

                # FORENSIC TRANSACTION EVIDENCE

                "transaction_hash": (
                    transaction_evidence.get(
                        "transaction_hash"
                    )
                ),

                "transaction_id": (
                    transaction_evidence.get(
                        "transaction_id"
                    )
                ),

                "block_number": (
                    transaction_evidence.get(
                        "block_number"
                    )
                ),

                "transaction_timestamp": (
                    transaction_evidence.get(
                        "transaction_timestamp"
                    )
                ),
            }

        # ----------------------------------------------------
        # RISK TRANSACTION
        # ----------------------------------------------------

        if risk_transaction is True:

            print(
                "!!! RISK TRANSACTION !!!",
                from_address,
                "->",
                to_address,
            )

        # ----------------------------------------------------
        # CONTINUE TRACING
        # ----------------------------------------------------

        if (
            to_address
            and to_address.lower()
            not in _visited
            and depth + 1 < max_depth
        ):

            print(
                f"TRC20 Depth {depth}: "
                f"{from_address} -> {to_address}"
            )

            result = trace_wallet(
                to_address,
                depth=depth + 1,
                max_depth=max_depth,
                _deadline=_deadline,
                _visited=_visited,
                _path=(
                    _path
                    + [to_address]
                ),
                _previous_timestamp=(
                    current_timestamp
                ),
            )

            if result.get(
                "matched"
            ):

                result["rapid_hops"] = (
                    result.get(
                        "rapid_hops",
                        False,
                    )
                    or rapid_hops
                )

                result["fan_out"] = (
                    result.get(
                        "fan_out",
                        False,
                    )
                    or fan_out
                )

                result["fan_in"] = (
                    result.get(
                        "fan_in",
                        False,
                    )
                    or fan_in
                )

                result["high_risk_entity"] = (
                    result.get(
                        "high_risk_entity",
                        False,
                    )
                    or high_risk_entity
                )

                return result

            if (
                result.get("reason")
                == "timeout"
            ):

                return result

    # ========================================================
    # NORMAL TRX TRANSACTIONS
    # ========================================================

    try:

        remaining = (
            _deadline
            - time.monotonic()
        )

        if remaining <= 0:

            return {
                "matched": False,
                "reason": "timeout",
                "detail": "No time remaining.",
                "fan_in": fan_in,
                "fan_out": fan_out,
            }

        response = requests.get(
            TRONSCAN_TX_URL,
            params={
                "fromAddress": address,
                "sort": "-timestamp",
                "limit": MAX_TRANSACTIONS_PER_HOP,
            },
            headers=get_headers(),
            timeout=min(
                HTTP_TIMEOUT_SECONDS,
                remaining,
            ),
        )

        response.raise_for_status()

        data = response.json()

    except requests.exceptions.Timeout as e:

        return {
            "matched": False,
            "reason": "timeout",
            "detail": str(e),
            "fan_in": fan_in,
            "fan_out": fan_out,
        }

    except requests.exceptions.RequestException as e:

        return {
            "matched": False,
            "reason": "api_error",
            "detail": str(e),
            "fan_in": fan_in,
            "fan_out": fan_out,
        }

    except ValueError:

        return {
            "matched": False,
            "reason": "api_error",
            "detail": "invalid_json_response",
            "fan_in": fan_in,
            "fan_out": fan_out,
        }

    transactions = data.get(
        "data",
        [],
    )

    # ========================================================
    # NORMAL TRX FAN-OUT
    # ========================================================

    normal_destinations = set()

    for tx in transactions:

        destination = tx.get(
            "toAddress"
        )

        if destination:

            normal_destinations.add(
                destination.lower()
            )

    if (
        len(normal_destinations)
        >= FAN_OUT_THRESHOLD
    ):

        fan_out = True

        print(
            "!!! NORMAL TRX FAN-OUT DETECTED !!!",
            address,
            "->",
            len(normal_destinations),
            "unique destinations",
        )

    # ========================================================
    # INSPECT NORMAL TRX TRANSACTIONS
    # ========================================================

    for tx in transactions[
        :MAX_TRANSACTIONS_PER_HOP
    ]:

        destination = tx.get(
            "toAddress"
        )

        if not destination:
            continue

        # ----------------------------------------------------
        # TRANSACTION EVIDENCE
        # ----------------------------------------------------

        transaction_evidence = (
            extract_transaction_evidence(
                tx
            )
        )

        # ----------------------------------------------------
        # TIMESTAMP
        # ----------------------------------------------------

        current_timestamp = extract_timestamp(
            tx
        )

        rapid_hop = calculate_rapid_hop(
            _previous_timestamp,
            current_timestamp,
        )

        if rapid_hop:

            rapid_hops = True

            print(
                "!!! RAPID HOP DETECTED !!!"
            )

        # ----------------------------------------------------
        # TRONSCAN TAG
        # ----------------------------------------------------

        destination_tag = tx.get(
            "toAddressTag"
        )

        tag_info = classify_address(
            destination,
            destination_tag,
        )

        # ====================================================
        # DESTINATION FOUND
        # ====================================================

        if tag_info:

            print(
                "!!! TRX DESTINATION MATCH !!!"
            )

            print(
                "Address:",
                destination,
            )

            print(
                "Entity:",
                tag_info.get(
                    "name"
                ),
            )

            print(
                "Type:",
                tag_info.get(
                    "type"
                ),
            )

            print(
                "Source:",
                tag_info.get(
                    "source_type"
                ),
            )

            print(
                "Transaction:",
                transaction_evidence.get(
                    "transaction_hash"
                ),
            )

            if (
                tag_info.get(
                    "type"
                )
                == "high_risk"
            ):

                high_risk_entity = True

            return {
                "matched": True,
                "tag": tag_info,

                "hops": depth + 1,

                "path": (
                    _path
                    + [destination]
                ),

                "rapid_hops": rapid_hops,
                "fan_out": fan_out,
                "fan_in": fan_in,

                "high_risk_entity": (
                    high_risk_entity
                ),

                "from_address": address,
                "to_address": destination,

                # FORENSIC TRANSACTION EVIDENCE

                "transaction_hash": (
                    transaction_evidence.get(
                        "transaction_hash"
                    )
                ),

                "transaction_id": (
                    transaction_evidence.get(
                        "transaction_id"
                    )
                ),

                "block_number": (
                    transaction_evidence.get(
                        "block_number"
                    )
                ),

                "transaction_timestamp": (
                    transaction_evidence.get(
                        "transaction_timestamp"
                    )
                ),
            }

        # ----------------------------------------------------
        # CONTINUE TRACING
        # ----------------------------------------------------

        if depth + 1 < max_depth:

            result = trace_wallet(
                destination,
                depth=depth + 1,
                max_depth=max_depth,
                _deadline=_deadline,
                _visited=_visited,
                _path=(
                    _path
                    + [destination]
                ),
                _previous_timestamp=(
                    current_timestamp
                ),
            )

            if result.get(
                "matched"
            ):

                result["rapid_hops"] = (
                    result.get(
                        "rapid_hops",
                        False,
                    )
                    or rapid_hops
                )

                result["fan_out"] = (
                    result.get(
                        "fan_out",
                        False,
                    )
                    or fan_out
                )

                result["fan_in"] = (
                    result.get(
                        "fan_in",
                        False,
                    )
                    or fan_in
                )

                result["high_risk_entity"] = (
                    result.get(
                        "high_risk_entity",
                        False,
                    )
                    or high_risk_entity
                )

                return result

            if (
                result.get("reason")
                == "timeout"
            ):

                return result

    # ========================================================
    # NO MATCH
    # ========================================================

    return {
        "matched": False,

        "reason": "no_match",

        "detail": (
            "No known exchange, mixer, sanctioned "
            "entity, high-risk entity, or tagged "
            "destination was reached."
        ),

        "rapid_hops": rapid_hops,
        "fan_out": fan_out,
        "fan_in": fan_in,

        "high_risk_entity": (
            high_risk_entity
        ),
    }