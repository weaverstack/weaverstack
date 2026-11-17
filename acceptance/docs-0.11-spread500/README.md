# 500-workspace Spread evidence

`spread500-evidence.json` holds the counts and timings that the workspace guide
(`docs/guides/organising-microsoft-fabric-workspaces/`) reports for the
500-workspace experiment. `reduce_spread500.py` produces it from the retained
run records, which stay unpublished, and records a SHA-256 for each one.

- `stages`: the 11 November 2026 managed run (attempt 2), from baseline through
  the failed full coordinated Load. The run does not qualify end to end:
  `10-coordinated-load` failed one semantic-model refresh, and
  `11-post-coordinated-health` did not run.
- `intermediate_rerun`: the later rerun on an intermediate Health build, which
  stopped in its impact assessment when the desktop ran out of file
  descriptors. Only Bronze was reloaded afterwards.
- `health_checks`: the two read-only Health checks on the 0.11.1 pre-release
  build (C and D), each over all 500 catalogues with inventories enabled.
