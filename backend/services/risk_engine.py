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
from typing import Dict, List, Optional, Set

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


def _fan_indicators(
    result: TraceResult, exclude: Optional[Set[str]] = None,
) -> List[RiskIndicator]:
    """
    Structural signals: how many distinct parties touch each node.

    High fan-in (many senders into one address) and high fan-out (one sender to
    many recipients) are the shapes that layer and distribute look like in the
    data. They are equally the shapes of a payroll, a distribution campaign, or
    an exchange's internal bookkeeping, so severity is medium, not high.

    `exclude` holds lowercased addresses that are contracts. A contract's
    fan-in is a property of the instrument, not behaviour by an actor, so it is
    not a signal about anything.
    """
    skip = exclude or set()
    indicators: List[RiskIndicator] = []

    for node in result.nodes:
        if (node.address or "").lower() in skip:
            continue
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


def _rapid_hop_indicators(
    result: TraceResult, exclude: Optional[Set[str]] = None,
) -> List[RiskIndicator]:
    """
    Funds moving through addresses in a very short window.

    Built from real timestamps only. If the provider gave none, this returns
    nothing and says so — it does not assume a hop was fast.

    `exclude` holds lowercased contract addresses. A token contract forwarding
    value twice in the same block is the contract working, not someone evading
    a time window.
    """
    skip = exclude or set()
    indicators: List[RiskIndicator] = []
    by_address: Dict[str, List[BlockchainTransaction]] = defaultdict(list)
    for tx in result.transactions:
        if tx.timestamp:
            by_address[tx.from_address or ""].append(tx)

    for address, txs in by_address.items():
        if (address or "").lower() in skip:
            continue
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


def _attribute_signals(
    result: TraceResult, indicators: List[RiskIndicator],
) -> Dict[str, Any]:
    """
    Record which address each signal was raised against.

    The risk score is a single number attached to the traced address, but the
    signals summed into it are not all about the traced address. A fan-in signal
    fires against whichever node consolidated value, a rapid-movement signal
    against whichever address moved twice inside the window, and in a real trace
    those are usually counterparties. A reader shown "CRITICAL 85" has no way to
    know that three of the four signals describe wallets the subject traded
    with, rather than the subject itself.

    This does not change the score -- the weighting is untouched and the total is
    still what it was. It records the provenance of each signal so the number can
    be read for what it is. That distinction has to come from the data rather
    than from a label, so an indicator counts as being about the subject only
    when the subject is actually among the addresses it names.
    """
    seed = (result.seed or "").lower()
    signals: List[Dict[str, Any]] = []
    subject = counterparty = 0

    for indicator in indicators:
        addresses = list(indicator.related_addresses or [])
        names = {a.lower() for a in addresses if a}
        # An indicator that names no address cannot be attributed either way.
        # It is counted as unattributed rather than guessed onto the subject,
        # because attributing it wrongly would misstate which claim it supports.
        if not names:
            is_subject = None
        else:
            is_subject = seed in names
        if is_subject is True:
            subject += 1
        elif is_subject is False:
            counterparty += 1
        signals.append({
            "code": indicator.code,
            "name": indicator.name,
            "weight": indicator.weight,
            "is_subject": is_subject,
            "addresses": addresses,
        })

    return {
        "subject": subject,
        "counterparty": counterparty,
        "unattributed": sum(1 for s in signals if s["is_subject"] is None),
        "total": len(signals),
        "subject_score": sum(s["weight"] for s in signals if s["is_subject"] is True),
        "counterparty_score": sum(
            s["weight"] for s in signals if s["is_subject"] is False
        ),
        "signals": signals,
    }


def _attribution_sentence(attribution: Dict[str, Any]) -> str:
    """
    One sentence saying how much of the score is about the subject.

    Returned as a separate clause rather than folded into the assessment
    prose so the report can place it next to the signals table, where a reader
    looking at "which address is this about" will find it.
    """
    total = attribution.get("total") or 0
    subject = attribution.get("subject") or 0
    counterparty = attribution.get("counterparty") or 0

    if not total:
        return "No signals were raised, so there is nothing to attribute."

    parts = [
        f"{counterparty} of {total} signal"
        f"{'s' if total != 1 else ''} "
        f"{'were' if counterparty != 1 else 'was'} raised against counterparty "
        f"addresses rather than the traced subject"
    ]
    if subject:
        parts.append(f"{subject} concerned the subject address itself")
    if attribution.get("unattributed"):
        parts.append(
            f"{attribution['unattributed']} could not be attributed to any address"
        )
    sentence = "; ".join(parts) + "."

    if counterparty and subject == 0:
        sentence += (
            " The score is an aggregate over the whole traced graph, so a high "
            "figure here can be driven entirely by addresses the subject dealt "
            "with. It is not a finding about the subject address itself."
        )
    elif counterparty:
        sentence += (
            " The score is an aggregate over the whole traced graph, so the "
            "subject's own contribution is the subject figure rather than the "
            "total."
        )
    return sentence


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
    # Deliberately NOT appending the signal attribution here.
    #
    # `assessment` is the engine's verdict sentence; `signal_attribution` is a
    # separate structured fact about which address each signal was raised
    # against. Blending the two into the prose put the "this score aggregates
    # the whole graph" caveat on every surface twice -- once here, once in the
    # provenance block that both the report and the console render. A caveat
    # stated twice reads as emphasis and is really just noise, and the copy that
    # gets trimmed by whoever tidies the page is the one carrying the warning.
    return " ".join(parts)


