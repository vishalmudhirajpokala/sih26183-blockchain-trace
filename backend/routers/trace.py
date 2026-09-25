"""
Trace endpoints: detect an input, and run an investigation.

The two are separate because the Trace Console needs to answer "is this even
valid, and on which chain?" on every keystroke, long before the user commits to
a multi-hop trace that costs real provider calls.
"""

from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status

import config
from models.api import (
    DetectRequestBody,
    DetectResponse,
    ErrorResponse,
    TraceRequestBody,
    TraceResponse,
)
from models.schemas import Chain, TraceStatus
from services.auth import AuthState, resolve_identity
from services.report_service import render_trace_report, report_filename_for
from services.alerting import build_alert, dispatch, should_alert
from services.repository import get_repository
from services.chain_detection import AmbiguousChainError
from services.trace_orchestrator import DetectionError, detect_only, run_investigation

#: The multi-chain trace lives at `POST /trace/run` rather than at
#: `POST /trace`, because the legacy TRON-only endpoint in `main.py` already
#: owns `POST /trace` and two handlers cannot share one path without the second
#: silently never being reached. `main.py` documents that endpoint as legacy;
#: this is the one new clients should call.
#:
#: The `/trace` prefix also keeps these away from `GET /investigations/{id}`,
#: which would otherwise match a literal `/trace` path segment under the
#: investigations router and return a misleading 404 for a malformed id.
router = APIRouter(prefix="/trace", tags=["trace"])


def _identity(authorization: Optional[str] = None) -> dict:
    """
    Resolve the caller, and refuse when auth is required but absent.

    A deployment with Supabase configured and demo mode off must not serve
    case data to an anonymous caller. The check lives here so every route that
    touches a case gets it by default.
    """
    identity = resolve_identity(authorization)
    if identity["state"] == AuthState.UNAVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "authentication_required",
                "detail": (
                    "This deployment requires sign-in. Send the Supabase "
                    "session token as `Authorization: Bearer <token>`."
                ),
                "kind": "unavailable",
            },
        )
    return identity


def _chain(value) -> Optional[Chain]:
    try:
        return Chain(value) if value else None
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "unsupported_chain",
                "detail": f"Unsupported chain: {value}",
                "kind": "invalid_input",
            },
        )


# ============================================================
# DETECTION
# ============================================================


@router.post(
    "/detect",
    response_model=DetectResponse,
    responses={400: {"model": ErrorResponse}},
    summary="Identify an address or transaction hash",
)
def detect(body: DetectRequestBody) -> DetectResponse:
    """
    Report what an input is, without running a trace.

    The Trace Console calls this debounced while the user types. It is cheap:
    no provider is called, because the question is entirely about format and
    checksums.

    The display name is added here rather than in `chain_detection` because that
    module deliberately knows nothing about presentation — it returns chain
    *slugs*. Putting the `Chain` enum's `display_name` into the response at the
    HTTP boundary keeps the detection logic free of UI vocabulary while saving
    the browser from maintaining a second, drift-prone table of chain names.
    """
    detection = detect_only(body.query, _chain(body.preferred_chain))
    if detection.get("chain"):
        try:
            detection["chain_name"] = Chain(detection["chain"]).display_name
        except ValueError:
            # A chain the display-name table does not know. The slug still goes
            # through; the browser falls back to it.
            detection["chain_name"] = None
    return DetectResponse(**detection)


# ============================================================
# TRACE
# ============================================================


