"""``weaver catalogue-dashboard`` at the command line: what it passes and prints."""

from __future__ import annotations

import json

import pytest
from support.weaver_test import weaver_test

import weaver
from weaver.operations.catalogue_dashboard import (
    CatalogueDashboardResult,
    DashboardItem,
)
from weaver_cli import main


@pytest.fixture
def captured(monkeypatch, desktop_credential):
    seen: dict = {}

    def fake(**kwargs):
        seen.update(kwargs)
        catalogues = tuple(kwargs["catalogue"] or ("Demo/Warehouse/Weaver",))
        return CatalogueDashboardResult(
            workspace="Demo",
            catalogue=catalogues[0],
            catalogues=catalogues,
            mode="import" if kwargs["import_mode"] else "directLake",
            name=kwargs["name"] or "Estate",
            items=(DashboardItem("SemanticModel", "Estate", "updated", "id"),),
            sources=("_.Log",),
            warnings=("No connection reaches finance;Weaver.",)
            if kwargs["import_mode"]
            else (),
        )

    monkeypatch.setattr(weaver, "deploy_catalogue_dashboard", fake)
    return seen


def _run(*args):
    return main(
        ["catalogue-dashboard", "--workspace", "Demo", "--name", "Estate", *args]
    )


@weaver_test()
def test_each_catalogue_is_passed_in_order_and_direct_lake_is_the_default(
    captured, capsys
):
    assert (
        _run(
            "--catalogue",
            "Finance/Warehouse/Weaver",
            "--catalogue",
            "Central/Warehouse/Weaver",
        )
        == 0
    )

    assert captured["catalogue"] == [
        "Finance/Warehouse/Weaver",
        "Central/Warehouse/Weaver",
    ]
    assert captured["import_mode"] is False
    out = capsys.readouterr().out
    assert "over Direct Lake" in out
    assert out.index("Finance/Warehouse/Weaver") < out.index("Central/Warehouse/Weaver")


@weaver_test()
def test_import_mode_is_asked_for_and_reported(captured, capsys):
    assert (
        _run("--ImportMode", "--catalogue", "Finance/Warehouse/Weaver", "--json") == 0
    )

    assert captured["import_mode"] is True
    result = json.loads(capsys.readouterr().out)
    assert result["mode"] == "import"
    assert result["catalogues"] == ["Finance/Warehouse/Weaver"]
    assert result["warnings"] == ["No connection reaches finance;Weaver."]
