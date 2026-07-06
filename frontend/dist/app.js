const DEMO_QUERY = "I hold VOO, QQQ and VGT - how much do they really overlap?";
const $ = (selector) => document.querySelector(selector);

// Window of `size` items starting at `off`, wrapping around. Shared helper
// for the "More" rotation of news, example questions, curiosity and follow-ups.
function windowSlice(pool, off, size) {
  if (!pool.length) return [];
  return Array.from({ length: Math.min(size, pool.length) }, (_, i) => pool[(off + i) % pool.length]);
}

// Render up to `size` items into a fixed-height list; if the content overflows
// the container, shrink the count (down to 1) so plates keep a stable height
// instead of growing/shrinking as the "More" button pages through items.
// `renderItems(items)` returns the innerHTML for a given slice.
function fitWindow(listNode, pool, off, size, renderItems) {
  for (let n = size; n >= 1; n--) {
    listNode.innerHTML = renderItems(windowSlice(pool, off, n));
    if (listNode.scrollHeight <= listNode.clientHeight || n === 1) break;
  }
}
const ASK_SUGGESTIONS = [
  { feature: "overlap", text: "VOO + QQQ + VGT overlap", query: DEMO_QUERY },
  { feature: "forensic", text: "NVDA red flags", query: "Should I buy NVDA? Show forensic red flags and the bear case." },
  { feature: "fees", text: "Fee drag calculator", query: "I have $50,000 over 30 years with expense ratio 0.25% and return 6% - am I overpaying in fund fees?" },
  { feature: "growth", text: "What if TSLA", query: "What if I invested $10,000 in TSLA 5 years ago?" },
  { feature: "compare", text: "NVDA vs AMD", query: "Compare NVDA vs AMD side by side." },
  { feature: "ticker", text: "TSLA ticker card", query: "Tell me about TSLA." },
  { feature: "term", text: "P/E percentile", query: "Explain P/E percentile in simple terms." },
];

// --- Risk-profile quiz (investor-profile onboarding, STRETCH T13.2) ------- //
// Six questions, each 1-3 plus a neutral "Don't know" (2). Sum range 6..18 maps
// to a profile via profileFromScore (kept in sync with personalize.py).
const DONT_KNOW = { text: "Don't know", score: 2 };
const RISK_QUIZ = [
  {
    key: "horizon",
    question: "When will you likely need this money?",
    help: "Your time horizon is the biggest driver: money you won't touch for a decade can ride out dips that short-term money can't.",
    options: [
      { text: "Within 3 years", score: 1 },
      { text: "3 to 10 years", score: 2 },
      { text: "10+ years", score: 3 },
      DONT_KNOW,
    ],
  },
  {
    key: "tolerance",
    question: "Your holdings drop 20% in a month. You...",
    help: "This gauges your emotional tolerance for volatility. Selling in a panic locks in losses; the 'right' answer is the one you'd actually do.",
    options: [
      { text: "Sell to stop the bleeding", score: 1 },
      { text: "Hold and wait it out", score: 2 },
      { text: "Buy more on the dip", score: 3 },
      DONT_KNOW,
    ],
  },
  {
    key: "goal",
    question: "What matters most to you?",
    help: "Capital preservation, steady growth, or maximum long-term return — this sets how much risk is worth taking for you.",
    options: [
      { text: "Protect what I have", score: 1 },
      { text: "Steady, balanced growth", score: 2 },
      { text: "Maximize long-term returns", score: 3 },
      DONT_KNOW,
    ],
  },
  {
    key: "experience",
    question: "How much investing experience do you have?",
    help: "More experience usually means more comfort holding through swings — but it's about your comfort, not being an expert.",
    options: [
      { text: "This is new to me", score: 1 },
      { text: "Some — I hold funds", score: 2 },
      { text: "Lots — I trade actively", score: 3 },
      DONT_KNOW,
    ],
  },
  {
    key: "savings_share",
    question: "Roughly what share of your savings is this money?",
    help: "If this is most of your safety net, a cautious mix protects you. If it's a small slice, you can afford more risk.",
    options: [
      { text: "Most of my savings", score: 1 },
      { text: "About half", score: 2 },
      { text: "A small slice", score: 3 },
      DONT_KNOW,
    ],
  },
  {
    key: "liquidity",
    question: "How likely are you to withdraw early?",
    help: "Money you might pull out on short notice shouldn't sit in volatile assets that could be down when you need it.",
    options: [
      { text: "Quite likely", score: 1 },
      { text: "Maybe, if needed", score: 2 },
      { text: "Very unlikely", score: 3 },
      DONT_KNOW,
    ],
  },
];
let riskAnswers = {};

// --- Top navigation (finance-app style) ---------------------------------- //
const NAV_ITEMS = [
  { label: "Home", nav: "home" },
  { label: "Ticker", query: "Tell me about NVDA." },
  { label: "Compare", query: "Compare NVDA vs AMD side by side." },
  { label: "Overlap", query: DEMO_QUERY },
  { label: "Fee calculator", query: "I have $50,000 over 30 years with expense ratio 0.25% and return 6% - am I overpaying in fund fees?" },
  { label: "Red-flag screen", query: "Should I buy NVDA? Show forensic red flags and the bear case." },
  { label: "Learn", nav: "learn" },
];

function renderNav() {
  const node = $("#nav-links");
  if (!node) return;
  node.innerHTML = NAV_ITEMS.map((item) =>
    item.nav
      ? `<button class="nav-link" data-nav="${esc(item.nav)}">${esc(item.label)}</button>`
      : queryLink(item.query, esc(item.label), "nav-link")
  ).join("");
}

// M8-UI: identity chip in the topnav. You always browse anonymously as "Guest"
// (no account/email/PII). Once a one-time code has linked this browser to saved
// context, the chip shows "· Synced". "Sign in" here means: carry a guest's saved
// context across devices via that code — not a real account.
function isSynced() {
  try { return localStorage.getItem("synced") === "1"; } catch { return false; }
}
function setSynced(on) {
  try { on ? localStorage.setItem("synced", "1") : localStorage.removeItem("synced"); } catch { /* ignore */ }
}
const AVATAR_SVG = `<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path fill="currentColor" d="M12 12a5 5 0 1 0-5-5 5 5 0 0 0 5 5Zm0 2c-4.4 0-8 2.2-8 5v1h16v-1c0-2.8-3.6-5-8-5Z"/></svg>`;
function renderIdentity() {
  const node = $("#identity");
  if (!node) return;
  const synced = isSynced();
  node.innerHTML = `
    <button class="identity-chip" id="identity-chip" title="You're browsing anonymously as a guest — no account or email needed">
      <span class="avatar" aria-hidden="true">${AVATAR_SVG}</span>
      <span class="identity-name">Guest${synced ? `<span class="synced-badge">Synced</span>` : ""}</span>
    </button>
    <button class="nav-link identity-signin" id="identity-signin">Sign in</button>`;
}

// M8-UI: a clean "Sign in" modal that replaces the old prompt()/alert() flow.
// It wraps the existing guest-code endpoints: redeem a code to adopt saved
// context here, or mint a code to continue on another device. Still zero PII.
function openSignInModal() {
  $("#modal").innerHTML = `<div class="modal-backdrop"><section class="modal signin-modal">
    <button class="icon-button" data-close>Close</button>
    <div class="modal-title"><span>Guest access</span><h2>Sign in</h2></div>
    <p class="note">No account, email or password. You browse anonymously as <strong>Guest</strong>. To keep your saved context (history + risk profile) when you switch devices, use a one-time code.</p>
    <div class="signin-section">
      <label class="signin-label" for="signin-code">Have a code? Sign in</label>
      <div class="signin-row">
        <input id="signin-code" placeholder="XXXX-XXXX-XXXX" autocomplete="off" autocapitalize="characters" spellcheck="false" />
        <button data-signin-submit>Sign in</button>
      </div>
      <p class="signin-msg" id="signin-msg" aria-live="polite"></p>
    </div>
    <div class="signin-divider"><span>or</span></div>
    <div class="signin-section">
      <label class="signin-label">Switching devices later? Get a code now</label>
      <button class="signin-secondary" data-get-code>Get my recovery code</button>
      <p class="signin-msg" id="signin-code-out" aria-live="polite"></p>
    </div>
    <div class="signin-footer">
      <button class="link-button" data-clear-data-modal title="Delete all stored preferences and conversation history for this browser">Clear my data</button>
    </div>
  </section></div>`;
}

function goHome({ push = true } = {}) {
  document.body.classList.remove("answering");
  $("#answer").innerHTML = "";
  $("#answer").className = "answer";
  $("#error").innerHTML = "";
  hideAskSuggestions();
  $("#query").value = "";
  if (push && location.hash) history.pushState({}, "", location.pathname + location.search);
  window.scrollTo(0, 0); // instant: avoid "rendered at bottom then slides up"
}

// --- Learn: glossary/FAQ index screen (all static, zero LLM) ------------- //
const LEARN_GROUPS = [
  { title: "Basics", slugs: ["index-fund", "exchange-traded-fund-etf", "diversification", "compound-interest", "dividend", "pe-ratio"] },
  { title: "Fees & funds", slugs: ["expense-ratio", "portfolio-overlap", "concentration", "dividend-safety", "market-movers"] },
  { title: "Forensic scores", slugs: ["altman-z-score", "beneish-m-score", "piotroski-f-score", "form-4"] },
];

function showLearn() {
  document.body.classList.add("answering"); // reuse landing-collapse; hides hero
  hideAskSuggestions();
  $("#error").innerHTML = "";
  $("#answer").className = "answer";
  $("#answer").innerHTML = `<header class="answer-head"><div><div class="intent">learn</div><h2>Learn the basics</h2><p>Plain-English explainers with examples and sources. Click any term for details.</p></div></header><div class="learn-loading">Loading glossary...</div>`;
  window.scrollTo(0, 0); // landing is hidden; #answer is already at the top
  apiGet("/api/glossary")
    .then((data) => renderLearn(data.terms || []))
    .catch((error) => { $("#answer").innerHTML += `<div class="error">${esc(error.message)}</div>`; });
}

function renderLearn(terms) {
  const bySlug = Object.fromEntries(terms.map((t) => [t.slug, t]));
  const grouped = new Set();
  const groupsHtml = LEARN_GROUPS.map((group) => {
    const cards = group.slugs
      .map((slug) => bySlug[slug])
      .filter(Boolean)
      .map((t) => { grouped.add(t.slug); return learnCard(t); })
      .join("");
    return cards ? `<section class="learn-group"><h3>${esc(group.title)}</h3><div class="learn-grid">${cards}</div></section>` : "";
  }).join("");
  // Any terms not placed in a group fall into "More".
  const rest = terms.filter((t) => !grouped.has(t.slug)).map(learnCard).join("");
  const restHtml = rest ? `<section class="learn-group"><h3>More</h3><div class="learn-grid">${rest}</div></section>` : "";
  $("#answer").innerHTML = `<header class="answer-head"><div><div class="intent">learn</div><h2>Learn the basics</h2><p>Plain-English explainers with examples and sources. Click any term for details.</p></div></header>${groupsHtml}${restHtml}`;
}

function learnCard(t) {
  return `<button class="learn-card" data-entity-kind="term" data-entity-ref="${esc(t.slug)}"><strong>${esc(t.term)}</strong><span>${esc(t.eli5)}</span></button>`;
}

function getRiskProfile() {
  try {
    return localStorage.getItem("riskProfile") || null;
  } catch {
    return null;
  }
}

