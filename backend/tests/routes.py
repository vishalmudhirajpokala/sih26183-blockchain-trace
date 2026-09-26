"""
Route inventory: what the API actually serves.

A router that fails to register produces a 404, which reads as "this feature
does not exist" rather than "this build is broken". So this asserts the surface
is really reachable.

NOTE ON HOW THIS INSPECTS: FastAPI 0.141 stores an included router in
`app.routes` as an `_IncludedRouter` wrapper rather than flattening its routes
into the top-level list. Walking `app.routes` directly therefore shows the
wrappers and finds nothing, which is how an earlier version of this test
"proved" 21 working endpoints were missing. The source of truth is the OpenAPI
schema, which is what a client actually receives — so this reads that instead.
"""

import sys

sys.path.insert(0, ".")

import main  # noqa: E402
from services.chain_registry import supported_chains  # noqa: E402


def main_check() -> int:
    # The contract a client sees.
    schema = main.app.openapi()
    paths = schema.get("paths", {})

    served = set()
    for path, operations in paths.items():
        for method in operations:
            if method.upper() in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                served.add((method.upper(), path))

    print("Routes in the OpenAPI schema:")
    for method, path in sorted(served, key=lambda x: (x[1], x[0])):
        print(f"  {method:6} {path}")

    failures = []

    def expect(method, path):
        if (method, path) not in served:
            failures.append(f"missing {method} {path}")

    # -- the investigation journey, endpoint by endpoint ----------------
    expect("POST", "/trace/detect")
    expect("POST", "/trace/run")
    expect("GET", "/investigations")
    expect("GET", "/investigations/{investigation_id}")
    expect("POST", "/investigations")
    expect("DELETE", "/investigations/{investigation_id}")
    expect("GET", "/analytics/overview")
    expect("GET", "/analytics/risk-trend")
    expect("GET", "/entities")
    expect("GET", "/entities/types")
    expect("GET", "/entities/{chain_value}/{address}")
    expect("GET", "/network/chains")
    expect("GET", "/network/status")
    expect("GET", "/network/overview")
    expect("GET", "/reports")
    expect("GET", "/reports/{filename}")
    expect("POST", "/reports/{investigation_id}/regenerate")
    expect("GET", "/auth/status")
    expect("POST", "/auth/login")
    expect("POST", "/auth/signup")
    expect("POST", "/auth/logout")

    # -- the legacy endpoint must survive the refactor -------------------
    expect("POST", "/trace")
    expect("GET", "/")
    expect("GET", "/health")

    # -- the two /trace paths must both exist and be distinct ------------
    # `/trace` is the legacy TRON-only handler in main.py; `/trace/run` is the
    # multi-chain engine. If either is shadowed the other, one of them is dead
    # code that still looks alive.
    for required in ("/trace", "/trace/run", "/trace/detect"):
        if required not in paths:
            failures.append(f"legacy/new trace path {required} absent from schema")

    # -- the health response must not under-report the chains -------------
    health = main.health()
    declared = {c.value for c in supported_chains()}
    if set(health.chains) != declared:
        failures.append(
            f"health reports chains {sorted(health.chains)} but the registry "
            f"has {sorted(declared)}"
        )
    if not health.persistence:
        failures.append("health does not report which persistence backend is in use")
    if not health.auth:
        failures.append("health does not report the auth mode")

    # -- RULE 7: no secret may appear anywhere in the schema --------------
    # -- the report must actually render ---------------------------------
    # A report route that is registered but throws is worse than an absent one:
    # the UI offers "Export PDF Report", the call 500s, and the failure is
    # reported as `ValueError` with no field named. This renders a report from
    # whatever stored investigations exist, so a regression in the renderer is
    # caught here rather than by a user clicking the button.
    import tempfile  # noqa: E402

    from fastapi.testclient import TestClient  # noqa: E402
    from services.repository import get_repository  # noqa: E402
    from services.report_service import render_trace_report  # noqa: E402
    from services.trace_orchestrator import TraceResult  # noqa: E402

    # In demo auth there is no signed-in user, so the row-level owner filter is
    # None -- the same value the route itself resolves.
    rows, _ = get_repository().list_investigations(limit=1, offset=0, user_id=None)
    if not rows:
        print()
        print("SKIP  no stored investigation available to render a report from")
    else:
        row = rows[0]
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as fh:
                out = fh.name
            render_trace_report(
                TraceResult.from_dict(row["result"]),
                out,
                investigator="contract-test",
            )
            import os  # noqa: E402

            size = os.path.getsize(out)
            with open(out, "rb") as fh:
                magic = fh.read(5)
            os.unlink(out)
            if size < 1024:
                failures.append(
                    f"report rendered to only {size} bytes; a PDF dossier is not empty"
                )
            elif magic != b"%PDF-":
                failures.append(
                    f"report is not a PDF: file starts with {magic!r}, not %PDF-"
                )
            else:
                print(f"report renders   : {size} bytes, valid %PDF- header")
        except Exception as exc:  # noqa: BLE001
            failures.append(
                f"REPORT RENDER FAILED: {type(exc).__name__}: {exc}"
            )

    # -- the risk level colour must be renderable at EVERY level -----------
    # The "Risk level" row interpolates a colour into a ReportLab `<font>`
    # attribute. That expression once did `HexColor.hexval()[2:]`, which strips
    # the "0x" and leaves a bare "b04a00" that `toColor` rejects -- so every
    # report raised `ValueError: Invalid color value 'b04a00'`, and because the
    # row is unconditional it failed for every risk level, not just one.
    #
    # Rendering a single stored case only covers whichever level that case
    # happens to be, so this asserts all of them directly. It is a guard on the
    # colour format only: no report layout, content or metadata is touched.
    from reportlab.lib import colors as _rl_colors  # noqa: E402
    from reportlab.lib.styles import getSampleStyleSheet as _styles  # noqa: E402
    from reportlab.platypus import (  # noqa: E402
        Paragraph as _Paragraph,
        SimpleDocTemplate as _Doc,
    )

    from services.report_service import _RISK_COLOURS  # noqa: E402

    _ss = _styles()
    for _level in _RISK_COLOURS:
        # Exactly the value the renderer passes to <font color=...>.
        _hexval = _RISK_COLOURS[_level].hexval()
        try:
            _Doc(
                tempfile.mktemp(suffix=".pdf")
            ).build(
                [
                    _Paragraph(
                        f'<font color="{_hexval}"><b>{_level}</b></font>',
                        _ss["BodyText"],
                    )
                ]
            )
        except Exception as exc:  # noqa: BLE001
            failures.append(
                f"REPORT COLOUR INVALID for risk level {_level}: "
                f"{type(exc).__name__}: {exc}"
            )
    if not any(f.startswith("REPORT COLOUR") for f in failures):
        print(
            "report colours   : all "
            f"{len(_RISK_COLOURS)} risk levels render"
        )

    # -- the report must lead with the finding, not the machinery ----------
    # A forensic dossier is read in two different ways by two different people.
    # The evaluator wants the conclusion first; the analyst who intends to rely
    # on it wants the provenance, the movement table and the call log. Both need
    # to be there, but the order is what makes the first read possible -- and
    # order is exactly the thing that silently drifts when a section is added
    # somewhere convenient rather than somewhere intended.
    #
    # So the order is asserted here, against the flowables the renderer actually
    # emits. The test wraps `Paragraph` to record what was drawn while still
    # returning the real object, so the document still builds and the assertion
    # reads the real story rather than the source order of the code. It
    # deliberately does not require a PDF text extractor: `pypdf` is not a
    # declared dependency of this project, and a test that only runs on a
    # machine where somebody happened to `pip install` something is not a test.
    import services.report_service as _rs  # noqa: E402

    _seen: list = []
    _real_paragraph = _rs.Paragraph

    def _recording_paragraph(*args, **kwargs):  # noqa: ANN202
        if args and isinstance(args[0], str):
            _seen.append(args[0])
        return _real_paragraph(*args, **kwargs)

    _expected_order = [
        "At a glance",
        "Risk signals",
        "Engine assessment",
        "Entity attribution",
        "Fund flow",
        "Addresses examined",
        "Appendix: Trace Scope & Provider Diagnostics",
        "Scope and evidence limits",
        "Data sources",
    ]
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as fh:
            order_out = fh.name
        _rs.Paragraph = _recording_paragraph
        try:
            render_trace_report(
                TraceResult.from_dict(row["result"]),
                order_out,
                investigator="contract-test",
            )
        finally:
            _rs.Paragraph = _real_paragraph
        os.unlink(order_out)

        _positions = []
        for _heading in _expected_order:
            _at = next(
                (i for i, t in enumerate(_seen) if t.strip() == _heading), -1
            )
            if _at < 0:
                failures.append(
                    f"REPORT ORDER: section {_heading!r} is not in the document"
                )
            else:
                _positions.append((_heading, _at))
        _ordered = [p for _, p in _positions]
        if _ordered != sorted(_ordered):
            failures.append(
                "REPORT ORDER: sections render out of order: "
                + " -> ".join(h for h, _ in _positions)
            )
    except Exception as exc:  # noqa: BLE001
        failures.append(f"REPORT ORDER CHECK FAILED: {type(exc).__name__}: {exc}")

    if not any(f.startswith("REPORT ORDER") for f in failures):
        # Also assert the two promises that make page 1 honest rather than
        # merely present: the destination row must never render blank, and the
        # triage disclaimer must survive verbatim next to the score it limits.
        #
        # Which of the two destination forms is correct depends on the case, so
        # the assertion follows the stored result rather than demanding one
        # particular wording unconditionally.
        _has_entity = bool(TraceResult.from_dict(row["result"]).entity)
        if _has_entity:
            if not any(
                TraceResult.from_dict(row["result"]).entity.name in t
                for t in _seen
            ):
                failures.append(
                    "REPORT ORDER: this investigation resolved an entity but "
                    "its name is absent from the document"
                )
        elif not any(
            "No known destination identified" in t for t in _seen
        ):
            failures.append(
                "REPORT ORDER: no entity was resolved, so the summary must "
                "state 'No known destination identified' rather than leaving "
                "the destination row blank"
            )
        if not any(
            "Scoring is a triage aid, not a probability of wrongdoing."
            in t
            for t in _seen
        ):
            failures.append(
                "REPORT ORDER: the triage disclaimer is missing from the "
                "summary; the score must never appear without its limits"
            )
        if not any(f.startswith("REPORT ORDER") for f in failures):
            print("report order     : finding first, appendix last (9 sections)")

    # The OpenAPI document is fetched by the browser. A service-role key or a
    # real provider key showing up in it would be a leak in the one artefact
    # every client can read.
    import config  # noqa: E402
    import json

    blob = json.dumps(schema, default=str)
    for secret_name, secret in (
        ("SUPABASE_SERVICE_ROLE_KEY", config.SUPABASE_SERVICE_ROLE_KEY),
        ("SUPABASE_ANON_KEY", config.SUPABASE_ANON_KEY),
        ("ETHERSCAN_API_KEY", config.ETHERSCAN_API_KEY),
        ("TRONSCAN_API_KEY", config.TRONSCAN_API_KEY),
    ):
        if secret and len(secret) > 8 and secret in blob:
            failures.append(f"SECRET LEAK: {secret_name} appears in the OpenAPI schema")

    print()
    print(f"supported chains : {sorted(declared)}")
    print(f"persistence      : {health.persistence}")
    print(f"auth mode        : {health.auth}")
    print(f"served routes    : {len(served)}")

    if failures:
        print()
        for f in failures:
            print("FAIL:", f)
        return 1

    print()
    print("PASS  every expected route is served; legacy + multi-chain coexist;")
    print("      health is honest about chains/persistence/auth; no secrets in schema")
    return 0


if __name__ == "__main__":
    sys.exit(main_check())
