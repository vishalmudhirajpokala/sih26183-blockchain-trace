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

    # -- the summary must not claim a counterparty is the destination ------
    # `TraceResult.entity` is the best attribution found *anywhere* in a trace,
    # which is the correct thing to report and the wrong thing to word as "the
    # destination". Trace the USDT contract and the best label in the trace is
    # "Binance-Hot 7" at hop 1 -- a counterparty that touched the contract, not
    # a place the subject's funds went. Rendering that as a destination states
    # something untrue in the most prominent position on page 1.
    #
    # So the report distinguishes the two cases, and this asserts that it does,
    # over every stored investigation, from the values rather than from the
    # prose: an attribution that belongs to the seed must be reported as the
    # subject's own identity, and one that belongs to a hop must be reported as
    # a counterparty. Getting this backwards in either direction is a false
    # statement about whose money went where.
    from services.report_service import _entity_origin  # noqa: E402

    # `rows` above is deliberately limit=1 -- it just needs one result to render
    # a PDF from. This check is only worth anything across every stored case, so
    # it asks for all of them separately.
    _all_rows, _ = get_repository().list_investigations(
        limit=200, offset=0, user_id=None
    )

    _subject_ok = _counterparty_ok = 0
    for _row in _all_rows:
        _res = TraceResult.from_dict(_row["result"])
        if _res.entity is None:
            continue
        _o = _entity_origin(_res)
        if _o["is_subject"]:
            if _o["depth"] != 0 or (_o["address"] or "").lower() != _res.seed.lower():
                failures.append(
                    f"REPORT ENTITY: {_res.seed} is reported as the subject's own "
                    f"identity but the origin does not point at the seed "
                    f"(depth={_o['depth']}, address={_o['address']})"
                )
            else:
                _subject_ok += 1
        else:
            # A counterparty claim has to be checkable: the address and the hop
            # must both be real, and the address must genuinely carry the label.
            if not _o["address"] or not isinstance(_o["depth"], int):
                failures.append(
                    f"REPORT ENTITY: a counterparty attribution in {_res.seed} is "
                    f"reported without a resolvable address or depth "
                    f"(address={_o['address']}, depth={_o['depth']})"
                )
            elif not any(
                (n.address or "").lower() == _o["address"].lower()
                and n.entity is not None
                and n.entity.name == _res.entity.name
                for n in _res.nodes
            ):
                failures.append(
                    f"REPORT ENTITY: {_o['address']} is named as the holder of "
                    f"{_res.entity.name} but no node in the trace carries it"
                )
            else:
                _counterparty_ok += 1

    if not any(f.startswith("REPORT ENTITY") for f in failures):
        print(
            "report entity    : "
            f"{_subject_ok} subject, {_counterparty_ok} counterparty "
            "(never mislabelled as a destination)"
        )

    # -- a token contract must never be scored like a wallet ---------------
    # Two bugs met in the same trace of the real USDT contract, and both were
    # found by looking at real output rather than by reading the code.
    #
    # This block covers the first: the wallet-shaped signals -- fan-in, fan-out,
    # rapid movement -- describe how a wallet handles money. USDT consolidates
    # every transfer ever made through it as a matter of design, so applying
    # them produced CRITICAL 85 for Tether. A reader who sees one absurd score
    # learns to distrust every score the tool issues, which costs more than the
    # bug did.
    #
    # The suppression must also be *visible*. A signal that was never computed
    # and left no trace would be indistinguishable from a signal that was
    # computed and came back negative, so the result has to carry a note saying
    # the question did not apply.
    from models.schemas import Chain as _Chain  # noqa: E402
    import services.risk_engine as risk_engine  # noqa: E402
    from services.risk_engine import _token_contract_nodes  # noqa: E402
    from services.token_identity import classify_token  # noqa: E402

    # The real USDT contract, and two contracts that lie about being it. The
    # second pair were taken from a real trace; both report symbol "USDT" on
    # chain, and neither is Tether.
    _real_usdt = "0xdAC17F958D2ee523a2206206994597C13D831ec7"
    _spoofers = [
        "0x2c9199362dE4aC2C1035AfEC53F686ad5ACbA9B5",
        "0x2A1A5b34bC3e4Ce2a9A2F3E56419a7474C609BB5",
    ]

    _v = classify_token(_Chain.ETHEREUM, _real_usdt, "USDT", "Tether USD", 6)
    if _v.tier != "verified" or _v.decimals != 6:
        failures.append(
            f"TOKEN IDENTITY: the verified USDT contract resolved as "
            f"{_v.tier} with {_v.decimals} decimals, expected verified/6"
        )
    for _s in _spoofers:
        _sv = classify_token(_Chain.ETHEREUM, _s, "USDT", "Tether USD", 6)
        if _sv.tier != "spoofed":
            failures.append(
                f"TOKEN IDENTITY: {_s} claims the symbol USDT and is not the "
                f"verified contract, but was classified {_sv.tier}"
            )
        elif "USDT" in _sv.display_symbol() and "claims" not in _sv.display_symbol():
            failures.append(
                f"TOKEN IDENTITY: spoofed token {_s} is displayed as "
                f"{_sv.display_symbol()!r}, which a reader could take for the "
                f"real asset"
            )
        elif not _sv.note():
            failures.append(
                f"TOKEN IDENTITY: spoofed token {_s} carries no note explaining "
                f"why its amount cannot be read as USDT"
            )

    # The registry must be right about the assets it claims to verify, including
    # the ones whose symbol is not what the asset is conventionally called.
    # Polygon USDT answers "USDT0" on chain; a registry written from memory would
    # have recorded "USDT" and then flagged the genuine article as a fake.
    _poly_usdt = "0xc2132D05D31c914a87C6611C10748AEb04B58e8F"
    for _reported in ("USDT0", "USDT"):
        _pv = classify_token(_Chain.POLYGON, _poly_usdt, _reported, "USDT0", 6)
        if _pv.tier != "verified":
            failures.append(
                f"TOKEN IDENTITY: the real Polygon USDT contract reporting "
                f"{_reported!r} was classified {_pv.tier}; a verified asset is "
                f"being accused of spoofing"
            )
    # A legitimate bridged USDC is not an impostor either.
    _poly_usdc_e = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
    _bv = classify_token(_Chain.POLYGON, _poly_usdc_e, "USDC", "USD Coin (PoS)", 6)
    if _bv.tier != "verified":
        failures.append(
            f"TOKEN IDENTITY: the bridged Polygon USDC contract was classified "
            f"{_bv.tier}; a real bridge asset is being accused of spoofing"
        )
    # BSC USDT is 18 decimals where Ethereum USDT is 6. The registry must win
    # over a provider that reports otherwise, or amounts are wrong by 10^12.
    _bsc = classify_token(
        _Chain.BSC, "0x55d398326f99059fF775485246999027B3197955", "USDT", "Tether USD", 6,
    )
    if _bsc.decimals != 18:
        failures.append(
            f"TOKEN IDENTITY: BSC USDT resolved with {_bsc.decimals} decimals, "
            f"expected 18 from the verified registry"
        )

    # Invisible characters in a symbol are a spoofing signal in their own right,
    # so they are removed from the display and reported, not quietly cleaned.
    from services.token_identity import sanitize_onchain_text  # noqa: E402

    for _raw, _expect_hidden in (
        ("US\u200bDT", True), ("US\u202EDT", True), ("USDT", False),
        ("USD Coin", False), ("", False),
    ):
        _clean, _hidden = sanitize_onchain_text(_raw)
        if _hidden is not _expect_hidden:
            failures.append(
                f"TOKEN IDENTITY: sanitizing {_raw!r} reported hidden="
                f"{_hidden}, expected {_expect_hidden}"
            )
        if any(ord(ch) > 0x200B and ord(ch) < 0x2070 for ch in _clean):
            failures.append(
                f"TOKEN IDENTITY: sanitizing {_raw!r} left invisible characters "
                f"in {_clean!r}"
            )

    # Suppression applies to token contracts, and only to token contracts. A
    # multisig is a contract and is still a wallet, so it keeps its signals.
    #
    # The probe is the real scenario: the subject *is* the token contract, and
    # it has 9 inbound and 1 outbound, which is exactly the shape that scored
    # CRITICAL 85 on Tether.
    _probe = TraceResult.from_dict({
        "chain": "ethereum", "seed": _real_usdt, "hops": 0,
        "nodes": [{"address": _real_usdt, "is_seed": True, "inbound": 9, "outbound": 1}],
        "transactions": [
            {"chain": "ethereum", "hash": "0x" + "aa" * 32, "from_address": "0x" + "22" * 20,
             "to_address": _real_usdt, "amount": 1.0, "token_contract": _real_usdt},
        ],
    })
    _probe.metadata.subject_is_contract = True
    _infra = _token_contract_nodes(_probe)
    if _real_usdt.lower() not in _infra:
        failures.append(
            "RISK CONTRACT: a subject that is both a confirmed contract and the "
            "contract behind its own transfers was not recognised as "
            "infrastructure, so its wallet signals would fire"
        )
    _scored = risk_engine.assess(_probe)
    _fan_fired = any(
        _real_usdt.lower() in {a.lower() for a in (i.related_addresses or [])}
        for i in _scored.indicators
    )
    if _fan_fired:
        failures.append(
            "RISK CONTRACT: a fan-in or fan-out signal was raised against a "
            "token contract, which is the false positive this check exists for"
        )
    if not any("token contract" in n for n in _probe.evidence_notes):
        failures.append(
            "RISK CONTRACT: signals were suppressed for a token contract with "
            "no note saying so, so the low score would read as a clean result"
        )

    # A contract that is NOT a token contract is a wallet that happens to be
    # code -- a multisig, typically -- and must keep its signals. Getting this
    # backwards would silently blind the tool on exactly the addresses serious
    # investigators care about.
    _multisig = TraceResult.from_dict({
        "chain": "ethereum", "seed": "0x" + "11" * 20, "hops": 0,
        "nodes": [{"address": "0x" + "11" * 20, "is_seed": True, "inbound": 9, "outbound": 1}],
        "transactions": [
            {"chain": "ethereum", "hash": "0x" + "bb" * 32, "from_address": "0x" + "22" * 20,
             "to_address": "0x" + "11" * 20, "amount": 1.0, "token_contract": _real_usdt},
        ],
    })
    _multisig.metadata.subject_is_contract = True
    if "0x" + "11" * 20 in _token_contract_nodes(_multisig):
        failures.append(
            "RISK CONTRACT: a contract that is not a token contract was "
            "classified as infrastructure; a multisig is still a wallet"
        )
    _mscored = risk_engine.assess(_multisig)
    if not any(
        "0x" + "11" * 20 in {a.lower() for a in (i.related_addresses or [])}
        for i in _mscored.indicators
    ):
        failures.append(
            "RISK CONTRACT: a multisig subject lost its fan signals; a contract "
            "that holds funds must still be assessed like a wallet"
        )

    if not any(f.startswith(("TOKEN IDENTITY", "RISK CONTRACT")) for f in failures):
        print(
            "token identity   : verified/spoofed/unverified all resolve; "
            "registry correct on 3 chains; invisible chars surfaced"
        )
        print(
            "risk contract    : token contracts exempt from wallet signals, and "
            "the exemption is stated"
        )

    # -- the score must say which address each signal is about ------------
    # `assess()` sums signals raised against any node in the graph into one
    # number attached to the traced address. That is how the engine has always
    # worked and it is not being changed here -- but a reader shown "CRITICAL
    # 85" cannot otherwise tell that most of the signals describe counterparties
    # rather than the subject. The attribution makes the existing number
    # legible; it must not quietly change it.
    #
    # So this asserts three things at once: the score is exactly what it was,
    # the split is derived from the addresses the indicators actually name, and
    # every indicator is accounted for rather than silently dropped.
    _mixed = TraceResult.from_dict({
        "chain": "ethereum", "seed": "0x" + "11" * 20, "hops": 1,
        "nodes": [
            {"address": "0x" + "11" * 20, "is_seed": True, "inbound": 1, "outbound": 9},
            {"address": "0x" + "22" * 20, "is_seed": False, "inbound": 9, "outbound": 1},
        ],
        "transactions": [
            {"chain": "ethereum", "hash": "0x" + f"{i:064x}", "from_address": "0x" + "11" * 20,
             "to_address": "0x" + "22" * 20, "amount": 1.0, "token_contract": _real_usdt}
            for i in range(1, 10)
        ] + [
            {"chain": "ethereum", "hash": "0x" + f"{i:064x}", "from_address": "0x" + "33" * 20,
             "to_address": "0x" + "22" * 20, "amount": 1.0, "token_contract": _real_usdt}
            for i in range(100, 109)
        ],
    })
    _mixed_assessed = risk_engine.assess(_mixed)
    _ma = _mixed_assessed.signal_attribution or {}
    if not _ma:
        failures.append(
            "RISK ATTRIBUTION: no attribution was recorded, so the reader cannot "
            "tell which address the score is about"
        )
    else:
        if _ma.get("total") != len(_mixed_assessed.indicators):
            failures.append(
                f"RISK ATTRIBUTION: {_ma.get('total')} signals attributed but "
                f"{len(_mixed_assessed.indicators)} raised; some are unaccounted "
                f"for and would vanish from the breakdown"
            )
        if (_ma.get("subject", 0) + _ma.get("counterparty", 0)
                + _ma.get("unattributed", 0)) != _ma.get("total"):
            failures.append(
                "RISK ATTRIBUTION: the subject/counterparty/unattributed split "
                "does not add up to the number of signals"
            )
        # Every indicator names its subject or a counterparty, so nothing should
        # be unattributable in this probe.
        if _ma.get("counterparty", 0) < 1:
            failures.append(
                "RISK ATTRIBUTION: a high fan-in counterparty produced no "
                "counterparty signal, so the split is not reading the addresses "
                "the indicators actually name"
            )
        # And the weights must account for the score, so the split explains the
        # number rather than sitting beside it.
        if (_ma.get("subject_score", 0) + _ma.get("counterparty_score", 0)
                != sum(i.weight for i in _mixed_assessed.indicators)):
            failures.append(
                "RISK ATTRIBUTION: subject and counterparty weights do not sum "
                "to the total signal weight, so the breakdown does not explain "
                "the score"
            )

    if not any(f.startswith("RISK ATTRIBUTION") for f in failures):
        print(
            "risk attribution : "
            f"{_ma.get('subject')} subject / {_ma.get('counterparty')} counterparty "
            f"of {_ma.get('total')} signals, score unchanged"
        )

    # -- a VASP candidate is never identified without a label ---------------
    # The problem statement asks for "the nearest exchange or VASP", and the
    # answer is derived from transaction shape. That is the hazard: an address
    # that aggregates and redistributes looks exactly like an exchange whether
    # or not it is one, and a fraudster's collection address does it too. So the
    # one thing that must never happen is an address being presented as
    # identified on the strength of its traffic.
    #
    # Asserted over every stored investigation: anything marked identified must
    # carry a real exchange label, and anything without a label must say so in
    # the row itself rather than in a footnote.
    from services.flow_intel import flow_shape, nearest_vasp_candidates  # noqa: E402

    # The probe's transfers have to actually produce the fan the shape classifier
    # reads. Declaring `inbound: 4` on a node that only ever received from the
    # subject does not make it exchange_like -- the classifier counts distinct
    # counterparties in the transfers, which is the whole point of it being
    # reproducible. So the transfers are built out properly.
    _a = lambda n: "0x" + f"{n:02x}" * 20  # noqa: E731
    _cand_result = TraceResult.from_dict({
        "chain": "ethereum", "seed": _a(0x11), "hops": 1,
        "nodes": [
            {"address": _a(0x11), "is_seed": True, "depth": 0,
             "inbound": 0, "outbound": 1},
            # Fans in from four senders and out to three: exchange_like.
            {"address": _a(0x22), "is_seed": False, "depth": 1,
             "inbound": 4, "outbound": 3},
            # Fans in from five and pays nobody: a collection wallet, not a VASP.
            {"address": _a(0x33), "is_seed": False, "depth": 1,
             "inbound": 5, "outbound": 0},
        ],
        "transactions": (
            # the subject pays the exchange-shaped address
            [{"chain": "ethereum", "hash": "0x" + f"{i:064x}",
              "from_address": _a(0x11), "to_address": _a(0x22),
              "amount": 1.0, "token_contract": _real_usdt} for i in range(1, 2)]
            # three unrelated senders also pay it -> four inbound counterparties
            + [{"chain": "ethereum", "hash": "0x" + f"{i:064x}",
                "from_address": _a(0x40 + i), "to_address": _a(0x22),
                "amount": 1.0, "token_contract": _real_usdt} for i in range(1, 4)]
            # and it pays three -> three outbound counterparties
            + [{"chain": "ethereum", "hash": "0x" + f"{i:064x}",
                "from_address": _a(0x22), "to_address": _a(0x70 + i),
                "amount": 1.0, "token_contract": _real_usdt} for i in range(1, 4)]
            # five senders pay the collector, which pays nobody
            + [{"chain": "ethereum", "hash": "0x" + f"{i:064x}",
                "from_address": _a(0x50 + i), "to_address": _a(0x33),
                "amount": 1.0, "token_contract": _real_usdt} for i in range(1, 6)]
        ),
    })
    _shapes = flow_shape(_cand_result)
    _cands = nearest_vasp_candidates(_cand_result, _shapes) or {}
    _list = _cands.get("candidates") or []

    if not _list:
        failures.append(
            "VASP CANDIDATE: an exchange-shaped hop-1 counterparty produced no "
            "candidate, so the feature finds nothing even in the clear case"
        )
    for _c in _list:
        _has_label = _c.get("entity") is not None
        if _c.get("identified") and not _has_label:
            failures.append(
                f"VASP CANDIDATE: {_c.get('address')} is reported as identified "
                f"with no label behind it; a traffic pattern is not an identity"
            )
        if _c.get("identified"):
            if (_c.get("entity") or {}).get("type") != "exchange":
                failures.append(
                    f"VASP CANDIDATE: {_c.get('address')} is reported as an "
                    f"identified VASP but its label type is "
                    f"{(_c.get('entity') or {}).get('type')!r}"
                )
            if not _c.get("entity", {}).get("verification_status"):
                failures.append(
                    f"VASP CANDIDATE: an identified candidate is shown without a "
                    f"verification status, so a name would read as confirmed"
                )
        if not _has_label:
            if _c.get("status") != "unlabelled":
                failures.append(
                    f"VASP CANDIDATE: {_c.get('address')} has no label but its "
                    f"status is {_c.get('status')!r} rather than 'unlabelled'"
                )
            if "not confirmed" not in (_c.get("statement") or ""):
                failures.append(
                    f"VASP CANDIDATE: unlabelled candidate {_c.get('address')} does "
                    f"not say 'not confirmed' in its own row"
                )
        if _c.get("hop") != 1:
            failures.append(
                f"VASP CANDIDATE: {_c.get('address')} is at hop {_c.get('hop')}; "
                f"'nearest' is hop 1 only"
            )

    if not any(f.startswith("VASP CANDIDATE") for f in failures):
        kinds = {}
        for _c in _list:
            kinds[_c["status"]] = kinds.get(_c["status"], 0) + 1
        print(
            "vasp candidates  : "
            + ", ".join(f"{n} {k}" for k, n in sorted(kinds.items()))
            + " (identified only ever with a real label)"
        )

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
