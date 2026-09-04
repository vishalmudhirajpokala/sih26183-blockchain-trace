# risk_engine.py


def calculate_risk(verdict):
    """
    Multi-signal cryptocurrency transaction risk engine.

    Risk score:
        0-24   = LOW
        25-49  = MEDIUM
        50-74  = HIGH
        75-100 = CRITICAL

    The score is an analytical indicator.
    It does NOT establish criminal activity.
    """

    score = 0
    indicators = []

    result = verdict.get("result", "")
    hops = verdict.get("hops", 0)

    risk_transaction = verdict.get(
        "risk_transaction",
        False
    )

    amount = verdict.get("amount")

    # Future behavioral signals.
    # These default to safe values so the current
    # system continues working unchanged.

    rapid_hops = verdict.get(
        "rapid_hops",
        False
    )

    fan_out = verdict.get(
        "fan_out",
        False
    )

    fan_in = verdict.get(
        "fan_in",
        False
    )

    high_risk_entity = verdict.get(
        "high_risk_entity",
        False
    )

    # =========================================================
    # 1. ENTITY RISK
    # =========================================================

    if result == "sanctioned":

        score += 90

        indicators.append(
            "Interaction with a sanctioned entity"
        )

    elif result == "sanctioned_delisted":

        score += 70

        indicators.append(
            "Interaction with a previously sanctioned entity"
        )

    elif result == "mixer_identified":

        score += 80

        indicators.append(
            "Interaction with a cryptocurrency mixer"
        )

    elif result == "exchange_identified":

        # Exchange interaction alone is NOT suspicious.

        score += 5

        indicators.append(
            "Funds reached a known cryptocurrency exchange"
        )

    # =========================================================
    # 2. HIGH-RISK ENTITY
    # =========================================================

    if high_risk_entity is True:

        score += 30

        indicators.append(
            "Interaction with a high-risk blockchain entity"
        )

    # =========================================================
    # 3. BLOCKCHAIN RISK FLAG
    # =========================================================

    if risk_transaction is True:

        score += 25

        indicators.append(
            "Blockchain explorer marked the transaction as risky"
        )

    # =========================================================
    # 4. MULTI-HOP ANALYSIS
    # =========================================================

    if hops >= 5:

        score += 20

        indicators.append(
            "Extended multi-hop fund movement"
        )

    elif hops >= 3:

        score += 12

        indicators.append(
            "Multiple wallet hops detected"
        )

    elif hops >= 2:

        score += 5

        indicators.append(
            "Funds moved through multiple wallets"
        )

    # =========================================================
    # 5. RAPID HOP ANALYSIS
    # =========================================================

    if rapid_hops is True:

        score += 15

        indicators.append(
            "Rapid movement of funds across multiple wallets"
        )

    # =========================================================
    # 6. FAN-OUT ANALYSIS
    # =========================================================

    if fan_out is True:

        score += 12

        indicators.append(
            "Funds were split across multiple destination wallets"
        )

    # =========================================================
    # 7. FAN-IN ANALYSIS
    # =========================================================

    if fan_in is True:

        score += 12

        indicators.append(
            "Funds from multiple wallets were consolidated"
        )

    # =========================================================
    # 8. TRANSACTION AMOUNT ANALYSIS
    # =========================================================

    if amount is not None:

        try:

            numeric_amount = float(amount)

            # Extremely large token transfer.
            # This is only an anomaly signal,
            # not proof of criminal activity.

            if numeric_amount >= 1_000_000_000:

                score += 8

                indicators.append(
                    "Unusually large token transfer detected"
                )

            elif numeric_amount >= 100_000_000:

                score += 5

                indicators.append(
                    "Large token transfer detected"
                )

        except (ValueError, TypeError):

            pass

    # =========================================================
    # 9. UNKNOWN / INCONCLUSIVE TRACE
    # =========================================================

    if result == "inconclusive":

        indicators.append(
            "No known high-risk entity was identified"
        )

    # =========================================================
    # 10. COMBINED BEHAVIOR BONUS
    # =========================================================

    suspicious_signals = 0

    if risk_transaction is True:
        suspicious_signals += 1

    if rapid_hops is True:
        suspicious_signals += 1

    if fan_out is True:
        suspicious_signals += 1

    if fan_in is True:
        suspicious_signals += 1

    if high_risk_entity is True:
        suspicious_signals += 1

    if result in [
        "sanctioned",
        "sanctioned_delisted",
        "mixer_identified"
    ]:
        suspicious_signals += 1

    if suspicious_signals >= 3:

        score += 10

        indicators.append(
            "Multiple independent suspicious behavior signals detected"
        )

    # =========================================================
    # 11. CAP SCORE
    # =========================================================

    score = min(score, 100)

    # =========================================================
    # 12. DETERMINE RISK LEVEL
    # =========================================================

    if score >= 75:

        risk_level = "CRITICAL"

    elif score >= 50:

        risk_level = "HIGH"

    elif score >= 25:

        risk_level = "MEDIUM"

    else:

        risk_level = "LOW"

    # =========================================================
    # 13. ASSESSMENT
    # =========================================================

    if risk_level == "CRITICAL":

        assessment = (
            "Multiple high-risk indicators were detected. "
            "The transaction path presents a critical risk "
            "and requires further investigation."
        )

    elif risk_level == "HIGH":

        assessment = (
            "Significant risk indicators were detected. "
            "The transaction path should be investigated "
            "further."
        )

    elif risk_level == "MEDIUM":

        assessment = (
            "Some risk indicators were detected. "
            "Additional transaction analysis is recommended."
        )

    else:

        assessment = (
            "No significant high-risk indicators were detected "
            "in the analyzed transaction path."
        )

    # =========================================================
    # 14. RETURN RISK RESULT
    # =========================================================

    return {
        "risk_score": score,
        "risk_level": risk_level,
        "risk_indicators": indicators,
        "risk_assessment": assessment
    }