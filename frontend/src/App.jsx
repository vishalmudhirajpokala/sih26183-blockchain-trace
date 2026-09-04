import { useRef, useState } from "react";
import axios from "axios";

/* =========================================================
   API CONFIG
   ========================================================= */

const API_BASE_URL = (
  import.meta.env.VITE_API_URL ||
  "http://127.0.0.1:8000"
).replace(/\/$/, "");

const API_URL = `${API_BASE_URL}/trace`;
const REPORTS_BASE = `${API_BASE_URL}/reports`;

/* =========================================================
   RESULT METADATA
   ========================================================= */

const RESULT_META = {
  exchange_identified: {
    heading: "Trace Complete",
    sub: "Exchange Identified",
    tone: "green",
  },
  mixer_identified: {
    heading: "Trace Halted",
    sub: "Trail Obscured — Mixer Detected",
    tone: "amber",
  },
  sanctioned: {
    heading: "Trace Complete",
    sub: "Sanctioned Entity Identified",
    tone: "red",
  },
  sanctioned_delisted: {
    heading: "Trace Complete",
    sub: "Previously Sanctioned Entity",
    tone: "amber",
  },
  high_risk_entity: {
    heading: "Trace Complete",
    sub: "High-Risk Entity Identified",
    tone: "amber",
  },
  identified: {
    heading: "Trace Complete",
    sub: "Entity Identified",
    tone: "blue",
  },
  inconclusive: {
    heading: "Trace Inconclusive",
    sub: "Insufficient Data to Establish Destination",
    tone: "slate",
  },
};

/* =========================================================
   INVESTIGATION NOTICES
   ========================================================= */

const NOTICE_TEXT = {
  exchange_identified: (r) =>
    `Funds were traced through the available transaction path and reached a wallet publicly identified as belonging to ${
      r.exchange_name || "a known exchange"
    }. This identifies where funds arrived — it does not establish intent or constitute evidence of criminal activity.`,

  mixer_identified: () =>
    "Automated tracing was halted at a wallet associated with known mixing activity. Destination beyond this point cannot be determined through automated on-chain analysis.",

  sanctioned: (r) =>
    `Funds reached a wallet identified on a sanctions list${
      r.exchange_name ? ` (${r.exchange_name})` : ""
    }. This is an important investigative finding, but it is not automatic proof of wrongdoing by the wallet owner.`,

  sanctioned_delisted: () =>
    "Funds reached a wallet that was previously flagged on a sanctions list but has since been delisted.",

  high_risk_entity: () =>
    "The destination matches a publicly tagged high-risk entity. This is an intelligence indicator, not proof of criminal activity.",

  identified: () =>
    "The destination wallet matches a publicly tagged entity.",

  inconclusive: () =>
    "Available on-chain transaction data was insufficient to establish a reliable known destination. Automated identification could not reach a confident conclusion.",
};

/* =========================================================
   LOADING
   ========================================================= */

const LOADING_STEPS = [
  "Querying TRON network…",
  "Resolving transaction hops…",
  "Matching entity intelligence…",
  "Compiling investigation record…",
];

/* =========================================================
   DEMO DATA
   ========================================================= */

const DEMO_SCENARIOS = {
  exchange: {
    wallet_address: "TWd4WrZ9wn84f5x1hZhL4DHvk738ns5jwb",
    result: "exchange_identified",
    exchange_name: "Binance-Hot 7",
    confidence: 95,
    hop_path: [
      "TWd4WrZ9wn84f5x1hZhL4DHvk738ns5jwb",
      "TDqSquXBgUCLYvYC4XZgrprLK589dkhSCf",
    ],
    hops: 1,
    token: "BTT",
    amount: "7,529,940,740,670.348",
    from_address: "TWd4WrZ9wn84f5x1hZhL4DHvk738ns5jwb",
    to_address: "TDqSquXBgUCLYvYC4XZgrprLK589dkhSCf",
    contract_address: "TAFjULxiVgT4qWk6UZwjqwZXTSaGaqnVp4",
    transaction_hash:
      "1d6775f27c7c18b847e813cd12f6be9d931d6b67669b79ff142d6f153300ba29",
    transaction_id:
      "1d6775f27c7c18b847e813cd12f6be9d931d6b67669b79ff142d6f153300ba29",
    block_number: 85920008,
    fan_in: true,
    fan_out: false,
    rapid_hops: false,
    high_risk_entity: false,
    risk_score: 25,
    risk_level: "MEDIUM",
    risk_indicators: [
      "Funds reached a known cryptocurrency exchange",
      "Funds from multiple wallets were consolidated",
      "Unusually large token transfer detected",
    ],
    risk_assessment:
      "Some risk indicators were detected. Additional transaction analysis is recommended.",
    report: "reports/trace_report.pdf",
  },

  mixer: {
    wallet_address: "TXaMpLeMixerWalletDemoAddress0001",
    result: "mixer_identified",
    exchange_name: null,
    confidence: 90,
    hop_path: [
      "TXaMpLeMixerWalletDemoAddress0001",
      "TIntermediateHopDemoAddress00002",
      "TMixerContractDemoAddress000003",
    ],
    hops: 2,
    token: "USDT",
    amount: "18,400.00",
    from_address: "TXaMpLeMixerWalletDemoAddress0001",
    to_address: "TMixerContractDemoAddress000003",
    contract_address: null,
    transaction_hash: null,
    transaction_id: null,
    block_number: null,
    fan_out: true,
    fan_in: false,
    rapid_hops: true,
    high_risk_entity: false,
    risk_score: 68,
    risk_level: "HIGH",
    risk_indicators: [
      "Rapid successive transfers observed",
      "Funds dispersed to multiple wallets",
    ],
    risk_assessment:
      "Trace halted at a known mixer contract interaction.",
    report: "reports/trace_report.pdf",
  },

  inconclusive: {
    wallet_address: "TUnknownDestinationDemoAddress009",
    result: "inconclusive",
    exchange_name: null,
    confidence: 0,
    hop_path: ["TUnknownDestinationDemoAddress009"],
    hops: 0,
    token: null,
    amount: null,
    from_address: "TUnknownDestinationDemoAddress009",
    to_address: null,
    contract_address: null,
    transaction_hash: null,
    transaction_id: null,
    block_number: null,
    risk_score: 10,
    risk_level: "LOW",
    risk_indicators: [],
    risk_assessment:
      "No reliable destination could be established from the available transaction data.",
    report: "reports/trace_report.pdf",
  },
};

/* =========================================================
   HELPERS
   ========================================================= */

function isValidTronAddress(addr) {
  return /^T[a-zA-Z0-9]{33}$/.test(addr.trim());
}

function reportUrlFromPath(path) {
  if (!path) return null;

  if (/^https?:\/\//i.test(path)) {
    return path;
  }

  const normalized = String(path).replace(/\\/g, "/");
  const filename = normalized.split("/").pop();

  if (!filename) return null;

  return `${REPORTS_BASE}/${encodeURIComponent(filename)}`;
}

