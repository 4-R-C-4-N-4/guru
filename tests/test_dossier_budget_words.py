"""Regression tests for token→word budget denomination (todo:58612368).

Root cause of the c12 overrun epidemic: prompt budgets were denominated in
tokens, which Qwen (and local models generally) cannot self-count — asked
for 124 tokens it produced ~2.5x over. The same model complies with a word
budget. Fix: prompts state words = round(tokens / 1.4); validation keeps
counting cl100k tokens.
"""
import importlib.util
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
_spec = importlib.util.spec_from_file_location(
    "generate_dossiers", PROJECT_ROOT / "scripts" / "generate_dossiers.py")
gd = importlib.util.module_from_spec(_spec)
sys.modules["generate_dossiers"] = gd
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
_spec.loader.exec_module(gd)


def test_budget_words_conversion():
    # The A/B evidence: a 124-token budget must render as ~89 words,
    # never below the 60-word floor for small budgets.
    assert gd.budget_words(124) == 89
    assert gd.budget_words(80) == 60      # floor: max(60, ...)
    assert gd.budget_words(350) == 250


def test_live_templates_denominate_in_words_not_tokens():
    # Every live prose template states its budget in words; none asks the
    # model to count tokens.
    for name in ("l1-v3", "compress-v1", "fold-v1"):
        tpl = (gd.PROMPTS_DIR / f"{name}.md").read_text()
        assert "{budget_words}" in tpl, f"{name} lost {{budget_words}}"
        assert "{budget}" not in tpl, f"{name} still has a token-denominated budget"
        assert "tokens" not in tpl.split("OUTPUT")[0], \
            f"{name} still denominates in tokens"


def test_attempt_compress_prompt_carries_word_budget():
    """The compression path renders compress-v1 with budget_words derived
    from the token budget — not with the raw token number."""
    captured = []
    responses = ["word " * 300, "short enough"]  # overrun, then compressed

    class FakeGen:
        def _llm(self, system, prompt):
            captured.append(prompt)
            return responses.pop(0)

        def _attempt(self, *a, **k):
            return gd.Generator._attempt(self, *a, **k)

    def _v(raw):
        if raw != "short enough":
            raise ValueError("prose length outside sanity band")
        return raw

    out = FakeGen()._attempt("sys", "gen prompt", _v, compress_to=140)
    assert out == "short enough"
    # Second call is the compress pass carrying the word-denominated budget.
    assert len(captured) == 2
    assert "at most 100 words" in captured[1]   # round(140/1.4)
    assert "tokens" not in captured[1]
