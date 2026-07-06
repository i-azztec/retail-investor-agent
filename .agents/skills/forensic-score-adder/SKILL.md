---
name: forensic-score-adder
description: Add a new forensic/quality score (formula + source + band + test) to the deterministic forensic tool.
---

# Forensic score adder

Forensic scores (Altman Z, Beneish M, Piotroski F) live in `app/tools/forensic.py`
and return `contracts.ForensicScore`. Scores are **formulas over filing data**,
not model opinions — that is what makes them citable.

## Steps

1. Implement the formula as a pure function over the inputs you already fetch
   (income statement / balance sheet fields). Keep inputs in the `inputs` dict.
2. Return a `ForensicScore` with: `name`, `value`, `formula` (human-readable),
   `inputs`, `interpretation`, `band` (`safe|grey|distress`), `source_line`,
   `citation_id`.
3. Choose bands from the score's published thresholds — cite the paper/regulator
   in a `Citation` (source line + URL).
4. Append it to `forensic(ticker).scores`; the scorecard/traffic blocks pick it
   up automatically via `assemble`.

## Acceptance

- `tests/test_forensic_scores.py` asserts the value on a known fixture and the
  band boundaries (safe/grey/distress).
- The score shows a formula and a citation in the panel.
