#!/usr/bin/env python3
"""Token usage analysis for cmux orchestrator sessions.

Scans Claude Code and Codex transcripts, keeps only sessions that actually
executed an orchestration script of the selected workflow (issue-chain,
planning or grilling), and reports per-session and per-run cost metrics
grouped by the skill commit that was live at the time.

Only the session executing run_state.py init (including its returned run path)
or named as the owner in run.init owns a run. Mentions do not establish ownership.
Owned sessions are sliced from run.init through run.completed, falling back to
run.recap. Open runs end at the next owned init or the transcript end. Worker
prompts identify separate worker totals, never orchestrator medians. Grilling
per-question and worker per-round metrics exclude calls before the first question.

Wall time per stage (launch to report capture, the gap until the next launch,
human waits) and test-runner summaries in the workers' artifact logs come from
the run directory alone.

Stdlib only. Writes orchestrator-usage-sessions.csv, orchestrator-usage-runs.csv
and orchestrator-usage-stages.csv, plus a median-based terminal summary.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shlex
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"
CODEX_SESSIONS = Path.home() / ".codex" / "sessions"
SKILL_REPO = Path.home() / "Sites" / "agentic-workflows" / "cmux-orchestration-skills"
CACHE_DIR = Path.home() / ".cache" / "orchestrator-usage"
CACHE_VERSION = 15


class Workflow:
    """What identifies one workflow's orchestrator: its skill directory, the scripts
    only that skill ships (executing one identifies the workflow even when the path
    came from a shell variable), and the prefix of its run ids."""

    def __init__(self, name: str, subdir: str, only_scripts: tuple[str, ...],
                 run_prefix: str | None, roles: tuple[str, ...] = ()):
        self.name = name
        self.subdir = subdir
        self.only_scripts = only_scripts
        self.run_prefix = run_prefix
        self.roles = roles
        self.only_re = re.compile(r"(?:" + "|".join(only_scripts) + r")\.py")

    def owns_run(self, run_id: str) -> bool:
        if self.run_prefix:
            return run_id.startswith(self.run_prefix)
        return not run_id.startswith(tuple(p for w in WORKFLOWS.values()
                                           if (p := w.run_prefix)))


WORKFLOWS = {w.name: w for w in (
    Workflow("issue-chain", "cmux-issue-chain", ("adopt_tracker", "issue_state"), None,
             ("implement", "simplify", "review", "test", "triage")),
    Workflow("planning", "cmux-planning",
             ("planning_state", "stage_snapshot", "tree_integrity", "spec_contract",
              "tracker_contract", "artifact_manifest", "grilling_input", "planning_recovery",
              "planning_diversity"), "plan-", ("spec", "spec-review", "tickets", "tickets-review")),
    Workflow("grilling", "cmux-grilling", ("launch_wave", "parse_research_report"), "grill-"),
)}

# Names more than one skill ships - an execution through a variable is ambiguous.
# `stage`, `wave` and `baseline_delta` are the planned composite-verb scripts.
SHARED_SCRIPTS = ("run_state", "pane_ctl", "render_prompt", "agents_config",
                  "await_report", "await_reports", "worker_readiness",
                  "stage", "wave", "baseline_delta")

# An execution is an interpreter followed by the script, or the script itself at the
# start of a command segment. The directory part may be a variable or quoted, but must
# not contain '=' so that `S=/path/run_state.py` stays an assignment. A quoted path
# without an interpreter (grep pattern, prose) never matches.
_SCRIPT = r"(?:" + "|".join(
    [s for w in WORKFLOWS.values() for s in w.only_scripts] + list(SHARED_SCRIPTS)) + r")\.py"
ORCHESTRATOR_CALL = re.compile(
    r"(?:(?:^|[\n;&|(`])\s*(?:python3?|uv\s+run(?:\s+python3?)?)\s+(?:-\S+\s+)*"
    r"[\"']?(?:[^\s'\";|&=]*/)?"
    r"|(?:^|[\n;&|(`])\s*(?:\./)?[^\s'\";|&=]*/)" + _SCRIPT
)
RUN_ID_RE = re.compile(r"orchestrator/runs/([A-Za-z0-9][A-Za-z0-9._-]*)")

# Whatever the wording, a worker is handed the path of its own stage prompt.
WORKER_PROMPT = re.compile(r"orchestrator/runs/[^\s\"']+/prompts/[^\s\"']+\.md")

USAGE_FIELDS = ("input_tokens", "cached_input_tokens", "cache_write_input_tokens",
                "output_tokens", "reasoning_output_tokens", "total_tokens")

CODEX_SHELL_TOOLS = {"exec", "shell", "exec_command", "shell_command", "run", "local_shell"}

CATEGORY_ORDER = [
    "wait",
    "pane-lifecycle",
    "bookkeeping",
    "code/verify",
    "tracker",
    "worker-report",
    "read",
    "other-bash",
]


# --------------------------------------------------------------------------- #
# turn classification
# --------------------------------------------------------------------------- #

WORD_TOOLS = re.compile(r"(?:^|[\s;&|(`$])(git|npm|npx|vitest|curl)(?:\s|$)")


def run_ids_in(text: str) -> list[str]:
    """Run ids named in a command; shell-variable stubs are dropped."""
    found = []
    for candidate in RUN_ID_RE.findall(text):
        candidate = candidate.rstrip("-._")
        if len(candidate) >= 4:
            found.append(candidate)
    return found


def new_evidence() -> dict:
    return {"hard": False, "soft": False, "own_path": False, "foreign_path": False,
            "own_run": False}


QUOTED_SPAN = re.compile(r"'[^'\n]*'|\"[^\"\n]*\"")
INTERPRETER_IN_SPAN = re.compile(r"(?:python3?|uv\s+run)\s")


def strip_quoted_examples(command: str) -> str:
    return QUOTED_SPAN.sub(
        lambda mo: "" if INTERPRETER_IN_SPAN.search(mo.group(0)) else mo.group(0), command)


def scan_command(command: str, evidence: dict, workflow: Workflow,
                 quoted_spans: bool = False) -> None:
    """Record what an executed shell command says about the session's workflow.

    A quoted span that carries its own interpreter is an example being discussed, not
    a run - analysis and documentation sessions quote invocations verbatim. Codex
    wraps every command in such a span, so there the spans stay.
    """
    if not quoted_spans:
        command = strip_quoted_examples(command)
    siblings = [w for w in WORKFLOWS.values() if w is not workflow]
    for match in ORCHESTRATOR_CALL.finditer(command):
        text = match.group(0)
        if workflow.subdir + "/" in text or workflow.only_re.search(text):
            evidence["hard"] = True
        elif any(w.subdir + "/" in text or w.only_re.search(text) for w in siblings):
            pass  # a sibling skill's script, not ours
        else:
            evidence["soft"] = True  # path came from a variable - needs corroboration
    if workflow.subdir + "/" in command:
        evidence["own_path"] = True
    if any(w.subdir + "/" in command for w in siblings):
        evidence["foreign_path"] = True
    if any(workflow.owns_run(run) for run in run_ids_in(command)):
        evidence["own_run"] = True


def is_orchestrator(evidence: dict) -> bool:
    """A variable-path execution needs corroboration: the session must name the skill
    directory, and a sibling workflow in the mix is only disqualifying when no run of
    this workflow was touched (skill development drives all three side by side)."""
    if evidence["hard"]:
        return True
    if not (evidence["soft"] and evidence["own_path"]):
        return False
    return evidence["own_run"] or not evidence["foreign_path"]


WAIT_COMMAND = re.compile(r"await_reports?\.py|tail -f|(?:^|[\n;&|(]\s*)sleep\s+\d")
# Ignore bookkeeping argument values, while retaining quoted executable shell
# content such as bash -c commands and command substitutions in assignments.
SCREEN_READ = re.compile(
    r"(?:^|[\s;&|(])(?:read-screen|capture-pane)(?![\w-])|\bcmux\s+capture(?![\w-])")
BOOKKEEPING_ARGUMENT = re.compile(
    r"(?<!\S)--(?:message|label)(?:\s+|=)"
    r'''(?:"(?:\\.|[^"\\])*"|'[^']*'|[^\s;&|]+)''')
WAIT_CATEGORIES = ("wait", "reply-after-wait")
# Composite verbs go by their verb: `stage.py capture` right after a watcher wake-up
# collects a finished report and must not fall into the screen-read rule below.
COMPOSITE_VERB = re.compile(
    r"(?:stage|wave)\.py[\"']?\s+(open|round|deliver|started|mark-started|capture|gate)(?![\w-])")
COMPOSITE_CATEGORY = {"open": "pane-lifecycle", "round": "pane-lifecycle",
                      "deliver": "pane-lifecycle", "started": "pane-lifecycle",
                      "mark-started": "pane-lifecycle", "capture": "bookkeeping",
                      "gate": "bookkeeping"}


def classify_bash(command: str, prev_category: str | None = None) -> str:
    c = command
    if WAIT_COMMAND.search(c):
        return "wait"
    verb = COMPOSITE_VERB.search(c)
    if verb:
        return COMPOSITE_CATEGORY[verb.group(1)]
    # A screen read is lifecycle when it judges a start or delivery, and waiting when
    # it follows a sleep or a watcher - the sleep-and-look loop of a harness without
    # a blocking wait.
    if SCREEN_READ.search(BOOKKEEPING_ARGUMENT.sub("", c)):
        return "wait" if prev_category in WAIT_CATEGORIES else "pane-lifecycle"
    if "pane_ctl" in c:
        return "pane-lifecycle"
    if "run_state" in c or "render_prompt" in c or "agents_config" in c or "gate_" in c \
            or "baseline_delta" in c:
        return "bookkeeping"
    if WORD_TOOLS.search(c):
        return "code/verify"
    if "issues/" in c or "decisions.md" in c or "HANDOFF" in c:
        return "tracker"
    if "reports/" in c:
        return "worker-report"
    return "other-bash"


def classify_tool(name: str, command: str | None, prev_category: str | None = None) -> str:
    if name in ("Monitor", "TaskStop", "sleep", "wait"):
        return "wait"
    if name in ("Read", "Grep", "Glob"):
        return "read"
    if name == "Bash" or command is not None:
        return classify_bash(command or "", prev_category)
    return "other:" + name


# --------------------------------------------------------------------------- #
# generic call container
# --------------------------------------------------------------------------- #


class Call:
    """One deduplicated API call."""

    __slots__ = ("ts", "input", "output", "cache_create", "cache_read",
                 "reasoning", "category", "run_id")

    def __init__(self, ts, inp, out, cc, cr, reasoning):
        self.ts = ts
        self.input = inp
        self.output = out
        self.cache_create = cc
        self.cache_read = cr
        self.reasoning = reasoning
        self.category = None
        self.run_id = None

    @property
    def context(self) -> int:
        return self.input + self.cache_create + self.cache_read

    @property
    def total(self) -> int:
        return self.context + self.output


def iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# Claude Code parsing
# --------------------------------------------------------------------------- #


INIT_SCRIPTS = ("run_state.py", "planning_state.py")
INIT_COMMAND = re.compile(r"(?:run|planning)_state\.py[\"']?\s+init(?:\s|$)")


def transcript_role(path: Path, harness: str) -> tuple[list[str], list[str]]:
    """Identify worker prompts and init tool/result pairs, not arbitrary mentions."""
    workers, owners = set(), set()
    init_tools = set()
    first_user = False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(ev, dict):
            continue
        payload = ev.get("payload") or {}
        if harness == "claude":
            user = ev.get("type") == "user"
            content = (ev.get("message") or {}).get("content")
        else:
            user = ev.get("type") == "response_item" and payload.get("role") == "user"
            content = payload.get("content")
        if user and not first_user:
            # Instruction headings inside AGENTS must not consume first-user status.
            text = "".join(
                part for part in (ENV_BLOCK.sub("", message_text([b])) for b in
                                  (content if isinstance(content, list) else [{"text": content}]))
                if not part.lstrip().startswith("# AGENTS.md instructions"))
            if text.strip():
                first_user = True
                workers.update(run_ids_in(" ".join(WORKER_PROMPT.findall(text))))
        if harness == "claude":
            for block in content if isinstance(content, list) else []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use" and block.get("name") == "Bash":
                    command = (block.get("input") or {}).get("command", "")
                    if executed_init(command):
                        init_tools.add(block.get("id"))
                        owners.update(init_command_runs(command))
                if block.get("type") == "tool_result" and block.get("tool_use_id") in init_tools:
                    if not block.get("is_error"):
                        owners.update(run_ids_in(message_text(block.get("content"))))
        elif ev.get("type") == "response_item":
            for command in codex_commands(payload):
                if executed_init(command):
                    init_tools.add(payload.get("call_id"))
                    owners.update(init_command_runs(command))
            if payload.get("type") in ("function_call_output", "custom_tool_call_output") \
                    and payload.get("call_id") in init_tools:
                owners.update(run_ids_in(str(payload.get("output", ""))))
    return sorted(workers), sorted(owners)


def executed_init(command: str) -> bool:
    command = strip_quoted_examples(command)
    return any(INIT_COMMAND.match(command, m.end() - len(script))
               for m in ORCHESTRATOR_CALL.finditer(command)
               for script in INIT_SCRIPTS if m.group().endswith(script))


def init_command_runs(command: str) -> list[str]:
    return run_ids_in(command) + re.findall(r"--run-id\s+[\"']?([\w.-]+)", command)


def parse_claude(path: Path, workflow: Workflow, include_workers: bool = False) -> dict | None:
    requests: dict[str, dict] = {}
    order: list[str] = []
    evidence = new_evidence()
    cwd = None
    session_id = path.stem

    with path.open(encoding="utf-8", errors="replace") as fh:
        for lineno, line in enumerate(fh):
            if not line.strip():
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(ev, dict):
                continue
            cwd = ev.get("cwd") or cwd
            etype = ev.get("type")

            if etype != "assistant":
                continue
            msg = ev.get("message") or {}
            usage = msg.get("usage") or {}
            key = ev.get("requestId") or f"__line{lineno}"
            rec = requests.get(key)
            if rec is None:
                rec = {"usage": usage, "ts": ev.get("timestamp"), "tool": None, "cmd": None,
                       "runs": []}
                requests[key] = rec
                order.append(key)
            elif not rec["usage"] and usage:
                rec["usage"] = usage

            for block in msg.get("content") or []:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                name = block.get("name") or ""
                tool_input = block.get("input") or {}
                command = tool_input.get("command") if isinstance(tool_input, dict) else None
                if name == "Bash" and isinstance(command, str):
                    scan_command(command, evidence, workflow)
                if rec["tool"] is None:
                    rec["tool"] = name
                    rec["cmd"] = command if isinstance(command, str) else None
                blob = json.dumps(tool_input) if isinstance(tool_input, (dict, list)) else str(tool_input)
                rec["runs"].extend(run_ids_in(blob))

    if not order:
        return None
    worker_runs, owned_runs = transcript_role(path, "claude")
    if (worker_runs and not include_workers) or (not worker_runs and not is_orchestrator(evidence)):
        return None

    calls = []
    prev_category = None
    for key in order:
        rec = requests[key]
        u = rec["usage"] or {}
        call = Call(
            rec["ts"],
            int(u.get("input_tokens") or 0),
            int(u.get("output_tokens") or 0),
            int(u.get("cache_creation_input_tokens") or 0),
            int(u.get("cache_read_input_tokens") or 0),
            None,  # Claude persists thinking blocks empty; reasoning is not measurable
        )
        if rec["tool"]:
            call.category = classify_tool(rec["tool"], rec["cmd"], prev_category)
            prev_category = call.category
        else:
            call.category = f"reply-after-{prev_category or 'none'}"
        call.run_id = rec["runs"][0] if rec["runs"] else None
        calls.append(call)

    return parsed_session("claude", session_id, path, cwd, calls, worker_runs, owned_runs)


def message_text(content) -> str:
    """Text of a message, across both harnesses' block types."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            b["text"] for b in content
            if isinstance(b, dict) and isinstance(b.get("text"), str)
        )
    return ""


