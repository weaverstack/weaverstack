# Weaver public-journey voice audit

## Decision

The current drafts are more accurate and less defensive, but the editorial correction is incomplete. Several pages still explain Weaver's categories and mechanisms from outside the reader's work. Removing caveats did not supply a sustained point of view, a useful recommendation or a teaching sequence.

This is not a request to replace every “Weaver” with “you”. Helpful practitioner prose connects a recognisable situation to an action, explains what the tool contributes, and helps the reader interpret the result. Product pages should make a case for adoption; guides should teach; reference should preserve precise contracts.

## Baseline and method

- Product PR #275: `ea4c9ebbbbe9400be9ed23391720caceb34c797d`.
- Workspace article PR #273: `c5483f5ae47394703bf77cf0e8b404b9207c7c96`.
- Developer docs PR #17: `36ad90f4dcb677d8c04285916af3ab86268b9cdf`.
- The product baseline was read from committed HEAD. Two subsequent, uncommitted local edits to How it works and Weaver vs dbt are not counted as delivered improvements.
- Assessment: source-reading editorial audit of the main public journey. Not a new runtime, link, visual or accessibility validation; not an audit of every reference page or embedded Dashboard asset.
- Locations below refer to these baseline files. Short rewrites illustrate an editorial direction, not approved final copy or changed technical contracts.

## Findings: product site

### P1 — Features needs a new structure, not another adjective pass

**High priority.** `docs/features/index.html`, Operational visibility, lines 215–238; Advanced/multi-workspace section, lines 239–275; Scale, lines 278–290.

Operational visibility combines investigation with recovery, stale reruns, selection, ad-hoc execution and concurrency controls. These are different reader jobs. The next section combines environments, cross-team execution, cycles, deployment previews, bundles, readiness and data protection. The final Scale section repeats concurrency and incremental processing. The navigation calls the middle section “Advanced”, which gives the reader no reason to go there.

This is a structural cause of the generic voice: the page has become a collection of technically defensible cards, rather than an explanation of why a team would choose Weaver.

**Direction:** Separate seeing state from running work. Bring coordination across teams into the scale argument, alongside engine readiness and concurrency. Introduce environments and Mirror as a development/change-management story. Do not simply rename the miscellaneous “Advanced” bucket “Scale”.

A possible ownership map, to settle before writing:

1. Work in familiar Python, SQL and native Power BI files.
2. Build and run connected data work.
3. Apply standards and tests to native Power BI.
4. Investigate what ran and what needs attention.
5. Develop and review changes against existing data.
6. Coordinate work as projects, teams and estates grow.

The coordination section should explain both situations: catching up your own team's work using upstream context, and deliberately running selected work across teams. Measured scale then supplies evidence for that story.

### P2 — Several cards expose an API or implementation detail without earning the reader's attention

**High priority.** Features, lines 89, 227, 236 and 268.

> “Use `with weaver.workflow():` to share a Session and configuration across Python operations.”

The card assumes the reader already cares about Session reuse and record correlation. It does not explain a valuable task. Remove this card as requested; retain the API in developer documentation where a notebook task needs it.

> “Deployed with one command”

Dashboard deployment is useful setup, not a separate reason to adopt the product. Put the command beside the Dashboard demonstration or guide link.

> “Control how much runs at once”

> “Wait for new data to be ready”

These labels could describe almost any orchestrator. The distinctive mechanism is cross-engine coordination: a Warehouse reader waits for the Lakehouse SQL endpoint it needs, while unrelated work can continue. Explain that relationship in one coherent passage rather than splitting it into vague cards.

**Illustrative direction:** “When your Warehouse reads a newly loaded Lakehouse table, Weaver waits for the SQL endpoint refresh before running that reader. Independent branches can run at the same time, within the limits you choose.” Preserve the specific publication/refresh distinctions in the owning reference.

Not every true implementation fact needs its own feature card.

### P3 — The workspace article is still largely an external report about a system

