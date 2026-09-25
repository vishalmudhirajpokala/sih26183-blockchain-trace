# Provider capability findings

Live probes run against every candidate data source, with the results recorded
verbatim. These findings drive the provider configuration in the adapters — they
are not assumptions, and any entry here can be re-verified with `curl`.

Re-probed 2026-09-25. Several endpoints that worked in an earlier round of
probing have since changed or been withdrawn; the "second probe" column records
the change.

## Summary

| Chain | Provider | Endpoint | Result |
|---|---|---|---|
| TRON | TronGrid | `POST api.trongrid.io/wallet/getnowblock` | 200, block 86548093 |
| TRON | TronGrid | `GET api.trongrid.io/v1/accounts/{a}/transactions` | 200 — keyless |
| TRON | TronGrid | `GET api.trongrid.io/v1/accounts/{a}/transactions/trc20` | 200 — keyless, honours `only_to` |
| TRON | TronScan | `apilist.tronscanapi.com/api/...` | requires `TRONSCAN_API_KEY` |
| Ethereum | Blockscout | `eth.blockscout.com/api/v2` | 200 — tx, token-transfers, internal-tx, address |
| Ethereum | Routescan | `api.routescan.io/v2/network/mainnet/evm/1/etherscan/api` | 200 txlist |
| Polygon | Blockscout | `polygon.blockscout.com/api/v2` | 200 — same shape as ETH |
| Polygon | JSON-RPC | `polygon.drpc.org` / `1rpc.io/matic` | 200 `eth_blockNumber` |
| BNB Smart Chain | JSON-RPC | `bsc-dataseed.binance.org` | 200 `eth_blockNumber` + `eth_getCode` |
| BNB Smart Chain | Blockscout | `bnb.blockscout.com` | **404 — does not exist** |
| BNB Smart Chain | Routescan | `evm/56/...` | **"chain not supported"** |
| BNB Smart Chain | bscscan | `api.bscscan.com` | **301 → Etherscan V2 migration page** |
| BNB Smart Chain | Etherscan V2 | `api.etherscan.io/v2?chainid=56` | **"Free API access is not supported for this chain"** |
| Bitcoin | Blockstream | `blockstream.info/api` | 200, tip 968513 |
| Bitcoin | mempool.space | `mempool.space/api` | 200, tip 968513 |

## Consequence: BSC has no keyless address-history provider

This is the single most important finding for the adapter layer, and it is a
real capability gap rather than a bug in the probe.

BSC is absent from every keyless explorer API available here:

- no Blockscout instance (`bnb.blockscout.com` is 404)
- Routescan explicitly answers `{"status":"0","message":"chain not supported"}`
- Etherscan V2 requires a paid plan for chain 56
- bscscan.com now redirects its whole API surface to the Etherscan V2 docs

Public JSON-RPC nodes work and `eth_getCode` is real, but an archival node is
needed to answer "which transactions touched this address" — public dataseed
nodes do not index by address. Building an address index client-side is out of
scope and would be unreliable.

**How the adapter handles it:** `EVMAdapter` for BSC reports the capability it
actually has. `get_outgoing_transfers` / `get_incoming_transfers` return an
explicit unavailable result; `get_network_status` still works over JSON-RPC and
returns a real block height. The UI must show BSC network status plus
"transaction history requires a configured `BSCSCAN_API_KEY`", never a
plausible-looking empty result.

With `BSCSCAN_API_KEY` set, BSC uses Etherscan V2, which serves all three EVM
chains from one key.

## Etherscan V2 covers all three EVM chains with one key

Confirmed against `api.etherscan.io/v2/api?chainid=...`:

- chainid 1 (Ethereum) and chainid 137 (Polygon): respond, but require a key
- chainid 56 (BSC): "Free API access is not supported for this chain"

So a single `ETHERSCAN_API_KEY` is the correct key to request for EVM coverage,
with BSC additionally needing a plan that includes chain 56.

## Routescan: Ethereum only

`evm/1` returns `status:1`. `evm/56` and `evm/137` both return "chain not
supported". An earlier probe in this project recorded 56/137 as working; they no
longer do, and the code must not be written against that earlier result.

## Blockscout carries public labels

`GET /api/v2/addresses/{hash}` returns `ens_domain_name`, `name`, `is_contract`,
`is_verified`, and `metadata.tags[]` sourced from the Open Labels Initiative.
This is the keyless entity-signal path for EVM chains, and it is a genuine
`PUBLIC_PROVIDER` tier attribution, not a curated fact.

## Bitcoin

`blockstream.info/api` and `mempool.space/api` are both Esplora, both keyless,
and returned byte-identical responses on every field probed — same tip, same
`chain_stats`, same vin/vout. Either can serve as primary; the other is the
fallback. Unlike BSC, **address history is keyless here**: the genesis address
returned 66,571 confirmed transactions and 79,687 UTXOs with no API key.

Two shape facts the adapter must handle, both confirmed live:

- `scriptpubkey` is a **string**, not an object
- a coinbase input has `prevout: null` and no `scriptpubkey_address`