# --------------------------------------------------------------------------- #
# Codex parsing
# --------------------------------------------------------------------------- #

ENV_BLOCK = re.compile(r"<environment_context>.*?</environment_context>", re.S)


CODEX_CMD = re.compile(
    r"[\"']?(?:cmd|command)[\"']?\s*:\s*"
    r"(?:\"((?:[^\"\\]|\\.)*)\"|'((?:[^'\\]|\\.)*)'|`([^`]*)`)")


def unwrap_shell(value) -> str:
    """The command a shell actually runs, unwrapped from its argv form."""
    if isinstance(value, list):
        if len(value) >= 3 and value[0] in ("bash", "sh", "zsh") \
                and value[1] in ("-lc", "-c", "-lic"):
            return str(value[-1])
        return " ".join(str(v) for v in value)
    return str(value or "")


def codex_commands(payload: dict):
    ptype = payload.get("type")
    name = payload.get("name")
    if name not in CODEX_SHELL_TOOLS:
        return
    if ptype == "custom_tool_call":
        # `exec` carries a JS snippet calling tools.exec_command({cmd: "..."}); the
        # command itself sits in a quoted literal, so pull it out before scanning.
        raw = str(payload.get("input") or "")
        found = False
        for match in CODEX_CMD.finditer(raw):
            literal = next(g for g in match.groups() if g is not None)
            try:
                literal = json.loads('"' + literal.replace('"', '\\"') + '"')
            except json.JSONDecodeError:
                pass
            found = True
            yield literal
        if not found:
            yield raw
    elif ptype in ("function_call", "local_shell_call"):
        try:
            args = json.loads(payload.get("arguments") or "{}")
        except (json.JSONDecodeError, TypeError):
            return
        if not isinstance(args, dict):
            return
        yield unwrap_shell(args.get("command") or args.get("cmd") or "")


