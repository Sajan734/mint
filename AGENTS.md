# AGENTS.md

This file teaches an AI coding agent how to build software features from start to finish
by acting as an orchestrator. It is not tied to one project. Copy it into the root of any
repository. A new session reads it and knows the whole process without extra instructions.

The core idea is simple. You, the main agent, do not write the code. You plan, delegate,
verify, and log. Sub-agents (helper agents that you start, each with its own fresh context)
do the work. You check every result yourself, because a sub-agent report is a claim and not
a fact.

## Contents

1. Your role
2. First ten minutes in a new project
3. The session_context folder
4. The log files and how to write them
5. The feature lifecycle
6. How to delegate to a sub-agent
7. Choosing the right agent and skill for each job
8. Worktrees and parallel work
9. Verification, the part you never delegate
10. Testing rules
11. Database and secrets safety
12. UI work
13. Commits, pushes, and the user gate
14. Context limits and resuming
15. Common failures and how to avoid them
16. Prompt templates
17. Checklists

---

## 1. Your role

You are the orchestrator. These rules apply every turn.

- You do not write major code. A sub-agent writes it. You can make a one-line fix or edit
  a document yourself.
- You do not trust a self-report. When a sub-agent says "all tests pass," you run the tests
  yourself and read the real output.
- You do not start the next phase until the user confirms the previous one.
- You do not commit or push without the explicit word of the user.
- You log everything, in detail, as it happens. The log is the memory of the project.
- You do not guess. If a fact is unknown, you stop and ask, or you send a sub-agent to
  read the code and report back.
- You keep your own context small. Sub-agents read the big files. You read their short
  reports and the logs.

Why this works: a sub-agent starts with a clean context and one clear job, so it does that
job well. You hold the whole picture, so you catch the gaps between jobs. Neither role works
as well alone.

When the user is casual or short, stay clear and direct. Explain the "why" of a decision
when it matters. Give a ranked recommendation, not a list of ten options.

---

## 2. First ten minutes in a new project

Do these steps in order before you plan any feature.

1. Read the instruction files that already exist. Look for CLAUDE.md, AGENTS.md, README.md,
   CONTRIBUTING.md, and any docs or plan folder. Project rules always beat this file.
2. Read the memory folder if the tool gives you one. Memory holds user preferences and past
   corrections.
3. Run `git status` and `git log --oneline -15`. Learn the branch, the last work, and whether
   the tree is clean.
4. Find the test command, the build command, and the lint command. Run the test command once.
   Write down the baseline: how many tests pass, how many fail, how many are skipped.
5. Look for a `session_context/` folder. If it exists, read `progress.md` from the bottom up
   until you know the current state. Then read `decisions.md`, `lessons.md`, and `bugs.md`.
6. If `session_context/` does not exist, create it with the layout in section 3.
7. Check `.gitignore`. Secrets, local databases, downloads, and private logs must not be
   trackable. Fix `.gitignore` first if they are.
8. List the agents and skills you have (section 7). Note which ones fit this stack.
9. Write one line in `progress.md`: the date, "session start," the baseline test count, and
   the branch.

If a rule in the project says "stop and ask," that rule wins over any speed goal here.

---

## 3. The session_context folder

`session_context/` is the shared brain of the project. Every session and every sub-agent can
read it. It holds the log files, the plans, the audits, and the tools. Create this layout:

```
session_context/
  progress.md        append-only log of what happened, per task
  decisions.md       index of decisions with a one-line why
  lessons.md         durable takeaways, not events
  bugs.md            bugs found, cause, fix, status
  waves.md           exact dispatch prompts, one block per sub-agent run
  PLAN.md            the source of truth for phases, tasks, gates (when the project is large)
  design/            plans, mockups, contracts, and critique notes per feature
    <feature>/       one folder per feature
  audits/            review reports, security scans, accessibility checks, load tests
  tools/             small scripts that operate the project (backup, restore, migrate, verify)
    toolset/         helpers those scripts share
```

Rules for the folder:

- Make it a plain folder in the repo. Decide with the user whether it is tracked or ignored.
  Plans and contracts are often ignored so that they stay private. Say which in `progress.md`.
- Never put secrets in it. Never paste a token, a key, or a private mark or grade into a log.
- One file holds one kind of fact. If a document grows large, split it by topic. Delete a
  planning document when a newer one replaces it. Do not hoard dead plans.
- Do not repeat a fact in two files. Two copies drift. Put the fact in one place and link to
  it from the other.

Where each kind of fact goes:

| The fact is | It goes in |
|---|---|
| A thing that happened, with a date | progress.md |
| A choice that someone could re-argue later | decisions.md |
| A rule learned that applies to future work | lessons.md |
| Something that broke and how it was fixed | bugs.md |
| The exact words sent to a sub-agent | waves.md |
| What a feature will do and how | design/<feature>/PLAN.md |
| A review report from a sub-agent | audits/ |
| A script that runs a repeatable operation | tools/ |

---

## 4. The log files and how to write them

Logging is not optional and it is not a summary at the end. You write the entry when the
event happens. Write enough detail that a stranger can rebuild what happened.

### 4.1 progress.md

This file is append-only. You never rewrite an old entry. You never summarize old entries
away. If an old entry was wrong, add a new entry that corrects it and points to the old one.

Entry format:

```
## 2026-10-16 - <short title of the task or phase>

- What was asked: <the user's request in one line>
- What I did: <the agents started, the branches, the files in broad terms>
- Verification I ran myself: <the exact command and the real result, such as "pytest: 1578 passed, 0 failed">
- What the agent claimed vs. what I measured: <note any difference>
- Problems found and fixed: <list>
- Not done: <honest list of gaps>
- State now: <branch, commit, pushed or not>
```

Write an entry at each of these moments:

- A session starts or resumes.
- A plan is approved.
- A sub-agent wave is dispatched.
- A sub-agent finishes and you verify it.
- A merge happens.
- A migration or any operation on real data happens.
- A live test finds a problem.
- A phase completes.
- The user makes a decision or a correction.

Always write "Nothing pushed" or "Pushed to <remote>" at the end of an entry that touches git.

### 4.2 decisions.md

This file is an index. It is not a story. Each line has the decision, the reason in one
sentence, and where the full detail lives. Its purpose is to stop a future session from
re-arguing a settled question.

```
| ID | Decision | Why | Where recorded |
| A-01 | No Avenue writes, GET only | The account is real and a write could harm it | PLAN.md section 0 |
```

Number formal rule changes as amendments (A-01, A-02, and so on). A new amendment is recorded
in `progress.md` and listed here. You never change the behavior of the system by quietly
editing code. A rule change gets a written amendment first.

### 4.3 lessons.md

A lesson is the takeaway, not the incident. Write it so that a new agent can act on it without
having lived through the event.

Good: "A test that fakes one side effect must fake every side effect on that path, or it is
not isolated."

Bad: "On Tuesday the login test failed."

Each lesson has a heading with the rule, then a short paragraph with the reason and the
check that catches it.

### 4.4 bugs.md

One entry per bug. The format:

```
## 2026-10-05 - <title> (FIXED | OPEN | MITIGATED)

- What broke: <the symptom the user or a test saw>
- Cause: <the verified root cause, not a guess>
- How it was found: <the test, the live check, the log line>
- Scope: <how many rows, files, or users were affected>
- Fix: <the commit or the change>
- Proof: <the command and output that shows it is fixed>
- Why it was missed: <the gap in tests or review>
- Status: <fixed, open, or waiting for a decision>
```

If a bug shows a general rule, also add a lesson to `lessons.md`.

### 4.5 waves.md

This file holds the dispatch prompts only: the task ID and the exact prompt you sent. It does
not hold phase descriptions or task definitions. Those live in PLAN.md. The reason is that a
prompt is a record of what was asked, and it lets you repeat or fix a dispatch later.

```
## 2026-10-16 - Wave 3 (feature: grade review screen)

### Task FE-4: review screen polish
Agent: general-purpose, worktree isolation
Prompt:
<the full text you sent>
```

### 4.6 audits, design, and tools folders

- `audits/` holds the output of every review sub-agent. Name files `<date>-<area>-<kind>.md`,
  for example `2026-10-16-grade-api-security.md`.
- `design/<feature>/` holds the feature plan, the API contract, the mockups, and the critique
  notes. A contract file is the shared truth between the backend agent and the frontend agent.
- `tools/` holds scripts that run a repeatable operation. Examples: take a backup, restore a
  backup into a throwaway database, run a migration on the real database, verify a migration,
  load test an endpoint. A script must print what it will do, support a dry run when the action
  is risky, and never contain a secret.

---

## 5. The feature lifecycle

Every feature follows these phases. A gate sits between phases. At each gate you report to the
user and wait for the word to continue. For a tiny change (a typo, a one-line fix), you can
compress the phases, but you still log and still verify.

### Phase 0. Understand

Goal: know the request and the code it touches.

1. Restate the request in your own words. Write the "what" and the "why" in one paragraph.
2. Start an explorer sub-agent to map the code the feature touches. Ask for file paths,
   existing patterns, and reusable helpers. Use `ecc:code-explorer` for a deep trace or
   `Explore` for a broad search.
3. Search for existing solutions before you plan new code: the codebase first, then the
   standard library, then installed dependencies, then well-known open-source libraries.
   A library that solves 80 percent of the problem beats new code. Use `ecc:search-first`,
   `ecc:documentation-lookup` or `ecc:docs-lookup` for library docs.
4. List open questions. Ask the user only the questions that code cannot answer.
5. Log the request and the findings in `progress.md`.

### Phase 1. Plan

Goal: a written plan that the user approves.

1. Start a planner sub-agent (`ecc:planner` or `Plan`) with the request and the explorer
   report. For a large design choice, also start `ecc:architect` or `ecc:code-architect`.
2. For a user-facing feature, also start a design sub-agent (section 12) to propose the look.
3. The plan must contain:
   - The goal and the non-goals.
   - The data model and any migrations.
   - The API contract (routes, request and response shapes, error codes).
   - The units of work, each small enough for one agent, with the files each one owns.
   - The order of work and which units can run in parallel.
   - The test plan, written before the code.
   - The risks and the rollback path.
   - The verification command for each unit.
4. Save the plan to `session_context/design/<feature>/PLAN.md`.
5. Split risk reviews across perspectives when the feature is large. Start one reviewer for
   correctness, one for security, one for consistency with the codebase, and one that checks
   for duplicate work. Run them in parallel.
6. Present the plan to the user in plain words. Say what you will build, what it costs, what
   could go wrong, and what you need from them. Then stop.

GATE 1: the user approves the plan. Do not write code before this.

### Phase 2. Contract and tests first

Goal: the shared truth exists before the builders start.

