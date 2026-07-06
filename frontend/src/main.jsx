import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  BarChart3,
  BookOpen,
  CheckCircle2,
  ChevronRight,
  Info,
  Loader2,
  MessageSquare,
  Search,
  ShieldAlert,
  Sparkles,
  TrendingUp,
  X,
} from "lucide-react";
import "./styles.css";

const DEMO_QUERY = "I hold VOO, QQQ and VGT - how much do they really overlap?";
const ASK_SUGGESTIONS = [
  { feature: "overlap", text: "VOO + QQQ + VGT overlap", query: DEMO_QUERY },
  { feature: "forensic", text: "NVDA red flags", query: "Should I buy NVDA? Show forensic red flags and the bear case." },
  { feature: "fees", text: "Fee drag calculator", query: "I have $50,000 over 30 years with expense ratio 0.25% and return 6% - am I overpaying in fund fees?" },
  { feature: "growth", text: "What if TSLA", query: "What if I invested $10,000 in TSLA 5 years ago?" },
  { feature: "compare", text: "NVDA vs AMD", query: "Compare NVDA vs AMD side by side." },
  { feature: "planned", text: "NVDA insider activity", query: "Who recently bought or sold NVDA insider shares?" },
  { feature: "planned", text: "Dividend safety", query: "Is SCHD dividend safety good?" },
  { feature: "planned", text: "Market today", query: "What moved the market today?" },
  { feature: "planned", text: "Which ETF remove?", query: "Which fund should I remove to reduce duplication?" },
  { feature: "ticker", text: "TSLA ticker card", query: "Tell me about TSLA." },
  { feature: "term", text: "P/E percentile", query: "Explain P/E percentile in simple terms." },
];