def parse_codex(path: Path, workflow: Workflow, include_workers: bool = False) -> dict | None:
    session_id = None
    cwd = None
    evidence = new_evidence()
    calls: list[Call] = []
    pending_tools: list[tuple[str, str | None]] = []  # (tool name, command)
    pending_runs: list[str] = []
    prev_category = None
    cumulative = {k: 0 for k in USAGE_FIELDS}

    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(ev, dict):
                continue
            etype = ev.get("type")
            payload = ev.get("payload") or {}

            if etype == "session_meta":
                session_id = payload.get("session_id") or payload.get("id")
                cwd = payload.get("cwd")
                continue

            ptype = payload.get("type")

            if etype == "response_item" and ptype in ("custom_tool_call", "function_call",
                                                      "local_shell_call"):
                got_command = False
                for command in codex_commands(payload):
                    got_command = True
                    scan_command(command, evidence, workflow)
                    pending_tools.append(("Bash", command))
                    pending_runs.extend(run_ids_in(command))
                if not got_command:
                    pending_tools.append((str(payload.get("name") or "tool"), None))
                continue

            if etype == "event_msg" and ptype == "token_count":
                info = payload.get("info") or {}
                # total_token_usage is cumulative per session. A token_count event is
                # occasionally emitted twice - the cumulative total then stands still,
                # which is a duplicate to drop, not a call. Only a backwards jump is a
                # context reset, where last_token_usage carries the real call.
                total = info.get("total_token_usage") or {}
                delta = {k: int(total.get(k) or 0) - int(cumulative.get(k) or 0)
                         for k in USAGE_FIELDS}
                if delta["total_tokens"] == 0:
                    continue
                if delta["total_tokens"] < 0 or delta["input_tokens"] < 0:
                    delta = {k: int((info.get("last_token_usage") or {}).get(k) or 0)
                             for k in USAGE_FIELDS}
                    if delta["total_tokens"] <= 0:
                        continue
                cumulative = {k: int(total.get(k) or 0) for k in USAGE_FIELDS}
                cached = delta["cached_input_tokens"]
                call = Call(
                    ev.get("timestamp"),
                    max(delta["input_tokens"] - cached, 0),
                    delta["output_tokens"],
                    delta["cache_write_input_tokens"],
                    cached,
                    delta["reasoning_output_tokens"],
                )
                if pending_tools:
                    name, command = pending_tools[0]
                    call.category = classify_tool(name, command, prev_category)
                    prev_category = call.category
                else:
                    call.category = f"reply-after-{prev_category or 'none'}"
                call.run_id = pending_runs[0] if pending_runs else None
                calls.append(call)
                pending_tools = []
                pending_runs = []

    if not calls or not session_id:
        return None
    worker_runs, owned_runs = transcript_role(path, "codex")
    if (worker_runs and not include_workers) or (not worker_runs and not is_orchestrator(evidence)):
        return None
    return parsed_session("codex", session_id, path, cwd, calls, worker_runs, owned_runs)


# --------------------------------------------------------------------------- #
# session aggregation
# --------------------------------------------------------------------------- #


def parsed_session(harness, session_id, path, cwd, calls, worker_runs, owned_runs):
    session = build_session(harness, session_id, str(path), cwd, calls)
    session.update(worker_runs=worker_runs, owned_runs=owned_runs,
                   transcript_calls=[{k: getattr(c, k) for k in Call.__slots__} for c in calls])
    return session


def restore_calls(session):
    calls = []
    for record in session.get("transcript_calls", []):
        call = Call.__new__(Call)
        for key in Call.__slots__:
            setattr(call, key, record[key])
        calls.append(call)
    return calls


def owned_session_windows(sessions, workflow):
    """One session slice per owned run, bounded by event times."""
    windows = []
    root_states: dict[Path, dict] = {}
    for session in sessions:
        if session.get("worker_runs"):
            continue
        root = project_root(session["cwd"])
        states = {}
        if root:
            if root not in root_states:
                root_states[root] = {d.name: read_run_state(d, workflow)
                                     for d in (root / ".scratch/orchestrator/runs").iterdir()
                                     if d.is_dir()}
            states = root_states[root]
        owned = set(session.get("owned_runs", []))
        owned.update(r for r, state in states.items()
                     if session["session_id"] in state["owner_sessions"])
        calls = [(iso(c.ts), c) for c in restore_calls(session)]
        starts = sorted(t for t in (iso(states[r]["init_time"]) for r in owned if r in states) if t)
        for run_id in sorted(owned):
            if not workflow.owns_run(run_id):
                continue
            state = states.get(run_id, {})
            start = iso(state.get("init_time"))
            end = iso(state.get("completed_time") or state.get("recap_time"))
            next_init = None
            if start and not end:
                next_init = next((t for t in starts if t > start), None)
            if start:
                selected = [c for t, c in calls if t and t >= start
                            and (end is None or t <= end)
                            and (next_init is None or t < next_init)]
            else:
                selected, current = [], None
                for _, c in calls:
                    current = c.run_id or current
                    if current == run_id:
                        selected.append(c)
            if not selected:
                continue
            for call in selected:
                call.run_id = run_id
            piece = build_session(session["harness"], session["session_id"], session["path"],
                                  session["cwd"], selected)
            for key in ("skill_commit", "skill_commit_date", "skill_md_bytes"):
                piece[key] = session.get(key, "")
            windows.append(piece)
    return windows


def build_session(harness: str, session_id: str, path: str, cwd: str | None,
                  calls: list[Call]) -> dict:
    # Sticky run assignment: a call belongs to the most recently named run.
    current = None
    per_run: dict[str, dict] = {}
    for call in calls:
        if call.run_id:
            current = call.run_id
        key = current or "(unassigned)"
        bucket = per_run.setdefault(key, {"calls": 0, "tokens": 0, "effective": 0.0,
                                          "waits": 0, "start": None, "end": None,
                                          "timeline": []})
        bucket["calls"] += 1
        bucket["timeline"].append([call.ts, call.total, effective(call)])
        bucket["tokens"] += call.total
        bucket["effective"] += effective(call)
        if call.category in WAIT_CATEGORIES:
            bucket["waits"] += 1
        if call.ts:
            bucket["start"] = min(bucket["start"] or call.ts, call.ts)
            bucket["end"] = max(bucket["end"] or call.ts, call.ts)

    merge_prefix_runs(per_run)

    purpose_calls: dict[str, int] = {}
    purpose_tokens: dict[str, int] = {}
    for call in calls:
        purpose_calls[call.category] = purpose_calls.get(call.category, 0) + 1
        purpose_tokens[call.category] = purpose_tokens.get(call.category, 0) + call.total

    tokens_total = sum(c.total for c in calls)
    contexts = [c.context for c in calls]
    timestamps = [c.ts for c in calls if c.ts]
    wait_tokens = sum(purpose_tokens.get(c, 0) for c in WAIT_CATEGORIES)
    pane_tokens = sum(purpose_tokens.get(c, 0)
                      for c in ("pane-lifecycle", "reply-after-pane-lifecycle"))
    reasoning_values = [c.reasoning for c in calls if c.reasoning is not None]

    return {
        "harness": harness,
        "project": project_name(cwd, path),
        "session_id": session_id,
        "path": path,
        "cwd": cwd or "",
        "start_ts": min(timestamps) if timestamps else "",
        "end_ts": max(timestamps) if timestamps else "",
        "run_ids": sorted(k for k in per_run if k != "(unassigned)"),
        "calls": len(calls),
        "tokens_total": tokens_total,
        "input": sum(c.input for c in calls),
        "output": sum(c.output for c in calls),
        "cache_create": sum(c.cache_create for c in calls),
        "cache_read": sum(c.cache_read for c in calls),
        "reasoning": sum(reasoning_values) if reasoning_values else None,
        "start_context_tokens": contexts[0],
        "end_context_tokens": contexts[-1],
        "avg_context_per_call": sum(contexts) / len(contexts),
        "context_growth_per_call": (contexts[-1] - contexts[0]) / len(calls),
        "effective_input_equiv": sum(effective(c) for c in calls),
        "wait_share": wait_tokens / tokens_total if tokens_total else 0.0,
        "pane_share": pane_tokens / tokens_total if tokens_total else 0.0,
        "purpose_calls": purpose_calls,
        "purpose_tokens": purpose_tokens,
        "per_run": per_run,
    }


