"""Glossary tool — static, regulator-cited ELI5 term cards (plan §3).

Terms live in app/data/glossary.json; every entry cites investor.gov (SEC).
Lookup is alias-aware and case-insensitive. Unknown terms raise KeyError — the
LLM layer can generate a card for those separately (that's a different path).
"""

import json
import pathlib

from app import contracts as c

_STORE_PATH = pathlib.Path(__file__).parent.parent / "data" / "glossary.json"
_CACHE: tuple[dict, dict] | None = None  # (raw_by_slug, alias->slug index)


def _norm(text: str) -> str:
    return " ".join(text.strip().lower().split())


def _load() -> tuple[dict, dict]:
    global _CACHE
    if _CACHE is None:
        raw = json.loads(_STORE_PATH.read_text(encoding="utf-8"))
        index: dict[str, str] = {}
        for slug, entry in raw.items():
            index[_norm(slug)] = slug
            index[_norm(entry["term"])] = slug
            for alias in entry.get("aliases", []):
                index[_norm(alias)] = slug
        _CACHE = (raw, index)
    return _CACHE


def glossary(term: str) -> c.GlossaryTerm:
    """Return the ELI5 card for a known term (by name, slug, or alias)."""
    if not term or not term.strip():
        raise ValueError("term must be a non-empty string")
    raw, index = _load()
    slug = index.get(_norm(term))
    if slug is None:
        raise KeyError(f"unknown glossary term: {term!r}")
    entry = raw[slug]
    return c.GlossaryTerm(
        term=entry["term"],
        eli5=entry["eli5"],
        example=entry["example"],
        detail_md=entry["detail_md"],
        citation=c.Citation(**entry["citation"]),
    )


def known_slugs() -> list[str]:
    raw, _ = _load()
    return sorted(raw.keys())
