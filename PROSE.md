# Weaver prose

Read this guide before changing product pages, documentation, CLI text, docstrings
or source comments. It governs wording, not product behaviour.

## Public pages and explanatory guides

**Confident explanation.** Lead with the task, capability or result. State what the
reader provides and what Weaver does. Define meaningful scope once. Prefer a
supported action or requirement to a sentence about what Weaver does not do.
Keep clear warnings for destructive actions and real security or compatibility
limits. Put detailed semantics in Reference and review provenance in maintainer
evidence.

**Persuasion through substance.** Product pages and organisational articles should
explain why the capabilities matter. Concrete benefits, examples and considered
recommendations are welcome. Support claims with the mechanism or evidence;
avoid slogans and unsupported superlatives.

**Enough explanation to teach.** Optimise for reader understanding and successful
action, not maximum information density or minimum word count. Use named actors,
reasons and examples where they help. Preserve concise passages that already work.

### Three related voices

- Product pages explain what a team can do, why it helps and where to start.
- Guides walk a reader through a recognisable task, its decisions and consequences.
- Reference specifies exact inputs, defaults, state changes and failure rules.

Begin with a failed load, shared table, development change or release decision
before introducing storage, bindings and identity. Explain one relationship at a
time with ordinary verbs. A senior engineering voice is approachable and precise.
Vary sentence length naturally; adding pronouns or making every sentence short
is not a substitute for an explanation.

Keep useful benefits such as “without copying data” or “no separate monitoring
service”. Give selection rules as controls: what the reader includes and what
runs. Give prerequisites as the setup needed for the action. Keep genuine data
loss, partial-state, security and compatibility consequences explicit beside the
relevant command. Link exact contracts rather than repeating them across cards.

Write release pages for the release being shipped. Keep draft status, review
history, test oracles, package-publication sequencing and planned coverage in
maintainer evidence. Public examples state their project, files and active
configuration, and give the reader a useful result and next step.

### Product website

Preserve **Making Fabric easier to use** and the closing line **Making Fabric
easier to use, and safer to scale.** The Story page keeps its personal history
and voice. Other headings name a task, capability or result.

Lead with Microsoft Fabric. Present items in this order: Lakehouse, Warehouse,
semantic models, Reports. Use Fabric before Power BI when naming platforms.
Explain standalone Power BI deployment where it helps a reader choose a setup.

Use familiar Python, SQL and native Power BI work to introduce the project.
Explain the engineering Weaver handles around it, then the next useful capability.
Keep precise API contracts in Reference rather than making them an admission
requirement for understanding the product.

### Evidence-led articles and examples

Use measured results to explain what people learned and accomplished. State the
workload, participating scope and measurement boundary once where they matter.
Keep source runs, revisions, hashes and reductions in the acceptance record.
Round results without changing the measured claim. Preserve historical captures
and use generators to update derived interfaces and illustrations.

Separate observed results from organisational implications. Projects representing
teams demonstrate an architecture; customer adoption and first-person experience
need their own evidence. Keep the central team's coordination and business teams'
ownership visible in the argument. Retain meaningful engineering detail and
useful benefits rather than adding a disclaimer after each result.

For graphs that can contain cycles, use “dependency graph”; an acyclic execution
plan is a separate concept. Explain the useful execution rule on product pages
and link the exact algorithm and Health behaviour in Reference.

Make passing validation the ordinary path through examples. Deliberate failures,
diagnostic selectors and restoration exercises belong in clearly optional
exploration, with the recovery actions and consequences preserved.

## Source comments and docstrings

Preserve non-obvious engineering information: invariants, platform constraints,
ordering requirements, failure boundaries and reasons the code cannot express.
Describe current behaviour. Leave old bugs and abandoned designs in history
unless compatibility or migration depends on them.

State the shortest direct explanation that preserves the engineering fact.
Delete comments that narrate obvious code. Document parameters and return values
when their meaning needs more than the signature and types. Source-comment
brevity is not the writing model for a product page or teaching guide.

Public behaviour belongs in `docs.weaverstack.dev`; implementation invariants
belong in source, tests or `AGENTS.md`.

## CLI help, errors, warnings and reports

Say what the command or option does. Name its input, target or effect when that
changes how it is used. For a result or error:

1. State the condition in the user's vocabulary.
2. Name the affected thing.
3. Give the next action when Weaver knows it.

Keep the information needed to act. An error is not an architecture lecture;
Registry rows, planner structures, bindings and transports belong there when the
user must interact with them to resolve it. Name catalogue tables when actionable;
otherwise describe the Warehouse or catalogue condition directly.

Do not justify behaviour against imaginary alternatives. Preserve actual
ordering, partial-state and destructive consequences. A report summarises the
result and useful evidence rather than reproducing an unrelated log.

## Review

For public pages, ask whether a reader can understand the capability, provide the
needed inputs and take the next useful step. Check the whole explanation, not
just its shortest sentences. Keep warnings and exact rules at their useful owner.

For source comments and diagnostics, ask which non-obvious fact or next action
the text carries, whether it belongs there and how directly it can be expressed.