function setRiskProfile(profile) {
  try {
    if (profile) localStorage.setItem("riskProfile", profile);
    else localStorage.removeItem("riskProfile");
  } catch {
    /* localStorage unavailable — profile stays in-memory only */
  }
}

// Recent questions (newest first, unique, capped) for the search suggestions.
function getRecent() {
  try {
    return JSON.parse(localStorage.getItem("recentQueries") || "[]");
  } catch {
    return [];
  }
}

function pushRecent(query) {
  const q = query.trim();
  if (!q) return;
  try {
    const recent = [q, ...getRecent().filter((r) => r !== q)].slice(0, 6);
    localStorage.setItem("recentQueries", JSON.stringify(recent));
  } catch {
    /* localStorage unavailable — recents stay empty */
  }
}

// 6 questions x 1-3 (Don't know = 2) -> sum 6..18. Keep thresholds in sync with
// personalize.risk_profile_from_score.
function profileFromScore(score) {
  if (score <= 10) return "conservative";
  if (score <= 14) return "balanced";
  return "aggressive";
}

function updateRiskChip() {
  const button = $("#risk-profile");
  if (button) {
    const profile = getRiskProfile();
    button.classList.toggle("active", Boolean(profile));
    button.textContent = profile ? `Risk: ${profile}` : "Set risk profile";
  }
  const status = $("#profile-status");
  if (status) {
    const profile = getRiskProfile();
    status.textContent = profile
      ? `Saved: ${profile}. Answers are now framed to your risk tolerance — retake anytime.`
      : "Answer 6 quick questions so every answer is framed to your risk tolerance.";
  }
}

function openQuiz() {
  riskAnswers = {};
  const modal = $("#modal");
  modal.innerHTML = `<div class="modal-backdrop"><section class="modal quiz-modal">
    <button class="icon-button" data-close>Close</button>
    <div class="modal-title"><span>Your investor profile</span><h2>A few questions to tune answers to you</h2></div>
    <p class="note">Six quick questions. We use this only to frame the same grounded numbers — never to give buy/sell advice. Not sure? Pick "Don't know".</p>
    <div class="quiz-body">${RISK_QUIZ.map((q, qi) => `
      <fieldset class="quiz-q" data-q="${qi}">
        <legend>${esc(q.question)}</legend>
        ${q.options.map((opt) => `<button class="quiz-opt" data-quiz-q="${qi}" data-quiz-score="${opt.score}">${esc(opt.text)}</button>`).join("")}
        ${q.help ? `<details class="quiz-help"><summary>What does this mean?</summary><p>${esc(q.help)}</p></details>` : ""}
      </fieldset>`).join("")}</div>
    <div class="quiz-actions">
      <button class="link-button" data-quiz-clear>Clear profile</button>
      <button id="quiz-submit" disabled>Save profile</button>
    </div>
  </section></div>`;
}

function selectQuizOption(qi, score, buttonEl) {
  riskAnswers[qi] = Number(score);
  buttonEl.parentElement.querySelectorAll(".quiz-opt").forEach((el) => el.classList.remove("selected"));
  buttonEl.classList.add("selected");
  const submit = $("#quiz-submit");
  if (submit) submit.disabled = Object.keys(riskAnswers).length < RISK_QUIZ.length;
}

function submitQuiz() {
  const total = Object.values(riskAnswers).reduce((sum, value) => sum + value, 0);
  const profile = profileFromScore(total);
  setRiskProfile(profile);
  updateRiskChip();
  $("#modal").innerHTML = "";
  // Only re-run when an answer is on screen; on Home just update the card.
  if (document.body.classList.contains("answering")) runQuery($("#query").value, { push: false });
}

function pct(value) {
  return `${(Number(value) * 100).toFixed(1).replace(".0", "")}%`;
}

function fmt(value, unit = "") {
  const number = Number(value);
  const rendered = Number.isFinite(number) ? number.toLocaleString(undefined, { maximumFractionDigits: 1 }) : value;
  return `${rendered}${unit || ""}`;
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

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
}

// Query navigator rendered as an <a href="#q=..."> so Ctrl/Cmd/middle-click
// opens the same question in a new tab. Plain click is intercepted by the
// delegated handler (runQuery + pushState). Keeps data-query for the handler.
// Readable deep links: spaces become "_" instead of "%20". encodeURIComponent
// never emits "_", so decoding is unambiguous for our (underscore-free) queries.
function encodeQ(q) {
  return encodeURIComponent(q).replaceAll("%20", "_");
}
function decodeQ(h) {
  return decodeURIComponent(h.replaceAll("_", "%20"));
}

// The hash is the single source of truth: #q=<query>&i=<intent>. Encoding the
// intent here means Back/Forward and shared links reproduce the exact cache key.
function buildHash(query, intent = null) {
  return `#q=${encodeQ(query)}${intent ? `&i=${intent}` : ""}`;
}

// Forum-style deterministic link: #/t/<seq>/<slug> (seq = topic number from the
// store, slug = readable title). Reloading/sharing this replays the stored panel
// with no LLM recompute. Legacy #q= links still work as an entry alias.
function buildTurnHash(seq, slug) {
  return `#/t/${seq}${slug ? `/${slug}` : ""}`;
}
function parseHash() {
  const t = location.hash.match(/^#\/t\/(\d+)/);
  if (t) return { seq: parseInt(t[1], 10) };
  const q = decodeQ((location.hash.match(/[#&]q=([^&]+)/) || [])[1] || "");
  const intent = (location.hash.match(/[#&]i=([^&]+)/) || [])[1] || null;
  return { q, intent };
}

// Refine actions (detail/simpler) re-ask the SAME underlying question with a new
// directive. Strip any directive already applied so a second click REPLACES it
// rather than stacking ("Explain more simply: Answer in more detail: …").
function baseQuestion(q) {
  let s = (q || "").trim();
  let prev;
  do {
    prev = s;
    s = s.replace(/^(?:Answer in more detail|Explain more simply)\s*:\s*/i, "").trim();
  } while (s !== prev);
  return s;
}

function queryLink(query, inner, className = "", intent = null) {
  const attr = intent ? ` data-intent="${intent}"` : "";
  return `<a class="${className}" href="${buildHash(query, intent)}" data-query="${esc(query)}"${attr}>${inner}</a>`;
}

// Inline formatting shared by renderMarkdown and single-line fields (headline,
// eli5). Escapes first, then applies `code`, **strong**, and [[text|kind|ref]]
// entity chips. Kept top-level so the headline renders chips too (not raw [[…]]).
function renderInline(text) {
  return esc(text)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\[\[([^|\]]+)\|(ticker|term)\|([^\]]+)\]\]/g, (m, txt, kind, ref) =>
      kind === "ticker"
        ? `<button class="entity-inline chip-stock" data-entity-kind="ticker" data-entity-ref="${ref}">${txt}</button>`
        : `<button class="entity-inline chip-term" data-term-ask="${txt}" data-term-ref="${ref}" title="Ask: explain ${txt}">${txt}</button>`)
    // Fallback for the bare [[SYMBOL]] form the LLM sometimes emits: treat it as a
    // ticker chip (ref = the symbol itself) so it never renders as raw brackets.
    .replace(/\[\[([^|\]]+)\]\]/g, (m, sym) => {
      const ref = sym.trim().toUpperCase();
      return `<button class="entity-inline chip-stock" data-entity-kind="ticker" data-entity-ref="${ref}">${sym}</button>`;
    });
}

function renderMarkdown(markdown = "") {
  // Pass raw lines to inline(): renderInline() escapes each one itself, so we
  // must NOT esc() here first or entities/ampersands would be double-escaped.
  const lines = String(markdown ?? "").split(/\r?\n/);
  const html = [];
  let list = [];
  let listTag = "ul";
  const inline = (text) => renderInline(text);
  const flushList = () => {
    if (!list.length) return;
    html.push(`<${listTag}>${list.map((item) => `<li>${inline(item)}</li>`).join("")}</${listTag}>`);
    list = [];
  };
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) {
      flushList();
      continue;
    }
    const heading = trimmed.match(/^(#{1,4})\s+(.*)$/);
    if (heading) {
      flushList();
      const level = Math.min(heading[1].length + 1, 5); // # -> h2 ... #### -> h5
      html.push(`<h${level}>${inline(heading[2])}</h${level}>`);
      continue;
    }
    const ordered = trimmed.match(/^\d+[.)]\s+(.*)$/);
    if (ordered) {
      if (listTag !== "ol") flushList();
      listTag = "ol";
      list.push(ordered[1]);
      continue;
    }
    if (trimmed.startsWith("- ") || trimmed.startsWith("* ")) {
      if (listTag !== "ul") flushList();
      listTag = "ul";
      list.push(trimmed.slice(2));
      continue;
    }
    flushList();
    html.push(`<p>${inline(trimmed)}</p>`);
  }
  flushList();
  return html.join("");
}

async function apiGet(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

// Client-side answer cache so repeats and Back/Forward render without a fetch.
// Keyed by query + risk profile (same panel personalization as the backend key).
const PANEL_CACHE = new Map();
const panelCacheKey = (query, intent = null) => `${query.trim().toLowerCase()}|${getRiskProfile() || ""}|${intent || ""}`;

// Fetched ticker cards, so the modal's explain buttons can read their numbers.
const TICKER_CARDS = new Map();

// Stable per-browser session id so the backend can rehydrate the last answer's
// context for refine/follow-up actions after a reload or on a shared link.
function getSessionId() {
  let id = localStorage.getItem("sessionId");
  if (!id) {
    id = (crypto.randomUUID && crypto.randomUUID()) || `s-${Date.now()}-${Math.floor(Math.random() * 1e9)}`;
    localStorage.setItem("sessionId", id);
  }
  return id;
}

// M8: adopt a canonical guest id (after redeeming a recovery code on a new
// device) so this browser's turns/profile map into that user's saved context.
function setSessionId(id) {
  try { localStorage.setItem("sessionId", id); } catch { /* in-memory only */ }
  window.__threadId = null; // next question starts a fresh thread under the adopted id
}

// A thread = one conversation. A fresh landing question starts a new thread;
// follow-ups inherit it, so the backend can reassemble the parent-chain context.
function newThread() {
  window.__threadId = (crypto.randomUUID && crypto.randomUUID()) || `t-${Date.now()}-${Math.floor(Math.random() * 1e9)}`;
  return window.__threadId;
}
function getThreadId() {
  return window.__threadId || newThread();
}

async function ask(query, { intent = null, parentSeq = null } = {}) {
  const body = { query, risk_profile: getRiskProfile(), session_id: getSessionId(), thread_id: getThreadId() };
  if (intent) body.intent = intent;
  if (parentSeq != null) body.parent_turn_id = parentSeq;
  const response = await fetch("/api/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    let detail = await response.text();
    try { detail = JSON.parse(detail).detail || detail; } catch {}
    const err = new Error(detail || "Request failed");
    err.status = response.status;
    throw err;
  }
  return response.json();
}

// Privacy "clear my data": delete the server-side turns+profile for this guest,
// then wipe the local browser state so nothing personal is left anywhere.
async function clearMyData() {
  if (!window.confirm("Delete all stored preferences and conversation history for this browser? This can't be undone.")) return;
  const userId = getSessionId();
  try {
    await fetch(`/api/me/${encodeURIComponent(userId)}`, { method: "DELETE" });
  } catch {
    /* best-effort: still clear the client below so the guest identity is reset */
  }
  try {
    localStorage.removeItem("sessionId");
    localStorage.removeItem("riskProfile");
    localStorage.removeItem("recentQueries");
    localStorage.removeItem("synced");
  } catch { /* localStorage unavailable — nothing to clear */ }
  window.__threadId = null; // next question starts a brand-new anonymous thread
  updateRiskChip();
  renderIdentity();
  $("#modal").innerHTML = ""; // close the Sign-in modal if the action came from there
  const note = $("#privacy-note");
  if (note) note.innerHTML = "Your stored data was deleted. A fresh anonymous session will start with your next question.";
}

// M8: mint a recovery code and show it inline in the Sign-in modal (no PII).
// The code is the only thing that resolves back to this guest id.
async function mintRecoveryCode() {
  const out = $("#signin-code-out");
  if (out) out.textContent = "Creating a code…";
  try {
    const res = await fetch("/api/claim", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: getSessionId() }),
    });
    if (!res.ok) throw new Error("claim failed");
    const { recovery_code } = await res.json();
    setSynced(true);
    renderIdentity();
    if (out) out.innerHTML = `Your code (write it down — shown once): <strong class="code-value">${esc(recovery_code)}</strong><br><small>Enter it under “Have a code?” on your other device to continue with this saved context.</small>`;
  } catch {
    if (out) out.textContent = "Couldn't create a code right now. Please try again.";
  }
}

// M8: redeem a code typed into the Sign-in modal → adopt that guest id here, so
// the saved context follows the user across devices.
async function submitSignIn() {
  const input = $("#signin-code");
  const msg = $("#signin-msg");
  const code = input ? input.value.trim() : "";
  if (!code) { if (msg) msg.textContent = "Enter your recovery code first."; return; }
  if (msg) msg.textContent = "Signing in…";
  try {
    const res = await fetch("/api/claim/redeem", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ recovery_code: code }),
    });
    if (res.status === 404) { if (msg) msg.textContent = "That code wasn't recognized."; return; }
    if (!res.ok) throw new Error("redeem failed");
    const { user_id } = await res.json();
    setSessionId(user_id);
    setSynced(true);
    updateRiskChip();
    renderIdentity();
    if (msg) msg.innerHTML = `<span class="ok">Signed in — your saved context is now on this device. Ask a question to continue where you left off.</span>`;
  } catch {
    if (msg) msg.textContent = "Couldn't sign in right now. Please try again.";
  }
}