def merge_prefix_runs(per_run: dict[str, dict]) -> None:
    """Fold truncated run ids (a glob prefix in a command) into the full one."""
    for short in [k for k in per_run if k != "(unassigned)"]:
        longer = sorted(k for k in per_run if k != short and k.startswith(short))
        if not longer:
            continue
        target, source = per_run[longer[0]], per_run.pop(short)
        for field in ("calls", "tokens", "effective", "waits", "timeline"):
            target[field] += source[field]
        if source["start"]:
            target["start"] = min(target["start"] or source["start"], source["start"])
        if source["end"]:
            target["end"] = max(target["end"] or source["end"], source["end"])


def effective(call: Call) -> float:
    return call.cache_read * 0.1 + call.cache_create * 1.25 + call.input


def project_name(cwd: str | None, path: str) -> str:
    if cwd:
        return "-" + re.sub(r"[^A-Za-z0-9]+", "-", cwd.lstrip("/"))
    return Path(path).parent.name


# --------------------------------------------------------------------------- #
# run state
# --------------------------------------------------------------------------- #


def project_root(cwd: str | None) -> Path | None:
    if not cwd:
        return None
    here = Path(cwd)
    for candidate in [here, *here.parents]:
        if (candidate / ".scratch" / "orchestrator" / "runs").is_dir():
            return candidate
    return None


def run_project(cwd: str | None) -> str:
    """The project key run rows carry: the slug of the run root, not of the cwd."""
    root = project_root(cwd)
    return project_name(str(root), str(root)) if root else project_name(cwd, "")


ATTEMPT_SUFFIX = re.compile(r"-attempt-\d+$")


ROUND_REPORT = re.compile(r"^(round-\d+)-")


def empty_run_state() -> dict:
    return {"stages_completed": 0, "stages_prepared": 0, "stages_reported": 0,
            "start": None, "end": None, "issue": "", "workflow": "",
            "first_question": None, "questions": 0, "start_mode": "",
            "init_time": None, "completed_time": None, "recap_time": None,
            "owner_sessions": []}


