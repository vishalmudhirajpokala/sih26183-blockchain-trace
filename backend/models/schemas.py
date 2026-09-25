"""
Normalized, chain-agnostic investigation data model.

Every chain adapter produces these structures. The investigation engine, the risk
engine, the report generator and the frontend all consume them, and none of them
may import a chain-specific provider payload.

Evidence discipline
-------------------
The model separates four things that a forensic product must never blur:

    FACT          direct provider data
    ATTRIBUTION   an entity label, with its provenance
    SIGNAL        a calculated risk indicator
    INTERPRETATION an automated analytical summary

`EntityAttribution` and `RiskIndicator` carry `provenance` / `evidence` so a
reader can always answer "why does the system believe this?".

Nothing in this module invents a value. A field that a provider could not supply
is None, and the surrounding `*_status` field says whether that is because the
data was unavailable or genuinely absent.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

# ============================================================
# ENUMS
# ============================================================


class Chain(str, Enum):
    """Supported chains. Values are the stable wire identifiers."""

    TRON = "tron"
    ETHEREUM = "ethereum"
    BSC = "bsc"
    POLYGON = "polygon"
    BITCOIN = "bitcoin"

    @property
    def is_evm(self) -> bool:
        return self in (Chain.ETHEREUM, Chain.BSC, Chain.POLYGON)

    @property
    def display_name(self) -> str:
        return {
            Chain.TRON: "TRON",
            Chain.ETHEREUM: "Ethereum",
            Chain.BSC: "BNB Smart Chain",
            Chain.POLYGON: "Polygon",
            Chain.BITCOIN: "Bitcoin",
        }[self]


class InputType(str, Enum):
    ADDRESS = "address"
    TRANSACTION_HASH = "transaction_hash"


class TraceStatus(str, Enum):
    """
    Why a trace ended.

    These are deliberately distinct. "We found nothing suspicious" and "the
    provider was down" must never collapse into the same word.
    """

    MATCHED = "matched"                  # reached a classified entity
    NO_MATCH = "no_match"                # traced successfully, no entity found
    INCONCLUSIVE = "inconclusive"        # traced but evidence was too thin
    INVALID_INPUT = "invalid_input"      # the input is not a valid address/hash
    PROVIDER_ERROR = "provider_error"    # every provider failed
    RATE_LIMITED = "rate_limited"        # providers rate-limited us out
    TIMEOUT = "timeout"                  # overall deadline hit
    PARTIAL = "partial"                  # some hops resolved, some failed
    DEPTH_EXCEEDED = "depth_exceeded"
    UNKNOWN = "unknown"


class EntityType(str, Enum):
    EXCHANGE = "exchange"
    MIXER = "mixer"
    SANCTIONED = "sanctioned"
    HIGH_RISK = "high_risk"
    SERVICE = "service"
    UNKNOWN = "unknown"


class AttributionSource(str, Enum):
    """
    Provenance tier for an entity label.

    The distinction is load-bearing: a curated, human-verified address is a
    different claim from a public label that matched a keyword.
    """

    CURATED_VERIFIED = "curated_verified"   # entered by the investigation team
    PUBLIC_PROVIDER = "public_provider"     # returned by a provider's own label
    HEURISTIC = "heuristic"                 # inferred by BlockTrace rules
    NONE = "none"


class VerificationStatus(str, Enum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    DISPUTED = "disputed"


class Severity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    MEDIUM_HIGH = "MEDIUM-HIGH"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
    UNKNOWN = "UNKNOWN"

    @property
    def rank(self) -> int:
        """Sortable ordering. UNKNOWN is not a level on this scale."""
        return {
            RiskLevel.LOW: 0,
            RiskLevel.MEDIUM: 1,
            RiskLevel.MEDIUM_HIGH: 2,
            RiskLevel.HIGH: 3,
            RiskLevel.CRITICAL: 4,
        }.get(self, -1)


class Direction(str, Enum):
    OUTGOING = "outgoing"
    INCOMING = "incoming"
    SELF = "self"


# ============================================================
# UNITS
# ============================================================


class Availability(str, Enum):
    """Whether a value is real, absent, or unobtainable. Never faked."""

    AVAILABLE = "available"
    NOT_PROVIDED = "not_provided"   # provider does not expose it
    UNAVAILABLE = "unavailable"     # provider was reached but failed
    UNSUPPORTED = "unsupported"     # chain does not have this concept


# ============================================================
# DESERIALIZATION HELPER
# ============================================================


def _enum(enum_cls, value: Any, default):
    """
    Rebuild an enum member from a wire string, tolerating an unknown value.

    A stored investigation is a historical record. If a later version adds an
    entity type, an older record naming it must still load — degrading that one
    field to the default and keeping the rest of the record is the correct
    behaviour. Raising would make a saved case un-openable because the code was
    upgraded, which is data loss caused by a deploy.
    """
    if value is None:
        return default
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(value)
    except (ValueError, KeyError):
        try:
            return enum_cls[str(value).upper()]
        except (ValueError, KeyError):
            return default


@dataclass
class AvailabilityInfo:
    status: Availability = Availability.AVAILABLE
    reason: Optional[str] = None


@dataclass
class EntityAttribution:
    """
    An entity label plus everything needed to audit it.

    `source_type` records which tier produced the claim. A public provider label
    is NOT a verified fact and the structure makes that impossible to lose.
    """

    name: Optional[str] = None
    type: EntityType = EntityType.UNKNOWN
    source_type: AttributionSource = AttributionSource.NONE
    confidence: int = 0
    evidence: List[str] = field(default_factory=list)
    source_url: Optional[str] = None
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    verified_at: Optional[str] = None
    notes: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type.value,
            "source_type": self.source_type.value,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "source_url": self.source_url,
            "verification_status": self.verification_status.value,
            "verified_at": self.verified_at,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> Optional["EntityAttribution"]:
        if not data:
            return None
        return cls(
            name=data.get("name"),
            type=_enum(EntityType, data.get("type"), EntityType.UNKNOWN),
            source_type=_enum(AttributionSource, data.get("source_type"), AttributionSource.NONE),
            confidence=int(data.get("confidence") or 0),
            evidence=list(data.get("evidence") or []),
            source_url=data.get("source_url"),
            verification_status=_enum(
                VerificationStatus, data.get("verification_status"), VerificationStatus.UNVERIFIED,
            ),
            verified_at=data.get("verified_at"),
            notes=data.get("notes"),
        )


@dataclass
class RiskIndicator:
    """
    A structured risk signal.

    `code` is a stable machine identifier, `weight` is what it contributes to
    the score, and `evidence` is what justifies it. An indicator without
    evidence is a bug, not a finding.
    """

    code: str
    name: str
    severity: Severity
    weight: int
    evidence: str = ""
    related_addresses: List[str] = field(default_factory=list)
    related_transactions: List[str] = field(default_factory=list)
    timestamp: Optional[int] = None
    amount: Optional[float] = None
    source: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "severity": self.severity.value,
            "weight": self.weight,
            "evidence": self.evidence,
            "related_addresses": self.related_addresses,
            "related_transactions": self.related_transactions,
            "timestamp": self.timestamp,
            "amount": self.amount,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RiskIndicator":
        return cls(
            code=data.get("code", ""),
            name=data.get("name", ""),
            severity=_enum(Severity, data.get("severity"), Severity.INFO),
            weight=int(data.get("weight") or 0),
            evidence=data.get("evidence", ""),
            related_addresses=list(data.get("related_addresses") or []),
            related_transactions=list(data.get("related_transactions") or []),
            timestamp=data.get("timestamp"),
            amount=data.get("amount"),
            source=data.get("source"),
        )


# ============================================================
# CORE NORMALIZED STRUCTURES
# ============================================================


@dataclass
class BlockchainTransaction:
    """A single normalized transfer, identical in shape across all chains."""

    chain: Chain
    hash: str
    timestamp: Optional[int] = None          # unix seconds
    from_address: Optional[str] = None
    to_address: Optional[str] = None
    asset: Optional[str] = None              # "USDT", "TRX", "BTC", "ETH"
    token_contract: Optional[str] = None
    amount: Optional[float] = None
    decimals: Optional[int] = None
    raw_amount: Optional[str] = None
    direction: Direction = Direction.OUTGOING
    block_number: Optional[int] = None
    status: str = "unknown"                  # success | failed | unknown
    fee: Optional[float] = None
    confirmations: Optional[int] = None
    # UTXO chains only: the transaction this one spends from.
    inputs: List[Dict[str, Any]] = field(default_factory=list)
    outputs: List[Dict[str, Any]] = field(default_factory=list)
    provider: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    def to_dict(self, include_raw: bool = False) -> Dict[str, Any]:
        data = {
            "chain": self.chain.value,
            "hash": self.hash,
            "timestamp": self.timestamp,
            "from_address": self.from_address,
            "to_address": self.to_address,
            "asset": self.asset,
            "token_contract": self.token_contract,
            "amount": self.amount,
            "decimals": self.decimals,
            "raw_amount": self.raw_amount,
            "direction": self.direction.value,
            "block_number": self.block_number,
            "status": self.status,
            "fee": self.fee,
            "confirmations": self.confirmations,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "provider": self.provider,
        }
        if include_raw:
            data["raw"] = self.raw
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BlockchainTransaction":
        return cls(
            chain=_enum(Chain, data.get("chain"), Chain.TRON),
            hash=data.get("hash", ""),
            timestamp=data.get("timestamp"),
            from_address=data.get("from_address"),
            to_address=data.get("to_address"),
            asset=data.get("asset"),
            token_contract=data.get("token_contract"),
            amount=data.get("amount"),
            decimals=data.get("decimals"),
            raw_amount=data.get("raw_amount"),
            direction=_enum(Direction, data.get("direction"), Direction.OUTGOING),
            block_number=data.get("block_number"),
            status=data.get("status", "unknown"),
            fee=data.get("fee"),
            confirmations=data.get("confirmations"),
            inputs=list(data.get("inputs") or []),
            outputs=list(data.get("outputs") or []),
            provider=data.get("provider"),
            raw=dict(data.get("raw") or {}),
        )


@dataclass
class TraceNode:
    """An address the investigation touched, with whatever we know about it."""

    address: str
    chain: Chain
    entity: Optional[EntityAttribution] = None
    entity_type: EntityType = EntityType.UNKNOWN
    source_type: AttributionSource = AttributionSource.NONE
    confidence: int = 0
    evidence: List[str] = field(default_factory=list)
    depth: int = 0
    inbound: int = 0
    outbound: int = 0
    is_seed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "address": self.address,
            "chain": self.chain.value,
            "entity": self.entity.to_dict() if self.entity else None,
            "entity_type": self.entity_type.value,
            "source_type": self.source_type.value,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "depth": self.depth,
            "inbound": self.inbound,
            "outbound": self.outbound,
            "is_seed": self.is_seed,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TraceNode":
        return cls(
            address=data.get("address", ""),
            chain=_enum(Chain, data.get("chain"), Chain.TRON),
            entity=EntityAttribution.from_dict(data.get("entity")),
            entity_type=_enum(EntityType, data.get("entity_type"), EntityType.UNKNOWN),
            source_type=_enum(AttributionSource, data.get("source_type"), AttributionSource.NONE),
            confidence=int(data.get("confidence") or 0),
            evidence=list(data.get("evidence") or []),
            depth=int(data.get("depth") or 0),
            inbound=int(data.get("inbound") or 0),
            outbound=int(data.get("outbound") or 0),
            is_seed=bool(data.get("is_seed")),
        )


@dataclass
class TraceEdge:
    """A value movement between two nodes."""

    transaction_hash: str
    from_address: Optional[str]
    to_address: Optional[str]
    chain: Chain
    asset: Optional[str] = None
    amount: Optional[float] = None
    timestamp: Optional[int] = None
    risk_flags: List[str] = field(default_factory=list)
    token_contract: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "transaction_hash": self.transaction_hash,
            "from_address": self.from_address,
            "to_address": self.to_address,
            "chain": self.chain.value,
            "asset": self.asset,
            "amount": self.amount,
            "timestamp": self.timestamp,
            "risk_flags": self.risk_flags,
            "token_contract": self.token_contract,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TraceEdge":
        return cls(
            transaction_hash=data.get("transaction_hash", ""),
            from_address=data.get("from_address"),
            to_address=data.get("to_address"),
            chain=_enum(Chain, data.get("chain"), Chain.TRON),
            asset=data.get("asset"),
            amount=data.get("amount"),
            timestamp=data.get("timestamp"),
            risk_flags=list(data.get("risk_flags") or []),
            token_contract=data.get("token_contract"),
        )


@dataclass
class RiskAssessment:
    """The complete, transparent output of the single risk engine."""

    risk_score: int = 0
    risk_level: RiskLevel = RiskLevel.UNKNOWN
    indicators: List[RiskIndicator] = field(default_factory=list)
    assessment: str = ""
    score_breakdown: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "risk_score": self.risk_score,
            "risk_level": self.risk_level.value,
            "indicators": [i.to_dict() for i in self.indicators],
            "indicator_names": [i.name for i in self.indicators],
            "assessment": self.assessment,
            "score_breakdown": self.score_breakdown,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "RiskAssessment":
        data = data or {}
        return cls(
            risk_score=int(data.get("risk_score") or 0),
            risk_level=_enum(RiskLevel, data.get("risk_level"), RiskLevel.UNKNOWN),
            indicators=[RiskIndicator.from_dict(i) for i in (data.get("indicators") or [])],
            assessment=data.get("assessment", ""),
            score_breakdown=dict(data.get("score_breakdown") or {}),
        )


@dataclass
class ProviderUsage:
    """Which provider actually served a piece of data, and how it went."""

    provider: str
    ok: bool
    status_code: Optional[int] = None
    latency_ms: Optional[int] = None
    retries: int = 0
    error: Optional[str] = None
    from_cache: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProviderUsage":
        return cls(
            provider=data.get("provider", ""),
            ok=bool(data.get("ok")),
            status_code=data.get("status_code"),
            latency_ms=data.get("latency_ms"),
            retries=int(data.get("retries") or 0),
            error=data.get("error"),
            from_cache=bool(data.get("from_cache")),
        )


@dataclass
class TraceMetadata:
    """Non-evidentiary facts about how the trace was produced."""

    investigation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    started_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    duration_ms: Optional[int] = None
    depth_limit: int = 0
    node_limit: int = 0
    max_depth_reached: int = 0
    nodes_examined: int = 0
    transactions_inspected: int = 0
    provider_usage: List[ProviderUsage] = field(default_factory=list)
    truncated: bool = False
    truncation_reasons: List[str] = field(default_factory=list)
    # Present only when the input was valid on more than one network and the
    # chain was settled by asking each network's indexer. It records what was
    # asked and what came back, so "this is an Ethereum address" is never shown
    # as though the address format had proved it, and a network that could not
    # be checked is visible as uncertain rather than empty.
    chain_resolution: Optional[dict] = None
    # Per-address flow shape and the investigative steps the shapes suggest. Both
    # are derived from the transfers in this result, so they are reproducible and
    # are stored with it. Kept under metadata rather than at the top level of the
    # result so the result's own key set -- which the multi-chain shape test
    # asserts exactly -- does not change.
    flow_shapes: Dict[str, Any] = field(default_factory=dict)
    recommendations: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "investigation_id": self.investigation_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_ms": self.duration_ms,
            "depth_limit": self.depth_limit,
            "node_limit": self.node_limit,
            "max_depth_reached": self.max_depth_reached,
            "nodes_examined": self.nodes_examined,
            "transactions_inspected": self.transactions_inspected,
            "provider_usage": [p.to_dict() for p in self.provider_usage],
            "truncated": self.truncated,
            "truncation_reasons": self.truncation_reasons,
            "chain_resolution": self.chain_resolution,
            "flow_shapes": self.flow_shapes,
            "recommendations": self.recommendations,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "TraceMetadata":
        data = data or {}
        return cls(
            investigation_id=data.get("investigation_id") or str(uuid.uuid4()),
            started_at=float(data.get("started_at") or 0.0),
            completed_at=data.get("completed_at"),
            duration_ms=data.get("duration_ms"),
            depth_limit=int(data.get("depth_limit") or 0),
            node_limit=int(data.get("node_limit") or 0),
            max_depth_reached=int(data.get("max_depth_reached") or 0),
            nodes_examined=int(data.get("nodes_examined") or 0),
            transactions_inspected=int(data.get("transactions_inspected") or 0),
            provider_usage=[ProviderUsage.from_dict(p) for p in (data.get("provider_usage") or [])],
            truncated=bool(data.get("truncated")),
            truncation_reasons=list(data.get("truncation_reasons") or []),
            chain_resolution=data.get("chain_resolution"),
            flow_shapes=data.get("flow_shapes") or {},
            recommendations=data.get("recommendations") or [],
        )


@dataclass
class TraceResult:
    """
    The single normalized result object.

    Every chain produces this. The orchestrator, risk engine, report service and
    frontend all read it, which is what makes the engine above the adapter layer
    chain-agnostic.
    """

    chain: Chain
    seed: str
    input_type: InputType = InputType.ADDRESS
    status: TraceStatus = TraceStatus.UNKNOWN
    status_detail: Optional[str] = None

    nodes: List[TraceNode] = field(default_factory=list)
    edges: List[TraceEdge] = field(default_factory=list)
    transactions: List[BlockchainTransaction] = field(default_factory=list)
    hop_path: List[str] = field(default_factory=list)
    hops: int = 0

    seed_entity: Optional[EntityAttribution] = None
    entity: Optional[EntityAttribution] = None
    risk: RiskAssessment = field(default_factory=RiskAssessment)

    report: Optional[str] = None
    report_id: Optional[str] = None
    metadata: TraceMetadata = field(default_factory=TraceMetadata)
    evidence_notes: List[str] = field(default_factory=list)

    def node_for(self, address: str) -> Optional[TraceNode]:
        key = (address or "").lower()
        for node in self.nodes:
            if node.address.lower() == key:
                return node
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chain": self.chain.value,
            "chain_name": self.chain.display_name,
            "seed": self.seed,
            "input_type": self.input_type.value,
            "status": self.status.value,
            "status_detail": self.status_detail,
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "transactions": [t.to_dict() for t in self.transactions],
            "hop_path": self.hop_path,
            "hops": self.hops,
            "seed_entity": self.seed_entity.to_dict() if self.seed_entity else None,
            "entity": self.entity.to_dict() if self.entity else None,
            "risk": self.risk.to_dict(),
            "report": self.report,
            "report_id": self.report_id,
            "metadata": self.metadata.to_dict(),
            "evidence_notes": self.evidence_notes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TraceResult":
        """
        Rebuild a result from its wire form — the exact inverse of `to_dict`.

        This exists so a stored investigation can be re-rendered into a PDF
        without re-querying the providers. Re-tracing would produce a *different*
        document describing a different moment in time, filed under the same id,
        which is the silent mutation a forensic record must never undergo.

        The round trip is exact: `TraceResult.from_dict(r.to_dict()).to_dict()`
        equals `r.to_dict()` for any result this version produced. That property
        is asserted in tests/roundtrip.py.
        """
        return cls(
            chain=_enum(Chain, data.get("chain"), Chain.TRON),
            seed=data.get("seed", ""),
            input_type=_enum(InputType, data.get("input_type"), InputType.ADDRESS),
            status=_enum(TraceStatus, data.get("status"), TraceStatus.UNKNOWN),
            status_detail=data.get("status_detail"),
            nodes=[TraceNode.from_dict(n) for n in (data.get("nodes") or [])],
            edges=[TraceEdge.from_dict(e) for e in (data.get("edges") or [])],
            transactions=[
                BlockchainTransaction.from_dict(t) for t in (data.get("transactions") or [])
            ],
            hop_path=list(data.get("hop_path") or []),
            hops=int(data.get("hops") or 0),
            seed_entity=EntityAttribution.from_dict(data.get("seed_entity")),
            entity=EntityAttribution.from_dict(data.get("entity")),
            risk=RiskAssessment.from_dict(data.get("risk")),
            report=data.get("report"),
            report_id=data.get("report_id"),
            metadata=TraceMetadata.from_dict(data.get("metadata")),
            evidence_notes=list(data.get("evidence_notes") or []),
        )