@router.post(
    "/run",
    response_model=TraceResponse,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
    },
    summary="Run a multi-chain fund-flow investigation",
)
def create_trace(
    body: TraceRequestBody,
    authorization: Optional[str] = None,
    identity: dict = Depends(_identity),
) -> TraceResponse:
    """
    Run one investigation and return the normalized result.

    The result shape is identical for every chain. Nothing downstream — the
    frontend, the report, the history page — branches on chain to read it.
    """
    try:
        result = run_investigation(
            body.query,
            preferred_chain=_chain(body.preferred_chain),
            max_depth=body.max_depth,
            max_nodes=body.max_nodes,
            max_txs_per_node=body.max_txs_per_node,
            deadline_seconds=body.deadline_seconds,
        )
    except DetectionError as exc:
        # The input is not a valid address or hash anywhere. This is a 400 with
        # the detection detail attached, so the console can say *why* rather
        # than showing a generic rejection.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "unrecognized_input",
                "detail": str(exc),
                "kind": "invalid_input",
                "detection": exc.detection,
            },
        )
    except AmbiguousChainError as exc:
        # More than one network has real activity for this address. This is not
        # a failure and not a question about blockchain infrastructure: those
        # are genuinely different subjects, so the evidence comes back and the
        # caller decides which to investigate. Nothing is guessed.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "ambiguous_chain",
                "detail": (
                    "Activity for this address was found on more than one "
                    "network. Each is a separate investigation."
                ),
                "kind": "ambiguous_chain",
                "detection": {
                    "candidates_with_activity": [
                        e["chain"] for e in exc.evidence if e.get("status") == "activity"
                    ],
                    "uncertain": exc.uncertain,
                    "evidence": exc.evidence,
                },
            },
        )
    except TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={
                "error": "trace_timed_out",
                "detail": (
                    "The investigation exceeded its time budget before the "
                    "providers responded. Narrow the depth and try again."
                ),
                "kind": "timeout",
            },
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "trace_failed",
                "detail": f"The investigation engine failed: {type(exc).__name__}.",
                "kind": "provider_error",
            },
        ) from exc

    payload = result.to_dict()
    investigation_id = result.metadata.investigation_id
    report_url: Optional[str] = None

    # -- report ------------------------------------------------------
    if body.generate_report:
        try:
            filename = report_filename_for(result.chain.value, result.seed, investigation_id)
            path = os.path.join(config.REPORT_DIR, filename)
            os.makedirs(config.REPORT_DIR, exist_ok=True)
            render_trace_report(
                result, path,
                investigator=identity.get("email") if identity else None,
            )
            report_url = f"/reports/{filename}"
            payload["report"] = report_url
        except Exception as exc:
            # A failed PDF must not discard a successful investigation. The
            # trace is the finding; the dossier is a rendering of it.
            payload["report"] = None
            result.evidence_notes.append(
                f"The PDF dossier could not be rendered ({type(exc).__name__}). "
                f"The investigation itself completed and is shown in full."
            )

    # -- persist -----------------------------------------------------
    if body.save:
        try:
            repository = get_repository()
            repository.save_investigation(
                {
                    "id": investigation_id,
                    "title": body.title
                            or f"{result.chain.display_name} trace - {result.seed[:16]}…",
                    "chain": result.chain.value,
                    "chain_name": result.chain.display_name,
                    "seed": result.seed,
                    "input_type": result.input_type.value,
                    "status": result.status.value,
                    "status_detail": result.status_detail,
                    "risk_score": result.risk.risk_score,
                    "risk_level": result.risk.risk_level.value,
                    "entity_name": result.entity.name if result.entity else None,
                    "node_count": len(result.nodes),
                    "transaction_count": len(result.transactions),
                    "edge_count": len(result.edges),
                    "has_report": bool(report_url),
                    "report_url": report_url,
                    "result": payload,
                },
                identity.get("user_id"),
            )
        except Exception as exc:
            # Persistence failing is worth reporting but must not lose the
            # result the investigator is looking at right now.
            result.evidence_notes.append(
                f"This investigation could not be saved to history "
                f"({type(exc).__name__}). The result below is complete and "
                f"can still be exported."
            )

    if result.status in (TraceStatus.PROVIDER_ERROR, TraceStatus.RATE_LIMITED, TraceStatus.TIMEOUT):
        # A provider-side failure is a real result, not a request error. It is
        # returned as 200 with the status carried in the body, because the
        # client must render what was and was not established. Recording the
        # fact here keeps the distinction from being re-litigated later.
        result.evidence_notes.append(
            f"This investigation ended with status '{result.status.value}'. "
            f"That is a statement about provider availability, not about the "
            f"address. No conclusion about this subject can be drawn from it."
        )
        payload = result.to_dict()

    # -- alert --------------------------------------------------------
    # Raised on the engine's own verdict, after the result is complete, so an
    # alert can never describe a different investigation than the one stored.
    #
    # Wrapped whole: a dispatch problem is reported, never raised, because the
    # investigator who ran this trace is waiting on the response and must get
    # their findings whether or not a third party's endpoint is reachable.
    alert_record: Optional[dict] = None
    try:
        decision = should_alert(
            result.risk.risk_level.value, result.risk.risk_score
        )
        if decision["alert"]:
            alert_record = dispatch(
                build_alert(investigation_id, payload, base_url=_public_base_url())
            )
            alert_record.update(decision)
        else:
            alert_record = {"dispatched": False, "reason": "below alert threshold"}
            alert_record.update(decision)
    except Exception as exc:  # noqa: BLE001
        alert_record = {
            "dispatched": False,
            "reason": f"alert evaluation failed: {type(exc).__name__}",
        }

    return TraceResponse(
        result=payload,
        report_url=report_url,
        investigation_id=investigation_id,
        alert=alert_record,
    )


def _public_base_url() -> str:
    """
    The base URL to put in an alert's link, if the operator configured one.

    Empty by default, in which case alerts carry no link. It is never derived
    from an inbound request header: a `Host` header is caller-controlled, and
    putting one into a URL that gets delivered to a third party would let the
    caller redirect an investigator's link at a host of their choosing.
    """
    import os

    return os.getenv("BLOCKTRACE_PUBLIC_URL", "").strip()
