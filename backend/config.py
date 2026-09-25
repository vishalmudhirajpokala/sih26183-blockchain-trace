"""
Configuration.

`.env` is loaded exactly once, here, so that no module has to remember to call
`load_dotenv()` and no adapter can silently run with missing credentials.

SECURITY: this module reads secrets but never prints, logs, or returns them in
any shape that reaches a response body. `describe()` reports only whether a
variable is present, which is what a health check needs and is not a leak.
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional

from dotenv import load_dotenv

# Idempotent; the backend's own .env wins over any parent directory's.
load_dotenv()

# ============================================================
# PROVIDER KEYS
# ============================================================

TRONSCAN_API_KEY: Optional[str] = os.getenv("TRONSCAN_API_KEY")
TRONGRID_API_KEY: Optional[str] = os.getenv("TRONGRID_API_KEY")
ROUTESCAN_API_KEY: Optional[str] = os.getenv("ROUTESCAN_API_KEY")
ETHERSCAN_API_KEY: Optional[str] = os.getenv("ETHERSCAN_API_KEY")
POLYGONSCAN_API_KEY: Optional[str] = os.getenv("POLYGONSCAN_API_KEY")
BSCSCAN_API_KEY: Optional[str] = os.getenv("BSCSCAN_API_KEY")
BLOCKCHAIR_API_KEY: Optional[str] = os.getenv("BLOCKCHAIR_API_KEY")
MEMPOOL_SPACE_API_KEY: Optional[str] = os.getenv("MEMPOOL_SPACE_API_KEY")

# ============================================================
# SUPABASE
#
# The anon key is publishable and is the only key the browser may ever see.
# The service-role key is server-only; routers/ must read it from here and must
# never place it in a response, a log line, or a client-side bundle.
# ============================================================

SUPABASE_URL: Optional[str] = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY: Optional[str] = os.getenv("SUPABASE_ANON_KEY")
SUPABASE_SERVICE_ROLE_KEY: Optional[str] = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

# When true, auth is bypassed so the app is usable without a Supabase project.
# Never enable in a deployment.
DEMO_MODE: bool = os.getenv("BLOCKTRACE_DEMO_MODE", "true").strip().lower() in {
    "1", "true", "yes", "on",
}

# ============================================================
# LIMITS
# ============================================================

MAX_TRACE_DEPTH = int(os.getenv("BLOCKTRACE_MAX_DEPTH", "3"))
MAX_TRACE_NODES = int(os.getenv("BLOCKTRACE_MAX_NODES", "25"))
MAX_TXS_PER_NODE = int(os.getenv("BLOCKTRACE_MAX_TXS_PER_NODE", "5"))
TRACE_DEADLINE_SECONDS = int(os.getenv("BLOCKTRACE_TRACE_DEADLINE", "90"))
REPORT_DIR = os.getenv(
    "BLOCKTRACE_REPORT_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports"),
)


def has_tronscan() -> bool:
    return bool(TRONSCAN_API_KEY)


def has_trongrid() -> bool:
    return bool(TRONGRID_API_KEY)


def has_routescan() -> bool:
    return bool(ROUTESCAN_API_KEY)


def has_supabase() -> bool:
    return bool(SUPABASE_URL and SUPABASE_ANON_KEY)


def describe() -> Dict[str, object]:
    """
    A health-check view of configuration.

    Reports presence only, never values. A present-but-empty key and an absent
    key are both `False`, which is all a caller can learn.
    """
    return {
        "providers": {
            "tronscan": has_tronscan(),
            "trongrid": has_trongrid(),
            "routescan": has_routescan(),
            "etherscan": bool(ETHERSCAN_API_KEY),
            "blockscout": True,          # keyless by design
            "blockstream": True,         # keyless by design
            "mempool_space": bool(MEMPOOL_SPACE_API_KEY) or True,
        },
        "supabase": {
            "url": bool(SUPABASE_URL),
            "anon_key": bool(SUPABASE_ANON_KEY),
            # Presence is reported; the value never leaves the process.
            "service_role_key": bool(SUPABASE_SERVICE_ROLE_KEY),
        },
        "demo_mode": DEMO_MODE,
        "limits": {
            "max_depth": MAX_TRACE_DEPTH,
            "max_nodes": MAX_TRACE_NODES,
            "max_txs_per_node": MAX_TXS_PER_NODE,
            "deadline_seconds": TRACE_DEADLINE_SECONDS,
        },
    }