## Blockscout field names (verified, not assumed)

The token-transfer list uses `transaction_hash`, **not** `tx_hash`, and the
amount lives in a nested object: `total: {value, decimals}`. Reading the wrong
hash key made every record fail validation, which silently reduced a
token-heavy address to its bare native-ETH history — the adapter looked healthy
and was quietly returning a fraction of the real picture. Timestamps are
ISO-8601 strings, not integers, so they need parsing rather than `int()`.

These are recorded here because each was a real defect caught by probing the
live API rather than by an error, and all three fail *silently* by returning
less data.

## Blockscout `/transactions` is not a transfer list

`.../addresses/{hash}/transactions` returns **every transaction the address
touched**, not only value movements. Most records on a busy contract are
contract calls. Verified live on `eth.blockscout.com`: five consecutive records
for a well-known address were all `type: 2` (contract call), `value: "0"`,
`token_transfers: []`, with calldata decoding to plain ASCII — `!AAA! ! open to
all bounty`, `@AM )(chain Attachment Message)`, and `setContenthash` with an
IPFS CID as input.

Treating those as transfers draws a value edge for a payment that never
happened, and lets a `large_transfer` indicator be scored against `0.0`. This is
the same defect as the TRON `TriggerSmartContract` case below: `to` is the
contract, not a recipient.

**Encoded as:** a record qualifies as value movement only if `value > 0` or
`token_transfers` is non-empty. A call that carries token transfers IS value
movement for the address and is kept.

## TRON: the parties are in `raw_data`, not at the top level

TronGrid's native-TRX endpoint (`/v1/accounts/{a}/transactions`) returns `from`
and `to` as keys that are **present but null**. The real parties are nested at
`raw_data.contract[0].parameter.value` as **21-byte hex**, and the amount is at
`value.amount` in SUN. A parser reading only the top level drops every record
and reports a busy account as empty, with no error anywhere.

**Encoded as:** `_normalize_trongrid_trx()` hex→Base58Check (version `0x41`),
and `/ 1_000_000` to TRX.

## TRON: TronScan names its fields differently

`TRONSCAN_TX_URL` uses `ownerAddress` / `toAddress` / `hash`, and the TRC-20
endpoint puts the timestamp in **`block_ts`** — not `block_timestamp`, not
`timestamp`. Reading the wrong names made every record return `None` and left
all TRC-20 timestamps `None`.

**Encoded as:** `_normalize_tronscan_trx()` and `block_ts` in the timestamp
field list.

## A keyed provider answering 200-with-empty masks a working one

With `TRONSCAN_API_KEY` set, TronScan returned HTTP 200 with **zero rows**, and
the adapter returned early on "success" — never falling through to keyless
TronGrid, which has the data. A configured-but-silent provider hid a working
one behind a clean "no history" answer.

**Encoded as:** the fetchers require a non-empty `records` list before
accepting a provider's result. A provider that answers successfully with
nothing falls through to the next one.

## Bitcoin Base58Check must actually be verified

`1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa` (genesis) and a TRON address are both
34-character base58 strings. Length and prefix alone cannot separate them, and
a Bitcoin address whose checksum was never verified produced a clean, entirely
fictional "no transactions found" for a mistyped address.

**Encoded as:** decode the base58, verify the double-SHA256 checksum, and read
the version byte — `0x00` mainnet P2PKH, `0x05` mainnet P2SH, `0x6F` testnet
P2PKH, `0xC4` testnet P2SH. When neither chain's checksum verifies, the
detector names the *intended* chain from the prefix so the user is told "you
mistyped a Bitcoin address" instead of "unrecognized".

## Bech32 needs the full HRP expansion and both checksum constants

A segwit validation that expands the HRP to only `[ord(c)>>5 …] + [0]` fails
for **every real address**; the low half `[ord(c)&31 …]` is required. Checking
only the Bech32 constant (`1`) also rejects every taproot address, which uses
Bech32m (`0x2BC830A3`). Witness program length must be decoded with a proper
5→8 bit regroup, and v0 is restricted to 20 or 32 bytes.

## Consequences encoded in the adapters

1. `TronAdapter` — TronScan when keyed, TronGrid keyless fallback. Full
   capability. Incoming transfers are now fetched, not just counted. Provider
   *reachability* is reported separately from *emptiness*, because "we asked
   and it has no history" and "we could not ask" are opposite findings.
2. `EVMAdapter` — Blockscout primary for ETH and Polygon (transfers, token
   transfers, internal transactions, address labels). Etherscan V2 when
   `ETHERSCAN_API_KEY` is set, which is the only way to get BSC. Zero-value
   contract calls are dropped rather than drawn as transfers.
3. BSC without a key is a documented, honest partial result.
4. `BitcoinAdapter` — Blockstream primary, mempool.space fallback. UTXO model:
   inputs and outputs, never account transfers.
5. All three promote a trace to `MATCHED` only on a `CURATED_VERIFIED`
   attribution. A block explorer's own label is `PUBLIC_PROVIDER` and is
   reported on the node, but it does not claim an entity was identified.
