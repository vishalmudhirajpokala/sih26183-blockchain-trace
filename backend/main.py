# main.py

import os
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    KeepTogether,
)

from trace import trace_wallet


# ============================================================
# ENVIRONMENT
# ============================================================

load_dotenv()


# ============================================================
# APP
# ============================================================

app = FastAPI(
    title="BlockTrace Investigation API",
    description=(
        "TRON blockchain investigation and fund-flow tracing API."
    ),
    version="1.0.0",
)


# ============================================================
# CORS
# ============================================================
#
# For the SIH prototype we allow cross-origin requests so the
# Vercel frontend can communicate with the Render backend.
#
# No browser credentials/cookies are used by this API.
#

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

REPORTS_DIR = BASE_DIR / "reports"
REPORTS_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

REPORT_FILE = REPORTS_DIR / "trace_report.pdf"


# ============================================================
# STATIC REPORT FILES
# ============================================================

app.mount(
    "/reports",
    StaticFiles(
        directory=str(REPORTS_DIR)
    ),
    name="reports",
)


# ============================================================
# REQUEST MODEL
# ============================================================

class TraceRequest(BaseModel):
    address: str = Field(
        ...,
        min_length=33,
        max_length=34,
        description="TRON wallet address",
    )


# ============================================================
# HELPERS
# ============================================================

def is_valid_tron_address(
    address: str,
) -> bool:
    """
    Basic TRON address validation.

    TRON base58 addresses begin with 'T' and are 34
    characters long.
    """
    if not isinstance(address, str):
        return False

    address = address.strip()

    if len(address) not in {33, 34}:
        return False

    return (
        address.startswith("T")
        and all(
            character.isalnum()
            for character in address
        )
    )


def safe_number(
    value: Any,
    default: Any = None,
):
    return (
        value
        if value is not None
        else default
    )


def determine_result_type(
    trace_result: Dict[str, Any],
) -> str:
    """
    Convert the internal trace classification into the
    frontend/API result vocabulary.
    """

    if not trace_result.get("matched"):
        return "inconclusive"

    tag = trace_result.get(
        "tag",
        {},
    )

    if not isinstance(tag, dict):
        return "identified"

    entity_type = str(
        tag.get(
            "type",
            ""
        )
    ).lower()

    if entity_type == "exchange":
        return "exchange_identified"

    if entity_type == "mixer":
        return "mixer_identified"

    if entity_type == "sanctioned":
        return "sanctioned"

    if entity_type == "high_risk":
        return "high_risk_entity"

    return "identified"


def determine_confidence(
    trace_result: Dict[str, Any],
) -> int:
    """
    Prefer confidence supplied by the entity intelligence.

    For the current prototype, a known exchange destination
    without an explicit confidence value is treated as a
    high-confidence public entity attribution.

    This confidence represents entity attribution strength,
    not criminality probability.
    """

    tag = trace_result.get(
        "tag",
        {},
    )

    if isinstance(tag, dict):
        supplied = tag.get(
            "confidence"
        )

        if supplied is not None:
            try:
                return max(
                    0,
                    min(
                        100,
                        int(supplied),
                    ),
                )
            except (
                ValueError,
                TypeError,
            ):
                pass

        if tag.get("type") == "exchange":
            return 95

        if tag.get("type") in {
            "sanctioned",
            "mixer",
        }:
            return 90

        if tag.get("type") == "high_risk":
            return 80

        return 75

    return 0


