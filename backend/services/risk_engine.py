"""
The single authoritative risk engine.

Chain-agnostic by construction: it reads only `TraceResult` / `TraceNode` /
`BlockchainTransaction` from `models.schemas` and never imports an adapter or a
provider payload. Adding a chain cannot change how risk is scored, because the
engine never learns which chain it is looking at beyond the `chain` field it
uses for a couple of chain-specific notes.

Three rules that shape every function here:

1. **An indicator without evidence is a bug.** Each `RiskIndicator` carries the
   specific transactions and addresses that triggered it, so a reader can audit
   the score rather than take it on faith.

2. **A signal is not a finding.** Rapid movement, a mixer label, a high fan-out
   — these are observations. The engine reports them at the severity the
   evidence supports and never asserts intent.

3. **Absence of evidence is not evidence of absence.** A wallet with no history
   scores UNKNOWN, not LOW. Scoring "we found nothing" as "this is safe" is the
   single most damaging thing a forensic tool can do.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional

from models.schemas import (
    AttributionSource,
    BlockchainTransaction,
    Chain,
    EntityType,
    RiskAssessment,
    RiskIndicator,
    RiskLevel,
    Severity,
    TraceNode,
    TraceResult,
)

# ============================================================
# WEIGHTS
# ============================================================
#
# A score is a weighted sum, capped at 100. The weights encode how much each
# signal moves an investigation forward, and they are deliberately conservative:
# a low-confidence heuristic must never on its own produce a HIGH rating.

W_SANCTIONED = 60
W_MIXER = 45
W_HIGH_RISK_ENTITY = 40
W_EXCHANGE = 10          # reaching an exchange is normal and is not suspicious
W_FAN_IN = 25            # many distinct senders consolidating: layering shape
W_FAN_OUT = 20           # one sender scattering to many: distribution shape
W_RAPID_HOP = 20
W_HIGH_VALUE = 20
W_SELF_FUNDING = 15
W_NO_ENTITY = 5          # weak on its own; only meaningful combined with others
W_ROUND_TRIP = 25        # value returns to where it came from

#: A hop chain shorter than this many seconds between two different addresses is
#: worth a look. Not a claim of laundering — consolidation and exchange sweeps
#: look identical in the data.
RAPID_HOP_SECONDS = 120

#: Above this, an individual transfer is "large" in context. Absolute thresholds
#: are meaningless across assets, so this is a fraction of the wallet's own
#: observed volume rather than a fixed number of coins.
LARGE_TRANSFER_FRACTION = 0.5


# ============================================================
# INDIVIDUAL SIGNALS
# ============================================================


def _entity_indicators(result: TraceResult) -> List[RiskIndicator]:
    """
    Attribution-based signals.

    The provenance tier is part of the signal: a curated, verified attribution
    and a provider keyword match cannot carry the same weight, and the evidence
    string says which one fired.
    """
    indicators: List[RiskIndicator] = []
    seen_codes: set = set()

    for node in result.nodes:
        entity = node.entity
        if not entity or not entity.name:
            continue

        code = f"entity_{entity.type.value}"
        if code in seen_codes:
            continue
        seen_codes.add(code)

        curated = entity.source_type == AttributionSource.CURATED_VERIFIED

        if entity.type == EntityType.SANCTIONED:
            weight = W_SANCTIONED if curated else W_SANCTIONED // 2
            indicators.append(RiskIndicator(
                code=code,
                name=f"Address attributed to a sanctioned entity ({entity.name})",
                severity=Severity.CRITICAL,
                weight=weight,
                evidence=(
                    f"{node.address} is attributed to \"{entity.name}\" "
                    f"({entity.type.value}) at {result.chain.display_name}. "
                    f"Provenance: {entity.source_type.value}. "
                    f"{'Verified by the BlockTrace curated record.' if curated else 'This is a public provider label, not independent verification.'} "
                    f"Evidence: {'; '.join(entity.evidence) or 'none recorded'}"
                ),
                related_addresses=[node.address],
                source=entity.source_url,
            ))

        elif entity.type == EntityType.MIXER:
            indicators.append(RiskIndicator(
                code=code,
                name=f"Address attributed to a mixer or tumbler ({entity.name})",
                severity=Severity.HIGH,
                weight=W_MIXER if curated else W_MIXER // 2,
                evidence=(
                    f"{node.address} is attributed to \"{entity.name}\" "
                    f"at {result.chain.display_name}. "
                    f"Provenance: {entity.source_type.value}. "
                    f"Evidence: {'; '.join(entity.evidence) or 'none recorded'}"
                ),
                related_addresses=[node.address],
                source=entity.source_url,
            ))

        elif entity.type == EntityType.HIGH_RISK:
            indicators.append(RiskIndicator(
                code=code,
                name=f"Address attributed to a high-risk service ({entity.name})",
                severity=Severity.HIGH,
                weight=W_HIGH_RISK_ENTITY if curated else W_HIGH_RISK_ENTITY // 2,
                evidence=(
                    f"{node.address} is attributed to \"{entity.name}\" "
                    f"at {result.chain.display_name}. "
                    f"Provenance: {entity.source_type.value}. "
                    f"Evidence: {'; '.join(entity.evidence) or 'none recorded'}"
                ),
                related_addresses=[node.address],
                source=entity.source_url,
            ))

        elif entity.type == EntityType.EXCHANGE:
            # Informational. Reaching an exchange is the single most common
            # legitimate endpoint of a trace and must not inflate the score.
            indicators.append(RiskIndicator(
                code=code,
                name=f"Funds reached a known exchange ({entity.name})",
                severity=Severity.INFO,
                weight=W_EXCHANGE,
                evidence=(
                    f"{node.address} is attributed to \"{entity.name}\". "
                    f"Provenance: {entity.source_type.value}. "
                    "An exchange is a normal destination; this is recorded for "
                    "completeness and is not itself suspicious."
                ),
                related_addresses=[node.address],
                source=entity.source_url,
            ))

    return indicators


def _fan_indicators(result: TraceResult) -> List[RiskIndicator]:
    """
    Structural signals: how many distinct parties touch each node.

    High fan-in (many senders into one address) and high fan-out (one sender to
    many recipients) are the shapes that layer and distribute look like in the
    data. They are equally the shapes of a payroll, a distribution campaign, or
    an exchange's internal bookkeeping, so severity is medium, not high.
    """
    indicators: List[RiskIndicator] = []

    for node in result.nodes:
        if node.inbound >= 5 and node.inbound > node.outbound:
            indicators.append(RiskIndicator(
                code="fan_in",
                name=f"High inbound fan-in at {node.address[:12]}…",
                severity=Severity.MEDIUM,
                weight=W_FAN_IN,
                evidence=(
                    f"{node.inbound} distinct inbound value movements reach "
                    f"{node.address}, against {node.outbound} outbound. "
                    "Consolidation from many sources into one address is a "
                    "layering pattern, but is equally consistent with payment "
                    "collection or an exchange's internal transfers."
                ),
                related_addresses=[node.address],
            ))

        if node.outbound >= 5 and node.outbound > node.inbound:
            indicators.append(RiskIndicator(
                code="fan_out",
                name=f"High outbound fan-out at {node.address[:12]}…",
                severity=Severity.MEDIUM,
                weight=W_FAN_OUT,
                evidence=(
                    f"{node.outbound} distinct outbound value movements leave "
                    f"{node.address}, against {node.inbound} inbound. "
                    "Scattering to many recipients is a distribution pattern, "
                    "but is equally consistent with a legitimate payout."
                ),
                related_addresses=[node.address],
            ))

    # Deduplicate: the shape is the finding, not each instance of it.
    return _collapse(indicators, key="code")


def _rapid_hop_indicators(result: TraceResult) -> List[RiskIndicator]:
    """
    Funds moving through addresses in a very short window.

    Built from real timestamps only. If the provider gave none, this returns
    nothing and says so — it does not assume a hop was fast.
    """
    indicators: List[RiskIndicator] = []
    by_address: Dict[str, List[BlockchainTransaction]] = defaultdict(list)
    for tx in result.transactions:
        if tx.timestamp:
            by_address[tx.from_address or ""].append(tx)

    for address, txs in by_address.items():
        timed = sorted([t for t in txs if t.timestamp], key=lambda t: t.timestamp)
        for previous, current in zip(timed, timed[1:]):
            gap = (current.timestamp or 0) - (previous.timestamp or 0)
            if 0 < gap < RAPID_HOP_SECONDS:
                indicators.append(RiskIndicator(
                    code="rapid_hop",
                    name=f"Rapid movement through {address[:12]}…",
                    severity=Severity.MEDIUM,
                    weight=W_RAPID_HOP,
                    evidence=(
                        f"{address} moved value out twice within {gap} seconds "
                        f"(tx {previous.hash[:16]}… then tx {current.hash[:16]}…). "
                        "A short interval is consistent with consolidation or an "
                        "exchange sweep as well as with evasion; the timing alone "
                        "does not distinguish them."
                    ),
                    related_addresses=[address],
                    related_transactions=[previous.hash, current.hash],
                    timestamp=current.timestamp,
                ))
                break  # one signal per address is enough

    return indicators


def _large_transfer_indicators(result: TraceResult) -> List[RiskIndicator]:
    """
    A transfer that is large relative to the wallet's own observed volume.

    Deliberately relative: a fixed BTC or USDT threshold would either fire on
    every retail transaction or never fire on a whale. The comparison is
    against this trace's own activity, and the evidence states the numbers.
    """
    seed_node = next((n for n in result.nodes if n.is_seed), None)
    if not seed_node:
        return []

    involved = [t for t in result.transactions if t.amount and seed_node.address.lower() in {
        (t.from_address or "").lower(), (t.to_address or "").lower(),
    }]
    amounts = [t.amount for t in involved if t.amount]
    if len(amounts) < 2:
        return []

    total = sum(amounts)
    indicators: List[RiskIndicator] = []
    threshold = total * LARGE_TRANSFER_FRACTION

    for tx in involved:
        if tx.amount and tx.amount >= threshold:
            indicators.append(RiskIndicator(
                code="large_transfer",
                name=f"Transfer of {tx.amount:g} {tx.asset} is most of the observed volume",
                severity=Severity.MEDIUM,
                weight=W_HIGH_VALUE,
                evidence=(
                    f"Transaction {tx.hash} moved {tx.amount:g} {tx.asset or 'units'}, "
                    f"which is {tx.amount / total:.0%} of the {total:g} {tx.asset or 'units'} "
                    f"observed across {len(amounts)} transactions involving "
                    f"{seed_node.address}. A concentrated outflow is worth review; "
                    "it is not by itself evidence of wrongdoing."
                ),
                related_addresses=[seed_node.address],
                related_transactions=[tx.hash],
                amount=tx.amount,
                timestamp=tx.timestamp,
            ))
            break  # one is enough to make the point

    return indicators


def _round_trip_indicator(result: TraceResult) -> List[RiskIndicator]:
    """
    Value returning close to where it came from.

    Structurally this is a cycle in the graph. It is called out because a
    cycle is easy to miss in a 3D render and is genuinely important — but the
    engine does not claim why it happened.
    """
    adjacency: Dict[str, set] = defaultdict(set)
    for edge in result.edges:
        if edge.from_address and edge.to_address:
            adjacency[edge.from_address].add(edge.to_address)

    if not adjacency:
        return []

    seed = result.seed
    # BFS from seed looking for an edge that returns to it.
    frontier = {seed}
    seen = {seed}
    while frontier:
        current = frontier.pop()
        for neighbour in adjacency.get(current, set()):
            if neighbour == seed:
                return [RiskIndicator(
                    code="round_trip",
                    name="Value returns to its origin address",
                    severity=Severity.HIGH,
                    weight=W_ROUND_TRIP,
                    evidence=(
                        f"The trace contains a cycle that returns to the seed "
                        f"address {seed}. Funds left and came back within "
                        f"{result.hops} hop(s). A return trip can indicate "
                        "obfuscation of the origin, but also a refund, an "
                        "overpayment correction, or ordinary exchange churn; the "
                        "graph structure alone does not distinguish them."
                    ),
                    related_addresses=[seed],
                )]
            if neighbour not in seen:
                seen.add(neighbour)
                frontier.add(neighbour)
    return []


# ============================================================
# SCORING
# ============================================================


def _collapse(indicators: List[RiskIndicator], key: str = "code") -> List[RiskIndicator]:
    """Keep the highest-weight instance of each signal code."""
    best: Dict[str, RiskIndicator] = {}
    for indicator in indicators:
        existing = best.get(getattr(indicator, key))
        if existing is None or indicator.weight > existing.weight:
            best[getattr(indicator, key)] = indicator
    return list(best.values())


def _level_for(score: int, indicators: List[RiskIndicator]) -> RiskLevel:
    """
    Map a weighted score to a level.

    A score threshold alone is not enough. A curated sanction hit carries
    weight 60, which lands in the same band as a pile of weak structural
    signals — and those are not equivalent findings. One verified attribution
    to a sanctioned entity is a stronger statement than fifty unconfirmed
    shape observations, so a CRITICAL-severity indicator floors the level at
    HIGH however low the arithmetic lands.
    """
    has_critical = any(i.severity == Severity.CRITICAL for i in indicators)

    if score >= 75:
        return RiskLevel.CRITICAL
    if score >= 50 or has_critical:
        return RiskLevel.HIGH
    if score >= 25:
        return RiskLevel.MEDIUM_HIGH
    if score >= 10:
        return RiskLevel.MEDIUM
    if score > 0:
        return RiskLevel.LOW
    return RiskLevel.LOW


def _assessment_text(
    result: TraceResult, indicators: List[RiskIndicator], level: RiskLevel,
) -> str:
    """
    A plain-language reading of the score.

    Describes what was found, never what it means. An automated summary that
    says "this wallet laundered funds" from five structural signals is making a
    claim no evidence in the data supports.
    """
    if not indicators:
        return (
            "No risk signals were observed within the examined hops. This is a "
            "statement about the data that was retrieved, not a clearance of the "
            "address."
        )

    critical = [i for i in indicators if i.severity == Severity.CRITICAL]
    high = [i for i in indicators if i.severity == Severity.HIGH]
    medium = [i for i in indicators if i.severity == Severity.MEDIUM]
    info = [i for i in indicators if i.severity == Severity.INFO]

    parts = [f"Risk level {level.value} from {len(indicators)} signal(s)."]
    if critical:
        parts.append(f"{len(critical)} critical: {'; '.join(i.name for i in critical)}.")
    if high:
        parts.append(f"{len(high)} high: {'; '.join(i.name for i in high)}.")
    if medium:
        parts.append(f"{len(medium)} medium: {'; '.join(i.name for i in medium)}.")
    if info:
        parts.append(f"{len(info)} informational: {'; '.join(i.name for i in info)}.")
    parts.append(
        "These are structural and attribution signals observed in the retrieved "
        "data. They indicate where an investigation should focus; they are not a "
        "determination of intent or wrongdoing."
    )
    return " ".join(parts)


def assess(result: TraceResult) -> RiskAssessment:
    """
    Score one trace. The entry point every caller uses.

    Returns UNKNOWN with a zero score when there is nothing to assess, rather
    than a low score that would read as "this address is clean".
    """
    # No data at all: an honest unknown, not a clean bill of health.
    if not result.transactions and not any(n.entity for n in result.nodes):
        return RiskAssessment(
            risk_score=0,
            risk_level=RiskLevel.UNKNOWN,
            indicators=[],
            assessment=(
                "No transactions or attributions were retrieved, so no risk "
                "assessment was possible. This is not a low-risk result: it "
                "means there was no evidence to assess."
            ),
            score_breakdown={},
        )

    indicators: List[RiskIndicator] = []
    indicators += _entity_indicators(result)
    indicators += _fan_indicators(result)
    indicators += _rapid_hop_indicators(result)
    indicators += _large_transfer_indicators(result)
    indicators += _round_trip_indicator(result)

    indicators = _collapse(indicators)

    raw_score = sum(i.weight for i in indicators)
    score = min(100, raw_score)

    breakdown: Dict[str, int] = {}
    for indicator in indicators:
        breakdown[indicator.code] = breakdown.get(indicator.code, 0) + indicator.weight

    level = _level_for(score, indicators)

    return RiskAssessment(
        risk_score=score,
        risk_level=level,
        indicators=indicators,
        assessment=_assessment_text(result, indicators, level),
        score_breakdown=breakdown,
    )