**High priority.** `docs/guides/organising-microsoft-fabric-workspaces/index.html`, lead and sections 1–7, especially lines 116, 136, 152–163, 205 and 227–233.

> “Teams can own separate Fabric projects and still coordinate the work between them.”

> “An enterprise needs the advantages of both.”

> “Each object must also record its operational state…”

> “The experiment demonstrates how a central team and business teams can operate…”

These statements are defensible, but the article repeatedly retreats to institutional subjects, object requirements and reported implications. The short Finance scene is not sustained through the argument. A named team appears, disappears into architecture and then reappears as a result-table role.

**Illustrative opening direction:** “If you run Finance's Warehouse, a failed central customer table becomes your problem too. You need to know which of your tables it has held up and what to reload after the central team repairs it. You should be able to do that while keeping your own project and schedule.”

Carry that team through the dependency explanation and recovery results. Make the writer's judgement visible through clear recommendations and interpretations, not fabricated first-person experience. Keep the experimental status explicit; simulated teams are not customer testimony.

The article should argue for independent ownership with coordinated operation. It should not alternate between an architecture specification, a tutorial and a lab report.

### P4 — The article's CLI section interrupts the argument to teach selection rules

**High priority.** Workspace article, “5.1 The Weaver CLI”, lines 181–195.

> “Use `--catalogue` to choose the records Weaver reads. For Load and Test, use item or workspace selectors to choose the work it runs. With no item selector…”

The reader has reached the product demonstration and is asked to learn defaults, interpret repeated physical names and then absorb permissions. That is the wrong burden for this point in a persuasive article.

**Direction:** Introduce the organisational result first: Team 05 can use the central catalogues to understand its dependencies while reloading only its own work. Show one compact, technically valid demonstration. Explain the consequence in plain language. Link the exact invocation, setup, selection/default rules and permissions to the across-catalogue guide. Do not shorten a command by silently deleting inputs it actually needs.

Keep historical command captures and measured evidence intact. An authored demonstration can be simplified without altering its source evidence.

### P5 — How it works names operations but does not explain the useful abstraction

**High priority.** `docs/how-it-works/index.html`, “The catalogue”, lines 175–200; “From source files to running work”, lines 203–213; “One set of commands”, lines 216–228.

> “BUILD — Install the definitions.”

> “The same recorded state is used by Build, Load, Test and Health.”

The page assumes the command names and catalogue explain themselves. Its capability list partly repeats Features. It does not sufficiently teach that the reader can use the same lifecycle across different Fabric engines, while Weaver handles the relevant deployment and execution paths.

**Direction:** Follow an actual query/table/model relationship. Explain what the reader writes, what Build installs, what Load runs, what Test checks and how Health helps interpret the result. Use title case, not shouting capitals. Add a short CLI demonstration, not another miniature setup guide. Preserve the separate model/Report Build boundary and Reports' deployment-only lifecycle.

The uncommitted local revision improves the point of view but now contains a long command block and dense prerequisites. It still needs editorial restraint before delivery. More explanation is not automatically better explanation.

### P6 — The dbt comparison begins with the reader, then mostly becomes a capability inventory

**Medium priority.** `docs/vs-dbt/index.html`, introduction, six capability cards, command section and Dashboard comparison, especially lines 60, 67–117 and 142.

> “You already know the appeal of defining data models in code.”

This is a sound opening. Some existing cards also work well: ordinary SQL, separate Build/Load and development with existing data. The weakness is the overall progression: the reader receives a tour of Weaver before a recommendation about when the additional scope matters.

**Direction:** Help a dbt practitioner assess their situation. If their work is primarily relational transformation, say what the comparison is for; if Python ingestion, Lakehouse/Warehouse dependencies and native Power BI are part of their job, show the connected workflow they can manage. Follow that with the evidence and precise comparison matrix. Preserve the matrix, external sources and authored migration brief rather than making the reference cells conversational.

Do not turn fairness into a defensive apology for having a product proposition. Explain the relevant difference and let the reader choose.

### P7 — The homepage is stronger than Features, but its personas underrepresent the proposition