async function apiGet(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

async function ask(query) {
  const response = await fetch("/api/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query }),
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

function pct(value) {
  return `${(Number(value) * 100).toFixed(1).replace(".0", "")}%`;
}

function fmt(value, unit = "") {
  const number = Number(value);
  const rendered = Number.isFinite(number) ? number.toLocaleString(undefined, { maximumFractionDigits: 1 }) : value;
  return `${rendered}${unit || ""}`;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
}

function renderMarkdown(markdown = "") {
  const lines = escapeHtml(markdown).split(/\r?\n/);
  const html = [];
  let list = [];
  const inline = (text) => text
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  const flushList = () => {
    if (!list.length) return;
    html.push(`<ul>${list.map((item) => `<li>${inline(item)}</li>`).join("")}</ul>`);
    list = [];
  };
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) {
      flushList();
      continue;
    }
    if (trimmed.startsWith("- ")) {
      list.push(trimmed.slice(2));
      continue;
    }
    flushList();
    html.push(`<p>${inline(trimmed)}</p>`);
  }
  flushList();
  return { __html: html.join("") };
}

function parseFeeInputs(query = "") {
  const amount = query.match(/\$?\s*([0-9][0-9,]*(?:\.\d+)?)\s*(k|m)?/i);
  const years = query.match(/\b(?:over|for)?\s*(\d{1,2})\s*(?:years?|yrs?)\b/i);
  const expense = query.match(/(?:expense\s*ratio|fee|fees?)\D{0,20}([0-9]+(?:\.\d+)?)\s*%/i);
  const gross = query.match(/(?:return|growth|gross)\D{0,20}([0-9]+(?:\.\d+)?)\s*%/i);
  let amountValue = amount ? Number(amount[1].replaceAll(",", "")) : 10000;
  if (amount?.[2]?.toLowerCase() === "k") amountValue *= 1000;
  if (amount?.[2]?.toLowerCase() === "m") amountValue *= 1000000;
  return {
    amount: amountValue,
    years: years ? Number(years[1]) : 20,
    expensePct: expense ? Number(expense[1]) : 0.75,
    returnPct: gross ? Number(gross[1]) : 7,
  };
}

function App() {
  const [landing, setLanding] = useState(null);
  const [panel, setPanel] = useState(null);
  const [query, setQuery] = useState(DEMO_QUERY);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [entity, setEntity] = useState(null);
  const [askedOnce, setAskedOnce] = useState(false);
  const [showSuggestions, setShowSuggestions] = useState(false);

  useEffect(() => {
    apiGet("/api/landing").then(setLanding).catch((err) => setError(err.message));
    runQuery(DEMO_QUERY);
  }, []);

  async function runQuery(nextQuery = query) {
    setLoading(true);
    setError("");
    try {
      setQuery(nextQuery);
      setShowSuggestions(false);
      setAskedOnce(true);
      const nextPanel = await ask(nextQuery);
      setPanel(nextPanel);
      requestAnimationFrame(() => document.querySelector(".answer")?.scrollIntoView({ behavior: "smooth", block: "start" }));
    } catch (err) {
      setError(err.message || "Request failed");
    } finally {
      setLoading(false);
    }
  }

  async function openEntity(item) {
    setEntity({ loading: true, item });
    const ref = encodeURIComponent(item.ref);
    const path = item.kind === "ticker" ? `/api/entity/ticker/${ref}` : `/api/entity/term/${ref}`;
    try {
      setEntity({ item, data: await apiGet(path) });
    } catch (err) {
      setEntity({ item, error: err.message || "Entity unavailable" });
    }
  }

  return (
    <main className="shell">
      <Landing landing={landing} onAsk={runQuery} />
      <section className="askbar" aria-label="Ask a question">
        <Search size={18} />
        <input
          value={query}
          placeholder="Ask a question or pick a workflow below"
          onFocus={(event) => {
            setShowSuggestions(true);
            if (query === DEMO_QUERY) setQuery("");
            else event.currentTarget.select();
          }}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => event.key === "Enter" && runQuery()}
        />
        <button onClick={() => runQuery()} disabled={loading}>
          {loading ? <Loader2 className="spin" size={18} /> : <MessageSquare size={18} />}
          Ask
        </button>
      </section>
      {showSuggestions && <AskSuggestions onAsk={runQuery} />}
      {error && <div className="error">{error}</div>}
      {loading && askedOnce && !panel && (
        <section className="answer">
          <header className="answer-head">
            <div>
              <div className="intent">working</div>
              <h2>Building the panel...</h2>
              <p>Fetching the contract response and rendering the interactive blocks.</p>
            </div>
          </header>
        </section>
      )}
      {panel && <AnswerPanel panel={panel} onAsk={runQuery} onEntity={openEntity} />}
      {entity && <EntityModal state={entity} onClose={() => setEntity(null)} />}
    </main>
  );
}

function AskSuggestions({ onAsk }) {
  return (
    <section className="ask-suggestions" aria-label="Suggested questions">
      {ASK_SUGGESTIONS.map((item) => (
        <button key={item.query} onMouseDown={(event) => event.preventDefault()} onClick={() => onAsk(item.query)}>
          <span>{item.text}</span>
          <small>{item.feature}</small>
        </button>
      ))}
    </section>
  );
}

