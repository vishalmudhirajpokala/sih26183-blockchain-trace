"""
Shared entity intelligence.

Three provenance tiers, and the difference is never lost:

    CURATED_VERIFIED   entered by the investigation team, with a source and a
                       verification date. Empty by default -- and that is the
                       correct state until humans verify real addresses.
    PUBLIC_PROVIDER   a label a block explorer returned. True as a label, not
                       a verified fact.
    HEURISTIC         inferred by BlockTrace from structural rules (e.g. a
                       contract with many holders). Always low confidence.

RULE: no address is ever added from memory. A wrong entry in this file becomes a
false attribution in a forensic report, which is worse than no attribution.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

from models.schemas import (
    AttributionSource,
    EntityAttribution,
    EntityType,
    VerificationStatus,
)

# ============================================================
# CURATED DATABASE
# ============================================================
#
# INTENTIONALLY EMPTY.
#
# Add an entry only after confirming the address on a public block explorer.
# Every entry MUST carry: name, address, chain, type, source, source_url,
# verification_status and verified_at. See ENTITY_DB_PATH below for the schema.
#
# This is a list rather than the dict the previous tags.py used so that a
# single address can belong to more than one chain and carry real provenance.

ENTITY_DB_PATH = os.getenv(
    "BLOCKTRACE_ENTITY_DB",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "entities.json"),
)

# Built once at import; an empty list is a valid, expected state.
_CURATED: List[Dict] = []
_INDEX: Dict[str, Dict] = {}
_LOAD_ERROR: Optional[str] = None


def load_curated_entities(path: Optional[str] = None) -> List[Dict]:
    """
    Read the curated entity file if present.

    A malformed file must not take the API down: it degrades to an empty
    database and records why, which the caller can surface.
    """
    global _CURATED, _INDEX, _LOAD_ERROR

    target = path or ENTITY_DB_PATH

    if not os.path.exists(target):
        _CURATED, _INDEX, _LOAD_ERROR = [], {}, None
        return []

    try:
        with open(target, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError) as exc:
        _CURATED, _INDEX = [], {}
        _LOAD_ERROR = f"entity database unreadable: {exc}"
        return []

    records = payload.get("entities", []) if isinstance(payload, dict) else payload

    index: Dict[str, Dict] = {}
    for record in records or []:
        address = str(record.get("address", "")).strip()
        if not address:
            continue
        index[f"{record.get('chain', '').lower()}:{address.lower()}"] = record

    _CURATED, _INDEX, _LOAD_ERROR = list(records or []), index, None
    return _CURATED


def curated_status() -> Dict[str, object]:
    """For /entities and the health endpoint: is the curated tier populated?"""
    return {
        "count": len(_CURATED),
        "path": ENTITY_DB_PATH,
        "exists": os.path.exists(ENTITY_DB_PATH),
        "error": _LOAD_ERROR,
    }


# ============================================================
# PUBLIC LABEL HEURISTICS
# ============================================================
#
# These classify a label STRING returned by a provider. They are keyword
# matching on a third-party label, which is why the result is PUBLIC_PROVIDER
# and never CURATED_VERIFIED. The keyword lists are deliberately explicit so
# an unexpected label is simply not classified, rather than being forced into a
# category it does not belong to.

EXCHANGE_KEYWORDS = (
    "binance", "okx", "okex", "kucoin", "kraken", "bitfinex", "coinbase",
    "bitstamp", "huobi", "htx", "gate.io", "gateio", "mexc", "bybit",
    "crypto.com", "bitget", "phemex", "lbank", "xt.com", "tether treasury",
    "poloniex", "upbit", "bithumb", "wazirx", "gemini", "bitflyer",
    "ftx", "crypto_com", "whitebit", "bitget", "latoken", "indodax",
)

MIXER_KEYWORDS = (
    "mixer", "tumbler", "privacy", "coinjoin", "wasabi", "samourai",
    "blender", "shuffle", "obfuscation",
)

SANCTIONED_KEYWORDS = (
    "sanction", "ofac", "sdn", "blocked", "blacklist_ofac", "tether_frozen",
    "frozen", "chained_analysis", "crypto.com_hack", "fbi", "europol",
    "interpol", "sec_seized", "seized",
)

HIGH_RISK_KEYWORDS = (
    "scam", "fraud", "phishing", "hack", "hacker", "exploit", "blacklist",
    "stolen", "malicious", "ransomware", "darknet", "illicit", "ponzi",
    "rugpull", "pyramid",
)

SERVICE_KEYWORDS = (
    "bridge", "staking", "lending", "dex", "swap", "router", "aggregator",
    "dao", "treasury", "marketplace", "nft", "gaming", "prediction",
)

# Longest-first so "privacy" wins over a shorter accidental substring match.
_ALL_KEYWORDS: List[tuple] = sorted(
    [(k, EntityType.EXCHANGE, "medium") for k in EXCHANGE_KEYWORDS]
    + [(k, EntityType.MIXER, "high") for k in MIXER_KEYWORDS]
    + [(k, EntityType.SANCTIONED, "critical") for k in SANCTIONED_KEYWORDS]
    + [(k, EntityType.HIGH_RISK, "high") for k in HIGH_RISK_KEYWORDS]
    + [(k, EntityType.SERVICE, "low") for k in SERVICE_KEYWORDS],
    key=lambda item: len(item[0]),
    reverse=True,
)


def classify_public_label(label: Optional[str]) -> Optional[EntityType]:
    """
    Map a provider label string onto an entity type.

    Returns None when nothing matches. A None is meaningful: it means "we do
    not know", and the caller must present it as unknown rather than guessing.
    """
    if not label or not isinstance(label, str):
        return None

    lowered = label.lower()

    for keyword, entity_type, _severity in _ALL_KEYWORDS:
        if keyword in lowered:
            return entity_type

    return None


# ============================================================
# RESOLUTION
# ============================================================


def _curated_lookup(chain: str, address: str) -> Optional[Dict]:
    return _INDEX.get(f"{(chain or '').lower()}:{(address or '').lower()}")


def resolve_entity(
    address: str,
    chain: str,
    public_label: Optional[str] = None,
    source_url: Optional[str] = None,
) -> Optional[EntityAttribution]:
    """
    Resolve an address to an entity, preferring curated over public.

    Order is deliberate: a human-verified entry outranks a provider label, and
    the returned `source_type` always says which one produced the answer.
    """
    if not address:
        return None

    record = _curated_lookup(chain, address)
    if record:
        verified_at = record.get("verified_at")
        return EntityAttribution(
            name=record.get("name"),
            type=EntityType(record.get("type", "unknown")),
            source_type=AttributionSource.CURATED_VERIFIED,
            confidence=int(record.get("confidence", 90)),
            evidence=[
                f"Curated BlockTrace record, added {verified_at or 'date unrecorded'}",
                f"Verification source: {record.get('source', 'not recorded')}",
            ],
            source_url=record.get("source_url"),
            verification_status=VerificationStatus(
                record.get("verification_status", "verified")
            ),
            verified_at=verified_at,
            notes=record.get("notes"),
        )

    if not public_label:
        return None

    entity_type = classify_public_label(public_label)
    if entity_type is None:
        return None

    confidence = {
        EntityType.EXCHANGE: 70,
        EntityType.SANCTIONED: 70,
        EntityType.MIXER: 65,
        EntityType.HIGH_RISK: 60,
        EntityType.SERVICE: 50,
    }.get(entity_type, 40)

    return EntityAttribution(
        name=public_label,
        type=entity_type,
        source_type=AttributionSource.PUBLIC_PROVIDER,
        confidence=confidence,
        evidence=[
            f"Public block-explorer label: \"{public_label}\"",
            "Classified by BlockTrace keyword rules, not by a curated record.",
            "A public label indicates a provider's own annotation. It is not "
            "independent verification of the entity's identity or conduct.",
        ],
        source_url=source_url,
        verification_status=VerificationStatus.UNVERIFIED,
        notes=None,
    )


def list_entities() -> List[Dict]:
    """Every curated entity, for the /entities endpoint."""
    return [dict(record) for record in _CURATED]


def get_entity(entity_id_or_name: str) -> Optional[Dict]:
    key = (entity_id_or_name or "").strip().lower()
    for record in _CURATED:
        if str(record.get("id", "")).lower() == key:
            return dict(record)
        if str(record.get("name", "")).lower() == key:
            return dict(record)
    return None


def entity_addresses(entity_id: str) -> List[Dict]:
    return [
        {
            "address": record.get("address"),
            "chain": record.get("chain"),
            "label": record.get("name"),
            "source": record.get("source"),
            "source_url": record.get("source_url"),
            "verification_status": record.get("verification_status"),
            "verified_at": record.get("verified_at"),
        }
        for record in _CURATED
        if str(record.get("id", "")).lower() == (entity_id or "").lower()
    ]


load_curated_entities()
