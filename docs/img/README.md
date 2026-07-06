# Screenshots — capture list

Drop images here with the **exact filenames** below. Docs reference them as
thumbnail → full-size links (click a thumbnail to open the full image):

```html
<a href="img/overlap-heatmap-full.png"><img src="img/overlap-heatmap-thumb.png" width="240"></a>
```

For each item make **two** files: a `-thumb.png` (~240 px wide) and a `-full.png`
(full resolution). A quick thumbnail from a full shot:

```bash
# ImageMagick
magick overlap-heatmap-full.png -resize 240x overlap-heatmap-thumb.png
```

If you'd rather ship one file per shot, you can point both links at the same
`-full.png` — the gallery still works, thumbnails will just be larger.

---

## Product (used by `README.md` and `docs/PRODUCT.md`)

| Base name | What to capture |
|---|---|
| `reddit-evidence-1` | The "no sign-up market terminal" post (single message) |
| `reddit-evidence-2` | The "explain it like I'm 5" post (single message) |
| `reddit-evidence-3` | The "prison time / IRS hallucination" comment (single message) |
| `landing` | Landing page (market-desk shelves + news + market map) |
| `landing-questions` | The generated demo-questions shelf |
| `overlap-heatmap` | ETF overlap — heatmap |
| `overlap-treemap` | ETF overlap — look-through treemap |
| `overlap-bar` | ETF overlap — shared-holdings bar |
| `overlap-donut` | ETF overlap — sector donut |
| `forensic-scores` | Forensic panel — scores + formulas + citations |
| `forensic-bearcase` | Forensic panel — bull vs bear |
| `ticker-card` | Ticker card modal (1-year chart + VOO baseline + KPIs) |
| `fee-drag` | Fee-drag calculator (two-line curve) |
| `glossary` | Glossary term card (ELI5 + investor.gov link) |
| `entities` | Inline clickable ticker/term chips in prose |
| `followups` | Follow-ups incl. the personalized concierge one |

## Backend (used by `docs/ARCHITECTURE.md`)

| Base name | How to capture |
|---|---|
| `swagger` | `http://127.0.0.1:8000/docs` — full API |
| `datasette-db` | `datasette app/data/app.db` → `turns` / `profiles` / `claims` tables |
| `adk-playground` | `agents-cli` playground rendering the agent graph (`app/adk_app.py`) |
| `eval-run` | `uv run python eval/run_eval.py --judge` terminal output |
| `pytest` | `uv run pytest` — 243 passing |
| `cloudrun` | Cloud Run console: service + public URL |

Optional extras: `semgrep` (`.semgrep` run), `docker-run` (container serving on 8080).