// Popup shown when a request fails because the LLM backend is unavailable.
function showLlmUnavailableModal(message) {
  $("#modal").innerHTML = `<div class="modal-backdrop"><section class="modal error-modal">
    <button class="icon-button" data-close>Close</button>
    <div class="modal-title"><span>Service notice</span><h2>AI service unavailable</h2></div>
    <p>This answer needs the AI model, which isn't responding right now.</p>
    <p class="note">${esc(message || "LLM unavailable")}</p>
    <p>Please try again in a moment. Deterministic tools (ticker cards, forensic scores, overlap) still work.</p>
  </section></div>`;
}

function renderLanding(landing) {
  $("#landing").innerHTML = `
    <div class="hero-copy">
      <div class="eyebrow">Market desk</div>
      <h1>Retail Investor Agent</h1>
      <p>Clear answers you can see — charts, citations, and clickable drilldowns.</p>
    </div>
    <div class="market-strip">
      ${landing.market.indices.map((index) => `
        <div class="quote">
          <span>${esc(index.name)}</span>
          <strong>${fmt(index.value)}</strong>
          <em class="${index.change_pct >= 0 ? "up" : "down"}">${pct(index.change_pct)}</em>
        </div>
      `).join("")}
    </div>
    <section class="profile-card" aria-label="Your investor profile">
      <div class="profile-copy">
        <div class="section-title">Your investor profile</div>
        <p class="profile-status" id="profile-status">Answer 6 quick questions so every answer is framed to your risk tolerance.</p>
        <p class="privacy-note" id="privacy-note">No sign-up. We store only anonymous preferences (no name, no email) to remember your context across visits. Use <strong>Sign in</strong> (top right) to carry your context to another device, or clear it anytime.</p>
      </div>
      <button id="risk-profile" class="risk-chip" title="Answer 6 questions so answers match your risk tolerance">Set risk profile</button>
    </section>
    <div class="landing-grid">
      <section class="rounded-2xl shadow-sm hover:shadow-md transition-shadow duration-200 panel-card chart-card">
        <div class="section-title">Chart of the day</div>
        ${renderBlock(landing.chart_of_day)}
      </section>
      <section class="rounded-2xl shadow-sm hover:shadow-md transition-shadow duration-200 panel-card">
        <div class="section-title">Movers and why</div>
        ${landing.market.movers.map((mover) => queryLink(
          `Should I buy ${mover.ticker}? Show forensic red flags and the bear case.`,
          `<span><strong>${esc(mover.ticker)}</strong> ${esc(mover.name)}</span>
            <em class="${mover.change_pct >= 0 ? "up" : "down"}">${pct(mover.change_pct)}</em>
            <small>${esc(mover.reason)}</small>`,
          "mover"
        )).join("")}
      </section>
      <section class="rounded-2xl shadow-sm hover:shadow-md transition-shadow duration-200 panel-card">
        <div class="section-title">Term of the day</div>
        <h2>${esc(landing.term_of_day.term)}</h2>
        <p>${esc(landing.term_of_day.eli5)}</p>
        ${queryLink(`Explain ${landing.term_of_day.term} simply`, "Explain it", "link-button")}
      </section>
      <section class="rounded-2xl shadow-sm hover:shadow-md transition-shadow duration-200 panel-card market-map-card" id="market-map">
        <div class="market-map-body note">Loading market map...</div>
      </section>
      <section class="rounded-2xl shadow-sm hover:shadow-md transition-shadow duration-200 panel-card news-shelf" id="news-shelf">
        <div class="section-title">Latest headlines <span class="demo-badge">cached</span><button class="more-btn" data-news-more>More</button></div>
        <div class="news-list">Loading headlines...</div>
      </section>
      <section class="rounded-2xl shadow-sm hover:shadow-md transition-shadow duration-200 panel-card">
        <div class="section-title">Interesting to know<button class="more-btn" data-curiosity-more>More</button></div>
        <div id="curiosity-list"></div>
      </section>
      <section class="rounded-2xl shadow-sm hover:shadow-md transition-shadow duration-200 panel-card questions-card">
        <div class="section-title">Want to learn more<button class="more-btn" data-questions-more>More</button></div>
        <div id="questions-list"></div>
      </section>
    </div>`;
  CURIOSITY_POOL = landing.curiosity || [];
  cOff = 0;
  renderCuriosityWindow();
  QUESTIONS_POOL = landing.generated_questions || [];
  qOff = 0;
  renderQuestionsWindow();
  flushPlotly();
  loadNewsShelf();
  loadMarketMap();
  updateRiskChip(); // reflect saved profile on the moved Home profile card
}

function loadMarketMap() {
  apiGet("/api/market-map")
    .then((block) => {
      const node = $("#market-map .market-map-body");
      if (!node) return;
      node.innerHTML = renderBlock(block);
      flushPlotly();
    })
    .catch(() => {});
}

// Landing news shelf: demo headlines with a clickable ticker badge each.
function loadNewsShelf() {
  apiGet("/api/news")
    .then((data) => {
      NEWS_POOL = data.market || [];
      newsOff = 0;
      renderNewsWindow();
    })
    .catch(() => {});
}

let NEWS_POOL = [];
let newsOff = 0;

function renderNewsWindow() {
  const list = $("#news-shelf .news-list");
  if (!list) return;
  if (!NEWS_POOL.length) { list.innerHTML = `<p class="note">No headlines available.</p>`; return; }
  fitWindow(list, NEWS_POOL, newsOff, 4, (items) => items
    .map((item) => {
      const badge = item.ticker
        ? `<button class="news-ticker" data-entity-kind="ticker" data-entity-ref="${esc(item.ticker)}">${esc(item.ticker)}</button>`
        : "";
      return `<div class="news-item">
        <a class="news-title" href="${esc(item.url)}" target="_blank" rel="noreferrer">${esc(item.title)}</a>
        <small>${badge}<span>${esc(item.source)} · ${esc(item.published)}</span></small>
      </div>`;
    })
    .join(""));
}

let CURIOSITY_POOL = [];
let cOff = 0;

function renderCuriosityWindow() {
  const node = $("#curiosity-list");
  if (!node) return;
  fitWindow(node, CURIOSITY_POOL, cOff, 3, (items) => items
    .map((item) => `<div class="curiosity-item">
      <p>${esc(item.text)}</p>
      <small>${esc(item.note)}</small>
      <button class="explain-more" data-curiosity-ask="${esc(item.text)}" title="Ask: Tell me more about this">Learn more</button>
    </div>`)
    .join(""));
}

let QUESTIONS_POOL = [];
let qOff = 0;

function renderQuestionsWindow() {
  const node = $("#questions-list");
  if (!node) return;
  fitWindow(node, QUESTIONS_POOL, qOff, 4, (items) => items
    .map((item) => queryLink(item.prefill_query, `<span>${esc(item.text)}</span><small>${esc(item.feature)}</small>`))
    .join(""));
}

// Follow-up rotation state: grouped by kind, with per-kind offset.
const FOLLOWUP_KINDS = ["deeper", "wider", "simpler"];
const FOLLOWUP_LABELS = { deeper: "Go deeper", wider: "Explore wider", simpler: "Explain simpler" };
let __followupGroups = { deeper: [], wider: [], simpler: [] };
let __followupOffsets = { deeper: 0, wider: 0, simpler: 0 };

function renderFollowupSlots(followups) {
  __followupGroups = { deeper: [], wider: [], simpler: [] };
  __followupOffsets = { deeper: 0, wider: 0, simpler: 0 };
  for (const f of (followups || [])) {
    const k = f.kind;
    if (__followupGroups[k]) __followupGroups[k].push(f);
  }
  return FOLLOWUP_KINDS.map((kind) => renderFollowupSlot(kind)).join("");
}

function renderFollowupSlot(kind) {
  const group = __followupGroups[kind] || [];
  if (!group.length) return "";
  const off = __followupOffsets[kind];
  const item = group[off % group.length];
  // Every slot with more than one item gets a "More" rotation pill — including
  // "Explain simpler", so all three columns stay visually consistent.
  const moreBtn = group.length > 1
    ? `<button class="more-btn followup-more-btn" data-followup-more="${esc(kind)}">More</button>`
    : "";
  // Column card: kind label on top, the self-contained question link (a #q= link,
  // so Back/Forward replay it), the small "More" rotation pill at the bottom.
  return `<div class="followup-slot" data-followup-kind="${esc(kind)}">
    <span class="followup-label">${esc(FOLLOWUP_LABELS[kind] || kind)}</span>
    ${queryLink(item.prefill_query, `<span>${esc(item.text)}</span>`)}
    ${moreBtn}
  </div>`;
}

// Colour-code an entity chip by type so ETFs, stocks and terms are tellable
// apart at a glance (subtle left-border accent, not a loud fill).
function entityChipClass(item) {
  if (item.kind === "term") return "chip-term";
  if (OVERLAP_FUNDS.includes((item.ref || "").toUpperCase())) return "chip-etf";
  return "chip-stock";
}

let __lastPanelTickers = [];
let __pendingFollowup = null; // the prior query awaiting the user's typed follow-up question