function newCaseId() {
  return `CASE-${Date.now().toString().slice(-6)}`;
}

/* =========================================================
   SMALL UI COMPONENTS
   ========================================================= */

function CopyButton({ text }) {
  const [copied, setCopied] = useState(false);

  async function copyText() {
    try {
      await navigator.clipboard?.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch {
      setCopied(false);
    }
  }

  return (
    <button
      className="copy-btn"
      type="button"
      title="Copy"
      onClick={copyText}
    >
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

function StatusDot({ tone = "green" }) {
  return <span className={`status-dot dot-${tone}`} />;
}

function Chip({ tone = "slate", children }) {
  return <span className={`chip chip-${tone}`}>{children}</span>;
}

function Spinner() {
  return <span className="spinner" aria-hidden="true" />;
}

function Card({ title, right, children, className = "" }) {
  return (
    <section className={`card ${className}`}>
      <div className="card-header">
        <div className="card-title">{title}</div>
        {right && <div className="card-header-right">{right}</div>}
      </div>

      <div className="card-body">{children}</div>
    </section>
  );
}

function ConfidenceBar({ value = 0, tone = "blue" }) {
  return (
    <div className="confidence-wrap">
      <div className="confidence-track">
        <div
          className={`confidence-fill fill-${tone}`}
          style={{ width: `${Math.min(100, Math.max(0, value))}%` }}
        />
      </div>
    </div>
  );
}

/* =========================================================
   APP
   ========================================================= */

export default function App() {
  const [address, setAddress] = useState("");
  const [status, setStatus] = useState("idle");
  const [result, setResult] = useState(null);
  const [errorMsg, setErrorMsg] = useState("");
  const [caseId, setCaseId] = useState(null);

  const [demoMode, setDemoMode] = useState(false);
  const [demoScenario, setDemoScenario] = useState("exchange");

  const [history, setHistory] = useState([]);
  const [loadingStep, setLoadingStep] = useState(0);

  const timerRef = useRef(null);
  const demoTimerRef = useRef(null);

  function finishWith(data) {
    const id = newCaseId();

    setCaseId(id);
    setResult(data);
    setStatus("done");

    setHistory((current) =>
      [
        {
          id,
          address: data.wallet_address,
          meta:
            RESULT_META[data.result] ||
            RESULT_META.identified,
        },
        ...current,
      ].slice(0, 6)
    );
  }

  async function handleTrace() {
    const trimmed = address.trim();

    if (demoMode) {
      setStatus("loading");
      setErrorMsg("");
      setResult(null);
      setLoadingStep(0);

      clearInterval(demoTimerRef.current);

      demoTimerRef.current = setInterval(() => {
        setLoadingStep((current) =>
          current < LOADING_STEPS.length - 1
            ? current + 1
            : current
        );
      }, 350);

      setTimeout(() => {
        clearInterval(demoTimerRef.current);
        finishWith(DEMO_SCENARIOS[demoScenario]);
      }, 1600);

      return;
    }

    if (!trimmed) {
      setErrorMsg("Enter a TRON wallet address to begin.");
      setStatus("error");
      return;
    }

    if (!isValidTronAddress(trimmed)) {
      setErrorMsg("Invalid TRON wallet address.");
      setStatus("error");
      return;
    }

    setStatus("loading");
    setErrorMsg("");
    setResult(null);
    setLoadingStep(0);

    clearInterval(timerRef.current);

    timerRef.current = setInterval(() => {
      setLoadingStep((current) =>
        current < LOADING_STEPS.length - 1
          ? current + 1
          : current
      );
    }, 900);

    try {
      const response = await axios.post(
        API_URL,
        { address: trimmed },
        { timeout: 120000 }
      );

      clearInterval(timerRef.current);
      finishWith(response.data);
    } catch (error) {
      clearInterval(timerRef.current);

      if (error.code === "ECONNABORTED") {
        setErrorMsg(
          "The investigation timed out. Please retry."
        );
      } else if (error.response) {
        setErrorMsg(
          error.response.data?.detail ||
            "The investigation service returned an error."
        );
      } else {
        setErrorMsg(
          "Unable to connect to the investigation service."
        );
      }

      setStatus("error");
    }
  }

  function handleNewCase() {
    setAddress("");
    setResult(null);
    setStatus("idle");
    setErrorMsg("");
    setCaseId(null);
  }

  function handleHistorySelect(item) {
    setAddress(item.address);
    setResult(null);
    setStatus("idle");
    setErrorMsg("");
    setCaseId(item.id);
  }

  function handleDownloadReport() {
    const url = reportUrlFromPath(result?.report);

    if (!url) return;

    window.open(
      url,
      "_blank",
      "noopener,noreferrer"
    );
  }

  const meta = result
    ? RESULT_META[result.result] ||
      RESULT_META.identified
    : null;

  const noticeFn = result
    ? NOTICE_TEXT[result.result] ||
      NOTICE_TEXT.identified
    : null;

  const hasResult =
    status === "done" && Boolean(result);

  return (
    <div className="app-shell">
      <style>{STYLES}</style>

      {/* =====================================================
          SIDEBAR
      ===================================================== */}

      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">
            BT
          </div>

          <div>
            <div className="brand-name">
              BlockTrace
            </div>

            <div className="brand-sub">
              Investigation Console
            </div>
          </div>
        </div>

        <button
          className="new-case-btn"
          onClick={handleNewCase}
        >
          <span className="plus">+</span>
          <span>New Investigation</span>
        </button>

        <div className="sidebar-divider" />

        <div className="sidebar-section-label">
          CURRENT CASE
        </div>

        <div
          className={`sidebar-case ${
            status !== "idle" ? "selected" : ""
          }`}
        >
          <StatusDot
            tone={
              status === "loading"
                ? "slate"
                : hasResult
                ? "green"
                : "slate"
            }
          />

          <div className="sidebar-case-copy">
            <div className="sidebar-case-id">
              {caseId || "No active case"}
            </div>

            <div className="sidebar-case-status">
              {status === "loading"
                ? "Tracing…"
                : hasResult
                ? meta?.heading
                : "Ready"}
            </div>
          </div>
        </div>

        {history.length > 1 && (
          <>
            <div className="sidebar-section-label previous-label">
              RECENT CASES
            </div>

            <div className="history-list">
              {history.slice(1).map((item) => (
                <button
                  key={item.id}
                  className="history-item"
                  onClick={() =>
                    handleHistorySelect(item)
                  }
                >
                  <span className="history-id">
                    {item.id}
                  </span>

                  <span className="history-address">
                    {item.address}
                  </span>
                </button>
              ))}
            </div>
          </>
        )}

        <div className="sidebar-spacer" />

        <div className="system-box">
          <div className="system-row">
            <span className="system-label">
              NETWORK
            </span>

            <span className="system-value">
              <StatusDot tone="green" />
              TRON
            </span>
          </div>

          <div className="system-row">
            <span className="system-label">
              DATA
            </span>

            <span className="system-value">
              Live
            </span>
          </div>
        </div>

        <div className="demo-area">
          <label className="demo-label">
            <input
              type="checkbox"
              checked={demoMode}
              onChange={(event) =>
                setDemoMode(event.target.checked)
              }
            />

            <span>Demonstration mode</span>
          </label>

          {demoMode && (
            <select
              value={demoScenario}
              onChange={(event) =>
                setDemoScenario(event.target.value)
              }
              className="demo-select"
            >
              <option value="exchange">
                Exchange identified
              </option>

              <option value="mixer">
                Trail obscured
              </option>

              <option value="inconclusive">
                Inconclusive
              </option>
            </select>
          )}
        </div>
      </aside>

      {/* =====================================================
          MAIN AREA
      ===================================================== */}

      <div className="main-area">
        {/* Top bar */}

        <header className="topbar">
          <div className="topbar-left">
            <span className="topbar-section">
              INVESTIGATION
            </span>

            {caseId && (
              <>
                <span className="topbar-slash">/</span>

                <span className="topbar-case">
                  {caseId}
                </span>
              </>
            )}
          </div>

          <div className="topbar-right">
            <div className="live-status">
              <StatusDot tone="green" />
              <span>TRON NETWORK</span>
              <span className="live-text">
                LIVE
              </span>
            </div>
          </div>
        </header>

        {/* Workspace */}

        <main className="workspace">
          <div className="workspace-inner">
            {/* =================================================
                INTRO
            ================================================= */}

            <div className="intro">
              <div className="intro-kicker">
                BLOCKCHAIN INVESTIGATION
              </div>

              <h1>
                Trace where the money went.
              </h1>

              <p>
                Follow available cryptocurrency flows,
                identify known destination entities, and
                preserve the investigative trail.
              </p>
            </div>

            {/* =================================================
                INPUT
            ================================================= */}

            <Card title="TRON WALLET ADDRESS">
              <div className="trace-input-area">
                <div className="input-row">
                  <div className="input-container">
                    <input
                      className="wallet-input"
                      value={address}
                      onChange={(event) =>
                        setAddress(event.target.value)
                      }
                      onKeyDown={(event) => {
                        if (
                          event.key === "Enter" &&
                          status !== "loading"
                        ) {
                          handleTrace();
                        }
                      }}
                      placeholder={
                        demoMode
                          ? "Demonstration mode — address validation bypassed"
                          : "Enter a TRON wallet address"
                      }
                      disabled={status === "loading"}
                      spellCheck={false}
                    />

                    <div className="input-meta">
                      <span>
                        <StatusDot tone="green" />
                        TRON mainnet
                      </span>

                      <span className="meta-divider">
                        |
                      </span>

                      <span>
                        Press Enter to trace
                      </span>
                    </div>
                  </div>

                  <button
                    className="trace-btn"
                    disabled={status === "loading"}
                    onClick={handleTrace}
                  >
                    {status === "loading" ? (
                      <>
                        <Spinner />
                        Tracing…
                      </>
                    ) : (
                      <>
                        Trace Funds
                        <span className="arrow">
                          →
                        </span>
                      </>
                    )}
                  </button>
                </div>

                {status === "error" && (
                  <div className="error-box">
                    {errorMsg}
                  </div>
                )}
              </div>
            </Card>

            {/* =================================================
                IDLE
            ================================================= */}

            {status === "idle" && !result && (
              <div className="empty-state">
                <div className="empty-icon">
                  <span>⌁</span>
                </div>

                <div className="empty-title">
                  No investigation active
                </div>

                <div className="empty-description">
                  Enter a TRON wallet address to begin
                  following the available fund flow.
                </div>
              </div>
            )}

            {/* =================================================
                LOADING
            ================================================= */}

            {status === "loading" && (
              <div className="trace-progress">
                <div className="progress-icon">
                  <Spinner />
                </div>

                <div className="progress-content">
                  <div className="progress-title">
                    Investigation in progress
                  </div>

                  <div className="progress-step">
                    {LOADING_STEPS[loadingStep]}
                  </div>

                  <div className="progress-line">
                    <div
                      className="progress-line-fill"
                      style={{
                        width: `${
                          ((loadingStep + 1) /
                            LOADING_STEPS.length) *
                          100
                        }%`,
                      }}
                    />
                  </div>
                </div>
              </div>
            )}

            {/* =================================================
                RESULT
            ================================================= */}

            {hasResult && (
              <div className="result-stack">
                {/* RESULT HERO */}

                <section
                  className={`result-hero hero-${meta.tone}`}
                >
                  <div className="result-hero-top">
                    <div>
                      <div className="result-eyebrow">
                        INVESTIGATION RESULT
                      </div>

                      <div className="result-heading">
                        {meta.heading}
                      </div>

                      <div
                        className={`result-sub result-${meta.tone}`}
                      >
                        {meta.sub}
                      </div>

                      {result.exchange_name && (
                        <div className="entity-row">
                          <span className="entity-name">
                            {result.exchange_name}
                          </span>

                          <Chip tone="blue">
                            Known Entity
                          </Chip>
                        </div>
                      )}
                    </div>

                    <div className="confidence-block">
                      <div className="confidence-number">
                        {result.confidence ?? 0}%
                      </div>

                      <div className="confidence-label">
                        Entity confidence
                      </div>

                      <ConfidenceBar
                        value={result.confidence ?? 0}
                        tone={meta.tone}
                      />
                    </div>
                  </div>

                  <div className="hero-stats">
                    <div className="hero-stat">
                      <span className="hero-stat-label">
                        HOPS
                      </span>
                      <span className="hero-stat-value">
                        {result.hops ?? 0}
                      </span>
                    </div>

                    <div className="hero-stat">
                      <span className="hero-stat-label">
                        ASSET
                      </span>
                      <span className="hero-stat-value">
                        {result.token || "—"}
                      </span>
                    </div>

                    <div className="hero-stat">
                      <span className="hero-stat-label">
                        NETWORK
                      </span>
                      <span className="hero-stat-value">
                        TRON
                      </span>
                    </div>

                    <div className="hero-stat">
                      <span className="hero-stat-label">
                        CASE
                      </span>
                      <span className="hero-stat-value mono">
                        {caseId || "—"}
                      </span>
                    </div>
                  </div>
                </section>

                {/* NOTICE */}

                {noticeFn && (
                  <div
                    className={`investigation-note note-${meta.tone}`}
                  >
                    <div className="note-marker" />
                    <div>{noticeFn(result)}</div>
                  </div>
                )}

                {/* FUND FLOW */}

                {Array.isArray(result.hop_path) &&
                  result.hop_path.length > 0 && (
                    <Card
                      title="FUND FLOW"
                      right={
                        <Chip
                          tone={
                            meta.tone === "green"
                              ? "green"
                              : meta.tone === "amber"
                              ? "amber"
                              : meta.tone
                          }
                        >
                          {meta.heading}
                        </Chip>
                      }
                    >
                      <div className="flow-area">
                        {result.hop_path.map(
                          (addr, index) => {
                            const first =
                              index === 0;

                            const last =
                              index ===
                              result.hop_path.length -
                                1;

                            const obstruction =
                              result.result ===
                                "mixer_identified" &&
                              last;

                            const identified =
                              last &&
                              result.exchange_name;

                            let label =
                              "INTERMEDIATE WALLET";

                            let title =
                              `Hop ${index}`;

                            if (first) {
                              label = "SOURCE";
                              title = "Source Wallet";
                            }

                            if (obstruction) {
                              label =
                                "OBSTRUCTION POINT";
                              title =
                                "Mixing activity";
                            }

                            if (identified) {
                              label =
                                "DESTINATION";
                              title =
                                result.exchange_name;
                            }

                            return (
                              <div
                                key={`${addr}-${index}`}
                                className="flow-step"
                              >
                                <div
                                  className={`flow-node ${
                                    identified
                                      ? "flow-node-green"
                                      : obstruction
                                      ? "flow-node-amber"
                                      : ""
                                  }`}
                                >
                                  <div className="flow-node-number">
                                    {String(
                                      index + 1
                                    ).padStart(2, "0")}
                                  </div>

                                  <div className="flow-node-content">
                                    <div className="flow-node-label">
                                      {label}
                                    </div>

                                    <div className="flow-node-title">
                                      {title}
                                    </div>

                                    <div className="flow-node-address">
                                      {addr}
                                      <CopyButton
                                        text={addr}
                                      />
                                    </div>
                                  </div>

                                  {identified && (
                                    <div className="identified-mark">
                                      ✓
                                    </div>
                                  )}

                                  {obstruction && (
                                    <div className="identified-mark warning">
                                      !
                                    </div>
                                  )}
                                </div>

                                {!last && (
                                  <div className="flow-arrow-line">
                                    <span />
                                    <b>↓</b>
                                  </div>
                                )}
                              </div>
                            );
                          }
                        )}
                      </div>
                    </Card>
                  )}

                {/* EVIDENCE */}

                <Card
                  title="TRANSACTION EVIDENCE"
                  right={
                    <span className="evidence-label">
                      {result.transaction_hash
                        ? "VERIFIED DATA"
                        : "AVAILABLE DATA"}
                    </span>
                  }
                >
                  <div className="evidence-grid">
                    <div className="evidence-item">
                      <span>Asset</span>
                      <strong>
                        {result.token || "—"}
                      </strong>
                    </div>

                    <div className="evidence-item">
                      <span>Amount</span>
                      <strong>
                        {result.amount || "—"}
                      </strong>
                    </div>

                    <div className="evidence-item">
                      <span>Hops</span>
                      <strong>
                        {result.hops ?? 0}
                      </strong>
                    </div>

                    <div className="evidence-item">
                      <span>Block</span>
                      <strong>
                        {result.block_number
                          ? result.block_number
                          : "—"}
                      </strong>
                    </div>
                  </div>

                  <div className="evidence-rows">
                    <div className="evidence-row">
                      <span>Source wallet</span>

                      <div className="evidence-value">
                        <code>
                          {result.from_address ||
                            result.wallet_address ||
                            "—"}
                        </code>

                        {(
                          result.from_address ||
                          result.wallet_address
                        ) && (
                          <CopyButton
                            text={
                              result.from_address ||
                              result.wallet_address
                            }
                          />
                        )}
                      </div>
                    </div>

                    <div className="evidence-row">
                      <span>Destination</span>

                      <div className="evidence-value">
                        <code>
                          {result.to_address ||
                            "—"}
                        </code>

                        {result.to_address && (
                          <CopyButton
                            text={
                              result.to_address
                            }
                          />
                        )}
                      </div>
                    </div>

                    <div className="evidence-row">
                      <span>Contract</span>

                      <div className="evidence-value">
                        <code>
                          {result.contract_address ||
                            "—"}
                        </code>

                        {result.contract_address && (
                          <CopyButton
                            text={
                              result.contract_address
                            }
                          />
                        )}
                      </div>
                    </div>

                    <div className="evidence-row">
                      <span>Transaction hash</span>

                      <div className="evidence-value">
                        <code>
                          {result.transaction_hash ||
                            result.transaction_id ||
                            "—"}
                        </code>

                        {(
                          result.transaction_hash ||
                          result.transaction_id
                        ) && (
                          <CopyButton
                            text={
                              result.transaction_hash ||
                              result.transaction_id
                            }
                          />
                        )}
                      </div>
                    </div>
                  </div>
                </Card>

                {/* ANALYTICAL SIGNALS */}

                {(result.risk_indicators?.length >
                  0 ||
                  result.risk_assessment) && (
                  <Card
                    title="ANALYTICAL SIGNALS"
                    right={
                      <div className="risk-inline">
                        <span>Risk</span>
                        <Chip
                          tone={
                            result.risk_level ===
                            "LOW"
                              ? "green"
                              : result.risk_level ===
                                "MEDIUM"
                              ? "blue"
                              : "amber"
                          }
                        >
                          {result.risk_level ||
                            "UNKNOWN"}
                        </Chip>
                      </div>
                    }
                  >
                    <div className="signals-grid">
                      <div className="signal">
                        <span className="signal-label">
                          FAN-IN
                        </span>

                        <span
                          className={`signal-value ${
                            result.fan_in
                              ? "signal-on"
                              : ""
                          }`}
                        >
                          {result.fan_in
                            ? "Detected"
                            : "Not detected"}
                        </span>
                      </div>

                      <div className="signal">
                        <span className="signal-label">
                          FAN-OUT
                        </span>

                        <span
                          className={`signal-value ${
                            result.fan_out
                              ? "signal-on"
                              : ""
                          }`}
                        >
                          {result.fan_out
                            ? "Detected"
                            : "Not detected"}
                        </span>
                      </div>

                      <div className="signal">
                        <span className="signal-label">
                          RAPID HOPS
                        </span>

                        <span
                          className={`signal-value ${
                            result.rapid_hops
                              ? "signal-on"
                              : ""
                          }`}
                        >
                          {result.rapid_hops
                            ? "Detected"
                            : "Not detected"}
                        </span>
                      </div>

                      <div className="signal">
                        <span className="signal-label">
                          RISK SCORE
                        </span>

                        <span className="signal-value">
                          {typeof result.risk_score ===
                          "number"
                            ? `${result.risk_score}/100`
                            : "—"}
                        </span>
                      </div>
                    </div>

                    {result.risk_indicators?.length >
                      0 && (
                      <div className="indicator-list">
                        <div className="indicator-heading">
                          INDICATORS
                        </div>

                        {result.risk_indicators.map(
                          (item, index) => (
                            <div
                              key={index}
                              className="indicator-item"
                            >
                              <span>•</span>
                              <span>{item}</span>
                            </div>
                          )
                        )}
                      </div>
                    )}

                    {result.risk_assessment && (
                      <div className="assessment">
                        <span className="assessment-label">
                          ASSESSMENT
                        </span>

                        <span>
                          {result.risk_assessment}
                        </span>
                      </div>
                    )}

                    <div className="analysis-disclaimer">
                      Analytical signals support
                      investigation and do not establish
                      criminal activity on their own.
                    </div>
                  </Card>
                )}

                {/* REPORT */}

                <Card title="CASE EVIDENCE">
                  <div className="report-panel">
                    <div>
                      <div className="report-title">
                        Investigation report
                      </div>

                      <div className="report-description">
                        Export the current trace,
                        destination information,
                        transaction evidence and
                        supporting analysis.
                      </div>
                    </div>

                    <button
                      className="report-btn"
                      onClick={
                        handleDownloadReport
                      }
                      disabled={!result.report}
                    >
                      <span>Export Report</span>
                      <span>↓</span>
                    </button>
                  </div>
                </Card>

                {/* FOOTNOTE */}

                <div className="forensic-footer">
                  Automated blockchain analysis is an
                  investigative aid. Destination
                  identification does not by itself establish
                  fraudulent or unlawful activity.
                </div>
              </div>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}

/* =========================================================
   STYLES
   ========================================================= */

const STYLES = `
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap');

:root {
  --navy-950: #0A1625;
  --navy-900: #0F2034;
  --navy-850: #142A42;
  --navy-800: #183552;
  --blue: #356A9F;
  --blue-soft: #EAF1F8;

  --ink: #17212D;
  --ink-soft: #4E5D6D;
  --muted: #788797;

  --canvas: #EEF2F5;
  --panel: #FFFFFF;
  --panel-soft: #F7F9FB;

  --border: #D8E0E7;
  --border-soft: #E9EEF2;

  --green: #18734A;
  --green-bg: #EDF8F2;
  --green-border: #B9DFC9;

  --amber: #946200;
  --amber-bg: #FFF8E9;
  --amber-border: #E9CF8C;

  --red: #A34444;
  --red-bg: #FEF1F1;
  --red-border: #E7BDBD;

  --shadow: 0 1px 2px rgba(15, 32, 52, .05);

  font-family:
    'IBM Plex Sans',
    -apple-system,
    BlinkMacSystemFont,
    'Segoe UI',
    sans-serif;
}

* {
  box-sizing: border-box;
}

html,
body,
#root {
  margin: 0;
  width: 100%;
  height: 100%;
}

body {
  background: var(--canvas);
  color: var(--ink);
  font-size: 13px;
}

button,
input,
select {
  font: inherit;
}

button {
  cursor: pointer;
}

code,
.mono {
  font-family:
    'IBM Plex Mono',
    ui-monospace,
    SFMono-Regular,
    Menlo,
    Consolas,
    monospace;
}

/* =========================================================
   SHELL
   ========================================================= */

.app-shell {
  min-height: 100vh;
  display: grid;
  grid-template-columns: 236px minmax(0, 1fr);
  background: var(--canvas);
}

/* =========================================================
   SIDEBAR
   ========================================================= */

.sidebar {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  padding: 20px 14px 14px;

  background:
    linear-gradient(
      180deg,
      var(--navy-950) 0%,
      var(--navy-900) 60%,
      #0C1B2C 100%
    );

  border-right: 1px solid #07111C;
  color: #EAF1F7;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 2px 7px 19px;
}

.brand-mark {
  width: 32px;
  height: 32px;

  display: grid;
  place-items: center;

  background: #DCEAF7;
  color: var(--navy-950);

  font-size: 11px;
  font-weight: 700;
  letter-spacing: .08em;

  border-radius: 6px;
}

.brand-name {
  color: #F3F7FA;
  font-size: 14px;
  font-weight: 700;
}

.brand-sub {
  margin-top: 2px;
  color: #8191A4;
  font-size: 10px;
  letter-spacing: .04em;
}

.new-case-btn {
  width: 100%;
  padding: 9px 11px;

  display: flex;
  align-items: center;
  gap: 8px;

  background: #142A42;
  border: 1px solid #29425D;
  border-radius: 5px;

  color: #DCE7F0;
  font-size: 11.5px;
  font-weight: 600;

  transition: .18s ease;
}

.new-case-btn:hover {
  background: #193551;
  border-color: #3B5874;
}

.plus {
  font-size: 16px;
  line-height: 1;
  color: #BBD2E5;
}

.sidebar-divider {
  height: 1px;
  margin: 17px 0 12px;
  background: #1C3148;
}

.sidebar-section-label {
  padding: 0 7px 7px;

  color: #62778D;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: .13em;
}

.previous-label {
  margin-top: 21px;
}

.sidebar-case {
  display: flex;
  align-items: flex-start;
  gap: 9px;

  padding: 10px 8px;

  border: 1px solid transparent;
  border-radius: 5px;
}

.sidebar-case.selected {
  background: rgba(255,255,255,.045);
  border-color: rgba(255,255,255,.08);
}

.sidebar-case-copy {
  min-width: 0;
}

.sidebar-case-id {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;

  color: #E4EDF4;
  font-size: 11.5px;
  font-weight: 600;
}

.sidebar-case-status {
  margin-top: 2px;
  color: #708297;
  font-size: 10px;
}

.status-dot {
  width: 6px;
  height: 6px;
  flex: 0 0 auto;

  display: inline-block;

  border-radius: 50%;
}

.dot-green {
  background: #55B980;
}

.dot-blue {
  background: #5E92C5;
}

.dot-amber {
  background: #D4A33A;
}

.dot-red {
  background: #C76A6A;
}

.dot-slate {
  background: #738397;
}

.history-list {
  display: grid;
  gap: 2px;
}

.history-item {
  width: 100%;
  padding: 7px 8px;

  display: grid;
  gap: 2px;

  text-align: left;

  background: transparent;
  border: 0;
  border-radius: 4px;

  color: #94A5B7;
}

.history-item:hover {
  background: rgba(255,255,255,.035);
}

.history-id {
  font-size: 10.5px;
  font-weight: 600;
}

.history-address {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;

  color: #5F7489;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 9px;
}

.sidebar-spacer {
  flex: 1;
}

.system-box {
  margin: 12px 0 10px;
  padding: 10px;

  background: rgba(255,255,255,.028);
  border: 1px solid #1F344A;
  border-radius: 5px;
}

.system-row {
  display: flex;
  align-items: center;
  justify-content: space-between;

  padding: 4px 0;
}

.system-label {
  color: #62778D;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: .1em;
}

.system-value {
  display: inline-flex;
  align-items: center;
  gap: 6px;

  color: #B7C7D6;
  font-size: 10px;
}

.demo-area {
  padding-top: 11px;
  border-top: 1px solid #1E3349;
}

.demo-label {
  display: flex;
  align-items: center;
  gap: 7px;

  color: #7890A5;
  font-size: 10.5px;

  cursor: pointer;
}

.demo-label input {
  width: 12px;
  height: 12px;
  accent-color: #5E8BB5;
}

.demo-select {
  width: 100%;
  margin-top: 7px;
  padding: 6px 8px;

  color: #C5D2DE;
  background: #11263C;
  border: 1px solid #2A435C;
  border-radius: 4px;

  font-size: 10px;
}

/* =========================================================
   MAIN
   ========================================================= */

.main-area {
  min-width: 0;
  min-height: 100vh;
  display: grid;
  grid-template-rows: 48px minmax(0, 1fr);
}

.topbar {
  min-width: 0;

  display: flex;
  align-items: center;
  justify-content: space-between;

  padding: 0 28px;

  background: #FFFFFF;
  border-bottom: 1px solid var(--border);
}

.topbar-left,
.topbar-right {
  display: flex;
  align-items: center;
}

.topbar-section {
  color: #667689;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: .14em;
}

.topbar-slash {
  margin: 0 9px;
  color: #B8C1CA;
}

.topbar-case {
  color: #435466;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 10.5px;
}

.live-status {
  display: flex;
  align-items: center;
  gap: 6px;

  color: #526273;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: .05em;
}

.live-text {
  color: var(--green);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: .1em;
}

/* =========================================================
   WORKSPACE
   ========================================================= */

.workspace {
  overflow-y: auto;
  background: var(--canvas);
  padding: 30px 36px 50px;
}

.workspace-inner {
  width: min(1040px, 100%);
  margin: 0 auto;
}

.intro {
  margin-bottom: 20px;
}

.intro-kicker {
  margin-bottom: 6px;

  color: var(--blue);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: .15em;
}

.intro h1 {
  margin: 0;

  color: #142131;

  font-size: 27px;
  line-height: 1.15;
  font-weight: 700;
  letter-spacing: -.02em;
}

.intro p {
  max-width: 680px;
  margin: 8px 0 0;

  color: #677788;
  font-size: 12.5px;
  line-height: 1.65;
}

/* =========================================================
   CARDS
   ========================================================= */

.card {
  margin-bottom: 13px;

  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 7px;

  box-shadow: var(--shadow);
  overflow: hidden;
}

.card-header {
  min-height: 36px;

  display: flex;
  align-items: center;

  padding: 0 15px;

  background: #FAFBFC;
  border-bottom: 1px solid var(--border-soft);
}

.card-title {
  color: #667689;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: .13em;
}

.card-header-right {
  margin-left: auto;
}

.card-body {
  min-width: 0;
}

/* =========================================================
   INPUT
   ========================================================= */

.trace-input-area {
  padding: 15px;
}

.input-row {
  display: flex;
  gap: 10px;
  align-items: flex-start;
}

.input-container {
  flex: 1;
  min-width: 0;
}

.wallet-input {
  width: 100%;
  min-height: 43px;

  padding: 0 12px;

  color: #192634;
  background: #FFFFFF;

  border: 1px solid #C8D2DC;
  border-radius: 5px;
  outline: none;

  font-family: 'IBM Plex Mono', monospace;
  font-size: 12px;

  transition: .16s ease;
}

.wallet-input:focus {
  border-color: #6690B8;
  box-shadow: 0 0 0 3px rgba(53, 106, 159, .08);
}

.wallet-input::placeholder {
  color: #9AA7B4;
}

.wallet-input:disabled {
  background: #F6F8FA;
  cursor: not-allowed;
}

.input-meta {
  display: flex;
  align-items: center;
  gap: 7px;

  margin-top: 7px;

  color: #94A2B0;
  font-size: 9.5px;
}

.input-meta span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.meta-divider {
  color: #C4CBD3;
}

.trace-btn {
  min-height: 43px;
  padding: 0 19px;

  display: inline-flex;
  align-items: center;
  gap: 8px;

  color: #FFFFFF;
  background: var(--navy-800);

  border: 1px solid var(--navy-800);
  border-radius: 5px;

  font-size: 11.5px;
  font-weight: 600;

  transition: .18s ease;
}

.trace-btn:hover {
  background: var(--blue);
  border-color: var(--blue);
}

.trace-btn:disabled {
  background: #7C91A7;
  border-color: #7C91A7;
  cursor: not-allowed;
}

.arrow {
  font-size: 14px;
}

.error-box {
  margin-top: 10px;
  padding: 9px 11px;

  color: var(--red);
  background: var(--red-bg);
  border: 1px solid var(--red-border);
  border-radius: 4px;

  font-size: 11px;
}

/* =========================================================
   EMPTY
   ========================================================= */

.empty-state {
  min-height: 245px;

  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;

  margin-top: 2px;

  background: rgba(255,255,255,.54);
  border: 1px dashed #D1DAE2;
  border-radius: 7px;
}

.empty-icon {
  width: 42px;
  height: 42px;

  display: grid;
  place-items: center;

  margin-bottom: 11px;

  color: #65819C;
  background: #E9F0F6;
  border: 1px solid #D1DEE9;
  border-radius: 7px;

  font-size: 19px;
}

.empty-title {
  color: #536577;
  font-size: 12px;
  font-weight: 600;
}

.empty-description {
  max-width: 350px;
  margin-top: 5px;

  color: #8795A3;
  text-align: center;
  font-size: 11px;
  line-height: 1.55;
}

/* =========================================================
   LOADING
   ========================================================= */

.trace-progress {
  display: flex;
  gap: 15px;
  align-items: center;

  margin-top: 2px;
  padding: 22px;

  background: #FFFFFF;
  border: 1px solid var(--border);
  border-radius: 7px;
  box-shadow: var(--shadow);
}

.progress-icon {
  width: 39px;
  height: 39px;

  display: grid;
  place-items: center;

  background: #EDF3F8;
  border: 1px solid #D6E0E9;
  border-radius: 6px;

  color: var(--blue);
}

.progress-content {
  flex: 1;
  min-width: 0;
}

.progress-title {
  color: #233446;
  font-size: 12px;
  font-weight: 600;
}

.progress-step {
  margin-top: 3px;
  color: #7A8998;
  font-size: 10.5px;
}

.progress-line {
  height: 3px;
  margin-top: 10px;

  background: #E9EEF2;
  border-radius: 2px;
  overflow: hidden;
}

.progress-line-fill {
  height: 100%;
  background: var(--blue);
  transition: width .3s ease;
}

/* =========================================================
   RESULT
   ========================================================= */

.result-stack {
  display: block;
}

.result-hero {
  margin-bottom: 10px;

  background: #FFFFFF;
  border: 1px solid var(--border);
  border-radius: 7px;
  overflow: hidden;

  box-shadow: var(--shadow);
}

.result-hero-top {
  min-height: 154px;

  display: flex;
  align-items: center;
  justify-content: space-between;

  padding: 23px;
}

.hero-green {
  border-top: 3px solid var(--green);
}

.hero-amber {
  border-top: 3px solid var(--amber);
}

.hero-red {
  border-top: 3px solid var(--red);
}

.hero-blue {
  border-top: 3px solid var(--blue);
}

.hero-slate {
  border-top: 3px solid #8995A0;
}

.result-eyebrow {
  color: #7C8996;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: .13em;
}

.result-heading {
  margin-top: 6px;

  color: #172431;
  font-size: 21px;
  font-weight: 700;
}

.result-sub {
  margin-top: 3px;
  font-size: 12.5px;
  font-weight: 600;
}

.result-green {
  color: var(--green);
}

.result-amber {
  color: var(--amber);
}

.result-red {
  color: var(--red);
}

.result-blue {
  color: var(--blue);
}

.result-slate {
  color: #677585;
}

.entity-row {
  display: flex;
  align-items: center;
  gap: 8px;

  margin-top: 10px;
}

.entity-name {
  color: #253648;
  font-size: 13px;
  font-weight: 600;
}

.confidence-block {
  width: 190px;
  padding-left: 30px;
  border-left: 1px solid var(--border-soft);
}

.confidence-number {
  color: #172431;
  font-size: 31px;
  line-height: 1;
  font-weight: 700;
}

.confidence-label {
  margin-top: 5px;

  color: #7E8B98;
  font-size: 9px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .08em;
}

.confidence-wrap {
  width: 100%;
  margin-top: 10px;
}

.confidence-track {
  height: 4px;
  background: #E8EDF1;
  border-radius: 3px;
  overflow: hidden;
}

.confidence-fill {
  height: 100%;
  border-radius: 3px;
}

.fill-green {
  background: var(--green);
}

.fill-amber {
  background: var(--amber);
}

.fill-red {
  background: var(--red);
}

.fill-blue {
  background: var(--blue);
}

.fill-slate {
  background: #82909D;
}

.hero-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);

  border-top: 1px solid var(--border-soft);
}

.hero-stat {
  min-height: 63px;

  padding: 11px 16px;

  border-right: 1px solid var(--border-soft);
}

.hero-stat:last-child {
  border-right: 0;
}

.hero-stat-label {
  display: block;

  color: #8693A0;
  font-size: 8.5px;
  font-weight: 700;
  letter-spacing: .11em;
}

.hero-stat-value {
  display: block;
  margin-top: 5px;

  color: #253546;
  font-size: 13px;
  font-weight: 600;
}

/* =========================================================
   NOTE
   ========================================================= */

.investigation-note {
  display: flex;
  gap: 11px;

  margin-bottom: 13px;
  padding: 12px 14px;

  border: 1px solid var(--border);
  border-radius: 5px;

  color: #495B6C;
  background: #F9FBFC;

  font-size: 10.5px;
  line-height: 1.6;
}

.note-marker {
  width: 3px;
  flex: 0 0 auto;
  border-radius: 3px;
}

.note-green {
  background: #F3FAF6;
  border-color: var(--green-border);
}

.note-green .note-marker {
  background: var(--green);
}

.note-amber {
  background: var(--amber-bg);
  border-color: var(--amber-border);
}

.note-amber .note-marker {
  background: var(--amber);
}

.note-red {
  background: var(--red-bg);
  border-color: var(--red-border);
}

.note-red .note-marker {
  background: var(--red);
}

.note-blue {
  background: var(--blue-soft);
  border-color: #CBDCEB;
}

.note-blue .note-marker {
  background: var(--blue);
}

/* =========================================================
   FLOW
   ========================================================= */

.flow-area {
  padding: 17px;
}

.flow-step {
  width: 100%;
}

.flow-node {
  min-height: 75px;

  display: flex;
  align-items: center;

  padding: 11px 12px;

  background: #FFFFFF;
  border: 1px solid #D2DCE4;
  border-radius: 6px;
}

.flow-node-green {
  background: #F5FBF7;
  border-color: var(--green-border);
}

.flow-node-amber {
  background: #FFFAEF;
  border-color: var(--amber-border);
}

.flow-node-number {
  width: 32px;
  flex: 0 0 32px;

  color: #81909E;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 9px;
  font-weight: 600;
}

.flow-node-content {
  min-width: 0;
  flex: 1;
}

.flow-node-label {
  color: #84929F;
  font-size: 8.5px;
  font-weight: 700;
  letter-spacing: .12em;
}

.flow-node-title {
  margin-top: 3px;

  color: #263748;
  font-size: 12px;
  font-weight: 600;
}

.flow-node-address {
  display: flex;
  align-items: center;
  gap: 4px;

  margin-top: 4px;

  color: #5A6D7F;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 10px;
  line-height: 1.5;

  word-break: break-all;
}

.identified-mark {
  width: 24px;
  height: 24px;
  flex: 0 0 auto;

  display: grid;
  place-items: center;

  color: var(--green);
  background: #E2F4E9;
  border-radius: 50%;

  font-size: 12px;
  font-weight: 700;
}

.identified-mark.warning {
  color: var(--amber);
  background: #FFF0C9;
}

.flow-arrow-line {
  height: 31px;

  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;

  color: #9BA8B3;
}

.flow-arrow-line span {
  width: 1px;
  height: 13px;
  background: #CBD4DC;
}

.flow-arrow-line b {
  margin-top: 1px;
  font-size: 12px;
  font-weight: 400;
}

/* =========================================================
   EVIDENCE
   ========================================================= */

.evidence-label {
  color: var(--green);
  font-size: 8px;
  font-weight: 700;
  letter-spacing: .1em;
}

.evidence-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);

  border-bottom: 1px solid var(--border-soft);
}

.evidence-item {
  min-height: 66px;
  padding: 12px 14px;
  border-right: 1px solid var(--border-soft);
}

.evidence-item:last-child {
  border-right: 0;
}

.evidence-item span {
  display: block;

  color: #8693A0;
  font-size: 8.5px;
  font-weight: 700;
  letter-spacing: .1em;
  text-transform: uppercase;
}

.evidence-item strong {
  display: block;
  margin-top: 6px;

  color: #253546;
  font-size: 11.5px;
  font-weight: 600;
  word-break: break-word;
}

.evidence-rows {
  display: block;
}

.evidence-row {
  display: grid;
  grid-template-columns: 136px minmax(0, 1fr);

  min-height: 46px;
  align-items: center;

  padding: 8px 14px;

  border-bottom: 1px solid var(--border-soft);
}

.evidence-row:last-child {
  border-bottom: 0;
}

.evidence-row > span {
  color: #7E8C99;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: .08em;
  text-transform: uppercase;
}

.evidence-value {
  min-width: 0;

  display: flex;
  align-items: center;
  gap: 8px;
}

.evidence-value code {
  min-width: 0;

  color: #415569;
  font-size: 10px;
  line-height: 1.55;

  word-break: break-all;
}

/* =========================================================
   COPY BUTTON
   ========================================================= */

.copy-btn {
  flex: 0 0 auto;

  padding: 3px 6px;

  color: #7990A6;
  background: transparent;

  border: 1px solid #D6E0E7;
  border-radius: 3px;

  font-size: 8px;
  font-weight: 600;
}

.copy-btn:hover {
  color: var(--blue);
  border-color: #AFC3D5;
  background: #F3F7FA;
}

/* =========================================================
   SIGNALS
   ========================================================= */

.risk-inline {
  display: flex;
  align-items: center;
  gap: 7px;
}

.risk-inline > span {
  color: #8895A2;
  font-size: 8.5px;
  font-weight: 700;
  letter-spacing: .1em;
  text-transform: uppercase;
}

.signals-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);

  border-bottom: 1px solid var(--border-soft);
}

.signal {
  min-height: 70px;
  padding: 12px 14px;
  border-right: 1px solid var(--border-soft);
}

.signal:last-child {
  border-right: 0;
}

.signal-label {
  display: block;

  color: #8996A3;
  font-size: 8.5px;
  font-weight: 700;
  letter-spacing: .1em;
}

.signal-value {
  display: block;
  margin-top: 8px;

  color: #4C5D6D;
  font-size: 11px;
  font-weight: 600;
}

.signal-on {
  color: var(--amber);
}

.indicator-list {
  padding: 12px 14px;
  border-bottom: 1px solid var(--border-soft);
}

.indicator-heading {
  margin-bottom: 8px;

  color: #8896A3;
  font-size: 8.5px;
  font-weight: 700;
  letter-spacing: .1em;
}

.indicator-item {
  display: flex;
  gap: 7px;

  margin-top: 5px;

  color: #596A79;
  font-size: 10.5px;
  line-height: 1.45;
}

.indicator-item span:first-child {
  color: #A27B2D;
}

.assessment {
  display: flex;
  gap: 15px;

  padding: 11px 14px;

  color: #596A79;
  background: #FBFCFD;

  font-size: 10.5px;
  line-height: 1.55;
}

.assessment-label {
  flex: 0 0 70px;

  color: #8A97A4;
  font-size: 8.5px;
  font-weight: 700;
  letter-spacing: .1em;
}

.analysis-disclaimer {
  padding: 9px 14px;

  color: #9AA6B2;
  background: #F8FAFB;

  font-size: 9px;
  line-height: 1.5;
}

/* =========================================================
   REPORT
   ========================================================= */

.report-panel {
  min-height: 92px;

  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;

  padding: 15px;
}

.report-title {
  color: #263849;
  font-size: 12px;
  font-weight: 600;
}

.report-description {
  max-width: 650px;
  margin-top: 4px;

  color: #7A8997;
  font-size: 10.5px;
  line-height: 1.55;
}

.report-btn {
  flex: 0 0 auto;

  min-height: 37px;
  padding: 0 14px;

  display: inline-flex;
  align-items: center;
  gap: 10px;

  color: #FFFFFF;
  background: var(--navy-800);

  border: 1px solid var(--navy-800);
  border-radius: 5px;

  font-size: 10.5px;
  font-weight: 600;

  transition: .18s ease;
}

.report-btn:hover {
  background: var(--blue);
  border-color: var(--blue);
}

.report-btn:disabled {
  opacity: .45;
  cursor: not-allowed;
}

/* =========================================================
   FORENSIC FOOTER
   ========================================================= */

.forensic-footer {
  padding: 4px 2px 12px;

  color: #929EAA;
  font-size: 9.5px;
  line-height: 1.55;
}

/* =========================================================
   CHIPS
   ========================================================= */

.chip {
  display: inline-flex;
  align-items: center;

  padding: 4px 7px;

  border-radius: 3px;

  font-size: 8px;
  font-weight: 700;
  letter-spacing: .08em;
  text-transform: uppercase;
}

.chip-green {
  color: var(--green);
  background: var(--green-bg);
  border: 1px solid var(--green-border);
}

.chip-blue {
  color: var(--blue);
  background: var(--blue-soft);
  border: 1px solid #C7D9E8;
}

.chip-amber {
  color: var(--amber);
  background: var(--amber-bg);
  border: 1px solid var(--amber-border);
}

.chip-red {
  color: var(--red);
  background: var(--red-bg);
  border: 1px solid var(--red-border);
}

.chip-slate {
  color: #667482;
  background: #F2F5F7;
  border: 1px solid #D8E0E6;
}

/* =========================================================
   SPINNER
   ========================================================= */

.spinner {
  width: 13px;
  height: 13px;

  display: inline-block;

  border: 1.7px solid rgba(255,255,255,.28);
  border-top-color: #FFFFFF;
  border-radius: 50%;

  animation: rotate .7s linear infinite;
}

@keyframes rotate {
  to {
    transform: rotate(360deg);
  }
}

/* =========================================================
   RESPONSIVE
   ========================================================= */

@media (max-width: 980px) {
  .app-shell {
    grid-template-columns: 205px minmax(0, 1fr);
  }

  .workspace {
    padding: 25px 22px 40px;
  }

  .confidence-block {
    width: 165px;
  }
}

@media (max-width: 820px) {
  .app-shell {
    grid-template-columns: 1fr;
  }

  .sidebar {
    min-height: auto;
    border-right: 0;
    border-bottom: 1px solid #07111C;
  }

  .sidebar-spacer {
    display: none;
  }

  .main-area {
    min-height: auto;
  }

  .hero-stats,
  .evidence-grid,
  .signals-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .confidence-block {
    width: 150px;
    padding-left: 20px;
  }
}

@media (max-width: 620px) {
  .topbar {
    padding: 0 15px;
  }

  .workspace {
    padding: 18px 13px 30px;
  }

  .intro h1 {
    font-size: 22px;
  }

  .input-row,
  .report-panel {
    flex-direction: column;
    align-items: stretch;
  }

  .trace-btn,
  .report-btn {
    width: 100%;
    justify-content: center;
  }

  .result-hero-top {
    flex-direction: column;
    align-items: flex-start;
    gap: 19px;
  }

  .confidence-block {
    width: 100%;
    padding: 13px 0 0;
    border-left: 0;
    border-top: 1px solid var(--border-soft);
  }

  .hero-stats {
    grid-template-columns: repeat(2, 1fr);
  }

  .evidence-grid,
  .signals-grid {
    grid-template-columns: 1fr 1fr;
  }

  .evidence-row {
    grid-template-columns: 1fr;
    gap: 6px;
  }
}
`;