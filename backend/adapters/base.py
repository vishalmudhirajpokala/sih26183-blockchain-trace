"""
Chain adapter contract.

The investigation engine above this layer only ever sees normalized
`BlockchainTransaction` / `TraceNode` / `TraceEdge` objects and calls the
methods defined here. It must never import a provider response shape.

Adding a chain means writing one subclass and registering it. It does not mean
touching the orchestrator, the risk engine, or the report generator.
"""

from __future__ import annotations

import abc
from typing import Any, Dict, List, Optional

from models.schemas import (
    Availability,
    BlockchainTransaction,
    Chain,
    EntityAttribution,
    TraceNode,
    TraceStatus,
)
from utils.http_client import HttpClient


class NetworkInfo:
    """A snapshot of live chain state. Fields may be None when unavailable."""

    def __init__(
        self,
        chain: Chain,
        status: str = "unknown",
        latest_block: Optional[int] = None,
        latest_block_hash: Optional[str] = None,
        latest_block_timestamp: Optional[int] = None,
        transaction_count: Optional[int] = None,
        provider: Optional[str] = None,
        availability: Availability = Availability.AVAILABLE,
        unavailable_reason: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.chain = chain
        self.status = status
        self.latest_block = latest_block
        self.latest_block_hash = latest_block_hash
        self.latest_block_timestamp = latest_block_timestamp
        self.transaction_count = transaction_count
        self.provider = provider
        self.availability = availability
        self.unavailable_reason = unavailable_reason
        self.extra = extra or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chain": self.chain.value,
            "chain_name": self.chain.display_name,
            "status": self.status,
            "latest_block": self.latest_block,
            "latest_block_hash": self.latest_block_hash,
            "latest_block_timestamp": self.latest_block_timestamp,
            "transaction_count": self.transaction_count,
            "provider": self.provider,
            "availability": self.availability.value,
            "unavailable_reason": self.unavailable_reason,
            "extra": self.extra,
        }


class ChainAdapter(abc.ABC):
    """
    Everything the investigation engine may ask of a chain.

    Implementations must never fabricate data. When a provider cannot answer,
    return the documented empty/unavailable result rather than plausible
    filler.
    """

    chain: Chain

    # --------------------------------------------------------
    # identity / validation
    # --------------------------------------------------------

    @abc.abstractmethod
    def validate_address(self, address: str) -> bool:
        """True only if the address is genuinely valid for this chain."""

    @abc.abstractmethod
    def validate_transaction_hash(self, tx_hash: str) -> bool:
        """True only if the hash is well-formed for this chain."""

    # --------------------------------------------------------
    # transaction retrieval
    # --------------------------------------------------------

    @abc.abstractmethod
    def get_transaction(self, tx_hash: str, client: HttpClient) -> Optional[BlockchainTransaction]:
        """Fetch one transaction by hash, or None if it does not exist."""

    @abc.abstractmethod
    def get_outgoing_transfers(
        self, address: str, client: HttpClient, limit: int = 10,
    ) -> List[BlockchainTransaction]:
        ...

    @abc.abstractmethod
    def get_incoming_transfers(
        self, address: str, client: HttpClient, limit: int = 10,
    ) -> List[BlockchainTransaction]:
        ...

    def get_address_activity(
        self, address: str, client: HttpClient, limit: int = 10,
    ) -> List[BlockchainTransaction]:
        """Union of incoming and outgoing, deduplicated by hash."""
        seen = {}
        for tx in self.get_outgoing_transfers(address, client, limit):
            seen[tx.hash] = tx
        for tx in self.get_incoming_transfers(address, client, limit):
            seen.setdefault(tx.hash, tx)
        return sorted(
            seen.values(),
            key=lambda t: t.timestamp or 0,
            reverse=True,
        )

    # --------------------------------------------------------
    # live network
    # --------------------------------------------------------

    @abc.abstractmethod
    def get_network_status(self, client: HttpClient) -> NetworkInfo:
        """Live chain state. Must degrade to an explicit unavailable state."""

    def get_latest_blocks(self, client: HttpClient, limit: int = 5) -> List[Dict[str, Any]]:
        return []

    def get_latest_transactions(self, client: HttpClient, limit: int = 10) -> List[Dict[str, Any]]:
        return []

    def get_network_metrics(self, client: HttpClient) -> Dict[str, Any]:
        """
        Derived metrics. Every key is None or an explicit unavailable marker
        when the provider does not expose it. Never invent TPS.
        """
        return {}

    # --------------------------------------------------------
    # entity intelligence
    # --------------------------------------------------------

    def get_address_label(
        self, address: str, client: HttpClient,
    ) -> Optional[EntityAttribution]:
        """
        A public label for an address, if this chain's providers expose one.

        The result must set `source_type` to PUBLIC_PROVIDER or HEURISTIC.
        """
        return None

    # --------------------------------------------------------
    # tracing
    # --------------------------------------------------------

    @abc.abstractmethod
    def trace(
        self,
        seed: str,
        client: HttpClient,
        max_depth: int = 3,
        max_nodes: int = 25,
        max_txs_per_node: int = 5,
        deadline: Optional[float] = None,
    ) -> "AdapterTrace":
        """
        Bounded multi-hop traversal for this chain.

        Returns an `AdapterTrace` holding nodes, edges, transactions, the hop
        path, and a `status` that distinguishes "found nothing" from "the
        provider failed".
        """

    # --------------------------------------------------------
    # capabilities
    # --------------------------------------------------------

    def supports(self, capability: str) -> bool:
        return capability in self.capabilities()

    def capabilities(self) -> List[str]:
        return [
            "address_validation",
            "transaction_lookup",
            "outgoing_transfers",
            "incoming_transfers",
            "network_status",
        ]


class AdapterTrace:
    """
    What an adapter hands back to the orchestrator.

    Intentionally contains no risk scoring and no entity resolution beyond what
    the chain itself can prove. Those belong to the shared services.
    """

    def __init__(
        self,
        chain: Chain,
        seed: str,
        status: TraceStatus = TraceStatus.UNKNOWN,
        status_detail: Optional[str] = None,
    ) -> None:
        self.chain = chain
        self.seed = seed
        self.status = status
        self.status_detail = status_detail
        self.nodes: List[TraceNode] = []
        self.edges: List = []
        self.transactions: List[BlockchainTransaction] = []
        self.hop_path: List[str] = []
        self.hops = 0
        self.notes: List[str] = []
        self.max_depth_reached = 0
        self.nodes_examined = 0
        self.transactions_inspected = 0
        self.truncated = False
        self.truncation_reasons: List[str] = []

    def add_node(self, node: TraceNode) -> TraceNode:
        for existing in self.nodes:
            if existing.address.lower() == node.address.lower():
                return existing
        self.nodes.append(node)
        return node
