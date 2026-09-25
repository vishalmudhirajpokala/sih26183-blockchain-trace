"""
Portfolio analytics over saved investigations.

Every number here is computed from investigations the caller actually ran.
None of it is a market statistic, a chain-wide metric, or a modelled figure —
there is no such data in this system, and the response says so explicitly
rather than leaving the frontend to imply it.
"""

from __future__ import annotations

from collections import Counter
from typing import Optional

from fastapi import APIRouter, Depends, Query

from models.api import ErrorResponse
from routers.trace import _identity
from services.repository import get_repository

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get(
    "/overview",
    responses={401: {"model": ErrorResponse}},
    summary="Aggregate statistics across saved investigations",
)
def overview(
    limit: int = Query(500, ge=1, le=2000),
    authorization: Optional[str] = None,
    identity: dict = Depends(_identity),
) -> dict:
    """
    Counts, distributions and trends computed from this user's cases.

    `data_basis` is carried in the payload so a reader always knows the
    denominator: these are statistics over investigations, not over
    transactions on any chain.
    """
    rows, total = get_repository().list_investigations(
        identity.get("user_id"), limit=limit, offset=0,
    )

    by_chain = Counter(r.get("chain") or "unknown" for r in rows)
    by_level = Counter(r.get("risk_level") or "UNKNOWN" for r in rows)
    by_status = Counter(r.get("status") or "unknown" for r in rows)
    by_entity_type = Counter(
        (r.get("result") or {}).get("entity", {}).get("type")
        for r in rows
        if ((r.get("result") or {}).get("entity") or {}).get("type")
    )

    scores = [int(r.get("risk_score") or 0) for r in rows]
    entities = [r.get("entity_name") for r in rows if r.get("entity_name")]

    by_day: Counter = Counter()
    for row in rows:
        created = str(row.get("created_at") or "")
        if len(created) >= 10:
            by_day[created[:10]] += 1

    return {
        "data_basis": {
            "source": "saved investigations for the current user",
            "investigation_count": total,
            "analysed_here": len(rows),
            "transactions_inspected": sum(
                int(r.get("transaction_count") or 0) for r in rows
            ),
            "note": (
                "These are statistics over investigations you have run. They "
                "are not market data, chain-wide metrics, or any figure derived "
                "from a provider other than those used for your own traces."
            ),
        },
        "risk": {
            "scores": scores,
            "average": round(sum(scores) / len(scores), 1) if scores else None,
            "max": max(scores) if scores else None,
            "min": min(scores) if scores else None,
            "by_level": dict(by_level),
        },
        "distribution": {
            "by_chain": dict(by_chain),
            "by_status": dict(by_status),
            "by_entity_type": dict(by_entity_type),
        },
        "timeline": {
            "by_day": [{"date": day, "count": count} for day, count in sorted(by_day.items())],
        },
        "entities": {
            "attributed_investigations": len(entities),
            "distinct_names": len(set(entities)),
            "names": sorted(set(entities))[:25],
        },
        "reports": {
            "generated": sum(1 for r in rows if r.get("has_report")),
        },
    }


@router.get(
    "/risk-trend",
    responses={401: {"model": ErrorResponse}},
    summary="Risk score over time",
)
def risk_trend(
    limit: int = Query(200, ge=1, le=1000),
    authorization: Optional[str] = None,
    identity: dict = Depends(_identity),
) -> dict:
    """A time series of scores, oldest first, for the dashboard chart."""
    rows, _ = get_repository().list_investigations(
        identity.get("user_id"), limit=limit, offset=0,
    )
    rows = list(reversed(rows))
    return {
        "points": [
            {
                "id": r.get("id"),
                "created_at": r.get("created_at"),
                "chain": r.get("chain"),
                "seed": r.get("seed"),
                "risk_score": r.get("risk_score", 0),
                "risk_level": r.get("risk_level", "UNKNOWN"),
            }
            for r in rows
        ],
    }
