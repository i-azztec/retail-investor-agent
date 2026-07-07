# Screenshots — inventory

**One file per shot — no separate `-thumb`.** The docs shrink each image with the
HTML `width` attribute, so a single full-resolution PNG is both the thumbnail and
the full-size target:

```html
<a href="img/overlap-full.png"><img src="img/overlap-full.png" width="240"></a>
```

Click a thumbnail to open the full image.

---

## Product — present (used by `README.md` and `docs/PRODUCT.md`)

**Normal screenshots** (single screen):

| File | What it shows |
|---|---|
| `coins-growth-wordcloud.png` | Needs word-cloud — README cover |
| `landing-start.png` | Landing — market desk (entry) |
| `landing-questions.png` | Generated demo-questions shelf |
| `landing-market-map.png` | Market-map heatmap |
| `landing-sign-in.png` | Optional sign-in / recovery code |
| `ticker-card.png` | Ticker card modal (1-yr chart + VOO baseline + KPIs) |
| `learn-term.png` | Glossary term card (ELI5 + investor.gov link) |

**Full pages** (scroll-captured, tall — shown in a row):

| File | What it shows |
|---|---|
| `landing-full.png` | Landing, full page |
| `ticker-full.png` | Ticker answer, full page |
| `compare-full.png` | Compare answer, full page |
| `overlap-full.png` | ETF overlap answer, full page |
| `fee-calc-full.png` | Fee calculator answer, full page |
| `red-flag-full.png` | Forensic red-flag screen, full page |
| `learn-full.png` | Glossary / learn, full page |

**Screen-recordings** are embedded from uploaded GitHub asset URLs
(`user-attachments/...`), not from the repo. The small `docs/videos/*-web.mp4`
mirrors are kept for reference; raw captures live in the git-ignored `.videos/`.

## Build — present (used by `docs/ARCHITECTURE.md`)

| File | What it shows |
|---|---|
| `antigravity-skills.png` | Agent skills authored in Google Antigravity (captioned) |
| `antigravity-deployability.png` | Deployability workflow in Antigravity (captioned) |

## Backend — TODO (placeholders in `docs/ARCHITECTURE.md`)

Capture from a local run, drop in with these exact names (single file each):

| File | How to capture |
|---|---|
| `swagger.png` | `http://127.0.0.1:8000/docs` — full API |
| `datasette-db.png` | `datasette app/data/app.db` → `turns` / `profiles` / `claims` |
| `adk-playground.png` | `agents-cli` playground rendering the agent graph (`app/adk_app.py`) |
| `eval-run.png` | `uv run python eval/run_eval.py --judge` terminal output |
| `pytest.png` | `uv run pytest` — 243 passing |
| `cloudrun.png` | Cloud Run console: service + public URL |
