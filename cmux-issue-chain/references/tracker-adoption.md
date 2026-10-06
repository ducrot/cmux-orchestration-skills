### Adopting a `to-tickets` tracker

Tickets written by `to-tickets` carry no frontmatter, so the preflight rejects them until they are adopted.
`adopt_tracker.py` converts them in place — filenames stay untouched, so `to-tickets` and `/implement` keep
finding their tickets by the paths they expect:

```bash
python3 scripts/adopt_tracker.py --tracker .scratch/<tracker> --dry-run
python3 scripts/adopt_tracker.py --tracker .scratch/<tracker> \
  --branch feature/<slug> --check-command "<canonical test command>"
```

It writes the frontmatter (`id`, `title`, `type`, `status`, the original triage label under `labels`),
lifts the inline `**Blocked by:**` line into a `## Blocked by` section with normalized ids, drops the now
duplicated inline `**Status:**` line, and scaffolds `README.md` (ground rules) and `decisions.md` when they
are missing. Already adopted files are skipped, so a later batch of tickets can be adopted without
disturbing issues the chain has already advanced.

`type` is derived from the triage vocabulary in `docs/agents/triage-labels.md`, never guessed:
`ready-for-agent` is the only AFK status; `ready-for-human`, `needs-triage`, `needs-info` and `wontfix`
become HITL. A missing or unknown status aborts the whole adoption without writing anything — an issue
whose `type` is silently empty would read as AFK and be handed to autonomous workers.

Adoption writes issue files, so it belongs to the orchestrator's lifecycle-state boundary, not to product
code. If `to-tickets` later rewrites an adopted file, its frontmatter is gone: re-running adoption restores
the format, but a `status: done` recorded there is lost.

