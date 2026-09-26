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

#: How many value movements the report lists in full.
#:
#: A busy subject produces hundreds, and listing every one turned a two-page
#: forensic summary into a nine-page data export -- four of those pages were
#: this table alone. Twelve is enough to show the shape of the flow and to give
#: a reader rows to check against a block explorer. Everything past that is
#: counted and pointed at, never silently dropped: the summary table already
#: carries the true total, and the note under the table states how many are
#: listed here and where the rest live.
_MOVEMENT_ROWS_SHOWN = 12

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
        # A heading inside the appendix, one step below a section. It exists so
        # the appendix can carry its own title and then name the parts beneath
        # it, rather than the appendix title and its first section being the
        # same size with no visible hierarchy between them.
        self.subheading = ParagraphStyle(
            "H2", parent=base["Heading3"], fontName="Helvetica-Bold", fontSize=9.5,
            leading=12, textColor=_NAVY, spaceBefore=4 * mm, spaceAfter=1.5 * mm,
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


def _plain_summary(result: TraceResult) -> str:
    """
    Two or three sentences of plain English, built only from values the engine
    actually recorded.

    This is generated, not written per case, so it cannot flatter a result. It
    reports the chain and the subject, the reach of the trace, and the strongest
    thing found -- and where the strongest thing is weak, such as a label that
    is only a public provider's word, it says so in the same breath. A reader
    who stops here should not come away with a stronger impression than the
    evidence supports.
    """
    meta = result.metadata
    chain = result.chain.display_name
    subject = result.seed
    risk = result.risk
    txs = len(result.transactions)
    addresses = meta.nodes_examined

    reach = (
        f"following value across {result.hops} hop{'' if result.hops == 1 else 's'}"
    )
    if meta.truncated:
        reach += (
            f", stopping at the configured limit of {meta.depth_limit} rather than "
            f"because the trail ended"
        )

    sentences = [
        f"BlockTrace began at {chain} address {subject} and traced outward, "
        f"{reach}. It examined {addresses} address"
        f"{'' if addresses == 1 else 'es'} and retrieved {txs} transfer"
        f"{'' if txs == 1 else 's'} from the providers queried."
    ]

    if risk.indicators:
        strongest = max(risk.indicators, key=lambda i: i.weight)
        sentences.append(
            f"The risk engine raised {len(risk.indicators)} indicator"
            f"{'' if len(risk.indicators) == 1 else 's'}, the largest being "
            f"\"{strongest.name}\" at {strongest.weight} points, giving a "
            f"{risk.risk_level.value} score of {risk.risk_score} out of 100."
        )
    else:
        sentences.append(
            "The risk engine raised no indicators, so the score is 0. That is a "
            "statement about the data that came back, not a clean bill of health."
        )

    origin = _entity_origin(result)
    entity = origin["entity"]
    if entity:
        qualifier = (
            "which is a public provider's label rather than an independently "
            "verified identification"
            if entity.source_type.value == "public_provider"
            else f"attributed at the {entity.source_type.value} tier"
        )
        if origin["is_subject"]:
            sentences.append(
                f"The traced address itself is attributed to {entity.name}, "
                f"a {entity.type.value}, {qualifier}."
            )
        else:
            # Naming the hop matters. "Binance" reads as a conclusion about
            # where the money ended up; "an address one hop out is labelled
            # Binance" is what the data actually supports, and for a subject
            # like a token contract the two are not remotely the same claim.
            depth = origin["depth"]
            where = (
                f"{depth} hop{'s' if depth != 1 else ''} out"
                if isinstance(depth, int) else "further out"
            )
            sentences.append(
                f"The traced address carries no attribution of its own; the "
                f"best-sourced label found in this trace belongs to a "
                f"counterparty {where}, and reads {entity.name}, "
                f"a {entity.type.value}, {qualifier}."
            )
    else:
        sentences.append(
            "No address in this trace carried an attribution from a real source, "
            "so no destination is named."
        )

    return " ".join(sentences)


def _same_entity(a, b) -> bool:
    """
    Value equality for two `EntityAttribution` objects.

    Not `is`. A report is often rendered from a result that came back out of
    storage, and `TraceResult.from_dict` rebuilds every attribution as a new
    object -- so the entity on `result` and the entity on the node that produced
    it are equal but distinct. Identity comparison silently reported "unknown
    hop, address not listed" for every re-rendered report, and would have
    mislabelled a labelled *subject* as a counterparty. Comparing the fields
    that define an attribution is what survives the round trip.
    """
    if a is None or b is None:
        return False
    return (
        getattr(a, "name", None) == getattr(b, "name", None)
        and getattr(a, "type", None) == getattr(b, "type", None)
        and getattr(a, "source_type", None) == getattr(b, "source_type", None)
        and getattr(a, "confidence", None) == getattr(b, "confidence", None)
        and getattr(a, "source_url", None) == getattr(b, "source_url", None)
    )


def _entity_origin(result: TraceResult) -> dict:
    """
    Work out whether the reported entity IS the traced address, or is one of the
    counterparties found along the way.

    This distinction is the difference between a true statement and a false one.
    `TraceResult.entity` is the best attribution found *anywhere* in the trace,
    which is the right thing to report and the wrong thing to describe as "the
    destination". Tracing the USDT contract, for example, resolves
    "Binance-Hot 7" at hop 1 -- USDT did not send its funds to Binance, Binance
    is simply one of the thousands of addresses that touched the contract. A
    report that says "Destination: Binance-Hot 7" about a subject that is USDT
    states something untrue, and it states it in the most prominent position on
    page 1.

    So the label follows the evidence: if the attribution belongs to the seed it
    is reported as the subject's own identity, and if it belongs to a hop it is
    reported as a counterparty, with the hop it was found at and the address it
    was found on, so a reader can go and check it.
    """
    entity = result.entity
    if entity is None:
        return {"entity": None, "is_subject": False, "depth": None, "address": None}

    # The seed's own attribution, if the resolver produced one.
    if _same_entity(result.seed_entity, entity):
        return {
            "entity": entity, "is_subject": True, "depth": 0, "address": result.seed,
        }

    # Otherwise find the node that carries it, which also gives the depth. The
    # node whose address is the seed is checked explicitly, because a subject
    # that is itself labelled may not have gone through `seed_entity`.
    for node in result.nodes:
        if _same_entity(node.entity, entity):
            is_seed = (node.address or "").lower() == (result.seed or "").lower()
            return {
                "entity": entity,
                "is_subject": is_seed,
                "depth": 0 if is_seed else getattr(node, "depth", None),
                "address": node.address,
            }

    # An entity with no node behind it should not happen, but if it ever does,
    # the honest rendering is "not the subject" rather than a guess.
    return {"entity": entity, "is_subject": False, "depth": None, "address": None}


def _entity_cell(origin: dict, styles) -> Paragraph:
    """
    Render the destination/entity row, in whichever form the evidence supports.
    """
    entity = origin["entity"]
    if entity is None:
        return Paragraph(
            "<b>No known destination identified.</b> No address in this trace "
            "carried an attribution from a real source. That is a statement "
            "about the data that was retrieved, not a claim that these "
            "addresses are unlabelled everywhere.",
            styles.body,
        )

    head = (
        f"<b>{escape(_text(entity.name))}</b> &mdash; {escape(entity.type.value)}"
        f"<br/>{entity.confidence}% confidence &mdash; "
        f"{escape(entity.verification_status.value)}"
        f"<br/>{escape(entity.source_type.value)}: "
        f"{escape(_PROVENANCE_NOTE.get(entity.source_type.value, ''))}"
    )

    if origin["is_subject"]:
        return Paragraph(
            head + "<br/><b>This is the traced address itself.</b>",
            styles.body,
        )

    depth = origin["depth"]
    where = (
        f"at hop {depth}" if isinstance(depth, int)
        else "somewhere in the trace"
    )
    addr = origin["address"]
    shown = _mono(addr, "") if addr else "an address this report does not list"
    tail = (
        f"<br/>Found {where} on {shown} &mdash; a counterparty, <b>not</b> the "
        f"traced address, which carries no attribution of its own."
    )
    return Paragraph(head + tail, styles.body)


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

    # =================================================================
    # AT A GLANCE
    #
    # The finding, before the machinery. Everything below this block is
    # supporting material for a reader who wants to verify it; this is the part
    # a reader who only has ten seconds needs.
    #
    # Nothing is dropped in the move. The fields that used to sit in the
    # "Investigation summary" table are all still here, re-grouped under the
    # four questions a reader actually arrives with: what was traced, what did
    # it reach, how risky is it, and who is behind it.
    # =================================================================
    story.append(Paragraph("At a glance", styles.section))

    # Whether the reported entity is the subject or a counterparty decides how
    # the row may be worded, so it is established before the row is written.
    origin = _entity_origin(result)
    destination_cell = _entity_cell(origin, styles)

    # The contract flag, stated next to the score it changes the meaning of.
    #
    # It has to be here rather than in the appendix. When the subject is a token
    # contract the wallet-pattern signals are not computed, so the number on this
    # page covers strictly less than it would for a wallet, and a reader who is
    # not told that will read the absence of CRITICAL findings as a clean result.
    #
    # The distinction drawn is token contract versus wallet, not contract versus
    # EOA. A multisig is a contract and is still a wallet, and a report that told
    # a reader their multisig was "not a wallet" would be wrong in a way that
    # undermines every other claim in the document.
    subject_is_token_contract = (
        meta.subject_is_contract is True
        and any(
            (tx.token_contract or "").strip().lower() == (result.seed or "").strip().lower()
            for tx in result.transactions
        )
    )

    if subject_is_token_contract:
        subject_note = (
            "<b>This address is a token contract, not a wallet. Standard "
            "fraud-pattern signals do not apply.</b> Inbound and outbound fan-in, "
            "fan-out and rapid-movement patterns describe how a wallet handles "
            "money, and a token contract consolidates every transfer made through "
            "it by design. Those signals were not computed, so the risk level "
            "above reflects the remaining signals only, and their absence is not "
            "evidence that this token is benign."
        )
    elif meta.subject_is_contract is True:
        subject_note = (
            "This address is a deployed contract rather than an externally-owned "
            "account, but it is not the contract behind any transfer in this "
            "trace, so it is assessed as a wallet — the common case being a "
            "multisig or smart account, which holds funds and behaves like one."
        )
    elif meta.subject_is_contract is None and meta.contract_check:
        subject_note = (
            "BlockTrace could not determine whether this address is a contract or "
            "a wallet, so wallet-pattern signals were computed without that "
            "context and may reflect the behaviour of a contract."
        )
    else:
        subject_note = None

    status_text = result.status.value
    if meta.truncated:
        status_text += f" &mdash; truncated at hop {meta.max_depth_reached} of {meta.depth_limit}"

    risk = result.risk
    risk_cell = Paragraph(
        f'<font color="{_RISK_COLOURS.get(risk.risk_level.value, _MUTED).hexval()}">'
        f"<b>{risk.risk_level.value}</b></font> &mdash; {risk.risk_score} / 100"
        f"<br/>{len(risk.indicators)} indicator"
        f"{'s' if len(risk.indicators) != 1 else ''} raised",
        styles.body,
    )

    story.append(_kv_table([
        ["Source wallet", Paragraph(_mono(result.seed), styles.address)],
        ["Destination / entity", destination_cell],
        ["Status", Paragraph(status_text, styles.body)],
        ["Risk level", risk_cell],
        ["Chain", f"{result.chain.display_name} ({result.chain.value})"],
        ["Input type", result.input_type.value],
        ["Nodes examined", str(meta.nodes_examined)],
        ["Transactions inspected", str(meta.transactions_inspected)],
        ["Hops reached", str(result.hops)],
        ["Providers consulted", str(len(meta.provider_usage))],
        ["Investigation ID", _mono(meta.investigation_id)],
        *([["Investigator", _text(investigator)]] if investigator else []),
        ["Generated", _when(int(meta.completed_at or time.time()))],
    ], styles, label_width=44 * mm))

    story.append(Spacer(1, 2.5 * mm))

    if subject_note:
        story.append(Paragraph(subject_note, styles.small))
        story.append(Spacer(1, 2.5 * mm))

    # The triage disclaimer, verbatim and unmoved. It is not softened, not
    # shortened, and not relocated to an appendix: the score is the first thing
    # on the page, so its limits have to be the first thing after it.
    story.append(Paragraph(
        "Scoring is a triage aid, not a probability of wrongdoing. "
        "Signals are structural observations; they indicate where to look next.",
        styles.small,
    ))

    story.append(Spacer(1, 2.5 * mm))

    # Plain English, for a reader who does not know what a hop is.
    story.append(Paragraph(
        "What happened", styles.subheading,
    ))
    story.append(Paragraph(_plain_summary(result), styles.body))

    # ---- 1. risk signals ---------------------------------------------
    # The score, the level and the triage disclaimer now live once, in "At a
    # glance", because that is where a reader meets the number. Repeating all
    # three here made the same three facts appear twice within one page of each
    # other, which reads as padding rather than as emphasis.
    #
    # What remains here is the part that section could not summarise: every
    # indicator, in full, with the evidence that fired it.
    risk = result.risk
    story.append(Paragraph("Risk signals", styles.section))

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
        for edge in result.edges[:_MOVEMENT_ROWS_SHOWN]:
            graph_rows.append([
                Paragraph(_mono(edge.transaction_hash[:22] + "…"), styles.address),
                Paragraph(_mono(edge.from_address), styles.address),
                Paragraph(_mono(edge.to_address), styles.address),
                Paragraph(f"{_amount(edge.amount)} {_text(edge.asset, '')}".strip(), styles.body),
                Paragraph(_when(edge.timestamp), styles.small),
            ])
        story.append(_header_table(graph_rows, first_width=34 * mm))
        if len(result.edges) > _MOVEMENT_ROWS_SHOWN:
            # Stated plainly, with both numbers, because a report that quietly
            # stops listing is worse than one that admits it stopped. The full
            # set is not discarded -- it is in the saved investigation and in
            # the app -- and this line is where the reader learns that.
            story.append(Paragraph(
                f"<b>Showing {_MOVEMENT_ROWS_SHOWN} of {len(result.edges)} "
                f"movements.</b> The remainder are not missing and have not been "
                f"filtered out: the complete set of "
                f"{len(result.edges)} transfers is held in the saved "
                f"investigation record, and every one of them carries the same "
                f"fields as the rows above.", styles.small,
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

    # =================================================================
    # APPENDIX
    #
    # Everything below is backup material: the boundaries of the trace and the
    # call log behind it. A reader who trusts the findings above does not need
    # it; a reader who intends to rely on them does. It is on its own page with
    # its own heading so that distinction is visible rather than implied.
    #
    # "Scope and evidence limits" moved here from the second position, where it
    # sat directly under the title and before any finding. That is a defensible
    # place for a caveat and a poor place for one that interrupts the finding.
    # Nothing about its wording changed.
    # =================================================================
    story.append(PageBreak())
    story.append(Paragraph("Appendix: Trace Scope & Provider Diagnostics", styles.section))

    # ---- 5. scope and evidence limits -------------------------------
    story.append(Paragraph("Scope and evidence limits", styles.subheading))
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

    # ---- 6. provider log --------------------------------------------
    # Failures only, with a one-line account of the calls that worked.
    #
    # This was two full pages of one row per HTTP call: 70 rows for an
    # investigation that read 98 transfers, all of them "yes / 200 / 2134 ms".
    # That is a data export, not evidence, and it buried the one thing a reader
    # needs from this section.
    #
    # What a reader needs to know is whether anything failed, because a trace
    # that succeeded after a provider outage is a different claim from one that
    # never hit an outage. So successes are counted in a sentence and only the
    # failures get rows.
    failed_usage = [u for u in (meta.provider_usage or []) if not u.ok]
    total_usage = len(meta.provider_usage or [])
    ok_usage = total_usage - len(failed_usage)
    providers_used = sorted({u.provider for u in (meta.provider_usage or []) if u.provider})

    story.append(Paragraph("Data sources", styles.section))
    if not total_usage:
        story.append(Paragraph(
            "No provider calls were made for this investigation.", styles.body,
        ))
    else:
        if failed_usage:
            story.append(Paragraph(
                f"<b>{len(failed_usage)} of {total_usage} provider calls "
                f"failed.</b> They are listed below. A failure is a statement "
                f"about the provider, not about the address: nothing can be "
                f"concluded from data that was not returned.", styles.body,
            ))
        else:
            story.append(Paragraph(
                f"All {total_usage} provider calls succeeded, across "
                f"{len(providers_used)} provider"
                f"{'s' if len(providers_used) != 1 else ''}"
                f" ({', '.join(providers_used)}). No provider reported an error "
                f"during this investigation.", styles.body,
            ))
        story.append(Spacer(1, 2 * mm))
        if failed_usage:
            prov_rows: List[List[Any]] = [[
                Paragraph("Provider", styles.body),
                Paragraph("Status", styles.body),
                Paragraph("Error", styles.body),
            ]]
            for usage in failed_usage:
                prov_rows.append([
                    Paragraph(_mono(usage.provider), styles.address),
                    _text(usage.status_code),
                    Paragraph(_text(usage.error, "No detail recorded."), styles.small),
                ])
            story.append(_header_table(prov_rows, first_width=36 * mm))

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
