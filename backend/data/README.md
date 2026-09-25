# Curated entity database

This file is **not** created by the application, and the application works
without it. It is the only place a VASP can be *named*.

## Why this file exists

The platform can locate an exchange-shaped address from transaction flow alone
(see `services/flow_intel.py`) — no dataset needed. What it cannot do is say
**which** exchange. That claim is about a legal entity, so it needs provenance,
and provenance means someone verified it and recorded where the verification
came from.

Measured on 2026-09-25, with no curated file present:

| Probe | Result |
|---|---|
| Ethereum · Binance 14 (`0x28C6c062…`) | no label |
| Ethereum · Coinbase 10 (`0x5038289…`) | no label |
| Polygon · any address | no label |
| BSC | no keyless provider configured |
| TRON | a party tag in 2 of 18 transfers, incidentally |
| Ethereum · `vitalik.eth` | resolves, as `service` |

Public indexers do not carry VASP labels at the keyless tier BlockTrace uses.
So without this file the honest answer to "which exchange received the funds" is
"an address behaving like one, unidentified".

## Do not populate this from memory

An address wrongly listed here is a mechanism for freezing an innocent party's
funds. Every record must carry a `source` that another person can go and check.
A record with no source is worse than no record: it looks like evidence.

Populate it from a licensed feed (TRM Intelligence, Chainalysis, Arkham,
Elliptic) or from a published exchange disclosure such as a proof-of-reserves
page or a withdrawal-address announcement, and record which.

## Schema

```json
{
  "entities": [
    {
      "address": "0x28C6c06298d514Db089934071355E5743bf21d60",
      "chain": "ethereum",
      "name": "<the registered legal entity or trading name>",
      "type": "exchange",
      "source": "<dataset or publication this came from, with a URL if any>",
      "verified_at": "2026-09-26",
      "confidence": 90,
      "notes": "optional free text"
    }
  ]
}
```

| Field | Required | Notes |
|---|---|---|
| `address` | yes | Matched case-insensitively. |
| `chain` | yes | One of the slugs in `GET /network/chains`. The same address on two chains is two records. |
| `name` | yes | The operator, not a brand mascot. |
| `type` | yes | One of `exchange`, `mixer`, `sanctioned`, `high_risk`, `service`. |
| `source` | yes | Where the claim comes from. See above. |
| `verified_at` | yes | ISO date. A stale attribution is a liability. |
| `confidence` | no | 0–100. Defaults to 100 when omitted. |
| `notes` | no | Free text. |

Records that fail validation are skipped, and `GET /health` reports
`config.entity_intelligence.curated_vasp_tier.error` if the file is unreadable,
so a malformed file degrades the tier rather than taking the API down.

## Check the tier is live

```bash
curl -s http://127.0.0.1:8000/health | python -m json.tool
```

`config.entity_intelligence.curated_vasp_tier.populated` is `false` until this
file has at least one valid record. `flow_shape_tier.available` is always `true`
and needs nothing.

## Point somewhere else

```bash
BLOCKTRACE_ENTITY_DB=/opt/blocktrace/vasp-entities.json
```