function Landing({ landing, onAsk }) {
  if (!landing) {
    return (
      <section className="hero">
        <div className="hero-copy">
          <div className="eyebrow"><Sparkles size={16} /> Loading market desk</div>
          <h1>Retail Investor Agent</h1>
          <p>Interactive research panels for beginner investors.</p>
        </div>
      </section>
    );
  }

  return (
    <section className="hero">
      <div className="hero-copy">
        <div className="eyebrow"><Sparkles size={16} /> Market desk</div>
        <h1>Retail Investor Agent</h1>
        <p>Clear answers you can see — charts, citations, and clickable drilldowns.</p>
      </div>
      <div className="market-strip">
        {landing.market.indices.map((index) => (
          <div className="quote" key={index.name}>
            <span>{index.name}</span>
            <strong>{fmt(index.value)}</strong>
            <em className={index.change_pct >= 0 ? "up" : "down"}>{pct(index.change_pct)}</em>
          </div>
        ))}
      </div>
      <div className="landing-grid">
        <section className="panel-card chart-card">
          <div className="section-title"><BarChart3 size={18} /> Chart of the day</div>
          <BlockRenderer block={landing.chart_of_day} />
        </section>
        <section className="panel-card">
          <div className="section-title"><TrendingUp size={18} /> Movers and why</div>
          {landing.market.movers.map((mover) => (
            <button className="mover" key={mover.ticker} onClick={() => onAsk(`Should I buy ${mover.ticker}? Show forensic red flags and the bear case.`)}>
              <span><strong>{mover.ticker}</strong> {mover.name}</span>
              <em className={mover.change_pct >= 0 ? "up" : "down"}>{pct(mover.change_pct)}</em>
              <small>{mover.reason}</small>
            </button>
          ))}
        </section>
        <section className="panel-card">
          <div className="section-title"><BookOpen size={18} /> Term of the day</div>
          <h2>{landing.term_of_day.term}</h2>
          <p>{landing.term_of_day.eli5}</p>
          <button className="link-button" onClick={() => onAsk(`Explain ${landing.term_of_day.term} simply`)}>
            Explain it <ChevronRight size={16} />
          </button>
        </section>
        <section className="panel-card">
          <div className="section-title"><Info size={18} /> Interesting to know</div>
          {landing.curiosity.map((item) => (
            <p className="note" key={item.text}>{item.text}<span>{item.note}</span></p>
          ))}
        </section>
        <section className="panel-card questions-card">
          <div className="section-title"><BarChart3 size={18} /> Example questions</div>
          {landing.generated_questions.map((item) => (
            <button key={item.text} onClick={() => onAsk(item.prefill_query)}>
              <span>{item.text}</span>
              <small>{item.feature}</small>
            </button>
          ))}
        </section>
      </div>
    </section>
  );
}

function AnswerPanel({ panel, onAsk, onEntity }) {
  return (
    <section className="answer">
      <header className="answer-head">
        <div>
          <div className="intent">{panel.intent.replace("_", " ")}</div>
          <h2>{panel.headline}</h2>
          <p>{panel.eli5}</p>
        </div>
        <div className="meta-pill">{panel.meta.cached ? "cached data" : "live data"}</div>
      </header>

      <div className="entity-row">
        {panel.entities.map((item) => (
          <button key={`${item.kind}-${item.ref}`} onClick={() => onEntity(item)}>{item.text}</button>
        ))}
      </div>

      {panel.intent === "beginner_fees" && <FeeControls panel={panel} onAsk={onAsk} />}

      <div className="blocks">
        {panel.blocks.map((block, index) => <BlockRenderer block={block} onEntity={onEntity} key={`${block.type}-${index}`} />)}
      </div>

      <div className="pros-cons">
        <section><h3><CheckCircle2 size={18} /> What looks good</h3>{panel.pros.map((item) => <p key={item}>{item}</p>)}</section>
        <section><h3><ShieldAlert size={18} /> What to watch</h3>{panel.cons.map((item) => <p key={item}>{item}</p>)}</section>
      </div>

      <FooterList title="Assumptions" items={panel.assumptions} />
      <FooterList title="Honesty notes" items={panel.honesty_notes} />
      <Citations citations={panel.citations} />

      <section className="followups">
        {panel.followups.map((item) => (
          <button key={item.prefill_query} onClick={() => onAsk(item.prefill_query)}>
            <span>{item.text}</span>
            <small>{item.kind}</small>
          </button>
        ))}
      </section>
    </section>
  );
}

