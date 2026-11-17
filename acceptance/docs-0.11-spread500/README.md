# 500-workspace Spread evidence

`spread500-evidence.json` holds the counts and timings that the workspace guide
(`docs/guides/organising-microsoft-fabric-workspaces/`) reports for the
500-workspace test. `reduce_spread500.py` produces it from the retained run
records, which stay unpublished, and records a SHA-256 for each one.

- `stages`: the 11 November 2026 run, from the coordinated baseline Load
  through the failed central load, the central repair, Team 05's recovery,
  the coordinated recovery of the remaining stale work and the final Health
  check.
- `health_checks`: the two Health checks (C and D) that give the guide's
  Health time, each over all 500 catalogues with inventories enabled.
