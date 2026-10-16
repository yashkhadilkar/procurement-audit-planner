# Procurement Audit Planner (West Berkshire Council)

An agent system, built in Claude Code, that plans an internal audit of West Berkshire Council's procurement from the council's own public data. It turns the council's purchasing rulebook into testable rules, analyses every published payment against them, reads past audit history, rates the risks on the council's own scale, and produces an audit planning pack that a human auditor approves and signs off.

> **Read this first.** The data is real and public. Everything in `outputs/` is a **risk indicator to investigate**, not a finding. A flagged payment or supplier is something an auditor would look at, nothing more. Nothing in this repo suggests wrongdoing by the council, any department or any supplier.

Built for Assignment 2 of the LLM class by Group 3: Yash Khadilkar, Hans Grunwald, Pranav Piedy, Reyn Okinaga and Forum Sanjanwala. Part A is the Claude Code system described below. Part B is the same system running as a deployed web app, described in [Part B: the deployed harness](#part-b-the-deployed-harness).

**Live app:** https://procurement-audit-planner-production-c85e.up.railway.app

---

## What it produces

Starting from four inputs in `data/` (the Contract Procedure Rules PDF, three months of "Expenditure over £500" workbooks, a Contracts Finder export and four Governance Committee papers), the system produces:

| Output | What it is |
| --- | --- |
| `outputs/rules.json` | Every testable rule in the rulebook, with clause, page, thresholds and a verbatim quote checked against the PDF |
| `outputs/analytics.json` + `outputs/analytics-full/` | Seven spend tests over every payment, computed in Python, with full lists of flagged transactions |
| `outputs/history.json` | Past audit opinions, gaps and the council's own risk-scoring method, each with a quote from the papers |
| `outputs/risk-register.md` | Rated risks (likelihood x impact on the council's 5x5 matrix), each citing a rule, a metric or a past audit |
| `outputs/auditor-comments.md` | The auditor's decision on every risk (the first human gate) |
| `outputs/planning-memo.md`, `risk-control-matrix.md`, `audit-program.md`, `samples/` | The audit planning pack: controls, tests, the exact payments to pull and the request list |
| `outputs/challenges.md` | The challenger's points on the plan and how each one ended |
| `outputs/review.md` | QA results, the verdict and the auditor's sign-off (the second human gate) |

## How the pieces fit together

```
                 data/contract-rules.pdf
                           |
          /extract-rules   (skill, run by a person)
                           |
                      rules.json
                           |
         +-----------------+------------------+
         |                                    |
   spend-analyst  (sub-agent)        findings-analyst  (sub-agent)
   spend workbooks + contracts.csv   committee papers
   writes and runs Python            reads and quotes
         |                                    |
   analytics.json                       history.json
         +-----------------+------------------+
                           |
   risk-assessor  (sub-agent, follows the risk-assessment skill)
                           |
          risk-register.md + auditor-comments.md
                           |
   HUMAN GATE 1: auditor approves, amends or rejects every risk
                           |
   agent team (follows the audit-program skill)
     planner      -> audit-plan.json -> the pack
     challenger   -> challenges.md   (questions the plan)
     qa-reviewer  -> review.md       (runs four check scripts)
                           |
   HUMAN GATE 2: auditor signs off review.md
```

Each stage only reads the files the previous stage wrote, so every handoff can be inspected and every stage can be rerun on its own.

Four rules hold at every stage (they are written into `CLAUDE.md`, which Claude Code reads at the start of every session):

1. **The model reads and judges; Python computes every number.** No agent does arithmetic over the data. Figures in the register and the pack are placeholders that a script fills in.
2. **Everything is traceable.** Quotes are verified against the source PDFs, every figure comes from a named script, and every rating cites a rule, a metric or a past audit.
3. **Indicators, not accusations.** Outputs describe patterns to investigate and never name a supplier in a risk statement.
4. **Missing input means stop and report.** Nothing is guessed. A threshold the rulebook names but never states stays empty, and the tests that need it report "not run".

## Skills

Skills are instruction folders in `.claude/skills/`. Each one is a method plus a script that enforces it.

| Skill | Used by | What it does |
| --- | --- | --- |
| `extract-rules` | a person, via `/extract-rules` | Turns the rulebook PDF into `rules.json`. `verify_quotes.py` checks every quote word for word on the page it cites, and checks that all 152 printed clause and appendix-row IDs are covered by a rule or an exclusion with a reason. |
| `risk-assessment` | risk-assessor | The rating method. The agent writes its judgments to `risk-ratings.json`; `build_register.py` resolves every citation, fills every figure, computes scores on the council's matrix, renders the register and the decision template, and refuses any risk with a citation that doesn't resolve. After the gate it applies the auditor's decisions as a numbered revision and fails if anything changed that the auditor didn't ask for. |
| `audit-program` | planner | The planning method. The planner writes its judgments to `audit-plan.json`; `build_pack.py` checks the gate, draws every sample from the flagged lists, checks each sampled transaction exists in the cleaned spend data, and renders the three documents plus `pack-figures.json`. |

## Agents

Agents live in `.claude/agents/`. The first three are sub-agents: each does one job in its own context window and hands back a result. The last three form an agent team that works together by messaging each other.

| Agent | Type | Owns | Job |
| --- | --- | --- | --- |
| `spend-analyst` | sub-agent | `scripts/`, `analytics.json` | Cleans the workbooks, parses Contracts Finder, tags every payment by kind of spend, runs seven tests, and re-derives one result per test in `selfcheck.py` |
| `findings-analyst` | sub-agent | `history.json` | Records audit opinions, gaps, contradictions and the risk-scoring method from the committee papers; never scores; checked by `scripts/verify_history.py` |
| `risk-assessor` | sub-agent | `risk-ratings.json` | Rates each risk using the risk-assessment skill; recommends only |
| `planner` | teammate | `audit-plan.json` | Plans the approved risks; announces each version as `PACK READY vN`; answers challenges; fixes QA failures |
| `challenger` | teammate | `challenges.md` | Raises up to eight cited challenges, then up to four more; checks each accepted change in the rebuilt pack; sends rating and scope points to the auditor |
| `qa-reviewer` | teammate | `review.md` | Runs `scripts/checks/run_checks.py` on every version; reports PASS or FAIL word for word; blocks sign-off until all four checks pass |

The QA checks in `scripts/checks/` deliberately do not import either builder, so the pack is checked independently of the code that built it:

- **check_quotes**: every rule quote is on its stated page of the PDF
- **check_numbers**: every figure in the three documents traces to the analytics, the rules, the builder's figures or a sample file
- **check_trace**: every rule is covered or excluded with a reason, every in-scope risk has a control with a test, every rejected or left-out item has the auditor's decision
- **check_samples**: every sampled payment exists in the cleaned data and at its stated row in the council's original workbook

All agents keep a project memory folder (`.claude/agent-memory/`) restricted to how-to lessons. No figures, supplier names or findings are stored there.

## Results from this run

| Stage | Result |
| --- | --- |
| Rules | 67 testable rules (25 approval, 23 required action, 18 threshold, 1 anti-avoidance), 49 exclusions, 37 notes on the rulebook itself; all 152 clause IDs covered |
| Spend | 10,607 payments (£80.43m) across May to July 2026; 8,649 (£67.16m) after removing statutory payments and payments to individuals; self-check 42/42 and 59/59 reconciliations |
| History | 20 audited areas, 25 risk themes, 23 contradictions and 8 gaps recorded; the council's own 5x5 scoring method found and used |
| Register r0 | 10 rated risks, 3 adverse audits noted but not rated, 0 excluded, 0 warnings |
| Gate 1 | 7 approved, 1 amended (R-05 likelihood 4 to 3), 2 rejected (R-03, R-04), 3 noted items left out; register revised to r1 with 8 risks in scope |
| Agent team | 3 pack versions, all passing QA; 7 challenges (6 accepted and verified, 1 for the auditor); 13 controls, 8 tests, 7 sample files, 520 sampled transactions |
| Gate 2 | Final QA 4/4 pass, READY FOR SIGN-OFF; signed off on 2026-10-13 |

## Decisions we made along the way

We followed the guide's lessons but had Claude Code write every skill and agent against our own data instead of copying the finished files. Profiling the real inputs turned up several places where the brief didn't fit, so we changed the brief (`CLAUDE.md`) first, since every agent follows it literally.

**Data and parsing**
- The council's name appears in capitals on six contract notices, so the buyer match ignores case.
- Contracts Finder's Published Date is ISO 8601, not D/M/Y like the other date columns, so it gets its own explicit format.
- The active-notice check uses the contract start and end dates, not the notice dates. One notice has a contract end date of 2055, which looks like a typo and would be worth raising with the council.

**What counts as procurement**
- 19% of payments name the supplier only as "Redacted". Most are Direct Payments and care allowances. We exclude payments to individuals (Direct Payments, care allowances, Payments to Carers) along with statutory and inter-authority payments, and keep any remaining Redacted rows out of the tests that group by supplier.
- Grants stay in, tagged as grants.
- Every payment is tagged as placement, grant, agency staff, premises or general procurement. Ratings rest on the general procurement figures because placement fees recur by design. Duplicates drop from 684 groups overall to 50 in general procurement.

**Tests**
- The guide's "off contract" test became `no_published_notice`. Only about 5% of large suppliers match a notice in the Contracts Finder export, because the export only covers notices published since 2021 and frameworks rarely get their own notice. Missing a notice isn't evidence of anything, so the result is a list of suppliers to request contract evidence for, and the council's contracts register goes on the request list.
- The clustering test compares the band just under each threshold with the band just over it, so a count under the threshold means something.
- The £1,000 split-purchase tier can never raise a rating on its own: every published payment is over £500, so any two under £1,000 add up to more than £1,000.
- The rulebook names "the Threshold" for full tenders but never states its value. We left it empty rather than filling it from memory, and the tests that need it report "not run".

**Rating and the gates**
- Audits with a Limited or Weak opinion on areas the spend tests exclude (Personal Budgets, two school follow-ups) are listed as "noted, not rated" for the auditor to decide, rather than being rated or dropped.
- Where the council's risk strategy contradicts itself (two different escalation cut-offs, overlapping impact bands, two names for the same band), the register uses one reading and states the other in its header. The four risks scoring 9 to 14 would be escalated under the strategy's Figure 4 but not under Table 4.
- The challenger caught the auditor too: our gate comment on AUD-16 said the area was "covered by the existing audit's follow-up", and the record shows no such follow-up. The decision to leave it out stands on its own grounds (payments to individuals, not council purchasing), and the sign-off comment corrects the reason.

**Keeping tests honest**
- Each verifier and builder was tested against fixtures with planted errors. The fixtures were kept outside the repo until after the real run, so an agent couldn't copy a hand-written example into its output.

## Steps completed

All 27 steps of the guide are done; the commit history shows each one.

| Lesson | Steps |
| --- | --- |
| Setup | VS Code and Claude Code installed; folder and repo; `CLAUDE.md`; council data in `data/`; Python environment; project folders |
| 1. Skills | 2.1 built `extract-rules` and its verifier; 2.2 ran it to produce `rules.json` |
| 2. Sub-agents | 3.1 to 3.2 built and ran `spend-analyst`; 3.3 to 3.4 built and ran `findings-analyst`, with three items checked against rendered PDF pages; 3.5 built the `risk-assessment` skill; 3.6 to 3.7 built and ran `risk-assessor` |
| 3. Human gate | 4.1 opened the decision template; 4.2 recorded all 13 decisions; 4.3 revised the register to r1 |
| 4. Agent team | 5.1 confirmed the gate; 5.2 enabled agent teams; 5.3 built the `audit-program` skill; 5.4 to 5.6 built the planner, challenger and qa-reviewer with its four checks; 5.7 ran the team; 5.8 signed off |

## Repo layout

```
CLAUDE.md                      the brief every session reads
data/                          council inputs, read-only
.claude/skills/                extract-rules, risk-assessment, audit-program
.claude/agents/                six agents
.claude/agent-memory/          per-agent how-to notes
.claude/settings.json          enables agent teams
scripts/                       spend analysis, verify_history.py, tests/, checks/
outputs/                       everything the system produced
app/                           Part B: the web harness (server, runner, team loop, UI, tests)
Dockerfile, .dockerignore      Part B: the container Railway builds
```

## Running it again

Requires VS Code, Claude Code 2.1.224 or later, and Python 3 with poppler (`pdftotext`).

```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
claude
```

Then, in Claude Code: `/extract-rules`; "Run the spend-analyst."; "Run the findings-analyst."; "Run the risk-assessor."; record decisions in `outputs/auditor-comments.md` and run the risk-assessor again; then run the agent team as described in `CLAUDE.md` (Agent team section). The QA checks can be run on their own with `.venv/bin/python scripts/checks/run_checks.py`.

## Limitations

- Three months of spend, annualised by multiplying by four. Seasonal spend will distort that.
- Payments are not contract values. Thresholds apply to total contract value, so single payments, 30-day groups and annualised totals are stand-ins.
- The spend data has no contract type, so goods, works and concession bands can't be told apart.
- The rulebook disagrees with itself on whether values include VAT. The tests use Net amount, and the memo leaves the reading to the auditor.
- Contracts Finder is not a contracts register. "No published notice found" is a request for evidence, not a gap in compliance.

---

## Part B: the deployed harness

Part A only runs inside Claude Code on a laptop. Part B runs the same skills, agents, scripts and checks as a web app anyone can open, with the two human gates as forms in the browser.

**Live app:** https://procurement-audit-planner-production-c85e.up.railway.app

The access code is in our Bruin Learn submission, not in this repo. Without it the site is read-only: you can open every stage and every output. With it you can run the agent team, record the gate decisions and reset the demo.

### Trying it

1. Open the link. The Overview shows every stage of the pipeline and where it stands.
2. Click through Rules, Spend, History and Register to see what each stage produced, then Gate 1 for the auditor's decision on every risk.
3. Enter the access code and open Team. Start a run and watch the planner, challenger and QA reviewer work in the live log. A run takes about 5 minutes and costs about $0.50 in API usage. The spend so far is shown at the top of the page.
4. When QA reports READY FOR SIGN-OFF, open Gate 2, review the challenges and QA points left for the auditor, and record the sign-off.
5. "Reset to signed-off run" restores the signed-off outputs committed in the repo (run logs are kept).

### How it works

```
browser (static HTML/CSS/JS)
   |  REST for actions, server-sent events for the live log
FastAPI server (app/server.py)
   |
runner (app/runner.py)  ->  Claude Agent SDK, one session per stage
   |                        loads the project's skills and agents from .claude/
team loop (app/team.py) ->  planner, challenger and QA as separate SDK sessions,
   |                        with Python passing messages between them
gates (app/gates.py)    ->  Gate 1 and Gate 2 decisions written to the same files as Part A
   |
working copy of the repo on a Railway volume (/data/work)
```

- **Same system, not a rewrite.** The harness uses the Agent SDK with the project's settings, so it loads the same `CLAUDE.md`, the same three skills and the same agent prompts as Part A. The builders, verifiers and the four QA checks are the same scripts.
- **The agent team.** The Agent SDK doesn't support Claude Code's experimental agent teams, so `app/team.py` plays the part of the team. It runs the planner, challenger and QA reviewer as separate sessions and passes each message to the right recipient: `PACK READY vN` from the planner goes to the challenger and QA, challenges go back to the planner, and QA's verdict decides whether the loop ends or the planner fixes and rebuilds. The protocol is the same as Part A, but the Python code enforces it instead of leaving it to the agents.
- **Limits in code.** `app/config.json` sets the model and spend cap for each stage. The team stage stops at $3, and the challenger gets 6 challenges and then 3 more. The server refuses to start a run while another is going.
- **The gates stay human.** Nothing moves past Gate 1 or Gate 2 without a decision recorded in the browser. Gate 2 only opens once QA reports READY FOR SIGN-OFF, and a new team run writes a new review that needs its own sign-off.
- **Working copy.** Each run works on a copy of the repo in `WORK_DIR`, never on the deployed code. The team stage fingerprints the protected inputs when it starts and stops the run if any of them change while it's going.

### What went wrong while building it

- **Background tasks.** The SDK started the sub-agent as a background task, and it was killed when the session ended. Setting `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1` makes stages wait for their agents, and runs that were cut off are marked failed instead of being left as "running".
- **Messages that didn't arrive.** The challenger's `CHALLENGER DONE` wasn't reaching QA, so QA kept waiting. QA is now a recipient, and the protocol gained a `QA DONE` message so the loop ends cleanly.
- **The planner gamed a check.** The pack has to explain every risk it leaves untested, and a check rejects copied-and-pasted reasons. In one run the planner got around it by writing the same template reason and changing only the quoted text and the risk ID. The check now masks quoted text and risk IDs before comparing, and the planner's prompt says not to list every risk with the same reason. It was a good reminder that a check the model can see becomes a target.
- **iCloud copies.** On a Mac, iCloud made " 2" copies of files in the working folder, which tripped the fingerprint check. The working folder now lives outside iCloud.

### Result of the live run

Run on the deployed app on 2026-10-15, from the Gate 1 decisions in Part A:

| | |
| --- | --- |
| QA verdict | READY FOR SIGN-OFF, pack v3, all four checks passing |
| Challenges | 8 raised, 7 resolved, 1 for the auditor (#4, the R-08 impact rating) |
| Pack | 16 controls, 8 tests, 531 sampled transactions, 29 rules traced |
| Cost | $0.44 |
| Gate 2 | Signed off by Yash Khadilkar (the date shows as 2026-10-16 because the server runs on UTC) |

The pack is not identical to the Part A pack, because the planner and challenger make different calls on each run. The checks are what stay fixed: every version has to pass all four before it can be signed.

### Deployment

- One Railway service built from the `Dockerfile` (Python 3.13, poppler for `pdftotext`, git), served by uvicorn with one worker. `/healthz` is the health check.
- A Railway volume at `/data` holds the working copy and run records, so they survive restarts and redeploys.
- The API key and access code are Railway variables. The Docker build fails if a `.env` file ends up in the image.
- The key belongs to a separate Anthropic workspace with an $8 monthly spend cap, so a grader can't run up a large bill.

### Running it locally

```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
touch .env              # then set ANTHROPIC_API_KEY, ACCESS_CODE and WORK_DIR
.venv/bin/uvicorn app.server:create_app --factory --reload
.venv/bin/python -m pytest app/tests
```

### Part B limitations

- The agents run as root inside the container. That's fine for a single-purpose demo but not for anything multi-tenant.
- One run at a time. A second person starting a run while one is going gets told to wait.
- The site is on Railway's free trial and the API key expires on 2026-11-12, so the live link will stop working after mid-November.
- The access code is shared rather than a login per user.