// A small chip under the ask bar showing the follow-up is active.
function showFollowupHint() {
  const hint = $("#followup-hint");
  if (!hint) return;
  hint.innerHTML = `<span class="followup-hint-chip">Follow-up <button data-followup-cancel title="Cancel">✕</button></span>`;
}

function clearFollowup() {
  __pendingFollowup = null;
  const q = $("#query");
  if (q) q.placeholder = "";
  const hint = $("#followup-hint");
  if (hint) hint.innerHTML = "";
}

// Single entry point for the ask bar (button click / Enter). A pending follow-up
// becomes a NEW turn whose parent is the current topic — the backend reassembles
// the prior answer + tickers + profile from that parent chain (one mechanism, no
// query-string folding).
function submitFromBar() {
  const value = $("#query").value;
  if (__pendingFollowup && value.trim()) {
    clearFollowup();
    runQuery(value, { intent: "generic", parentSeq: window.__currentTurnSeq ?? null });
    return;
  }
  runQuery();
}

// True when the panel carries an LLM prose answer (a text block) — the refine /
// follow-up action bar only makes sense there, not on pure calculator panels.
function panelHasLlmAnswer(panel) {
  return (panel.blocks || []).some((b) => b.type === "text" && (b.markdown || "").trim());
}

function renderPanel(panel) {
  window.__currentPanel = panel; // Part C: block "Explain" reads block data + query
  __lastPanelTickers = (panel.entities || []).filter((e) => e.kind === "ticker").map((e) => e.ref).filter(Boolean);
  $("#answer").className = "answer";
  $("#answer").innerHTML = `
    <header class="answer-head">
      <div>
        <div class="intent">${esc(panel.intent.replace("_", " "))}</div>
        <h2>${renderInline(panel.headline)}</h2>
        <p>${renderInline(panel.eli5)}</p>
      </div>
      <div class="pill-stack">
        ${getRiskProfile() ? `<div class="meta-pill profile-pill">tuned: ${esc(getRiskProfile())}</div>` : ""}
        <div class="meta-pill">${panel.meta.cached ? "cached data" : "live data"}</div>
      </div>
    </header>
    <div class="entity-row">
      ${panel.entities.map((item) => `<button class="${entityChipClass(item)}" data-entity-kind="${esc(item.kind)}" data-entity-ref="${esc(item.ref)}">${esc(item.text)}</button>`).join("")}
    </div>
    ${panel.intent === "beginner_fees" ? renderFeeControls(panel) : ""}
    ${panel.intent === "overlap" ? renderOverlapControls(panel) : ""}
    ${panel.intent === "compare" ? renderCompareControls(panel) : ""}
    ${panel.intent === "forensic" ? renderForensicControls(panel) : ""}
    <div class="blocks">${renderBlocks(panel)}</div>
    <div class="pros-cons">
      <section><h3>What looks good</h3><ul>${panel.pros.map((item) => `<li><span>${esc(item)}</span><button class="explain-more" data-proscons-ask="${esc(item)}" title="Ask about this point">Explain</button></li>`).join("")}</ul></section>
      <section><h3>What to watch</h3><ul>${panel.cons.map((item) => `<li><span>${esc(item)}</span><button class="explain-more" data-proscons-ask="${esc(item)}" title="Ask about this point">Explain</button></li>`).join("")}</ul></section>
    </div>
    ${renderFooterList("Assumptions", panel.assumptions)}
    ${renderFooterList("Honesty notes", panel.honesty_notes)}
    ${renderCitations(panel.citations)}
    <section class="followups">
      ${renderFollowupSlots(panel.followups)}
    </section>`;
  flushPlotly();
}

function renderFeeControls(panel) {
  const inputs = parseFeeInputs(panel.query);
  return `<section class="calculator-controls" aria-label="Fee calculator controls">
    <label>Amount<input id="fee-amount" type="number" min="1" step="500" value="${esc(inputs.amount)}"></label>
    <label>Years<input id="fee-years" type="number" min="1" max="60" value="${esc(inputs.years)}"></label>
    <label>Expense ratio %<input id="fee-expense" type="number" min="0" max="5" step="0.01" value="${esc(inputs.expensePct)}"></label>
    <label>Gross return %<input id="fee-return" type="number" min="0" max="30" step="0.1" value="${esc(inputs.returnPct)}"></label>
    <button data-fee-run>Recalculate</button>
  </section>`;
}

// Wrap a ticker <input> with a per-cell "×" remove button (handler keeps >=2).
function tickerField(inputHtml) {
  return `<span class="ticker-field">${inputHtml}<button type="button" class="ticker-remove" data-ticker-remove aria-label="Remove">×</button></span>`;
}

// Tickers already on a panel, used to prefill Overlap/Compare inputs.
function panelTickers(panel) {
  return (panel.entities || []).filter((e) => e.kind === "ticker").map((e) => e.ref);
}

// ETFs with cached look-through holdings (the only valid Overlap inputs).
// Loaded once on boot from /api/overlap-funds.
let OVERLAP_FUNDS = [];

// Overlap: editable list of ETF tickers + add/recalculate. Re-runs the overlap
// query so users aren't stuck with the funds baked into the original question.
// Prefills only real fund tickers (panel entities also carry look-through
// holdings), and offers a datalist so users pick funds that actually resolve.
function renderOverlapControls(panel) {
  const fundSet = new Set(OVERLAP_FUNDS);
  let tickers = panelTickers(panel).filter((t) => fundSet.has(t));
  if (!tickers.length) tickers = OVERLAP_FUNDS.slice(0, 3);
  while (tickers.length < 2) tickers.push("");
  const options = OVERLAP_FUNDS.map((t) => `<option value="${esc(t)}">`).join("");
  const fields = tickers
    .map((t) => tickerField(`<input class="overlap-ticker" type="text" list="overlap-fund-list" maxlength="6" placeholder="ETF" value="${esc(t)}">`))
    .join("");
  const hint = OVERLAP_FUNDS.length ? `<small class="controls-hint">Available: ${OVERLAP_FUNDS.join(", ")}</small>` : "";
  return `<section class="calculator-controls overlap-controls" aria-label="Overlap funds">
    <datalist id="overlap-fund-list">${options}</datalist>
    <div class="ticker-fields">${fields}</div>
    <button type="button" data-overlap-add>+ Add fund</button>
    <button type="button" data-overlap-run>Recalculate</button>
    ${hint}
  </section>`;
}

// Compare: editable N-way ticker inputs. Re-runs compare with every filled field.
function renderCompareControls(panel) {
  const CAP = 6;
  const tickers = panelTickers(panel).slice(0, CAP);
  while (tickers.length < 2) tickers.push("");
  const datalistOpts = ALL_TICKERS.map((t) => `<option value="${esc(t)}">`).join("");
  const fields = tickers
    .map((t) => tickerField(`<input class="compare-ticker" type="text" list="compare-ticker-list" maxlength="6" placeholder="Ticker" value="${esc(t)}">`))
    .join("");
  return `<section class="calculator-controls compare-controls" aria-label="Compare tickers">
    <datalist id="compare-ticker-list">${datalistOpts}</datalist>
    <div class="ticker-fields">${fields}</div>
    <button type="button" data-compare-add ${tickers.length >= CAP ? "disabled" : ""} title="Add ticker">+ Add</button>
    <button type="button" data-compare-run>Compare</button>
  </section>`;
}

// Forensic screen: a single ticker picker + "Run screen" so the red-flag panel
// works like the Compare/Overlap calculators instead of being fixed to NVDA.
function renderForensicControls(panel) {
  const t = panelTickers(panel)[0] || "NVDA";
  const opts = ALL_TICKERS.map((x) => `<option value="${esc(x)}">`).join("");
  return `<section class="calculator-controls forensic-controls" aria-label="Forensic screen ticker">
    <datalist id="forensic-ticker-list">${opts}</datalist>
    <label>Ticker<input class="forensic-ticker" type="text" list="forensic-ticker-list" maxlength="6" value="${esc(t)}"></label>
    <button type="button" data-forensic-run>Run screen</button>
  </section>`;
}

function renderFooterList(title, items = []) {
  if (!items.length) return "";
  return `<section class="footer-list"><h3>${esc(title)}</h3>${items.map((item) => `<p>${esc(item)}</p>`).join("")}</section>`;
}

function renderCitations(citations = []) {
  if (!citations.length) return "";
  return `<section class="citations"><h3>Sources</h3>${citations.map((citation) => `<a href="${esc(citation.url)}" target="_blank" rel="noreferrer">${esc(citation.label)}<span>${esc(citation.source)}${citation.as_of_date ? ` · ${esc(citation.as_of_date)}` : ""}</span></a>`).join("")}</section>`;
}

function renderAskSuggestions() {
  const node = $("#ask-suggestions");
  const recent = getRecent();
  const recentHtml = recent.length
    ? recent.map((q) => queryLink(q, `<span>${esc(q)}</span><small>recent</small>`)).join("")
    : "";
  node.innerHTML = recentHtml + ASK_SUGGESTIONS.map((item) => queryLink(item.query, `<span>${esc(item.text)}</span><small>${esc(item.feature)}</small>`)).join("");
}

function showAskSuggestions() {
  renderAskSuggestions();
  $("#ask-suggestions").hidden = false;
}

function hideAskSuggestions() {
  $("#ask-suggestions").hidden = true;
}

function shell(block, inner, wide = false) {
  return `<article class="block ${wide ? "wide" : ""} rounded-2xl shadow-sm hover:shadow-md transition-shadow duration-200">${block.title ? `<h3>${esc(block.title)}</h3>` : ""}${inner}${block.takeaway ? `<p class="takeaway">${esc(block.takeaway)}</p>` : ""}${blockActions(block)}</article>`;
}

