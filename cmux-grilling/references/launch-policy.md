The default wave sends:

```bash
CMUX_AGENT_MANAGED_SUBAGENT=1 claude \
  --model opus --effort high \
  --permission-mode auto                                   # codebase
CMUX_AGENT_MANAGED_SUBAGENT=1 codex -s workspace-write \
  --ask-for-approval on-request \
  -c approvals_reviewer=auto_review \
  -c check_for_update_on_startup=false \
  -c tui.animations=false \
  -c tui.disable_paste_burst=true \
  --model gpt-6.1-sol \
  -c model_reasoning_effort=high                          # codebase2
CMUX_AGENT_MANAGED_SUBAGENT=1 codex -s workspace-write \
  -c sandbox_workspace_write.network_access=true \
  --ask-for-approval on-request \
  -c approvals_reviewer=auto_review \
  -c check_for_update_on_startup=false \
  -c tui.animations=false \
  -c tui.disable_paste_burst=true \
  --model gpt-6.1-sol \
  -c model_reasoning_effort=medium                         # docs
CMUX_AGENT_MANAGED_SUBAGENT=1 claude \
  --model sonnet --effort medium \
  --permission-mode auto                                   # web
```

`CMUX_AGENT_MANAGED_SUBAGENT=1` marks the pane as a managed subagent, which is what cmux
keys its notification suppression on. Without it a session fires a desktop banner with sound
for every turn end, idle reminder and approval prompt across four lanes, and the human ends
up muting cmux entirely. The lane still appears in the Feed and in `surface-health`; only the
banners are gone. Suppression follows `automation.suppressSubagentNotifications` (on by
default), and the variable is a cmux internal, so the failure mode is noise, never a
broken run.

Use plain `claude` / `codex`, not `cmux claude-teams` / `cmux codex-teams`. The teams
wrappers open lane-spawned subagents as extra cmux panes, and those splits anchor to the
focused workspace instead of the lane's workspace — while the human works in another
workspace, subagent panes land there. Plain launches keep subagents internal to the lane's
Claude Code process. Every interactive Claude lane starts in `auto` permission mode; the safe,
tool-disabled live provider probe remains in `plan` mode.
own TUI; the lane pane stays the visible unit, and cmux pane integration (hooks,
notifications, `surface-health`) comes from the per-pane CLI shims, so it is unaffected.

The configured harness, executable, model, and effort come from the wave. Codebase,
codebase2, and docs accept Claude Code or Codex; web remains Claude Code-only because that
is the existing tested network policy. The Codex flags are fixed lane policy; do not ask the
human for startup options at session start. Each flag earns its place:

- `-s workspace-write` lets a Codex lane write its draft and report handoff files without a per-write
  confirmation (in the first pilot, a lane stuck at that prompt cost most of a round).
- `--ask-for-approval on-request` pins the escalation policy explicitly: the lane runs
  sandboxed and requests approval only when the sandbox blocks something.
- `approvals_reviewer=auto_review` routes those approval requests to Codex's automated
  reviewer agent instead of a human prompt, so an unattended lane does not stall at the
  sandbox boundary. It is a reviewer swap, not a permission grant.
- `check_for_update_on_startup=false` suppresses the startup update prompt, which otherwise
  blocks an unattended lane before it reads its task. Set it only here, so interactive Codex
  sessions still get update notices.
- `tui.animations=false` disables decorative motion on the welcome screen, shimmer, and spinner, so
  the lane screen that readiness checks and `observe` read stays stable.
- `tui.disable_paste_burst=true` disables Enter suppression after a typed burst, so exception-path
  `deliver` submits text with a single Enter.

Which lanes may reach the network is declared by `launch_wave.CODEX_NETWORK_LANES`. Only a
Codex docs lane receives `sandbox_workspace_write.network_access=true`, preserving its
documentation access; the web lane is Claude Code-only and has no sandbox to grant. Codebase and
codebase2 remain no-web lanes, and no grilling lane
receives `writable_roots`; those container grants belong to `cmux-issue-chain` workers. The
launch command is stored as an argument vector in the wave and converted to shell text with
safe quoting by `pane_ctl.py start-agent`; its `worker.launch_sent` event records the wave id,
argument vector, resolved executable, and detected version. With
`approvals_reviewer=auto_review` a Codex lane decides its
own escalations, so it does not stop at a human approval prompt; a lane that looks idle is
either working or done, and only its report file settles which.

