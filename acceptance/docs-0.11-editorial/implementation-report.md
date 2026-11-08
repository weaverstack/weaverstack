# Weaver 0.11 editorial implementation — working evidence

Status: implementation in progress; not a release or publication sign-off. No live Fabric operations authorised or performed. Runtime, CI, package configuration and VERSION are unchanged.

## Starting revisions and ownership

Runtime: `efc046e7cf066daefd27f9268413ae05c3ed64e4`; baseline `v0.10.0` (`13a6fb359164d64b18da87f14c213c7064261a40`). Refreshed origin/main matches the brief.

| Draft | Starting head | Base | Work |
|---|---|---|---|
| product #273 | db8f6f24743a6a9c0fb68228d8091c4ea3d6897f | main | organisational article and index |
| product #274 | 485f4a89e3c6936f72b34274720b89f09600b342 | main | retained tone foundation |
| product #275 | 13da9c688446c262ad38a381aefba56caf5c22d0 | docs/site-tone | technical/product reconciliation, prose policy, acceptance evidence |
| developer #16 | ee4a8f9f7ae4f5d8cb555a7a0bf6067eb0bae4aa | main | permissions |
| developer #17 | 3239dd004c52327c1319a0275c49ae6bacc9336c | docs/permissions | developer journeys and generated integration |

Developer main starts at `0c4d7888e3e694b63ecb5aa3aa79331f1c7078fb`. Existing checkouts are untouched; work occurs in isolated worktrees. Product parent checkout contains an unrelated `.claude/launch.json` edit, which was preserved.

## Coverage ledger

The runtime comparison includes already-merged developer documentation. These are not all new 0.11 features.

| Change | Runtime evidence at the frozen revision | Reader-facing owner | Disposition |
|---|---|---|---|
| first-separator Python naming | #254 c882a3e7; declaration parsing | naming reference; docs #12 | preserve merged explanation, verify later separators/schema restriction |
| Python workflow context | #256 7fc253be; src/weaver/workflow.py | sessions-and-workflows; docs #13; product Features | product explains shared Session/config and Load/Test correlation, not invented Build/Health records |
| test --stale | #257 e6e6d7e9; operations/test.py | CLI/test, recovery; docs #14; Features | distinguish validation selection from pre-existing load --stale |
| Execute | #258 ae493a31; operations/execute.py | CLI/execute, AI agents; docs #15; Features | SQL/Python mutation stated; exact command/file input maintained |
| installation lookup | #259 252bc5ce | concise release fixes | fix, not new tutorial |
| Folder publication | #264 332c2f0d | Lakehouse runtime/release fixes | readers' run mount, not remount per publication |
| shared Environment/report-only init | #265 6b62937f | initialise, Lakehouse runtime, permissions | supported paths and platform requirements |
| housekeeping/column readiness/prune fixes | #265 | release fixes and affected model/build reference | retain actual corrected behaviour, not new features |
| cycles | #266 b459ffd2; graph.py | dependencies, across-catalogues, operation reference; Features/article | deterministic execution once/invocation, no convergence; no relative intra-cycle freshness comparison |
| joined Health | #267 73901961; operations/health.py, joined.py | across-catalogues, Health | supplied context; unassessable state not silently current; T05 separate |
| joined Load/Test | #268 a495b7e2, #269 6cce4ac1 | across-catalogues, recovery/selective runs; Features/article | context vs selection; owner-local execution/records; correlated workflow |
| cross-workspace Mirror/retained rows | #270 5e5d3d17; operations/mirror.py | Mirror walkthrough/config/behaviour/Health | product scopes Lakehouse cross-workspace vs Warehouse same-workspace |
| multi-catalogue Dashboard | #270; dashboard_model.py | Dashboard deployment, demos, Features/comparison | Direct Lake up to ten, Import more than ten, current page names |
| static HTML export | #271 efc046e7; operations/catalogue_dashboard.py | Dashboard export CLI/Python; Features/article | model-data snapshot; local downloaded copy vs remote destination availability |

Developer-specific completion and exact tests are recorded in the companion developer-repository acceptance report; this working ledger must be reconciled before sign-off.

## Technical findings

| Item | Current disposition |
|---|---|
| T01 | Confirmed in source: Execute's _RUN submits code without read-only validation. Product corrected. Developer corrections in progress. |
| T02 | No permissions inferred from --yes or config. Agent guide/parser audit delegated; product avoids universal flag protocol. |
| T03 | Source graph.py inspected: strongly connected components, closing edges based on deterministic order, acyclic execution. Article and product corrected; developer sweep in progress. |
| T04 | Product Mirror caption scoped. Developer old ownership/source and retained-row explanations under reconciliation. |
| T05 | Separate focused runtime investigation; no runtime fix authorised. Pending result. |
| T06 | Product removes universal Contributor claim. Exact Microsoft prerequisites and developer matrix under review. |
| T07 | Product and article separate supplied context from selected work and owner-local records. Article has complete three-catalogue commands, explicit working workspace and positional Team 05 selection. |
| T08 | Article rewritten around team ownership; acknowledges Fabric lineage/impact analysis; names separated from GUID identity; no business-correctness inference. |
| T09 | Product/article no unlimited Import claim or live snapshot promise. Current eight-page reader route retained. Historical snapshot bytes left unchanged. |
| T10 | Current AI route retained. Integrated developer build, old fragments and demo-helper dependency still need final verification. |

## Experiment evidence: recovered, parsed and retained