// Pre-baked contextual-help texts. Clicking an "Explain..." button opens an
// instant popover from this dictionary -- NO LLM call, NO network request.
// Copy is short ELI5 (2-4 sentences), aligned with app/data/glossary.json.
const EXPLAIN_TEXTS = {
  chart_line: {
    title: "What this chart shows",
    body_md:
      "This is the recent price path, indexed so every line starts at 100. That lets you compare how funds or stocks moved *relative to each other*, ignoring their raw dollar prices. A line ending at 120 means +20% over the window; 90 means -10%.",
  },
  overlap: {
    title: "What fund overlap means",
    body_md:
      "Overlap is how much two funds hold the *same* underlying companies. High overlap means you own the same stocks twice, so you get less diversification than the number of funds suggests. It's shown as a shared-holdings weight or a heatmap of common names.",
  },
  allocation: {
    title: "Asset allocation & diversification",
    body_md:
      "Allocation is the split of your money across stocks, bonds and other assets. Spreading across many uncorrelated holdings (diversification) smooths the ride: when one part falls, another may hold up. The donut shows each slice's share of the whole.",
  },
  triage_score: {
    title: "How this score is built",
    body_md:
      "It's a simple triage number that rolls several checks into one 0-to-N score for a quick first pass. It is a starting point for research, not a buy/sell signal -- always read the underlying checks below it.",
  },
  snowflake: {
    title: "What a snowflake score is",
    body_md:
      "A snowflake plots a company on five axes -- value, growth, financial health, past performance and dividend -- each rated 0 to 5. A bigger, more balanced shape is generally healthier; a spiky one flags strengths and weak spots at a glance.",
  },
  ratings: {
    title: "What these ratings mean",
    body_md:
      "Quality, value and momentum are traffic-light summaries. **Quality** = how sound the business is, **Value** = how cheap it looks versus fundamentals, **Momentum** = recent price trend. Green is favourable, yellow mixed, red a caution.",
  },
  forensic_checks: {
    title: "Forensic red-flag checks",
    body_md:
      "These are accounting screens that look for warning signs -- e.g. earnings not backed by cash, rising debt, or margins that look too smooth. Passing them isn't a guarantee; failing one is a prompt to dig deeper before investing.",
  },
  fundamentals_columns: {
    title: "The fundamentals columns",
    body_md:
      "Each row is a fiscal year. **Revenue** = total sales, **Net income** = profit after costs, **Margin** = profit per dollar of sales, **Debt** = what the company owes, **Dividend** = cash paid to shareholders. Trends across years matter more than any single number.",
  },
  etf_holdings: {
    title: "The top-holdings table",
    body_md:
      "Each row is a company the fund owns, with its **weight** — the share of the fund's money in that position. Bigger weights drive more of the fund's return. A few large weights means the fund is concentrated; many small ones means it's spread out.",
  },
  compare_metrics: {
    title: "The side-by-side metrics",
    body_md:
      "Every row is the same signal measured for each ticker: **Price** and **latest move**, **valuation context** (how expensive it looks), **analyst mean target**, and **Quality / Value / Momentum** lights. Read across a row to see who wins that dimension; no single row decides it.",
  },
  overlap_matrix: {
    title: "The overlap matrix",
    body_md:
      "Each cell shows how much two funds hold in common — higher means more duplicate exposure. High overlap means you own the same companies twice, so you're less diversified than the number of funds suggests.",
  },
  valuation_context: {
    title: "What valuation context means",
    body_md:
      "Valuation context shows where this ticker's current price-to-earnings (P/E) ratio sits **relative to its own history** — expressed as a percentile. A 90th percentile P/E means it's more expensive than 90% of its own past valuations. It doesn't tell you it's overpriced, but it's a signal to check *why* the market is paying a premium.",
  },
  analyst_range: {
    title: "What the analyst range means",
    body_md:
      "Analyst price targets are the average of Wall Street forecasts for where the stock price will be in 12 months. The **low / mean / high** range shows disagreement among analysts. A big spread means high uncertainty. Note: analysts are often optimistic — the mean is typically above the current price.",
  },
  chart_line_single: {
    title: "Reading this price chart",
    body_md:
      "The **left axis** shows the ticker's actual price in dollars. The **right axis** shows the S&P 500 (via VOO) price over the same period. Because both lines cover exactly the same date range, you can see how the ticker performed relative to the broad market — without normalising to 100.",
  },
};

// Which explainer fits each table, chosen by title (tables share block.type).
const TABLE_EXPLAIN = {
  "Fundamentals": "fundamentals_columns",
  "Top holdings": "etf_holdings",
  "Side-by-side quick metrics": "compare_metrics",
};

// Small contextual buttons under each chart/table. "Explain..." buttons open an
// instant static popover (data-explain); real analysis buttons still run a query.
const BLOCK_ACTIONS = {
  "chart.line": [["Explain this chart", { explain: "chart_line" }], ["Show 5-year growth", { query: "What if I invested $10,000 in the S&P 500 5 years ago?" }]],
  "chart.heatmap": [["Explain overlap", { explain: "overlap" }]],
  "chart.treemap": [["Explain overlap", { explain: "overlap" }]],
  "chart.donut": [["What does this mean?", { explain: "allocation" }]],
  "chart.bar": [["What is this score?", { explain: "triage_score" }]],
  "radar": [["What is a snowflake?", { explain: "snowflake" }]],
  "traffic_light": [["What do these ratings mean?", { explain: "ratings" }]],
  "scorecard": [["Explain these checks", { explain: "forensic_checks" }]],
  "table": [["Explain these columns", { explain: "fundamentals_columns" }]],
};

// A chart series name is a real ticker if it's 1-5 uppercase letters (not the
// "S&P 500" baseline label). Used to aim the "Show 5-year growth" button.
function isTickerName(name) {
  return typeof name === "string" && /^[A-Z]{1,5}$/.test(name);
}

// Serialize a block's actual data into a self-contained question, so the LLM
// re-explains THIS chart (with its numbers) in the context of the user's query.
function blockExplainQuery(block, originalQuery) {
  const ctx = originalQuery ? `In the context of my question "${originalQuery}", ` : "";
  let data = "";
  switch (block.type) {
    case "chart.heatmap":
      data = (block.y_labels || []).map((y, i) =>
        (block.x_labels || []).map((x, j) => `${y}×${x} ${Math.round((block.matrix?.[i]?.[j] || 0) * 100)}%`).join(", ")
      ).join("; ");
      break;
    case "radar":
      data = (block.axes || []).map((a) => `${a.name} ${a.value}/${a.max}`).join(", ");
      break;
    case "traffic_light":
      data = (block.items || []).map((i) => `${i.label} ${i.status}`).join(", ");
      break;
    case "chart.bar":
      data = (block.items || []).map((i) => `${i.label}: ${i.value}${i.unit || ""}`).join(", ");
      break;
    case "chart.donut":
      data = (block.items || []).map((i) => `${i.label} ${i.value}%`).join(", ");
      break;
    case "scorecard":
      data = (block.items || []).map((i) => `${i.label} (${i.pass ? "pass" : "watch"})`).join(", ");
      break;
    case "chart.treemap":
      data = (block.items || []).slice(0, 12).map((i) => `${i.label} ${i.value}%`).join(", ");
      break;
    case "chart.line":
      data = (block.series || []).map((s) => {
        const pts = s.points || [];
        const range = pts.length ? ` (${pts[0].x} → ${pts[pts.length - 1].x})` : "";
        return `${s.name}${range}`;
      }).join(", ");
      break;
    case "table":
      data = `columns ${(block.columns || []).join(" | ")}; ` +
        (block.rows || []).slice(0, 8).map((r) => r.join(" | ")).join("; ");
      break;
    default:
      data = block.title || "";
  }
  const what = block.title ? `this "${block.title}" ${block.type.replace(".", " ")}` : `this ${block.type}`;
  return `${ctx}explain what ${what} shows and what it means for me: ${data}.`;
}

function blockActions(block) {
  let actions = BLOCK_ACTIONS[block.type];
  if (!actions) return "";
  // "Show 5-year growth" should follow the chart's own ticker, not always S&P.
  if (block.type === "chart.line") {
    const t = block.series?.[0]?.name;
    const target = isTickerName(t) ? t : "the S&P 500";
    actions = actions.map(([label, action]) =>
      action.query
        ? [label, { query: `What if I invested $10,000 in ${target} 5 years ago?` }]
        : [label, action]
    );
  }
  // Tables share block.type — pick the explainer that matches this table's title.
  if (block.type === "table") {
    const key = TABLE_EXPLAIN[block.title] || "fundamentals_columns";
    actions = [["Explain these columns", { explain: key }]];
  }
  // Index into the current panel (block objects are the same references), so the
  // explain button can rebuild the panel from THIS block's data via the LLM.
  const idx = (window.__currentPanel?.blocks || []).indexOf(block);
  return `<div class="block-actions">${actions
    .map(([label, action]) =>
      action.explain
        ? idx >= 0
          ? `<button class="block-action" data-block-explain="${idx}" data-explain-fallback="${esc(action.explain)}">${esc(label)}</button>`
          : `<button class="block-action" data-explain="${esc(action.explain)}">${esc(label)}</button>`
        : queryLink(action.query, esc(label), "block-action")
    )
    .join("")}</div>`;
}

// --- Plotly integration -------------------------------------------------- //
// Renderers return an HTML placeholder + queue a Plotly spec; flushPlotly()
// draws them once the container HTML is in the DOM. Falls back gracefully
// (empty chart area) if the vendored plotly.min.js failed to load.
const PLOT_PALETTE = ["#3366cc", "#109778", "#d97706", "#7c3aed", "#dc2626", "#0891b2", "#64748b"];
const PLOT_FONT = { family: "Inter, ui-sans-serif, system-ui, sans-serif", size: 12, color: "#334155" };
const PLOT_CONFIG = { displayModeBar: false, responsive: true, scrollZoom: false };
let __plotSeq = 0;
const __plotQueue = [];

function baseLayout(overrides = {}) {
  return {
    margin: { l: 44, r: 16, t: 8, b: 34 },
    height: 230,
    font: PLOT_FONT,
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    showlegend: false,
    hoverlabel: { bgcolor: "#0f172a", font: { color: "#f8fafc", size: 12 } },
    ...overrides,
  };
}

function queuePlot(data, layout, onClick) {
  const id = `plot-${++__plotSeq}`;
  __plotQueue.push({ id, data, layout, onClick });
  return `<div id="${id}" class="plotly-chart"></div>`;
}

function flushPlotly() {
  const queued = __plotQueue.splice(0);
  if (!window.Plotly) return; // vendored bundle missing — leave placeholders empty
  for (const item of queued) {
    const el = document.getElementById(item.id);
    if (!el) continue;
    window.Plotly.newPlot(el, item.data, item.layout, PLOT_CONFIG);
    if (item.onClick) {
      el.on("plotly_click", (event) => {
        const point = event.points?.[0];
        const cd = point?.customdata;
        if (cd && cd.ref) openEntity(cd.kind || "ticker", cd.ref, cd.text || cd.ref);
      });
    }
  }
}

function entityAttrs(item) {
  if (!item.entity_kind || !item.entity_ref) return "";
  return ` class="clickable-chart-item" role="button" tabindex="0" data-entity-kind="${esc(item.entity_kind)}" data-entity-ref="${esc(item.entity_ref)}" data-entity-text="${esc(item.label)}"`;
}

// Refine / follow-up action pills. Rendered INSIDE the LLM prose block (see
// renderBlocks) as a .block-actions row — same dashed-separator pill pattern as
// every other block. Each action re-asks a self-contained question via #q=.
function renderAnswerActions(panel) {
  if (!panelHasLlmAnswer(panel)) return "";
  return `<div class="block-actions">
    <button class="block-action" data-answer-action="detail">Tell me about this in more detail</button>
    <button class="block-action" data-answer-action="simpler">Explain this more simply</button>
    <button class="block-action" data-answer-action="followup">Ask a follow-up question</button>
  </div>`;
}

function renderBlocks(panel) {
  const blocks = panel.blocks;
  const actions = renderAnswerActions(panel);
  // Render a text block with the action pills tucked inside its article, so they
  // sit within the answer block (full width, no grid stretch), after a dashed line.
  const textWithActions = (b) => `<article class="block text-block">${renderMarkdown(b.markdown)}${actions}</article>`;
  // Lead with a hero row whenever the answer starts with prose + a single KPI:
  // full-width text on the left, the headline number as a compact sidebar. Used
  // by forensic and every LLM-narrated panel (Tell me about, overlap, …) so the
  // text never squeezes a chart beside it and the number stays symmetric.
  if (blocks.length >= 2 && blocks[0].type === "text" && blocks[1].type === "kpi") {
    const hero = `<div class="answer-hero">${textWithActions(blocks[0])}<aside class="answer-hero-kpi">${renderBlock(blocks[1])}</aside></div>`;
    return hero + blocks.slice(2).map(renderBlock).join("");
  }
  // Otherwise attach the actions inside the first text (LLM) block.
  const firstText = blocks.findIndex((b) => b.type === "text");
  if (firstText >= 0) {
    return blocks.map((b, i) => (i === firstText ? textWithActions(b) : renderBlock(b))).join("");
  }
  return blocks.map(renderBlock).join("");
}