def calculate_risk(
    trace_result: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Transparent prototype risk scoring.

    This is a triage indicator, not a probability of guilt.
    """

    score = 0
    indicators = []

    result_type = determine_result_type(
        trace_result
    )

    # --------------------------------------------------------
    # KNOWN DESTINATION
    # --------------------------------------------------------

    if result_type == "exchange_identified":
        score += 10

        indicators.append(
            "Funds reached a known cryptocurrency exchange"
        )

    if result_type == "mixer_identified":
        score += 30

        indicators.append(
            "Trace reached a known mixing-related destination"
        )

    if result_type == "sanctioned":
        score += 45

        indicators.append(
            "Funds reached a sanctioned entity"
        )

    if result_type == "high_risk_entity":
        score += 35

        indicators.append(
            "Funds reached a known high-risk entity"
        )

    # --------------------------------------------------------
    # FAN-IN
    # --------------------------------------------------------

    if trace_result.get(
        "fan_in",
        False,
    ):
        score += 8

        indicators.append(
            "Funds from multiple wallets were consolidated"
        )

    # --------------------------------------------------------
    # FAN-OUT
    # --------------------------------------------------------

    if trace_result.get(
        "fan_out",
        False,
    ):
        score += 5

        indicators.append(
            "Funds were dispersed across multiple wallets"
        )

    # --------------------------------------------------------
    # RAPID MOVEMENT
    # --------------------------------------------------------

    if trace_result.get(
        "rapid_hops",
        False,
    ):
        score += 7

        indicators.append(
            "Rapid successive fund movement was observed"
        )

    # --------------------------------------------------------
    # LARGE TRANSFER
    # --------------------------------------------------------

    amount = trace_result.get(
        "amount"
    )

    try:
        if amount is not None:
            numeric_amount = float(amount)

            # Prototype-level generic threshold.
            # It is deliberately not presented as a
            # chain-wide financial crime threshold.
            if numeric_amount >= 1_000_000:
                score += 7

                indicators.append(
                    "Unusually large token transfer detected"
                )

    except (
        ValueError,
        TypeError,
    ):
        pass

    score = min(
        100,
        max(
            0,
            score,
        ),
    )

    # --------------------------------------------------------
    # LEVEL
    # --------------------------------------------------------

    if score >= 70:
        level = "HIGH"
    elif score >= 40:
        level = "MEDIUM-HIGH"
    elif score >= 20:
        level = "MEDIUM"
    else:
        level = "LOW"

    if not indicators:
        indicators.append(
            "No significant high-risk indicators were detected"
        )

    assessment = (
        "Some risk indicators were detected. "
        "Additional transaction analysis is recommended."
        if score >= 20
        else
        "No significant high-risk indicators were detected "
        "in the analyzed transaction path."
    )

    return {
        "risk_score": score,
        "risk_level": level,
        "risk_indicators": indicators,
        "risk_assessment": assessment,
    }


def format_amount(
    amount: Any,
) -> Optional[str]:
    if amount is None:
        return None

    try:
        return f"{float(amount):,.3f}".rstrip(
            "0"
        ).rstrip(".")
    except (
        ValueError,
        TypeError,
    ):
        return str(amount)


# ============================================================
# PDF REPORT
# ============================================================

def generate_report(
    result: Dict[str, Any],
) -> Path:
    """
    Generate a structured investigation PDF.
    """

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        alignment=TA_LEFT,
        textColor=colors.HexColor(
            "#163A5F"
        ),
        spaceAfter=6 * mm,
    )

    section_style = ParagraphStyle(
        "Section",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=13,
        textColor=colors.HexColor(
            "#536577"
        ),
        spaceBefore=4 * mm,
        spaceAfter=2 * mm,
    )

    body_style = ParagraphStyle(
        "Body",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=9,
        leading=13,
        textColor=colors.HexColor(
            "#354656"
        ),
    )

    small_style = ParagraphStyle(
        "Small",
        parent=body_style,
        fontSize=7.5,
        leading=10,
        textColor=colors.HexColor(
            "#6C7B89"
        ),
    )

    document = SimpleDocTemplate(
        str(REPORT_FILE),
        pagesize=A4,
        rightMargin=15 * mm,
        leftMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title="BlockTrace Investigation Report",
        author="BlockTrace",
    )

    story = []

    # --------------------------------------------------------
    # TITLE
    # --------------------------------------------------------

    story.append(
        Paragraph(
            "BLOCKTRACE",
            title_style,
        )
    )

    story.append(
        Paragraph(
            "Cryptocurrency Forensic Trace Report",
            section_style,
        )
    )

    story.append(
        Spacer(
            1,
            2 * mm,
        )
    )

    story.append(
        Paragraph(
            "Automated blockchain transaction analysis "
            "for investigative triage.",
            body_style,
        )
    )

    story.append(
        Spacer(
            1,
            5 * mm,
        )
    )

    # --------------------------------------------------------
    # CORE RESULT
    # --------------------------------------------------------

    story.append(
        Paragraph(
            "INVESTIGATION RESULT",
            section_style,
        )
    )

    result_type = result.get(
        "result",
        "inconclusive",
    )

    result_heading = {
        "exchange_identified": "Exchange Identified",
        "mixer_identified": "Trace Halted — Mixer Detected",
        "sanctioned": "Sanctioned Entity Identified",
        "high_risk_entity": "High-Risk Entity Identified",
        "identified": "Entity Identified",
        "inconclusive": "Trace Inconclusive",
    }.get(
        result_type,
        "Trace Inconclusive",
    )

    story.append(
        Paragraph(
            f"<b>{result_heading}</b>",
            body_style,
        )
    )

    if result.get(
        "exchange_name"
    ):
        story.append(
            Paragraph(
                (
                    "Known destination: "
                    f"<b>{result['exchange_name']}</b>"
                ),
                body_style,
            )
        )

    # --------------------------------------------------------
    # WALLET
    # --------------------------------------------------------

    story.append(
        Paragraph(
            "WALLET UNDER INVESTIGATION",
            section_style,
        )
    )

    wallet_data = [
        [
            "Wallet Address",
            result.get(
                "wallet_address",
                "—",
            ),
        ],
        [
            "Result",
            result.get(
                "result",
                "—",
            ),
        ],
        [
            "Confidence",
            f"{result.get('confidence', 0)}%",
        ],
        [
            "Hops",
            str(
                result.get(
                    "hops",
                    0,
                )
            ),
        ],
        [
            "Network",
            "TRON",
        ],
    ]

    wallet_table = Table(
        wallet_data,
        colWidths=[
            42 * mm,
            125 * mm,
        ],
    )

    wallet_table.setStyle(
        TableStyle(
            [
                (
                    "BACKGROUND",
                    (0, 0),
                    (0, -1),
                    colors.HexColor(
                        "#F1F4F7"
                    ),
                ),
                (
                    "TEXTCOLOR",
                    (0, 0),
                    (-1, -1),
                    colors.HexColor(
                        "#354656"
                    ),
                ),
                (
                    "FONTNAME",
                    (0, 0),
                    (0, -1),
                    "Helvetica-Bold",
                ),
                (
                    "FONTNAME",
                    (1, 0),
                    (1, -1),
                    "Helvetica",
                ),
                (
                    "FONTSIZE",
                    (0, 0),
                    (-1, -1),
                    8,
                ),
                (
                    "GRID",
                    (0, 0),
                    (-1, -1),
                    0.4,
                    colors.HexColor(
                        "#D8E0E7"
                    ),
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

    story.append(
        wallet_table
    )

    # --------------------------------------------------------
    # FUND FLOW
    # --------------------------------------------------------

    story.append(
        Paragraph(
            "TRACE PATH",
            section_style,
        )
    )

    path = result.get(
        "hop_path",
        [],
    )

    path_data = []

    for index, address in enumerate(
        path
    ):
        if index == 0:
            label = "SOURCE"
        elif index == len(path) - 1:
            label = "DESTINATION"
        else:
            label = f"HOP {index}"

        path_data.append(
            [
                label,
                address,
            ]
        )

    if not path_data:
        path_data.append(
            [
                "PATH",
                "No trace path available",
            ]
        )

    path_table = Table(
        path_data,
        colWidths=[
            35 * mm,
            132 * mm,
        ],
    )

    path_table.setStyle(
        TableStyle(
            [
                (
                    "BACKGROUND",
                    (0, 0),
                    (0, -1),
                    colors.HexColor(
                        "#F7F9FB"
                    ),
                ),
                (
                    "FONTNAME",
                    (0, 0),
                    (0, -1),
                    "Helvetica-Bold",
                ),
                (
                    "FONTNAME",
                    (1, 0),
                    (1, -1),
                    "Courier",
                ),
                (
                    "FONTSIZE",
                    (0, 0),
                    (-1, -1),
                    7.5,
                ),
                (
                    "GRID",
                    (0, 0),
                    (-1, -1),
                    0.4,
                    colors.HexColor(
                        "#D8E0E7"
                    ),
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
                    5,
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    5,
                ),
            ]
        )
    )

    story.append(
        path_table
    )

    # --------------------------------------------------------
    # TRANSACTION EVIDENCE
    # --------------------------------------------------------

    story.append(
        Paragraph(
            "TRANSACTION EVIDENCE",
            section_style,
        )
    )

    transaction_data = [
        [
            "Asset",
            result.get(
                "token",
                "—",
            ) or "—",
        ],
        [
            "Amount",
            format_amount(
                result.get(
                    "amount"
                )
            ) or "—",
        ],
        [
            "Source",
            result.get(
                "from_address"
            )
            or result.get(
                "wallet_address"
            )
            or "—",
        ],
        [
            "Destination",
            result.get(
                "to_address"
            )
            or "—",
        ],
        [
            "Contract",
            result.get(
                "contract_address"
            )
            or "—",
        ],
        [
            "Transaction Hash",
            result.get(
                "transaction_hash"
            )
            or result.get(
                "transaction_id"
            )
            or "—",
        ],
        [
            "Block Number",
            str(
                result.get(
                    "block_number"
                )
                or "—"
            ),
        ],
    ]

    transaction_table = Table(
        transaction_data,
        colWidths=[
            42 * mm,
            125 * mm,
        ],
    )

    transaction_table.setStyle(
        TableStyle(
            [
                (
                    "BACKGROUND",
                    (0, 0),
                    (0, -1),
                    colors.HexColor(
                        "#F1F4F7"
                    ),
                ),
                (
                    "FONTNAME",
                    (0, 0),
                    (0, -1),
                    "Helvetica-Bold",
                ),
                (
                    "FONTNAME",
                    (1, 0),
                    (1, -1),
                    "Courier",
                ),
                (
                    "FONTSIZE",
                    (0, 0),
                    (-1, -1),
                    7.5,
                ),
                (
                    "GRID",
                    (0, 0),
                    (-1, -1),
                    0.4,
                    colors.HexColor(
                        "#D8E0E7"
                    ),
                ),
                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "TOP",
                ),
                (
                    "WORDWRAP",
                    (0, 0),
                    (-1, -1),
                    True,
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
                    5,
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    5,
                ),
            ]
        )
    )

    story.append(
        transaction_table
    )

    # --------------------------------------------------------
    # ANALYTICAL SIGNALS
    # --------------------------------------------------------

    story.append(
        Paragraph(
            "ANALYTICAL SIGNALS",
            section_style,
        )
    )

    risk_data = [
        [
            "Risk Score",
            f"{result.get('risk_score', 0)} / 100",
        ],
        [
            "Risk Level",
            result.get(
                "risk_level",
                "LOW",
            ),
        ],
        [
            "Fan-in",
            "Detected"
            if result.get(
                "fan_in",
                False,
            )
            else "Not detected",
        ],
        [
            "Fan-out",
            "Detected"
            if result.get(
                "fan_out",
                False,
            )
            else "Not detected",
        ],
        [
            "Rapid Hops",
            "Detected"
            if result.get(
                "rapid_hops",
                False,
            )
            else "Not detected",
        ],
    ]

    risk_table = Table(
        risk_data,
        colWidths=[
            42 * mm,
            125 * mm,
        ],
    )

    risk_table.setStyle(
        TableStyle(
            [
                (
                    "BACKGROUND",
                    (0, 0),
                    (0, -1),
                    colors.HexColor(
                        "#F7F9FB"
                    ),
                ),
                (
                    "FONTNAME",
                    (0, 0),
                    (0, -1),
                    "Helvetica-Bold",
                ),
                (
                    "FONTSIZE",
                    (0, 0),
                    (-1, -1),
                    8,
                ),
                (
                    "GRID",
                    (0, 0),
                    (-1, -1),
                    0.4,
                    colors.HexColor(
                        "#D8E0E7"
                    ),
                ),
                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "TOP",
                ),
            ]
        )
    )

    story.append(
        risk_table
    )

    indicators = result.get(
        "risk_indicators",
        [],
    )

    if indicators:
        story.append(
            Spacer(
                1,
                2 * mm,
            )
        )

        story.append(
            Paragraph(
                "<b>Indicators</b>",
                body_style,
            )
        )

        for indicator in indicators:
            story.append(
                Paragraph(
                    f"• {indicator}",
                    body_style,
                )
            )

    # --------------------------------------------------------
    # ASSESSMENT
    # --------------------------------------------------------

    assessment = result.get(
        "risk_assessment"
    )

    if assessment:
        story.append(
            Paragraph(
                "AUTOMATED ASSESSMENT",
                section_style,
            )
        )

        story.append(
            Paragraph(
                assessment,
                body_style,
            )
        )

    # --------------------------------------------------------
    # DISCLAIMER
    # --------------------------------------------------------

    story.append(
        Spacer(
            1,
            7 * mm,
        )
    )

    story.append(
        Paragraph(
            (
                "<b>Forensic limitation:</b> Automated blockchain "
                "analysis is an investigative aid. Entity "
                "identification, confidence and risk indicators "
                "do not independently establish criminal "
                "activity, intent, identity or guilt."
            ),
            small_style,
        )
    )

    document.build(
        story
    )

    return REPORT_FILE


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/")
def root():
    return {
        "service": "BlockTrace Investigation API",
        "status": "online",
        "network": "TRON",
        "docs": "/docs",
    }


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "network": "TRON",
    }


# ============================================================
# TRACE ENDPOINT
# ============================================================

@app.post("/trace")
def trace(
    request: TraceRequest,
):
    address = request.address.strip()

    if not is_valid_tron_address(
        address
    ):
        raise HTTPException(
            status_code=400,
            detail="Invalid TRON wallet address.",
        )

    try:
        trace_result = trace_wallet(
            address,
            depth=0,
            max_depth=5,
        )

    except Exception as exc:
        print(
            "TRACE ERROR:",
            repr(exc),
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Blockchain tracing failed."
            ),
        ) from exc

    if not isinstance(
        trace_result,
        dict,
    ):
        raise HTTPException(
            status_code=500,
            detail=(
                "Tracer returned an invalid response."
            ),
        )

    # ========================================================
    # RESULT CLASSIFICATION
    # ========================================================

    result_type = determine_result_type(
        trace_result
    )

    confidence = determine_confidence(
        trace_result
    )

    # ========================================================
    # BASE RESPONSE
    # ========================================================

    response: Dict[str, Any] = {
        "wallet_address": address,
        "result": result_type,
        "exchange_name": None,
        "confidence": confidence,
        "hop_path": trace_result.get(
            "path",
            [address],
        ),
        "hops": trace_result.get(
            "hops",
            0,
        ),
        "token": trace_result.get(
            "token"
        ),
        "amount": trace_result.get(
            "amount"
        ),
        "raw_amount": trace_result.get(
            "raw_amount"
        ),
        "decimals": trace_result.get(
            "decimals"
        ),
        "contract_address": trace_result.get(
            "contract_address"
        ),
        "from_address": trace_result.get(
            "from_address"
        ),
        "to_address": trace_result.get(
            "to_address"
        ),
        "transaction_hash": trace_result.get(
            "transaction_hash"
        ),
        "transaction_id": trace_result.get(
            "transaction_id"
        ),
        "block_number": trace_result.get(
            "block_number"
        ),
        "transaction_timestamp": trace_result.get(
            "transaction_timestamp"
        ),
        "risk_transaction": trace_result.get(
            "risk_transaction",
            False,
        ),
        "rapid_hops": trace_result.get(
            "rapid_hops",
            False,
        ),
        "fan_out": trace_result.get(
            "fan_out",
            False,
        ),
        "fan_in": trace_result.get(
            "fan_in",
            False,
        ),
        "high_risk_entity": trace_result.get(
            "high_risk_entity",
            False,
        ),
        "trace_reason": None,
        "trace_detail": None,
    }

    # ========================================================
    # ENTITY NAME
    # ========================================================

    tag = trace_result.get(
        "tag",
        {},
    )

    if isinstance(
        tag,
        dict,
    ):
        if tag.get("type") == "exchange":
            response["exchange_name"] = tag.get(
                "name"
            )

        elif tag.get("name"):
            response["exchange_name"] = tag.get(
                "name"
            )

    # ========================================================
    # INCONCLUSIVE / ERROR INFORMATION
    # ========================================================

    if not trace_result.get(
        "matched",
        False,
    ):
        reason = trace_result.get(
            "reason"
        )

        response["trace_reason"] = reason

        response["trace_detail"] = trace_result.get(
            "detail"
        )

    # ========================================================
    # RISK
    # ========================================================

    risk = calculate_risk(
        response
    )

    response.update(
        risk
    )

    # ========================================================
    # REPORT
    # ========================================================

    try:
        report_path = generate_report(
            response
        )

        response["report"] = (
            f"reports/{report_path.name}"
        )

    except Exception as exc:
        print(
            "REPORT ERROR:",
            repr(exc),
        )

        response["report"] = None

    return response
