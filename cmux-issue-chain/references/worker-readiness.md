# Interactive worker readiness

Apply this protocol to every harness worker (Codex, Claude Code, Pi) after every start,
after recovering context, and before every `deliver` (including follow-ups and grilling session/round prompts).
A successful `start-agent`, a live surface, provider preflight, or a visible prompt glyph
is not proof of readiness. Codex can display a composer while still loading, and Pi renders
its banner, skill list and composer frame before the session is usable.

## Observe, assess, then deliver

Use the same `--run-dir`, stable `--surface` UUID and worker selector on every command:
`--stage <stage> --pass <n>` for planning, `--role <role> --pass <n>` for issue-chain,
or `--lane <lane>` for grilling.

1. Run `pane_ctl.py start-agent` once. Read its output before issuing another command.
   Do not batch start and delivery in one shell/tool invocation.
2. Run `pane_ctl.py observe <worker arguments>`. Its JSON contains the current screen and
   an `observation_id`. Read the whole visible screen, including dialogs and errors.
3. Record your judgment with `pane_ctl.py assess <worker arguments>
   --observation <observation_id> --state <state> --reason "<concrete screen evidence>"`.
   Choose:
   - `loading`: initialization still in progress. Wait briefly (roughly 1–2 seconds), then
     observe again. Bound startup observation to 60 seconds; on expiry record `unknown`,
     report the blocking screen and stop delivery. Do not restart into an existing TUI.
   - `prompt`: a trust, onboarding, login, permission, update, or other dialog is pending.
     Handle the dialog below; never paste a work order into it.
   - `failed`: startup error, exited process, or return to the shell. Report the concrete
     failure and follow the skill's recovery rules; no automatic duplicate worker.
   - `unknown`: cannot confidently identify the application or its state. Inspect further
     or ask a targeted question; do not deliver.
   - `ready`: the expected harness and project are loaded, initialization is complete,
     the work composer is idle and empty, and no blocking dialog is active. Do not infer
     this from the absence of a known error or a single `>`/`›` character.
4. Only after `ready`, run `deliver` as a separate invocation. The script verifies the
   screen again and consumes this readiness before sending input. The comparison ignores only
   the observed Codex single-dot Braille background in the empty default composer; actual text,
   loading indicators, dialogs, warnings, paths and typed input still invalidate readiness when
   changed. Observations older than 60 seconds also require a fresh observe/assess cycle.
   Never batch observe, assess and send to outrun an animation. If another animation causes
   repeated mismatches, stop and report it rather than bypassing the inspection. Non-ready
   assessments can describe an animated observed frame; they never authorize delivery.
5. Inspect the post-delivery screen and confirm actual assignment execution before recording
   `worker.started` (planning: `mark-started`). A readiness assessment does not confirm work.
   An adopted grilling session contract means the lane is waiting for its round assignment.

## Respond to a dialog

Judge the actual dialog and existing task authorization. A known directory-trust question
for the exact project the user authorized may be confirmed within that authorization after
checking the displayed path. Trust may enable project-local config, hooks and execution policies;
do not extend it to an unexpected path or silently enable additional privileges. Login/account
choices, unknown dialogs, destructive choices, and permission expansions need targeted clarification
unless the session already authorizes the exact choice. Known optional notices can be dismissed
without changing the configured worker profile. Never blindly send Enter or a sequence of answers.

After assessing `prompt`, send one explicitly chosen key with:

```text
pane_ctl.py respond <worker arguments> --observation <observation_id> \
  --key <key> --reason "<identified dialog, chosen action, existing authorization>"
```

`respond` checks that the assessed screen is still current, invalidates readiness before input,
and prints a new observation. Read and assess that observation before any further key. If rendering
is still in progress, observe again. The allowed keys cover menu navigation and selection; do not
use `deliver --text` for dialog answers or route task text through raw CMUX input to bypass the gate.
Authentication that needs interactive secrets should be completed by the human in the pane.

## Recovery and audit

`worker.starting` invalidates earlier readiness before launch input; `worker.launch_sent` only
means the start command was submitted. `worker.observed` and `worker.startup_status` capture the
inspection and judgment; `worker.ready` permits one delivery. `worker.readiness_consumed` and
`worker.dialog_response` invalidate that permission. Each observation is tied to the launch and
surface, has a short expiry, and stores a screen digest rather than potentially sensitive screen text.

After context compaction or another interruption, always observe again before any new input,
even if an earlier status says ready. Existing launch events can be inspected, but old runs receive
no inferred readiness. Pane replacement, close, another start, a new observation, a dialog response,
or a delivery requires a new readiness assessment. An uncertain partially sent command is not a
reason to retry automatically: inspect the pane and follow the skill's blocker/recovery rules.
For already running assignments, preserve the existing report watcher and do not send a duplicate task.
