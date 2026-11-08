# Weaver 0.11 confidence editorial revision

## Scope and starting point

Targeted continuation of the existing drafts, not a new PR layer. The confidence brief supersedes the earlier proposed public wording; runtime and platform requirements remain in force.

| Draft | Refreshed starting head | Existing base |
|---|---|---|
| product #273 | fcd0172adea3d56a96aeb4594df9a6642106a6b8 | main |
| product #274 | 485f4a89e3c6936f72b34274720b89f09600b342 | main |
| product #275 | c4fd67ef9f6deacf6ca9c5b94ccc80f9433e30de | docs/site-tone |
| developer #16 | 7bc1ccb04397458961f12ba10ed1cee4167b9fbf | main |
| developer #17 | 83e3252c5371175e33f9862980747ad22ba297a4 | docs/permissions |

The refreshed #17 was **MERGEABLE**, so the audit's earlier non-mergeable state needed no conflict repair. Existing unrelated `.claude/launch.json` work in the runtime checkout was preserved. Product #274 remains the untouched tone foundation; current product edits belong to #275. Article work belongs to #273. Permissions belong to #16 and guide/reference work to #17.

Runtime evidence remains `efc046e7cf066daefd27f9268413ae05c3ed64e4`; release baseline remains `13a6fb359164d64b18da87f14c213c7064261a40`. No runtime, CI, package configuration, VERSION, historical capture or live Fabric resource changes.

## Main editorial decisions

| Before | After / disposition |
|---|---|
| “An experiment ... explores how separate projects can participate” | Lead states what teams accomplished; Finance example follows the new ownership/dependency heading. |
| “not a count of every business or end-user impact” | Names the 77 managed tables/models and explains what the central and downstream teams could identify from the common cause. |
| “leaving business teams' loads unselected” | Central team reloads its six objects; business teams retain control of their reload timing. |
| “not a performance guarantee” | One measurement note states small tables, FTL64 and the end-to-end timing boundary. |
| Incorrect Fabric-ID join assertion | Source-to-installation matching, verified against the name/type/workspace index and object resolution in `src/weaver/catalogues.py:237–246,287–316`. |
| Execute card begins with bookkeeping exclusions | Command/file, engines and investigation result lead; submitted SQL/Python mutation remains explicit. Bookkeeping stays in CLI Execute reference. |
| Dense Report/Mirror/Wipe exception paragraph | Build deploys Reports; Load refreshes their models. Wipe's unmanaged-content consequence stays visible at Wipe with its exact reference link. |
| Two standalone-Power-BI exceptions | One useful starting paragraph: native project, modelling rules, DAX validation, requirements, next task. |
| Product policy applies comment-level terseness to public pages | Separate source-comment/diagnostic rules from confident explanation, evidence-led persuasion and enough teaching context. |

The article retains the central-team/business-team conclusion, the complete Team05 commands and meaningful benefits such as avoiding a second dependency map. Its byline remains organisational; the incident is described as “The experiment”, not invented first-person experience.

## Target dispositions and adjacent sweep

`product-dispositions.json` records every A01–A12 and P01–P08 decision with owning paths. The companion developer `acceptance/docs-0.11-confidence/dispositions.json` records D01–D12. Both files were read together and their IDs checked programmatically: **exactly 32 unique expected targets**, with none missing or duplicated.

| Developer target | Disposition |
|---|---|
| D01 | Changed: affirmative Dashboard lifecycle; exact independence remains in CLI reference. |
| D02 | Moved: speculative Fabric Apps roadmap removed; existing best-effort status retained in named support/compatibility reference. Available history did not establish formal support terms; clarification stays in maintainer backlog. |
| D03 | Changed: update source projects, check schema and identify remedies before applying deployment changes; existing permission requirements retained. |
| D04 | Changed: Build → Load → Test → Health and authored validations; installed-source reminder at Load. Separate source/model Build calls preserved. |
| D05 | Changed: completed changes remain; inspect partial failures, correct cause and recover. |
| D06 | Changed: catalogue context and selected execution taught directly; default scope and exact selectors retained. |
| D07 | Changed: AI opening and feature entries lead with useful development actions. |
| D08 | Changed: scoped Health acceptance, findings/completeness report and declared data/business rules. |
| D09 | Changed: consolidated identity permissions, development configuration and approval policy. Mirror reset, source-reading identity and production prohibition preserved. |
| D10 | Changed: command-specific flags and JSON opening simplified; exact commands, streams, fields, versions and compatibility contracts retained. |
| D11 | Changed in #16, ordinarily merged into #17: usable-role introduction; duplicate ownership rebuttal removed, verified matrix retained. |
| D12 | Changed: actionable own-mirror-configuration workaround under a clear limitation heading; T05 remains open and incomplete joined scope explicit. |

Adjacent product sweep: Home and comparison paragraph/caption copy retained for concrete benefits, fair adapter/workflow scope and migration approval/validation consequences. Matching paragraphs in the performance and dbt guides were inspected; real measurement boundaries, one-bookmark-per-consumer semantics, platform scope and retained evidence were kept rather than changing every negative construction. This is not a claim that every page on both sites received a fresh audit.

