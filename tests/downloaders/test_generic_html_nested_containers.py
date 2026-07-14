"""Regression test for todo:89425b7b — nested content containers.

Global Grey pages lay out the book as <main><article>…</article></main>.
generic_html.extract_text collected soup.find_all("main") AND
find_all("article") into one container list, so the article's text was
concatenated after the main's — duplicating the entire book (the
transcendental-magic raw came out at 1.43M chars from a 760KB page, every
chapter heading appearing exactly twice). The id()-based dedup only caught
the same element, not one nested inside another.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "downloaders"))

import generic_html  # noqa: E402


NESTED_FIXTURE = """
<html>
  <body>
    <main>
      <article>
        <h1>Transcendental Magic</h1>
        <p>Behind the veil of all the hieratic and mystical allegories.</p>
        <p>A second paragraph of primary text.</p>
      </article>
    </main>
  </body>
</html>
"""

SIBLING_FIXTURE = """
<html>
  <body>
    <main><p>First independent block.</p></main>
    <article><p>Second independent block.</p></article>
  </body>
</html>
"""


def test_nested_main_article_extracted_once():
    text = generic_html.extract_text(NESTED_FIXTURE, "test-nested")
    assert text.count("Behind the veil of all the hieratic") == 1
    assert text.count("A second paragraph of primary text.") == 1


def test_sibling_containers_both_kept():
    text = generic_html.extract_text(SIBLING_FIXTURE, "test-siblings")
    assert "First independent block." in text
    assert "Second independent block." in text


if __name__ == "__main__":
    test_nested_main_article_extracted_once()
    test_sibling_containers_both_kept()
    print("ok")
