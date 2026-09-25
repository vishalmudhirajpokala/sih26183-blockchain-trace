"""
Chain registry — the one place that maps a `Chain` to a concrete adapter.

This module is the seam that keeps the investigation engine chain-agnostic. The
engine asks "give me the adapter for this chain" and receives something that
satisfies `ChainAdapter`; it never imports `TronAdapter`, never sees
`apilist.tronscanapi.com`, and never branches on `if chain == Chain.TRON`.

Adding a sixth chain means writing one adapter and adding one line here. It
does not mean touching the orchestrator, the risk engine, the routers, or the
frontend.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from adapters.base import ChainAdapter
from adapters.bitcoin import BitcoinAdapter
from adapters.evm import EVMAdapter
from adapters.tron import TronAdapter
from models.schemas import Chain

#: Adapter instances are stateless with respect to a trace (the client carries
#: the cache and usage log), so one instance per chain is shared safely.
_ADAPTERS: Dict[Chain, ChainAdapter] = {
    Chain.TRON: TronAdapter(),
    Chain.ETHEREUM: EVMAdapter(Chain.ETHEREUM),
    Chain.BSC: EVMAdapter(Chain.BSC),
    Chain.POLYGON: EVMAdapter(Chain.POLYGON),
    Chain.BITCOIN: BitcoinAdapter(),
}


def get_adapter(chain: Chain) -> ChainAdapter:
    """
    The adapter for a chain.

    Raises KeyError for an unregistered chain rather than returning None, so a
    typo surfaces at the call site instead of as a confusing NoneAttributeError
    three layers down.
    """
    try:
        return _ADAPTERS[chain]
    except KeyError:
        raise KeyError(
            f"No adapter registered for {chain}. "
            f"Registered: {', '.join(c.value for c in _ADAPTERS)}"
        ) from None


def supported_chains() -> List[Chain]:
    return list(_ADAPTERS.keys())


def chain_capabilities() -> List[Dict[str, object]]:
    """
    What each chain can actually do right now, with this configuration.

    The UI reads this to explain a limitation before a user hits it, rather
    than letting a trace fail and showing an error after the fact.
    """
    summary = []
    for chain, adapter in _ADAPTERS.items():
        entry: Dict[str, object] = {
            "chain": chain.value,
            "chain_name": chain.display_name,
            "capabilities": adapter.capabilities(),
        }
        # An adapter may know it is partially blind. It is either a string
        # attribute or, on adapters that cannot trade a method for an
        # attribute, absent entirely — so read it defensively and never
        # assume it is callable.
        reason = getattr(adapter, "unavailable_reason", None)
        if callable(reason):
            reason = reason()
        if reason:
            entry["limitation"] = reason
        summary.append(entry)
    return summary


def register_adapter(chain: Chain, adapter: ChainAdapter) -> None:
    """Install or replace an adapter. Used by tests; not by request handlers."""
    _ADAPTERS[chain] = adapter


def is_registered(chain: Optional[Chain]) -> bool:
    return chain in _ADAPTERS