def _token_contract_nodes(result: TraceResult) -> Dict[str, str]:
    """
    Addresses in this trace that are *token contracts* -- instruments rather
    than wallets.

    This is deliberately narrower than "is a contract", and the narrowing
    matters. Plenty of addresses a person or institution genuinely holds funds
    in are deployed contracts: Gnosis Safes, ERC-4337 accounts, exchange
    withdrawal contracts, bridge contracts. `vitalik.eth` is a verified
    multisig, so `eth_getCode` reports code for it, and suppressing its
    wallet-pattern signals on the strength of that would be wrong -- a multisig
    *is* a wallet, it just happens to be implemented as one.

    A token contract is different in kind. USDT is not a party to a
    transaction; it is the thing being moved, and it consolidates every
    transfer ever made through it as a matter of design. Fan-in on it describes
    the popularity of the token, not anyone's behaviour.

    So the test is whether the address is the contract behind a transfer in this
    trace, which is free and is true by construction for every token the trace
    actually moved. Returns address (lowercased) -> how it was established, so
    the reader is told the basis rather than shown a flag from nowhere.
    """
    found: Dict[str, str] = {}

    for tx in result.transactions:
        contract = (tx.token_contract or "").strip().lower()
        if contract and contract not in found:
            found[contract] = "it is the contract behind a transfer in this trace"

    seed_is_token = (result.seed or "").lower() in found
    if result.metadata.subject_is_contract is True and seed_is_token:
        # Both agree, which is the strongest form of the claim, and the one the
        # report should lead with.
        found[(result.seed or "").lower()] = (
            "confirmed against the chain as deployed bytecode, and it is the "
            "contract behind a transfer in this trace"
        )

    return found


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

    # Wallet-shaped signals are only meaningful for wallets.
    #
    # Fan-in, fan-out and rapid-movement describe how a *person or account*
    # handles money: many senders consolidating into one address is a layering
    # shape. A token contract does that by definition -- USDT consolidates every
    # transfer ever made in it -- and so does a staking pool and a payment
    # processor. Scoring them for it produces CRITICAL on Tether, which is not a
    # finding about Tether and is worse than useless, because a reader who sees
    # one absurd score learns to distrust every score this tool issues.
    #
    # The exclusion is for *token* contracts specifically, not for everything
    # with code at its address. A multisig is a contract and is still a wallet,
    # so it keeps its signals.
    #
    # The suppression is stated rather than left as a suspiciously low number.
    # A suppressed signal that leaves no trace reads as a negative result, and a
    # reader who sees a low score would conclude the address was checked and
    # found unremarkable -- the exact opposite of what happened.
    infrastructure = _token_contract_nodes(result)
    seed_key = (result.seed or "").lower()
    indicators += _fan_indicators(result, exclude=set(infrastructure))
    indicators += _rapid_hop_indicators(result, exclude=set(infrastructure))

    if seed_key in infrastructure:
        basis = infrastructure[seed_key]
        if result.metadata.subject_is_contract is True:
            established = "confirmed directly against the chain"
        else:
            established = (
                f"established from the transfers in this trace ({basis}), "
                f"not confirmed against the chain"
            )
        result.evidence_notes.append(
            "This address is a token contract, not a wallet, and the finding is "
            f"{established}. Standard fraud-pattern signals do not apply: "
            "inbound/outbound fan-in, fan-out and rapid-movement patterns "
            "describe how a wallet handles money, and a token contract "
            "consolidates every transfer made through it by design. Those "
            "signals were not computed for it. The risk score reflects the "
            "remaining signals only, and the absence of wallet-pattern findings "
            "is not evidence that this token is benign."
        )
    elif result.metadata.subject_is_contract is True:
        # A contract that is not a token contract: almost always a multisig or
        # smart account, i.e. a wallet that happens to be code. Its wallet-pattern
        # signals were computed and are meaningful, so the note says that rather
        # than leaving the reader to wonder whether a contract was penalised.
        result.evidence_notes.append(
            "This address is a deployed contract rather than an externally-owned "
            "account, confirmed against the chain. It is not the contract behind "
            "any transfer in this trace, so it is treated as a wallet -- the "
            "common case being a multisig or smart account, which holds funds "
            "and behaves like one. Wallet-pattern signals were computed for it "
            "normally."
        )

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
        signal_attribution=_attribute_signals(result, indicators),
    )