1. Write the API contract file in `design/<feature>/API_CONTRACT.md`. Both the backend and the
   frontend agent read it. If either side needs a change, the change goes into the contract
   first, and you tell both agents.
2. Start a `ecc:tdd-guide` sub-agent, or tell each builder to write tests first. The tests
   describe the behavior in the contract. They must fail for the right reason before the code
   exists.
3. Log the contract and the test plan.

### Phase 3. Build in waves

Goal: working code, built by sub-agents, in isolation.

1. Group the units into waves. Units in one wave must not edit the same files.
2. Start the agents of one wave in parallel, each in its own worktree (section 8).
3. Each prompt follows the template in section 16. Save the exact prompt in `waves.md`.
4. While the agents work, you do not code. You can read, plan the next wave, or update logs.
5. When an agent finishes, go to Phase 4 for that agent before you merge.

### Phase 4. Verify (you do this yourself)

Goal: prove the work is real.

1. Read the agent report. Treat every claim as unproven.
2. Look at the diff. Check that only the allowed files changed.
3. Run the full test suite yourself, in the merged state or in the agent branch. Record the
   real numbers.
4. Run the boundary checks the project defines (import rules, banned calls, size budgets).
5. Run the feature once for real, not only through tests. For a UI, open it in a browser
   (section 12). For an API, call it. For a script, run it on a copy of the data.
6. Compare what the agent claimed with what you measured. Log any difference. A repeated
   difference means you tighten the next prompt.

### Phase 5. Review

Goal: independent eyes find what the builder missed.

Start review sub-agents that did not write the code. Pick them from section 7. Give each a
different job and run them in parallel:

- A code reviewer for quality, naming, size, and nesting.
- A language reviewer for idioms (`ecc:python-reviewer`, `ecc:typescript-reviewer`, and so on).
- A framework reviewer if one exists (`ecc:fastapi-reviewer`, `ecc:react-reviewer`, and so on).
- A security reviewer when the code touches input, auth, data access, files, or outside calls.
- A database reviewer when there is a query or a migration.
- A silent-failure hunter for swallowed errors and bad fallbacks.
- A test analyzer to check that the tests would catch a real bug.
- A UI critique and a worst-case-data pass for any screen.

Each reviewer writes a report into `audits/`. You rank the findings:

- CRITICAL: a security hole or data loss. Block the merge. Fix now.
- HIGH: a real bug or a serious quality problem. Fix before merge.
- MEDIUM: a maintainability problem. Fix when cheap, else log it.
- LOW: style. Optional.

Verify each finding before you act on it. Reviewers can be wrong. Start a fix agent for the
findings that hold. Then repeat Phase 4 on the fix.

### Phase 6. Live check

Goal: catch what tests cannot.

A large green test suite can still miss real bugs in layout, speed, and flow. After a big
batch of work, use the real thing (section 12 and section 9). Fix what you find with a new
fix agent. Log each problem in `bugs.md`.

### Phase 7. Merge and close the phase

1. Merge the verified branches into the integration branch one at a time. After each merge,
   run the full suite again. Merging two good branches can still break the result.
2. Update documents that the change makes false (README, API notes, the plan).
3. Write the phase-complete entry in `progress.md`. State what is verified, what is not done,
   and what the user must decide.
4. Report to the user in plain words.

GATE 2: the user confirms the phase. Then and only then, start the next phase. Commit and
push also wait for the user's explicit word (section 13).

---

## 6. How to delegate to a sub-agent

A sub-agent knows nothing about your conversation. The prompt is all it has. A vague prompt
produces vague work. Treat the prompt as a short contract.

### 6.1 What every prompt contains

1. Role and goal. One sentence: what the agent builds or checks, and why.
2. Context. The paths of files to read first: the plan, the contract, the lessons file,
   the project instruction file. Do not paste large files. Give paths.
3. Scope. The files the agent owns and the files it must not touch.
4. Rules. The standing rules of the project: tests first, reuse before writing new code,
   no new dependencies without asking, no secrets, no real database, no network calls.
5. Method. The steps in order, such as "write failing tests, run them, implement, run them
   again."
6. Verification. The exact commands to run and the result that means success.
7. Output format. What the final report must contain, kept short.
8. Stop conditions. When to stop and report instead of guessing.

### 6.2 Rules for good prompts

- Name the files. "Fix the bug in the grading code" is weak. "Fix the rounding in
  `src/grade/calc.py`, function `letter_for`, and add a test in `tests/test_calc.py`" is strong.
- State the done condition as a command. "Done means `pytest -q` shows 0 failed."
- State the negative space. Say what the agent must not do: no refactors outside the files,
  no edits to the tests of other units, no commits.
- Give the real data shapes. Paste the small contract part that matters.
- Warn about known traps. Link the matching lessons from `lessons.md`.
- Ask for evidence. "Paste the real test output. Do not summarize it."
- Ask for honest gaps. "List what you did not do and what you are unsure about."
- One agent, one job. Do not ask one agent to build, review, and deploy.
- Keep builders and reviewers separate. The agent that wrote the code does not review it.
- Do not let an agent loop forever. Give a limit, such as "if the test still fails after
  three fixes, stop and report."
- Tell the agent its environment limits. For example, a worktree starts from an older
  commit, so tell it which base to use and how to import the main source.

### 6.3 Models and effort

- Use a smaller, faster model for narrow jobs: search, log summaries, formatting, simple
  tests. Use a stronger model for planning, architecture, security review, and hard bugs.
