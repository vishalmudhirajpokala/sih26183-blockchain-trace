"""
Flow-shape classification: what does this address *behave* like?

WHY THIS EXISTS
---------------
The problem this platform is built for is to identify the exchange or VASP
receiving a fraud victim's deposits. That identification has exactly two
possible sources, and only one of them can be produced by this codebase:

  1. A curated label someone else verified. `entity_service` already supports
     this at the `curated_verified` tier, reading `data/entities.json`. It is the
     authoritative answer, and it is empty until an operator populates it from a
     licensed feed (TRM, Chainalysis, Arkham) or a published exchange
     disclosure. Nothing here can substitute for it and nothing here should
     pretend to.

  2. The address's own observable behaviour. This module.

The distinction matters more than it looks. Naming a specific company --
"Binance" -- is a claim about a legal entity and needs provenance, so it belongs
in tier 1. Saying "this address receives from many senders and sends to many
recipients, which is the shape of a deposit address rather than a burner" is a
claim about observed behaviour, it is derived from the data the engine already
collected, and it is reproducible. That is a `heuristic` claim, and it is
recorded as one.

WHAT IT DOES NOT DO
-------------------
It does not name a VASP. It does not assert that any address is criminal, or
that funds flowing to it are proceeds of crime. Reaching an exchange is
ordinary -- the risk engine already scores `W_EXCHANGE = 10` for exactly that
reason, and the low weight is the correct signal. A shape label narrows where an
investigator should look; it convicts no one.

THE FOUR SHAPES
---------------
Measured from the subject's perspective, using the normalized transfers:

  collector     many distinct senders, few or no outgoing transfers. This is the
                signature the brief is actually about: a wallet that only
                receives, from many unrelated parties, and does not itself pay
                anyone. A fraud collection wallet and a burner look like this.

  exchange_like many distinct senders AND many distinct recipients, sustained
                over time. Deposit addresses aggregate and redistribute, so the
                bidirectional fan is the shape that separates an exchange from a
                collection wallet. This is the *behavioural* counterpart to a
                curated exchange label, and it is what lets an investigator
                decide a curated lookup is worth doing.

  distributor   few senders, many distinct recipients. Consolidation outward:
                the shape of a payout or cash-out stage.

  relay         roughly one-to-one in both directions. An ordinary wallet, or a
                single payment.

The thresholds are deliberately modest and stated in the output, because a
classifier whose parameters are hidden cannot be argued with by a defence
expert, and cannot be tuned by an operator either.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from models.schemas import AttributionSource, EntityType, TraceResult

# A party is "distinct" by lowercased address: the same identity the engine uses
# to de-duplicate nodes, so a wallet cannot inflate its own fan by appearing
# under case variants.
def _key(address: Optional[str]) -> Optional[str]:
    return address.lower() if address else None


#: Distinct counterparties on each side before a fan is called a fan. Low, and
#: intentionally so: the point is to separate "a few transfers" from "an
#: address that lots of unrelated parties pay", not to draw a fine boundary.
FAN_THRESHOLD = 3


def flow_shape(result: TraceResult) -> Dict[str, Dict]:
    """
    Classify every address in a result by observed flow shape.

    Returns a map keyed by lowercased address, so it is stable and free of array
    indices. Every address that appears in a transfer is classified, including
    ones the traversal did not expand to -- a counterparty seen only in a
    transfer record is still evidence about how that address behaves.
    """
    subject = _key(result.seed)
    senders: Dict[str, set] = {}
    recipients: Dict[str, set] = {}
    sent_count: Dict[str, int] = {}
    received_count: Dict[str, int] = {}
    value_in: Dict[str, float] = {}
    value_out: Dict[str, float] = {}
    assets: Dict[str, set] = {}
    first_seen: Dict[str, int] = {}
    last_seen: Dict[str, int] = {}

    for tx in result.transactions or []:
        frm, to = _key(tx.from_address), _key(tx.to_address)
        if not frm or not to:
            continue

        recipients.setdefault(frm, set()).add(to)
        senders.setdefault(to, set()).add(frm)
        sent_count[frm] = sent_count.get(frm, 0) + 1
        received_count[to] = received_count.get(to, 0) + 1

        if isinstance(tx.amount, (int, float)):
            value_in[to] = value_in.get(to, 0.0) + tx.amount
            value_out[frm] = value_out.get(frm, 0.0) + tx.amount

        for party in (frm, to):
            if tx.asset:
                assets.setdefault(party, set()).add(tx.asset)
            if isinstance(tx.timestamp, int):
                first_seen[party] = min(first_seen.get(party, tx.timestamp), tx.timestamp)
                last_seen[party] = max(last_seen.get(party, 0), tx.timestamp)

    shapes: Dict[str, Dict] = {}
    for address in set(senders) | set(recipients):
        in_fan = len(senders.get(address, ()))
        out_fan = len(recipients.get(address, ()))
        label, reasoning = _classify(in_fan, out_fan)

        shapes[address] = {
            "shape": label,
            "inbound_counterparties": in_fan,
            "outbound_counterparties": out_fan,
            "inbound_transfers": received_count.get(address, 0),
            "outbound_transfers": sent_count.get(address, 0),
            "value_in": round(value_in.get(address, 0.0), 8) or None,
            "value_out": round(value_out.get(address, 0.0), 8) or None,
            "assets": sorted(a for a in assets.get(address, ()) if a),
            "active_from": first_seen.get(address),
            "active_to": last_seen.get(address),
            "is_subject": address == subject,
            "reasoning": reasoning,
        }

    return shapes


def _classify(in_fan: int, out_fan: int) -> Tuple[str, str]:
    """Assign a shape and state the evidence for it, in the output itself."""
    wide_in = in_fan >= FAN_THRESHOLD
    wide_out = out_fan >= FAN_THRESHOLD

    if wide_in and wide_out:
        return (
            "exchange_like",
            f"Receives from {in_fan} distinct senders and pays {out_fan} distinct "
            f"recipients. Aggregating and redistributing value in both directions "
            f"is the behavioural shape of a deposit address, not a collection "
            f"wallet.",
        )
    if wide_in and not wide_out:
        return (
            "collector",
            f"Receives from {in_fan} distinct senders and pays "
            f"{out_fan} distinct recipients. One-directional collection from "
            f"many unrelated parties, with little onward movement, is the shape a "
            f"fraud collection wallet and a burner leave.",
        )
    if wide_out and not wide_in:
        return (
            "distributor",
            f"Receives from {in_fan} distinct senders and pays {out_fan} distinct "
            f"recipients. Scattering value onward to many recipients is the shape "
            f"of a cash-out or payout stage.",
        )
    return (
        "relay",
        f"Receives from {in_fan} distinct sender(s) and pays {out_fan} distinct "
        f"recipient(s). Neither side fans out, which is an ordinary transfer "
        f"rather than an aggregation point.",
    )


#: How each shape maps onto the entity vocabulary the rest of the app already
#: uses. `collector` deliberately does NOT become a risk entity type -- it is a
#: neutral description of a direction of flow, and inventing an entity type for
#: it would let a shape label read as an accusation.
SHAPE_ENTITY_TYPE = {
    "exchange_like": EntityType.EXCHANGE,
    "collector": EntityType.SERVICE,
    "distributor": EntityType.SERVICE,
    "relay": EntityType.UNKNOWN,
}


def as_attribution(shape: Dict) -> Dict:
    """
    Render a shape as an `EntityAttribution`-shaped dict at the HEURISTIC tier.

    Deliberately not `curated_verified` and deliberately carrying a name. A
    heuristic may contribute a weak `entity_type` hint the risk engine can weigh
    at low confidence, but it may never claim a name or a source URL, because
    there is no third party standing behind either.
    """
    label = shape.get("shape", "relay")
    return {
        "name": None,
        "type": SHAPE_ENTITY_TYPE.get(label, EntityType.UNKNOWN).value,
        "source_type": AttributionSource.HEURISTIC.value,
        # Low by construction. This is a pattern, and the weight the risk engine
        # gives a heuristic must reflect that; a shape reading "80% sure this is
        # an exchange" would be a lie about what was actually observed.
        "confidence": 20,
        "evidence": [
            f"Flow shape: {label} -- {shape.get('reasoning', '')}",
            (
                f"Observed: {shape.get('inbound_counterparties', 0)} inbound and "
                f"{shape.get('outbound_counterparties', 0)} outbound distinct "
                f"counterparties over {shape.get('inbound_transfers', 0)}/"
                f"{shape.get('outbound_transfers', 0)} transfers."
            ),
        ],
        "source_url": None,
        "verification_status": "unverified",
        "verified_at": None,
        "notes": (
            "Derived from transaction flow in this investigation. This is a "
            "pattern, not an identification: it does not name the operator of "
            "this address and is not evidence that it is involved in crime."
        ),
    }


def nearest_vasp_candidates(
    result: TraceResult, shapes: Dict[str, Dict]
) -> Dict[str, Any]:
    """
    Rank the traced address's immediate counterparties by how VASP-like they are.

    The problem statement asks for "the nearest exchange or VASP receiving direct
    deposits". This answers it as far as the available data honestly allows, and
    it is deliberately built from two things only: a counterparty's flow shape,
    which is computed from the transfers in front of us, and whatever label a
    public provider already attached to it. No new data source, no model, no
    inference beyond the existing four-shape classification.

    THE ONE RULE THIS FUNCTION ENFORCES

    A candidate is never presented as identified unless an address in the
    curated registry or a public provider label says so, and when it is, the
    existing provenance language travels with it unchanged -- source tier,
    confidence, verification status. A behavioural candidate with no label is
    reported as unlabelled, in those words, because "exchange-like" is a
    description of traffic and not an identity. A scammer's deposit address
    aggregates and redistributes exactly as an exchange's does; that is the whole
    reason the shape cannot be allowed to read as a name.

    RANKING, and why

      1. labelled, and labelled as an exchange -- an actual identification, and
         the only thing in this list that is one
      2. unlabelled but `exchange_like` -- the behaviour matches a deposit
         address, nothing more
      3. labelled as something else -- named, but not as a VASP
      4. anything else is not a candidate and is not listed

    Only hop-1 counterparties are considered. "Nearest" is meant literally: a
    candidate three hops out is a different question, and a trace bounded at
    depth 1 would otherwise return an empty list while implying it had looked
    further than it did.
    """
    seed = (result.seed or "").lower()

    # Which direction money moved between the subject and each counterparty, from
    # the transfers themselves rather than from the shape record.
    direction: Dict[str, str] = {}
    for tx in result.transactions:
        sender = (tx.from_address or "").lower()
        recipient = (tx.to_address or "").lower()
        if sender == seed and recipient and recipient != seed:
            direction[recipient] = "received_from_subject"
        elif recipient == seed and sender and sender != seed:
            direction.setdefault(sender, "sent_to_subject")

    candidates = []
    for node in result.nodes:
        address = node.address or ""
        key = address.lower()
        if key == seed:
            continue
        # Hop 1 only. A node the shape record never saw has no flow evidence, so
        # it cannot be assessed and is not guessed at.
        shape = shapes.get(key) or shapes.get(address)
        if not shape:
            continue
        # Hop 1 only, from the node's own depth. The shape record has no depth
        # field, and "nearest" is meant literally -- a candidate further out is
        # a different question.
        depth = getattr(node, "depth", None)
        if not isinstance(depth, int) or depth != 1:
            continue
        if int(shape.get("inbound_counterparties", 0)) == 0 and int(
            shape.get("outbound_counterparties", 0)
        ) == 0:
            # Present as a node but with no observed fan in either direction.
            continue

        entity = node.entity
        is_labelled = entity is not None and bool(getattr(entity, "name", None))
        entity_type = getattr(getattr(entity, "type", None), "value", None)
        is_exchange_label = is_labelled and entity_type == EntityType.EXCHANGE.value
        shape_name = shape.get("shape")

        if is_exchange_label:
            rank = 0
        elif shape_name == "exchange_like":
            rank = 1
        elif is_labelled:
            rank = 2
        else:
            continue

        # `identified` is the whole point of the feature, so it is computed once
        # here and the UI reads it rather than re-deriving it and getting it
        # subtly wrong.
        identified = is_exchange_label
        if identified:
            status = "identified"
            statement = (
                f"Labelled {entity.name} ({entity_type}) by a "
                f"{getattr(entity.source_type, 'value', 'unknown')} source at "
                f"{entity.confidence}% confidence, "
                f"{getattr(entity.verification_status, 'value', 'unverified')}. "
                f"This is a provider's label, not a BlockTrace confirmation."
            )
        elif shape_name == "exchange_like":
            status = "unlabelled"
            statement = (
                "Unlabelled \u2014 flow shape suggests possible exchange/VASP, not "
                "confirmed. No provider or curated record names this address. Its "
                "traffic aggregates and redistributes in both directions, which "
                "is also what a fraudulent deposit address does."
            )
        else:
            status = "labelled_not_vasp"
            statement = (
                f"Labelled {entity.name} ({entity_type}), which is not an "
                f"exchange or VASP. Listed because it is a named counterparty on "
                f"the path, not as a VASP candidate."
            )

        candidates.append({
            "address": address,
            "hop": depth,
            "rank": rank,
            "status": status,
            "identified": identified,
            "shape": shape_name,
            "shape_reasoning": shape.get("reasoning"),
            "direction": direction.get(key),
            "inbound_counterparties": shape.get("inbound_counterparties"),
            "outbound_counterparties": shape.get("outbound_counterparties"),
            "value": shape.get("value_in") if direction.get(key) == "sent_to_subject"
                    else shape.get("value_out"),
            "assets": shape.get("assets") or [],
            "entity": {
                "name": entity.name,
                "type": entity_type,
                "source_type": getattr(entity.source_type, "value", None),
                "confidence": entity.confidence,
                "verification_status": getattr(entity.verification_status, "value", None),
                "source_url": getattr(entity, "source_url", None),
                "notes": getattr(entity, "notes", None),
            } if is_labelled else None,
            "statement": statement,
        })

    candidates.sort(key=lambda c: (c["rank"], -(c.get("value") or 0)))

    return {
        "fan_threshold": FAN_THRESHOLD,
        "considered": "hop-1 counterparties only",
        "named": sum(1 for c in candidates if c["identified"]),
        "unlabelled_candidates": sum(
            1 for c in candidates if c["status"] == "unlabelled"
        ),
        "candidates": candidates,
        # Stated once, at the top, so a reader who only reads this still knows
        # the difference between the two kinds of row below it.
        "note": (
            "Candidates are ranked from observed flow and existing labels only. "
            "A row marked 'identified' carries a public provider's label at the "
            "confidence shown; a row marked 'unlabelled' is a behavioural "
            "observation and names nobody. No address is identified by this "
            "system on the basis of its transaction pattern alone."
        ),
    }


def investigative_recommendations(
    result: TraceResult, shapes: Dict[str, Dict]
) -> List[Dict]:
    """
    What the shapes actually suggest an investigator should do next.

    Each item names the addresses it is about and says why, so it is a
    recommendation an analyst can check rather than a black-box priority score.
    No item asserts a conclusion; each is a next *step*.
    """
    out: List[Dict] = []

    exchange_like = [a for a, s in shapes.items() if s["shape"] == "exchange_like"]
    collectors = [a for a, s in shapes.items() if s["shape"] == "collector"]
    distributors = [a for a, s in shapes.items() if s["shape"] == "distributor"]

    if exchange_like:
        out.append(
            {
                "code": "vasp_deposit_candidate",
                "title": "Exchange-shaped addresses in the flow",
                "detail": (
                    f"{len(exchange_like)} address(es) receive from many senders "
                    f"and pay many recipients. That is the behaviour of a deposit "
                    f"address and is where an asset-freeze request is most likely "
                    f"to succeed."
                ),
                "addresses": sorted(exchange_like),
                "next_step": (
                    "Look these up against a licensed VASP dataset to name the "
                    "operator, then raise a preservation request against the "
                    "identified VASP. The behaviour is not the identification."
                ),
            }
        )

    if collectors:
        out.append(
            {
                "code": "collection_wallet_shape",
                "title": "Addresses that only receive",
                "detail": (
                    f"{len(collectors)} address(es) receive from several distinct "
                    f"parties and pay almost no one, which is how a fraud "
                    f"collection wallet or burner behaves."
                ),
                "addresses": sorted(collectors),
                "next_step": (
                    "Treat these as collection points. Their earliest inbound "
                    "counterparty is often the originating wallet, and the "
                    "closest exchange-shaped address on their onward path is "
                    "where the proceeds surface."
                ),
            }
        )

    if distributors:
        out.append(
            {
                "code": "cashout_shape",
                "title": "Addresses that scatter value onward",
                "detail": (
                    f"{len(distributors)} address(es) pay many distinct recipients "
                    f"while receiving from few, consistent with a payout stage."
                ),
                "addresses": sorted(distributors),
                "next_step": (
                    "Trace these toward their nearest exchange-shaped or "
                    "exchange-labelled address; a payout stage usually terminates "
                    "at a VASP."
                ),
            }
        )

    if not out:
        out.append(
            {
                "code": "no_shape_signal",
                "title": "No aggregation or cash-out shape detected",
                "detail": (
                    "No address in this result fans out to several distinct "
                    "counterparties in either direction, so nothing here suggests "
                    "a collection point, a payout stage or a deposit address."
                ),
                "addresses": [],
                "next_step": (
                    "This is a statement about the addresses this run examined, "
                    "not about the subject's full history. Widen depth or nodes if "
                    "the run was truncated."
                ),
            }
        )

    return out
