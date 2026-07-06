"""Evalset validity: well-formed, uses real intents, covers every intent."""

from typing import get_args

from app import contracts as c

import importlib.util
import pathlib

_spec = importlib.util.spec_from_file_location(
    "run_eval", pathlib.Path(__file__).parent.parent / "eval" / "run_eval.py"
)
run_eval = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_eval)


def test_evalset_is_well_formed():
    cases = run_eval.load_evalset()
    assert len(cases) >= 20
    for case in cases:
        assert case["query"].strip()
        assert case["expected_intent"] in get_args(c.Intent)


def test_evalset_covers_every_intent():
    cases = run_eval.load_evalset()
    covered = {case["expected_intent"] for case in cases}
    assert set(get_args(c.Intent)) <= covered