function renderBlock(block) {
  if (block.type === "kpi") return `<article class="block kpi rounded-2xl shadow-sm hover:shadow-md transition-shadow duration-200"><span>${esc(block.label)}</span><strong>${esc(block.value)}</strong><p>${esc(block.takeaway)}</p></article>`;
  if (block.type === "chart.heatmap") return renderHeatmap(block);
  if (block.type === "chart.treemap") return renderTreemap(block);
  if (block.type === "chart.bar") return renderBars(block);
  if (block.type === "chart.donut") return renderDonut(block);
  if (block.type === "chart.line") return renderLine(block);
  if (block.type === "radar") return renderRadar(block);
  if (block.type === "traffic_light") return shell(block, `<div class="traffic-list">${block.items.map((item) => `<span class="${item.status}"><strong>${esc(item.label)}</strong>${esc(item.note || "")}</span>`).join("")}</div>`);
  if (block.type === "scorecard") return shell(block, `<div class="score-list">${block.items.map((item) => `<p><strong>${item.pass ? "Pass" : "Watch"}</strong><span>${esc(item.label)}</span><small>${esc(item.detail)}</small></p>`).join("")}</div>`);
  if (block.type === "table") return shell(block, `<table><thead><tr>${block.columns.map((col) => `<th>${esc(col)}</th>`).join("")}</tr></thead><tbody>${block.rows.map((row) => `<tr>${row.map((cell) => `<td>${esc(cell)}</td>`).join("")}</tr>`).join("")}</tbody></table>`, true);
  if (block.type === "text") return `<article class="block text-block">${renderMarkdown(block.markdown)}</article>`;
  return "";
}

function renderHeatmap(block) {
  const z = block.matrix.map((row) => row.map((v) => Number(v)));
  const text = z.map((row) => row.map((v) => pct(v)));
  const data = [{
    type: "heatmap",
    z,
    x: block.x_labels,
    y: block.y_labels,
    text,
    texttemplate: "%{text}",
    textfont: { size: 11, color: "#0f172a" },
    hovertemplate: "%{y} vs %{x}: %{text}<extra></extra>",
    colorscale: [[0, "#e6f2f0"], [0.5, "#5eb0a4"], [1, "#0f766e"]],
    showscale: false,
    xgap: 3,
    ygap: 3,
  }];
  const layout = baseLayout({
    height: 60 + block.y_labels.length * 42,
    margin: { l: 70, r: 12, t: 8, b: 40 },
    xaxis: { side: "bottom", fixedrange: true, tickfont: { size: 11 } },
    yaxis: { autorange: "reversed", fixedrange: true, tickfont: { size: 11 } },
  });
  return shell(block, queuePlot(data, layout));
}

function renderBars(block) {
  const items = [...block.items].reverse(); // Plotly draws bottom-up; keep input order top-down
  const clickable = items.some((item) => item.entity_ref);
  const data = [{
    type: "bar",
    orientation: "h",
    x: items.map((item) => Number(item.value)),
    y: items.map((item) => item.label),
    marker: { color: "#3366cc" },
    customdata: items.map((item) => ({ kind: item.entity_kind, ref: item.entity_ref, text: item.label })),
    hovertemplate: `%{y}: %{x:.1f}${esc(block.items[0]?.unit || "")}<extra></extra>`,
  }];
  const layout = baseLayout({
    height: Math.max(180, items.length * 30 + 40),
    margin: { l: 92, r: 24, t: 8, b: 28 },
    xaxis: { fixedrange: true, zeroline: false, gridcolor: "#eef2f7" },
    yaxis: { fixedrange: true, automargin: true },
  });
  return shell(block, queuePlot(data, layout, clickable ? true : null), block.items.length > 6);
}

function renderDonut(block) {
  const data = [{
    type: "pie",
    hole: 0.58,
    labels: block.items.map((item) => item.label),
    values: block.items.map((item) => Number(item.value)),
    marker: { colors: PLOT_PALETTE },
    textposition: "inside",
    texttemplate: "%{label}<br>%{percent}",
    hovertemplate: "%{label}: %{value:.1f}%<extra></extra>",
    sort: false,
  }];
  const layout = baseLayout({ height: 260, margin: { l: 8, r: 8, t: 8, b: 8 }, showlegend: true, legend: { orientation: "h", y: -0.05, font: { size: 11 } } });
  return shell(block, queuePlot(data, layout));
}

function renderLine(block) {
  const hasRight = block.series.some((s) => s.axis === "right");
  const data = block.series.map((series, index) => ({
    type: "scatter",
    mode: "lines",
    name: series.name,
    x: series.points.map((point) => point.x),
    y: series.points.map((point) => point.y),
    yaxis: series.axis === "right" ? "y2" : "y",
    line: { color: PLOT_PALETTE[index % PLOT_PALETTE.length], width: 2 },
    hovertemplate: `${esc(series.name)}: %{x} = %{y:.2f}<extra></extra>`,
  }));
  const layout = baseLayout({
    height: 240,
    showlegend: block.series.length > 1,
    legend: { orientation: "h", y: 1.12, font: { size: 11 } },
    xaxis: { fixedrange: true, gridcolor: "#eef2f7", tickfont: { size: 11 } },
    yaxis: { fixedrange: true, gridcolor: "#eef2f7", tickfont: { size: 11 } },
  });
  if (hasRight) {
    layout.yaxis2 = { overlaying: "y", side: "right", fixedrange: true, showgrid: false, tickfont: { size: 11 } };
  }
  return shell(block, queuePlot(data, layout));
}

// Red/green tile colour for a % move (fraction); saturates around ±3%.
function moveColor(v) {
  const m = Math.min(Math.abs(Number(v)) / 0.03, 1);
  return v >= 0 ? `rgba(16,151,120,${0.25 + 0.6 * m})` : `rgba(220,38,38,${0.25 + 0.6 * m})`;
}

function renderTreemap(block) {
  const clickable = block.items.some((item) => item.entity_ref);
  const heat = block.items.some((item) => item.color_value != null);
  let trace;
  if (heat) {
    // Sector parent tiles + colour-by-move child tiles (SaaS market-map style).
    const sectors = [...new Set(block.items.map((item) => item.group || "Other"))];
    trace = {
      type: "treemap",
      labels: [...sectors, ...block.items.map((item) => item.label)],
      parents: [...sectors.map(() => ""), ...block.items.map((item) => item.group || "Other")],
      values: [...sectors.map(() => 0), ...block.items.map((item) => Number(item.value))],
      text: [...sectors.map(() => ""), ...block.items.map((item) => `${fmt(item.value, "%")}<br>${pct(item.color_value)}`)],
      texttemplate: "%{label}<br>%{text}",
      customdata: [...sectors.map(() => ({})), ...block.items.map((item) => ({ kind: item.entity_kind, ref: item.entity_ref, text: item.label }))],
      hovertemplate: "%{label}<extra></extra>",
      marker: { colors: [...sectors.map(() => "rgba(148,163,184,0.14)"), ...block.items.map((item) => moveColor(item.color_value))], line: { width: 2, color: "#ffffff" } },
      tiling: { pad: 2 },
    };
  } else {
    trace = {
      type: "treemap",
      labels: block.items.map((item) => item.label),
      parents: block.items.map(() => ""),
      values: block.items.map((item) => Number(item.value)),
      text: block.items.map((item) => `${fmt(item.value, "%")}${item.group ? `<br>${item.group}` : ""}`),
      texttemplate: "%{label}<br>%{text}",
      customdata: block.items.map((item) => ({ kind: item.entity_kind, ref: item.entity_ref, text: item.label })),
      hovertemplate: "%{label}: %{value:.1f}%<extra></extra>",
      marker: { colors: block.items.map((_, i) => PLOT_PALETTE[i % PLOT_PALETTE.length]), line: { width: 2, color: "#ffffff" } },
      tiling: { pad: 2 },
    };
  }
  const layout = baseLayout({ height: 280, margin: { l: 6, r: 6, t: 6, b: 6 } });
  return shell(block, queuePlot([trace], layout, clickable ? true : null));
}

function renderRadar(block) {
  const axes = block.axes;
  const max = Math.max(...axes.map((axis) => axis.max), 1);
  const data = [{
    type: "scatterpolar",
    r: [...axes.map((axis) => axis.value), axes[0]?.value ?? 0],
    theta: [...axes.map((axis) => axis.name), axes[0]?.name ?? ""],
    fill: "toself",
    fillcolor: "rgba(51,102,204,0.18)",
    line: { color: "#3366cc", width: 2 },
    hovertemplate: "%{theta}: %{r}<extra></extra>",
  }];
  const layout = baseLayout({
    height: 280,
    margin: { l: 40, r: 40, t: 30, b: 30 },
    polar: { radialaxis: { visible: true, range: [0, max], tickfont: { size: 10 } }, angularaxis: { tickfont: { size: 11 } } },
  });
  return shell(block, queuePlot(data, layout));
}

function renderTickerExtras(card) {
  const etf = card.asset_type === "etf" ? renderEtfExtras(card) : "";
  const snowflake = card.snowflake?.length
    ? renderBlock({
        type: "radar",
        title: "Snowflake snapshot",
        axes: card.snowflake.map((axis) => ({ name: axis.axis, value: axis.value, max: axis.max })),
        takeaway: "Quick visual summary of value, growth, health, past performance, and dividend profile.",
      })
    : "";
  const traffic = card.traffic?.length
    ? `<div class="traffic-list">${card.traffic.map((item) => `<span class="${esc(item.status)}"><strong>${esc(item.label)}</strong></span>`).join("")}</div>`
    : "";
  const percentiles = card.percentiles?.length
    ? `<div class="mini-section"><h3>Valuation context</h3>${card.percentiles.map((item) => `<p><strong>${esc(item.metric)}</strong> ${esc(item.percentile)}th percentile · ${esc(item.context)}</p>`).join("")}</div>`
    : "";
  const analyst = card.analyst ? renderAnalystBand(card.analyst) : "";
  const fundamentals = card.fundamentals?.length
    ? renderBlock({
        type: "table",
        title: "Fundamentals",
        columns: ["Year", "Revenue", "Net income", "Margin", "Debt"],
        rows: card.fundamentals.map((row) => [
          String(row.year),
          fmt(row.revenue),
          fmt(row.net_income),
          pct(row.margin),
          fmt(row.debt),
        ]),
        takeaway: "Compact cached fundamentals for the ticker card.",
      })
    : "";
  const news = card.news?.length
    ? `<div class="mini-section"><h3>Recent headlines</h3>${card.news.map((item) => `<a href="${esc(item.url)}" target="_blank" rel="noreferrer">${esc(item.title)}<span>${esc(item.source)} · ${esc(item.published)}</span></a>`).join("")}</div>`
    : "";
  return `${etf}${snowflake}${traffic}${percentiles}${analyst}${fundamentals}${news}`;
}

function renderEtfExtras(card) {
  const profile = `<div class="mini-section"><h3>ETF profile</h3><p><strong>Expense ratio:</strong> ${pct(card.expense_ratio || 0)}</p><p><strong>Holdings as of:</strong> ${esc(card.holdings_as_of || "cached")}</p></div>`;
  const holdings = card.top_holdings?.length
    ? renderBlock({
        type: "table",
        title: "Top holdings",
        columns: ["Ticker", "Company", "Weight", "Sector"],
        rows: card.top_holdings.map((row) => [
          row.ticker,
          row.name,
          pct(row.weight),
          row.sector || "Unknown",
        ]),
        takeaway: "ETF cards show the fund's cached holdings, not just a stock-style price card.",
      })
    : "";
  const sectors = card.sector_exposure?.length
    ? renderBlock({
        type: "chart.donut",
        title: "Sector exposure",
        items: card.sector_exposure.slice(0, 7).map((row) => ({ label: row.sector, value: row.weight * 100 })),
        takeaway: "Sector exposure is computed from the cached ETF holdings file.",
      })
    : "";
  return `${profile}${holdings}${sectors}`;
}

