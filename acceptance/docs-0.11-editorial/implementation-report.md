# Weaver 0.11 editorial implementation — working evidence

Status: draft implementation complete, with the confirmed T05 runtime defect explicitly outstanding; not a release or publication sign-off. No live Fabric operations authorised or performed. Runtime, CI, package configuration and VERSION are unchanged.

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

Developer-specific completion, full coverage and exact tests are recorded in the companion developer-repository `acceptance/docs-0.11-editorial/` report and ledger. The final docs bundle passes 20/20 checks after correcting a stale example-format assertion. The confirmed T05 defect remains separate from editorial completion.

## Technical findings

| Item | Current disposition |
|---|---|
| T01 | Confirmed in source: Execute's _RUN submits code without read-only validation. Product and developer docs corrected. |
| T02 | No permissions inferred from --yes or config. Agent guide corrected; 54 complete commands parsed without dispatch. Check/workflow flag restrictions tested. |
| T03 | Source graph.py inspected: strongly connected components, closing edges based on deterministic order, acyclic execution. Article, product and developer contradiction sweep corrected. |
| T04 | Product Mirror caption scoped. Developer ownership/source, scope and retained-row explanations reconciled. |
| T05 | Confirmed offline: joined remote workspace resolution clears mirror configuration, so Health cannot resolve borrowed state. Separate developer T05 report/probe retained. Own-configuration invocation documented; runtime unchanged. |
| T06 | Product removes universal Contributor claim. Microsoft-backed permissions cover semantic ownership, default/shared Environments, shortcut identity, Execute Queries and organisational visuals. |
| T07 | Product and article separate supplied context from selected work and owner-local records. Article has complete three-catalogue commands, explicit working workspace and positional Team 05 selection. |
| T08 | Article rewritten around team ownership; acknowledges Fabric lineage/impact analysis; names separated from GUID identity; no business-correctness inference. |
| T09 | Product/article no unlimited Import claim or live snapshot promise. Current eight-page reader route retained. Historical snapshot bytes left unchanged. |
| T10 | Current AI route/#json-output retained; developer rendered crawl covers 114 original pages and 872 fragments. Integrated product-to-built-docs check passes, including root URLs and actual pointer destinations. Demo check passes with #275 helper. |

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

Final additional validation:

- Parent reran all 20 developer checks: strict MkDocs, four generated references, Dashboard demo, estate/reference/refresh/journey examples, route/asset checks, generator tests, complete commands and T05 probe: 20/20 pass. The stale Executive format expectation now checks its existing authored `0 "delivered"` override; no fixture/runtime change.
- 296 focused runtime tests passed in the developer investigation; parent independently ran 51 joined Health/Load representation tests, all passing.
- Product checker regression suite: 12 passed after adding a failing-then-passing root-URL regression. Integrated checking also exposed an old pointer gate that looked up the source route on the developer site rather than its actual destination; corrected to resolve destination host/path/fragment, without disabling broken-target checks.
- Product #275 and article #273 merged only into a detached local integration tree. Combined product checker against the built developer site passes; both remote bases remain unchanged.
- Actual browser review at 1280px desktop and 390px mobile: Features, article opening/results; no page-level horizontal overflow. Results table scrolls inside its container on mobile. Features content and safety statement remain readable with JavaScript disabled; full navigation remains available. Developer targeted desktop/mobile review is recorded in its own report.
- Loopback HTML and private tailnet HTTPS article content verified. Review preview serves only integrated product `docs/`, not a repository root. It remains a tracked review server, not public deployment; requires this Mac awake and connected. No unrelated Serve route was changed.

Final scope: draft editorial changes, acceptance evidence and reusable skills are delivered. T05 is a real runtime issue requiring separate authorisation, not an unresolved prose task. Exact final PR head/draft readback accompanies the delivery message.

## Proposed later integration/publication order

No merge/publication authorised. Retain draft PR status.

1. Review permissions #16 then release docs #17, keeping stack bases consistent.
2. Review product tone #274 then release product #275; the demo helper in #275 is a local generation dependency for #17, not a reason to publish the product first.
3. Validate both final trees together using the helper from #275 and the frozen runtime. Review article #273 alongside them.
4. When separately authorised, publish developer destinations before product links to those destinations. Runtime/package release availability must be reconciled with installation copy before public launch.

## Final reviewed content and file inventory

| Existing draft | Final reviewed content head | Base retained |
|---|---|---|
| product #273 | `abf7606fe107404f3d0d9b47b3f7a7baa838e9b8` | main |
| product #274 | `485f4a89e3c6936f72b34274720b89f09600b342` (unchanged) | main |
| product #275 | `1f5aa471` (final product/checker content; this report-only delivery commit follows it) | docs/site-tone |
| developer #16 | `7bc1ccb04397458961f12ba10ed1cee4167b9fbf` | main |
| developer #17 | `121ce2f8164614544ecd25afefe5f23a82545fbd` | docs/permissions |

Final delivery readback records the full #275 reporting-commit hash in the user response; a tracked report cannot include its own commit hash. Runtime remains frozen at `efc046e7cf066daefd27f9268413ae05c3ed64e4`. The detached integration checkout combines the exact article/product content above for local testing only, without changing remote bases.

Changed product files relative to the starting draft: `PROSE.md`; `docs/features/index.html`; `docs/get-started/index.html`; `acceptance/features-unification/claims.json`; `tests/test_features_story_invariant.py`; `tools/check_product_site.py`; `tools/test_check_product_site.py`; and the three files in `acceptance/docs-0.11-editorial/`. Article changes: `docs/guides/index.html` and `docs/guides/organising-microsoft-fabric-workspaces/index.html`.

Developer #16 changes installation and permissions. Developer #17 changes canonical PROSE; catalogue/dependencies/mirrors/sessions concepts; across-catalogues/Dashboard/connected-items/Mirror/operate journeys; incremental-build and materialisation guidance; Lakehouse runtime; AI/Execute/Initialise/Health/Load/Power BI/Test/Assumption references; release summary and legacy JSON routes; route inventory and validators; and its acceptance evidence. Complete exact paths are reproducible with `git diff --name-only 3239dd004c52327c1319a0275c49ae6bacc9336c..121ce2f8164614544ecd25afefe5f23a82545fbd`.

Final commands (product interpreter: `~/dev/weaverstack/.venv/bin/python`):

```bash
python -m pytest -q tests/test_features_story_invariant.py tests/test_performance_guide_weaver_links_invariant.py tests/test_website_routing_invariant.py tests/test_test_architecture_invariant.py
# 12 passed
python -m pytest tools/test_check_product_site.py -q
# 12 passed
python tools/check_product_site.py --developer-site ~/dev/weaverstack-docs-editorial17/site
# pass, also from the detached combined article/product tree
```

Developer full bundle: `run_validation.py` and `validation.json` in its acceptance directory contain all 20 exact commands/stdout/return codes; parent rerun returned 20/20. The report there lists the eight frozen-runtime pytest modules; parent rerun returned 296 passed. Product/article snippets were checked with `build_parser().parse_args`, never handler dispatch.

Final rendered article results at 390px: page width 390px, table 640px inside its 356px labelled, focusable scrolling region. Desktop results use sensible Question/Answer proportions; the inherited numeric no-wrap rule no longer makes the question consume half the table. Features Dashboard illustrations and Workspaces/Items captions were inspected. Full keyboard/clipboard/console exhaustiveness is not claimed.

Review preview: a private local preview served only the integrated product `docs/`.
