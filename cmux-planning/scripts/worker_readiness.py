#!/usr/bin/env python3
"""Screen-bound delivery gates; vendored identically for standalone skill installs.

The orchestrator judges screens. This module enforces observation, explicit assessment,
short-lived one-use readiness, and scoped dialog responses; it never guesses from a prompt glyph.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from pathlib import Path

MAX_AGE_SECONDS = 60
STATES = ("ready", "loading", "prompt", "failed", "unknown")
VERBS = ("observe", "assess", "respond")


class ReadinessError(ValueError):
    pass


def add_commands(subparsers, *, parents=(), selector=None):
    for verb in VERBS:
        parser = subparsers.add_parser(verb, parents=list(parents))
        if not parents:
            parser.add_argument("--run-dir", required=True)
            parser.add_argument("--surface", required=True)
            parser.add_argument("--" + selector, required=True)
            if selector == "role":
                parser.add_argument("--pass", dest="pass_num", type=int, required=True)
        if verb != "observe":
            parser.add_argument("--observation", required=True)
            parser.add_argument("--reason", required=True)
        if verb == "assess":
            parser.add_argument("--state", required=True, choices=STATES)
        if verb == "respond":
            parser.add_argument("--key", required=True,
                                choices=("enter", "up", "down", "left", "right", "escape", "tab", "1", "2", "3"))


def read_events(run_dir):
    path = Path(run_dir) / "events.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def selector(args):
    for key in ("stage", "role", "lane"):
        value = getattr(args, key, None)
        if value is not None:
            result = {key: value}
            if key != "lane":
                result["pass"] = args.pass_num
            return result
    raise ReadinessError("worker identity required: stage/pass, role/pass, or lane")


def context(events, identity, surface):
    if not surface or surface.startswith("surface:"):
        raise ReadinessError("readiness requires the stable surface UUID, not a positional ref")
    matching = [(i, e) for i, e in enumerate(events)
                if all(e.get("data", {}).get(k) == v for k, v in identity.items())]
    launches = [(i, e) for i, e in matching if e.get("type") == "pane.launched"]
    floor = -1
    if launches:
        floor, launch = launches[-1]
        if launch["data"].get("surface_id") != surface:
            raise ReadinessError("worker was replaced; use its latest recorded surface UUID")
    scoped = [(i, e) for i, e in matching if i > floor and e.get("data", {}).get("surface_id") == surface]
    boundary = [(i, e) for i, e in scoped if e.get("type") in
                ("worker.starting", "worker.launch_sent", "pane.closed")]
    if not boundary or boundary[-1][1]["type"] != "worker.launch_sent":
        raise ReadinessError("no confirmed launch command for this worker; inspect startup before continuing")
    index, launch = boundary[-1]
    surface_boundaries = [(i, e) for i, e in enumerate(events)
                          if e.get("data", {}).get("surface_id") == surface
                          and e.get("type") in ("worker.starting", "worker.launch_sent", "pane.closed")]
    if surface_boundaries and surface_boundaries[-1][0] != index:
        raise ReadinessError("surface was closed or reused by another worker; inspect the current worker")
    # Legacy runs can be inspected safely, but gain no readiness from their old launch event.
    launch_id = launch["data"].get("launch_id") or hashlib.sha256(
        json.dumps([index, launch], sort_keys=True).encode()).hexdigest()
    return launch_id, [e for i, e in scoped if i > index]


def fresh(data):
    age = time.time() - data.get("observed_at", 0)
    return 0 <= age <= MAX_AGE_SECONDS


def screen_hash(screen):
    return hashlib.sha256(screen.encode()).hexdigest()


# Codex 0.154 can draw single-dot Braille particles in its otherwise empty composer.
# Scope normalization to that observed UI band, never arbitrary text, spinners, or dialogs.
CODEX_PARTICLES = "⠁⠂⠄⡀⠈⠐⠠⢀"
CODEX_EMPTY_COMPOSER = "› Ask Codex to do anything"


def screen_fingerprint(screen):
    lines = screen.splitlines()
    if not any("OpenAI Codex (v" in line for line in lines):
        return screen_hash(screen)
    particle_row = re.compile("[ " + CODEX_PARTICLES + "]*")
    for index, line in enumerate(lines):
        # Particles can replace the blank immediately after the composer caret as well.
        plain = line.translate(str.maketrans({dot: " " for dot in CODEX_PARTICLES}))
        if " ".join(plain.split()) != CODEX_EMPTY_COMPOSER:
            continue
        # Normalize only the empty composer and its immediately adjacent background rows.
        lines[index] = CODEX_EMPTY_COMPOSER
        for step in (-1, 1):
            neighbor = index + step
            while 0 <= neighbor < len(lines) and particle_row.fullmatch(lines[neighbor]):
                lines[neighbor] = ""
                neighbor += step
    return screen_hash("\n".join(lines))


def readiness_status(events, identity, surface):
    try:
        launch_id, later = context(events, identity, surface)
    except ReadinessError:
        return "unverified"
    relevant = [e for e in later if e.get("type") in
                ("worker.observed", "worker.ready", "worker.startup_status",
                 "worker.readiness_consumed", "worker.dialog_response")]
    if not relevant:
        return "unverified"
    last = relevant[-1]
    data = last.get("data", {})
    if data.get("launch_id") != launch_id or not fresh(data):
        return "unverified"
    if last["type"] == "worker.ready":
        return "ready"
    if last["type"] == "worker.startup_status":
        return data["state"]
    return "unverified"


class Gate:
    def __init__(self, args, workspace, call, record):
        self.args = args
        self.run_dir = Path(args.run_dir)
        self.identity = selector(args)
        self.surface = args.surface
        self.call = call
        self.record = record
        self.target = ["--workspace", workspace, "--surface", self.surface]

    def emit(self, kind, data):
        self.record(self.run_dir, kind, "interactive worker readiness", {
            **self.identity, "surface_id": self.surface, **data})

    def screen(self):
        return self.call(self.args, ["read-screen", *self.target, "--lines", "80"]).stdout

    def current(self):
        return context(read_events(self.run_dir), self.identity, self.surface)

    def observe(self):
        launch_id, _ = self.current()
        screen = self.screen()
        data = {"launch_id": launch_id, "observation_id": str(uuid.uuid4()),
                "observed_at": time.time(), "screen_sha256": screen_hash(screen),
                "screen_fingerprint_sha256": screen_fingerprint(screen)}
        # Persist only the digest; dialogs can contain account details.
        self.emit("worker.observed", data)
        print(json.dumps({**data, "screen": screen, "next": "assess this screen before any delivery"}))

    def observation(self, observation_id, *, recheck=True):
        launch_id, later = self.current()
        relevant = [e for e in later if e.get("type") in
                    ("worker.observed", "worker.readiness_consumed", "worker.dialog_response")]
        if not relevant or relevant[-1]["type"] != "worker.observed":
            raise ReadinessError("observe this worker before assessing or responding")
        data = relevant[-1]["data"]
        if data.get("observation_id") != observation_id or data.get("launch_id") != launch_id or not fresh(data):
            raise ReadinessError("observation expired or was superseded; observe again")
        if recheck and screen_fingerprint(self.screen()) != data.get("screen_fingerprint_sha256", data["screen_sha256"]):
            self.emit("worker.readiness_consumed", data)
            raise ReadinessError("screen changed; observe and assess again before sending anything")
        return data

    def assess(self):
        if not self.args.reason.strip():
            raise ReadinessError("assessment requires a concrete reason")
        # Non-ready assessments authorize no input and remain valid descriptions of the
        # observed frame even while startup is animating. Responses recheck before input.
        data = self.observation(self.args.observation, recheck=self.args.state == "ready")
        self.emit("worker.ready" if self.args.state == "ready" else "worker.startup_status",
                  {**data, "state": self.args.state, "reason": self.args.reason})
        print(json.dumps({"state": self.args.state, "observation_id": self.args.observation}))

    def respond(self):
        if not self.args.reason.strip():
            raise ReadinessError("dialog response requires its authorization and reason")
        data = self.observation(self.args.observation)
        _, later = self.current()
        assessments = [e for e in later if e.get("type") in ("worker.ready", "worker.startup_status")]
        if not assessments or assessments[-1]["data"].get("state") != "prompt" or assessments[-1]["data"].get("observation_id") != self.args.observation:
            raise ReadinessError("respond requires a current assessment of state prompt")
        # Invalidate before input; even a failed send may have reached the terminal.
        self.emit("worker.dialog_response", {**data, "key": self.args.key, "reason": self.args.reason})
        self.call(self.args, ["send-key", *self.target, self.args.key])
        self.observe()

    def consume(self):
        events = read_events(self.run_dir)
        if readiness_status(events, self.identity, self.surface) != "ready":
            raise ReadinessError("delivery blocked: observe and assess --state ready for this worker first")
        _, later = self.current()
        ready = [e for e in later if e.get("type") == "worker.ready"][-1]["data"]
        self.observation(ready["observation_id"])
        self.emit("worker.readiness_consumed", ready)

    def run(self):
        getattr(self, self.args.command)()
        return 0


def begin_start(args, record, data):
    # Invalidates readiness before launch IO, including partially failed restarts.
    data = {**data, "launch_id": str(uuid.uuid4())}
    record(Path(args.run_dir), "worker.starting", "launch input about to be sent", data)
    return data
