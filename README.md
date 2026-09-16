# cmux Orchestration Skills

Three [Agent Skills](https://agentskills.io) that turn an AI coding agent into an orchestrator for multi-agent workflows running in visible [cmux](https://github.com/manaflow-ai/cmux) terminal panes:

- **`cmux-grilling`**: autonomously stress-tests a plan by asking decision-level questions and answering them through four parallel research lanes, producing reviewed assumptions instead of guesses.
- **`cmux-planning`**: turns a task or optional human-revalidated grilling result into an approved repository-grounded specification and an independently reviewed native issue tracker.
- **`cmux-issue-chain`**: runs issues from a local Markdown issue tracker through a gated implement → simplify → review → test worker chain, fully AFK.

All three skills follow the same philosophy: the orchestrating agent coordinates and judges, but never edits product code itself and never hides work in background subagents. Every worker runs in a visible cmux pane you can watch and intervene in.

They form an optional progression, not a mandatory pipeline:

```text
optional decision research       planning synthesis and review       issue execution
cmux-grilling               ->   cmux-planning                  ->   cmux-issue-chain
```

Start at planning when the task is already clear, execute an existing tracker without planning, or use
grilling alone when only the decision stress-test is needed. No workflow automatically invokes another.

## Requirements

These skills are only useful if you have the full stack below. Check this list first.

- **[cmux](https://github.com/manaflow-ai/cmux)**: an open-source, Ghostty-based macOS terminal built for AI coding agents. The skills drive it via its CLI/socket interface to launch and monitor worker panes. macOS only.
- **[Claude Code](https://claude.com/claude-code)**: runs the orchestrator and several worker roles. The built-in `/simplify` and `/code-review` commands are used by `cmux-issue-chain`, and skill support is needed to load the skills themselves.
- **[Codex CLI](https://developers.openai.com/codex/cli)**: runs the implementer/tester roles (`cmux-issue-chain`), the second-opinion research lane (`cmux-grilling`), and the mandatory independent reviewer (`cmux-planning`).
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
4. **Review** (Claude Code, `/code-review medium --fix`): reviews the full diff and fixes must-fix findings itself, within a strict intent boundary: findings that challenge documented issue decisions are relayed to the human instead of silently "fixed".
5. **Final test** (Codex by default): the only check after the last code-changing stage; reviewers never accept their own fixes.

Between stages, structured worker reports are parsed and gated: blockers, plan drift, and human-in-the-loop issues stop the chain instead of being papered over. All lifecycle state (run logs, gate decisions, snapshots, prompts, reports) is written to an auditable run directory. The orchestrator itself never touches product code.

### cmux-planning

The planning bridge between optional grilling and issue execution. It persists one task, imports and
explicitly revalidates an optional grilling JSON/Markdown pair, and runs a fresh specification author
followed by an independent Codex review. After explicit spec approval, a fresh tickets author creates a
small set of cohesive qualitative fresh-context vertical slices and another fresh Codex reviewer checks
them. Workers synthesize persisted context and inspect the repository; they do not interview the user.
Safe `pass_with_fixes` corrections go through deterministic validation and a human-visible diff, not an
automatic model re-review. Product, scope, architecture, ticket-boundary, or dependency decisions block
for human input.

Strict report and digest validation plus complete before/after Git-visible working-tree inspection
prevent a clean report from hiding tracked changes, staged changes, untracked paths and their content
(regular files up to the 8 MiB size cap and symlink target bytes), or commits (HEAD movement). That
boundary excludes ignored files and skipped untracked content (files above the size cap or unsupported
types). Likewise,
structural and digest checks on optional grilling input prove integrity, not freshness; explicit human
revalidation is the freshness policy.

After ticket approval, planning stages and validates a native tracker and publishes it with one
collision-safe atomic move. Public status, context, and resume commands recover interrupted grilling,
author, reviewer, approval, and publication stages without duplicating workers, decisions, or targets.
Recorded approvals remain bound to artifact digests, and completed runs never block a new planning
session.

## Deterministic Worker Profiles

> **Coordinated upgrade required:** Upgrade `cmux-planning`, `cmux-grilling`, and `cmux-issue-chain` together before any shared configuration is migrated to schema v2. Older separately installed sibling skills cannot read the migrated schema-v2 shared configuration.

Each skill independently ships the same dependency-free `scripts/agents_config.py` CLI and
default profile contract; installing only one skill does not depend on the sibling directory or
repository-only Python modules. From a target Git repository, `init` atomically creates
`.scratch/orchestrator/agents.json` once, `validate` performs strict local validation, and
`show-resolved` displays the effective profiles and assignments. An explicit `--config <path>`
works outside Git, while `--repo <path>` anchors default discovery to that repository's Git root.
Create-only `init` never overwrites an existing file. `validate`, `show-resolved`, and orchestration
preparation are read-only: a schema-v1 file makes them stop with the exact preview and acceptance
commands instead of migrating as a side effect. Run `agents_config.py migrate [--config <path>]` to
display the coordinated-upgrade warning, the validated complete schema-v2 candidate, all resolved
workflow assignments, and the candidate digest without changing the file. After explicit human
approval, `agents_config.py migrate --accept [--config <path>]` is the only shared-CLI mutation path.
The displayed acceptance command carries that candidate's digest as `--expect-sha256`, so a file edited
between preview and acceptance is refused instead of migrated to a candidate nobody approved.
The output-stream contract is stable: standalone read-only `migrate` writes the complete migration
guidance once on stdout, while stderr contains only its short refusal and never repeats either command.
For a schema-v1 refusal, planning initialization leaves stdout empty and writes one complete actionable
guidance block on stderr, with the candidate digest and exact preview and acceptance commands once each.

Accepted migration preserves existing profiles and assignments, deterministically selects planning
authors, requires a Codex reviewer (adding a collision-safe default only when necessary), validates the
complete candidate before atomic replacement, and leaves original bytes untouched on failure. If
`claude-fable-high` is unavailable, the preview identifies that fact and shows the lexicographically
first compatible fallback's profile name, harness, model, and effort without inferring relative quality.
A target with no write bit or more than one hard link is refused even when its parent is writable.
Symlink paths remain symlinks: migration resolves the intended target and applies the same write-bit and
hard-link guards there.

Configuration creation is a first-use human checkpoint, not part of run initialization. When the
selected file is missing, the interactive orchestrator creates it with `agents_config.py init`,
shows all three workflows' resolved assignments, and asks whether to start with them or pause for edits.
When any workflow checkpoint finds schema v1, it presents the shared CLI's read-only preview in the
human's language and asks for explicit confirmation. On approval it invokes the same
`agents_config.py migrate --accept` operation, then reloads and validates the current bytes before
starting. Refusal or interruption leaves the file and run state untouched.
`planning_state.py --accept-config` remains only the acceptance mechanism for a newly created
schema-v2 default; it never authorizes schema migration.
Claude Code and Codex use their native structured-input tool when available and fall back to a
normal chat question otherwise. A negative answer ends the turn without a run or worker snapshot;
after the human returns, the current file is validated before work starts. Direct calls to
`run_state.py init` require an existing configuration and never silently bootstrap one.

The ten default profiles provide Claude Fable at high and medium effort, Opus at high, medium,
and xhigh effort, Sonnet/medium, Codex GPT-6 Astra at high, medium, and xhigh effort, and
GPT-5.6 Luna/medium. Issue-chain assigns Astra/xhigh to `implement`, Opus/high to `simplify`
and `review`, and Astra/high to `test`. Grilling assigns Opus/high, Astra/high, Luna/medium,
and Sonnet/medium to `codebase`, `codebase2`, `docs`, and `web`. Planning assigns Fable/high
to `spec` and `tickets` and Astra/high to its mandatory Codex `reviewer`. Claude's `fable`,
`opus`, and `sonnet` names are moving provider aliases; selecting an alias does not pin the
provider's underlying model version. Syntax-validating a local model string does not prove that
the authenticated provider account is entitled to use it. Pi and Hermes are explicitly unsupported;
their registry entries mark the code-owned adapter boundary for future support.

Every interactive Claude worker is launched with `--permission-mode auto`, including roles switched
to Claude through typed overrides. The tool-disabled live provider probe remains isolated in `plan`
mode and the version, help, and authentication preflight calls remain non-interactive diagnostics.

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

All three workflows share the flat `.scratch/orchestrator/runs/<run-id>/` root. Default UTC ids are
`grill-<slug>-<YYYY-MM-DD>-<HHMM>`, `plan-<slug>-<YYYY-MM-DD>-<HHMM>`, and
`chain-issue-NNN-<YYYY-MM-DD>-<HHMM>`; task slugs contain at most 30 characters and can be overridden
with `--slug` in grilling and planning. Each state records its `workflow`, `layout_version: 1`, and
`deliverables`: the grilling Markdown/JSON pair, published planning tracker, or chain tracker/issue.
Legacy runs (including `.scratch/orchestrator/planning-runs/`) stay inspectable read-only and must be
restarted or, for planning, handled through a separately reviewed migration procedure.
