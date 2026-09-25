"""
Network explorer: live chain status and per-chain capability disclosure.

RULE 5 — no fake live data. This router is where that rule is most likely to
be broken by accident, because a network panel wants to show a number in every
cell. So:

- A metric a provider does not expose is `None`, with an availability marker
  saying WHY it is absent.
- Block height is fetched live, never cached, never inferred.
- Average block time comes from a named source and says which one. It is a
  protocol constant, not a measurement, and is labelled accordingly.
- A chain whose providers are all unreachable reports `available: false` with
  the reason. It does not render zeros.

Nothing on this page is estimated, interpolated, or filled in.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query

from models.api import ChainCapability, NetworkStatusResponse
from models.schemas import Availability, Chain
from services.chain_registry import chain_capabilities, get_adapter, supported_chains
from utils.http_client import HttpClient, RequestCache

router = APIRouter(prefix="/network", tags=["network"])

#: A status is only "available" when the provider actually answered. Anything
#: else is a real, reportable condition.
_AVAILABLE = {Availability.AVAILABLE.value, "available", "ok"}


def _marker(value: Any) -> str:
    """Normalize an Availability (enum or string) to its wire value."""
    if isinstance(value, Availability):
        return value.value
    if value is None:
        return Availability.NOT_PROVIDED.value
    return str(value)


def _describe(info, evidence: List[str]) -> Dict[str, Any]:
    """Turn an adapter `NetworkInfo` into the router's response shape."""
    extra = getattr(info, "extra", None) or {}
    availability = _marker(getattr(info, "availability", Availability.AVAILABLE))
    available = availability in _AVAILABLE

    block_height = getattr(info, "latest_block", None)
    if available and block_height is None:
        evidence.append(
            "The provider responded but did not report a block height. It is "
            "shown as not available rather than as 0, which would be a "
            "different and false statement."
        )

    tps_availability = _marker(extra.get("tps_availability", Availability.NOT_PROVIDED))
    tps = extra.get("tps")

    if tps_availability == Availability.NOT_PROVIDED.value and available:
        evidence.append(
            f"{info.chain.display_name} transactions-per-second is not exposed "
            f"by any provider this deployment uses. It is reported as not "
            f"provided rather than estimated from block height, because block "
            f"time alone cannot tell you how full a block is."
        )

    block_time = extra.get("average_block_time_seconds")
    if block_time is not None:
        evidence.append(
            f"Average block time of {block_time}s is a documented protocol "
            f"parameter for {info.chain.display_name}, not a measurement "
            f"taken during this request."
        )

    if extra.get("address_history") is False:
        reason = extra.get("address_history_unavailable_reason")
        if reason:
            evidence.append(reason)

    return {
        "chain": info.chain.value,
        "chain_name": info.chain.display_name,
        "available": available,
        "unavailable_reason": None if available else (
            getattr(info, "unavailable_reason", None)
            or "The provider did not report a usable status."
        ),
        "block_height": block_height if available else None,
        "block_hash": getattr(info, "latest_block_hash", None) if available else None,
        "block_timestamp": getattr(info, "latest_block_timestamp", None) if available else None,
        "transaction_count": getattr(info, "transaction_count", None) if available else None,
        "tps": tps,
        "tps_availability": tps_availability,
        "average_block_time_seconds": block_time,
        "block_time_source": "documented protocol parameter" if block_time is not None else None,
        "availability": availability,
        "provider": getattr(info, "provider", None),
        "checked_at": time.time(),
        "evidence_notes": evidence,
    }


def _fetch(chain: Chain, timeout: float = 20.0) -> NetworkStatusResponse:
    """One live status fetch, with every failure mode reported honestly."""
    evidence: List[str] = []
    adapter = get_adapter(chain)

    # A stale tip presented as a live one is exactly the fabricated "live
    # data" this product must never show, so this is never cached.
    client = HttpClient(cache=RequestCache(), deadline=time.monotonic() + timeout)
    try:
        info = adapter.get_network_status(client)
    except Exception as exc:
        return NetworkStatusResponse(
            chain=chain.value,
            chain_name=chain.display_name,
            available=False,
            block_height=None,
            tps=None,
            tps_availability=Availability.UNAVAILABLE.value,
            availability=Availability.UNAVAILABLE.value,
            unavailable_reason=f"{type(exc).__name__} while querying {chain.display_name}.",
            checked_at=time.time(),
            evidence_notes=[
                "This chain's providers could not be reached. No network "
                "figures are shown, because an unreachable provider is not a "
                "chain at height zero."
            ],
        )
    finally:
        client.close()

    return NetworkStatusResponse(**_describe(info, evidence))


def jsonable(response: NetworkStatusResponse) -> dict:
    """Pydantic model -> plain dict, for the hand-built overview envelope."""
    return response.model_dump()


# ============================================================
# ENDPOINTS
# ============================================================


@router.get(
    "/chains",
    response_model=List[ChainCapability],
    summary="Every supported chain and what it can currently do",
)
def list_chains() -> List[ChainCapability]:
    """
    Declared capabilities and any active limitation.

    The UI reads this to explain a gap *before* the user hits it — for example,
    that BSC address history needs a key this deployment does not have.
    """
    return [ChainCapability(**entry) for entry in chain_capabilities()]


@router.get(
    "/status",
    response_model=NetworkStatusResponse,
    # No 502: a provider that is down is a reportable result carried in the
    # body with `available: false`, not a transport failure. The endpoint
    # succeeds so one dead provider never blanks the network explorer.
    summary="Live status for one chain",
)
def chain_status(
    chain: Chain = Query(..., description="Chain to query"),
) -> NetworkStatusResponse:
    """Fetch live network status for one chain. Never cached, never faked."""
    return _fetch(chain)


@router.get(
    "/overview",
    summary="Live status for every supported chain",
)
def network_overview() -> dict:
    """
    All chains at once, for the network explorer page.

    Each chain reports independently: one unreachable chain never blanks the
    others, and a failure is visible as a failure in that chain's own cell
    rather than as a zero.
    """
    chains: List[dict] = []
    for chain in supported_chains():
        response = _fetch(chain, timeout=15.0)
        chains.append(jsonable(response))

    return {
        "checked_at": time.time(),
        "chains": chains,
        "note": (
            "Block heights are fetched live on every request. Any metric a "
            "provider does not expose is shown as not provided; nothing here "
            "is estimated or interpolated."
        ),
    }
