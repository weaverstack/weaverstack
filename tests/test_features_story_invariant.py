from pathlib import Path

from support.weaver_test import weaver_test

ROOT = Path(__file__).resolve().parents[1]
FEATURES = ROOT / "docs/features/index.html"
HOME = ROOT / "docs/index.html"
DAG_NODES = (
    "folder",
    "event",
    "current",
    "shortcut",
    "consumer",
    "model",
    "report",
)
DAG_EDGES = (
    "folder|event",
    "event|current",
    "event|shortcut",
    "shortcut|consumer",
    "consumer|model",
    "model|report",
)


@weaver_test()
def test_features_and_homepage_show_different_fabric_objects_in_one_dag():
    features = FEATURES.read_text(encoding="utf-8")
    homepage = HOME.read_text(encoding="utf-8")

    assert (
        '<h3 id="dag-title">A single DAG across all your work — from Python to SQL '
        "to Power BI.</h3>"
    ) in features
    assert '<svg class="parcel-diagram"' in features
    assert "Different Fabric objects, one DAG." in homepage
    assert "Python, Spark SQL, T-SQL, a semantic model and a Report" in homepage

    for node in DAG_NODES:
        marker = f'data-project-node="{node}"'
        assert marker in features
        assert marker in homepage

    for edge in DAG_EDGES:
        marker = f'data-project-edge="{edge}"'
        assert marker in features
        assert marker in homepage

    assert features.count('data-project-edge="event|') == 2
    assert 'data-boundary="Lakehouse:Warehouse"' in features


@weaver_test()
def test_warehouse_visibility_is_one_feature_story():
    features = FEATURES.read_text(encoding="utf-8")
    jumps = features.split('class="feature-jumps"', 1)[1].split("</nav>", 1)[0]
    visibility = features.split(
        '<section class="section feature-group" id="visibility"', 1
    )[1].split('<section class="section feature-group"', 1)[0]

    assert "#operations" not in jumps
    assert jumps.count("#visibility") == 1
    assert '<section class="section feature-group" id="operations"' not in features
    assert (
        "The entire estate — every object and its health state — is exposed through "
        "Warehouse tables."
    ) in visibility
    assert (
        "So you know exactly what exists, what ran and what needs attention."
        in visibility
    )
    assert "Visibility, included" in visibility
    assert visibility.index("Visibility, included") < visibility.index(
        'data-spotlight="catalogue-dashboard"'
    )
    assert 'data-feature="catalogue"' in visibility
    assert 'data-feature="dashboard-deploy"' in visibility
