"""Template-placeholder drift guard (todo:0a81a956 review).

The hierarchical merge originally rendered compress-v1 with budget=<n> after
todo:58612368 had renamed the placeholder to {budget_words} — render() raises
on unresolved placeholders, so every merge call would have crashed at render
time. FakeGen-style tests override _llm and never exercise render, so the
drift slipped through. These tests run the REAL render on COMPRESS_TPL at
every fold call site's shape.
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


def test_compress_template_renders_with_budget_words():
    """The template's only placeholders are {budget_words} and {summary};
    rendering with budget_words= never raises and lands the number."""
    out = gd.render(gd.COMPRESS_TPL, budget_words=gd.budget_words(300),
                    summary="SUMMARY BODY")
    assert "SUMMARY BODY" in out
    assert gd.budget_words(300) in out.split() or str(gd.budget_words(300)) in out
    assert "{budget_words}" not in out and "{budget}" not in out


def test_compress_template_rejects_budget_placeholder():
    """The drift itself: budget=<n> must raise, not silently render a prompt
    with an unresolved placeholder left for the model to see."""
    try:
        gd.render(gd.COMPRESS_TPL, budget="150", summary="X")
    except ValueError as e:
        assert "unresolved placeholders" in str(e)
        assert "{budget_words}" in str(e)
    else:
        raise AssertionError("render with budget= should have raised")


def test_fold_merge_call_sites_render_shapes():
    """Both merge-level shapes (intermediate cluster + final) use keyword
    budgets that resolve against the live template. Mirrors the exact
    render calls in _fold_l1._merge_level."""
    cluster_budget, budget = 250, 300
    # intermediate-cluster shape
    gd.render(gd.COMPRESS_TPL,
              budget_words=gd.budget_words(cluster_budget),
              summary="cluster text")
    # final-merge shape
    gd.render(gd.COMPRESS_TPL,
              budget_words=gd.budget_words(budget),
              summary="final text")
