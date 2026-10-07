- `recap-draft` refuses an active run, including one waiting at an approval boundary. It writes
  `recap.md` with the facts from `state.json` and `events.jsonl`: status (complete, or halted at stage
  and decision), duration, the published tracker path with its issue count and ready frontier, the
  number of spec and ticket revisions, and for a completed run the next step: the issue chain with the
  first startable issue, ranked as in `cmux-issue-chain` (AFK before HITL, `in_progress` first, most
  transitively unblocked issues, lowest ID). A deviation from that default needs a startable issue and
  a `Reason:` line (German: `Begründung:`); `recap-show` enforces both. A prompt block follows with
  `/cmux-issue-chain <tracker> <issue-id>`; additions from the planning prompt are not carried over. It
  never overwrites an existing recap.
