# cmux Orchestration Skills

Three [Agent Skills](https://agentskills.io) that turn an AI coding agent into an orchestrator for multi-agent workflows running in visible [cmux](https://github.com/manaflow-ai/cmux) terminal panes:

- **`cmux-grilling`**: autonomously stress-tests a plan by asking decision-level questions and answering them through four parallel research lanes, producing reviewed assumptions instead of guesses.
- **`cmux-planning`**: turns a task or optional human-revalidated grilling result into a repository-grounded specification, independently reviews it in a fresh Codex pane, and pauses for explicit approval before ticket decomposition.
- **`cmux-issue-chain`**: runs issues from a local Markdown issue tracker through a gated implement → simplify → review → test worker chain, fully AFK.

All three skills follow the same philosophy: the orchestrating agent coordinates and judges, but never edits product code itself and never hides work in background subagents. Every worker runs in a visible cmux pane you can watch and intervene in.

## Requirements

These skills are only useful if you have the full stack below. Check this list first.

- **[cmux](https://github.com/manaflow-ai/cmux)**: an open-source, Ghostty-based macOS terminal built for AI coding agents. The skills drive it via its CLI/socket interface to launch and monitor worker panes. macOS only.
- **[Claude Code](https://claude.com/claude-code)**: runs the orchestrator and several worker roles. The built-in `/simplify` and `/code-review` commands are used by `cmux-issue-chain`, and skill support is needed to load the skills themselves.
- **[Codex CLI](https://developers.openai.com/codex/cli)**: runs the implementer/tester roles (`cmux-issue-chain`) and the second-opinion research lane (`cmux-grilling`).
- **Python 3**: the bundled orchestration scripts (prompt rendering, report parsing, gate watching, run state) use only the standard library; no packages to install.

**A note on billing:** as of publication, both CLIs are covered by their regular subscriptions: Claude Code by Claude Pro/Max and Codex CLI by ChatGPT Plus/Pro. Agentic CLI usage of this kind is included in those plans, so no API key and no per-token billing is required.

## The Skills

### cmux-grilling

An autonomous version of "grill me about this plan before I build it". You hand it a plan, a task plus its already-fixed constraints, and it runs rounds of questioning without asking you anything:

1. A **griller** step formulates one decision-level question per round: a question whose answer changes what would be built.
2. Four persistent **research lanes** answer it in parallel, each in its own visible pane: repo research with Claude Code, independent second-opinion repo research with Codex, official-docs research, and web research.
3. A **synthesizer** consolidates the four gate-parsed reports into an answer with confidence and sources.
4. After the question budget is spent, the session distills everything into **defined assumptions**, written as a Markdown + JSON artifact pair for human review.

The result is a reviewed set of assumptions grounded in your actual repository and current documentation, produced while you were away, with every research step visible and auditable. The grilling prompt is based on [grill-me](https://github.com/mattpocock/skills/tree/main/skills/productivity/grill-me) by Matt Pocock. For interactive grilling where a human answers the questions, use a separate interactive grilling skill; it is not bundled here.

### cmux-issue-chain

An orchestrator for working through a local Markdown issue tracker while you are AFK. You point it at an issue; it runs a gated chain of fresh worker panes:

1. **Implement** (Codex by default): builds the change, anchored by regression tests that fail without it and an end-to-end run of the changed path.
2. **Simplify** (Claude Code, `/simplify`): applies behavior-preserving refactorings to the diff.
3. **Orchestrator check**: re-runs the tracker's canonical check commands itself; a red suite stops the chain regardless of what reports claim.
4. **Review** (Claude Code, `/code-review max --fix`): reviews the full diff and fixes must-fix findings itself, within a strict intent boundary: findings that challenge documented issue decisions are relayed to the human instead of silently "fixed".
5. **Final test** (Codex by default): the only check after the last code-changing stage; reviewers never accept their own fixes.

Between stages, structured worker reports are parsed and gated: blockers, plan drift, and human-in-the-loop issues stop the chain instead of being papered over. All lifecycle state (run logs, gate decisions, snapshots, prompts, reports) is written to an auditable run directory. The orchestrator itself never touches product code.

### cmux-planning

The planning bridge between optional grilling and issue execution. It persists one task, imports and
explicitly revalidates an optional grilling JSON/Markdown pair, and runs a fresh specification author
followed by an independent Codex review. Strict report and digest validation plus complete before/after
Git-visible working-tree inspection prevent a clean report from hiding unauthorized product changes.
The human sees the reviewed candidate, corrections, assumptions, decisions, and proposed test seams
before explicitly approving or requesting a fresh author-and-review pass.

The first vertical slice currently ends at the approved-specification `tickets` boundary; native ticket
decomposition and publication are added by the subsequent planning slices.

## Deterministic Worker Profiles

> **Coordinated upgrade required:** Upgrade `cmux-planning`, `cmux-grilling`, and `cmux-issue-chain` together before any shared configuration is migrated to schema v2. Older separately installed sibling skills cannot read the migrated schema-v2 shared configuration.

Each skill independently ships the same dependency-free `scripts/agents_config.py` CLI and
default profile contract; installing only one skill does not depend on the sibling directory or
repository-only Python modules. From a target Git repository, `init` atomically creates
`.scratch/orchestrator/agents.json` once, `validate` performs strict local validation, and
`show-resolved` displays the effective profiles and assignments. An explicit `--config <path>`
works outside Git, while `--repo <path>` anchors default discovery to that repository's Git root.
Create-only `init` never overwrites an existing file. Every CLI recognizes an otherwise valid schema-v1
file and atomically migrates it to schema v2 before current required-workflow validation. Migration
preserves existing profiles and assignments, deterministically selects planning authors, requires a
Codex reviewer (adding a collision-safe default only when necessary), validates the complete candidate
before replacement, and leaves original bytes untouched on failure.

Configuration creation is a first-use human checkpoint, not part of run initialization. When the
selected file is missing, the interactive orchestrator creates it with `agents_config.py init`,
shows all three workflows' resolved assignments, and asks whether to start with them or pause for edits.
When `cmux-planning` **initializes a run** and finds schema v1, it previews the validated schema-v2
assignments and the compatibility warning without changing the file; only an explicit acceptance rerun
performs migration. That checkpoint covers `planning_state.py init` alone. Every other command in every
skill that loads the configuration — including `validate` and `show-resolved` — migrates a schema-v1
file as a side effect of reading it, reporting the migration on stderr.
Claude Code and Codex use their native structured-input tool when available and fall back to a
normal chat question otherwise. A negative answer ends the turn without a run or worker snapshot;
after the human returns, the current file is validated before work starts. Direct calls to
`run_state.py init` require an existing configuration and never silently bootstrap one.

The defaults provide Claude Opus at medium and xhigh effort, Sonnet/medium, Codex GPT-5.6 Sol at
medium and xhigh effort, and Luna/medium. Issue-chain assigns Sol/xhigh to implement/test and
Opus/xhigh to simplify/review. Grilling assigns Opus/xhigh, Sol/xhigh, Luna/medium, and
Sonnet/medium to `codebase`, `codebase2`, `docs`, and `web`. Planning assigns Opus/xhigh to `spec`
and `tickets` and Codex Sol/xhigh to its mandatory Codex `reviewer`. Claude's `opus` and `sonnet` names are
intentionally moving aliases; syntax-validating any local model string does not prove that the
authenticated provider account is entitled to use it. Pi and Hermes are explicitly unsupported;
their registry entries mark the code-owned adapter boundary for future support.

All workflows accept repeatable typed `--profile`, `--harness`, `--model`, `--effort`, and
`--executable` overrides. Precedence is file assignment, then profile override, then direct field
overrides. Issue-chain reloads and fully revalidates the pinned source for each fresh stage;
grilling freezes all four persistent lanes in one immutable launch wave, and planning reloads the
pinned source for each fresh author or review stage. Before any pane exists,
mandatory local preflight checks executable discovery, version, CLI capabilities, and local auth.

Live provider verification is opt-in: pass `--probe-profiles` to issue-chain or planning stage
preparation, or grilling `init`, optionally with the CLI-only `--probe-timeout <seconds>` (default 120). Each unique
assigned and resolved profile receives one minimal request; duplicate assignments are deduplicated
and unused profiles are skipped. The probe disables Claude tools or gives Codex a read-only sandbox,
requires an exact fixed sentinel, and fails before pane creation on provider errors, timeouts,
malformed output, or a missing sentinel. Snapshots audit configuration source/hash, typed overrides,
resolved profiles, executable/version/preflight data, final argv, entitlement, and probe outcome and
timing; provider output, credentials, and ambient environment values are not stored. Without probes,
entitlement remains `unverified`; successful probes record `verified`.

Safety policy is code-owned. Configuration cannot add free-form arguments, environment values,
capabilities, sandbox/approval/network/writable-root settings, or other runtime safety overrides.

## Installation

Install with the [skills CLI](https://vercel.com/docs/agent-resources/skills), which supports Claude Code, Codex, and many other agents:

```bash
npx skills add ducrot/cmux-orchestration-skills
```

To install a single skill:

```bash
npx skills add ducrot/cmux-orchestration-skills --skill cmux-issue-chain
```

A single-skill installation remains supported, but a partial upgrade beside older sibling copies is
not: upgrade every installed sibling together before allowing any of them to migrate the shared file.

Manual alternative: clone the repo and copy or symlink the three skill directories into your agent's skills directory (e.g. `~/.claude/skills/` for Claude Code, `~/.codex/skills/` for Codex, or a project-level `.claude/skills/`).

All paths inside the skills are relative to each skill's own directory, so any install location works.

## License

[MIT](LICENSE)