function FeeControls({ panel, onAsk }) {
  const initial = useMemo(() => parseFeeInputs(panel.query), [panel.query]);
  const [amount, setAmount] = useState(initial.amount);
  const [years, setYears] = useState(initial.years);
  const [expensePct, setExpensePct] = useState(initial.expensePct);
  const [returnPct, setReturnPct] = useState(initial.returnPct);

  useEffect(() => {
    setAmount(initial.amount);
    setYears(initial.years);
    setExpensePct(initial.expensePct);
    setReturnPct(initial.returnPct);
  }, [initial]);

  function recalc() {
    onAsk(
      `I have $${Number(amount).toLocaleString()} over ${years} years with expense ratio ${expensePct}% and return ${returnPct}% - am I overpaying in fund fees?`
    );
  }

  return (
    <section className="calculator-controls" aria-label="Fee calculator controls">
      <label>Amount<input type="number" min="1" step="500" value={amount} onChange={(event) => setAmount(event.target.value)} /></label>
      <label>Years<input type="number" min="1" max="60" value={years} onChange={(event) => setYears(event.target.value)} /></label>
      <label>Expense ratio %<input type="number" min="0" max="5" step="0.01" value={expensePct} onChange={(event) => setExpensePct(event.target.value)} /></label>
      <label>Gross return %<input type="number" min="0" max="30" step="0.1" value={returnPct} onChange={(event) => setReturnPct(event.target.value)} /></label>
      <button onClick={recalc}>Recalculate</button>
    </section>
  );
}

function BlockRenderer({ block, onEntity }) {
  if (block.type === "kpi") return <Kpi block={block} />;
  if (block.type === "chart.heatmap") return <Heatmap block={block} />;
  if (block.type === "chart.treemap") return <Treemap block={block} onEntity={onEntity} />;
  if (block.type === "chart.bar") return <BarBlock block={block} onEntity={onEntity} />;
  if (block.type === "chart.donut") return <Donut block={block} />;
  if (block.type === "chart.line") return <LineChart block={block} />;
  if (block.type === "radar") return <Radar block={block} />;
  if (block.type === "traffic_light") return <Traffic block={block} />;
  if (block.type === "scorecard") return <Scorecard block={block} />;
  if (block.type === "table") return <TableBlock block={block} />;
  if (block.type === "text") return <article className="block text-block" dangerouslySetInnerHTML={renderMarkdown(block.markdown)} />;
  return null;
}

function openChartEntity(item, onEntity) {
  if (!item.entity_ref || !item.entity_kind || !onEntity) return;
  onEntity({ kind: item.entity_kind, ref: item.entity_ref, text: item.label });
}

function chartEntityKeyDown(event, item, onEntity) {
  if (event.key !== "Enter" && event.key !== " ") return;
  event.preventDefault();
  openChartEntity(item, onEntity);
}

function BlockShell({ block, children, wide = false }) {
  return (
    <article className={`block ${wide ? "wide" : ""}`}>
      {"title" in block && <h3>{block.title}</h3>}
      {children}
      {"takeaway" in block && <p className="takeaway">{block.takeaway}</p>}
    </article>
  );
}

function Kpi({ block }) {
  return (
    <article className="block kpi">
      <span>{block.label}</span>
      <strong>{block.value}</strong>
      <p>{block.takeaway}</p>
    </article>
  );
}

function Heatmap({ block }) {
  const max = Math.max(...block.matrix.flat(), 1);
  return (
    <BlockShell block={block}>
      <div className="heatmap" style={{ gridTemplateColumns: `72px repeat(${block.x_labels.length}, minmax(54px, 1fr))` }}>
        <span />
        {block.x_labels.map((label) => <b key={label}>{label}</b>)}
        {block.y_labels.map((label, row) => (
          <React.Fragment key={label}>
            <b>{label}</b>
            {block.matrix[row].map((value, col) => (
              <span
                className="heat-cell"
                key={`${row}-${col}`}
                style={{ "--heat": value / max }}
                title={`${block.y_labels[row]} vs ${block.x_labels[col]}: ${pct(value)}`}
              >
                {pct(value)}
              </span>
            ))}
          </React.Fragment>
        ))}
      </div>
    </BlockShell>
  );
}

