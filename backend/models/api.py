"""
Request and response models for the HTTP API.

These are the only shapes that cross the network boundary. They exist so the
routers stay thin and so the wire contract is written down in one place rather
than implied by whatever a handler happens to return.

Two rules:

1. **No invented defaults.** Every field that could plausibly be faked has to
   be supplied by a real source. `preferred_chain=None` means "detect it",
   never "assume TRON because that is the default".

2. **The frontend never sees a raw provider payload.** `TraceResult.to_dict()`
   is the contract, and it is identical for every chain.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from models.schemas import Chain

# ============================================================
# REQUESTS
# ============================================================


class TraceRequestBody(BaseModel):
    """
    Run an investigation.

    `query` is whatever the user pasted: an address or a transaction hash, on
    any supported chain. The detector decides which.
    """

    query: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="A wallet address or transaction hash on any supported chain",
    )
    preferred_chain: Optional[Chain] = Field(
        default=None,
        description=(
            "Pin the input to one chain. Required in practice for 0x-prefixed "
            "EVM addresses, which are valid on Ethereum, BSC and Polygon at once."
        ),
    )
    max_depth: Optional[int] = Field(default=None, ge=0, le=6)
    max_nodes: Optional[int] = Field(default=None, ge=1, le=200)
    max_txs_per_node: Optional[int] = Field(default=None, ge=1, le=50)
    deadline_seconds: Optional[int] = Field(default=None, ge=5, le=300)
    title: Optional[str] = Field(
        default=None,
        max_length=200,
        description="A name for this case in the investigation history",
    )
    save: bool = Field(
        default=True,
        description="Persist this investigation so it appears in history",
    )
    generate_report: bool = Field(
        default=True,
        description="Render a PDF dossier alongside the result",
    )

    @field_validator("query")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("query must not be blank")
        return cleaned


class DetectRequestBody(BaseModel):
    """Identify an input without running a full trace."""

    query: str = Field(..., min_length=1, max_length=128)
    preferred_chain: Optional[Chain] = None


class SaveInvestigationBody(BaseModel):
    """
    Persist a completed investigation.

    The full result travels with the request rather than being re-derived from
    an id, because a trace is a record of what the providers said at a moment
    in time. Re-running it later would produce a different document, and a
    forensic history that silently mutates is worse than no history.
    """

    result: Dict[str, Any] = Field(
        ...,
        description="A `TraceResult.to_dict()` payload exactly as the trace endpoint returned it",
    )
    title: Optional[str] = Field(default=None, max_length=200)
    notes: Optional[str] = Field(default=None, max_length=5000)


# ============================================================
# RESPONSES
# ============================================================


class HealthResponse(BaseModel):
    status: str
    version: str
    chains: List[str]
    config: Dict[str, Any]
    persistence: str
    auth: str


class DetectResponse(BaseModel):
    """
    What an input is, as determined without calling a provider.

    `candidates` is the list of chain slugs the input is structurally valid on.
    It exists because one address format can be valid on several chains at once:
    a `0x…` address is valid on Ethereum, BSC and Polygon simultaneously, and
    the chains' *contents* differ completely. The Trace Console reads this to
    refuse to pick for the operator.

    The field name must match what `services.chain_detection.detect_chain`
    actually returns. An earlier version of this model declared
    `alternatives: List[Dict[str, Any]]` instead, and pydantic v2 silently
    discards undeclared keys — so `candidates` never reached the wire and
    `alternatives` was always empty. The console would have been unable to say
    *why* an input was ambiguous, and the ambiguity check would have had nothing
    to enumerate.
    """
    chain: Optional[str] = None
    chain_name: Optional[str] = None
    input_type: Optional[str] = None
    valid: bool
    ambiguous: bool = False
    confidence: int = 0
    normalized_input: Optional[str] = None
    address_type: Optional[str] = None
    reason: Optional[str] = None
    note: Optional[str] = None
    network: Optional[str] = None
    candidates: List[str] = Field(default_factory=list)


class TraceResponse(BaseModel):
    """The normalized investigation. Identical shape for every chain."""

    result: Dict[str, Any]
    report_url: Optional[str] = None
    investigation_id: Optional[str] = None


class ChainCapability(BaseModel):
    """
    What one chain adapter can actually do *in this deployment*.

    `capabilities` is a list of capability names, mirroring
    `ChainAdapter.capabilities() -> List[str]` in `adapters/base.py`. That
    abstract method is the contract every adapter already honours; an earlier
    version of this model declared the field as a dict, which rejected all
    five chains at runtime with a 500 on `/network/chains`.

    The list is deliberately allowed to be *shorter* per chain rather than
    padded to a fixed set: an EVM chain with no API key and no Blockscout
    fallback really cannot do address history, and a matrix that showed it
    anyway would be the "fake capability" this project exists to avoid. The
    UI renders the union of all names and checks membership per chain.

    `limitation` carries the adapter's own explanation of what it cannot do,
    in words a user can act on.
    """

    chain: str
    chain_name: str
    capabilities: List[str]
    limitation: Optional[str] = None


class NetworkStatusResponse(BaseModel):
    """
    Live chain status.

    Any metric a provider does not expose is `None` with an explicit
    availability marker beside it. It is never filled with a plausible number.

    `block_hash`, `block_timestamp`, `transaction_count`, `provider` and
    `availability` were added because `routers/network.py` already computed all
    five from the adapter's `NetworkInfo`, and Pydantic was silently discarding
    them because they were not declared here. The network explorer reads every
    one of them, so without these fields the page reported a chain's provider
    and tip timestamp as permanently unavailable even though the backend had
    them in hand.
    """

    chain: str
    chain_name: str
    block_height: Optional[int] = None
    block_hash: Optional[str] = None
    block_timestamp: Optional[int] = None
    transaction_count: Optional[int] = None
    provider: Optional[str] = None
    availability: str = "available"
    tps: Optional[float] = None
    tps_availability: str = "not_provided"
    average_block_time_seconds: Optional[float] = None
    block_time_source: Optional[str] = None
    available: bool = True
    unavailable_reason: Optional[str] = None
    checked_at: float
    evidence_notes: List[str] = Field(default_factory=list)


class InvestigationSummary(BaseModel):
    id: str
    title: str
    chain: str
    chain_name: str
    seed: str
    status: str
    risk_score: int
    risk_level: str
    entity_name: Optional[str] = None
    nodes: int
    transactions: int
    created_at: str
    has_report: bool = False


class PaginatedResponse(BaseModel):
    items: List[Any]
    total: int
    limit: int
    offset: int


class ErrorResponse(BaseModel):
    """
    Errors are structured, not prose.

    A forensic tool that answers "something went wrong" forces the operator to
    guess whether the input was wrong, the provider was down, or the tool
    failed — three very different problems with three different responses.
    """

    error: str
    detail: str
    # One of: invalid_input | not_found | provider_error | rate_limited |
    #        timeout | unavailable | internal
    kind: str = "internal"
    # Present when the failure is about a specific input, so the UI can show
    # the detected chain and why it was rejected.
    detection: Optional[Dict[str, Any]] = None
