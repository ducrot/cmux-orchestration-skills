"""Planning input pointers, including the persisted task.md compatibility format."""
from pathlib import Path

INLINE_SOURCES = {"explicit-text", "conversation-summary"}


def planning_inputs(state: dict) -> list[dict]:
    if "inputs" in state:
        inputs = state["inputs"]
        if not isinstance(inputs, list) or not inputs or not all(isinstance(item, dict) for item in inputs):
            raise ValueError("planning inputs must be a non-empty list of pointers")
        return inputs
    task = state["task"]
    source = task.get("source", "")
    original = source[5:] if source.startswith("file:") else source or task["path"]
    return [{**task, "kind": "task-file", "original_path": original}]


def manifest_kind(state: dict, item: dict) -> str:
    return item["kind"] if "inputs" in state else "task"


def original_display(state: dict, item: dict) -> str:
    original = Path(item["original_path"])
    if original.is_absolute():
        try:
            return str(original.relative_to(Path(state["repository"])))
        except ValueError:
            pass
    return str(original)