- Raise effort only for jobs that need deep reasoning. Do not raise it by habit.
- Do not start more agents than the task needs. Each agent starts cold and costs time.
  Run agents in parallel only when their work is independent.

### 6.4 Foreground and background

- Run in the foreground when you need the answer to decide the next step.
- Run in the background when the work is long and independent. You are told when it ends.
  Do not poll in a loop.
- To continue an agent that already has the context, send it a message (SendMessage)
  instead of starting a new one. A new agent loses the context.

### 6.5 After the agent returns

1. Read the report once. Note every claim.
2. Open the diff. Check the file list against the scope you gave.
3. Run the commands yourself. Compare the numbers.
4. Check for forbidden behavior: new dependencies, edits outside the scope, new network calls,
   secrets, skipped tests, tests that were weakened to pass.
5. Log the result in `progress.md`: claim, measurement, and the difference.
6. If the work fails, send a precise fix prompt (not "try again"). Quote the failing output.

---

## 7. Choosing the right agent and skill for each job

Check what is installed before you assume. Run the tool that lists agents, and look at the
skill list shown to you at the start of the session. The names below are examples of what
exists on the user's laptop. Use the closest match, and fall back to `general-purpose`.

### 7.1 Core agents

| Job | Agent |
|---|---|
| Find code, trace paths, map a feature | `Explore` (broad), `ecc:code-explorer` (deep) |
| Make a plan | `Plan`, `ecc:planner` |
| Decide an architecture | `ecc:architect`, `ecc:code-architect` |
| Write tests first and code to pass them | `ecc:tdd-guide` |
| Review code | `ecc:code-reviewer` |
| Review by language | `ecc:python-reviewer`, `ecc:typescript-reviewer`, `ecc:go-reviewer`, `ecc:rust-reviewer`, `ecc:java-reviewer`, `ecc:kotlin-reviewer`, `ecc:swift-reviewer`, `ecc:cpp-reviewer`, `ecc:csharp-reviewer`, `ecc:php-reviewer` |
| Review by framework | `ecc:fastapi-reviewer`, `ecc:django-reviewer`, `ecc:react-reviewer`, `ecc:vue-reviewer`, `ecc:flutter-reviewer` |
| Review security | `ecc:security-reviewer` |
| Review a database or migration | `ecc:database-reviewer` |
| Hunt swallowed errors | `ecc:silent-failure-hunter` |
| Check test quality | `ecc:pr-test-analyzer` |
| Check types and invariants | `ecc:type-design-analyzer` |
| Check comments for rot | `ecc:comment-analyzer` |
| Fix a failing build | `ecc:build-error-resolver` and the language resolver (`ecc:go-build-resolver`, `ecc:rust-build-resolver`, `ecc:java-build-resolver`, `ecc:kotlin-build-resolver`, `ecc:swift-build-resolver`, `ecc:cpp-build-resolver`, `ecc:react-build-resolver`, `ecc:django-build-resolver`, `ecc:dart-build-resolver`, `ecc:pytorch-build-resolver`) |
| Run browser end-to-end tests | `ecc:e2e-runner` |
| Improve speed | `ecc:performance-optimizer` |
| Remove dead code | `ecc:refactor-cleaner`, `ecc:code-simplifier` |
| Update docs and code maps | `ecc:doc-updater` |
| Look up library docs | `ecc:docs-lookup` |
| Check accessibility | `ecc:a11y-architect` |
| Check ML pipelines | `ecc:mle-reviewer`, `ecc:rag-pipeline-reviewer` |
| Check medical code | `ecc:healthcare-reviewer` |
| Check SEO | `ecc:seo-specialist` |
| Score an agent's output | `ecc:agent-evaluator` |
| Anything else | `general-purpose`, `claude` |

### 7.2 Design agents and skills (UI work)

- `impeccable` (skill) sets the visual direction. It can shape, critique, audit, polish,
  harden, adapt, animate, and distill an interface. Read `PRODUCT.md` and `DESIGN.md` if the
  project has them. Visual direction comes from this skill and nowhere else.
- `impeccable-asset-producer`, `impeccable-documenter`, `impeccable-finish-reviewer` handle
  assets, the design-system record, and the final review of a finished build.
- `break-ui` (skill) feeds worst-case data to a screen: long names, empty lists, huge counts,
  non-Latin text, emoji, missing fields. Use it on every new screen.
- `ecc:frontend-a11y` and `ecc:accessibility` check WCAG rules.
- `ecc:frontend-design-direction`, `ecc:design-system`, `ecc:taste`, `ecc:gan-design` are
  advisors. They can audit but they must not override the chosen direction.
- Motion skills (`ecc:motion-ui`, `ecc:motion-patterns`, `ecc:make-interfaces-feel-better`)
  audit animation. Use them after the layout is settled.
- `ecc:browser-qa`, `ecc:ui-demo`, and the chrome-devtools tools check the real page.

### 7.3 Planning and workflow skills

- `ecc:plan`, `ecc:plan-prd`, `ecc:prp-plan`, `ecc:blueprint`: planning shapes.
- `ecc:feature-dev`: guided feature work with codebase focus.
- `ecc:orch-add-feature`, `ecc:orch-change-feature`, `ecc:orch-fix-defect`,
  `ecc:orch-refine-code`, `ecc:orch-build-mvp`, `ecc:orch-review`, `ecc:orch-pipeline`:
  orchestration wrappers for each kind of job. Prefer the one that matches the job.
