"""The Catalogue Dashboard's pages exported as static HTML."""

from __future__ import annotations

import pytest
from support.weaver_test import weaver_test
from test_catalogue_dashboard_cycle import DashboardDefinition, dashboard_session

import weaver
from weaver.dashboard_model import page_measures, page_text
from weaver.errors import CommandError
from weaver.locations import Location

RENDERER = "<style>.wd{}</style><script>draw()</script>"


class Answering(DashboardDefinition):
    """A deployed Dashboard that answers each measure with a text of its own."""

    def __init__(self):
        super().__init__()
        self.queries = []

    def query_dax(self, query):
        self.queries.append(query)
        measure = query.split("[", 1)[1].rsplit("]", 1)[0]
        if measure == "Renderer":
            return [{"[v]": RENDERER}]
        # Data measures may hold "<", which a page escapes as DAX does.
        return [{"[v]": f"{measure}<x>"}]


def exporting(**options):
    session, _model, _report = dashboard_session(**options)
    model = Answering()
    session.answer_semantic_model("Demo", "Estate Dashboard", model)
    return session, model


@weaver_test()
def test_every_page_is_written_from_its_sections_with_the_renderer(tmp_path):
    session, model = exporting()

    result = weaver.export_catalogue_dashboard(tmp_path / "out", session=session)

    pages = page_measures()
    assert [page.page for page in result.pages][0] == "workspaces"
    assert {page.page for page in result.pages} == {page.page for page in pages}
    written = sorted(path.name for path in (tmp_path / "out").iterdir())
    assert written == sorted([f"{p.page}.html" for p in pages] + ["index.html"])
    for page in pages:
        html = (tmp_path / "out" / f"{page.page}.html").read_text(encoding="utf-8")
        values = [f"{section}<x>" for section in page.sections]
        assert page_text(page.page, values, RENDERER) in html
        # The data's "<" is escaped as the page measure escapes it; the renderer's is not.
        assert "<x>" not in html and RENDERER in html
        exported = next(p for p in result.pages if p.page == page.page)
        assert exported.characters == len(html)
    index = (tmp_path / "out" / "index.html").read_text(encoding="utf-8")
    assert index == (tmp_path / "out" / "workspaces.html").read_text(encoding="utf-8")
    # Each page links to every other, and marks itself.
    assert '<a href="entities.html">Entity dictionary</a>' in index
    assert '<a href="workspaces.html" aria-current="page">Workspaces</a>' in index


@weaver_test()
def test_each_data_measure_is_read_once_whatever_the_pages_share(tmp_path):
    session, model = exporting()

    weaver.export_catalogue_dashboard(tmp_path / "out", session=session)

    sections = {s for page in page_measures() for s in page.sections}
    assert len(model.queries) == len(sections) + 1
    assert len(set(model.queries)) == len(model.queries)


@weaver_test()
def test_a_onelake_destination_is_written_through_the_sessions_store(tmp_path):
    session, _model = exporting()
    written = {}

    class Recording:
        def make_directory(self, location):
            written[location.value] = None

        def write(self, location, data):
            written[location.value] = data

    session.transport_store = lambda workspace=None: Recording()
    folder = "abfss://ws@onelake.dfs.fabric.microsoft.com/lh/Files/dashboard"

    result = weaver.export_catalogue_dashboard(folder, session=session)

    assert result.path == folder
    assert f"{folder}/index.html" in written
    assert written[f"{folder}/entities.html"].startswith(b"<!doctype html>")


@weaver_test()
def test_a_dashboard_that_is_not_deployed_is_named_with_the_next_step(tmp_path):
    session, _model = exporting(existing=False)

    with pytest.raises(CommandError, match="Deploy it with weaver catalogue-dashboard"):
        weaver.export_catalogue_dashboard(tmp_path / "out", session=session)
    assert not (tmp_path / "out").exists()


@weaver_test()
def test_the_result_reports_plain_data(tmp_path):
    session, _model = exporting()

    result = weaver.export_catalogue_dashboard(tmp_path / "out", session=session)

    report = result.report()
    assert report == result.to_mapping()
    assert report["name"] == "Estate Dashboard" and report["workspace"] == "Demo"
    assert report["path"] == Location(str(tmp_path / "out")).value
    assert {"page", "title", "file", "characters"} <= set(report["pages"][0])