def read_run_state(run_dir: Path, workflow: Workflow | None = None) -> dict:
    """Stage instances, wall clock and issue metadata for one run. For grilling the
    stage unit is the round, and the first `grill.question` ends the session start."""
    info = empty_run_state()
    events = run_dir / "events.jsonl"
    gates: list[str | None] = []
    prepared: set[tuple] = set()
    launches = []
    if events.is_file():
        for line in events.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(ev, dict):
                continue
            time = ev.get("time")
            if time:
                info["start"] = min(info["start"] or time, time)
                info["end"] = max(info["end"] or time, time)
            etype = ev.get("type")
            if etype == "worker.launch_sent":
                launches.append("prompt_path" in (ev.get("data") or {}))
            if etype == "run.init":
                info["init_time"] = time
                for source in (ev, ev.get("data") or {}, ev.get("state") or {}):
                    owner = source.get("session_id") or source.get("orchestrator_session_id")
                    if owner:
                        info["owner_sessions"].append(owner)
            if etype in ("run.completed", "run.recap") and time:
                field = "completed_time" if etype == "run.completed" else "recap_time"
                info[field] = min(info[field] or time, time)
            if etype == "gate":
                data = ev.get("data") or {}
                gates.append(ev.get("decision") or data.get("decision"))
            elif etype == "stage.prepared":
                data = ev.get("data") or {}
                prepared.add((data.get("stage"), data.get("pass")))
            elif etype == "grill.question":
                info["questions"] += 1
                if time:
                    info["first_question"] = min(info["first_question"] or time, time)
    if launches:
        info["start_mode"] = "new-start" if all(launches) else "mixed" if any(launches) else "old-start"
    state_file = run_dir / "state.json"
    if state_file.is_file():
        try:
            state = json.loads(state_file.read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError:
            state = {}
        info["issue"] = (state.get("issue") or {}).get("id", "")
        info["workflow"] = state.get("workflow", "")
        if not any(gates):
            gates = [g.get("decision") for g in state.get("gate_decisions") or []]
    # A stage instance counts once it produced a worker report - that is the only
    # signal that survives resumes (which replay carried-over gates) and aborts
    # (which prepare a stage that never ran). Retries of one instance land in
    # `<stage>-<pass>-attempt-N.md` and fold into it.
    reported = set()
    reports = run_dir / "reports"
    grilling = workflow is not None and workflow.name == "grilling"
    if reports.is_dir():
        for report in reports.glob("*.md"):
            if grilling:
                match = ROUND_REPORT.match(report.stem)
                if match:
                    reported.add(match.group(1))
            else:
                reported.add(ATTEMPT_SUFFIX.sub("", report.stem))
    advanced = [d for d in gates if d in ("advance", "complete", "done")]
    info["stages_reported"] = len(reported)
    info["stages_prepared"] = len(prepared)
    info["stages_completed"] = (len(reported) or len(prepared)
                                or (len(advanced) if advanced else len(gates)))
    return info


# --------------------------------------------------------------------------- #
# wall time and test runs
# --------------------------------------------------------------------------- #

UNKNOWN = "unknown"
HUMAN_EVENTS = ("decision.human", "hitl.resolved", "spec.approved", "tickets.approved",
                "spec.revision_requested", "tickets.revision_requested",
                "tickets.spec_revision_requested", "run.relaunch_approved")
TEST_COMMAND = re.compile(
    r"\bunittest\b|\bpytest\b|phpunit|\bvitest\b|\bjest\b"
    r"|\b(?:npm|pnpm|yarn)\s+(?:run\s+)?test\b|\bcomposer\s+(?:run(?:-script)?\s+)?test\b"
    r"|\bmake\s+(?:check|test)|\b(?:go|cargo)\s+test\b|\bartisan\s+test\b")
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
UNITTEST_SUMMARY = re.compile(r"^Ran (\d+) tests? in ([\d.]+)s")
PYTEST_SUMMARY = re.compile(r"^=+ .*?\b\d+ (?:passed|failed|errors?)\b.* in ([\d.]+)s")
PHPUNIT_SUMMARY = re.compile(r"^(?:OK \(\d+ tests?,|Tests: \d+, Assertions)")
JS_SUMMARY = re.compile(r"^\s*Tests:?\s+.*(?:\(\d+\)|\d+ total)\s*$")
RUN_TIME = re.compile(r"^\s*(?:Time:|Duration)\s+([\d:.]+)\s*(ms|s|m|seconds?|minutes?)?")


def log_seconds(value: str, unit: str | None) -> float | None:
    try:
        if ":" in value:  # PHPUnit's mm:ss.fff or hh:mm:ss
            seconds = 0.0
            for part in value.split(":"):
                seconds = seconds * 60 + float(part)
            return seconds
        number = float(value)
    except ValueError:
        return None
    if unit == "ms":
        return number / 1000
    if unit and unit.startswith("m"):
        return number * 60
    return number


def test_runs_in_log(text: str) -> list[float | None]:
    """Durations of the test-runner summaries in one log, None where a summary
    carries no time. PHPUnit prints its time before the summary, Jest and Vitest
    after it."""
    runs: list[float | None] = []
    pending, last_summary = None, None
    for index, line in enumerate(ANSI.sub("", text).splitlines()):
        match = UNITTEST_SUMMARY.match(line) or PYTEST_SUMMARY.match(line)
        if match:
            runs.append(float(match.groups()[-1]))
            continue
        if PHPUNIT_SUMMARY.match(line) or JS_SUMMARY.match(line):
            runs.append(pending)
            pending, last_summary = None, index
            continue
        match = RUN_TIME.match(line)
        if match:
            seconds = log_seconds(*match.groups())
            if last_summary is not None and index - last_summary <= 5 and runs[-1] is None:
                runs[-1] = seconds
            else:
                pending = seconds
    return runs


def stage_test_runs(artifacts: Path) -> dict[str, list[float | None]]:
    """Test-runner summaries per stage in the workers' artifact logs. A stage without
    a recognized summary is absent: its logs may be in a format not parsed here."""
    found: dict[str, list[float | None]] = {}
    if not artifacts.is_dir():
        return found
    for stage_dir in artifacts.iterdir():
        if not stage_dir.is_dir():
            continue
        runs = []
        for log in sorted(stage_dir.rglob("*.log")):
            try:
                runs += test_runs_in_log(log.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
        if runs:
            found.setdefault(ATTEMPT_SUFFIX.sub("", stage_dir.name), []).extend(runs)
    return found


def test_commands(data: dict) -> int | None:
    commands = data.get("commands")
    if commands is None:
        return None
    if not isinstance(commands, list):
        commands = [commands]
    count = 0
    for command in commands:
        command = str(command)
        try:
            argv = shlex.split(command)
        except ValueError:
            argv = []
        # Evidence checks run no suites, even when their paths name a test runner.
        if (len(argv) >= 2 and Path(argv[1]).name == "check_evidence.py"
                and re.fullmatch(r"(?:python|pypy)(?:\d+(?:\.\d+)*)?", Path(argv[0]).name)):
            continue
        count += bool(TEST_COMMAND.search(command))
    return count


def read_run_timing(run_dir: Path) -> dict:
    """Worker time per stage, from the launch to the report capture, and the gap
    after each capture until the next launch. A gap holding a human decision is
    split: the human wait runs from the last gate before the first human event to
    the last human event, the rest of the gap is the orchestrator's."""
    events = []
    path = run_dir / "events.jsonl"
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(ev, dict) and iso(ev.get("time")):
                events.append((iso(ev["time"]), ev))
    events.sort(key=lambda item: item[0])
    stages: dict[str, dict] = {}
    snapshot_keys = set()
    for when, ev in events:
        etype, data = ev.get("type"), ev.get("data") or {}
        message = ev.get("message") or ""
        if etype == "tree.snapshot" and message.startswith(("launched ", "report-captured ")):
            label, _, key = message.partition(" ")
            stage = stages.setdefault(key.strip(), {})
            if label == "launched":
                stage.setdefault("launch", when)
            else:
                stage["capture"] = when
            snapshot_keys.add((key.strip(), label))
            continue
        role = data.get("role") or data.get("stage")
        if not role or data.get("pass") in (None, ""):
            continue
        key = f"{role}-{data['pass']}"
        if etype == "pane.launched" and (key, "launched") not in snapshot_keys:
            stages.setdefault(key, {}).setdefault("launch", when)
        elif etype == "worker.waiting" and data.get("outcome") == "report" \
                and (key, "report-captured") not in snapshot_keys:
            stages.setdefault(key, {})["capture"] = when

    timed = sorted(((k, v) for k, v in stages.items() if "launch" in v and "capture" in v),
                   key=lambda kv: kv[1]["launch"])
    end = None
    for when, ev in events:
        if ev.get("type") in ("run.completed", "run.recap"):
            end = when
            break
    end = end or (events[-1][0] if events else None)
    suites = stage_test_runs(run_dir / "artifacts")
    rows = []
    for index, (key, stage) in enumerate(timed):
        gap_end = timed[index + 1][1]["launch"] if index + 1 < len(timed) else end
        capture = stage["capture"]
        gap = max((gap_end - capture).total_seconds(), 0) if gap_end else 0
        window = [(t, ev) for t, ev in events if capture <= t <= (gap_end or capture)]
        humans = [t for t, ev in window if ev.get("type") in HUMAN_EVENTS]
        human = 0.0
        if humans:
            gates = [t for t, ev in window if ev.get("type") == "gate" and t <= humans[0]]
            human = (humans[-1] - (gates[-1] if gates else capture)).total_seconds()
        orchestrator_tests: int | str = 0
        verified = [test_commands(ev.get("data") or {}) for t, ev in window
                    if ev.get("type") == "orchestrator.verified"]
        if verified and all(v is None for v in verified):
            orchestrator_tests = UNKNOWN
        else:
            orchestrator_tests = sum(v for v in verified if v)
        runs = suites.get(key)
        rows.append({
            "stage": key, "role": key.rpartition("-")[0],
            "launch_ts": stage["launch"].isoformat(), "capture_ts": capture.isoformat(),
            "worker_minutes": round((capture - stage["launch"]).total_seconds() / 60, 1),
            "gap_minutes": round(gap / 60, 1),
            "human_wait_minutes": round(human / 60, 1),
            "orchestrator_gap_minutes": round((gap - human) / 60, 1),
            "suite_runs_worker": len(runs) if runs else UNKNOWN,
            "suite_minutes_worker": round(sum(r for r in runs if r) / 60, 1) if runs else UNKNOWN,
            "suite_runs_orchestrator": orchestrator_tests,
        })
    return {"stages": rows}


def run_timing_columns(stages: list[dict], workflow: Workflow) -> dict:
    """Per-run wall-time and test-run columns; blank when no stage was timed."""
    def total(field):
        known = [s[field] for s in stages if s[field] != UNKNOWN]
        return round(sum(known), 1) if known else UNKNOWN

    columns = {"wall_worker_minutes": "", **{f"wall_{r}_minutes": "" for r in workflow.roles},
               "wall_orchestrator_gap_minutes": "", "wall_human_wait_minutes": "",
               "suite_runs_worker": "", "suite_minutes_worker": "",
               "suite_unknown_stages": "", "suite_runs_orchestrator": ""}
    if not stages:
        return columns
    columns["wall_worker_minutes"] = total("worker_minutes")
    for role in workflow.roles:
        minutes = [s["worker_minutes"] for s in stages if s["role"] == role]
        columns[f"wall_{role}_minutes"] = round(sum(minutes), 1) if minutes else ""
    columns["wall_orchestrator_gap_minutes"] = total("orchestrator_gap_minutes")
    columns["wall_human_wait_minutes"] = total("human_wait_minutes")
    for field in ("suite_runs_worker", "suite_minutes_worker", "suite_runs_orchestrator"):
        columns[field] = total(field)
    columns["suite_unknown_stages"] = sum(1 for s in stages if s["suite_runs_worker"] == UNKNOWN)
    return columns


# --------------------------------------------------------------------------- #
# skill versions
# --------------------------------------------------------------------------- #


def git(repo: Path, *args: str) -> str:
    out = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if out.returncode != 0:
        return ""
    return out.stdout


def skill_commits(repo: Path, subdir: str) -> list[tuple[str, datetime]]:
    """Commits touching the skill directory, newest first."""
    raw = git(repo, "log", "--format=%H\t%cI", "--", f"{subdir}/")
    commits = []
    for line in raw.splitlines():
        sha, _, date = line.partition("\t")
        when = iso(date)
        if sha and when:
            commits.append((sha, when))
    return commits


def skill_md_bytes(repo: Path, subdir: str, rev: str, cache: dict) -> int:
    if rev in cache:
        return cache[rev]
    total = 0
    for line in git(repo, "ls-tree", "-r", "-l", rev, "--", f"{subdir}/").splitlines():
        head, _, name = line.partition("\t")
        if not name.endswith(".md"):
            continue
        parts = head.split()
        if len(parts) >= 4 and parts[3].isdigit():
            total += int(parts[3])
    cache[rev] = total
    return total


def assign_skill_version(sessions: list[dict], repo: Path, subdir: str) -> None:
    commits = skill_commits(repo, subdir)
    size_cache: dict[str, int] = {}
    for session in sessions:
        start = iso(session["start_ts"])
        session["skill_commit"] = ""
        session["skill_commit_date"] = ""
        session["skill_md_bytes"] = ""
        if not start:
            continue
        for sha, when in commits:  # newest first
            if when <= start:
                session["skill_commit"] = sha[:8]
                session["skill_commit_date"] = when.date().isoformat()
                session["skill_md_bytes"] = skill_md_bytes(repo, subdir, sha, size_cache)
                break


# --------------------------------------------------------------------------- #
# cache
# --------------------------------------------------------------------------- #


def cache_path(workflow: Workflow) -> Path:
    return CACHE_DIR / f"index-{workflow.name}.json"


def load_cache(enabled: bool, path: Path) -> dict:
    if not enabled or not path.is_file():
        return {"version": CACHE_VERSION, "files": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"version": CACHE_VERSION, "files": {}}
    if data.get("version") != CACHE_VERSION:
        return {"version": CACHE_VERSION, "files": {}}
    return data


def save_cache(cache: dict, enabled: bool, path: Path) -> None:
    if not enabled:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache), encoding="utf-8")