function Treemap({ block, onEntity }) {
  const total = block.items.reduce((sum, item) => sum + item.value, 0) || 1;
  return (
    <BlockShell block={block}>
      <div className="treemap">
        {block.items.map((item) => {
          const clickable = Boolean(item.entity_ref && item.entity_kind && onEntity);
          return (
          <div
            className={clickable ? "clickable-chart-item" : ""}
            key={item.label}
            role={clickable ? "button" : undefined}
            tabIndex={clickable ? 0 : undefined}
            title={`${item.label}: ${fmt(item.value, "%")}${clickable ? " - open ticker card" : ""}`}
            onClick={() => openChartEntity(item, onEntity)}
            onKeyDown={(event) => chartEntityKeyDown(event, item, onEntity)}
            style={{ flexBasis: `${Math.max(18, (item.value / total) * 100)}%` }}
          >
            <strong>{item.label}</strong>
            <span>{fmt(item.value, "%")}</span>
            {item.group && <small>{item.group}</small>}
          </div>
        );})}
      </div>
    </BlockShell>
  );
}

function BarBlock({ block, onEntity }) {
  const max = Math.max(...block.items.map((item) => item.value), 1);
  return (
    <BlockShell block={block} wide={block.items.length > 6}>
      <div className="bars">
        {block.items.map((item) => {
          const clickable = Boolean(item.entity_ref && item.entity_kind && onEntity);
          return (
          <div
            className={`bar-row ${clickable ? "clickable-chart-item" : ""}`}
            key={item.label}
            role={clickable ? "button" : undefined}
            tabIndex={clickable ? 0 : undefined}
            title={`${item.label}: ${fmt(item.value, item.unit || "")}${clickable ? " - open ticker card" : ""}`}
            onClick={() => openChartEntity(item, onEntity)}
            onKeyDown={(event) => chartEntityKeyDown(event, item, onEntity)}
          >
            <span>{item.label}</span>
            <div><i style={{ width: `${(item.value / max) * 100}%` }} /></div>
            <strong>{fmt(item.value, item.unit || "")}</strong>
          </div>
        );})}
      </div>
    </BlockShell>
  );
}

function Donut({ block }) {
  const total = block.items.reduce((sum, item) => sum + item.value, 0) || 1;
  let cursor = 0;
  const colors = ["#3366cc", "#109778", "#d97706", "#7c3aed", "#dc2626", "#64748b", "#0891b2"];
  const gradient = block.items.map((item, index) => {
    const start = cursor;
    cursor += (item.value / total) * 100;
    return `${colors[index % colors.length]} ${start}% ${cursor}%`;
  }).join(", ");
  return (
    <BlockShell block={block}>
      <div className="donut-wrap">
        <div className="donut" style={{ background: `conic-gradient(${gradient})` }}><span>{fmt(total, "%")}</span></div>
        <div className="legend">
          {block.items.map((item, index) => <span key={item.label} title={`${item.label}: ${fmt(item.value, "%")}`}><i style={{ background: colors[index % colors.length] }} />{item.label} {fmt(item.value, "%")}</span>)}
        </div>
      </div>
    </BlockShell>
  );
}

