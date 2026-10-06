## Prerequisites and installation

Install the skill into an agent that can run Python 3 and Git in the target repository. Visible worker
operation additionally requires cmux, Claude Code for the default author profiles, and Codex CLI
for the default reviewer profile. Offline tests use fake harnesses and fake CMUX and contact no
model provider.

Use the skills CLI from this repository or copy the complete `cmux-planning` directory into the agent's
skills directory. Upgrade installed siblings together before accepting schema migration. Runtime is
standalone: a direct task needs neither sibling, and vendored contracts validate optional grilling input
and the native tracker without locating another skill installation.

On first use, let `planning_state.py init` create or preview the shared configuration. For a newly
created schema-v3 default, inspect `planning.spec`, `planning.tickets`, and `planning.reviewer`,
then rerun with `--accept-config`. For schema v1 or v2, run the shared read-only preview, obtain explicit
confirmation, run `agents_config.py migrate --accept`, and only then rerun
`planning_state.py init`.

