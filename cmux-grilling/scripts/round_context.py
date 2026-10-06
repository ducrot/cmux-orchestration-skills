"""Bounded, shared synthesis context for fresh research workers."""
from __future__ import annotations

import json
import re
from pathlib import Path

from orchestrator_lib import read_json
from worker_readiness import read_events

CONTEXT_LIMIT = 16 * 1024
QUESTION_ID = re.compile(r"R([1-9][0-9]*)Q([1-9][0-9]*)\Z")
LOCAL_ID = re.compile(r"Q[1-9][0-9]*\Z")


def recorded_questions(events: list[dict], number: int, identifier: str | None = None) -> list[dict]:
    return [e["data"] for e in events if e.get("type") == "grill.question"
            and e.get("data", {}).get("round") == number
            and (identifier is None or e["data"].get("id") == identifier)]


def validate_question(data: dict, events: list[dict]) -> None:
    number = data.get("round")
    if type(number) is not int or number < 1 or not LOCAL_ID.fullmatch(str(data.get("id", ""))):
        raise ValueError("grill.question requires a positive round and Q<n> id")
    if not isinstance(data.get("question"), str) or not data["question"].strip():
        raise ValueError("grill.question requires question text")
    deps = data.get("depends_on")
    if not isinstance(deps, list) or any(not isinstance(dep, str) for dep in deps):
        raise ValueError("grill.question requires an explicit depends_on array (empty allowed)")
    if len(deps) != len(set(deps)):
        raise ValueError("depends_on contains duplicates")
    for dep in deps:
        match = QUESTION_ID.fullmatch(dep)
        if not match or int(match[1]) >= number:
            raise ValueError(f"depends_on must name valid earlier RkQj ids: {dep}")
        if len(recorded_questions(events, int(match[1]), f"Q{match[2]}")) != 1:
            raise ValueError(f"depends_on must name one recorded earlier question: {dep}")


def render_context(run_dir: Path, number: int, questions: list[str], digest: Path | None = None) -> Path:
    events = read_events(run_dir)
    dependencies = set()
    for index, question in enumerate(questions, 1):
        matches = recorded_questions(events, number, f"Q{index}")
        if len(matches) != 1 or matches[0].get("question") != question:
            raise ValueError(f"round {number} Q{index} needs one matching grill.question event")
        data = matches[0]
        # An authored digest is the explicit recovery for missing legacy dependency metadata.
        if digest is not None and "depends_on" not in data:
            continue
        validate_question(data, events)
        dependencies.update(data["depends_on"])
    if len(recorded_questions(events, number)) != len(questions):
        raise ValueError("round frontier does not match recorded grill.question events")
    if digest is not None:
        text = digest.read_text(encoding="utf-8")
        if not text.strip():
            raise ValueError("authored neutral digest is empty")
    else:
        text = synthesized_context(run_dir, number, dependencies)
    if len(text.encode("utf-8")) > CONTEXT_LIMIT:
        raise ValueError("round context exceeds 16 KiB UTF-8; supply --context-digest")
    path = run_dir / "prompts" / f"round-{number}-context.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def synthesized_context(run_dir: Path, number: int, dependencies: set[str]) -> str:
    settled = {}
    for previous in range(1, number):
        source = run_dir / "synthesis" / f"round-{previous}.json"
        if not source.is_file():
            raise ValueError(f"missing synthesis metadata: {source}; supply --context-digest")
        payload = read_json(source)
        if not isinstance(payload, dict) or payload.get("round") != previous or not isinstance(payload.get("questions"), list):
            raise ValueError(f"invalid synthesis metadata: {source}; supply --context-digest")
        for item in payload["questions"]:
            if (not isinstance(item, dict) or not LOCAL_ID.fullmatch(str(item.get("id", "")))
                    or not isinstance(item.get("question"), str) or not item["question"].strip()):
                raise ValueError(f"invalid synthesis question: {source}; supply --context-digest")
            identifier = f"R{previous}{item['id']}"
            if identifier in settled:
                raise ValueError(f"duplicate synthesis question: {identifier}")
            settled[identifier] = (item, source)
    missing = dependencies - settled.keys()
    if missing:
        raise ValueError(f"missing synthesis metadata for {','.join(sorted(missing))}; supply --context-digest")
    lines = ["# Earlier-round context", "", "Context to re-verify, not evidence. Do not read earlier lane reports.", ""]
    for identifier, (item, source) in settled.items():
        if identifier in dependencies:
            if (not isinstance(item.get("answer"), str) or not item["answer"].strip()
                    or item.get("confidence") not in ("high", "medium", "low")
                    or not isinstance(item.get("sources"), list)
                    or any(not isinstance(source, str) for source in item["sources"])
                    or not isinstance(item.get("reasoning", ""), str)):
                raise ValueError(f"{identifier} has missing or invalid synthesis metadata; supply --context-digest")
            projection = {key: item[key] for key in ("question", "answer", "confidence", "sources")}
            projection["id"] = identifier
            reasoning = item.get("reasoning", "")
            # The synthesizer classifies caveats/disagreement; never guess semantics
            # from English keywords or silently drop uncertainty in another language.
            if reasoning:
                if type(item.get("reasoning_for_context")) is not bool:
                    raise ValueError(f"{identifier} needs reasoning_for_context metadata; supply --context-digest")
                if item["reasoning_for_context"]:
                    projection["reasoning"] = reasoning
            lines.extend([f"## {identifier} ({source})", json.dumps(projection, ensure_ascii=False), ""])
        else:
            lines.append(f"- {identifier}: {' '.join(item['question'].split())} — {source}")
    return "\n".join(lines) + "\n"
