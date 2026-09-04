
# report.py

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from datetime import datetime


# =========================================================
# FORMATTING HELPERS
# =========================================================

def format_amount(amount):
    """Convert blockchain amount into a clean human-readable value."""

    if amount is None:
        return "N/A"

    try:
        value = float(amount)

        if value.is_integer():
            return f"{value:,.0f}"

        return f"{value:,.2f}".rstrip("0").rstrip(".")

    except (ValueError, TypeError):
        return str(amount)


def format_bool(value):
    """Convert Python boolean values into report-friendly text."""

    if value is True:
        return "Detected"

    if value is False:
        return "None"

    return "N/A"


def safe(value, default="N/A"):
    """Prevent None/empty values from appearing in the report."""

    if value is None or value == "":
        return default

    return str(value)


# =========================================================
# GENERATE REPORT
# =========================================================

def generate_report(verdict, output_path):

    document = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title="Cryptocurrency Forensic Trace Report",
        author="Blockchain Forensic Analysis System",
    )

    styles = getSampleStyleSheet()

    # =====================================================
    # STYLES
    # =====================================================

    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#172033"),
        spaceAfter=4 * mm,
    )

    subtitle_style = ParagraphStyle(
        "Subtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#667085"),
        spaceAfter=8 * mm,
    )

    section_style = ParagraphStyle(
        "Section",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=10.5,
        leading=14,
        textColor=colors.HexColor("#19365F"),
        spaceBefore=5 * mm,
        spaceAfter=2.5 * mm,
    )

    normal_style = ParagraphStyle(
        "NormalReport",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor("#172033"),
    )

    bold_style = ParagraphStyle(
        "BoldReport",
        parent=normal_style,
        fontName="Helvetica-Bold",
    )

    small_style = ParagraphStyle(
        "SmallReport",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7.5,
        leading=10,
        textColor=colors.HexColor("#667085"),
    )

    address_style = ParagraphStyle(
        "Address",
        parent=normal_style,
        fontName="Courier",
        fontSize=7.4,
        leading=10,
        wordWrap="CJK",
    )

    story = []

    # =====================================================
    # HEADER
    # =====================================================

    story.append(
        Paragraph(
            "CRYPTOCURRENCY FORENSIC TRACE REPORT",
            title_style,
        )
    )

    story.append(
        Paragraph(
            "Automated Blockchain Transaction Analysis",
            subtitle_style,
        )
    )

    # =====================================================
    # WALLET UNDER INVESTIGATION
    # =====================================================

    story.append(
        Paragraph(
            "WALLET UNDER INVESTIGATION",
            section_style,
        )
    )

    wallet_address = safe(
        verdict.get("wallet_address")
    )

    wallet_table = Table(
        [
            [
                Paragraph(
                    "<b>Wallet Address</b>",
                    normal_style,
                ),
                Paragraph(
                    wallet_address,
                    address_style,
                ),
            ]
        ],
        colWidths=[42 * mm, 130 * mm],
    )

    wallet_table.setStyle(
        TableStyle(
            [
                (
                    "BACKGROUND",
                    (0, 0),
                    (0, 0),
                    colors.HexColor("#F2F4F7"),
                ),
                (
                    "BOX",
                    (0, 0),
                    (-1, -1),
                    0.6,
                    colors.HexColor("#D9DEE5"),
                ),
                (
                    "INNERGRID",
                    (0, 0),
                    (-1, -1),
                    0.3,
                    colors.HexColor("#E4E7EC"),
                ),
                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "MIDDLE",
                ),
                (
                    "LEFTPADDING",
                    (0, 0),
                    (-1, -1),
                    7,
                ),
                (
                    "RIGHTPADDING",
                    (0, 0),
                    (-1, -1),
                    7,
                ),
                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    7,
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    7,
                ),
            ]
        )
    )

    story.append(wallet_table)

    # =====================================================
    # RISK ASSESSMENT
    # =====================================================

    story.append(
        Paragraph(
            "RISK ASSESSMENT",
            section_style,
        )
    )

    risk_level = safe(
        verdict.get("risk_level")
    )

    risk_score = safe(
        verdict.get("risk_score")
    )

    result = safe(
        verdict.get("result")
    )

    confidence = safe(
        verdict.get("confidence")
    )

    exchange_name = verdict.get("exchange_name")

    if exchange_name:
        identified_entity = exchange_name

    elif result == "mixer_identified":
        identified_entity = "Obstruction service / mixer"

    elif result == "sanctioned":
        identified_entity = "Sanctioned entity"

    elif result == "sanctioned_delisted":
        identified_entity = "Sanctioned / delisted entity"

    elif result == "high_risk_entity":
        identified_entity = "High-risk entity"

    elif result == "inconclusive":
        identified_entity = "No verified destination identified"

    else:
        identified_entity = "N/A"

    risk_table = Table(
        [
            [
                Paragraph(
                    "<b>Risk Level</b>",
                    normal_style,
                ),
                Paragraph(
                    "<b>Risk Score</b>",
                    normal_style,
                ),
                Paragraph(
                    "<b>Detection Verdict</b>",
                    normal_style,
                ),
            ],
            [
                Paragraph(
                    risk_level,
                    bold_style,
                ),
                Paragraph(
                    f"{risk_score} / 100",
                    bold_style,
                ),
                Paragraph(
                    result,
                    bold_style,
                ),
            ],
            [
                Paragraph(
                    "<b>Entity Confidence</b>",
                    normal_style,
                ),
                Paragraph(
                    "<b>Identified Entity</b>",
                    normal_style,
                ),
                "",
            ],
            [
                Paragraph(
                    f"{confidence}%",
                    bold_style,
                ),
                Paragraph(
                    safe(identified_entity),
                    bold_style,
                ),
                "",
            ],
        ],
        colWidths=[
            55 * mm,
            55 * mm,
            62 * mm,
        ],
    )

    risk_table.setStyle(
        TableStyle(
            [
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, 0),
                    colors.HexColor("#F2F4F7"),
                ),
                (
                    "BACKGROUND",
                    (0, 2),
                    (-1, 2),
                    colors.HexColor("#F2F4F7"),
                ),
                (
                    "BOX",
                    (0, 0),
                    (-1, -1),
                    0.6,
                    colors.HexColor("#D9DEE5"),
                ),
                (
                    "INNERGRID",
                    (0, 0),
                    (-1, -1),
                    0.3,
                    colors.HexColor("#E4E7EC"),
                ),
                (
                    "SPAN",
                    (1, 2),
                    (2, 2),
                ),
                (
                    "SPAN",
                    (1, 3),
                    (2, 3),
                ),
                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "MIDDLE",
                ),
                (
                    "LEFTPADDING",
                    (0, 0),
                    (-1, -1),
                    7,
                ),
                (
                    "RIGHTPADDING",
                    (0, 0),
                    (-1, -1),
                    7,
                ),
                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    6,
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    6,
                ),
            ]
        )
    )

    story.append(risk_table)

    # =====================================================
    # TRANSACTION EVIDENCE
    # =====================================================

    story.append(
        Paragraph(
            "TRANSACTION EVIDENCE",
            section_style,
        )
    )

    token = safe(
        verdict.get("token")
    )

    amount = format_amount(
        verdict.get("amount")
    )

    sender = safe(
        verdict.get("from_address")
        or verdict.get("wallet_address")
    )

    recipient = safe(
        verdict.get("to_address")
    )

    contract = safe(
        verdict.get("contract_address")
    )

    risk_transaction = verdict.get(
        "risk_transaction"
    )

    # Optional transaction evidence.
    # These fields will appear automatically if trace.py
    # starts returning them later.

    transaction_hash = (
        verdict.get("transaction_hash")
        or verdict.get("tx_hash")
        or verdict.get("transaction_id")
    )

    block_number = (
        verdict.get("block_number")
        or verdict.get("block")
    )

    transaction_timestamp = (
        verdict.get("transaction_timestamp")
        or verdict.get("timestamp")
    )

    evidence_rows = [
        [
            Paragraph(
                "<b>Asset</b>",
                normal_style,
            ),
            Paragraph(
                token,
                normal_style,
            ),
        ],
        [
            Paragraph(
                "<b>Amount</b>",
                normal_style,
            ),
            Paragraph(
                f"{amount} {token}",
                normal_style,
            ),
        ],
        [
            Paragraph(
                "<b>Sender</b>",
                normal_style,
            ),
            Paragraph(
                sender,
                address_style,
            ),
        ],
        [
            Paragraph(
                "<b>Recipient</b>",
                normal_style,
            ),
            Paragraph(
                recipient,
                address_style,
            ),
        ],
        [
            Paragraph(
                "<b>Token Contract</b>",
                normal_style,
            ),
            Paragraph(
                contract,
                address_style,
            ),
        ],
        [
            Paragraph(
                "<b>Explorer Risk Flag</b>",
                normal_style,
            ),
            Paragraph(
                format_bool(risk_transaction),
                normal_style,
            ),
        ],
    ]

    if transaction_hash:

        evidence_rows.append(
            [
                Paragraph(
                    "<b>Transaction Hash</b>",
                    normal_style,
                ),
                Paragraph(
                    str(transaction_hash),
                    address_style,
                ),
            ]
        )

    if block_number is not None:

        evidence_rows.append(
            [
                Paragraph(
                    "<b>Block Number</b>",
                    normal_style,
                ),
                Paragraph(
                    str(block_number),
                    normal_style,
                ),
            ]
        )

    if transaction_timestamp:

        evidence_rows.append(
            [
                Paragraph(
                    "<b>Transaction Timestamp</b>",
                    normal_style,
                ),
                Paragraph(
                    str(transaction_timestamp),
                    normal_style,
                ),
            ]
        )

    evidence_table = Table(
        evidence_rows,
        colWidths=[
            48 * mm,
            124 * mm,
        ],
    )

    evidence_table.setStyle(
        TableStyle(
            [
                (
                    "BACKGROUND",
                    (0, 0),
                    (0, -1),
                    colors.HexColor("#F8F9FA"),
                ),
                (
                    "BOX",
                    (0, 0),
                    (-1, -1),
                    0.6,
                    colors.HexColor("#D9DEE5"),
                ),
                (
                    "INNERGRID",
                    (0, 0),
                    (-1, -1),
                    0.3,
                    colors.HexColor("#E4E7EC"),
                ),
                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "TOP",
                ),
                (
                    "LEFTPADDING",
                    (0, 0),
                    (-1, -1),
                    7,
                ),
                (
                    "RIGHTPADDING",
                    (0, 0),
                    (-1, -1),
                    7,
                ),
                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    6,
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    6,
                ),
            ]
        )
    )

    story.append(evidence_table)

    # =====================================================
    # RISK INDICATORS
    # =====================================================

    story.append(
        Paragraph(
            "RISK INDICATORS",
            section_style,
        )
    )

    indicators = verdict.get(
        "risk_indicators"
    ) or []

    if indicators:

        indicator_rows = []

        for indicator in indicators:

            indicator_rows.append(
                [
                    Paragraph(
                        "•",
                        bold_style,
                    ),
                    Paragraph(
                        safe(indicator),
                        normal_style,
                    ),
                ]
            )

        indicator_table = Table(
            indicator_rows,
            colWidths=[
                7 * mm,
                165 * mm,
            ],
        )

        indicator_table.setStyle(
            TableStyle(
                [
                    (
                        "VALIGN",
                        (0, 0),
                        (-1, -1),
                        "TOP",
                    ),
                    (
                        "LEFTPADDING",
                        (0, 0),
                        (-1, -1),
                        5,
                    ),
                    (
                        "RIGHTPADDING",
                        (0, 0),
                        (-1, -1),
                        5,
                    ),
                    (
                        "TOPPADDING",
                        (0, 0),
                        (-1, -1),
                        3,
                    ),
                    (
                        "BOTTOMPADDING",
                        (0, 0),
                        (-1, -1),
                        3,
                    ),
                ]
            )
        )

        story.append(indicator_table)

    else:

        story.append(
            Paragraph(
                "No additional behavioral risk indicators detected.",
                normal_style,
            )
        )

    # =====================================================
    # AUTOMATED ASSESSMENT
    # =====================================================

    story.append(
        Paragraph(
            "AUTOMATED ASSESSMENT",
            section_style,
        )
    )

    assessment = safe(
        verdict.get("risk_assessment"),
        "No automated assessment available.",
    )

    assessment_table = Table(
        [
            [
                Paragraph(
                    assessment,
                    normal_style,
                )
            ]
        ],
        colWidths=[
            172 * mm
        ],
    )

    assessment_table.setStyle(
        TableStyle(
            [
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, -1),
                    colors.HexColor("#F8F9FA"),
                ),
                (
                    "BOX",
                    (0, 0),
                    (-1, -1),
                    0.6,
                    colors.HexColor("#D9DEE5"),
                ),
                (
                    "LEFTPADDING",
                    (0, 0),
                    (-1, -1),
                    9,
                ),
                (
                    "RIGHTPADDING",
                    (0, 0),
                    (-1, -1),
                    9,
                ),
                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    8,
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    8,
                ),
            ]
        )
    )

    story.append(assessment_table)

    # =====================================================
    # TRACE PATH
    # =====================================================

    story.append(
        Paragraph(
            "TRACE PATH",
            section_style,
        )
    )

    hop_path = verdict.get(
        "hop_path"
    ) or []

    if hop_path:

        path_rows = []

        for index, address in enumerate(
            hop_path,
            start=1
        ):

            # IMPORTANT:
            # Do not use Unicode arrows here.
            # Some PDF font/rendering combinations can
            # produce unwanted characters such as "fl".

            if index < len(hop_path):
                flow_marker = "TO"
            else:
                flow_marker = ""

            path_rows.append(
                [
                    Paragraph(
                        f"<b>{index}.</b>",
                        normal_style,
                    ),
                    Paragraph(
                        safe(address),
                        address_style,
                    ),
                    Paragraph(
                        flow_marker,
                        small_style,
                    ),
                ]
            )

        path_table = Table(
            path_rows,
            colWidths=[
                10 * mm,
                145 * mm,
                17 * mm,
            ],
        )

        path_table.setStyle(
            TableStyle(
                [
                    (
                        "BOX",
                        (0, 0),
                        (-1, -1),
                        0.6,
                        colors.HexColor("#D9DEE5"),
                    ),
                    (
                        "INNERGRID",
                        (0, 0),
                        (-1, -1),
                        0.3,
                        colors.HexColor("#E4E7EC"),
                    ),
                    (
                        "BACKGROUND",
                        (0, 0),
                        (-1, -1),
                        colors.white,
                    ),
                    (
                        "VALIGN",
                        (0, 0),
                        (-1, -1),
                        "MIDDLE",
                    ),
                    (
                        "ALIGN",
                        (2, 0),
                        (2, -1),
                        "CENTER",
                    ),
                    (
                        "LEFTPADDING",
                        (0, 0),
                        (-1, -1),
                        6,
                    ),
                    (
                        "RIGHTPADDING",
                        (0, 0),
                        (-1, -1),
                        6,
                    ),
                    (
                        "TOPPADDING",
                        (0, 0),
                        (-1, -1),
                        7,
                    ),
                    (
                        "BOTTOMPADDING",
                        (0, 0),
                        (-1, -1),
                        7,
                    ),
                ]
            )
        )

        story.append(path_table)

    else:

        story.append(
            Paragraph(
                "No trace path was established.",
                normal_style,
            )
        )

    calculated_hops = verdict.get(
        "hops"
    )

    if calculated_hops is None:

        calculated_hops = max(
            0,
            len(hop_path) - 1
        )

    story.append(
        Spacer(
            1,
            2 * mm
        )
    )

    story.append(
        Paragraph(
            f"<b>Total Hops:</b> {calculated_hops}",
            normal_style,
        )
    )

    # =====================================================
    # GENERATED TIME
    # =====================================================

    generated_time = (
        datetime.now()
        .astimezone()
        .strftime(
            "%Y-%m-%d %H:%M:%S %Z"
        )
    )

    story.append(
        Spacer(
            1,
            6 * mm
        )
    )

    story.append(
        Paragraph(
            f"<b>Generated:</b> {generated_time}",
            small_style,
        )
    )

    # =====================================================
    # DISCLAIMER
    # =====================================================

    story.append(
        Spacer(
            1,
            5 * mm
        )
    )

    disclaimer = (
        "This report is generated automatically from blockchain "
        "transaction data and publicly available entity metadata. "
        "Risk scores are analytical indicators and should not be "
        "interpreted as definitive proof of criminal activity. "
        "Identification of an exchange, mixer, or other entity "
        "does not by itself establish wrongdoing. Findings should "
        "be independently verified before enforcement or legal action."
    )

    disclaimer_table = Table(
        [
            [
                Paragraph(
                    f"<b>DISCLAIMER</b><br/>{disclaimer}",
                    small_style,
                )
            ]
        ],
        colWidths=[
            172 * mm
        ],
    )

    disclaimer_table.setStyle(
        TableStyle(
            [
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, -1),
                    colors.HexColor("#F8F9FA"),
                ),
                (
                    "BOX",
                    (0, 0),
                    (-1, -1),
                    0.5,
                    colors.HexColor("#D9DEE5"),
                ),
                (
                    "LEFTPADDING",
                    (0, 0),
                    (-1, -1),
                    8,
                ),
                (
                    "RIGHTPADDING",
                    (0, 0),
                    (-1, -1),
                    8,
                ),
                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    8,
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    8,
                ),
            ]
        )
    )

    story.append(
        disclaimer_table
    )

    # =====================================================
    # FOOTER
    # =====================================================

    def add_page_number(
        canvas,
        doc,
    ):

        canvas.saveState()

        canvas.setStrokeColor(
            colors.HexColor("#D9DEE5")
        )

        canvas.line(
            18 * mm,
            12 * mm,
            A4[0] - 18 * mm,
            12 * mm,
        )

        canvas.setFont(
            "Helvetica",
            7,
        )

        canvas.setFillColor(
            colors.HexColor("#667085")
        )

        canvas.drawString(
            18 * mm,
            7.5 * mm,
            "Blockchain Forensic Analysis Report",
        )

        canvas.drawRightString(
            A4[0] - 18 * mm,
            7.5 * mm,
            f"Page {doc.page}",
        )

        canvas.restoreState()

    # =====================================================
    # BUILD PDF
    # =====================================================

    document.build(
        story,
        onFirstPage=add_page_number,
        onLaterPages=add_page_number,
    )