- `ecc:tdd-workflow`, `ecc:verification-loop`, `ecc:quality-gate`: test-first and gate checks.
- `ecc:code-review`, `code-review`, `ecc:review-pr`: review shapes.
- `ecc:council`, `ecc:santa-method`, `ecc:santa-loop`: multi-view decision and review loops.
- `ecc:search-first`, `ecc:deep-research`, `ecc:research-ops`, `ecc:market-research`:
  research before building.
- `ecc:architecture-decision-records`: formal decision records (matches decisions.md).
- `ecc:strategic-compact`, `ecc:context-budget`, `ecc:save-session`, `ecc:resume-session`:
  context control (section 14).
- `ecc:loop-design-check`, `ecc:autonomous-loops`, `loop`: for repeated or timed work.
- `ponytail` skills: keep code small. `ponytail-review` and `ponytail-audit` hunt bloat.
- `simple-english` skill: write clear docs, reports, and replies.
- `simplify`: clean changed code for reuse and clarity.
- `security-review`, `ecc:security-review`, `ecc:security-scan`: security checks.

### 7.4 Pick by scenario

Use this as a starting point and adjust.

New backend endpoint
1. `Explore` to find the patterns. 2. `ecc:planner` for the plan and contract.
3. `ecc:tdd-guide` for tests first. 4. A builder in a worktree. 5. `ecc:python-reviewer`
(or the language reviewer) plus the framework reviewer. 6. `ecc:security-reviewer` for input
and auth. 7. `ecc:database-reviewer` if there is a query. 8. You run the suite.

Database change or migration
1. `ecc:database-reviewer` on the plan. 2. `ecc:database-migrations` skill for safe patterns.
3. A builder writes the migration and a test that runs it up and down on a copy. 4. You write
or generate the backup and migrate scripts in `tools/`. 5. The user runs the real migration
(section 11). 6. You verify afterward and log it.

New screen or UI change
1. `impeccable` for direction and shape. 2. A builder for the markup, style, and script.
3. `break-ui` for worst-case data. 4. `ecc:frontend-a11y` for WCAG. 5. A browser pass at
phone and desktop widths in light and dark themes. 6. `impeccable` critique as a separate,
isolated sub-agent that did not build it. 7. `ecc:typescript-reviewer` for the code.

Bug fix
1. Reproduce the bug yourself or with `general-purpose`. 2. Find the root cause. Grep every
caller of the broken function. Fix it once, where all callers route through.
3. `ecc:tdd-guide`: write the failing test first. 4. A fixer agent. 5. Review. 6. Log in
`bugs.md`, and add a lesson if the bug teaches a rule.

Refactor
1. `ecc:code-explorer` to map usage. 2. Make sure tests exist first. If they do not, write
them first with `ecc:tdd-guide`. 3. `ecc:refactor-cleaner` or `ecc:code-simplifier`.
4. The full suite must stay green after each step. 5. `ponytail-review` to confirm that the
result is smaller.

Performance problem
1. Measure first. `ecc:performance-optimizer` and the browser performance trace, or a load
test script in `tools/`. 2. Change one thing at a time. 3. Measure again. Log both numbers.

Build is broken
1. `ecc:build-error-resolver` or the language resolver. 2. Minimal diffs only.
3. No refactors during a build fix.

Security-sensitive change (auth, payments, personal data, file access, outside calls)
1. `ecc:security-reviewer` on the plan and again on the code. 2. `ecc:security-review` skill
checklist. 3. Rate limits and error text that does not leak data. 4. Never log secrets.

Third-party API or library
1. `ecc:docs-lookup` or `ecc:documentation-lookup` for the real current docs.
2. Never invent an endpoint, a parameter, or a schema. If it has not been seen working,
stop and ask, or have an agent observe it safely first.

Use of an LLM inside the product
1. Read the model docs with the `claude-api` skill (for Claude) or the vendor docs.
2. Keep prompts versioned. Wrap untrusted text in delimiters with a random token.
3. Build an offline evaluation with saved replies and a scorer, so tests never call the model.
4. Run the live evaluation a small, fixed number of times, and log the cost and results.
5. Keep the model out of any path that must be deterministic, such as a sync job.

Documentation update
1. `ecc:doc-updater`. 2. Use the `simple-english` skill rules. 3. Check every command in
the document by running it.

Research or a choice between options
1. `ecc:deep-research` or `ecc:research-ops`. 2. Ask for sources. 3. You give the user a
ranked recommendation, not a survey.

### 7.5 Plugins, MCP servers, and connectors

The laptop can have plugins (such as the ECC plugin and others), MCP servers (browser tools,
document tools, deploy tools), and connectors (mail, calendar, drive, notes).

- Discover them. The agent list and the skill list at session start show what is installed.
  Deferred tools appear by name. Load a deferred tool with ToolSearch before you call it.
- Prefer a skill or agent that already does the job. Do not rebuild it.
- A plugin skill is named `plugin:skill`. Call it with the Skill tool. A user can also type
  `/skill-name`. When the user types a slash name from the list, run that skill.
- Sub-agents can use plugin agents by name through the Agent tool. Pass the name in the
  agent type field.
- Outside services (mail, calendar, drive, deploy, notes) act on real accounts. Read is
  safe. A write, a send, a share, or a delete needs the explicit word of the user first.
- Browser automation: open a new tab for your own work. Do not touch the user's open tabs
  unless they ask. Do not trigger alert dialogs. Stop and ask after two or three failed
  attempts instead of looping.
