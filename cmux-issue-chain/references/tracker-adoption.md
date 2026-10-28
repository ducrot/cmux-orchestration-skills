### Adopting a `to-tickets` tracker

Tickets written by `to-tickets` carry no frontmatter, so the preflight rejects them until they are adopted.
`adopt_tracker.py` converts them, preserving ticket filenames. An undated tracker requires the human's
approved `--feature YYYY-MM-DD-<slug>` basename: a valid calendar date and a lowercase kebab-case slug
of at most 30 characters. The destination must not exist and stays in the same parent directory;
paths and traversal are not accepted as names. Ask for approval before running the rename.

```bash
python3 scripts/adopt_tracker.py --tracker .scratch/<tracker> --feature YYYY-MM-DD-<slug> --dry-run
python3 scripts/adopt_tracker.py --tracker .scratch/<tracker> \
  --feature YYYY-MM-DD-<slug> \
  --branch feature/<slug> --check-command "<canonical test command>"
```

It writes the frontmatter (`id`, `title`, `type`, `status`, the original triage label under `labels`),
lifts the inline `**Blocked by:**` line into a `## Blocked by` section with normalized ids, drops the now
duplicated inline `**Status:**` line, and scaffolds `README.md` (ground rules) and `decisions.md` when they
are missing. Already adopted files are skipped, so a later batch of tickets can be adopted without
disturbing issues the chain has already advanced.

The adoption validates all tickets and plans scaffolds before renaming, then renames before writing
frontmatter. `--dry-run` reports the rename and adoption without writing anything. An invalid or
missing name, an occupied destination, or an adoption validation error leaves the tree unchanged.
A tracker with a valid date prefix is never renamed, even if `--feature` names something else.
If execution stops after the rename, rerun adoption with `--tracker` pointing at the dated folder;
already adopted files are skipped and the remaining work completes.

Later `to-tickets` batches and `/implement` calls must point at the dated folder. For a Git-tracked
tracker, Git shows the rename as deleting the old paths and adding the new ones; adoption uses a
filesystem rename, not `git mv`. After renaming, initialize the chain with the dated `--tracker` and
replace the old tracker path in `--invocation` too, so the next-run prompt uses the existing folder.

`type` is derived from the triage vocabulary in `docs/agents/triage-labels.md`, never guessed:
`ready-for-agent` is the only AFK status; `ready-for-human`, `needs-triage`, `needs-info` and `wontfix`
become HITL. A missing or unknown status aborts the whole adoption without writing anything — an issue
whose `type` is silently empty would read as AFK and be handed to autonomous workers.

Adoption writes issue files, so it belongs to the orchestrator's lifecycle-state boundary, not to product
code. If `to-tickets` later rewrites an adopted file, its frontmatter is gone: re-running adoption restores
the format, but a `status: done` recorded there is lost.

