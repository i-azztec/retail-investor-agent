# 5-minute video — storyboard & narration

Weighting follows what won the previous capstone: **problem + demo carry the
time; architecture / build stay compact.** Judges reward an explicit "why agents"
line and an explicit list of course concepts. Keep it **≤ 5:00**, publish on
YouTube, and **show no API keys on screen.**

Format: slides (Problem · Why agents · Architecture · Build · Value) + a screen
recording for the demo, all under one continuous voiceover.

---

## Storyboard

| Time | Block | On screen | Voiceover beat |
|---|---|---|---|
| 0:00–1:15 | **Problem & approach** | Cover (needs word-cloud) → 3 Reddit screenshots (NVDA-not-Enron, "no sign-up" terminal, "explain like I'm 5") | We read ~350 real retail posts. Beginners want a free, no-login, honest second opinion — and they're scared of AI getting numbers wrong. That fear defined the product. |
| 1:15–1:45 | **Why agents** | Simple graph: router → analyst ‖ skeptic → narrator | A single prompt collapses everything into one voice and drops the counter-argument. We make it structural: an analyst and a skeptic run in parallel, so "what looks good" and "what to watch" are always both there. |
| 1:45–3:45 | **Demo** (core) | Screen recording | Landing → ETF overlap (interactive charts) → click a ticker → forensic NVDA → fee calculator → glossary → concierge follow-up. |
| 3:45–4:20 | **Architecture & build** (fast) | One slide: the 3 diagrams + a bullet list | Numbers are computed by deterministic tools, every one cited — the LLM only writes language. ADK multi-agent, function calling, MCP, persistent sessions + memory, security guardrails, 243 tests, LLM-as-judge eval, one container on Cloud Run. Details are in the docs. |
| 4:20–5:00 | **Value & close** | Value slide | Verifiable, plain-language, balanced, private, free. Read-only — it informs, it never trades. Thanks to Kaggle & Google. |

Demo click-path (rehearse until it's tight):
`landing → "VOO, QQQ, VGT overlap?" → treemap company → "Should I buy NVDA? red flags + bear case" → fee calculator ($50k / 30y / 0.25%) → "explain expense ratio" → personalized follow-up.`

---

## Narration script (~740 words ≈ 5:00 at a calm pace)

**[Problem — 0:00]**
Meet a beginner investor. They've got a brokerage account, a few thousand
dollars, and a lot of anxiety. To understand what they actually want, we read
about three hundred and fifty real posts and comments from retail investors. Not
what experts think they *should* want — what they ask for in their own words.

Three things came up again and again. First: give me one *free* place, *no
sign-up*, to make sense of my investments. Second: explain it like I'm five — I'm
new. And third, the one that shaped everything: give me numbers I can *trust and
verify*, because I'm scared of an AI getting it wrong. One investor put it
bluntly — they don't want an AI that could get them *audited by the IRS over a
hallucination.* Another worried about *prison time if there are errors.* The
recurring engineering advice underneath it: *LLMs are bad at numbers — make the
logic deterministic.*

So we built exactly that: a read-only second opinion that *shows its work.*

**[Why agents — 1:15]**
Why use agents at all, instead of one big prompt? Because a good answer to an
investing question is several jobs at once: classify what's being asked, pull the
right grounded data, argue the bull case *and* the bear case, then translate it
for a beginner. A single prompt blends those into one voice — and quietly drops
the counter-argument. We make the counter-argument *structural.* An **analyst**
and a **skeptic** run in parallel as independent agents, so "what looks good" and
"what to watch" are always both on screen. A router classifies, tools compute, a
narrator explains.

**[Demo — 1:45]**
Here's the product. The landing page isn't an empty chat — it's a market desk
with freshly generated questions. Let's ask the flagship one: *I hold VOO, QQQ
and VGT — how much do they really overlap?* Instead of a wall of text, we get a
panel: an overlap heatmap, a treemap looking *through* the funds into the real
companies, a shared-holdings bar, and a sector donut. The takeaway lands in
seconds — these three "diversified" funds are largely the same mega-caps.

Everything is clickable. I'll open one company as a ticker card — a one-year chart
against the S&P baseline. Now the anxious question: *Should I buy NVDA? Show the
red flags and the bear case.* We compute forensic scores — Altman Z, Beneish M,
Piotroski F — and every number carries its formula and a citation. The analyst
gives the bull case; the skeptic gives the bear case. It's a screen, not a
verdict, and we say so.

Costs next: *am I overpaying in fees?* A fee-drag curve shows what an expense
ratio quietly costs over decades. And a jargon question — *explain expense ratio*
— returns a plain-language card with a link to the regulator. Notice the last
follow-up: it remembers what I looked at earlier and offers a personalized next
step. That's the concierge touch.

**[Architecture & build — 3:45]**
Under the hood, one principle: the language model routes and explains, but
**deterministic tools compute every number, and every number is cited.** That's
the direct answer to "I don't trust AI with math." The reasoning is a real ADK
multi-agent graph. Behind flags, the agent can invoke its tools itself through
function calling, and even consume them over MCP. Context flows through persistent
sessions and long-term memory. There are guardrails on input and output, two
hundred and forty-three tests, an LLM-as-judge evaluation, and the whole thing
ships as one container on Cloud Run. The details are all in the documentation.

**[Value & close — 4:20]**
So this is a helper built from what investors actually ask for: verifiable,
plain-language, balanced, private, and free. It reads only public data, keeps no
personal information, and never places a trade — it informs, it doesn't act. A
thoughtful second opinion shouldn't require a Bloomberg terminal or a login.
Thanks to Kaggle and Google for the intensive course that made this possible.

---

## Production notes

- Record the demo separately, tight and rehearsed; overlay the voiceover.
- Export the three Mermaid diagrams from `ARCHITECTURE.md` to PNG
  (mermaid.live or `mmdc`) for the architecture slide.
- Auto-build the slide deck from facts + screenshots with **NotebookLM** (free,
  grounded in your source docs) or **Gamma** (fastest text→slides); polish with
  **Beautiful.ai**/**Canva**. Budget 15–30 min of manual cleanup.
- Cover image = needs word-cloud (required by the Media Gallery).
