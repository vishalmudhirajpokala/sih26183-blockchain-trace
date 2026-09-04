from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pathlib import Path
from fastapi.staticfiles import StaticFiles

from trace import trace_wallet
from report import generate_report
from risk_engine import calculate_risk


app = FastAPI()


# ============================================================
# REPORT DIRECTORY
# ============================================================

reports_dir = Path("reports")
reports_dir.mkdir(exist_ok=True)

app.mount(
    "/reports",
    StaticFiles(directory="reports"),
    name="reports"
)


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# REQUEST MODEL
# ============================================================

class TraceRequest(BaseModel):
    address: str


# ============================================================
# TRACE ENDPOINT
# ============================================================

@app.post("/trace")
async def trace(request: TraceRequest):

    wallet_address = request.address.strip()

    # --------------------------------------------------------
    # RUN BLOCKCHAIN TRACE
    # --------------------------------------------------------

    trace_result = trace_wallet(
        wallet_address
    )

    # --------------------------------------------------------
    # BEHAVIORAL FLAGS
    # --------------------------------------------------------

    rapid_hops = trace_result.get(
        "rapid_hops",
        False
    )

    fan_out = trace_result.get(
        "fan_out",
        False
    )

    fan_in = trace_result.get(
        "fan_in",
        False
    )

    high_risk_entity = trace_result.get(
        "high_risk_entity",
        False
    )

    # --------------------------------------------------------
    # DETERMINE VERDICT
    # --------------------------------------------------------

    if trace_result.get("matched"):

        tag = trace_result.get(
            "tag",
            {}
        )

        tag_type = tag.get(
            "type"
        )

        tag_name = tag.get(
            "name"
        )

        if tag_type == "exchange":

            result = "exchange_identified"

            exchange_name = tag_name

            confidence = tag.get(
                "confidence",
                95
            )

        elif tag_type == "mixer":

            result = "mixer_identified"

            exchange_name = None

            confidence = tag.get(
                "confidence",
                95
            )

        elif tag_type == "sanctioned":

            result = "sanctioned"

            exchange_name = None

            confidence = tag.get(
                "confidence",
                98
            )

        elif tag_type == "sanctioned_delisted":

            result = "sanctioned_delisted"

            exchange_name = None

            confidence = tag.get(
                "confidence",
                95
            )

        elif tag_type == "high_risk":

            result = "high_risk_entity"

            exchange_name = None

            confidence = tag.get(
                "confidence",
                90
            )

        else:

            result = "identified"

            exchange_name = None

            confidence = tag.get(
                "confidence",
                90
            )

        hop_path = trace_result.get(
            "path",
            []
        )

    else:

        result = "inconclusive"

        exchange_name = None

        confidence = 0

        hop_path = [
            wallet_address
        ]

    # --------------------------------------------------------
    # TRANSACTION DATA
    # --------------------------------------------------------

    token = trace_result.get(
        "token"
    )

    amount = trace_result.get(
        "amount"
    )

    raw_amount = trace_result.get(
        "raw_amount"
    )

    decimals = trace_result.get(
        "decimals"
    )

    contract_address = trace_result.get(
        "contract_address"
    )

    from_address = trace_result.get(
        "from_address"
    )

    to_address = trace_result.get(
        "to_address"
    )

    risk_transaction = trace_result.get(
        "risk_transaction",
        False
    )

    # --------------------------------------------------------
    # FORENSIC TRANSACTION EVIDENCE
    # --------------------------------------------------------

    transaction_hash = trace_result.get(
        "transaction_hash"
    )

    transaction_id = trace_result.get(
        "transaction_id"
    )

    block_number = trace_result.get(
        "block_number"
    )

    transaction_timestamp = trace_result.get(
        "transaction_timestamp"
    )

    # --------------------------------------------------------
    # HOP COUNT
    # --------------------------------------------------------

    calculated_hops = trace_result.get(
        "hops"
    )

    if calculated_hops is None:

        calculated_hops = max(
            0,
            len(hop_path) - 1
        )

    # --------------------------------------------------------
    # RISK ENGINE
    # --------------------------------------------------------

    risk_data = calculate_risk({

        "result": result,

        "hops": calculated_hops,

        "risk_transaction": (
            risk_transaction
        ),

        "amount": amount,

        "token": token,

        "rapid_hops": rapid_hops,

        "fan_out": fan_out,

        "fan_in": fan_in,

        "high_risk_entity": (
            high_risk_entity
        )
    })

    # --------------------------------------------------------
    # FINAL VERDICT OBJECT
    # --------------------------------------------------------

    verdict = {

        "wallet_address": wallet_address,

        "result": result,

        "exchange_name": exchange_name,

        "confidence": confidence,

        "hop_path": hop_path,

        "hops": calculated_hops,

        # -------------------------------
        # ASSET INFORMATION
        # -------------------------------

        "token": token,

        "amount": amount,

        "raw_amount": raw_amount,

        "decimals": decimals,

        "contract_address": (
            contract_address
        ),

        # -------------------------------
        # SOURCE / DESTINATION
        # -------------------------------

        "from_address": from_address,

        "to_address": to_address,

        # -------------------------------
        # TRANSACTION EVIDENCE
        # -------------------------------

        "transaction_hash": (
            transaction_hash
        ),

        "transaction_id": (
            transaction_id
        ),

        "block_number": (
            block_number
        ),

        "transaction_timestamp": (
            transaction_timestamp
        ),

        # -------------------------------
        # RISK
        # -------------------------------

        "risk_transaction": (
            risk_transaction
        ),

        "rapid_hops": rapid_hops,

        "fan_out": fan_out,

        "fan_in": fan_in,

        "high_risk_entity": (
            high_risk_entity
        ),

        "risk_score": (
            risk_data["risk_score"]
        ),

        "risk_level": (
            risk_data["risk_level"]
        ),

        "risk_indicators": (
            risk_data["risk_indicators"]
        ),

        "risk_assessment": (
            risk_data["risk_assessment"]
        )
    }

    # --------------------------------------------------------
    # GENERATE PDF
    # --------------------------------------------------------

    report_path = (
        reports_dir /
        "trace_report.pdf"
    )

    generate_report(
        verdict,
        str(report_path)
    )

    # --------------------------------------------------------
    # API RESPONSE
    # --------------------------------------------------------

    return {

        **verdict,

        "trace_reason": trace_result.get(
            "reason"
        ),

        "trace_detail": trace_result.get(
            "detail"
        ),

        "report": str(
            report_path
        )
    }