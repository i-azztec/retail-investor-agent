"""Deterministic tools. Each returns a typed contract from app.contracts.

Tools compute numbers by formula/data (not LLM opinion) so every value is
citable and unit-testable without a model. See plan §3.
"""

from app.tools.calculators import fee_drag, growth, rule72
from app.tools.glossary import glossary, known_slugs
from app.tools.forensic import forensic, validate_ticker
from app.tools.overlap import available_etfs, load_cached_etf, overlap, validate_etf_ticker
from app.tools.ticker_card import known_tickers, ticker_card

__all__ = [
    "fee_drag",
    "growth",
    "rule72",
    "glossary",
    "known_slugs",
    "forensic",
    "validate_ticker",
    "ticker_card",
    "known_tickers",
    "overlap",
    "available_etfs",
    "load_cached_etf",
    "validate_etf_ticker",
]
