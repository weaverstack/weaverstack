"""The performance story should lead readers back into Weaver."""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

from support.weaver_test import weaver_test

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "docs/guides/fabric-performance-optimisation/index.html"
FEATURES = ROOT / "docs/features/index.html"
DASHBOARD_DEMO = "https://docs.weaverstack.dev/assets/catalogue-dashboard/overview.html"
BOOKMARKS = (
    "https://docs.weaverstack.dev/advanced/incremental-data-processing/"
    "#bookmarks-separate-processing-state-from-source-data"
)


class GuideLinks(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: set[str] = set()
        self.iframes: list[dict[str, str | None]] = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "a" and attributes.get("href"):
            self.links.add(attributes["href"] or "")
        elif tag == "iframe":
            self.iframes.append(attributes)


@weaver_test()
def test_performance_guide_makes_weaver_visible_before_the_conclusion():
    page = GUIDE.read_text(encoding="utf-8")
    parser = GuideLinks()
    parser.feed(page)

    assert "These data engineering capabilities are included in" in page
    assert "/features/#data-engineering" in parser.links
    assert "/features/#scale" in parser.links
    assert BOOKMARKS in parser.links
    assert "https://docs.weaverstack.dev/estate/catalogue-dashboard/" in parser.links
    assert any(
        iframe.get("src") == DASHBOARD_DEMO
        and iframe.get("loading") == "lazy"
        and iframe.get("title")
        for iframe in parser.iframes
    )


@weaver_test()
def test_feature_scale_story_links_to_the_performance_guide():
    page = FEATURES.read_text(encoding="utf-8")
    scale = page.split('id="scale"', 1)[1].split('id="visibility"', 1)[0]

    assert (
        '<h3 id="scale-title"><a href="/guides/fabric-performance-optimisation/">'
        "From 3 objects to 3,000.</a></h3>"
    ) in scale
    assert "github.com/weaverstack/weaverstack/tree/main/examples/stress" not in scale
