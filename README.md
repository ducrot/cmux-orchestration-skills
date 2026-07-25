# cmux Orchestration Skills

Two [Agent Skills](https://agentskills.io) that turn an AI coding agent into an orchestrator for multi-agent workflows running in visible [cmux](https://github.com/manaflow-ai/cmux) terminal panes:

- **`cmux-grilling`**: autonomously stress-tests a plan by asking decision-level questions and answering them through four parallel research lanes, producing reviewed assumptions instead of guesses.
- **`cmux-issue-chain`**: runs issues from a local Markdown issue tracker through a gated implement → simplify → review → test worker chain, fully AFK.

Both skills follow the same philosophy: the orchestrating agent coordinates and judges, but never edits product code itself and never hides work in background subagents. Every worker runs in a visible cmux pane you can watch and intervene in.

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

The result is a reviewed set of assumptions grounded in your actual repository and current documentation, produced while you were away, with every research step visible and auditable. For interactive grilling where a human answers the questions, use a separate interactive grilling skill; it is not bundled here.

### cmux-issue-chain

An orchestrator for working through a local Markdown issue tracker while you are AFK. You point it at an issue; it runs a gated chain of fresh worker panes:

1. **Implement** (Codex): builds the change, anchored by regression tests that fail without it and an end-to-end run of the changed path.
2. **Simplify** (Claude Code, `/simplify`): applies behavior-preserving refactorings to the diff.
3. **Orchestrator check**: re-runs the tracker's canonical check commands itself; a red suite stops the chain regardless of what reports claim.
4. **Review** (Claude Code, `/code-review max --fix`): reviews the full diff and fixes must-fix findings itself, within a strict intent boundary: findings that challenge documented issue decisions are relayed to the human instead of silently "fixed".
5. **Final test** (Codex): the only check after the last code-changing stage; reviewers never accept their own fixes.

Between stages, structured worker reports are parsed and gated: blockers, plan drift, and human-in-the-loop issues stop the chain instead of being papered over. All lifecycle state (run logs, gate decisions, snapshots, prompts, reports) is written to an auditable run directory. The orchestrator itself never touches product code.

## Installation

Install with the [skills CLI](https://vercel.com/docs/agent-resources/skills), which supports Claude Code, Codex, and many other agents:

```bash
npx skills add ducrot/cmux-orchestration-skills
```

To install a single skill:

```bash
npx skills add ducrot/cmux-orchestration-skills --skill cmux-issue-chain
```

Manual alternative: clone the repo and copy or symlink the two skill directories into your agent's skills directory (e.g. `~/.claude/skills/` for Claude Code, `~/.codex/skills/` for Codex, or a project-level `.claude/skills/`).

All paths inside the skills are relative to each skill's own directory, so any install location works.

## License

[MIT](LICENSE)
