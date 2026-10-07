The dependency-free configuration CLI is `scripts/agents_config.py`. Run it from anywhere
inside the target Git repository; the default path is the repository root's
`.scratch/orchestrator/agents.json`:

```bash
python3 scripts/agents_config.py init
python3 scripts/agents_config.py validate
python3 scripts/agents_config.py show-resolved
python3 scripts/agents_config.py migrate
python3 scripts/agents_config.py migrate --accept
```

Use `--config <path>` after any command to select an explicit file, including outside Git,
or `--repo <path>` to resolve the default path from a specific target repository. `init`
atomically creates the complete shared defaults and never changes an existing file or the
repository's ignore rules. `validate` and `show-resolved` are local-only operations: they do
not launch workers or contact Claude Code, Codex, or any provider. They are read-only and stop
on schema v1 or v2 with the exact preview and acceptance commands; run initialization does the same
before publishing a launch wave.

Treat configuration creation as a first-use human checkpoint, separate from run initialization.
Before starting any worker-bearing run, resolve the selected configuration path and follow this
protocol. Never offer profile overrides the human did not ask for.

1. If the file already exists at schema v1 or v2, run `agents_config.py migrate` without `--accept`.
   Present its coordinated-upgrade warning and complete validated preview in the human's language,
   including every resolved workflow assignment. When `claude-fable-high` is unavailable, call out
   the displayed fallback profile name, harness, model, and effort without inferring relative quality.
   Also call out every added required assignment the preview names, such as `issue-chain.triage`.
   Ask whether to accept exactly that proposal. On refusal or interruption, make no further tool call.
   On confirmation, invoke the preview's exact `agents_config.py migrate --accept` command, digest
   argument included, then validate and continue.
2. If the file already exists and is valid schema v3, continue with its assignments.
   A schema-v3 file needs no migration question.
   An existing valid schema-v3 file needs no start confirmation either; the start question
   belongs only to a newly created default (accepted with the **Yes, start now** answer).
3. If it is missing, run `agents_config.py init` for that exact default or explicit path, then run
   `show-resolved`. Do not call `run_state.py init` yet.
4. Present the created path and all three workflows' resolved assignments, because the file is shared.
   Ask one single-select question in the human's language: whether to start the current run with
   these assignments. The choices mean **Yes, start now** and **No, I will edit the file**.
5. Use the host's native structured-input tool when it is available: `AskUserQuestion` in Claude
   Code or `request_user_input` in Codex. Do not assume Codex exposes it in the current mode; when
   no native tool is available, ask the same question in chat and end the turn for the answer.
6. On yes, reload and validate the current bytes before starting the run. On no, perform no more
   tool calls, tell the human to edit the file and reply when it is ready, and end the turn. When
   they return, validate and show the resolved assignments again; start only after validation
   succeeds. Report validation errors and remain stopped when it fails.

This checkpoint belongs to the interactive orchestrator, never to a worker pane or subagent. Do
not emulate it with shell input, a sleeping process, or polling while the human edits the file.

The sixteen shipped profiles are `claude-fable-high` and `claude-fable-medium` (`claude-code`,
`claude`, `fable`); `claude-opus-high` and `claude-opus-medium` (`claude-code`, `claude`, `opus`);
`claude-sonnet-high` and `claude-sonnet-medium` (`claude-code`, `claude`, `sonnet`);
`codex-astra-high` and `codex-astra-medium` (`codex`, `codex`, `gpt-6-astra`);
`codex-sol-high` and `codex-sol-medium` (`codex`, `codex`, `gpt-6.1-sol`);
`pi-gemini-pro-high` and `pi-gemini-pro-medium` (`pi`, `pi`, `google/gemini-3.1-pro-preview`);
`pi-glm-high` and `pi-glm-medium` (`pi`, `pi`, `openrouter/z-ai/glm-5.3`); and `pi-grok-high`
and `pi-grok-medium` (`pi`, `pi`, `xai/grok-4.7`). Each tuple lists
harness, executable, and model; the profile suffix specifies effort. No workflow assigns a Pi
profile by default; Pi is opted into per run or per tracker config. Grilling assigns Opus/high, Sol/high, Sol/medium, and Sonnet/medium to
`codebase`, `codebase2`, `docs`, and `web`, respectively. The `fable`, `opus`, and `sonnet`
strings are intentionally moving provider aliases; deterministic selection of an alias does not
pin the provider's underlying model version.

Configuration is strict and user-owned after its create-only bootstrap. Schema-v1 and schema-v2 reads never migrate.
The read-only `migrate` preview validates the complete schema-v3 candidate before displaying it;
`migrate --accept` is the only shared-CLI path that atomically replaces the file. Existing profiles and
assignments are preserved. From schema v1, planning roles are selected deterministically and a
collision-safe Codex reviewer is added only when needed. A missing `issue-chain.triage` is assigned
`claude-opus-high`, copied from the defaults when the file lacks that profile. The original bytes remain
untouched if validation or publication fails. Migration refuses a resolved target with no write bit or more than one hard link. A symlink is
preserved and those same guards apply to its intended target.
The output-stream contract is stable: standalone read-only `migrate` writes the complete migration
guidance once on stdout, while stderr contains only its short refusal and never repeats either command.
For a schema-v1 or schema-v2 refusal, planning initialization leaves stdout empty and writes one complete actionable
guidance block on stderr, with the candidate digest and exact preview and acceptance commands once each.
Unknown fields, versions,
harnesses, efforts, assignments, or profile references fail rather than falling back. Model
strings are syntax-checked, not looked up in a stale catalog, so local validation cannot prove
provider or model entitlement. `show-resolved` is the inspection command for the complete
profiles, assignments, sources, models, and efforts. A Pi model must name its provider
(`provider/id`, such as `openrouter/z-ai/glm-5.3`), because Pi has no provider-wide auth status and
its preflight check is scoped to the model it is given. Hermes remains an explicit unsupported
entry in the code-owned adapter registry; that registry — rather than JSON — is the implementation
boundary for adding future harnesses. It lives in `scripts/agents_config.py` together with the
preflight rules, the launch and probe adapters, and the override parsing and profile resolution
all workflows share, so a harness is added in that one file; each workflow keeps its own
sandbox, approval, and network policy.