**Medium priority.** `docs/index.html`, lines 145–157 and 260–291.

> “Keep writing Python, SQL and Power BI. Weaver loads data, runs tests, deploys changes and keeps everything in the right order.”

This is a good division of responsibility. The closing section also makes a concrete proposition. Preserve those strengths.

The persona cards then narrow the developer to “my five tables”, the lead to consistency, and the architect to something they can “confidently recommend”. They give little space to semantic-model/Report authors, independent team ownership or cross-team coordination. The project introduction also uses “DAG” without helping a new reader understand why the connection matters.

**Direction:** Keep three decision-making perspectives rather than adding job titles: building the work, leading a reliable team, choosing an approach across an estate. Broaden what those people do and explain the connections in ordinary language. The full mission line belongs near the main proposition if that change is approved; it should not have to wait until the closing section.

## Findings: developer teaching journey

### D1 — The development loop never supplies the actual change

**High priority.** `docs/estate/development-cycle.md`, lines 9–15 and 33–37.

> “Edit a Landing declaration while leaving its logical names and Operations connection intact.”

The reader must invent a change and predict its effects before learning the iteration loop. The explanation then moves quickly into reconciled state, descendants and stale selection.

**Direction:** Choose one small, technically verified change to the existing project. State the intended result, preview it, apply it, run the affected work and interpret what changed. Keep wider variants and exact operation semantics available after that successful path.

A command loop without a concrete input and observable result is a reference sequence, not a complete tutorial.

### D2 — Operate tells the reader to decide without teaching the decision

**High priority.** `docs/estate/operate.md`, lines 13–17 and 45.

> “Use the findings to decide whether the estate needs data work, validation or Build recovery.”

This states the assignment rather than helping with it. The validation paragraph then combines rule authorship, language coverage, result interpretation and source/file mode.

**Illustrative direction:** “Read the finding before choosing a command. If source data was loaded after its validation last passed, rerun the validation. If a load is pending or stale, use the catch-up Load below. If you changed a project definition, Check and Build it first.” Keep other failure/recovery cases in their proper task.

The existing completed-work/failure consequence at line 37 is useful and should remain.

### D3 — Across-catalogue teaching puts the broader operation before the likely own-team task

**Medium priority.** `docs/estate/across-catalogues.md`, lines 69–104.

The first Load example selects both teams' workspaces. The own-team catch-up example comes later, after selection rules and runtime requirements.

**Direction:** Start with the team catching up its own work using the upstream team's catalogue as context. Explain why that catalogue is included and what will run. Then show the deliberate coordinated variation that selects both teams. Preserve exact selector forms and failure rules in reference.

### D4 — Mirror's benefit becomes a state-transition explanation and an optional detour

**Medium priority.** `docs/estate/mirror.md`, lines 140–157.

> “A changed selected object, or an affected selected descendant, becomes local after successful installation.”

The first concrete change then depends on an object introduced by an optional exercise elsewhere. A reader following the main path cannot directly demonstrate the promised benefit.

**Direction:** Use an object already required by this Mirror task. Show the local change and the unchanged borrowed data side by side. Explain the state transition after that result. Retain the reset warning, supported materialisation limits and borrowed-state runtime workaround; these are not removable tone defects.

### D5 — Dashboard teaching repeatedly becomes UI description

**Medium priority.** `docs/estate/catalogue-dashboard.md`, “Workspaces”, lines 204–208.

> “The workspaces and items the catalogues describe, drawn as a network of what each supplies to and receives from the others.”

The detail is useful lookup material, but it does not carry forward the opening investigation.

**Direction:** Lead with a question: which items depend on Operations? Show where to select Operations, follow a connected item and inspect the results. Keep symbol keys, filters and refresh behaviour as reference, and preserve the distinction between last-run state and a Health assessment.

### D6 — First-success tasks could explain why the validations matter

**Medium priority.** `docs/lakehouse/python.md`, “Check, build and load”, around line 322; `docs/warehouse/first-project.md`, around line 305.

> “Run the two generated validations, then read Health…”

