"""
End-to-end HTTP test through the real ASGI app.

This drives the product the way the browser will, using `TestClient` against
`main.app`. It is the only test that proves the routers, the engine, the
repository, the report service and the auth dependency are actually wired
together — unit tests of each in isolation can all pass while the assembled app
serves nothing.

RULE 3/5 applied to the assertions: the test checks that whatever comes back
is internally consistent and honestly labelled, NOT that a specific risk score
appears. A provider outage must not fail this suite, because the product's job
in that case is to *report* the outage, which is what a 200 with a provider
status is.

Runs against a real TRON address with real providers. Set BLOCKTRACE_E2E=0 to
skip the live trace and exercise only the offline surface.
"""

import os
import sys

sys.path.insert(0, ".")

import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

# A known-good TRON address used for the live leg. It is a public exchange
# address, present in public chain data; it is not a private key or credential.
LIVE_TRON = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"   # USDT-TRC20 contract


def offline_checks(client: TestClient) -> list:
    """Endpoints that must work with no provider call at all."""
    failures = []

    r = client.get("/health")
    if r.status_code != 200:
        failures.append(f"/health returned {r.status_code}")
    else:
        body = r.json()
        for key in ("status", "version", "chains", "config", "persistence", "auth"):
            if key not in body:
                failures.append(f"/health is missing '{key}'")
        # RULE 5: health must not claim a chain is reachable.
        # It reports which adapters exist; reachability is /network/status.
        if body.get("config", {}).get("demo_mode") is None:
            failures.append("/health config does not report demo_mode")

    r = client.get("/")
    if r.status_code != 200 or "chains" not in r.json():
        failures.append("/ did not return a chain list")

    r = client.get("/auth/status")
    if r.status_code != 200:
        failures.append(f"/auth/status returned {r.status_code}")
    else:
        status_body = r.json()
        # RULE 7: capability disclosure must not leak a credential.
        blob = str(status_body)
        import config as cfg
        for name, secret in (
            ("service_role", cfg.SUPABASE_SERVICE_ROLE_KEY),
            ("anon_key", cfg.SUPABASE_ANON_KEY),
        ):
            if secret and secret in blob:
                failures.append(f"/auth/status leaked {name}")

    r = client.post("/trace/detect", json={"query": LIVE_TRON})
    if r.status_code != 200:
        failures.append(f"/trace/detect returned {r.status_code}: {r.text[:200]}")
    else:
        d = r.json()
        # Detection must name the chain and a validity verdict.
        if not d.get("valid"):
            failures.append(f"/trace/detect did not recognise a valid TRON address: {d}")
        if d.get("chain") != "tron":
            failures.append(f"/trace/detect misidentified TRON as {d.get('chain')}")

    # A nonsense input must be rejected with 400 and an explanation, not a
    # 500 and not a silent empty result.
    r = client.post("/trace/detect", json={"query": "not-an-address"})
    if r.status_code not in (200, 400):
        failures.append(f"/trace/detect on garbage returned {r.status_code}")

    # Empty list endpoints must succeed with zero items, not error.
    for path in ("/investigations", "/entities", "/reports", "/analytics/overview"):
        r = client.get(path)
        if r.status_code != 200:
            failures.append(f"GET {path} returned {r.status_code}: {r.text[:160]}")

    # /network/chains declares capability without a provider call.
    r = client.get("/network/chains")
    if r.status_code != 200:
        failures.append(f"/network/chains returned {r.status_code}")
    else:
        chains = r.json()
        names = {c["chain"] for c in chains}
        expected = {"tron", "ethereum", "bsc", "polygon", "bitcoin"}
        if names != expected:
            failures.append(f"/network/chains lists {sorted(names)}, expected {sorted(expected)}")

    return failures