function renderAnalystBand(analyst) {
  const range = Math.max(analyst.high - analyst.low, 1);
  const meanOffset = Math.min(100, Math.max(0, ((analyst.mean - analyst.low) / range) * 100));
  return `<div class="mini-section analyst-band"><h3>Analyst range</h3><div><span>${esc(analyst.currency)} ${fmt(analyst.low)}</span><i style="--mean:${meanOffset}%"></i><span>${esc(analyst.currency)} ${fmt(analyst.high)}</span></div><p>Mean target: <strong>${esc(analyst.currency)} ${fmt(analyst.mean)}</strong></p></div>`;
}

async function runQuery(nextQuery = $("#query").value, { push = true, intent = null, parentSeq = null } = {}) {
  window.__lastQuery = nextQuery;
  if (parentSeq == null) newThread(); // a brand-new question opens a new conversation
  document.body.classList.add("answering"); // collapse the landing, keep the askbar on top
  $("#ask").disabled = true;
  $("#ask").textContent = "Loading";
  hideAskSuggestions();
  $("#error").innerHTML = "";
  $("#answer").className = "answer";
  $("#answer").innerHTML = `<header class="answer-head"><div><div class="intent">working</div><h2>Building the panel...</h2><p>Fetching the contract response and rendering the interactive blocks.</p></div></header><div class="blocks">${'<article class="block skeleton-block"><div class="skeleton skeleton-title"></div><div class="skeleton skeleton-chart"></div><div class="skeleton skeleton-line"></div></article>'.repeat(2)}</div>`;
  // Shareable deep link + browser history. popstate replays with push=false so
  // back/forward don't stack duplicate entries.
  if (push) {
    const hash = buildHash(nextQuery, intent);
    if (location.hash !== hash) history.pushState({ q: nextQuery, i: intent }, "", hash);
  }
  try {
    $("#query").value = nextQuery;
    const cacheKey = panelCacheKey(nextQuery, intent) + `|p:${parentSeq ?? ""}`;
    let panel = PANEL_CACHE.get(cacheKey);
    if (!panel) {
      panel = await ask(nextQuery, { intent, parentSeq });
      PANEL_CACHE.set(cacheKey, panel);
    }
    const seq = panel.meta && panel.meta.turn_seq;
    window.__currentTurnSeq = seq ?? null;
    if (seq != null) PANEL_CACHE.set(`t:${seq}`, panel);
    // Redirect the (provisional #q=) URL to the readable, deterministic forum link.
    if (push && seq != null) history.replaceState({ seq }, "", buildTurnHash(seq, panel.meta.turn_slug));
    renderPanel(panel);
    pushRecent(nextQuery);
    window.scrollTo(0, 0); // landing is hidden; #answer is already at the top
  } catch (error) {
    if (error.status === 503) {
      $("#answer").innerHTML = "";
      $("#answer").className = "answer";
      showLlmUnavailableModal(error.message);
    } else {
      $("#error").innerHTML = `<div class="error">${esc(error.message || "Request failed")}</div>`;
    }
  } finally {
    $("#ask").disabled = false;
    $("#ask").textContent = "Ask";
  }
}

// Open a stored topic by its forum number (#/t/<seq>). Renders the persisted
// panel verbatim — no LLM recompute — so reloads and shared links are instant.
async function openTurn(seq, { push = true } = {}) {
  document.body.classList.add("answering");
  hideAskSuggestions();
  $("#error").innerHTML = "";
  try {
    let panel = PANEL_CACHE.get(`t:${seq}`);
    if (!panel) {
      panel = await apiGet(`/api/turn/${seq}`);
      PANEL_CACHE.set(`t:${seq}`, panel);
    }
    window.__currentTurnSeq = seq;
    window.__lastQuery = panel.query || "";
    window.__threadId = null; // continuing from a shared link starts a fresh thread on the next ask
    $("#query").value = panel.query || "";
    if (push) {
      const hash = buildTurnHash(seq, panel.meta && panel.meta.turn_slug);
      if (location.hash !== hash) history.pushState({ seq }, "", hash);
    }
    renderPanel(panel);
    window.scrollTo(0, 0);
  } catch (error) {
    $("#error").innerHTML = `<div class="error">${esc(error.message || "Could not open this topic")}</div>`;
  }
}

async function openEntity(kind, ref, text) {
  const modal = $("#modal");
  modal.innerHTML = `<div class="modal-backdrop"><section class="modal"><button class="icon-button" data-close>Close</button><p class="modal-loading">Loading ${esc(text)}</p></section></div>`;
  const path = kind === "ticker" ? `/api/entity/ticker/${encodeURIComponent(ref)}` : `/api/entity/term/${encodeURIComponent(ref)}`;
  try {
    const data = await apiGet(path);
    if (data.ticker) {
      TICKER_CARDS.set(data.ticker, data);
      // One tidy row of explainers at the bottom, mirroring the main panels.
      // Only offer an explainer when its section is actually present.
      const t = esc(data.ticker);
      const actionBtns = [
        `<button class="block-action" data-interpret="${t}">What do these numbers mean?</button>`,
        `<button class="block-action" data-llm-explain="${t}">Explain these numbers</button>`,
      ];
      if (data.traffic?.length) actionBtns.push(`<button class="block-action" data-explain="ratings">What do these ratings mean?</button>`);
      if (data.percentiles?.length) actionBtns.push(`<button class="block-action" data-explain="valuation_context">What is valuation context?</button>`);
      if (data.analyst) actionBtns.push(`<button class="block-action" data-explain="analyst_range">What is an analyst range?</button>`);
      const explainButtons = `<div class="block-actions">${actionBtns.join("")}</div>`;
      const learnMore = `<button class="link-button" data-ticker-ask="${t}" title="Ask for a full write-up on ${t}">Learn more about ${t}</button>`;
      const modalSeries = [{ name: data.ticker, points: data.price_series.map((p) => ({ x: p.date, y: p.close })), axis: "left" }];
      if (SP_BASELINE && SP_BASELINE.points && SP_BASELINE.points.length) modalSeries.push(SP_BASELINE);
      modal.innerHTML = `<div class="modal-backdrop"><section class="modal"><button class="icon-button" data-close>Close</button><div class="modal-title"><span>${t}</span><h2>${esc(data.name)}</h2><strong>${esc(data.currency)} ${fmt(data.price)} <em class="${data.change_pct >= 0 ? "up" : "down"}">${pct(data.change_pct)}</em></strong></div>${learnMore}${renderLine({ type: "chart.line", title: "Recent price vs S&P 500", series: modalSeries, takeaway: "Left axis: ticker price. Right axis: S&P 500 (VOO)." })}${renderTickerExtras(data)}${explainButtons}${renderCitations(data.citations)}</section></div>`;
    } else {
      const detail = data.detail_md ? `<div class="term-detail">${renderMarkdown(data.detail_md)}</div>` : "";
      modal.innerHTML = `<div class="modal-backdrop"><section class="modal"><button class="icon-button" data-close>Close</button><div class="modal-title"><span>Term</span><h2>${esc(data.term)}</h2></div><p>${esc(data.eli5)}</p><p class="note">${esc(data.example)}</p>${detail}<button class="explain-more" data-term-ask="${esc(data.term)}" title="Ask: what does this term mean?">Learn more</button>${renderCitations([data.citation])}</section></div>`;
    }
    flushPlotly();
  } catch (error) {
    modal.innerHTML = `<div class="modal-backdrop"><section class="modal"><button class="icon-button" data-close>Close</button><div class="error">${esc(error.message || "Entity unavailable")}</div></section></div>`;
  }
}

// Tiny inline-markdown -> HTML for pre-baked help text (bold/italic only).
// Input is trusted (our own constants), but we still escape first for safety.
function mdInline(text) {
  return esc(text)
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>");
}

// Instant contextual-help popover from EXPLAIN_TEXTS. No fetch, no LLM.
function openExplain(key) {
  const item = EXPLAIN_TEXTS[key];
  if (!item) return;
  openExplainHtml(item.title, `<p>${mdInline(item.body_md)}</p>`);
}

// Explainer popover with caller-supplied HTML body (reuses openExplain markup).
function openExplainHtml(title, html) {
  $("#modal").innerHTML = `<div class="modal-backdrop"><section class="modal explain-modal"><button class="icon-button" data-close>Close</button><div class="modal-title"><span>Quick explainer</span><h2>${esc(title)}</h2></div>${html}</section></div>`;
}

// Deterministic, offline reading of a ticker card's numbers (no network/LLM).
function interpretCard(card) {
  const t = card.ticker;
  const parts = [];
  if (card.percentiles?.length) {
    const p = card.percentiles[0];
    const where = p.percentile >= 60 ? "on the expensive side" : p.percentile <= 40 ? "on the cheaper side" : "roughly mid-pack";
    parts.push(`${t}'s ${p.metric} sits near the ${p.percentile}th percentile — ${where} versus its history.`);
  }
  if (card.traffic?.length) {
    const by = {};
    card.traffic.forEach((x) => (by[x.label] = x.status));
    const word = (s) => (s === "green" ? "favourable" : s === "red" ? "a caution" : "mixed");
    parts.push(`Quality looks ${word(by.Quality)}, Value ${word(by.Value)}, and Momentum ${word(by.Momentum)}.`);
  }
  if (card.fundamentals?.length >= 2) {
    const a = card.fundamentals[card.fundamentals.length - 2];
    const b = card.fundamentals[card.fundamentals.length - 1];
    parts.push(`Revenue ${b.revenue >= a.revenue ? "grew" : "fell"} in the latest year and net margin ${b.margin >= a.margin ? "held up or improved" : "slipped"} to about ${(b.margin * 100).toFixed(0)}%.`);
  }
  if (card.analyst) {
    const upside = ((card.analyst.mean - card.price) / card.price) * 100;
    parts.push(`The analyst mean target of ${card.analyst.currency} ${fmt(card.analyst.mean)} implies about ${upside >= 0 ? "+" : ""}${upside.toFixed(0)}% versus the current ${card.currency} ${fmt(card.price)}.`);
  }
  return parts.length ? parts.map((p) => `<p>${esc(p)}</p>`).join("") : "<p>Not enough cached signals to interpret this ticker.</p>";
}

// Natural-language question built from the same numbers, sent down the normal ask path.
function llmExplainQuery(card) {
  const p = card.percentiles?.[0];
  const by = {};
  (card.traffic || []).forEach((x) => (by[x.label] = x.status));
  const m = card.fundamentals?.length ? `${(card.fundamentals[card.fundamentals.length - 1].margin * 100).toFixed(0)}%` : "n/a";
  const mean = card.analyst ? `${card.analyst.currency} ${fmt(card.analyst.mean)}` : "n/a";
  const val = p ? `${p.metric} at the ${p.percentile}th percentile` : "valuation n/a";
  return `Explain in plain English what these numbers mean for ${card.ticker}: ${val}, net margin ${m}, Quality ${by.Quality || "n/a"}, Value ${by.Value || "n/a"}, Momentum ${by.Momentum || "n/a"}, analyst mean target ${mean}. What does the recent price chart show?`;
}

