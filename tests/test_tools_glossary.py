"""M1: static glossary tool — lookup, aliases, citations, guards.

Use the package-level API (`tools.glossary`, `tools.known_slugs`) — that's the
public surface the agent uses, and it avoids the module/function name overlap.
"""

import pytest

from app import contracts as c
from app import tools


def test_lookup_by_term_returns_card_with_investorgov_citation():
    card = tools.glossary("expense ratio")
    assert isinstance(card, c.GlossaryTerm)
    assert card.citation.source == "investor.gov"
    assert card.citation.url.startswith("https://www.investor.gov/")
    assert card.eli5 and card.example and card.detail_md


def test_lookup_is_alias_and_case_insensitive():
    by_alias = tools.glossary("ETF")
    by_name = tools.glossary("Exchange-traded fund (ETF)")
    assert by_alias.term == by_name.term


def test_generated_entity_terms_have_cards():
    assert tools.glossary("concentration").term == "Concentration"
    assert tools.glossary("Altman Z").term == "Altman Z-Score"
    assert tools.glossary("Beneish M").term == "Beneish M-Score"
    assert tools.glossary("Piotroski F").term == "Piotroski F-Score"
    assert tools.glossary("P/E percentile").term == "P/E ratio"
    assert tools.glossary("Form 4").term == "Form 4"
    assert tools.glossary("dividend safety").term == "Dividend safety"
    assert tools.glossary("market movers").term == "Market movers"


def test_unknown_term_raises_keyerror():
    with pytest.raises(KeyError):
        tools.glossary("frobnication ratio")


@pytest.mark.parametrize("bad", ["", "   ", None])
def test_empty_term_raises_valueerror(bad):
    with pytest.raises(ValueError):
        tools.glossary(bad)


def test_all_entries_validate_and_cite_trusted_source():
    for slug in tools.known_slugs():
        card = tools.glossary(slug)
        assert card.citation.url.startswith(("https://www.investor.gov/", "https://www.sec.gov/"))