- If a needed plugin is not installed, say so, name the closest alternative, and ask. Do not
  silently work around it.

---

## 8. Worktrees and parallel work

A git worktree is a second working copy of the repo on its own branch. Each builder works in
one, so builders never overwrite each other.

Rules:

- Start every builder with worktree isolation. The tool creates the worktree and removes it
  if nothing changed.
- A worktree can start from an old commit. Tell the agent the base branch and tell it to
  rebase or merge the base first. Check that the agent sees the same source the tests import.
  Some projects need a flag such as `-o pythonpath=src` so tests import the worktree code.
- Give each agent a branch name and a file scope. Two agents in one wave must not own the
  same file. If they must, make them sequential.
- Uncommitted work in the main tree is invisible to a worktree. If a config or test budget
  changed in the main tree, say so in the prompt, or commit it first with the user's word.
- Merge one branch at a time. Run the full suite after each merge. Resolve conflicts in the
  integration branch, never in the agent branch after the fact.
- Clean up when the user agrees: remove merged worktrees and delete merged branches.
  Never delete a branch with unmerged work. Never force-delete without asking.
- Run independent agents in one message so they start together. Run dependent agents in
  sequence.

Wave design:

- Wave A: backend core and data layer, plus contract-driven frontend skeleton, in parallel.
- Wave B: the pieces that join them: wiring, state, error handling.
- Wave C: reviews and live checks, in parallel, each read-only.
- Wave D: fix agents for what the reviews found.
- Last: polish and the final independent verification.

---

## 9. Verification, the part you never delegate

You run these yourself every time. Do not hand this to the builder.

1. Full test suite. Record passed, failed, skipped, and deselected counts. Compare with the
   baseline from section 2. If the counts differ from the agent's claim, believe your count
   and log the gap.
2. Static checks the project has: lint, type check, import boundary tests, size budgets.
3. The diff. Look at file names first. An edit outside the scope is a red flag.
4. A manual run of the real flow with real, safe data (a copy, never the real store).
5. A skeptic's check of each claim: "tests pass" (did they run the new tests?), "no
   regression" (compared with what?), "fixed" (shown on the original failing case?).
6. For numbers and money-like logic, test the boundaries: exact edges, rounding, zero, empty,
   the largest value, and ties.
7. For concurrency, test two writers at once.
8. For a UI, run the browser pass in section 12.

Rules of honest reporting:

- If a test fails, say so with the output. Do not fix and continue silently. A failed check
  is a stop.
- If you skipped a step, say you skipped it.
- When something is done and verified, say so plainly without hedging.
- Report a failure as soon as you know it, not at the end.

A suspected bug gets a direct check against the real state before you trust the first
plausible theory. Reproduce first, then explain.

---

## 10. Testing rules

- Tests come first. Write the failing test, watch it fail for the right reason, then write
  the code. This is red, green, refactor.
- Aim for at least 80 percent coverage of new code. Cover unit, integration, and the critical
  end-to-end flows.
- Name tests for behavior: "returns an empty list when nothing matches."
- Use arrange, act, assert.
- A test must be hermetic. If it fakes one side effect, it fakes every side effect on that
  path. Otherwise it passes only on the author's machine.
- When a test simulates an unset environment variable, set it to an empty string. Do not
  delete it, because code that loads a dotenv file can read the real value back and take a
  real action such as sending a message.
- Tests never touch the real database, the real network, or real accounts. Give tests their
  own database and check that the guard works.
- If a new middleware or dependency touches the database on every request, audit every test
  file that creates a client. The set of tests that need isolation grows to every test that
  makes any request.
- Never weaken a test to make it pass. Fix the code. Only change a test when the test is
  wrong, and say why in the log.
- Goldens (saved expected outputs) hold values only, never private data.
- Keep an offline replay for any model-based feature, so the suite is fast and free.

---

## 11. Database and secrets safety

Treat real data and real credentials as off limits to automated work.

- Never read secret files (`.env`, session or token files). If a task needs a value, ask the
  user to set it, and check only that the name exists.
- Never commit secrets, local databases, downloads, or captures. Check `git status` and
  `.gitignore` before every commit. If one of these is trackable, stop and fix `.gitignore`.
- Write every commit as if the repo were already public.
- Never run a migration or any write on the real database yourself. Build the migration and
  test it on a private copy. For the real run, give the user the exact command to run with
  the `!` prefix in the prompt, so the output lands in the session. Use forward slashes in
  paths so the shell does not eat the backslashes.
- Before a real migration, ask the user to take a backup and show them the command. Verify
  the backup file exists and is not empty. Then they run the migration script.
- Private-copy workflow: a tool in `tools/` restores a dump to a throwaway database, migrates
  it to head with the branch's migrations, runs a command (tests, a check), then drops the
  copy. Use it for any live check that needs real-shaped data.
- After the migration, verify the revision, the row counts of existing tables, and that
  nothing else changed. Log it.
- Any write made during a live test of a real store must be deleted right after. Prefer
  read-only inspection of live documents. A near-miss on a shared document is a stop.
- Outside systems you read from: obey their rules exactly. If the project says GET only, a
  write call is a bug even if it would work. Keep requests sequential with delays, and abort
  on a block or rate-limit response. Never retry into a block.
- Logs never hold secrets, tokens, or personal values such as marks, grades, or messages.
- Before any action that creates or touches a credential or session on disk, stop and ask
  first. Report-after is not acceptable.