Additional small edits: Get started now directs Report design to the reader's usual Power BI tools and deployment to Weaver; How it works says “Validate stored data and model calculations.” Approved mission/closing line, Story history, layout, URLs, visual examples and historical assets remain unchanged.

## Preserved precision and evidence

- Catalogue options provide context; selectors choose execution; working-catalogue default retained beside commands. Results stay in owner catalogues with workflow correlation.
- Cycles run once in consistent order and may use earlier results; exact Health timestamp rules remain in the linked technical reference.
- Mirror's cross-workspace Lakehouse/same-workspace Warehouse scope stays beside its example; reset, retained/live rows and remote ownership remain in reference.
- Wipe explicitly includes unmanaged contents. SQL/Python execution may mutate data. Permissions remain the actual security control.
- Timing table keeps 82s impact, 11s Team05 impact, 138s central repair, separate 5s check/15s reload, 256s wider recovery and 315s coordinated run. Later green confirmation is not counted in the 15s reload cell.
- All 50 catalogues are labelled participating context; no assertion of 50 load-bearing execution owners. Wider run remains 71 loads plus 41 readiness steps over 43 combined owner workspaces; the earlier evidence ledger preserves the 42 object-owner distinction.
- `spread-evidence.json`, raw-record reductions/hashes, benchmark captures, Dashboard snapshots and since-0.10 coverage ledger were preserved. No rerun or reinterpretation of the experiment.
- T05 remains a confirmed runtime issue, separate from this editorial sign-off.

## Checks run in this pass

Product interpreter: `~/dev/weaverstack/.venv/bin/python`.

```bash
python tools/check_product_site.py
python -m pytest -q tests/test_features_story_invariant.py tests/test_performance_guide_weaver_links_invariant.py tests/test_website_routing_invariant.py tests/test_test_architecture_invariant.py
python -m pytest tools/test_check_product_site.py -q
```

Product checker passed separately on article and site, and on the detached combined tree. Focused product invariants: **12 passed**. Checker regressions: **12 passed**. Product/article CLI blocks parsed with the existing local non-dispatching checker; no handlers executed.

From the frozen runtime, with `PYTHONPATH="$PWD/src"`:

```bash
.venv/bin/python -m pytest -q tests/targeted/test_joined_health_representation.py tests/targeted/test_joined_run_representation.py
```

**51 passed**. Source inspection separately verified the catalogue join key and Build's configuration-derived item bindings; these are not claims of live execution. `git diff --check` passed. Git comparisons confirmed unchanged experiment evidence, claims ledger and visual asset bytes.

Rendered parent review: article read continuously at 1280px; How it works lifecycle/Wipe and Features Execute at 1280px; article recovery/cycle and Get started Power BI entry at 390px; developer AI workflow at 1280px and Health workaround at 390px. Mobile page width 390px, result table 640px within a 356px scrolling region. No page-level overflow in these cases. Developer worker additionally recorded nine routes at desktop/mobile widths, with no document overflow or broken images. This is targeted review, not exhaustive keyboard/clipboard/console testing.

## Developer checks and combined delivery

Developer worker ran the existing bundle in this pass: **20/20 checks passed**, including strict MkDocs, four reference generators, Dashboard demo, estate/reference/refresh/journey examples, route/generator regressions, non-dispatching CLI parsing and the offline T05 probe. Exact commands/stdout/return codes are in developer `acceptance/docs-0.11-confidence/validation.json`; its initial incorrect Execute link and corrected rerun are both retained. The parent read and counted these results, inspected the diffs and performed the combined product-to-built-docs check. An extra full parent-bundle rerun did not receive tool consent before timeout and executed no commands; it is not counted as another successful run.

The current-pass parser checked **81 complete commands on 14 pages**, without handlers. The rendered developer crawl checked **5,184 links**, 114 original pages and 872 fragments with no errors. Preservation evidence confirms exact shell blocks, historical captures and generated sections across all 12 changed developer public pages. The parent used the correct established product checker interface (`--developer-site` from the integration checkout); an initial unsupported `--root` invocation was rejected before checking, then corrected.

Additional developer consistency work scopes physical address inference to Build, while joined Health/Load/Test can connect physical Shortcuts through supplied catalogues. Nearby environment/development/Mirror/index copy received bounded edits. Recovery, catalogue concepts, developer home and relevant exact CLI contracts were deliberately retained. The developer canonical PROSE now agrees with the product policy's confident explanation, substantive persuasion and teaching priorities.

Final reviewed content heads:

| Existing draft | Content head |
|---|---|
| product #273 | `c5483f5a` |
| product #274 | `485f4a89e3c6936f72b34274720b89f09600b342` (unchanged) |
| product #275 | `765ff116` plus this report/disposition-only commit |
| developer #16 | `7442917e4dc24f580364727b219a4c9de49064af` |
| developer #17 | `642a45a6609dc135cfce4b71714fa421b4a38839` |

Exact final PR heads and retained bases/draft status are read back after pushing. The report-only commit's own hash is supplied in the final delivery link. Both review previews serve these integrated sources/builds; no remote integration branch or new PR was created.

## Publication boundary

All PRs stay drafts with their existing bases. Later authorised publication must make developer destinations available before product links become public and coordinate installation copy with the available package. Those sequencing checks belong here, not as warnings on release pages. No merge, release, site publication or production execution is authorised by this revision.