function LineChart({ block }) {
  const all = block.series.flatMap((s) => s.points);
  const minY = Math.min(...all.map((p) => p.y));
  const maxY = Math.max(...all.map((p) => p.y));
  const spread = maxY - minY || 1;
  const colors = ["#3366cc", "#109778", "#d97706"];
  const firstX = all[0]?.x ?? "";
  const lastX = all[all.length - 1]?.x ?? "";
  return (
    <BlockShell block={block}>
      <svg className="line-chart" viewBox="0 0 420 190" role="img" aria-label={block.title}>
        <line className="axis" x1="22" y1="162" x2="398" y2="162" />
        <line className="axis" x1="22" y1="36" x2="22" y2="162" />
        <text className="axis-label" x="22" y="24">{fmt(maxY)}</text>
        <text className="axis-label" x="22" y="180">{String(firstX).slice(0, 10)}</text>
        <text className="axis-label end" x="398" y="180">{String(lastX).slice(0, 10)}</text>
        {block.series.map((series, seriesIndex) => {
          const points = series.points.map((point, index) => {
            const x = 22 + (index / Math.max(series.points.length - 1, 1)) * 376;
            const y = 162 - ((point.y - minY) / spread) * 126;
            return `${x},${y}`;
          }).join(" ");
          return (
            <React.Fragment key={series.name}>
              <polyline points={points} fill="none" stroke={colors[seriesIndex % colors.length]} strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" />
              {series.points.map((point, index) => {
                const x = 22 + (index / Math.max(series.points.length - 1, 1)) * 376;
                const y = 162 - ((point.y - minY) / spread) * 126;
                return <circle key={`${series.name}-${index}`} cx={x} cy={y} r="4.5" fill={colors[seriesIndex % colors.length]}><title>{`${series.name}: ${point.x} = ${fmt(point.y)}`}</title></circle>;
              })}
            </React.Fragment>
          );
        })}
      </svg>
      <div className="legend">{block.series.map((series, index) => <span key={series.name}><i style={{ background: colors[index % colors.length] }} />{series.name}</span>)}</div>
    </BlockShell>
  );
}

function Radar({ block }) {
  return (
    <BlockShell block={block}>
      <div className="radar-list">
        {block.axes.map((axis) => <div key={axis.name}><span>{axis.name}</span><meter min="0" max={axis.max} value={axis.value} /><strong>{axis.value}/{axis.max}</strong></div>)}
      </div>
    </BlockShell>
  );
}

function Traffic({ block }) {
  return (
    <BlockShell block={block}>
      <div className="traffic-list">
        {block.items.map((item) => <span className={item.status} key={item.label}><strong>{item.label}</strong>{item.note}</span>)}
      </div>
    </BlockShell>
  );
}

function Scorecard({ block }) {
  return (
    <BlockShell block={block}>
      <div className="score-list">
        {block.items.map((item) => <p key={item.label}><strong>{item.pass ? "Pass" : "Watch"}</strong><span>{item.label}</span><small>{item.detail}</small></p>)}
      </div>
    </BlockShell>
  );
}

function TableBlock({ block }) {
  return (
    <BlockShell block={block} wide>
      <table><thead><tr>{block.columns.map((col) => <th key={col}>{col}</th>)}</tr></thead><tbody>{block.rows.map((row, index) => <tr key={index}>{row.map((cell, cellIndex) => <td key={cellIndex}>{cell}</td>)}</tr>)}</tbody></table>
    </BlockShell>
  );
}

function FooterList({ title, items }) {
  if (!items?.length) return null;
  return <section className="footer-list"><h3>{title}</h3>{items.map((item) => <p key={item}>{item}</p>)}</section>;
}

function Citations({ citations }) {
  if (!citations?.length) return null;
  return <section className="citations"><h3>Sources</h3>{citations.map((citation) => <a key={citation.id} href={citation.url} target="_blank" rel="noreferrer">{citation.label}<span>{citation.source}{citation.as_of_date ? ` · ${citation.as_of_date}` : ""}</span></a>)}</section>;
}

function EntityModal({ state, onClose }) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <section className="modal" onClick={(event) => event.stopPropagation()}>
        <button className="icon-button" onClick={onClose} aria-label="Close"><X size={18} /></button>
        {state.loading && <p className="modal-loading"><Loader2 className="spin" size={18} /> Loading {state.item.text}</p>}
        {state.error && <p className="error">{state.error}</p>}
        {state.data?.ticker && <TickerCard card={state.data} />}
        {state.data?.term && <TermCard term={state.data} />}
      </section>
    </div>
  );
}

