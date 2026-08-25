"""Regression tests for the _attempt compression retry (todo:b1c8be4c).

Observed on blavatsky-sd c12: length-band overruns were treated as
pass/fail re-rolls — 3 identical regenerations, then the span was dropped
entirely. The fix: after the first length overrun, feed the model its own
output back through a compress instruction instead of regenerating.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
_spec = importlib.util.spec_from_file_location(
    "generate_dossiers", PROJECT_ROOT / "scripts" / "generate_dossiers.py")
gd = importlib.util.module_from_spec(_spec)
sys.modules["generate_dossiers"] = gd
# generate_dossiers imports siblings from scripts/ — make that importable.
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
_spec.loader.exec_module(gd)


class FakeGen:
    """Minimal stand-in exercising only the _attempt retry machinery."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []
        self.calls = 0

    def _llm(self, system, prompt):
        self.calls += 1
        self.prompts.append(prompt)
        return self.responses.pop(0)

    def _attempt(self, *args, **kwargs):
        # Bind the real method onto this fake.
        return gd.Generator._attempt(self, *args, **kwargs)


def _v_prose_len(raw, lo, hi):
    n = len(raw.split())
    if not (lo <= n <= hi):
        raise ValueError(
            f"prose length {n} outside sanity band [{lo}, {hi}]")
    return raw


def test_overrun_switches_to_compress_not_regenerate():
    """The core fix: an overrunning summary is fed back for compression,
    not thrown away and regenerated at 3x compute."""
    long_summary = " ".join(["claim"] * 120)  # 120 words vs band [10, 20]
    compressed = " ".join(["claim"] * 15)     # in-band
    gen = FakeGen([long_summary, compressed])

    out = gen._attempt("sys", "gen prompt",
                       lambda r: _v_prose_len(r, 10, 20), compress_to=15)
    assert out == compressed
    assert gen.calls == 2
    # Second call must be the COMPRESS template carrying the model's own
    # overrunning output — not a re-roll of the generation prompt.
    assert "compress" in gen.prompts[1].lower()
    assert long_summary in gen.prompts[1]


def test_non_length_rejects_still_use_corrective_feedback():
    """Scaffold/echo rejects keep the original corrective-feedback retry;
    they never enter the compression path."""
    responses = [
        "# Summary\nsome scaffolded text here",  # scaffold reject
        "Clean prose here",                        # passes
    ]
    gen = FakeGen(responses)

    def _v(raw):
        gd._v_no_scaffold(raw, prose=True)
        return _v_prose_len(raw, 2, 20)

    out = gen._attempt("sys", "gen prompt", _v)
    assert out == "Clean prose here"
    assert gen.calls == 2
    # Second attempt carries the corrective feedback line, not a compress prompt.
    assert "Your previous output was rejected" in gen.prompts[-1]
    assert all("compress the summary below" not in p.lower() for p in gen.prompts)


def test_compress_still_validated_and_can_fail():
    """A compressed result that STILL violates the contract exhausts the
    attempt budget and returns None (span surfaces in the gap report)."""
    long = " ".join(["claim"] * 120)
    still_long = " ".join(["claim"] * 100)
    gen = FakeGen([long, still_long])

    out = gen._attempt("sys", "gen prompt",
                       lambda r: _v_prose_len(r, 10, 20), compress_to=15)
    assert out is None
    assert gen.calls == 2  # generate -> compress -> give up


def test_no_compress_budget_keeps_legacy_loop():
    """Callers without a prose budget (structure/fields) are unchanged."""
    def _v(raw):
        if raw != "good":
            raise ValueError("nope")
        return raw

    gen = FakeGen(["bad", "good"])
    out = gen._attempt("sys", "gen prompt", _v)
    assert out == "good"
    assert gen.calls == 2


def test_compress_template_exists_and_carries_placeholders():
    tpl = (PROJECT_ROOT / "prompts" / "dossier" / "compress-v1.md").read_text()
    assert "{budget}" in tpl and "{summary}" in tpl
    rendered = gd.render(gd.COMPRESS_TPL, budget="150", summary="SUMMARY TEXT")
    assert "SUMMARY TEXT" in rendered and "150" in rendered