The original CLI reports were located after the initial provisional pass. The article now uses the coherent **7 November 2026 main rerun**, not the earlier PR #268 run. No Fabric rerun was performed. Runtime `efc046e7cf066daefd27f9268413ae05c3ed64e4`, wheel `weaverstack-0.10.0.dev2733981627354525514`, FTL64 trial capacity in Australia East. `runs3/RESULTS.md` records the run context; `runs3/00-publish.txt` identifies the wheel; `runs3/times.json` records CLI harness wall time.

Original evidence was in the Claude scratchpad identified by the experiment owner. Selected originals are now preserved outside disposable worktrees in the runtime repository's ignored `.cache/docs-0.11-editorial/spread-evidence/`. `spread-evidence.json` records hashes and programmatic reductions, not invented replacement output. Reproduce those reductions with `check_spread_evidence.py <retained-evidence-root>`.

| Published fact | Source and measurement boundary | Verified disposition |
|---|---|---|
| 50 workspaces, 50 catalogues, 53 connections | `runs/RESULTS.md` estate inventory; `spread_estate.py`; 50 catalogue reports in rerun | simulated team architecture, not adoption |
| 77 downstream subjects in 45 workspaces | unique `(catalogue, object_id)` findings naming BRZ.Customer in `runs3/04-impact-health.json`, excluding failed source | 61 Warehouse + 5 Lakehouse + 11 semantic models; catalogue statuses 1 red / 45 amber / 4 green |
| impact 82s | `times.json`, 04-impact-health 81.9s | rounded wall time, not only execution |
| Team05 impact 11s | 05-team05-health.txt; times 10.8s | two affected Mart tables |
| central repair 138s | 06b-central-plan.txt and 06c-central-recovery.txt; times 137.6s | six object loads, no business-team loads; planning is a separate 23.2s measurement |
| Team05 check 5s, reload 15s | 07a-team05-ready.txt, 07b-team05-reload.txt, 07c-team05-after.txt; times 5.0s / 14.9s | post-repair sequence retained; green check confirmed separately |
| 71 remaining loads, combined run in 43 workspaces, 256s | 08-federated-stale.json; times 256.0s | 112 steps = 71 logical loads owned by **42** catalogues + 41 readiness steps; **all nodes** span 43 catalogues. Do not call all 43 object owners. |
| coordinated 125 steps / 80 loads / 315s | 01-federated-load.json; times 314.5s | 125 succeeded, 41 endpoint refreshes + 4 publication waits; one workflow ID; 50 catalogues supplied but load-bearing nodes owned by 46 |
| final Health | 09-final-health.json | 49 green, one amber; do not turn this into a claim that cycles necessarily leave one member stale |

The earlier **305-second** PR #268 run is different: source `55d6e3f886756aab9e2432712057e0f6b2b88998`, published checkout `355dd0ffa16735f0987a0c806798f25e11b73949`, wheel `weaverstack-0.10.0.dev12201172653880442203`, prior to review fixes. It must not replace or be rounded into the 315-second main rerun.

The final amber finding names Team02 `MART.RegionCustomers` as the newer ancestor of Team01 `MART.PeerSummary`. `RegionCustomers` is **outside** the reported strongly connected component (whose Team02 member is `MART.Summary`). This is not evidence that Health compared relative load times inside the cycle. The article teaches current cycle semantics without attributing this historical finding to a nonexistent universal cycle rule.

Thin-report workspaces have no separate load here, but can still display affected source data. No business-correctness claim is drawn from the recorded states. No invented first-person authorship; the organisational byline is retained.

## Editorial changes and reusable policy

- Features lead: generic consistency promise → concrete division of work between the team and Weaver.
- Visibility: storage definition → failed-load investigation → records and included Dashboard.
- Execute: “Query an item without changing state” → command/file submission and explicit SQL/Python mutation.
- Article: search-phrase-heavy opening → a central team's ownership decision and a Finance dependency; independent schedules no longer imply an inability to coordinate.
- Article conclusion: repeated self-service claims → central coordination and business-team ownership through the same records.
- Product PROSE.md now distinguishes product, teaching and reference voices; requirements stay beside tasks, destructive warnings stay visible, measured results keep provenance.
- Reusable weaver-site-editorial skill removes stale blanket-DAG/locked-old-sentence guidance. technical-documentation-delivery gains integrated release/coverage/parser/evidence checks. Skills supplement, rather than duplicate, the canonical per-repository PROSE policy.

## Validation performed so far

From isolated product site worktree:

- `python tools/check_product_site.py`: pass (9 routes, local links/fragments/metadata); cross-site destinations not yet checked against final developer build.
- article branch same checker: pass (10 routes); independent article branch still has older product-page content until integrated with #275.
- focused Features/performance-guide/website-routing/test-architecture invariants: 12 passed after updating visibility expectation.
- `python -m pytest tools/test_check_product_site.py -q`: 11 passed after changing a stale heading-specific fixture to a stable scale-title anchor.
- local parser check via build_parser(): seven product/article commands parsed, none dispatched. Includes explicit Team05 selection and working workspace.
- `git diff --check`: pass.

Pending: combined runtime representation tests, integrated article/site build, final developer-site link/fragment crawl, desktop/mobile/no-JS rendered review and exact final PR head readback.

## Proposed later integration/publication order

No merge/publication authorised. Retain draft PR status.

1. Review permissions #16 then release docs #17, keeping stack bases consistent.
2. Review product tone #274 then release product #275; the demo helper in #275 is a local generation dependency for #17, not a reason to publish the product first.
3. Validate both final trees together using the helper from #275 and the frozen runtime. Review article #273 alongside them.
4. When separately authorised, publish developer destinations before product links to those destinations. Runtime/package release availability must be reconciled with installation copy before public launch.