document.addEventListener("click", (event) => {
  if (event.target.closest("[data-news-more]")) {
    newsOff += 4;
    renderNewsWindow();
    return;
  }
  if (event.target.closest("[data-curiosity-more]")) {
    cOff += 3;
    renderCuriosityWindow();
    return;
  }
  if (event.target.closest("[data-questions-more]")) {
    qOff += 4;
    renderQuestionsWindow();
    return;
  }
  const curiosityAsk = event.target.closest("[data-curiosity-ask]");
  if (curiosityAsk) {
    runQuery("Tell me more about this and why it matters: " + curiosityAsk.dataset.curiosityAsk, { intent: "generic" });
    return;
  }
  const termAsk = event.target.closest("[data-term-ask]");
  if (termAsk) {
    const term = termAsk.dataset.termAsk;
    const ctx = window.__lastQuery ? ` in the context of: ${window.__lastQuery}` : " in more detail with a concrete example";
    $("#modal").innerHTML = "";
    runQuery(`Explain ${term}${ctx}, for a beginner investor.`, { intent: "generic" });
    return;
  }
  const tickerAsk = event.target.closest("[data-ticker-ask]");
  if (tickerAsk) {
    const ticker = tickerAsk.dataset.tickerAsk;
    $("#modal").innerHTML = "";
    runQuery(`Tell me about ${ticker} — overview, quality signals, risks.`);
    return;
  }
  const prosConsAsk = event.target.closest("[data-proscons-ask]");
  if (prosConsAsk) {
    const tickers = __lastPanelTickers.length ? ` for ${__lastPanelTickers.join(", ")}` : "";
    runQuery(`Explain what this means${tickers} and why it is good or bad: ${prosConsAsk.dataset.prosconsAsk}`, { intent: "generic" });
    return;
  }
  const followupMore = event.target.closest("[data-followup-more]");
  if (followupMore) {
    const kind = followupMore.dataset.followupMore;
    __followupOffsets[kind] = (__followupOffsets[kind] + 1) % (__followupGroups[kind].length || 1);
    const slot = followupMore.closest(".followup-slot");
    if (slot) slot.outerHTML = renderFollowupSlot(kind);
    return;
  }
  if (event.target.closest("[data-followup-cancel]")) {
    clearFollowup();
    return;
  }
  const answerAction = event.target.closest("[data-answer-action]");
  if (answerAction) {
    const action = answerAction.dataset.answerAction;
    const base = baseQuestion(window.__lastQuery || "");
    if (action === "followup") {
      // Hand off to the search bar: next submit folds this query into a follow-up.
      __pendingFollowup = base;
      const q = $("#query");
      q.value = "";
      q.placeholder = "Ask a follow-up question…";
      q.focus();
      showFollowupHint();
    } else if (action === "detail") {
      runQuery(`Answer in more detail: ${base}`, { intent: "generic" });
    } else if (action === "simpler") {
      runQuery(`Explain more simply: ${base}`, { intent: "generic" });
    }
    return;
  }
  const blockExplainButton = event.target.closest("[data-block-explain]");
  if (blockExplainButton) {
    const panel = window.__currentPanel;
    const block = panel?.blocks?.[Number(blockExplainButton.dataset.blockExplain)];
    if (block) runQuery(blockExplainQuery(block, panel.query), { intent: "generic" });
    else openExplain(blockExplainButton.dataset.explainFallback); // stale panel → static help
    return;
  }
  const explainButton = event.target.closest("[data-explain]");
  if (explainButton) {
    openExplain(explainButton.dataset.explain);
    return;
  }
  const interpretButton = event.target.closest("[data-interpret]");
  if (interpretButton) {
    const card = TICKER_CARDS.get(interpretButton.dataset.interpret);
    if (card) openExplainHtml(`What these mean for ${card.ticker}`, interpretCard(card));
    return;
  }
  const llmButton = event.target.closest("[data-llm-explain]");
  if (llmButton) {
    const card = TICKER_CARDS.get(llmButton.dataset.llmExplain);
    if (card) {
      $("#modal").innerHTML = ""; // close the ticker modal before the answer loads
      runQuery(llmExplainQuery(card), { intent: "generic" });
    }
    return;
  }
  const navButton = event.target.closest("[data-nav]");
  if (navButton) {
    if (navButton.dataset.nav === "home") goHome();
    else if (navButton.dataset.nav === "learn") showLearn();
    return;
  }
  if (event.target.closest("#risk-profile")) openQuiz();
  if (event.target.closest("#clear-data")) { clearMyData(); return; }
  // Identity chip + landing links all open the one Sign-in modal.
  if (event.target.closest("#identity-chip") || event.target.closest("#identity-signin")) { openSignInModal(); return; }
  if (event.target.closest("#save-device") || event.target.closest("#redeem-code")) { openSignInModal(); return; }
  if (event.target.closest("[data-signin-submit]")) { submitSignIn(); return; }
  if (event.target.closest("[data-get-code]")) { mintRecoveryCode(); return; }
  if (event.target.closest("[data-clear-data-modal]")) { clearMyData(); return; }
  const quizOpt = event.target.closest("[data-quiz-q]");
  if (quizOpt) selectQuizOption(quizOpt.dataset.quizQ, quizOpt.dataset.quizScore, quizOpt);
  if (event.target.closest("#quiz-submit")) submitQuiz();
  if (event.target.closest("[data-quiz-clear]")) {
    setRiskProfile(null);
    updateRiskChip();
    $("#modal").innerHTML = "";
    if (document.body.classList.contains("answering")) runQuery($("#query").value, { push: false });
  }
  const suggestButton = event.target.closest("[data-suggest-query]");
  if (suggestButton) runQuery(suggestButton.dataset.suggestQuery);
  const queryButton = event.target.closest("[data-query]");
  if (queryButton) {
    // Let Ctrl/Cmd/Shift-click fall through so anchor query-links open a new tab.
    if (event.metaKey || event.ctrlKey || event.shiftKey) return;
    event.preventDefault(); // avoid the browser pushing its own #q= history entry
    runQuery(queryButton.dataset.query, { intent: queryButton.dataset.intent || null });
  }
  const entityButton = event.target.closest("[data-entity-kind]");
  if (entityButton) openEntity(entityButton.dataset.entityKind, entityButton.dataset.entityRef, entityButton.dataset.entityText || entityButton.textContent);
  const feeButton = event.target.closest("[data-fee-run]");
  if (feeButton) {
    const amount = $("#fee-amount").value || "10000";
    const years = $("#fee-years").value || "20";
    const expense = $("#fee-expense").value || "0.75";
    const gross = $("#fee-return").value || "7";
    runQuery(`I have $${Number(amount).toLocaleString()} over ${years} years with expense ratio ${expense}% and return ${gross}% - am I overpaying in fund fees?`);
  }
  if (event.target.closest("[data-overlap-add]")) {
    const fields = event.target.closest(".overlap-controls").querySelector(".ticker-fields");
    fields.insertAdjacentHTML("beforeend", tickerField(`<input class="overlap-ticker" type="text" list="overlap-fund-list" maxlength="6" placeholder="ETF" value="">`));
  }
  if (event.target.closest("[data-ticker-remove]")) {
    const wrap = event.target.closest(".ticker-field");
    const box = wrap.parentElement;
    if (box.querySelectorAll(".ticker-field").length > 2) wrap.remove();
  }
  if (event.target.closest("[data-overlap-run]")) {
    const tickers = [...event.target.closest(".overlap-controls").querySelectorAll(".overlap-ticker")]
      .map((i) => i.value.trim().toUpperCase())
      .filter(Boolean);
    if (tickers.length >= 2) runQuery(`overlap ${tickers.join(" ")}`);
  }
  if (event.target.closest("[data-compare-add]")) {
    const controls = event.target.closest(".compare-controls");
    const fields = controls.querySelector(".ticker-fields");
    if (fields.querySelectorAll(".compare-ticker").length < 6) {
      fields.insertAdjacentHTML("beforeend", tickerField(`<input class="compare-ticker" type="text" list="compare-ticker-list" maxlength="6" placeholder="Ticker" value="">`));
    }
    event.target.disabled = fields.querySelectorAll(".compare-ticker").length >= 6;
  }
  if (event.target.closest("[data-forensic-run]")) {
    const t = event.target.closest(".forensic-controls").querySelector(".forensic-ticker").value.trim().toUpperCase();
    if (t) runQuery(`Should I buy ${t}? Show forensic red flags and the bear case.`);
  }
  if (event.target.closest("[data-compare-run]")) {
    const tickers = [...event.target.closest(".compare-controls").querySelectorAll(".compare-ticker")]
      .map((i) => i.value.trim().toUpperCase())
      .filter(Boolean);
    if (tickers.length >= 2) runQuery(`Compare ${tickers.join(" vs ")} side by side.`);
  }
  if (event.target.closest("[data-close]") || event.target.classList.contains("modal-backdrop")) $("#modal").innerHTML = "";
});

document.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" && event.key !== " ") return;
  const entityButton = event.target.closest("[data-entity-kind]");
  if (!entityButton) return;
  if (entityButton.tagName === "BUTTON") return;
  event.preventDefault();
  openEntity(entityButton.dataset.entityKind, entityButton.dataset.entityRef, entityButton.dataset.entityText || entityButton.textContent);
});

$("#ask").addEventListener("click", () => submitFromBar());
$("#query").addEventListener("focus", (event) => {
  showAskSuggestions();
  if ($("#query").value === DEMO_QUERY) $("#query").value = "";
  else event.target.select();
});
$("#query").addEventListener("keydown", (event) => {
  if (event.key === "Enter") submitFromBar();
});
// Enter inside the Sign-in modal's code field submits the code.
document.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && event.target && event.target.id === "signin-code") {
    event.preventDefault();
    submitSignIn();
  }
});

// Back/forward: replay the URL without pushing a fresh entry. A #/t/<seq> forum
// link renders the stored panel; a legacy #q= re-asks the question.
window.addEventListener("popstate", () => {
  const h = parseHash();
  if (h.seq != null) openTurn(h.seq, { push: false });
  else if (h.q) runQuery(h.q, { push: false, intent: h.intent });
  else goHome({ push: false });
});

if ("scrollRestoration" in history) history.scrollRestoration = "manual";
let SP_BASELINE = null;
let ALL_TICKERS = [];
apiGet("/api/sp500-baseline").then((d) => { SP_BASELINE = d; }).catch(() => {});
apiGet("/api/tickers").then((d) => { ALL_TICKERS = d.tickers || []; }).catch(() => {});
renderNav();
renderIdentity();
renderAskSuggestions();
updateRiskChip();
apiGet("/api/overlap-funds").then((d) => { OVERLAP_FUNDS = d.funds || []; }).catch(() => {});
apiGet("/api/landing").then(renderLanding).catch((error) => {
  $("#error").innerHTML = `<div class="error">${esc(error.message)}</div>`;
});
// Start on the landing screen; the demo query is prefilled but not auto-run.
// A #/t/<seq> forum link opens the stored topic; a legacy #q= link re-asks.
const boot = parseHash();
if (boot.seq != null) openTurn(boot.seq, { push: false });
else if (boot.q) runQuery(boot.q, { intent: boot.intent });
else {
  $("#query").value = DEMO_QUERY;
  window.scrollTo(0, 0);
}
