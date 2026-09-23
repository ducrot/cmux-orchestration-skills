"""Publish a mechanically gated triage report after validating every precondition."""
from __future__ import annotations

import re
from pathlib import Path

from collect_recommendations import FOLLOWUP_ALLOWED, UNSUPPORTED_PASS_ERROR, collected_data, read_items
from orchestrator_lib import append_jsonl, load_issues, normalize_issue_id, read_run_state, slugify, utc_now
from parse_report import parse_report
from triage_contract import VERDICTS
from worker_readiness import read_events


def publish(run_dir: Path, pass_num: int) -> dict:
    if pass_num not in FOLLOWUP_ALLOWED:
        raise ValueError(UNSUPPORTED_PASS_ERROR)
    state = read_run_state(run_dir)
    if state["triage_mode"] != "autonomous" or state.get("current_stage") != "triage":
        raise ValueError("publish-triage requires autonomous mode and current_stage triage")
    audit = read_events(run_dir)
    if any(e.get("type") == "triage.published" and e.get("data", {}).get("pass") == pass_num for e in audit):
        raise ValueError("triage already published for this pass")
    data = collected_data(run_dir, pass_num)
    if not data or not data["item_count"]:
        raise ValueError("missing nonempty triage.collected event")
    snapshot_label = f"report-captured triage-{pass_num}"
    if not any(e.get("type") == "tree.snapshot" and (e.get("message") == snapshot_label or e.get("data", {}).get("label") == snapshot_label) for e in audit):
        raise ValueError(f"missing tree.snapshot labelled {snapshot_label}")
    items_path = run_dir / f"triage-items-{pass_num}.md"
    items = read_items(items_path)
    report = run_dir / "reports" / f"triage-{pass_num}.md"
    gate = parse_report(report.read_text(encoding="utf-8"), items_path)
    if gate["gate"] != "advance":
        raise ValueError("triage report does not gate advance: " + "; ".join(gate["reasons"]))
    tracker = Path(state["tracker"])
    issues = load_issues(tracker)
    issue_paths = [Path(issue.path) for issue in issues.values()]
    number = max((int(re.search(r"\d+", issue.id)[0]) for issue in issues.values()), default=0)
    numeric_names = [re.fullmatch(r"(\d+)-(.+)\.md", path.name) for path in issue_paths]
    numeric = bool(numeric_names) and all(numeric_names)
    padding = max(len(m[1]) for m in numeric_names) if numeric else None
    slugs = {re.sub(r"^(?:ISSUE-)?\d+-?", "", p.stem) for p in issue_paths}
    planned = []
    created_by_item = {}
    for verdict in gate["verdicts"]:
        if verdict["id"] not in gate["new_issue_items"]:
            continue
        draft = verdict["draft"]
        unknown = set(draft["blockers"]) - issues.keys()
        if unknown:
            raise ValueError(f"unknown blocker IDs: {sorted(unknown)}")
        slug = slugify(draft["title"])
        if slug in slugs:
            raise ValueError(f"issue slug collision: {slug}")
        slugs.add(slug)
        number += 1
        issue_id = normalize_issue_id(number)
        prefix = f"{number:0{padding}d}" if numeric else issue_id
        target = tracker / "issues" / f"{prefix}-{slug}.md"
        if target.exists():
            raise ValueError(f"target issue path exists: {target}")
        title = draft["title"].replace('"', "'")
        body = (f'---\nid: {issue_id}\ntitle: "{title}"\ntype: AFK\nstatus: todo\nlabels: [ready-for-agent]\n---\n\n'
                f'# {issue_id} — {draft["title"]}\n\n{draft["body"]}\n')
        planned.append((target, body))
        created_by_item[verdict["id"]] = issue_id
    followup_path = run_dir / "followup-items.md"
    if gate["followup_items"] and followup_path.exists():
        raise ValueError(f"follow-up file already exists: {followup_path}")
    # All content, paths, drafts, hashes and ledger entries are prepared before the first write.
    ledger = tracker / "decisions.md"
    prior = ledger.read_text(encoding="utf-8") if ledger.exists() else "# Decisions\n"
    ledger_lines = []
    item_events = []
    followups = []
    source_items = {i["id"]: i for i in items["items"]}
    for verdict in gate["verdicts"]:
        key = verdict["id"]
        if key in gate["followup_items"]:
            consequence = "follow-up pass"
        elif key in created_by_item:
            consequence = created_by_item[key]
        elif verdict["verdict"] == "for-the-human":
            consequence = "open for the human"
        else:
            consequence = "ledger only"
        label = "FOR-THE-HUMAN (open)" if verdict["verdict"] == "for-the-human" else verdict["verdict"].upper()
        supersedes = f' Supersedes: {verdict["supersedes"]}.' if verdict["supersedes"] != "none" else ""
        ledger_lines.append(f'- {state["issue"]["id"]} triage-{pass_num} {key} ({verdict["source"]}): '
                            f'{verdict["title"]} — {label} — {verdict["reason"]}{supersedes} '
                            f'Consequence: {consequence}. [triage-worker verdict, run {state["run_id"]}, gate advance]')
        item_events.append({"pass": pass_num, **{field: verdict[field] for field in
                            ("id", "source", "title", "verdict", "followup_eligible", "reason", "supersedes")},
                            "consequence": consequence, "issue": created_by_item.get(key), "authority": "triage-worker"})
        if key in gate["followup_items"]:
            followups.append(f'- {key} ({verdict["source"]})\n  Supersedes: {verdict["supersedes"]}\n'
                             f'  Files: {", ".join(verdict["files"])}\n\n```markdown\n'
                             + source_items[key]["text"] + f'\n```\n\nTriage reason: {verdict["reason"]}\n')
    published = {"pass": pass_num, "counts": {v: sum(i["verdict"] == v for i in gate["verdicts"]) for v in VERDICTS},
                 "created_issues": list(created_by_item.values()), "followup_items": gate["followup_items"],
                 "for_the_human": gate["for_the_human"],
                 "followup_file": str(followup_path) if followups else None}
    for target, body in planned:
        with target.open("x", encoding="utf-8") as stream:
            stream.write(body)
    ledger.write_text(prior.rstrip() + "\n\n" + "\n".join(ledger_lines) + "\n", encoding="utf-8")
    if followups:
        with followup_path.open("x", encoding="utf-8") as stream:
            stream.write("# Approved Follow-up Items\n\n" + "\n".join(followups))
    for event in item_events:
        append_jsonl(run_dir / "events.jsonl", {"time": utc_now(), "type": "recommendations.triaged", "data": event})
    append_jsonl(run_dir / "events.jsonl", {"time": utc_now(), "type": "triage.published", "data": published})
    return {**published, "next_stage": "implement" if followups else None}