function TickerCard({ card }) {
  return (
    <>
      <div className="modal-title"><span>{card.ticker}</span><h2>{card.name}</h2><strong>{card.currency} {fmt(card.price)} <em className={card.change_pct >= 0 ? "up" : "down"}>{pct(card.change_pct)}</em></strong></div>
      <LineChart block={{ type: "chart.line", title: "Recent price", series: [{ name: card.ticker, points: card.price_series.map((p) => ({ x: p.date, y: p.close })) }], takeaway: "Cached card data for this ticker." }} />
      {card.asset_type === "etf" && <EtfExtras card={card} />}
      {card.snowflake?.length > 0 && <Radar block={{ type: "radar", title: "Snowflake snapshot", axes: card.snowflake.map((axis) => ({ name: axis.axis, value: axis.value, max: axis.max })), takeaway: "Quick visual summary of value, growth, health, past performance, and dividend profile." }} />}
      <div className="traffic-list">{card.traffic.map((item) => <span className={item.status} key={item.label}><strong>{item.label}</strong></span>)}</div>
      {card.percentiles?.length > 0 && <div className="mini-section"><h3>Valuation context</h3>{card.percentiles.map((item) => <p key={item.metric}><strong>{item.metric}</strong> {item.percentile}th percentile · {item.context}</p>)}</div>}
      {card.analyst && <AnalystBand analyst={card.analyst} />}
      {card.fundamentals?.length > 0 && (
        <TableBlock block={{
          type: "table",
          title: "Fundamentals",
          columns: ["Year", "Revenue", "Net income", "Margin", "Debt"],
          rows: card.fundamentals.map((row) => [String(row.year), fmt(row.revenue), fmt(row.net_income), pct(row.margin), fmt(row.debt)]),
          takeaway: "Compact cached fundamentals for the ticker card.",
        }} />
      )}
      {card.news?.length > 0 && <div className="mini-section"><h3>Recent headlines</h3>{card.news.map((item) => <a key={item.title} href={item.url} target="_blank" rel="noreferrer">{item.title}<span>{item.source} · {item.published}</span></a>)}</div>}
      <Citations citations={card.citations} />
    </>
  );
}

function EtfExtras({ card }) {
  return (
    <>
      <div className="mini-section">
        <h3>ETF profile</h3>
        <p><strong>Expense ratio:</strong> {pct(card.expense_ratio || 0)}</p>
        <p><strong>Holdings as of:</strong> {card.holdings_as_of || "cached"}</p>
      </div>
      {card.top_holdings?.length > 0 && (
        <TableBlock block={{
          type: "table",
          title: "Top holdings",
          columns: ["Ticker", "Company", "Weight", "Sector"],
          rows: card.top_holdings.map((row) => [row.ticker, row.name, pct(row.weight), row.sector || "Unknown"]),
          takeaway: "ETF cards show the fund's cached holdings, not just a stock-style price card.",
        }} />
      )}
      {card.sector_exposure?.length > 0 && (
        <Donut block={{
          type: "chart.donut",
          title: "Sector exposure",
          items: card.sector_exposure.slice(0, 7).map((row) => ({ label: row.sector, value: row.weight * 100 })),
          takeaway: "Sector exposure is computed from the cached ETF holdings file.",
        }} />
      )}
    </>
  );
}

function AnalystBand({ analyst }) {
  const range = Math.max(analyst.high - analyst.low, 1);
  const meanOffset = Math.min(100, Math.max(0, ((analyst.mean - analyst.low) / range) * 100));
  return (
    <div className="mini-section analyst-band">
      <h3>Analyst range</h3>
      <div>
        <span>{analyst.currency} {fmt(analyst.low)}</span>
        <i style={{ "--mean": `${meanOffset}%` }} />
        <span>{analyst.currency} {fmt(analyst.high)}</span>
      </div>
      <p>Mean target: <strong>{analyst.currency} {fmt(analyst.mean)}</strong></p>
    </div>
  );
}

function TermCard({ term }) {
  return (
    <>
      <div className="modal-title"><span>Term</span><h2>{term.term}</h2></div>
      <p>{term.eli5}</p>
      <p className="note">{term.example}</p>
      <Citations citations={[term.citation]} />
    </>
  );
}

createRoot(document.getElementById("root")).render(<App />);
