# trace.py

import os
import time
from datetime import datetime

import requests
from dotenv import load_dotenv
from tags import is_tagged

load_dotenv()

# ============================================================
# TRONSCAN
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
# TRONGRID
# ============================================================

TRONGRID_BASE_URL = (
    "https://api.trongrid.io"
)

TRONGRID_TRX_URL = (
    f"{TRONGRID_BASE_URL}/v1/accounts/{{address}}/transactions"
)

TRONGRID_TRC20_URL = (
    f"{TRONGRID_BASE_URL}/v1/accounts/{{address}}/transactions/trc20"
)

TRONGRID_API_KEY = os.getenv(
    "TRONGRID_API_KEY"
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

MIN_REQUEST_INTERVAL_SECONDS = 0.35

# ============================================================
# REQUEST STATE
# ============================================================

_LAST_TRONSCAN_REQUEST_TIME = 0.0
_LAST_TRONGRID_REQUEST_TIME = 0.0


# ============================================================
# ENTITY CLASSIFICATION
# ============================================================

def classify_tag(tag):
    """
    Classify a public blockchain entity label.
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
    # MIXERS
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
    # HIGH-RISK
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
    Classification priority:

    1. Curated verified local intelligence
    2. TronScan public entity tag
    3. Unknown
    """

    if not address:
        return None

    # --------------------------------------------------------
    # 1. LOCAL CURATED INTELLIGENCE
    # --------------------------------------------------------

    local_tag = is_tagged(address)

    if local_tag:
        return {
            **local_tag,
            "source_type": "curated_verified",
        }

    # --------------------------------------------------------
    # 2. PUBLIC TRONSCAN TAG
    # --------------------------------------------------------

    if tronscan_tag:
        public_classification = classify_tag(
            tronscan_tag
        )

        if public_classification:
            return public_classification

    return None


# ============================================================
# HTTP HEADERS
# ============================================================

def get_tronscan_headers():
    headers = {}

    if TRONSCAN_API_KEY:
        headers["TRON-PRO-API-KEY"] = (
            TRONSCAN_API_KEY
        )

    return headers


def get_trongrid_headers():
    headers = {}

    if TRONGRID_API_KEY:
        headers["TRON-PRO-API-KEY"] = (
            TRONGRID_API_KEY
        )

    return headers


# ============================================================
# GENERIC RATE-LIMIT-AWARE REQUEST
# ============================================================

def _perform_request(
    url,
    params,
    headers,
    deadline,
    provider_name,
    max_attempts=2,
):
    """
    Perform a GET request with:

    - request spacing
    - 429 handling
    - Retry-After support
    - bounded exponential backoff
    - overall deadline protection
    """

    global _LAST_TRONSCAN_REQUEST_TIME
    global _LAST_TRONGRID_REQUEST_TIME

    if provider_name == "TronScan":
        last_request_time = (
            _LAST_TRONSCAN_REQUEST_TIME
        )
    else:
        last_request_time = (
            _LAST_TRONGRID_REQUEST_TIME
        )

    last_response = None

    for attempt in range(max_attempts):
        remaining = (
            deadline
            - time.monotonic()
        )

        if remaining <= 0:
            raise requests.exceptions.Timeout(
                "Overall tracing timeout reached."
            )

        # ----------------------------------------------------
        # REQUEST SPACING
        # ----------------------------------------------------

        elapsed = (
            time.monotonic()
            - last_request_time
        )

        if (
            elapsed
            < MIN_REQUEST_INTERVAL_SECONDS
        ):
            wait_for = (
                MIN_REQUEST_INTERVAL_SECONDS
                - elapsed
            )

            if wait_for >= remaining:
                raise requests.exceptions.Timeout(
                    "Overall tracing timeout reached."
                )

            time.sleep(wait_for)

        # ----------------------------------------------------
        # REQUEST
        # ----------------------------------------------------

        remaining = (
            deadline
            - time.monotonic()
        )

        try:
            response = requests.get(
                url,
                params=params,
                headers=headers,
                timeout=min(
                    HTTP_TIMEOUT_SECONDS,
                    remaining,
                ),
            )
        finally:
            now = time.monotonic()

            if provider_name == "TronScan":
                _LAST_TRONSCAN_REQUEST_TIME = now
                last_request_time = now
            else:
                _LAST_TRONGRID_REQUEST_TIME = now
                last_request_time = now

        last_response = response

        # ----------------------------------------------------
        # NOT RATE LIMITED
        # ----------------------------------------------------

        if response.status_code != 429:
            return response

        # ----------------------------------------------------
        # RATE LIMITED
        # ----------------------------------------------------

        retry_after = response.headers.get(
            "Retry-After"
        )

        try:
            wait_seconds = float(
                retry_after
            )
        except (
            TypeError,
            ValueError,
        ):
            wait_seconds = 1.5 * (
                attempt + 1
            )

        wait_seconds = max(
            1.0,
            min(wait_seconds, 6.0),
        )

        remaining = (
            deadline
            - time.monotonic()
        )

        if remaining <= wait_seconds:
            break

        print(
            f"{provider_name} rate limited "
            f"(429). Retrying in "
            f"{wait_seconds:.1f}s..."
        )

        time.sleep(wait_seconds)

    return last_response


# ============================================================
# TRONSCAN REQUEST
# ============================================================

def tronscan_get(
    url,
    params,
    deadline,
):
    if not TRONSCAN_API_KEY:
        return None

    try:
        response = _perform_request(
            url=url,
            params=params,
            headers=get_tronscan_headers(),
            deadline=deadline,
            provider_name="TronScan",
            max_attempts=2,
        )

        return response

    except (
        requests.exceptions.Timeout,
        requests.exceptions.RequestException,
    ):
        return None


# ============================================================
# TRONGRID REQUEST
# ============================================================

def trongrid_get(
    url,
    params,
    deadline,
):
    try:
        response = _perform_request(
            url=url,
            params=params,
            headers=get_trongrid_headers(),
            deadline=deadline,
            provider_name="TronGrid",
            max_attempts=2,
        )

        return response

    except (
        requests.exceptions.Timeout,
        requests.exceptions.RequestException,
    ):
        return None


# ============================================================
# TIMESTAMP EXTRACTION
# ============================================================

def extract_timestamp(transaction):
    """
    Extract a transaction timestamp.

    Supports:
    - Unix seconds
    - Unix milliseconds
    - numeric strings
    - ISO-8601 strings
    - nested transaction objects
    - nested block objects
    """

    if not isinstance(transaction, dict):
        return None

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
    # DIRECT FIELDS
    # --------------------------------------------------------

    for field in possible_fields:
        value = transaction.get(field)

        if value is None or value == "":
            continue

        if isinstance(
            value,
            (int, float),
        ):
            try:
                timestamp = float(value)

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

        if isinstance(value, str):
            cleaned = value.strip()

            if not cleaned:
                continue

            # Numeric string
            try:
                timestamp = float(cleaned)

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

            # ISO datetime
            try:
                iso_value = cleaned

                if iso_value.endswith("Z"):
                    iso_value = (
                        iso_value[:-1]
                        + "+00:00"
                    )

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
    # NESTED OBJECTS
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
        if not isinstance(
            nested,
            dict,
        ):
            continue

        result = extract_timestamp(
            nested
        )

        if result is not None:
            return result

    # --------------------------------------------------------
    # RECURSIVE SEARCH
    # --------------------------------------------------------

    for value in transaction.values():
        if isinstance(value, dict):
            result = extract_timestamp(
                value
            )

            if result is not None:
                return result

    return None


# ============================================================
# TRANSACTION EVIDENCE EXTRACTION
# ============================================================

def extract_transaction_evidence(
    transaction
):
    if not isinstance(transaction, dict):
        return {
            "transaction_hash": None,
            "transaction_id": None,
            "block_number": None,
            "transaction_timestamp": None,
        }

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

    block_number = (
        transaction.get("block")
        or transaction.get("blockNumber")
        or transaction.get("block_number")
    )

    transaction_timestamp = extract_timestamp(
        transaction
    )

    return {
        "transaction_hash": transaction_hash,
        "transaction_id": transaction_id,
        "block_number": block_number,
        "transaction_timestamp": (
            transaction_timestamp
        ),
    }


# ============================================================
# TRC20 TOKEN EXTRACTION
# ============================================================

def extract_token_amount(transfer):
    """
    Extract token data from normalized TronScan
    or TronGrid transfer objects.
    """

    token_info = transfer.get(
        "tokenInfo",
        {},
    )

    if not isinstance(
        token_info,
        dict,
    ):
        token_info = {}

    # TronGrid uses token_info.
    if not token_info:
        token_info = transfer.get(
            "token_info",
            {},
        )

        if not isinstance(
            token_info,
            dict,
        ):
            token_info = {}

    token_symbol = (
        token_info.get("tokenAbbr")
        or token_info.get("tokenAbbrName")
        or token_info.get("symbol")
    )

    decimals = (
        token_info.get("tokenDecimal")
        if token_info.get(
            "tokenDecimal"
        ) is not None
        else token_info.get("decimals")
    )

    raw_amount = None

    # TronScan format
    trigger_info = transfer.get(
        "trigger_info",
        {},
    )

    if isinstance(
        trigger_info,
        dict,
    ):
        parameter = trigger_info.get(
            "parameter",
            {},
        )

        if isinstance(
            parameter,
            dict,
        ):
            raw_amount = parameter.get(
                "value"
            )

    # TronScan fallback
    if raw_amount is None:
        raw_amount = transfer.get(
            "quant"
        )

    # TronGrid format
    if raw_amount is None:
        raw_amount = transfer.get(
            "value"
        )

    amount = None

    try:
        if raw_amount is not None:
            if decimals is not None:
                amount = (
                    int(raw_amount)
                    / (
                        10
                        ** int(decimals)
                    )
                )
            else:
                amount = int(raw_amount)

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
# NORMALIZE TRONGRID TRC20 TRANSFER
# ============================================================

def normalize_trongrid_trc20_transfer(
    transfer
):
    """
    Convert TronGrid's TRC20 response shape into
    the internal transfer format used by the tracer.
    """

    if not isinstance(
        transfer,
        dict,
    ):
        return None

    token_info = transfer.get(
        "token_info",
        {},
    )

    if not isinstance(
        token_info,
        dict,
    ):
        token_info = {}

    transaction_id = (
        transfer.get("transaction_id")
        or transfer.get("transactionId")
        or transfer.get("txID")
        or transfer.get("txid")
        or transfer.get("hash")
    )

    from_address = (
        transfer.get("from")
        or transfer.get("from_address")
        or transfer.get("fromAddress")
    )

    to_address = (
        transfer.get("to")
        or transfer.get("to_address")
        or transfer.get("toAddress")
    )

    contract_address = (
        token_info.get("address")
        or token_info.get("contract_address")
        or transfer.get("contract_address")
    )

    symbol = (
        token_info.get("symbol")
        or token_info.get("tokenAbbr")
        or token_info.get("name")
    )

    decimals = (
        token_info.get("decimals")
        if token_info.get(
            "decimals"
        ) is not None
        else token_info.get(
            "tokenDecimal"
        )
    )

    raw_value = (
        transfer.get("value")
        if transfer.get("value") is not None
        else transfer.get("quant")
    )

    return {
        "from_address": from_address,
        "to_address": to_address,
        "transaction_id": transaction_id,
        "transaction_hash": transaction_id,
        "block_timestamp": transfer.get(
            "block_timestamp"
        ),
        "tokenInfo": {
            "symbol": symbol,
            "tokenAbbr": symbol,
            "decimals": decimals,
            "tokenDecimal": decimals,
            "address": contract_address,
        },
        "quant": raw_value,
        "value": raw_value,
        "contract_address": contract_address,
        "confirmed": transfer.get(
            "confirmed"
        ),
    }


# ============================================================
# NORMALIZE TRONGRID TRX TRANSACTION
# ============================================================

def normalize_trongrid_trx_transaction(
    transaction
):
    """
    Convert TronGrid TRX transaction data into the
    internal format used by the tracer.
    """

    if not isinstance(
        transaction,
        dict,
    ):
        return None

    transaction_id = (
        transaction.get("txID")
        or transaction.get("transaction_id")
        or transaction.get("transactionId")
        or transaction.get("hash")
    )

    from_address = (
        transaction.get("from")
        or transaction.get("fromAddress")
        or transaction.get("from_address")
    )

    to_address = (
        transaction.get("to")
        or transaction.get("toAddress")
        or transaction.get("to_address")
    )

    return {
        "fromAddress": from_address,
        "toAddress": to_address,
        "transaction_id": transaction_id,
        "transaction_hash": transaction_id,
        "block_timestamp": transaction.get(
            "block_timestamp"
        ),
        "blockNumber": transaction.get(
            "block"
        ) or transaction.get(
            "blockNumber"
        ),
        "value": transaction.get(
            "value"
        ),
        "confirmed": transaction.get(
            "confirmed"
        ),
    }


# ============================================================
# FETCH TRC20 TRANSFERS
# ============================================================

def fetch_trc20_transfers(
    address,
    direction,
    deadline,
):
    """
    Fetch TRC20 transfers.

    Primary source:
        TronScan

    Fallback:
        TronGrid

    direction:
        "from" -> outgoing
        "to"   -> incoming
    """

    # ========================================================
    # 1. TRONSCAN
    # ========================================================

    if TRONSCAN_API_KEY:
        params = {
            "limit": MAX_TRANSACTIONS_PER_HOP,
        }

        if direction == "from":
            params["fromAddress"] = address
        else:
            params["toAddress"] = address

        response = tronscan_get(
            TRONSCAN_TRC20_URL,
            params=params,
            deadline=deadline,
        )

        if response is not None:
            try:
                response.raise_for_status()

                data = response.json()

                transfers = data.get(
                    "token_transfers",
                    [],
                )

                if not transfers:
                    transfers = data.get(
                        "data",
                        [],
                    )

                if isinstance(
                    transfers,
                    list,
                ):
                    return {
                        "ok": True,
                        "source": "tronscan",
                        "transfers": transfers,
                        "error": None,
                    }

            except (
                requests.exceptions.RequestException,
                ValueError,
            ):
                pass

        print(
            "TronScan unavailable/rate-limited. "
            "Falling back to TronGrid."
        )

    # ========================================================
    # 2. TRONGRID FALLBACK
    # ========================================================

    remaining = (
        deadline
        - time.monotonic()
    )

    if remaining <= 0:
        return {
            "ok": False,
            "source": None,
            "transfers": [],
            "error": "timeout",
        }

    url = TRONGRID_TRC20_URL.format(
        address=address
    )

    params = {
        "limit": MAX_TRANSACTIONS_PER_HOP,
        "only_confirmed": "true",
        "order_by": "block_timestamp,desc",
    }

    if direction == "from":
        params["only_from"] = "true"
    else:
        params["only_to"] = "true"

    response = trongrid_get(
        url,
        params=params,
        deadline=deadline,
    )

    if response is None:
        return {
            "ok": False,
            "source": "trongrid",
            "transfers": [],
            "error": (
                "TronGrid request failed."
            ),
        }

    try:
        response.raise_for_status()

        data = response.json()

    except (
        requests.exceptions.RequestException,
        ValueError,
    ) as exc:
        return {
            "ok": False,
            "source": "trongrid",
            "transfers": [],
            "error": str(exc),
        }

    raw_transfers = data.get(
        "data",
        [],
    )

    transfers = []

    for transfer in raw_transfers:
        normalized = (
            normalize_trongrid_trc20_transfer(
                transfer
            )
        )

        if normalized is not None:
            transfers.append(
                normalized
            )

    return {
        "ok": True,
        "source": "trongrid",
        "transfers": transfers,
        "error": None,
    }


# ============================================================
# FETCH TRX TRANSFERS
# ============================================================

def fetch_trx_transactions(
    address,
    deadline,
):
    """
    Fetch normal TRX transactions.

    Primary:
        TronScan

    Fallback:
        TronGrid
    """

    # ========================================================
    # 1. TRONSCAN
    # ========================================================

    if TRONSCAN_API_KEY:
        response = tronscan_get(
            TRONSCAN_TX_URL,
            params={
                "fromAddress": address,
                "sort": "-timestamp",
                "limit": MAX_TRANSACTIONS_PER_HOP,
            },
            deadline=deadline,
        )

        if response is not None:
            try:
                response.raise_for_status()

                data = response.json()

                transactions = data.get(
                    "data",
                    [],
                )

                if isinstance(
                    transactions,
                    list,
                ):
                    return {
                        "ok": True,
                        "source": "tronscan",
                        "transactions": transactions,
                        "error": None,
                    }

            except (
                requests.exceptions.RequestException,
                ValueError,
            ):
                pass

        print(
            "TronScan TRX endpoint unavailable. "
            "Falling back to TronGrid."
        )

    # ========================================================
    # 2. TRONGRID
    # ========================================================

    remaining = (
        deadline
        - time.monotonic()
    )

    if remaining <= 0:
        return {
            "ok": False,
            "source": None,
            "transactions": [],
            "error": "timeout",
        }

    url = TRONGRID_TRX_URL.format(
        address=address
    )

    response = trongrid_get(
        url,
        params={
            "only_confirmed": "true",
            "only_from": "true",
            "limit": MAX_TRANSACTIONS_PER_HOP,
            "order_by": "block_timestamp,desc",
        },
        deadline=deadline,
    )

    if response is None:
        return {
            "ok": False,
            "source": "trongrid",
            "transactions": [],
            "error": (
                "TronGrid request failed."
            ),
        }

    try:
        response.raise_for_status()

        data = response.json()

    except (
        requests.exceptions.RequestException,
        ValueError,
    ) as exc:
        return {
            "ok": False,
            "source": "trongrid",
            "transactions": [],
            "error": str(exc),
        }

    raw_transactions = data.get(
        "data",
        [],
    )

    transactions = []

    for transaction in raw_transactions:
        normalized = (
            normalize_trongrid_trx_transaction(
                transaction
            )
        )

        if normalized is not None:
            transactions.append(
                normalized
            )

    return {
        "ok": True,
        "source": "trongrid",
        "transactions": transactions,
        "error": None,
    }


# ============================================================
# TRC20 FAN-IN DETECTION
# ============================================================

def detect_trc20_fan_in(
    address,
    deadline,
):
    """
    Detect whether multiple unique wallets sent
    TRC20 tokens into the address.

    This is a behavioral indicator only.
    It does not establish fraudulent activity.
    """

    result = fetch_trc20_transfers(
        address=address,
        direction="to",
        deadline=deadline,
    )

    if not result.get("ok"):
        return {
            "fan_in": False,
            "incoming_senders": [],
            "incoming_count": 0,
        }

    transfers = result.get(
        "transfers",
        [],
    )

    senders = set()

    for transfer in transfers:
        if not isinstance(
            transfer,
            dict,
        ):
            continue

        sender = (
            transfer.get("from_address")
            or transfer.get("fromAddress")
            or transfer.get("from")
        )

        if not sender:
            continue

        if (
            sender.lower()
            == address.lower()
        ):
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

    if (
        not TRONSCAN_API_KEY
        and not TRONGRID_API_KEY
    ):
        return {
            "matched": False,
            "reason": "api_error",
            "detail": (
                "Both TRONSCAN_API_KEY and "
                "TRONGRID_API_KEY are missing."
            ),
        }

    # ========================================================
    # INITIALIZE
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
    # TIMEOUT
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
    # DEPTH
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
    # BEHAVIOURAL STATE
    # ========================================================

    fan_out = False
    fan_in = False
    rapid_hops = False
    high_risk_entity = False

    # ========================================================
    # FAN-IN
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
    # OUTGOING TRC20
    # ========================================================

    trc20_result = fetch_trc20_transfers(
        address=address,
        direction="from",
        deadline=_deadline,
    )

    if trc20_result.get("ok"):
        transfers = trc20_result.get(
            "transfers",
            [],
        )
    else:
        return {
            "matched": False,
            "reason": "api_error",
            "detail": trc20_result.get(
                "error"
            ),
            "fan_in": fan_in,
        }

    print(
        f"\nFound {len(transfers)} TRC20 transfers "
        f"at depth {depth} "
        f"(source: {trc20_result.get('source')})."
    )

    # ========================================================
    # FAN-OUT
    # ========================================================

    destinations = set()

    for transfer in transfers:
        if not isinstance(
            transfer,
            dict,
        ):
            continue

        destination = (
            transfer.get("to_address")
            or transfer.get("toAddress")
            or transfer.get("to")
        )

        if destination:
            destinations.add(
                destination.lower()
            )

    if (
        len(destinations)
        >= FAN_OUT_THRESHOLD
    ):
        fan_out = True

        print(
            "!!! FAN-OUT DETECTED !!!",
            address,
            "->",
            len(destinations),
            "unique destinations",
        )

    # ========================================================
    # INSPECT TRC20
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

        if not isinstance(
            transfer,
            dict,
        ):
            continue

        # ----------------------------------------------------
        # ADDRESSES
        # ----------------------------------------------------

        from_address = (
            transfer.get("from_address")
            or transfer.get("fromAddress")
            or transfer.get("from")
        )

        to_address = (
            transfer.get("to_address")
            or transfer.get("toAddress")
            or transfer.get("to")
        )

        if not to_address:
            continue

        # ----------------------------------------------------
        # EVIDENCE
        # ----------------------------------------------------

        transaction_evidence = (
            extract_transaction_evidence(
                transfer
            )
        )

        # ----------------------------------------------------
        # TIMESTAMP
        # ----------------------------------------------------

        current_timestamp = (
            extract_timestamp(
                transfer
            )
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
        # TOKEN
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

        contract_address = (
            transfer.get(
                "contract_address"
            )
        )

        if not contract_address:
            token_info = transfer.get(
                "tokenInfo",
                {},
            )

            if not isinstance(
                token_info,
                dict,
            ):
                token_info = {}

            contract_address = (
                token_info.get(
                    "address"
                )
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

        sender_classification = (
            classify_address(
                from_address,
                from_tag,
            )
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

        recipient_classification = (
            classify_address(
                to_address,
                to_tag,
            )
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
        # CONTINUE TRACE
        # ----------------------------------------------------

        normalized_destination = (
            to_address.lower()
        )

        if (
            normalized_destination
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

    trx_result = fetch_trx_transactions(
        address=address,
        deadline=_deadline,
    )

    if not trx_result.get("ok"):
        return {
            "matched": False,
            "reason": "api_error",
            "detail": trx_result.get(
                "error"
            ),
            "fan_in": fan_in,
            "fan_out": fan_out,
            "rapid_hops": rapid_hops,
            "high_risk_entity": (
                high_risk_entity
            ),
        }

    transactions = trx_result.get(
        "transactions",
        [],
    )

    print(
        f"Found {len(transactions)} TRX transactions "
        f"at depth {depth} "
        f"(source: {trx_result.get('source')})."
    )

    # ========================================================
    # TRX FAN-OUT
    # ========================================================

    normal_destinations = set()

    for tx in transactions:
        if not isinstance(
            tx,
            dict,
        ):
            continue

        destination = (
            tx.get("toAddress")
            or tx.get("to_address")
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
    # INSPECT NORMAL TRX
    # ========================================================

    for tx in transactions[
        :MAX_TRANSACTIONS_PER_HOP
    ]:
        if not isinstance(
            tx,
            dict,
        ):
            continue

        destination = (
            tx.get("toAddress")
            or tx.get("to_address")
        )

        if not destination:
            continue

        # ----------------------------------------------------
        # EVIDENCE
        # ----------------------------------------------------

        transaction_evidence = (
            extract_transaction_evidence(
                tx
            )
        )

        # ----------------------------------------------------
        # TIMESTAMP
        # ----------------------------------------------------

        current_timestamp = (
            extract_timestamp(tx)
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
        # PUBLIC TAG
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
        # CONTINUE TRACE
        # ----------------------------------------------------

        normalized_destination = (
            destination.lower()
        )

        if (
            normalized_destination
            not in _visited
            and depth + 1 < max_depth
        ):
            print(
                f"TRX Depth {depth}: "
                f"{address} -> {destination}"
            )

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

    difference = abs(
        current_timestamp
        - previous_timestamp
    )

    return (
        difference
        <= RAPID_HOP_SECONDS
    )