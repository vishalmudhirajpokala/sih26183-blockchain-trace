import { useEffect, useRef, useState } from "react";
import axios from "axios";
import "./App.css";

const API_BASE_URL = (import.meta.env.VITE_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
const API_URL = `${API_BASE_URL}/trace`;
const REPORTS_BASE = `${API_BASE_URL}/reports`;

const RESULT_META = {
  exchange_identified: { label: "EXCHANGE IDENTIFIED", title: "Trace complete", tone: "green" },
  mixer_identified: { label: "MIXER DETECTED", title: "Trace halted", tone: "amber" },
  sanctioned: { label: "SANCTIONED ENTITY", title: "Immediate review", tone: "red" },
  sanctioned_delisted: { label: "PREVIOUSLY SANCTIONED", title: "Trace complete", tone: "amber" },
  high_risk_entity: { label: "HIGH-RISK ENTITY", title: "Trace complete", tone: "amber" },
  identified: { label: "ENTITY IDENTIFIED", title: "Trace complete", tone: "blue" },
  inconclusive: { label: "INCONCLUSIVE", title: "Insufficient evidence", tone: "slate" },
};

const LOADING_STEPS = ["Querying TRON mainnet", "Resolving transaction hops", "Matching entity intelligence", "Compiling investigation record"];
const DEMO_SCENARIOS = {
  exchange: { wallet_address: "TWd4WrZ9wn84f5x1hZhL4DHvk738ns5jwb", result: "exchange_identified", exchange_name: "Binance-Hot 7", confidence: 95, hop_path: ["TWd4WrZ9wn84f5x1hZhL4DHvk738ns5jwb", "TDqSquXBgUCLYvYC4XZgrprLK589dkhSCf"], hops: 1, token: "BTT", amount: "7,529,940,740,670.348", from_address: "TWd4WrZ9wn84f5x1hZhL4DHvk738ns5jwb", to_address: "TDqSquXBgUCLYvYC4XZgrprLK589dkhSCf", contract_address: "TAFjULxiVgT4qWk6UZwjqwZXTSaGaqnVp4", transaction_hash: "1d6775f27c7c18b847e813cd12f6be9d931d6b67669b79ff142d6f153300ba29", transaction_id: "1d6775f27c7c18b847e813cd12f6be9d931d6b67669b79ff142d6f153300ba29", block_number: 85920008, fan_in: true, fan_out: false, rapid_hops: false, high_risk_entity: false, risk_score: 25, risk_level: "MEDIUM", risk_indicators: ["Funds reached a known cryptocurrency exchange", "Funds from multiple wallets were consolidated", "Unusually large token transfer detected"], risk_assessment: "Some risk indicators were detected. Additional transaction analysis is recommended.", report: "reports/trace_report.pdf" },
  mixer: { wallet_address: "TXaMpLeMixerWalletDemoAddress0001", result: "mixer_identified", exchange_name: null, confidence: 90, hop_path: ["TXaMpLeMixerWalletDemoAddress0001", "TIntermediateHopDemoAddress00002", "TMixerContractDemoAddress000003"], hops: 2, token: "USDT", amount: "18,400.00", from_address: "TXaMpLeMixerWalletDemoAddress0001", to_address: "TMixerContractDemoAddress000003", contract_address: null, transaction_hash: null, transaction_id: null, block_number: null, fan_out: true, fan_in: false, rapid_hops: true, high_risk_entity: false, risk_score: 68, risk_level: "HIGH", risk_indicators: ["Rapid successive transfers observed", "Funds dispersed to multiple wallets"], risk_assessment: "Trace halted at a known mixer contract interaction.", report: "reports/trace_report.pdf" },
  inconclusive: { wallet_address: "TUnknownDestinationDemoAddress009", result: "inconclusive", exchange_name: null, confidence: 0, hop_path: ["TUnknownDestinationDemoAddress009"], hops: 0, token: null, amount: null, from_address: "TUnknownDestinationDemoAddress009", to_address: null, contract_address: null, transaction_hash: null, transaction_id: null, block_number: null, risk_score: 10, risk_level: "LOW", risk_indicators: [], risk_assessment: "No reliable destination could be established from the available transaction data.", report: "reports/trace_report.pdf" },
};

function isValidTronAddress(addr) {
  return /^T[a-zA-Z0-9]{33}$/.test(addr.trim());
}
function reportUrlFromPath(path) { if (!path) return null; if (/^https?:\/\//i.test(path)) return path; const filename = String(path).replace(/\\/g, "/").split("/").pop(); return filename ? `${REPORTS_BASE}/${encodeURIComponent(filename)}` : null; }
function newCaseId() { return `CASE-${Date.now().toString().slice(-6)}`; }
function shorten(value = "", start = 8, end = 7) { return value.length > start + end + 3 ? `${value.slice(0, start)}…${value.slice(-end)}` : value; }

function CopyButton({ text }) {
  const [copied, setCopied] = useState(false);
  return <button className="copy-button" type="button" onClick={async () => { try { await navigator.clipboard?.writeText(text); setCopied(true); window.setTimeout(() => setCopied(false), 1200); } catch { setCopied(false); } }}>{copied ? "Copied" : "Copy"}</button>;
}
function Dot({ tone = "green" }) { return <span className={`dot dot-${tone}`} aria-hidden="true" />; }
function Badge({ children, tone = "slate" }) { return <span className={`badge badge-${tone}`}>{children}</span>; }
function Spinner() { return <span className="spinner" aria-hidden="true" />; }
function Panel({ eyebrow, title, action, children, className = "" }) { return <section className={`panel ${className}`}><div className="panel-heading"><div><div className="panel-eyebrow">{eyebrow}</div><h2>{title}</h2></div>{action}</div>{children}</section>; }
function DataRow({ label, value, copy = false, muted = false }) { return <div className="data-row"><span className="data-label">{label}</span><span className={`data-value ${muted ? "muted" : ""}`}>{value || "—"}{copy && value ? <CopyButton text={value} /> : null}</span></div>; }

function Notice({ result, meta }) {
  const messages = {
    exchange_identified: <>Funds reached a wallet publicly identified as <strong>{result.exchange_name || "a known exchange"}</strong>. This establishes where funds arrived, not intent or criminal activity.</>,
    mixer_identified: <>Automated tracing halted at a wallet associated with known mixing activity. Destination beyond this point cannot be determined through automated on-chain analysis.</>,
    sanctioned: <>Funds reached a wallet identified on a sanctions list. This is an investigative finding, not automatic proof of wrongdoing by the wallet owner.</>,
    sanctioned_delisted: <>Funds reached a wallet previously flagged on a sanctions list but since delisted.</>,
    high_risk_entity: <>The destination matches a publicly tagged high-risk entity. This is an intelligence indicator, not proof of criminal activity.</>,
    identified: <>The destination wallet matches a publicly tagged entity.</>,
    inconclusive: <>Available on-chain data was insufficient to establish a reliable known destination.</>,
  };
  return <div className={`notice notice-${meta.tone}`}><span className="notice-mark">!</span><p>{messages[result.result] || messages.identified}</p></div>;
}

function ResultView({ result, meta, onDownload }) {
  const path = result.hop_path || [result.from_address, result.to_address].filter(Boolean);
  return <div className="results-grid">
    <Panel eyebrow="Trace outcome" title={meta.title} action={<Badge tone={meta.tone}>{meta.label}</Badge>} className="outcome-panel">
      <Notice result={result} meta={meta} />
      <div className="outcome-summary"><div className="summary-value">{result.confidence ?? 0}<span>%</span></div><div><div className="summary-label">CONFIDENCE</div><div className="summary-copy">Based on available on-chain evidence</div></div></div>
      <div className="confidence-track"><span style={{ width: `${Math.min(100, Math.max(0, result.confidence || 0))}%` }} /></div>
      <div className="metric-strip"><div><span>HOPS</span><strong>{result.hops ?? path.length - 1}</strong></div><div><span>RISK SCORE</span><strong>{result.risk_score ?? 0}</strong></div><div><span>RISK LEVEL</span><strong className={`risk-${String(result.risk_level || "low").toLowerCase()}`}>{result.risk_level || "UNKNOWN"}</strong></div></div>
    </Panel>
    <Panel eyebrow="Transaction path" title="Fund flow" action={<span className="panel-count">{path.length} nodes</span>} className="flow-panel">
      <div className="flow-list">{path.map((node, index) => <div className="flow-node" key={`${node}-${index}`}><div className="node-marker">{index === path.length - 1 ? "↗" : index + 1}</div><div className="node-copy"><span className="node-kind">{index === 0 ? "SOURCE WALLET" : index === path.length - 1 ? "DESTINATION" : `HOP ${index}`}</span><strong>{shorten(node, 14, 12)}</strong><small>{node}</small></div>{index < path.length - 1 && <div className="flow-line" />}</div>)}</div>
    </Panel>
    <Panel eyebrow="Trace metadata" title="Transaction details" className="details-panel"><div className="data-grid"><DataRow label="Token" value={result.token} /><DataRow label="Amount" value={result.amount} /><DataRow label="Block" value={result.block_number} /><DataRow label="Entity" value={result.exchange_name} /><DataRow label="Transaction ID" value={result.transaction_id || result.transaction_hash} copy /><DataRow label="Contract" value={result.contract_address} copy /></div></Panel>
    <Panel eyebrow="Analytical signals" title="Risk indicators" action={<Badge tone={String(result.risk_level || "slate").toLowerCase()}>{result.risk_level || "UNASSESSED"}</Badge>} className="signals-panel"><p className="assessment">{result.risk_assessment || "No additional risk assessment was returned."}</p>{result.risk_indicators?.length ? <ul className="signal-list">{result.risk_indicators.map((item) => <li key={item}><Dot tone="red" />{item}</li>)}</ul> : <div className="empty-signals"><Dot tone="green" />No additional indicators detected</div>}</Panel>
    <Panel eyebrow="Case file" title="Preserve this investigation" action={reportUrlFromPath(result.report) && <button className="outline-button" type="button" onClick={onDownload}>Download report</button>} className="case-panel"><div className="case-file"><div><span className="case-label">CASE ID</span><strong>{result.case_id || "Generated on export"}</strong></div><div><span className="case-label">NETWORK</span><strong>TRON mainnet</strong></div><div><span className="case-label">SOURCE</span><strong>BlockTrace automated analysis</strong></div></div></Panel>
  </div>;
}

export default function App() {
  const [address, setAddress] = useState(""); const [status, setStatus] = useState("idle"); const [result, setResult] = useState(null); const [errorMsg, setErrorMsg] = useState(""); const [caseId, setCaseId] = useState(null); const [demoMode, setDemoMode] = useState(false); const [demoScenario, setDemoScenario] = useState("exchange"); const [history, setHistory] = useState([]); const [loadingStep, setLoadingStep] = useState(0); const timerRef = useRef(null); const demoTimerRef = useRef(null);
  useEffect(() => () => { clearInterval(timerRef.current); clearInterval(demoTimerRef.current); }, []);
  function finishWith(data) { const id = newCaseId(); setCaseId(id); setResult({ ...data, case_id: id }); setStatus("done"); setHistory((current) => [{ id, address: data.wallet_address, meta: RESULT_META[data.result] || RESULT_META.identified }, ...current].slice(0, 6)); }
  async function handleTrace() { const trimmed = address.trim(); if (demoMode) { setStatus("loading"); setErrorMsg(""); setResult(null); setLoadingStep(0); clearInterval(demoTimerRef.current); demoTimerRef.current = setInterval(() => setLoadingStep((current) => Math.min(current + 1, LOADING_STEPS.length - 1)), 350); window.setTimeout(() => { clearInterval(demoTimerRef.current); finishWith(DEMO_SCENARIOS[demoScenario]); }, 1600); return; } if (!trimmed) { setErrorMsg("Enter a TRON wallet address to begin."); setStatus("error"); return; } if (!isValidTronAddress(trimmed)) { setErrorMsg("Invalid TRON wallet address. TRON addresses begin with T and contain 34 characters."); setStatus("error"); return; } setStatus("loading"); setErrorMsg(""); setResult(null); setLoadingStep(0); clearInterval(timerRef.current); timerRef.current = setInterval(() => setLoadingStep((current) => Math.min(current + 1, LOADING_STEPS.length - 1)), 900); try { const response = await axios.post(API_URL, { address: trimmed }, { timeout: 120000 }); clearInterval(timerRef.current); finishWith(response.data); } catch (error) { clearInterval(timerRef.current); setErrorMsg(error.code === "ECONNABORTED" ? "The investigation timed out. Please retry." : error.response?.data?.detail || (error.response ? "The investigation service returned an error." : "Unable to connect to the investigation service.")); setStatus("error"); } }
  function handleNewCase() { setAddress(""); setResult(null); setStatus("idle"); setErrorMsg(""); setCaseId(null); }
  function handleHistorySelect(item) { setAddress(item.address); setResult(null); setStatus("idle"); setErrorMsg(""); setCaseId(item.id); }
  const meta = result ? RESULT_META[result.result] || RESULT_META.identified : null; const hasResult = status === "done" && Boolean(result);
  return <div className="app-shell">
    <aside className="sidebar"><div className="brand"><div className="brand-mark">BT</div><div><div className="brand-name">BlockTrace</div><div className="brand-sub">Investigation console</div></div></div><button className="new-case-button" type="button" onClick={handleNewCase}><span>+</span> New investigation</button><div className="sidebar-rule" /><div className="sidebar-label">CURRENT CASE</div><div className={`active-case ${status !== "idle" ? "active" : ""}`}><Dot tone={status === "loading" ? "slate" : hasResult ? meta.tone : "slate"} /><div><strong>{caseId || "No active case"}</strong><span>{status === "loading" ? "Tracing…" : hasResult ? meta.label : "Ready to begin"}</span></div></div>{history.length > 1 && <><div className="sidebar-label recent-label">RECENT CASES</div><div className="history-list">{history.slice(1).map((item) => <button className="history-item" type="button" key={item.id} onClick={() => handleHistorySelect(item)}><strong>{item.id}</strong><span>{shorten(item.address, 10, 8)}</span></button>)}</div></>}<div className="sidebar-spacer" /><div className="network-card"><div><span>NETWORK</span><strong><Dot /> TRON</strong></div><div><span>DATA SOURCE</span><strong>Live intelligence</strong></div></div><div className="demo-controls"><label><input type="checkbox" checked={demoMode} onChange={(event) => setDemoMode(event.target.checked)} /> Demonstration mode</label>{demoMode && <select value={demoScenario} onChange={(event) => setDemoScenario(event.target.value)}><option value="exchange">Exchange identified</option><option value="mixer">Trail obscured</option><option value="inconclusive">Inconclusive trace</option></select>}</div></aside>
    <div className="main-area"><header className="topbar"><div><span className="topbar-section">INVESTIGATION</span>{caseId && <><span className="topbar-divider">/</span><span className="topbar-case">{caseId}</span></>}</div><div className="live-indicator"><Dot /> TRON NETWORK <span>LIVE</span></div></header><main className="workspace"><div className="workspace-inner"><div className="page-intro"><div className="intro-line"><span>BLOCKCHAIN INVESTIGATION</span><span>TRON / PUBLIC LEDGER</span></div><h1>Trace where the money went.</h1><p>Follow available cryptocurrency flows, identify known destination entities, and preserve the investigative trail.</p></div><Panel eyebrow="Start an investigation" title="TRON wallet address" action={<span className="input-hint">Press Enter to trace</span>} className="trace-panel"><div className="trace-form"><div className="input-wrap"><input value={address} onChange={(event) => setAddress(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.nativeEvent.isComposing && event.keyCode !== 229 && status !== "loading") handleTrace(); }} placeholder={demoMode ? "Demonstration mode — validation bypassed" : "T… enter a 34-character wallet address"} disabled={status === "loading"} spellCheck="false" aria-label="TRON wallet address" /><div className="input-footer"><span><Dot /> TRON mainnet</span><span>Wallet addresses are public</span></div></div><button className="trace-button" type="button" disabled={status === "loading"} onClick={handleTrace}>{status === "loading" ? <><Spinner /> Tracing</> : <>Trace funds <span>→</span></>}</button></div>{status === "loading" && <div className="loading-state"><div className="loading-header"><span><Spinner /> Investigation in progress</span><span>{Math.min(loadingStep + 1, LOADING_STEPS.length)} / {LOADING_STEPS.length}</span></div><div className="loading-steps">{LOADING_STEPS.map((step, index) => <div className={index <= loadingStep ? "complete" : ""} key={step}><span>{index < loadingStep ? "✓" : index === loadingStep ? <Spinner /> : "·"}</span>{step}</div>)}</div></div>}{status === "error" && <div className="error-state" role="alert"><span>!</span>{errorMsg}</div>}</Panel>{hasResult && <ResultView result={result} meta={meta} onDownload={() => { const url = reportUrlFromPath(result.report); if (url) window.open(url, "_blank", "noopener,noreferrer"); }} />}{status === "idle" && <div className="empty-workspace"><div className="empty-icon">⌁</div><h2>Ready for analysis</h2><p>Enter a TRON wallet address above to begin tracing funds across the public ledger.</p></div>}</div></main><footer className="footer"><span>BlockTrace / Investigation console</span><span>Automated analysis is informational and requires human review.</span></footer></div>
  </div>;
}