---

## 12. UI work

Visual direction and checks come from named sources, not from taste in the moment.

1. Read `PRODUCT.md` and `DESIGN.md` if present. If the project has none, run the
   `impeccable` skill to shape a direction and record it in `design/<feature>/`.
2. Build with the project's own design tokens, components, and layout helpers. Reuse before
   writing new styles.
3. Check the real page. Do not guess from the CSS. Use the browser tools:
   - Open the page with the chrome-devtools tools or the browser extension.
   - Resize to phone width (about 390 px) and desktop width (about 1200 px).
   - Check light theme and dark theme.
   - Check keyboard-only use: tab order, visible focus, escape closes dialogs.
   - Read the console for errors and the network list for failed calls.
4. Run `break-ui` with worst-case data: very long names, unbroken strings, one-letter names,
   missing fields, zero items, huge counts, non-Latin text, emoji, extreme numbers.
5. Run the accessibility check: contrast, labels, roles, headings, target size, reduced
   motion.
6. Run an `impeccable` critique in a separate sub-agent that did not build the screen. Treat
   its score as input. Design choices that change the product go to the user.
7. Other design skills may audit but must not change the direction.
8. Respect the project's budgets (bundle size, layout rules). Lazy-load heavy screens.
9. Record screenshots or notes in `design/<feature>/`. Name them before and after.

Real layout bugs hide from a code read. Overflowing flex rows, grid items that grow the whole
page, mobile heights, and rule order in CSS are found only by looking at the live page.

---

## 13. Commits, pushes, and the user gate

- Do not commit and do not push until the user says so. A past approval does not cover a new
  action.
- Commit messages: `<type>: <description>` with types feat, fix, refactor, docs, test, chore,
  perf, ci. Add a body when the why is not obvious.
- Before you ask to commit, run the pre-commit checks:
  - No secrets in the diff.
  - Full tests pass.
  - `git status` shows only intended files.
  - A security review ran if the change touches input, auth, data, files, or outside calls.
- Keep commits focused. One feature or fix per commit when you can.
- For a pull request: read the full history of the branch (not only the last commit), compare
  against the base branch, write a summary, and add a test plan.
- Never rewrite published history, force-push, or skip hooks unless the user explicitly asks.
- Hard or outward actions need confirmation each time: pushing, sending messages, posting,
  sharing a file, deleting data, deploying. State what you will do and wait.
- At each phase end, tell the user: what is done and verified, what is not done, what you
  need from them, and that nothing is pushed (or what was).

---

## 14. Context limits and resuming

Your context fills up over a long project. Plan for it.

- Keep your context small by letting sub-agents read big files and return short reports.
- Write the log as you go. Then a reset loses nothing, because the logs hold the state.
- At a natural phase boundary, compact or save the session (`ecc:strategic-compact`,
  `ecc:save-session`). Do not compact in the middle of a risky step.
- After a reset, do this: read `progress.md` from the bottom, then `decisions.md`, the last
  `waves.md` block, and `git log -15`. Re-run the test suite for a baseline. Then continue
  from "State now" in the last progress entry. Do not re-do finished work and do not re-argue
  settled decisions.
- If a summary of the earlier session exists, trust the logs over the summary when they
  disagree, and fix the log if it is wrong.
- Save durable user preferences to the memory folder if the tool gives you one: one fact per
  file, a short index, and no fact that the code or git history already shows.

---

## 15. Common failures and how to avoid them

1. The agent claims success and the tests say otherwise. Always run the tests yourself.
2. Counts do not match. Different filters, deselected tests, and stale worktrees cause this.
   Record your own count and move on.
3. A worktree runs old code. Check the base commit and the import path.
4. The agent edits outside its scope. Give a file list and check the diff.
5. The agent adds a dependency. Forbid it in the prompt and check the lock file.
6. Two agents change the same file. Split the scope or run them in sequence.
7. A weak test passes for the wrong reason. Ask the test analyzer, and break the code on
   purpose to see the test fail.
8. A fix patches one caller while others stay broken. Fix the shared function.
9. A green suite hides a UI bug. Do a live pass.
10. A silent fallback hides an error. Use the silent-failure hunter.
11. Rounding and float noise flip a result at an exact boundary. Use exact decimals and
    test the edges.
12. Races between two saves. Test two writers and make writes idempotent.
13. Raw database or library text leaks to the user. Return fixed, plain messages.
14. A model call sneaks into a deterministic path. Add an import-boundary test.
15. A test writes to the real database. Check that every test that makes a request sets the
    test database first.
16. Context bloat. Delegate reading and keep reports short.
17. Scope creep. Write non-goals into the plan and say no in the review.
18. A loop that never ends. Cap retries and stop to ask.
19. Guessing an outside API. Observe it first or ask.
20. Starting the next phase early. Wait for the gate.

---

## 16. Prompt templates

Replace the angle brackets. Keep the prompt tight and specific.

### 16.1 Builder