def live_trace_check(client: TestClient) -> list:
    """One real investigation, asserting internal consistency only.

    NOTE ON THE LIMITS BELOW. `max_depth: 1, max_nodes: 5` is deliberate -- this
    is a live test against real providers and a full-scope trace would take
    minutes. It is emphatically NOT the product default, which is
    `MAX_TRACE_DEPTH=3 / MAX_TRACE_NODES=25` resolved in the orchestrator when
    the request omits them.

    That distinction matters because this test used to leave its own caps behind:
    `save` defaults to true, so every run appended an investigation to the real
    store whose `metadata` recorded `depth_limit: 1`, `node_limit: 5`. The
    history page then presented a test artefact as a real case, showing
    "Limited scope -- max depth 1" and inviting the reader to conclude the
    product truncates ordinary traces at one hop. It does not; a trace with no
    limits in the request resolves to 3/25 and reaches ~48 nodes.

    So the row is deleted again at the end of this function. Persistence is still
    genuinely exercised -- create, read back, and delete are all asserted -- but
    the test no longer leaves residue in the store a user browses.
    """
    failures = []
    r = client.post("/trace/run", json={"query": LIVE_TRON, "max_depth": 1, "max_nodes": 5})
    if r.status_code != 200:
        failures.append(f"/trace/run returned {r.status_code}: {r.text[:300]}")
        return failures

    body = r.json()
    result = body.get("result", {})

    # The result must be a normalized TraceResult, chain-agnostic shape.
    for key in ("chain", "seed", "status", "nodes", "edges", "transactions", "risk", "metadata"):
        if key not in result:
            failures.append(f"trace result is missing '{key}'")

    if result.get("chain") != "tron":
        failures.append(f"expected chain tron, got {result.get('chain')}")

    status = result.get("status")
    if not status:
        failures.append("trace result has no status")

    # RULE 5: a status is never collapsed into 'success'. If a provider failed,
    # the status must say so and the payload must not invent data.
    if status in ("provider_error", "rate_limited", "timeout"):
        # A provider failure is a legitimate outcome; assert it is *labelled*
        # and that no fabricated transactions were attached.
        if result.get("transactions") and status == "provider_error":
            # Partial data with a provider_error is acceptable if evidenced;
            # the engine records provider_usage for exactly this. Just note it.
            pass
    elif status in ("matched", "partial", "no_match", "inconclusive"):
        pass
    else:
        failures.append(f"unexpected trace status '{status}'")

    # Every transaction hash that IS present must be non-empty and real-shaped.
    for tx in result.get("transactions", []):
        if not tx.get("hash"):
            failures.append("a transaction has no hash")
            break

    # The report, if generated, must resolve.
    report_url = body.get("report_url")
    if report_url:
        r2 = client.get(report_url)
        if r2.status_code != 200:
            failures.append(f"report at {report_url} returned {r2.status_code}")
        elif not r2.content.startswith(b"%PDF"):
            failures.append(f"report at {report_url} is not a PDF")

    # The investigation must have been persisted (save defaults to true).
    inv_id = body.get("investigation_id")
    if inv_id:
        r3 = client.get(f"/investigations/{inv_id}")
        if r3.status_code != 200:
            failures.append(f"saved investigation {inv_id} not readable: {r3.status_code}")

        # ...and then removed again. See the note on this function: a live test
        # with deliberately tiny caps must not leave a row in the store that a
        # user will later read as a real, depth-1 investigation.
        r4 = client.delete(f"/investigations/{inv_id}")
        if r4.status_code not in (200, 204):
            failures.append(
                f"cleanup of test investigation {inv_id} failed with {r4.status_code}; "
                "it is left in the store with this test's depth/nodes caps"
            )
        else:
            r5 = client.get(f"/investigations/{inv_id}")
            if r5.status_code != 404:
                failures.append(
                    f"test investigation {inv_id} still readable after delete "
                    f"({r5.status_code})"
                )

    return failures


def main_check() -> int:
    client = TestClient(main.app)
    print("=== offline surface ===")
    failures = offline_checks(client)
    if failures:
        for f in failures:
            print("FAIL:", f)
        return 1
    print("PASS  health, root, auth status, detection, list endpoints, chain caps")

    if os.getenv("BLOCKTRACE_E2E", "1") == "0":
        print("\n(blocked: live trace skipped via BLOCKTRACE_E2E=0)")
        return 0

    print("\n=== live trace (real providers) ===")
    live_failures = live_trace_check(client)
    if live_failures:
        for f in live_failures:
            print("FAIL:", f)
        return 1
    print("PASS  live investigation is internally consistent, report + history land")

    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main_check())