The examples provide actual outcomes, but the instruction makes validation sound like another required command. Briefly name the business question each rule answers before asking the reader to run it. The complete authored Test forms can remain in the linked testing task.

### D7 — Execute is outside the copyable AI-agent brief

**Direct requested omission; not primarily a voice defect.** `docs/reference/ai-agents.md`, lines 15, 34 and 46–59.

Execute is introduced in the guide, but absent from the fenced standing-instructions template. Copying the template therefore loses the investigative step Matthias requested.

**Direction:** Include Execute in the actual copyable instructions: select the intended development item, pass the development configuration and supported machine-output flags, begin with a read-only query, and require approval for SQL/Python mutations. Do not invent an Execute read-only or dry-run flag. Keep production permissions and unknown-outcome handling explicit without turning the template into a second reference manual.

## What already works

- Product homepage opening: clear division between the reader's familiar work and the engineering Weaver handles.
- Product Get started: concrete installation and starting choices; “Design Reports in your usual Power BI tools, then use Weaver to deploy their definitions” explains responsibility directly.
- Developer `estate/connected-items.md`, line 238: “Tests are Amber even though their previous runs succeeded: the source data was loaded after those runs.” It interprets an actual finding, then gives the next action.
- Developer Mirror, line 25: “Compare the plan with the names above; answer `y` only if they match. Declining changes nothing.” It names the reader's decision and consequence at the point of risk.
- Warehouse first-success query and native-model before/after comparison provide observable results. Preserve them.

## Why the previous pass was insufficient

The prose policy already asks for actors, reasons, tasks and consequences. The implementation removed much of the negative framing but retained the underlying feature inventory and architecture-first sequence. Technical coverage was treated as editorial completion. More cards and explicit contracts accumulated, while the reader's purpose became less continuous.

Passing parser, route, preservation and runtime checks establishes valuable technical properties. It does not establish a helpful voice or a persuasive page. Another banned-word list or pronoun pass would repeat the mistake.

## Revision and acceptance direction

1. Settle Features' section ownership first. Delete or absorb weak cards rather than promoting every implementation detail into a feature.
2. Rebuild the workspace article around the teams' decisions and the demonstrated recovery. Restore the CLI's role as a short demonstration.
3. Teach one lifecycle across engines in How it works; use the dbt comparison to help the reader make a choice.
4. Repair the developer teaching transitions: a real change, interpretation of findings, own-team scope before broader coordination, a runnable Mirror example and meaningful validations.
5. Add Execute to the copyable agent instructions.
6. Read the complete page without the review brief. For each section ask: what does this reader need now; who acts; what should they do or understand; why does it matter; what result supports that explanation?
7. Verify technical contracts and rendered journeys after the editorial structure works. Do not use test success as a substitute for that reading.

## Coverage inventory

Product pages read at committed baseline:

- `docs/index.html`
- `docs/features/index.html`
- `docs/how-it-works/index.html`
- `docs/vs-dbt/index.html`
- `docs/get-started/index.html`
- `docs/guides/organising-microsoft-fabric-workspaces/index.html` (article-owning worktree)

Developer pages read in full:

- `docs/index.md`
- `docs/getting-started/index.md`
- `docs/getting-started/installation.md`
- `docs/lakehouse/python.md`
- `docs/warehouse/first-project.md`
- `docs/semantic-models/native-tmdl.md`
- `docs/estate/index.md`
- `docs/estate/connected-items.md`
- `docs/estate/development-cycle.md`
- `docs/estate/operate.md`
- `docs/estate/across-catalogues.md`
- `docs/estate/mirror.md`
- `docs/estate/catalogue-dashboard.md`
- `docs/reference/ai-agents.md`
- `docs/reference/cli/execute.md`

Reference schemas and generated syntax were read for context, not judged as though they should be conversational tutorials. The Story page, embedded Dashboard pages and the remaining deep-reference/advanced tasks were not included. No public-copy edit or new push was made as part of this audit. The two local How it works/comparison edits remain uncommitted for reassessment.
