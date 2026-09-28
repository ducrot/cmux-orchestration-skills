# cmux Orchestration Skills

Three agent skills for researching, planning, and implementing changes through AI workers in visible [cmux](https://github.com/manaflow-ai/cmux) terminal panes. The orchestrating agent coordinates the work, checks reports and changes, and brings decisions back to you. Workers do the research and edit product code.

| Start with | When you need | What you get |
|---|---|---|
| **[cmux-grilling](cmux-grilling/SKILL.md)** | To stress-test a plan or resolve uncertainty | Assumptions, sources, and open decisions in Markdown + JSON |
| **[cmux-planning](cmux-planning/SKILL.md)** | To turn a task into an executable plan | An approved specification and reviewed local issue tracker |
| **[cmux-issue-chain](cmux-issue-chain/SKILL.md)** | To implement an issue from an existing tracker | Implemented, simplified, reviewed, and tested changes |

They form an optional progression, not a mandatory pipeline:

```text
cmux-grilling  →  cmux-planning  →  cmux-issue-chain
```

Use any skill on its own. No workflow automatically invokes another. Research and execution can run unattended between checkpoints; initial setup, approvals, blockers, and changes to agreed decisions may need your input.

## Install

Install all three with the [skills CLI](https://vercel.com/docs/agent-resources/skills):

```bash
npx skills add ducrot/cmux-orchestration-skills
```

Or install just one:

```bash
npx skills add ducrot/cmux-orchestration-skills --skill cmux-issue-chain
```

Each skill includes its own runtime helpers and works without the sibling directories. For a manual installation, copy or symlink complete skill directories into your agent's skills directory, such as `~/.claude/skills/` or `~/.codex/skills/`.

### Requirements

- **cmux** for visible worker panes, with its CLI available to the orchestrator.
- **Git and Python 3.11 or newer** in the target repository. The bundled Python helpers use only the standard library, including `tomllib` for Codex trust configuration.
- **One-time repository trust:** Before preparation, start each assigned `claude` or `codex` harness in the exact repository root, accept the trust dialog, then exit. Preparation reads Claude Code trust from `~/.claude.json` (or `$CLAUDE_CONFIG_DIR/.claude.json`) and Codex trust from `~/.codex/config.toml` (or `$CODEX_HOME/config.toml`); for a linked Git worktree, both harnesses record the trust under the main checkout, which preparation accepts; parent or home-directory trust is insufficient. Pi must support `--no-approve`, which worker launches append.
- **An orchestrating agent** that can load skills and operate cmux, such as Claude Code or Codex.
- **Authenticated Claude Code and Codex CLIs** for the shipped worker defaults. The configured models must be available to your account. The Pi CLI is supported too, but no default assignment uses it.

Worker assignments are configurable. Issue-chain and planning support every harness for every role; grilling's web lane needs Claude Code or Pi, because Codex cannot reach the web. Planning pins no role to a harness: when its reviewer resolves to the same harness and model as the author it checks, preparation stops for your explicit confirmation instead. A Pi profile must name its provider, as in `openrouter/z-ai/glm-5.3`.

For Claude Code issue-chain workers, make sure `/simplify` and `/code-review medium --fix` are available in that installation. These commands are not supplied by this repository. On Codex and Pi, the skill provides the corresponding simplify and review instructions directly in the worker prompt.

Pi is the least contained harness on offer: it ships no sandbox and no approval gate, so a Pi worker's shell and file tools run unconfined and the `.git` protection that Codex workers get does not apply. Choose a Pi profile only where that is acceptable.

## First run

Open the target repository in cmux and ask your agent to use the relevant skill. For example:

> Use cmux-grilling to stress-test adding full-text search to this repository. Keep the existing database and deployment setup. Research up to five decision-level questions.

> Use cmux-planning to plan CSV export for the orders list. Ground the specification in this repository and prepare a local issue tracker for my approval.

> Use cmux-issue-chain to implement ISSUE-001 from .scratch/orders-export. Follow the tracker's acceptance criteria and canonical check commands.

On first use, the orchestrator creates `.scratch/orchestrator/agents.json`, shows the assignments for all three workflows, and asks whether to start or pause for edits. An existing valid schema-v3 file needs no start confirmation. Worker startup checks the configured executables, CLI capabilities, and local authentication.

Issue-chain needs a compatible local Markdown tracker with issue metadata, dependencies, and canonical check commands. Planning produces this format. Existing `to-tickets` trackers can be converted with the [tracker adoption helper](cmux-issue-chain/SKILL.md#adopting-a-to-tickets-tracker).

## How the workflows work

### cmux-grilling: research decisions

Give it a task or plan and any constraints already settled. The orchestrator asks the decision-level questions whose prerequisites are settled in rounds (four by default), several per round when they are independent. Four persistent workers research each round's questions in parallel: repository analysis, a second repository opinion, official documentation, and web research. The orchestrator checks their reports and synthesizes an answer with confidence and sources.

The research ends when the round budget is spent or no relevant open question remains. It produces a Markdown + JSON pair containing assumptions and open decisions. You then review the assumptions and walk through the open decisions; the artifacts are updated with those outcomes. Research is autonomous, while the closing review involves you.

[Workflow and artifact details](cmux-grilling/SKILL.md). A separate interactive grilling skill, where you answer every research question, is not bundled here.

### cmux-planning: approve a specification and tracker

Start with a task, optionally accompanied by a grilling artifact pair that you explicitly revalidate.

1. A fresh author inspects the repository and writes a specification.
2. A fresh independent reviewer checks it and records what was checked and the outcome. Safe corrections are validated and shown to you.
3. **You approve the specification** or request revisions.
4. A fresh author creates cohesive implementation tickets, followed by another fresh independent review.
5. **You approve the tickets**, then the complete native tracker is published with a collision-safe atomic move.

Changes to scope, architecture, or other substantive decisions return to you. If an author and reviewer resolve to the same CLI and model, preparation pauses for explicit confirmation. Approvals are bound to the reviewed artifacts; changed content requires a new approval.

[Workflow and approval details](cmux-planning/SKILL.md) · [Resume an interrupted run](cmux-planning/SKILL.md#status-and-context-recovery)

### cmux-issue-chain: implement and verify

Point it at a ready issue in a local tracker. Each worker stage starts fresh:

1. **Implement:** build the change, prove it with regression tests and an end-to-end run of the changed path.
2. **Simplify:** apply behavior-preserving refactorings.
3. **Orchestrator check:** rerun the tracker's canonical checks; a failing suite stops advancement.
4. **Review:** inspect the full diff and apply safe fixes within the issue's intent.
5. **Final test:** independently verify the result after the last code-changing stage. The tester does not edit product code.

Reviewers must respect documented decisions from earlier stages and passes of the same run, including refactorings deliberately left unapplied. Replacing those decisions requires recorded human approval. Fixing a regression while preserving the intended behavior remains allowed. A reviewer who disagrees with such a decision on quality grounds alone does not stop the chain: the earlier decision stands and the counter-proposal goes to triage.

Blockers, plan drift, and unresolved review findings stop the chain for human input. After the final test, recommendations are triaged; small accepted items that preserve behavior and stay inside the issue diff are applied in one follow-up pass (implement, then test) before the run completes, and other accepted items become new issues. A fresh triage worker decides recommendations autonomously by default; use `--human-triage` at init to decide them yourself. Successful completion leaves checked changes and a recorded commit proposal. In commit mode the orchestrator commits; otherwise the human commits. Push, PR, and CI remain human steps.

[Workflow, gates, and report contract](cmux-issue-chain/SKILL.md)

## Worker configuration

The shared configuration lives at `.scratch/orchestrator/agents.json`. These are the shipped assignments:

| Workflow | Role | Model / effort |
|---|---|---|
| Grilling | Repository research | Claude Opus / high |
| Grilling | Second repository opinion | GPT-6 Astra / high |
| Grilling | Official documentation | GPT-5.6 Luna / medium |
| Grilling | Web research | Claude Sonnet / medium |
| Planning | Specification and ticket authors | Claude Fable / high |
| Planning | Reviewer | GPT-6 Astra / high |
| Issue-chain | Implementer | GPT-6 Astra / xhigh |
| Issue-chain | Simplifier and reviewer | Claude Opus / high |
| Issue-chain | Final tester | GPT-6 Astra / high |

Claude model names are provider aliases. These assignments describe the shipped configuration, not guaranteed model access. Optional `--probe-profiles` checks make a minimal live provider request before workers launch.

Use the installed skill's `scripts/agents_config.py validate` and `show-resolved` commands to inspect configuration. Typed profile, CLI, model, effort, and executable overrides are supported; runtime safety policies remain code-owned. See the [configuration reference](cmux-issue-chain/SKILL.md#worker-profile-configuration) for commands, precedence, profiles, and probes.

### Upgrading an existing configuration

> **Coordinated upgrade required:** Upgrade `cmux-planning`, `cmux-grilling`, and `cmux-issue-chain` together before any shared configuration is migrated to schema v3. Older separately installed sibling skills cannot read the migrated schema-v3 shared configuration.

Upgrade all installed siblings together. Schema-v1 and schema-v2 migration requires a read-only preview and explicit human approval before running the displayed `agents_config.py migrate --accept` command. Validation never migrates configuration as a side effect. A schema-v3 file needs no migration question.

[Migration procedure and safeguards](cmux-issue-chain/SKILL.md#worker-profile-configuration)

## Visibility, checks, and run artifacts

Workers run in visible cmux panes. The launch command carries a start prompt instructing the worker to create its `started` marker as its first step. The watcher writes `worker.started` when it confirms that marker (or, for issue-chain and planning, a report arriving first); normal starts need no readiness assessment or separate delivery. Successful starts record `worker.launch_sent` and `worker.started` for every worker. Watcher exit 9 means start was not confirmed within the start window and requires the exception path: observe and assess the pane, resolve any dialog, and re-arm without automatically sending the assignment again. A fresh readiness assessment is also required after context recovery before any new input and before every `deliver`, including follow-ups, re-delivery, and grilling rounds. See the [worker readiness protocol](cmux-planning/references/worker-readiness.md).

Structured reports gate advancement, and Git snapshots support checks for unauthorized changes, including staged changes and commits. Coverage has limits, including ignored files and some untracked content; see the [integrity boundaries](cmux-planning/SKILL.md#ground-rules) for the exact scope. A clean report alone does not establish that a stage is safe to advance.

All three workflows store prompts, reports, events, snapshots, and task artifacts under `.scratch/orchestrator/runs/<run-id>/`. Run state records the workflow and its deliverables. Grilling results live beside the selected tracker or in `.scratch/grilling/`; planning publishes a tracker; issue-chain updates the selected issue. There is no automatic handoff between workflows.

Legacy run layouts remain inspectable read-only. Follow the relevant skill's recovery guidance before continuing an older run.

## Tokenverbrauch messen

`tools/orchestrator_usage.py` measures what the orchestrator itself spends, not the workers. It reads the local Claude Code and Codex transcripts, keeps the sessions that executed the selected workflow's scripts, and groups the medians by the skill commit that was live at the time:

```sh
python3 tools/orchestrator_usage.py --workflow issue-chain|planning|grilling --harness all --out <dir>
```

`--workflow` defaults to `issue-chain`. The tool writes `orchestrator-usage-sessions.csv` and `orchestrator-usage-runs.csv` to `<dir>` and prints one table per harness:

- `calls/stg`: orchestrator API calls per stage. A stage is a reported stage pass for issue-chain and planning, and a round for grilling. Grilling reports the session start (all calls before the first question) separately, below the table.
- `ctx/call`: average context size per call. Each call re-reads the whole context, so this drives cost.
- `tok/stage`: tokens per stage (context plus output, summed over the stage's calls).
- `wait%`: share of tokens spent waiting for workers (watchers, sleeps and the replies that follow them).
- `pane%`: share of tokens spent on the pane lifecycle (start, readiness, delivery, close).
- `start_ctx`: context size of the first call, that is, the fixed cost of the loaded skill and system prompt.

## Acknowledgments

These skills build in part on [Matt Pocock’s skills](https://github.com/mattpocock/skills). In particular, `cmux-grilling` adapts the questioning approach from [grill-me](https://github.com/mattpocock/skills/tree/main/skills/productivity/grill-me) into an autonomous research workflow with visible workers and a human decision review.

## License

[MIT](LICENSE)
