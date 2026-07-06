"""Prefetch dense ticker cards into the committed seed catalog.

Run once locally with network access:

    TICKER_HISTORY_PERIOD=1y TICKER_HISTORY_POINTS=400 \
        uv run python scripts/prefetch_ticker_cards.py

Writes app/data/ticker_cards_seed/{TICKER}.json for every SEED_TICKER. That
directory is committed (it is NOT under app/data/.cache/, which .gitignore
excludes), so the dense demo charts survive the Docker build / Cloud Run deploy.

Numbers still come from yfinance formulas/data, not an LLM — grounding holds.
"""

import importlib
import json
import os
import sys

# Ensure repo root on path when run as a script.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import tools  # noqa: E402

# Import the submodule via importlib: `from app.tools import ticker_card` would
# bind the re-exported *function*, not the module (see app/tools/__init__.py).
tc = importlib.import_module("app.tools.ticker_card")

# Deterministic seed universe: top S&P 500 names + all bundled ETFs + fallback
# profiles. Kept as an explicit constant so the catalog is reproducible.
SEED_TICKERS: list[str] = sorted(
    set(
        [
            "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "GOOG", "META", "TSLA",
            "AVGO", "AMD", "ORCL", "CRM", "ADBE", "NFLX", "INTC", "CSCO",
            "QCOM", "TXN", "IBM", "NOW", "UBER", "PLTR", "MU", "AMAT",
            "JPM", "BAC", "WFC", "GS", "MS", "V", "MA", "AXP",
            "BRK-B", "UNH", "JNJ", "LLY", "PFE", "MRK", "ABBV", "TMO",
            "WMT", "COST", "HD", "MCD", "NKE", "SBUX", "PG", "KO", "PEP",
            "DIS", "CMCSA", "T", "VZ", "XOM", "CVX", "BA", "CAT", "GE",
            "F", "GM", "PYPL", "SQ", "SHOP", "COIN", "ABNB", "SNOW",
        ]
        + list(tools.available_etfs())
    )
)


def main() -> int:
    os.environ.setdefault("TICKER_HISTORY_PERIOD", "1y")
    os.environ.setdefault("TICKER_HISTORY_POINTS", "400")
    tc._SEED_DIR.mkdir(parents=True, exist_ok=True)

    ok, failed = 0, 0
    for ticker in SEED_TICKERS:
        try:
            card = tc._compute_live(ticker)
            if ticker in tools.available_etfs():
                card = tc._etf_card_from_cache(
                    ticker, base=card, note="Prefetched live price + bundled ETF holdings."
                )
            tc._seed_path(ticker).write_text(
                json.dumps(card.model_dump(mode="json"), indent=2), encoding="utf-8"
            )
            points = len(card.price_series)
            print(f"  ok  {ticker:6s} {points} points")
            ok += 1
        except Exception as exc:  # noqa: BLE001 — best-effort prefetch, skip failures
            print(f"  skip {ticker:6s} {type(exc).__name__}: {exc}")
            failed += 1
    print(f"\nDone: {ok} written, {failed} skipped -> {tc._SEED_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
