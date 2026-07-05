#!/usr/bin/env python3
"""autotune_cycle.py — hands-free tuning cycle, designed to run from a SessionEnd hook.

One quiet pass: throttle-check -> corpus eligibility -> fit -> gated apply -> auto-sync the
user-wide install. Every step reuses autotune.py (same gates, same clamps, same ledger).

Hook contract (must never disturb the user's session):
  * ALWAYS exits 0 — any internal failure is recorded as a report file, never raised.
  * Prints nothing unless a change was actually applied; then it emits one line of hook
    JSON ({"systemMessage": ...}) so the user gets a single non-intrusive note.
  * Exits in milliseconds in the common cases (throttled / not enough runs / disabled).
  * Runs ONLY against the repo master: if this file's location is not inside a repo that
    has the test suite (e.g. it's the deployed copy under ~/.claude/skills), it no-ops.
  * A trace file that fails schema validation is moved to the spool's quarantine/ folder
    (never deleted) so one bad file cannot block every future cycle.
"""
from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
import time
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve()
SKILL_DIR = HERE.parents[1]          # .../.claude/skills/aletheia
REPO_ROOT = HERE.parents[4]          # .../<repo>
CONFIG = SKILL_DIR / "reference" / "autotune-config.toml"

sys.path.insert(0, str(HERE.parent))
import autotune  # noqa: E402


def _quiet(fn, cfg, args) -> tuple[int, dict]:
    """Run an autotune cmd_* capturing its stdout JSON instead of printing it."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = fn(cfg, args)
    try:
        payload = json.loads(buf.getvalue())
    except (json.JSONDecodeError, ValueError):
        payload = {"raw": buf.getvalue()}
    return rc, payload


def _eligible(cfg) -> bool:
    spool = autotune._path(cfg, "paths", "runs_dir")
    if not spool.is_dir():
        return False
    glob = cfg.req("paths", "trace_glob")
    schema = cfg.req("schema_version")
    quarantine = spool / "quarantine"
    for _ in range(10):  # self-heal: quarantine bad files, then re-check
        try:
            runs = autotune.load_traces(spool, glob, schema)
            break
        except ValueError as e:
            name = str(e).split(":", 1)[0].strip()
            bad = spool / name
            if not bad.is_file():
                return False  # unparseable error shape — stand down, leave data alone
            quarantine.mkdir(parents=True, exist_ok=True)
            shutil.move(str(bad), str(quarantine / bad.name))
    else:
        return False
    if not runs:
        return False
    w = cfg.req("trigger", "inconclusive_weight")
    weight = sum(w if r["final"]["inconclusive"] else 1.0 for r in runs.values())
    return weight >= cfg.req("trigger", "min_completed_runs")


def _sync_user_install(cfg) -> None:
    dst = autotune._path(cfg, "paths", "user_install_dir")
    shutil.copytree(SKILL_DIR, dst, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__"))


def main() -> int:
    try:
        # Master-repo guard: never run from a deployed copy.
        if not (REPO_ROOT / "tests").is_dir() or not CONFIG.is_file():
            return 0
        cfg = autotune.load_config(CONFIG)
        if not cfg.req("automation", "enabled"):
            return 0

        # Throttle.
        marker = autotune._path(cfg, "automation", "marker_file")
        window = cfg.req("automation", "min_interval_hours") * 3600
        if marker.is_file() and (time.time() - marker.stat().st_mtime) < window:
            return 0
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()

        import os
        os.chdir(REPO_ROOT)  # repo-relative config paths (prior, ledger, fixtures) resolve

        if not _eligible(cfg):
            return 0

        rc, fit = _quiet(autotune.cmd_fit, cfg, SimpleNamespace(source="runs"))
        proposal_file = fit.get("proposal_file")
        if rc != 0 or not proposal_file or fit.get("proposed_changes") in (
                None, "none (fit within rounding of current)"):
            return 0  # honest no-op: corpus didn't justify any change

        rc, applied = _quiet(autotune.cmd_apply, cfg,
                             SimpleNamespace(proposal=proposal_file))
        if rc == 0 and applied.get("applied"):
            if cfg.req("automation", "auto_sync"):
                _sync_user_install(cfg)
            print(json.dumps({"systemMessage": (
                "Aletheia quietly recalibrated itself from your recent investigations "
                "(details in its tuning ledger). Nothing you need to do.")}))
        # Rejected proposals: cmd_apply already wrote an apply-rejected report. Silence.
        return 0
    except Exception:
        # A hook must never disturb the session. Best-effort error report, then quiet exit.
        try:
            report = REPO_ROOT / "runs" / "tuning-reports"
            report.mkdir(parents=True, exist_ok=True)
            import traceback
            (report / "cycle-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        except Exception:
            pass
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
