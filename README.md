# BlockTrace

Real-time crypto fraud attribution for victim-reported wallet addresses. Given an
address a victim was told to send funds to, BlockTrace traces the value outward
across five blockchains, works out which addresses behave like collection
wallets, exchanges or cash-out points, scores the wallet against explainable
risk rules, and produces a forensic PDF report an investigator can file.

Every claim it makes is traceable to a provider response. Where it could not
establish something, it says so instead of filling the gap.

**Live demo:** https://sih26183-blockchain-trace.vercel.app
**API:** `https://sih26183-api.onrender.com` — OpenAPI docs at `/docs`

---

## Supported chains

| Chain | Provider | Status |
|---|---|---|
| TRON | TronScan / TronGrid | Working |
| Ethereum | Blockscout, Etherscan fallback | Working |
| Polygon | Blockscout | Working |
| Bitcoin | mempool.space | Working |
| BSC (BNB Smart Chain) | Etherscan only | **Requires `ETHERSCAN_API_KEY`.** No keyless provider indexes BscScan address history, so without the key BSC traces return `inconclusive` with that reason. |

Five chains are registered. Four trace with no credentials at all.

---

## Running it locally

Two processes: a FastAPI backend and a Vite frontend. You need **both** — the
frontend is a static bundle and holds no data of its own.

### 1. Backend (port 8000)

```bash
cd backend
pip install -r requirements.txt
python -m uvicorn main:app --reload --port 8000
```

Check it: `http://127.0.0.1:8000/health`

### 2. Frontend (port 5173)

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. The landing page is public; `/app` is the working
surface.

> Use port **5173**. Google OAuth redirects to `http://localhost:5173/login`
> exactly, and a different port fails with an invalid-redirect error.

---

## Environment variables

Both `.env` files are gitignored. Nothing here is required to start.

### `backend/.env` — all optional

| Variable | Effect if absent |
|---|---|
| `TRONSCAN_API_KEY` | Falls back to TronGrid. Rate limits are tighter. |
| `TRONGRID_API_KEY` | Unkeyed TronGrid. Works, lower rate limit. |
| `ETHERSCAN_API_KEY` | **BSC becomes untraceable.** Ethereum and Polygon still work via Blockscout. |
| `SUPABASE_URL` + `SUPABASE_ANON_KEY` | **Google sign-in is hidden.** The app runs in open demo mode. |
| `BLOCKTRACE_ALERT_WEBHOOK` | Alerts are computed and returned in the API response but nothing is delivered. |
| `BLOCKTRACE_DEMO_MODE` | Defaults to `true`. Set `false` to require sign-in. |
| `BLOCKTRACE_MAX_DEPTH` / `_MAX_NODES` / `_MAX_TXS_PER_NODE` / `_TRACE_DEADLINE` | Defaults: 3 / 25 / 5 / 90s. |
| `BLOCKTRACE_ENTITY_DB` | Path to the curated VASP registry. Unset or empty means no curated names — see Limitations. |

### `frontend/.env`

| Variable | Effect if absent |
|---|---|
| `VITE_API_URL` | **Defaults to `http://127.0.0.1:8000`.** A deployed frontend with this unset calls the *visitor's own* localhost and silently does nothing. Set it to your API host. |
| `VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY` | Google sign-in button is hidden. |

Vite reads `VITE_*` **at startup only**. Edit the file, then restart the dev
server. A page refresh will not pick up a change.

---

## Tests

```bash
cd backend
python tests/roundtrip.py                      # serialization is lossless
BLOCKTRACE_E2E=0 python tests/routes.py        # route + report contract suite
BLOCKTRACE_E2E=1 python tests/e2e_http.py      # live trace against real providers

cd ../frontend
npm run lint && npm run build
```

On PowerShell, set the variable first:

```powershell
cd backend
$env:BLOCKTRACE_E2E="0"; python tests/routes.py
$env:BLOCKTRACE_E2E="1"; python tests/e2e_http.py
```

`tests/e2e_http.py` runs a real trace against real providers and costs a few
seconds of provider quota. `tests/routes.py` is offline except for one stored
investigation, which it needs in order to render a report.

`routes.py` asserts the report section order, that the risk score is never shown
without its triage disclaimer, that a counterparty attribution is never
presented as the traced subject's destination, and that token identity
resolution refuses to display a spoofed symbol as the real asset.

---

## Known limitations

Written plainly, because a judge reading this should get an accurate picture
rather than a sales pitch.

**VASP identification is the headline feature and it is only partial.**
BlockTrace can *locate* addresses that behave like a collection wallet or a
cash-out point, from observed flow alone. It can *name* an operator when a public
block explorer happens to carry a label, and that happens intermittently. It
**cannot reliably name the VASP**, because the curated VASP registry
(`curated_vasp_tier`) is **empty**. The loading mechanism exists and reports
itself as unpopulated rather than pretending otherwise. Populating it requires
a licensed dataset from TRM, Chainalysis or Arkham. We have not fabricated
entries: a wrongly-labelled address is what freezes an innocent party's funds,
so a guessed label is worse than no label.

**Not built:** wallet clustering, ML-based risk detection, and a
self-operated blockchain indexer. These were scoped out deliberately rather than
half-built. Risk scoring is a transparent rule engine, not a learned model, and
all data is fetched live from public providers rather than indexed locally.

**"Real-time" is generous.** A bounded trace takes 45–90 seconds depending on
chain depth and provider latency. The default budget is 90s; a deeper
investigation will hit it and return `timeout`, which is reported honestly
rather than being presented as a partial success.

**Cross-chain is chain *selection*, not chain *linking*.** An ambiguous EVM
address is resolved to one network from provider evidence and the operator is
asked to choose when it is genuinely ambiguous. BlockTrace does not yet track
the same entity as it moves between chains via a bridge.

**Intermediary detection is heuristic.** The collector / distributor / relay
classification is derived from transfer counts and directions in the retrieved
data. It is reproducible and it names nobody, but it is a shape, not proof of
laundering. It is recorded at the `heuristic` provenance tier and cannot be
promoted to a curated finding.

**Production caveats.** The deployed backend stores investigations in a local
JSON file, so saved cases do not survive a redeploy. And the deployed frontend
and backend must be configured together — a missing `VITE_API_URL` produces a
page that loads and then does nothing.

**Entity labels are usually unverified.** Most names come from public block
explorers at 70% confidence and are labelled `unverified` throughout the UI and
the report. BlockTrace distinguishes what a provider *said* from what a curated
database *claims*, and never blurs the two.
