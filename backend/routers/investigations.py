"""
Saved investigations: list, read, annotate, delete.

A saved investigation is a frozen record. It is not re-derived on read. A
forensic history that silently changes when providers change is worse than no
history at all, so GET returns exactly what was stored.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from models.api import ErrorResponse, PaginatedResponse, SaveInvestigationBody
from routers.trace import _identity
from services.repository import get_repository

router = APIRouter(prefix="/investigations", tags=["investigations"])


def _summary(row: dict) -> dict:
    """The list view. Deliberately excludes the full graph payload."""
    return {
        "id": row.get("id"),
        "title": row.get("title") or row.get("seed", "Untitled investigation"),
        "chain": row.get("chain"),
        "chain_name": row.get("chain_name"),
        "seed": row.get("seed"),
        "input_type": row.get("input_type"),
        "status": row.get("status"),
        "risk_score": row.get("risk_score", 0),
        "risk_level": row.get("risk_level", "UNKNOWN"),
        "entity_name": row.get("entity_name"),
        "nodes": row.get("node_count", 0),
        "transactions": row.get("transaction_count", 0),
        "edges": row.get("edge_count", 0),
        "created_at": row.get("created_at"),
        "has_report": bool(row.get("has_report")),
        "report_url": row.get("report_url"),
    }


@router.get(
    "",
    response_model=PaginatedResponse,
    responses={401: {"model": ErrorResponse}},
    summary="List saved investigations",
)
def list_investigations(
    limit: int = Query(25, ge=1, le=200),
    offset: int = Query(0, ge=0),
    chain: Optional[str] = None,
    risk_level: Optional[str] = None,
    search: Optional[str] = Query(None, max_length=200),
    authorization: Optional[str] = Header(None),
    identity: dict = Depends(_identity),
) -> PaginatedResponse:
    """The investigation history, newest first, scoped to the caller."""
    rows, total = get_repository().list_investigations(
        identity.get("user_id"),
        limit=limit, offset=offset,
        chain=chain, risk_level=risk_level, search=search,
    )
    return PaginatedResponse(
        items=[_summary(r) for r in rows],
        total=total, limit=limit, offset=offset,
    )


@router.get(
    "/{investigation_id}",
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
    summary="Read one saved investigation in full",
)
def get_investigation(
    investigation_id: str,
    authorization: Optional[str] = Header(None),
    identity: dict = Depends(_identity),
) -> dict:
    """
    The complete record: graph, transactions, risk, evidence and provider log.

    A 404 here is returned for another user's case as well as for a missing
    one. Distinguishing them would confirm the existence of an investigation
    the caller is not allowed to see.
    """
    row = get_repository().get_investigation(investigation_id, identity.get("user_id"))
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "investigation_not_found",
                "detail": f"No investigation with id {investigation_id} is available to you.",
                "kind": "not_found",
            },
        )
    return {
        "id": row.get("id"),
        "title": row.get("title"),
        "notes": row.get("notes"),
        "created_at": row.get("created_at"),
        "report_url": row.get("report_url"),
        "result": row.get("result"),
    }


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses={401: {"model": ErrorResponse}, 400: {"model": ErrorResponse}},
    summary="Save a completed investigation",
)
def save_investigation(
    body: SaveInvestigationBody,
    authorization: Optional[str] = Header(None),
    identity: dict = Depends(_identity),
) -> dict:
    """
    Persist a result obtained elsewhere.

    The trace endpoint saves automatically, so this exists for a result the
    client wants to keep under a different title, or for a result recovered
    from an export. The payload is stored as submitted: re-running the trace
    would produce a different document describing a different moment in time.
    """
    result = body.result or {}
    if not result.get("chain") or not result.get("seed"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "malformed_result",
                "detail": "A saved investigation needs at least a chain and a seed address.",
                "kind": "invalid_input",
            },
        )

    risk = result.get("risk") or {}
    entity = result.get("entity") or {}
    metadata = result.get("metadata") or {}

    row = get_repository().save_investigation(
        {
            "id": metadata.get("investigation_id"),
            "title": body.title or f"{result.get('chain_name', result['chain'])} trace - {result['seed'][:16]}…",
            "notes": body.notes,
            "chain": result["chain"],
            "chain_name": result.get("chain_name"),
            "seed": result["seed"],
            "input_type": result.get("input_type"),
            "status": result.get("status"),
            "status_detail": result.get("status_detail"),
            "risk_score": risk.get("risk_score", 0),
            "risk_level": risk.get("risk_level", "UNKNOWN"),
            "entity_name": entity.get("name"),
            "node_count": len(result.get("nodes") or []),
            "transaction_count": len(result.get("transactions") or []),
            "edge_count": len(result.get("edges") or []),
            "has_report": bool(result.get("report")),
            "report_url": result.get("report"),
            "result": result,
        },
        identity.get("user_id"),
    )
    return {"id": row.get("id"), "title": row.get("title"), "created_at": row.get("created_at")}


@router.delete(
    "/{investigation_id}",
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    summary="Delete a saved investigation",
)
def delete_investigation(
    investigation_id: str,
    authorization: Optional[str] = Header(None),
    identity: dict = Depends(_identity),
) -> dict:
    """Removes the case record. The generated PDF is left in place on disk."""
    removed = get_repository().delete_investigation(investigation_id, identity.get("user_id"))
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "investigation_not_found",
                "detail": f"No investigation with id {investigation_id} is available to you.",
                "kind": "not_found",
            },
        )
    return {"deleted": True, "id": investigation_id}
