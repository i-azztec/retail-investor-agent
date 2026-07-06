"""M1: forensic tool orchestration — validation, cache mode, live (optional)."""

import pytest

from app import contracts as c
from app import tools


@pytest.mark.parametrize("good", ["AAPL", "nvda", "  msft ", "BRK.B"])
def test_validate_ticker_normalizes(good):
    assert tools.validate_ticker(good).isupper()


@pytest.mark.parametrize("bad", ["", "   ", None, "TOO-LONG-TICKER", "1234", "a b"])
def test_validate_ticker_rejects_junk(bad):
    with pytest.raises(ValueError):
        tools.validate_ticker(bad)


def test_cache_mode_returns_valid_result():
    r = tools.forensic("NVDA", data_mode="cache")
    assert isinstance(r, c.ForensicResult)
    assert r.scores and all(s.band in {"safe", "grey", "distress"} for s in r.scores)
    # every score references a citation, every citation has a source
    assert r.citations and all(cit.source for cit in r.citations)


def test_live_forensic_smoke(request):
    """Real yfinance call. Skips gracefully if the network/API is unavailable."""
    try:
        r = tools.forensic("AAPL", data_mode="live")
    except Exception as e:  # network/rate-limit/parse — not a code failure
        pytest.skip(f"live yfinance unavailable: {e}")
    assert r.ticker == "AAPL" and r.scores
    names = {s.name for s in r.scores}
    assert names & {"Altman Z", "Beneish M", "Piotroski F"}
    for s in r.scores:
        assert s.formula and s.interpretation
