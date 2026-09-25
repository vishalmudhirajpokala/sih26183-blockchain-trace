"""
Entity intelligence.

RULE 4 — every attribution carries its provenance. Nothing on this page is a
bare label. A name is always accompanied by where it came from, a link to that
source, a verification status, and the evidence that produced it. An entity
with a name and no source is not shown, because an investigator cannot act on
an unsourced label and has no way to tell a curated exchange address from a
string that happened to match.

Entities here are *derived from investigations the caller has actually run*.
There is no pre-seeded list of exchanges, no address database compiled from
memory, and no cross-user corpus. An address appears because a trace in this
account produced it.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from models.api import ErrorResponse, PaginatedResponse
from models.schemas import Chain
from routers.trace import _identity
from services.repository import get_repository

router = APIRouter(prefix="/entities", tags=["entities"])

#: Mirrors the provenance tiers in `models/schemas.py`. Kept as strings so this
#: router never has to import the enum to render a label.
_TIER_NOTE = {
    "curated_verified": (
        "Attribution verified against a maintained published source. The source "
        "URL below is the reference."
    ),
    "public_provider": (
        "The provider this trace used labelled this address. That is the "
        "provider's claim, reproduced — not an independent verification."
    ),
    "heuristic": (
        "Inferred from the shape of the traffic, not from a source. Treat as a "
        "lead, not a finding."
    ),
    "none": (
        "No attribution source. This address is known only by its behaviour in "
        "the transactions that were retrieved."
    ),
}


def _enrich(row: dict) -> dict:
    """Attach the provenance explanation to a stored entity row."""
    tier = str(row.get("source_type") or "none").lower()
    verification = str(row.get("verification_status") or "unverified")
    out = dict(row)
    out["provenance_tier"] = tier
    out["provenance_note"] = _TIER_NOTE.get(
        tier,
        f"Unrecognised provenance tier '{tier}'. Treated as unverified.",
    )
    # Anything without a citable source is marked as such, and the UI greys the
    # label accordingly rather than presenting it with equal weight.
    out["has_citable_source"] = bool(row.get("source_url"))
    if not out["has_citable_source"] and tier == "curated_verified":
        out["provenance_note"] = (
            "Marked as curated-verified but carries no source URL. It is "
            "therefore shown as unverified: an attribution with nothing to "
            "check is not evidence."
        )
        out["has_citable_source"] = False
    out["evidence"] = row.get("evidence") or []
    return out


@router.get(
    "",
    response_model=PaginatedResponse,
    responses={401: {"model": ErrorResponse}},
    summary="Entities observed across this user's investigations",
)
def list_entities(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    entity_type: Optional[str] = Query(None, description="Filter by entity type"),
    chain: Optional[Chain] = None,
    authorization: Optional[str] = None,
    identity: dict = Depends(_identity),
) -> PaginatedResponse:
    """
    Every named address seen in this account's traces, with its provenance.

    `source_type` is the provenance tier and `verification_status` is the
    confidence the source itself claims. Both are returned unedited, because a
    filtered list of entities is a list of entities whose weakness has been
    removed.
    """
    rows, total = get_repository().list_entities(
        identity.get("user_id"),
        limit=limit,
        offset=offset,
        entity_type=entity_type,
        chain=chain.value if chain else None,
    )
    return PaginatedResponse(
        items=[_enrich(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/types",
    summary="Entity types present, with their provenance tiers",
)
def entity_types(
    authorization: Optional[str] = None,
    identity: dict = Depends(_identity),
) -> dict:
    """
    A summary of the types seen, so the filter menu is not a hard-coded list
    of entity categories that may not exist in this account's data.
    """
    rows, total = get_repository().list_entities(
        identity.get("user_id"), limit=1000, offset=0,
    )
    by_type: dict = {}
    for row in rows:
        key = str(row.get("type") or "unclassified")
        bucket = by_type.setdefault(
            key,
            {"type": key, "count": 0, "chains": set(), "provenance_tiers": set()},
        )
        bucket["count"] += 1
        if row.get("chain"):
            bucket["chains"].add(row["chain"])
        bucket["provenance_tiers"].add(str(row.get("source_type") or "none").lower())

    return {
        "total": total,
        "types": [
            {
                **bucket,
                "chains": sorted(bucket["chains"]),
                "provenance_tiers": sorted(bucket["provenance_tiers"]),
            }
            for bucket in sorted(by_type.values(), key=lambda b: -b["count"])
        ],
        "note": (
            "Types observed in your own investigations. An address is only "
            "listed if a trace you ran attributed it."
        ),
    }


@router.get(
    "/{chain_value}/{address}",
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    summary="Every appearance of one address across investigations",
)
def entity_detail(
    chain_value: Chain,
    address: str,
    authorization: Optional[str] = None,
    identity: dict = Depends(_identity),
) -> dict:
    """
    The address, its provenance, and the investigations in which it appeared.

    Scoped to the caller's cases. A 404 covers both "never seen" and "not
    yours", for the same reason the investigation detail route does that.
    """
    rows, _ = get_repository().list_entities(
        identity.get("user_id"), limit=1000, offset=0, chain=chain_value.value,
    )
    match = next(
        (
            r for r in rows
            if str(r.get("address", "")).lower() == address.strip().lower()
        ),
        None,
    )
    if match is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "entity_not_found",
                "detail": (
                    f"No attributed entity {address} on "
                    f"{chain_value.display_name} is available to you."
                ),
                "kind": "not_found",
            },
        )

    investigations, _ = get_repository().list_investigations(
        identity.get("user_id"), limit=500, offset=0, chain=chain_value.value,
    )
    appearances = [
        {
            "id": r.get("id"),
            "title": r.get("title"),
            "seed": r.get("seed"),
            "status": r.get("status"),
            "risk_level": r.get("risk_level"),
            "risk_score": r.get("risk_score"),
            "created_at": r.get("created_at"),
        }
        for r in investigations
        if any(
            str(n.get("address", "")).lower() == address.strip().lower()
            for n in ((r.get("result") or {}).get("nodes") or [])
        )
    ]

    return {
        **_enrich(match),
        "investigation_count": len(appearances),
        "investigations": appearances,
    }