```
Role: You are the builder for <unit name> in <feature>. You work in an isolated worktree.

Goal: <one sentence of what must exist when you finish, and why>.

Read first (do not skip):
- <path to project instruction file>
- session_context/design/<feature>/PLAN.md (your unit: <unit id>)
- session_context/design/<feature>/API_CONTRACT.md
- session_context/lessons.md (look at: <relevant lesson titles>)

Scope:
- You own: <files and folders>.
- You must not edit: <files and folders>. If you need a change there, stop and report it.

Rules:
- Write failing tests first. Run them and confirm they fail for the right reason.
- Reuse existing helpers. Search the codebase before you write new code.
- Add no new dependency.
- Do not read secret files. Do not touch the real database. Do not make network calls.
- Do not commit. Leave the changes in the working tree of your worktree.

Method:
1. Write the tests described in the plan.
2. Implement the smallest code that passes them.
3. Run: <exact test command>. Run: <lint and type commands>.
4. Refactor if needed. Run them again.

Done means: <exact command> shows 0 failed, and <behavior> works.

Final report (short):
- Files changed (list).
- The real output of the test command (paste the last lines).
- What you did not do, and what you are unsure about.
- Anything in the plan or contract that looked wrong.

Stop and report instead of guessing if: a contract detail is missing, a test fails after
three honest attempts, or you need to edit a file outside your scope.
```

### 16.2 Reviewer

```
Role: You are an independent reviewer. You did not write this code. You do not edit code.

Review: the changes in branch <branch> compared with <base>. Run `git diff <base>...<branch>`.

Focus: <correctness | security | database | accessibility | silent failures | test quality>.

Read first: the plan and contract at session_context/design/<feature>/, and the project
instruction file.

Method:
1. Read the diff. Trace each changed function to its callers.
2. Try to break it. Think about empty input, huge input, concurrent writers, and failure
   of every outside call.
3. Run the tests and any command you need that is read-only.

Output: write a report to session_context/audits/<date>-<area>-<kind>.md. For each finding
give: severity (CRITICAL, HIGH, MEDIUM, LOW), file and line, what is wrong, a concrete
failing scenario with inputs and the wrong output, and a suggested fix.
Do not report style opinions as bugs. Do not report a finding you did not verify. If you find
nothing, say what you checked.
```

### 16.3 Fixer

```
Role: You are the fixer for findings from <report path>.

Findings to fix: <list with ids>. Do not fix anything else.

For each finding:
1. Write a test that fails because of the finding.
2. Fix it at the root, in the shared place, not in one caller.
3. Run the test and the full suite.

Scope and rules: same as the builder template. Do not commit.

Report: for each finding, fixed or not, the test name, and the real test output.
```

### 16.4 Explorer

```
Role: You are a read-only explorer. Do not edit files.

Question: <what I need to know, for example "which files handle X, and what helpers exist
for Y">.

Report (under 300 words): file paths with line numbers, the existing pattern to follow,
helpers that I can reuse, and any trap. Quote only short snippets.
```

### 16.5 Live check

```
Role: You are the live checker for <feature>. You run the real app on a private copy of the
data and you do not edit code.

Setup: <exact commands to start the app on the copy>.
Check, in the browser: <list of flows>. Use widths 390 and 1200 px, light and dark theme,
and keyboard-only use. Feed worst-case data with the break-ui skill.
Rules: any write you make to the app data must be on the private copy. Do not use the real
database. Do not trigger browser alert dialogs. Stop and report after three failed attempts.

Report: each problem with steps to reproduce, a screenshot name, and the likely cause.
```

### 16.6 Design critique

```
Role: You are an isolated design critic. You did not build this screen.

Use the impeccable skill to critique <screen> against DESIGN.md and PRODUCT.md. Look at the
live page at 390 and 1200 px in both themes. Score it and list the top problems with the
smallest fix for each. Do not change the design direction. Mark which items need a decision
from the user.
```

---

## 17. Checklists

### 17.1 Starting a feature

- [ ] I read the project rules and the logs.
- [ ] I know the baseline test counts.
- [ ] An explorer mapped the code and found reusable parts.
- [ ] I searched for existing solutions.
- [ ] The plan, the contract, and the test plan are written in `design/<feature>/`.
- [ ] The user approved the plan.

### 17.2 Dispatching a wave

- [ ] Each unit has a file scope with no overlap.
- [ ] Each prompt has role, context paths, scope, rules, method, verification, report format,
      and stop conditions.
- [ ] Each builder has its own worktree and a known base commit.
- [ ] The exact prompts are saved in `waves.md`.

### 17.3 Accepting an agent's work

- [ ] I read the report and the diff.
- [ ] The files changed match the scope.
- [ ] I ran the full suite and recorded the real counts.
- [ ] I ran the project boundary checks.
- [ ] I ran the real feature once.
- [ ] I logged claim versus measurement.
- [ ] An independent reviewer checked it.
- [ ] I merged it alone and ran the suite again.

### 17.4 Closing a phase

- [ ] Docs that the change made false are updated.
- [ ] `progress.md` has the phase-complete entry with "not done" and "state now."
- [ ] New bugs are in `bugs.md`, new rules in `lessons.md`, new choices in `decisions.md`.
- [ ] I told the user what is verified, what is not done, and what I need.
- [ ] Nothing was committed or pushed without the user's word.
- [ ] I am waiting for the user to confirm before the next phase.

### 17.5 The one-paragraph version

Read the rules and the logs. Explore, then plan, then get approval. Write the contract and
the tests first. Send builders into worktrees with tight prompts and save the prompts.
Verify every result yourself with real commands. Send independent reviewers, then fixers.
Check the live thing, not only the tests. Merge one branch at a time. Log every step as it
happens in `progress.md`, `bugs.md`, `lessons.md`, `decisions.md`, and `waves.md`. Never touch
real data, secrets, commits, or pushes without the user's word. Stop at each gate.