def scan(paths, parser, cache: dict, use_cache: bool, workflow: Workflow) -> list[dict]:
    sessions = []
    for path in paths:
        try:
            stat = path.stat()
        except OSError:
            continue
        key = str(path)
        stamp = [stat.st_size, int(stat.st_mtime)]
        entry = cache["files"].get(key) if use_cache else None
        if entry and entry.get("stamp") == stamp:
            if entry.get("session"):
                sessions.append(entry["session"])
            continue
        # Cheap pre-filter: a transcript that never mentions the skill cannot
        # contain an executed orchestrator script call.
        try:
            with path.open("rb") as fh:
                blob = fh.read()
        except OSError:
            continue
        session = parser(path, workflow, include_workers=True) if (workflow.subdir.encode() in blob or b"orchestrator/runs/" in blob) else None
        cache["files"][key] = {"stamp": stamp, "session": session}
        if session:
            sessions.append(session)
    return sessions


# --------------------------------------------------------------------------- #
# reporting
# --------------------------------------------------------------------------- #


def median(values):
    values = [v for v in values if v is not None]
    return statistics.median(values) if values else None


def aggregate_runs(sessions: list[dict], workflow: Workflow = WORKFLOWS["issue-chain"]) -> list[dict]:
    chain = workflow.name == "issue-chain"
    runs: dict[tuple[str, str], dict] = {}
    # Where each run actually lives, so sessions driving a run from another checkout
    # do not split it into a second, stage-less row.
    home: dict[str, tuple[Path, str]] = {}
    for root in {project_root(s["cwd"]) for s in sessions}:
        if not root:
            continue
        for run_dir in (root / ".scratch" / "orchestrator" / "runs").glob("*"):
            if run_dir.is_dir():
                home.setdefault(run_dir.name, (root, project_name(str(root), str(root))))
    for session in sessions:
        root = project_root(session["cwd"])
        # Key on the project root so gap detection below lands in the same bucket
        # even when the session ran from a subdirectory.
        project = project_name(str(root), str(root)) if root else session["project"]
        for run_id, bucket in session["per_run"].items():
            if run_id == "(unassigned)":
                continue
            if root and not (root / ".scratch" / "orchestrator" / "runs" / run_id).is_dir() \
                    and any(other != run_id and other.startswith(run_id)
                            for other in session["per_run"]):
                continue  # truncated id whose full run is present
            run_root, run_project = home.get(run_id, (root, project))
            key = (run_project, run_id)
            run = runs.setdefault(key, {
                "run_id": run_id, "project": run_project, "harnesses": set(),
                "sessions": [], "calls": 0, "tokens_total": 0, "effective_input_equiv": 0.0,
                "waits": 0, "start": None, "end": None, "root": run_root, "timeline": [],
                "skill_commit": session.get("skill_commit", ""),
                "skill_commit_date": session.get("skill_commit_date", ""),
                "skill_md_bytes": session.get("skill_md_bytes", ""),
            })
            run["harnesses"].add(session["harness"])
            run["sessions"].append(session["session_id"][:8])
            run["calls"] += bucket["calls"]
            run["tokens_total"] += bucket["tokens"]
            run["effective_input_equiv"] += bucket["effective"]
            run["waits"] += bucket["waits"]
            run["timeline"].extend(bucket.get("timeline", []))
            for field, value in (("start", bucket["start"]), ("end", bucket["end"])):
                if value:
                    run[field] = min(run[field] or value, value) if field == "start" \
                        else max(run[field] or value, value)
            if root and not run["root"]:
                run["root"] = root

    # Gap detection: every run directory of every touched project must appear.
    roots = {project_root(s["cwd"]) for s in sessions}
    for root in roots:
        if not root:
            continue
        project = project_name(str(root), str(root))
        for run_dir in sorted((root / ".scratch" / "orchestrator" / "runs").glob("*")):
            if not run_dir.is_dir():
                continue
            if chain:
                if read_run_state(run_dir)["workflow"] not in ("issue-chain", ""):
                    continue
                if run_dir.name.startswith(("grill-", "plan-")):
                    continue
            elif not workflow.owns_run(run_dir.name) or not (
                    (run_dir / "events.jsonl").is_file() or (run_dir / "state.json").is_file()):
                continue  # another workflow's run, or a stray directory from a truncated id
            key = (project, run_dir.name)
            if key not in runs:
                runs[key] = {"run_id": run_dir.name, "project": project, "harnesses": set(),
                             "sessions": [], "calls": 0, "tokens_total": 0,
                             "effective_input_equiv": 0.0, "waits": 0, "start": None,
                             "end": None, "root": root, "timeline": [], "skill_commit": "",
                             "skill_commit_date": "", "skill_md_bytes": ""}

    for (project, short) in sorted(runs, key=lambda k: -len(k[1])):
        longer = sorted((k for k in runs
                         if k[0] == project and k[1] != short and k[1].startswith(short)),
                        key=lambda k: -len(k[1]))
        if not longer:
            continue
        target, source = runs[longer[0]], runs.pop((project, short))
        for field in ("calls", "tokens_total", "effective_input_equiv", "waits", "timeline"):
            target[field] += source[field]
        target["harnesses"].update(source["harnesses"])
        target["sessions"].extend(source["sessions"])

    rows = []
    for (_, run_id), run in sorted(runs.items()):
        if not chain and not workflow.owns_run(run_id):
            continue  # a sibling workflow's run the session also touched
        state = empty_run_state()
        have_state = False
        stage_timings = []
        if run["root"]:
            run_dir = run["root"] / ".scratch" / "orchestrator" / "runs" / run_id
            if run_dir.is_dir():
                state = read_run_state(run_dir, workflow)
                stage_timings = read_run_timing(run_dir)["stages"]
                have_state = True
        start = iso(state["start"] or run["start"])
        end = iso(state["end"] or run["end"])
        minutes = (end - start).total_seconds() / 60 if start and end else None
        stages = state["stages_completed"]
        # Grilling reports the session start (everything before the first question)
        # apart from the rounds, so the per-round columns cover rounds only.
        start_calls = start_tokens = start_effective = 0
        if workflow.name == "grilling":
            first = iso(state["first_question"])
            for ts, total, eff in run["timeline"]:
                when = iso(ts)
                if first is None or (when and when < first):
                    start_calls += 1
                    start_tokens += total
                    start_effective += eff
        round_calls = run["calls"] - start_calls
        round_tokens = run["tokens_total"] - start_tokens
        round_effective = run["effective_input_equiv"] - start_effective
        row = {
            "run_id": run_id,
            "start_mode": state["start_mode"],
            "project": run["project"],
            "issue": state["issue"],
            "workflow": state["workflow"],
            "coverage": ("orchestrator-session" if have_state else "no-run-state")
            if run["calls"] else "missing",
            "harnesses": "+".join(sorted(run["harnesses"])),
            "sessions": " ".join(run["sessions"]),
            "skill_commit": run["skill_commit"],
            "skill_commit_date": run["skill_commit_date"],
            "skill_md_bytes": run["skill_md_bytes"],
            "start_ts": state["start"] or run["start"] or "",
            "end_ts": state["end"] or run["end"] or "",
            "wall_clock_minutes": round(minutes, 1) if minutes is not None else "",
            "stages_completed": stages,
            "stages_prepared": state["stages_prepared"],
            "stages_reported": state["stages_reported"],
            "calls": run["calls"],
            "tokens_total": run["tokens_total"],
            "effective_input_equiv": round(run["effective_input_equiv"]),
            "wait_calls": run["waits"],
            "calls_per_stage": round(round_calls / stages, 2) if stages else "",
            "tokens_per_stage": round(round_tokens / stages) if stages else "",
            "effective_tokens_per_stage": round(round_effective / stages) if stages else "",
            "tokens_per_call": round(run["tokens_total"] / run["calls"]) if run["calls"] else "",
            "waits_per_worker_hour": round(run["waits"] / (minutes / 60), 2)
            if minutes and minutes > 0 else "",
        }
        if workflow.name == "grilling":
            row["questions"] = state["questions"]
            row["calls_per_question"] = round(round_calls / state["questions"], 2) if state["questions"] else ""
            row["tokens_per_question"] = round(round_tokens / state["questions"]) if state["questions"] else ""
            row["session_start_calls"] = start_calls
            row["session_start_tokens"] = start_tokens
        row.update(run_timing_columns(stage_timings, workflow))
        row["stage_timings"] = stage_timings
        rows.append(row)
    return rows


