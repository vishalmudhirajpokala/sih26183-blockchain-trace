"""
Multi-chain forensic report renderer.

Turns a `TraceResult` into a PDF dossier. This is a NEW renderer built on the
normalized model; the original TRON-only `report.py` is left untouched and
still used by the legacy `/trace` path, so no working functionality is
discarded. New multi-chain traces come through here.

The report obeys the same evidence discipline as the engine:

- Every factual row cites the provider it came from.
- Every attribution prints its provenance tier. A public provider label is
  shown as a public provider label, never as a verified fact.
- Indicators are printed as signals with their evidence, and the assessment
  paragraph is shown in full so a reader can see the engine's own words next to
  the score.
- Anything the engine could not determine is printed as "Not available", never
  as a blank and never as a guess.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from xml.sax.saxutils import escape

from models.schemas import TraceResult
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

_INK = colors.HexColor("#172033")
_MUTED = colors.HexColor("#667085")
_NAVY = colors.HexColor("#19365F")
_RULE = colors.HexColor("#D6DBE4")

#: Risk levels get a colour, but the colour never changes the words. The text
#: is what a reader acts on; colour is a scanning aid only.
_RISK_COLOURS = {
    "LOW": colors.HexColor("#1E7A45"),
    "MEDIUM": colors.HexColor("#8A6100"),
    "MEDIUM-HIGH": colors.HexColor("#B04A00"),
    "HIGH": colors.HexColor("#B3261E"),
    "CRITICAL": colors.HexColor("#7A0E0E"),
    "UNKNOWN": colors.HexColor("#5B6472"),
}

_PROVENANCE_NOTE = {
    "curated_verified": "Curated and verified by the BlockTrace investigation team.",
    "public_provider": "A public provider label. Not independently verified.",
    "heuristic": "Inferred by BlockTrace rules from observed behaviour. Not a confirmed identity.",
    "none": "No attribution source recorded.",
}


def _source_link(source_url: Any) -> tuple:
    """Markup for a provenance link, or plain text when the URL is unusable.

    Escaping alone is not sufficient here. `escape()` neutralises the markup
    characters, so a source URL can no longer break out of the `href`
    attribute — but the *value* of that attribute is still a URL, and ReportLab
    will happily make a `javascript:` one clickable inside the dossier. A
    citation the investigator is expected to click is the last place to accept
    a scheme unchecked, so the scheme is verified first and the link is
    downgraded to text when it does not pass.

    Downgrading is not a failure. A provenance row with a rejected URL still
    shows the name, address, source label, and confidence weight — the citation
    that cannot be followed is simply reported as one that cannot be followed.
    """
    if not source_url:
        return ("Not available",)
    try:
        parsed = urlparse(str(source_url).strip())
    except ValueError:
        return (f"Supplied but unparseable: {escape(str(source_url))}",)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return (f"Supplied but not an http(s) URL: {escape(str(source_url))}",)
    safe = escape(str(source_url).strip(), {'"': "&quot;"})
    return (f'<link href="{safe}" color="#19365F">{escape(str(source_url))}</link>',)


def _text(value: Any, default: str = "Not available") -> str:
    """Render a value as PDF body text, escaped.

    ReportLab's `Paragraph` is not a plain-text primitive: it parses a small
    inline markup language, so `<`, `&`, and `<link href=...>` in the input are
    instructions to the renderer rather than characters. Most of what reaches
    this function is provider-supplied — a block-explorer's label for an
    address, an evidence string the risk engine assembled out of entity names,
    an error message from an HTTP client — which makes it attacker-influenceable
    in exactly the way that markup injection is about. Unescaped, a provider
    label could inject formatting or a hyperlink into an investigator's dossier,
    and a malformed tag raises at render time, which loses the whole document.

    Escaping here rather than at each call site is deliberate: there are a
    dozen call sites, and the ones added later are the ones that forget.
    """
    if value is None or value == "":
        return escape(default)
    return escape(str(value))


def _amount(value: Any) -> str:
    if value is None:
        return "Not available"
    try:
        number = float(value)
    except (ValueError, TypeError):
        return str(value)
    if number == 0:
        return "0"
    if number.is_integer():
        return f"{number:,.0f}"
    # Keep significant digits without losing a whale's tail: a 9,683,958.88
    # token transfer must not render as "9,683,958" and read as a different
    # amount than the one on chain.
    return f"{number:,.8f}".rstrip("0").rstrip(".")


def _when(unix_seconds: Optional[int]) -> str:
    if not unix_seconds:
        return "Not available"
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(unix_seconds))
    except (ValueError, OSError, OverflowError):
        return "Not available"


def _mono(value: Any, default: str = "Not available") -> str:
    return _text(value, default)


class _Styles:
    def __init__(self) -> None:
        base = getSampleStyleSheet()
        self.title = ParagraphStyle(
            "T", parent=base["Title"], fontName="Helvetica-Bold", fontSize=19,
            leading=23, alignment=TA_CENTER, textColor=_INK, spaceAfter=2 * mm,
        )
        self.subtitle = ParagraphStyle(
            "S", parent=base["Normal"], fontName="Helvetica", fontSize=8.5,
            leading=11, alignment=TA_CENTER, textColor=_MUTED, spaceAfter=7 * mm,
        )
        self.section = ParagraphStyle(
            "H", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=10.5,
            leading=13, textColor=_NAVY, spaceBefore=5 * mm, spaceAfter=2 * mm,
        )
        self.body = ParagraphStyle(
            "B", parent=base["Normal"], fontName="Helvetica", fontSize=8.3,
            leading=11, textColor=_INK,
        )
        self.small = ParagraphStyle(
            "s", parent=base["Normal"], fontName="Helvetica", fontSize=7.2,
            leading=9.5, textColor=_MUTED,
        )
        self.address = ParagraphStyle(
            "a", parent=base["Normal"], fontName="Courier", fontSize=6.9,
            leading=9, textColor=_INK, wordWrap="CJK",
        )


def _kv_table(rows: List[List[Any]], styles: _Styles, label_width: float = 46 * mm) -> Table:
    table = Table(rows, colWidths=[label_width, None])
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, _RULE),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F4F6F9")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("LEADING", (0, 0), (-1, -1), 10.5),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return table


def _header_table(data: List[List[Any]], first_width: float = 40 * mm) -> Table:
    table = Table(data, repeatRows=1, colWidths=[first_width, None, None, None])
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, _RULE),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F4F6F9")),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
    ]))
    return table


def render_trace_report(
    result: TraceResult,
    output_path: str,
    title: Optional[str] = None,
    investigator: Optional[str] = None,
) -> str:
    """
    Render one investigation to `output_path` and return the path.

    The document states its own limits on the cover: which chain, what status,
    whether the trace was truncated, and how many providers were consulted. A
    forensic reader has to know that before reading any conclusion.
    """
    styles = _Styles()
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=16 * mm, leftMargin=16 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
        title=title or f"BlockTrace Forensic Report - {result.seed}",
        author="BlockTrace",
    )
    story: List[Any] = []

    # ---- cover -----------------------------------------------------
    story.append(Paragraph(
        title or "BLOCKTRACE MULTI-CHAIN FORENSIC REPORT", styles.title,
    ))
    story.append(Paragraph(
        f"{result.chain.display_name} &nbsp;|&nbsp; automated fund-flow analysis",
        styles.subtitle,
    ))

    meta = result.metadata
    story.append(Paragraph("Investigation summary", styles.section))
    story.append(_kv_table([
        ["Subject", Paragraph(_mono(result.seed), styles.address)],
        ["Chain", f"{result.chain.display_name} ({result.chain.value})"],
        ["Input type", result.input_type.value],
        ["Status", f"{result.status.value}"],
        ["Status detail", Paragraph(_text(result.status_detail), styles.body)],
        ["Nodes examined", str(meta.nodes_examined)],
        ["Transactions inspected", str(meta.transactions_inspected)],
        ["Depth (limit / reached)", f"{meta.depth_limit} / {meta.max_depth_reached}"],
        ["Hops", str(result.hops)],
        ["Truncated", "Yes" if meta.truncated else "No"],
        ["Providers consulted", str(len(meta.provider_usage))],
        ["Generated", _when(int(meta.completed_at or time.time()))],
        ["Investigation ID", _mono(meta.investigation_id)],
        *([["Investigator", _text(investigator)]] if investigator else []),
    ], styles))

    # ---- evidence limits -------------------------------------------
    story.append(Paragraph("Scope and evidence limits", styles.section))
    limits: List[str] = [
        "This report describes only the data returned by the providers queried, "
        "up to the depth and time limits shown above. It is not a complete "
        "picture of the address's on-chain history.",
    ]
    if meta.truncated:
        limits.append(
            "The trace was truncated: " + "; ".join(meta.truncation_reasons) + ". "
            "Findings beyond that boundary were not examined."
        )
    for note in result.evidence_notes:
        limits.append(note)
    for paragraph in limits:
        story.append(Paragraph(f"&bull; {paragraph}", styles.body))
        story.append(Spacer(1, 1.5 * mm))

    # ---- risk ------------------------------------------------------
    risk = result.risk
    story.append(Paragraph("Risk assessment", styles.section))
    story.append(_kv_table([
        ["Risk score", f"{risk.risk_score} / 100"],
        ["Risk level", Paragraph(
            f'<font color="{_RISK_COLOURS.get(risk.risk_level.value, _MUTED).hexval()[2:]}">'
            f"<b>{risk.risk_level.value}</b></font>", styles.body,
        )],
        ["Signals", str(len(risk.indicators))],
    ], styles, label_width=40 * mm))

    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(
        "Scoring is a triage aid, not a probability of wrongdoing. "
        "Signals are structural observations; they indicate where to look next.",
        styles.small,
    ))

    if risk.indicators:
        story.append(Spacer(1, 2.5 * mm))
        rows: List[List[Any]] = [[
            Paragraph("Signal", styles.body),
            Paragraph("Severity", styles.body),
            Paragraph("Evidence", styles.body),
        ]]
        for indicator in risk.indicators:
            rows.append([
                Paragraph(f"<b>{_text(indicator.name)}</b>", styles.body),
                Paragraph(escape(indicator.severity.value), styles.body),
                Paragraph(escape(indicator.evidence), styles.small),
            ])
        story.append(_header_table(rows, first_width=62 * mm))

    story.append(Spacer(1, 2.5 * mm))
    story.append(Paragraph("Engine assessment", styles.section))
    story.append(Paragraph(escape(risk.assessment), styles.body))

    # ---- entity attribution ---------------------------------------
    story.append(Paragraph("Entity attribution", styles.section))
    if not result.entity:
        story.append(Paragraph(
            "No entity was attributed to any address in this trace. This is a "
            "statement about the retrieved data, not a claim that the addresses "
            "are unlabelled in the wider world.", styles.body,
        ))
    else:
        entity = result.entity
        story.append(_kv_table([
            ["Name", _text(entity.name)],
            ["Type", entity.type.value],
            ["Provenance", Paragraph(
                f"{entity.source_type.value} &mdash; "
                f"{_PROVENANCE_NOTE.get(entity.source_type.value, '')}", styles.body,
            )],
            ["Confidence", f"{entity.confidence}%"],
            ["Verification", entity.verification_status.value],
            ["Source", Paragraph(*_source_link(entity.source_url), styles.body)],
            ["Evidence", Paragraph(
                "<br/>".join(escape(e) for e in entity.evidence)
                if entity.evidence else "None recorded",
                styles.small,
            )],
        ], styles))

    # ---- graph -----------------------------------------------------
    story.append(Paragraph("Fund flow", styles.section))
    if not result.edges:
        story.append(Paragraph(
            "No value movements were retrieved for the addresses examined.",
            styles.body,
        ))
    else:
        graph_rows: List[List[Any]] = [[
            Paragraph("Transaction", styles.body),
            Paragraph("From", styles.body),
            Paragraph("To", styles.body),
            Paragraph("Amount", styles.body),
            Paragraph("Time", styles.body),
        ]]
        for edge in result.edges[:60]:
            graph_rows.append([
                Paragraph(_mono(edge.transaction_hash[:22] + "…"), styles.address),
                Paragraph(_mono(edge.from_address), styles.address),
                Paragraph(_mono(edge.to_address), styles.address),
                Paragraph(f"{_amount(edge.amount)} {_text(edge.asset, '')}".strip(), styles.body),
                Paragraph(_when(edge.timestamp), styles.small),
            ])
        story.append(_header_table(graph_rows, first_width=34 * mm))
        if len(result.edges) > 60:
            story.append(Paragraph(
                f"Showing 60 of {len(result.edges)} movements. The full set is "
                f"in the saved investigation record.", styles.small,
            ))

    # ---- chain detail ---------------------------------------------
    story.append(Paragraph("Addresses examined", styles.section))
    node_rows: List[List[Any]] = [[
        Paragraph("Address", styles.body),
        Paragraph("Depth", styles.body),
        Paragraph("In / Out", styles.body),
        Paragraph("Attribution", styles.body),
        Paragraph("Provenance", styles.body),
    ]]
    for node in result.nodes[:80]:
        node_rows.append([
            Paragraph(_mono(node.address), styles.address),
            str(node.depth),
            f"{node.inbound} / {node.outbound}",
            Paragraph(
                f"<b>{node.entity.name}</b>" if node.entity and node.entity.name
                else "None",
                styles.body,
            ),
            Paragraph(node.source_type.value, styles.small),
        ])
    story.append(_header_table(node_rows, first_width=58 * mm))

    # ---- providers -------------------------------------------------
    story.append(Paragraph("Provider log", styles.section))
    story.append(Paragraph(
        "Which provider served which part of this investigation, and how it "
        "went. A failed call is recorded as a failed call.", styles.small,
    ))
    story.append(Spacer(1, 2 * mm))
    if meta.provider_usage:
        prov_rows: List[List[Any]] = [[
            Paragraph("Provider", styles.body),
            Paragraph("OK", styles.body),
            Paragraph("Status", styles.body),
            Paragraph("Latency", styles.body),
            Paragraph("Error", styles.body),
        ]]
        for usage in meta.provider_usage:
            prov_rows.append([
                Paragraph(_mono(usage.provider), styles.address),
                "yes" if usage.ok else "no",
                _text(usage.status_code),
                f"{usage.latency_ms} ms" if usage.latency_ms is not None else "-",
                Paragraph(_text(usage.error, "-"), styles.small),
            ])
        story.append(_header_table(prov_rows, first_width=36 * mm))
    else:
        story.append(Paragraph(
            "No provider calls were made for this investigation.", styles.body,
        ))

    # ---- footer ----------------------------------------------------
    def _page(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(_MUTED)
        canvas.drawString(16 * mm, 10 * mm, "BlockTrace - automated blockchain forensics")
        canvas.drawRightString(A4[0] - 16 * mm, 10 * mm, f"Page {doc_.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_page, onLaterPages=_page)
    return output_path


def report_filename_for(chain: str, seed: str, investigation_id: Optional[str] = None) -> str:
    """
    A stable, collision-free filename per investigation.

    Keyed on the investigation id when there is one, so re-running the same
    address produces a new document rather than silently overwriting the
    previous case. Two analysts tracing one address must not clobber each
    other's dossier.

    `investigation_id` is client-supplied: it arrives in the body of the save
    request as arbitrary JSON and flows here unfiltered. `safe_seed` below
    strips everything that is not alphanumeric, but the id did not get the same
    treatment, so a value containing a separator or `..` would shape the path
    this function's result is joined into. Filtering it the same way costs
    nothing and removes the question — the id only needs to make the name
    unique, and alphanumerics do that.
    """
    import hashlib

    digest = hashlib.sha256(f"{chain}:{seed}".encode("utf-8")).hexdigest()[:8]
    safe_seed = "".join(c for c in seed[:12] if c.isalnum()) or "seed"
    safe_id = "".join(c for c in str(investigation_id)[:8] if c.isalnum()) if investigation_id else ""
    suffix = f"_{safe_id}" if safe_id else ""
    return f"trace_{safe_seed}_{digest}{suffix}.pdf"
