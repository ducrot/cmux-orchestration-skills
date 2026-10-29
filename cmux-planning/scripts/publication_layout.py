"""Read-only checks shared by publication and its recovery status."""

from pathlib import Path

from spec_contract import ContractError


def grilling_directory(root: Path) -> bool:
    entry = root / "grilling"
    if entry.is_symlink() or (entry.exists() and not entry.is_dir()):
        raise ContractError(f"invalid publication entry: {entry}")
    return entry.is_dir()


def target_layout(target: Path, *, staged_grilling: bool = False) -> str:
    if target.is_symlink():
        raise ContractError(f"invalid publication target: {target}")
    if not target.exists():
        return "absent"
    if not target.is_dir():
        raise ContractError(f"invalid publication target: {target.name}")
    entries = sorted(p.name for p in target.iterdir())
    if entries == ["grilling"] and grilling_directory(target):
        if staged_grilling:
            raise ContractError("publication is inconsistent: grilling exists in both target and staging")
        return "grilling"
    if not entries and staged_grilling:
        return "empty"
    raise ContractError("publication target already exists; interfering entries: "
                        + (", ".join(entries) or "<empty target>"))


def check_publication_paths(run_dir: Path, state: dict) -> None:
    canonical = run_dir.resolve() / "publication-stage"
    recorded = state.get("staged_tracker")
    if not isinstance(recorded, dict):
        recorded = {}
    staged = Path(recorded.get("path", str(canonical)))
    if staged != canonical or staged.resolve() != canonical or staged.is_symlink():
        raise ContractError("recorded staged tracker path is outside the canonical planning staging directory")
    target = Path(state["approved_tickets"]["target"])
    feature = Path(state["feature_dir"])
    scratch = Path(state["repository"]) / ".scratch"
    if (target != feature or target.parent != scratch or target.resolve() != target
            or scratch.resolve() != scratch):
        raise ContractError("publication target must match the frozen feature folder without path escape")
