# Changelog

What changed in each weaverstack release on PyPI. Each GitHub Release also
lists the pull requests it contains.

## 0.11.0

Changes since 0.10.0.

### Several teams' catalogues together

Each team keeps its own workspace and catalogue. `weaver health`,
`weaver load` and `weaver test` now take more than one `--catalogue` and read
them together. The catalogues are joined through the shortcuts they already
record, so nothing is configured.

```bash
weaver load Sales/Warehouse/Mart --stale --workspace Sales \
  --catalogue Central/Warehouse/Weaver --catalogue Sales/Warehouse/Weaver
```

- Health reports each catalogue in the order given, with ancestry through the
  others. A catalogue that cannot be read keeps its place with the reason, and
  an object that reads it is reported as unverified.
- Load and Test run one graph across the catalogues. Each object records in its
  own catalogue, and every record shares one workflow ID. A reader of another
  team's Warehouse table waits for that table's OneLake publication.

### Dependency cycles

Teams that read one another's data form cycles. Every graph now orders a cycle
deterministically instead of refusing it. Load runs each member once per
invocation and reports the cycle. Health does not compare load times within a
cycle, but still carries a failed or Pending member's state to the others.
Build's physical plan still requires an acyclic graph.

### Catalogue Dashboard

- `weaver catalogue-dashboard` reads one or more catalogues in any workspaces
  and deploys in the invoking workspace. Up to ten catalogues are read over
  Direct Lake on OneLake; `--ImportMode` imports them and is required for more.
- A new Workspaces page shows the network of workspaces and items, and
  Overview is now Items, grouped by workspace. The Filters pane narrows every
  page to the selected items or objects.
- `weaver catalogue-dashboard export --path <folder>` and
  `weaver.export_catalogue_dashboard()` write a deployed Dashboard's pages as
  static HTML that opens without a running capacity.

### Added

- `weaver execute` and `weaver.execute()` run ad hoc T-SQL, Spark SQL, Python
  or DAX against one item's configured target. Nothing is recorded in the
  catalogue. Spark SQL and Python need no published Environment.
- `weaver.workflow()` runs several operations in one Session, with one resolved
  configuration and one workflow ID.
- `weaver test --stale` and `weaver.test(stale=True)` run only the validations
  Health does not report as Green.
- `weaver initialise --environment Workspace/Name` uses an existing Environment
  in another workspace, so teams can share one.
- `--json` output: a Build dry run reports `actions.total`, and Load reports
  `totals` by status, as Test does.

### Changed

- A `Schema__Object` file name splits at its first `__`, so an object name may
  contain `__`. A schema name may not. Names valid in 0.10.0 keep their meaning.
- `weaver initialise` gives a project holding only Reports the default
  catalogue.
- After a Mirror, an object built locally keeps its `_.Mirror` row, marked
  deleted, as the record of what was mirrored.
- Lineage through `from shortcuts import X` for a physical shortcut reaches the
  shortcut's installed source.
- When a Build's wait for a SQL endpoint times out, the error names each table
  not yet listed and the reason Fabric gave.

### Fixed

- A Folder publishes through the load's Files mount, so a reader in the same
  load sees what it published.
- A semantic model generated over a Lakehouse shortcut to a Warehouse table
  leaves out Weaver's housekeeping columns.
- A semantic model built straight after a new shortcut refreshes the SQL
  endpoint when the source lists no columns.
- A runtime install no longer runs beside the prune of a folder above it.
- Checking installations that all name one item no longer lists the workspace.

### Upgrading

The catalogue schema is unchanged. Republish each Environment that runs Weaver
so Fabric runs 0.11.0:

```bash
weaver fabric environment publish <environment> --workspace <workspace>
```