def add_worker_usage(rows, workers, workflow):
    for row in rows:
        linked = [s for s in workers if row["run_id"] in s.get("worker_runs", [])
                  and run_project(s["cwd"]) == row["project"]]
        first = None
        for session in linked:
            root = project_root(session["cwd"])
            if root:
                first = iso(read_run_state(root / ".scratch/orchestrator/runs" / row["run_id"],
                                           workflow)["first_question"])
                if first:
                    break
        after_first = {}
        if workflow.name == "grilling":
            for session in linked:
                after_first[id(session)] = sum(
                    c.total for c in restore_calls(session)
                    if first and iso(c.ts) and iso(c.ts) >= first)
        for harness in (None, "claude", "codex"):
            suffix = "_" + harness if harness else ""
            group = [s for s in linked if harness is None or s["harness"] == harness]
            row["worker_sessions" + suffix] = len({s["session_id"] for s in group})
            row["worker_tokens" + suffix] = sum(s["tokens_total"] for s in group)
            if workflow.name == "grilling":
                tokens = sum(after_first[id(s)] for s in group)
                for unit, count in (("round", row["stages_completed"]), ("question", row["questions"])):
                    row["worker_tokens_per_" + unit + suffix] = round(tokens / count) if count else ""


def print_start_summary(sessions, runs, workflow):
    print("\nMedians per start_mode (n = run/session windows; runs = run rows)")
    row_fields = ["calls_per_question", "tokens_per_question"] if workflow.name == "grilling" else []
    row_fields += [k for k in (runs[0] if runs else {}) if k.startswith("worker_")]
    for harness in sorted({s["harness"] for s in sessions}):
        print(f"\n[{harness}]")
        print("start_mode n runs calls/stg tok/stage ctx/call wait% pane% pane-calls/session "
              + " ".join(f.replace("_per_question", "/question") if not f.startswith("worker_") else f
                         for f in row_fields))
        for mode in ("old-start", "new-start", "mixed"):
            rows = [r for r in runs if r["start_mode"] == mode and r["harnesses"] == harness]
            if not rows:
                continue
            keys = {(sid, r["run_id"]) for r in rows for sid in r["sessions"].split()}
            group = [s for s in sessions if s["harness"] == harness and
                     any((s["session_id"][:8], r) in keys for r in s["run_ids"])]

            def row_median(key):
                return median([r[key] for r in rows if r[key] != ""])

            values = [row_median("calls_per_stage"), row_median("tokens_per_stage"),
                      median([s["avg_context_per_call"] for s in group]),
                      median([100 * s["wait_share"] for s in group]),
                      median([100 * s["pane_share"] for s in group]),
                      median([s["purpose_calls"].get("pane-lifecycle", 0) for s in group])]
            values += [row_median(key) for key in row_fields]
            print(f"{mode} {len(group)} {len(rows)} " + " ".join(fmt(v, 1) for v in values))


def write_sessions_csv(sessions: list[dict], out_dir: Path) -> Path:
    categories = sorted({c for s in sessions for c in s["purpose_calls"]},
                        key=lambda c: (CATEGORY_ORDER.index(c) if c in CATEGORY_ORDER else 99, c))
    base = ["harness", "project", "session_id", "start_ts", "end_ts", "run_ids", "skill_commit",
            "skill_commit_date", "skill_md_bytes", "calls", "tokens_total", "input", "output",
            "cache_create", "cache_read", "reasoning", "start_context_tokens",
            "end_context_tokens", "avg_context_per_call", "context_growth_per_call",
            "effective_input_equiv", "wait_share", "pane_share", "path"]
    columns = base + [f"calls_{c}" for c in categories] + [f"tokens_{c}" for c in categories]
    target = out_dir / "orchestrator-usage-sessions.csv"
    with target.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        for session in sorted(sessions, key=lambda s: (s["start_ts"], s["session_id"])):
            row = {k: session.get(k, "") for k in base}
            row["run_ids"] = " ".join(session["run_ids"])
            row["reasoning"] = "" if session["reasoning"] is None else session["reasoning"]
            row["avg_context_per_call"] = round(session["avg_context_per_call"], 1)
            row["context_growth_per_call"] = round(session["context_growth_per_call"], 1)
            row["effective_input_equiv"] = round(session["effective_input_equiv"])
            row["wait_share"] = round(session["wait_share"], 4)
            row["pane_share"] = round(session["pane_share"], 4)
            for c in categories:
                row[f"calls_{c}"] = session["purpose_calls"].get(c, 0)
                row[f"tokens_{c}"] = session["purpose_tokens"].get(c, 0)
            writer.writerow(row)
    return target


def write_runs_csv(rows: list[dict], out_dir: Path) -> Path:
    target = out_dir / "orchestrator-usage-runs.csv"
    columns = [k for k in rows[0] if k != "stage_timings"] if rows else ["run_id"]
    with target.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return target


STAGE_COLUMNS = ["project", "run_id", "skill_commit", "stage", "role", "launch_ts", "capture_ts",
                 "worker_minutes", "gap_minutes", "orchestrator_gap_minutes",
                 "human_wait_minutes", "suite_runs_worker", "suite_minutes_worker",
                 "suite_runs_orchestrator"]


def write_stages_csv(rows: list[dict], out_dir: Path) -> Path:
    target = out_dir / "orchestrator-usage-stages.csv"
    with target.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=STAGE_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            for stage in row.get("stage_timings", []):
                writer.writerow({**{k: row[k] for k in ("project", "run_id", "skill_commit")},
                                 **stage})
    return target


def print_wall_time(runs: list[dict], workflow: Workflow) -> None:
    """Wall-time medians per skill commit over the runs with at least one timed stage.
    Unlike the token columns these do not depend on the harness."""
    timed = [r for r in runs if r.get("stage_timings")
             and (r["workflow"] in ("issue-chain", "") if workflow.name == "issue-chain"
                  else workflow.owns_run(r["run_id"]))]
    if not timed:
        return
    fields = [("total", "wall_clock_minutes"), ("worker", "wall_worker_minutes"),
              ("orch-gap", "wall_orchestrator_gap_minutes"), ("human", "wall_human_wait_minutes")]
    fields += [(role[:8], f"wall_{role}_minutes") for role in workflow.roles]
    fields += [("w-tests", "suite_runs_worker"), ("w-test-m", "suite_minutes_worker"),
               ("o-tests", "suite_runs_orchestrator")]
    header = f"{'commit':<10}{'date':<12}{'runs':>5}" + "".join(f"{label:>10}" for label, _ in fields)
    print()
    print(f"{workflow.subdir} wall time in minutes and test runs, medians per skill commit")
    print("worker = launch to report capture; orch-gap = capture to next launch minus human "
          "wait; w-tests = test-runner summaries in worker logs, o-tests = orchestrator test commands")
    print(header)
    print("-" * len(header))
    groups: dict[str, list[dict]] = {}
    for run in timed:
        groups.setdefault(run["skill_commit"] or "-", []).append(run)
    for commit, rows in sorted(groups.items(),
                               key=lambda kv: (kv[1][0]["skill_commit_date"], kv[0])):
        values = [median([r[key] for r in rows if r[key] not in ("", UNKNOWN)])
                  for _, key in fields]
        print(f"{commit:<10}{rows[0]['skill_commit_date']:<12}{len(rows):>5}"
              + "".join(f"{fmt(v, 1):>10}" for v in values))
    unknown = sum(r["suite_unknown_stages"] or 0 for r in timed)
    stages = sum(len(r["stage_timings"]) for r in timed)
    print(f"{len(timed)} runs with timed stages; {unknown} of {stages} stages have no "
          "recognized test summary in their logs (counted as unknown, not zero)")


