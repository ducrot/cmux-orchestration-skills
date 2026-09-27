# Worker start and interactive readiness

## Normal start

For every harness worker (Codex, Claude Code, Pi), `pane_ctl.py start-agent` attaches the
start prompt to the launch command. The worker's first step is to create the assignment's
`started` marker at the path in its rendered prompt. Normal start needs no readiness assessment
or separate `deliver`: read the launch output and arm the skill's watcher.

`worker.launch_sent` records the launch and assignment identity; it alone does not prove that
work began. On a fresh marker for the current launch, the watcher writes `worker.started`
without a screen judgment. Issue-chain and planning also accept a report arriving
first and continue watching for the report after start confirmation. Grilling uses
`await_reports.py --session` to confirm all lane session markers; session adoption means the lane
is waiting for its round assignment, not that a round report is complete.

The start window defaults to five minutes (`--start-minutes 5`). Watcher exit 9 means assignment
start was not confirmed within that window; use the exception path below. Do not send a duplicate
assignment or restart merely because a marker is missing. Normal successful launches have
`worker.launch_sent` and `worker.started` for every worker, without readiness or delivery events.

## When readiness is required

Apply the interactive protocol after a watcher exit 9, after context recovery before any new input,
and before every `deliver` (follow-ups, re-delivery, and grilling rounds, including session re-delivery).
A successful `start-agent`, a live surface, provider preflight, or a visible prompt glyph
is not proof of readiness for new input. Codex can display a composer while still loading, and
Pi renders its banner, skill list and composer frame before the session is usable.

After exit 9, observe and assess the current launch before choosing an action:

- A dialog: use `respond` as described below, then re-arm the watcher without re-delivery;
  the assignment is already attached to the launch. Resolve further dialogs individually.
- Failed startup: stop and follow the skill's blocker/recovery rules.
- Confirmed idle or summarized-and-waiting assignment, unsent delivery line, or no adopted
  grilling session: use one readiness-gated re-delivery of the same prompt, then re-arm the
  watcher. Follow the skill's prompt and baseline requirements; a missing marker alone does
  not authorize re-delivery.
- Visibly working, or an adopted grilling session: confirm `worker.started` with screen evidence
  using the skill's exception procedure (planning: `mark-started`), then re-arm the watcher.

Preserve the current launch identity when re-arming and follow the skill's deadline rules.
Screen-based start confirmation is reserved for this exception path.

## Observe, assess, then deliver

Use the same `--run-dir`, stable `--surface` UUID and worker selector on every command:
`--stage <stage> --pass <n>` for planning, `--role <role> --pass <n>` for issue-chain,
or `--lane <lane>` for grilling.

1. Run `pane_ctl.py observe <worker arguments>`. Its JSON contains the current screen and
   an `observation_id`. Read the whole visible screen, including dialogs and errors.
2. Record your judgment with `pane_ctl.py assess <worker arguments>
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
3. Only after `ready`, run `deliver` as a separate invocation. The script verifies the
   screen again and consumes this readiness before sending input. The comparison ignores only
   the observed Codex single-dot Braille background in the empty default composer; actual text,
   loading indicators, dialogs, warnings, paths and typed input still invalidate readiness when
   changed. Observations older than 60 seconds also require a fresh observe/assess cycle.
   Never batch observe, assess and send to outrun an animation. If another animation causes
   repeated mismatches, stop and report it rather than bypassing the inspection. Non-ready
   assessments can describe an animated observed frame; they never authorize delivery.
4. After exception-path re-delivery, re-arm the watcher to confirm the marker or report.
   A readiness assessment does not confirm work. For screen-based start confirmation, follow
   the exception procedure above. Follow-ups and grilling rounds keep the existing launch
   confirmation and use the skill's report watcher; they do not need another `worker.started`.

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
means the start command with its attached prompt was submitted. `worker.started` confirms
assignment execution from marker or report evidence on the normal path, or screen evidence on
the exception path. `worker.observed` and `worker.startup_status` capture the
inspection and judgment; `worker.ready` permits one delivery. `worker.readiness_consumed` and
`worker.dialog_response` invalidate that permission. Each observation is tied to the launch and
surface, has a short expiry, and stores a screen digest rather than potentially sensitive screen text.

After context compaction or another interruption, always observe again before any new input,
even if an earlier status says ready. Existing launch events can be inspected, but old runs receive
no inferred readiness. Pane replacement, close, another start, a new observation, a dialog response,
or a delivery invalidates earlier readiness; assess afresh before further interactive input.
An uncertain partially sent command is not a reason to retry automatically: inspect the pane and
follow the skill's blocker/recovery rules.
For already running assignments, preserve the existing report watcher and do not send a duplicate task.
