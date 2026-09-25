"""
Alert dispatch: get a completed investigation to an investigator who is not
looking at the screen.

WHY THIS IS A SEPARATE MODULE
-----------------------------
Tracing is a request/response call that a human is waiting on. An alert is not:
the point of alerting a law-enforcement workflow is that the trace was started
by a system, not a person, and the result needs to reach a human anyway. Firing
that through the response body would reach nobody. So dispatch is deliberately
separate from scoring: `assess()` decides whether an alert is warranted, this
module decides how it is delivered, and a delivery failure can never change or
suppress the assessment it was reporting.

THE RULE THAT MATTERS MOST HERE
-------------------------------
A dispatch failure MUST NOT affect the investigation. If a webhook endpoint is
down, an investigator who explicitly ran a trace still gets their result. The
error is recorded on the alert, visible in the response and in `/health`, and
that is all. Anything else would mean an outage at a third party's endpoint
silently costing an investigation its findings, which is the failure mode this
design exists to avoid.

WHAT AN ALERT CONTAINS
----------------------
An identifier, a link back to the stored investigation, the risk verdict, the
flow shapes that mattered, and the addresses the recommendation concerns. Not
the full graph, not the transaction table: an alert is a notification that
something needs a human, and a payload large enough to read is a payload
somebody will skim.
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, List, Optional

#: Score at or above which an alert is raised. Deliberately conservative: an
#: alert that fires on everything trains people to ignore it, which is worse
#: than an alert that fires late. Configurable so an operator can match it to
#: their triage policy.
ALERT_SCORE_THRESHOLD = int(os.getenv("BLOCKTRACE_ALERT_SCORE", "50"))

#: Risk levels that always warrant a human, regardless of score.
ALERT_LEVELS = {"HIGH", "CRITICAL"}


def should_alert(
    risk_level: Optional[str],
    risk_score: Optional[int],
    threshold: int = ALERT_SCORE_THRESHOLD,
) -> Dict[str, Any]:
    """
    Whether this result warrants a human, and why.

    Returns the decision rather than a bare boolean so the reason travels with
    it -- an operator tuning the threshold needs to know which rule fired, and
    an investigator seeing no alert needs to know the system considered it.
    """
    level = (risk_level or "").upper()
    score = risk_score if isinstance(risk_score, int) else None

    reasons: List[str] = []
    if level in ALERT_LEVELS:
        reasons.append(f"risk level {level}")
    if score is not None and score >= threshold:
        reasons.append(f"risk score {score} at or above the alert threshold {threshold}")

    return {
        "alert": bool(reasons),
        "reasons": reasons,
        "threshold": threshold,
        "levels_that_always_alert": sorted(ALERT_LEVELS),
    }


def build_alert(
    investigation_id: str,
    result: Dict[str, Any],
    base_url: str = "",
) -> Dict[str, Any]:
    """
    Build the alert body from a stored result.

    `base_url` only ever prefixes a link back into this deployment. It is
    configuration supplied by the operator, never a provider-supplied URL, so
    there is no path here that an untrusted value can steer.
    """
    risk = result.get("risk") or {}
    metadata = result.get("metadata") or {}
    shapes = metadata.get("flow_shapes") or {}
    recommendations = metadata.get("recommendations") or []

    # Only the shapes an alert reader can act on. `relay` is ordinary traffic
    # and would bury the two that matter.
    notable = {
        "exchange_like": [],
        "collector": [],
        "distributor": [],
    }
    for address, shape in shapes.items():
        label = shape.get("shape")
        if label in notable:
            notable[label].append(address)

    link = f"{base_url.rstrip('/')}/app/investigations/{investigation_id}" if base_url else ""

    return {
        "type": "blocktrace.investigation.alert",
        "version": 1,
        "investigation_id": investigation_id,
        "chain": result.get("chain"),
        "seed": result.get("seed"),
        "input_type": result.get("input_type"),
        "status": result.get("status"),
        "risk": {
            "level": risk.get("risk_level"),
            "score": risk.get("risk_score"),
            "indicators": [
                {
                    "code": i.get("code"),
                    "name": i.get("name"),
                    "severity": i.get("severity"),
                    "weight": i.get("weight"),
                }
                for i in (risk.get("indicators") or [])
            ],
        },
        "scope": {
            "truncated": metadata.get("truncated"),
            "depth_limit": metadata.get("depth_limit"),
            "max_depth_reached": metadata.get("max_depth_reached"),
            "nodes_examined": metadata.get("nodes_examined"),
            "transactions_inspected": metadata.get("transactions_inspected"),
        },
        "notable_addresses": notable,
        "recommendations": [
            {"code": r.get("code"), "title": r.get("title"), "next_step": r.get("next_step")}
            for r in recommendations
        ],
        "link": link,
        "disclaimer": (
            "Automated notification. Risk is a summary of observed on-chain data, "
            "not a legal judgement, a compliance determination, or evidence that "
            "any address is controlled by any person. Flow shape is an observed "
            "pattern and does not identify the operator of an address. Verify "
            "against cited sources before acting."
        ),
    }


# ---------------------------------------------------------------------------
# TRANSPORT
# ---------------------------------------------------------------------------

def configured_webhook() -> str:
    """The webhook this deployment delivers to, or empty. One source of truth."""
    return os.getenv("BLOCKTRACE_ALERT_WEBHOOK", "").strip()


def dispatch(
    alert: Dict[str, Any],
    webhook_url: Optional[str] = None,
    timeout: float = 5.0,
) -> Dict[str, Any]:
    """
    Attempt delivery. Returns a record of what happened; never raises.

    `webhook_url` defaults to the configured deployment webhook, so a caller
    cannot accidentally dispatch nothing by forgetting to pass it -- which is
    exactly the bug this default exists to prevent.

    A failure here is information, not an error: the caller keeps the
    investigation and reports the dispatch outcome alongside it.
    """
    target = webhook_url if webhook_url is not None else configured_webhook()
    if not target:
        return {
            "dispatched": False,
            "reason": "no webhook configured",
            "webhook_configured": False,
        }

    try:
        import requests

        response = requests.post(
            target,
            json=alert,
            timeout=timeout,
            headers={"Content-Type": "application/json"},
        )
        ok = response.status_code < 400
        return {
            "dispatched": ok,
            "status_code": response.status_code,
            "webhook_configured": True,
            "reason": None if ok else f"webhook returned {response.status_code}",
        }
    except Exception as exc:  # noqa: BLE001
        # Swallowed on purpose. The investigation is complete and correct
        # regardless of whether a third party's endpoint is reachable, and
        # losing the findings because a receiver is down is the one outcome
        # this must never produce.
        return {
            "dispatched": False,
            "webhook_configured": True,
            "reason": f"webhook unreachable: {type(exc).__name__}",
        }


def alert_capability() -> Dict[str, Any]:
    """For /health: is alerting wired up, and to where."""
    url = configured_webhook()
    return {
        "available": bool(url),
        "score_threshold": ALERT_SCORE_THRESHOLD,
        "always_alerts_on": sorted(ALERT_LEVELS),
        "note": (
            "Alerts are raised on the risk verdict and delivered to "
            "BLOCKTRACE_ALERT_WEBHOOK. A delivery failure never affects the "
            "investigation."
            if url
            else "No alert webhook configured; set BLOCKTRACE_ALERT_WEBHOOK to "
            "receive alerts. Investigations are unaffected either way."
        ),
    }