def print_summary(sessions: list[dict], runs: list[dict],
                  workflow: Workflow = WORKFLOWS["issue-chain"]) -> None:
    # Sessions that never touched a run directory are skill development or smoke
    # tests; they would distort the per-commit medians.
    scored = [s for s in sessions if s["run_ids"]]
    if workflow.name != "issue-chain":
        # A skill-development session can drive several workflows; it counts where it
        # touched a run of this one, and only with those runs.
        scored = [dict(s, run_ids=[r for r in s["run_ids"] if workflow.owns_run(r)])
                  for s in scored]
        scored = [s for s in scored if s["run_ids"]]
    header = (f"{'commit':<10}{'date':<12}{'skill_md':>9}{'n':>4}{'runs':>6}"
              f"{'start_ctx':>11}{'calls/stg':>11}{'ctx/call':>10}{'tok/stage':>12}{'wait%':>7}{'pane%':>7}")
    print()
    print(f"{workflow.subdir} orchestrator usage, medians per skill commit")
    if workflow.name == "grilling":
        print("calls/stg and tok/stage are per round; the session start is reported below")
    print("harnesses are reported separately - their context levels are not comparable")

    for harness in sorted({s["harness"] for s in scored}):
        by_commit: dict[str, dict] = {}
        for session in (s for s in scored if s["harness"] == harness):
            key = session.get("skill_commit") or "(unknown)"
            group = by_commit.setdefault(key, {
                "date": session.get("skill_commit_date", ""),
                "bytes": session.get("skill_md_bytes", ""),
                "start_context": [], "avg_context": [], "wait_share": [], "pane_share": [],
                "runs": set(),
            })
            group["start_context"].append(session["start_context_tokens"])
            group["avg_context"].append(session["avg_context_per_call"])
            group["wait_share"].append(session["wait_share"])
            group["pane_share"].append(session["pane_share"])
            group["runs"].update(session["run_ids"])
        if not by_commit:
            continue

        per_run_stage: dict[str, list] = {}
        for run in runs:
            if run["calls_per_stage"] != "" and run["skill_commit"] \
                    and run["harnesses"] == harness \
                    and (run["workflow"] in ("issue-chain", "") if workflow.name == "issue-chain"
                         else workflow.owns_run(run["run_id"])):
                per_run_stage.setdefault(run["skill_commit"], []).append(run)

        print()
        print(f"[{harness}]")
        print(header)
        print("-" * len(header))
        for commit, group in sorted(by_commit.items(), key=lambda kv: (kv[1]["date"], kv[0])):
            run_rows = per_run_stage.get(commit, [])
            print(
                f"{commit:<10}{group['date']:<12}{str(group['bytes']):>9}"
                f"{len(group['start_context']):>4}{len(group['runs']):>6}"
                f"{fmt(median(group['start_context'])):>11}"
                f"{fmt(median([r['calls_per_stage'] for r in run_rows]), 1):>11}"
                f"{fmt(median(group['avg_context'])):>10}"
                f"{fmt(median([r['tokens_per_stage'] for r in run_rows])):>12}"
                f"{fmt(median(group['wait_share']) * 100 if group['wait_share'] else None, 1):>7}"
                f"{fmt(median(group['pane_share']) * 100 if group['pane_share'] else None, 1):>7}"
            )

    print_start_summary(sessions, runs, workflow)
    print_wall_time(runs, workflow)

    if workflow.name == "grilling":
        started = [r for r in runs if r["calls"] and r["stages_completed"]]
        print()
        print(f"session start, medians over {len(started)} runs with at least one round: "
              f"{fmt(median([r['session_start_calls'] for r in started]), 1)} calls, "
              f"{fmt(median([r['session_start_tokens'] for r in started]))} tokens")

    missing = [r for r in runs if r["coverage"] == "missing"]
    print()
    print(f"sessions: {len(sessions)}  "
          f"(claude {sum(1 for s in sessions if s['harness'] == 'claude')}, "
          f"codex {sum(1 for s in sessions if s['harness'] == 'codex')})")
    print(f"medians above cover {len(scored)} sessions attached to a run; "
          f"{len(sessions) - len(scored)} run-less sessions are in the CSV only"
          if workflow.name == "issue-chain" else
          f"medians above cover {len(scored)} sessions attached to a {workflow.name} run; "
          f"{len(sessions) - len(scored)} other sessions are in the CSV only")
    staged = [r for r in runs if r["calls_per_stage"] != "" and r["skill_commit"]]
    mixed = [r for r in staged if "+" in r["harnesses"]]
    print(f"runs: {len(runs)}  with transcript: {len(runs) - len(missing)}  "
          f"without transcript: {len(missing)}")
    print(f"per-stage columns rest on {len(staged) - len(mixed)} runs whose directory "
          f"still exists; {len(mixed)} mixed-harness runs are excluded from them")
    for run in missing:
        print(f"  gap: {run['project']} {run['run_id']}")
    print("n = sessions behind a median; a group with n=1 carries no trend information.")
    print("note: reasoning tokens are only reported for codex; "
          "Claude persists thinking blocks empty.")


def fmt(value, digits: int = 0) -> str:
    if value is None or value == "":
        return "-"
    return f"{value:,.{digits}f}"


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--workflow", choices=list(WORKFLOWS), default="issue-chain",
                    help="orchestrator workflow to measure (default: issue-chain)")
    ap.add_argument("--since", help="only sessions starting on or after YYYY-MM-DD")
    ap.add_argument("--project", help="substring filter on the project slug / cwd")
    ap.add_argument("--exclude-project", action="append", default=[],
                    help="exclude project/cwd substrings from medians (repeatable; CSVs retain them)")
    ap.add_argument("--harness", choices=["claude", "codex", "all"], default="all")
    ap.add_argument("--out", default=".", help="output directory for the CSV files")
    ap.add_argument("--no-cache", action="store_true", help="ignore and rewrite the parse cache")
    args = ap.parse_args(argv)

    workflow = WORKFLOWS[args.workflow]
    use_cache = not args.no_cache
    cache_file = cache_path(workflow)
    cache = load_cache(use_cache, cache_file)

    sessions: list[dict] = []
    if CLAUDE_PROJECTS.is_dir():
        sessions += scan(sorted(CLAUDE_PROJECTS.glob("*/*.jsonl")), parse_claude, cache,
                         use_cache, workflow)
    if CODEX_SESSIONS.is_dir():
        sessions += scan(sorted(CODEX_SESSIONS.glob("*/*/*/*.jsonl")), parse_codex, cache,
                         use_cache, workflow)
    save_cache(cache, use_cache, cache_file)

    workers = [s for s in sessions if s.get("worker_runs")]
    assign_skill_version(sessions, SKILL_REPO, workflow.subdir)
    sessions = owned_session_windows(sessions, workflow)
    if args.harness != "all":
        sessions = [s for s in sessions if s["harness"] == args.harness]
    if args.since:
        sessions = [s for s in sessions if s["start_ts"][:10] >= args.since]
    if args.project:
        sessions = [s for s in sessions
                    if args.project in s["project"] or args.project in s["cwd"]]

    if not sessions:
        print("no orchestrator sessions matched", file=sys.stderr)
        return 1

    runs = aggregate_runs(sessions, workflow)
    if args.since:
        runs = [r for r in runs if r["start_ts"][:10] >= args.since]
    add_worker_usage(runs, workers, workflow)

    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    s_csv = write_sessions_csv(sessions, out_dir)
    r_csv = write_runs_csv(runs, out_dir)
    t_csv = write_stages_csv(runs, out_dir)

    excluded = [s for s in sessions if any(
        text in s["project"] or text in s["cwd"] for text in args.exclude_project)]
    excluded_ids = {id(s) for s in excluded}
    scored_sessions = [s for s in sessions if id(s) not in excluded_ids]
    excluded_projects = {run_project(s["cwd"]) for s in excluded}
    scored_runs = [r for r in runs if r["project"] not in excluded_projects
                   and not any(text in r["project"] for text in args.exclude_project)]
    print_summary(scored_sessions, scored_runs, workflow)
    print(f"\nwrote {s_csv}")
    print(f"wrote {r_csv}")
    print(f"wrote {t_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
