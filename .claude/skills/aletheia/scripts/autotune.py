#!/usr/bin/env python3
"""autotune.py — offline statistical recalibration for Aletheia (Approach A).

Implements docs/statistical-recalibration-implementation-plan.md:
  status  — corpus stats + trigger readiness
  replay  — deterministic re-computation of recorded traces (champion or candidate params)
  fit     — Dawid–Skene-style EM + Beta shrinkage + clamps -> proposal JSON (applies nothing)
  apply   — gates (replay dominance, pytest, confidence invariant) -> surgical prior patch
            -> ledger append -> trace archive -> user-install sync reminder
  audit   — VOI-honesty + gate-statistics report (report-only; thresholds never auto-applied)

Design contracts:
  * stdlib only; belief math is IMPORTED from pomdp_belief.py (parity by construction).
  * ZERO configuration defaults in code: every parameter comes from autotune-config.toml;
    a missing key raises ConfigError naming it. `.get(key, default)` on config is banned.
  * The only files ever written outside runs/: numeric literals in the prior file's
    sensor/threshold lines (guarded, atomic) and a tuning-ledger append.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pomdp_belief as pb  # noqa: E402  (bayes_update, entropy, normalized_entropy, _update_one)


# ---------------------------------------------------------------- config

class ConfigError(Exception):
    """A required configuration key is missing or invalid."""


class Cfg:
    """Fail-fast config accessor: no defaults, ever."""

    def __init__(self, data: dict, path: Path):
        self._data, self._path = data, path

    def req(self, *keys):
        cur = self._data
        for k in keys:
            if not isinstance(cur, dict) or k not in cur:
                raise ConfigError(
                    f"missing required config key: {'.'.join(keys)} (in {self._path})")
            cur = cur[k]
        return cur


def load_config(path: str | Path) -> Cfg:
    p = Path(path)
    if not p.is_file():
        raise ConfigError(f"config file not found: {p}")
    with open(p, "rb") as f:
        return Cfg(tomllib.load(f), p)


# ---------------------------------------------------------------- prior file parse/patch

SENSOR_LINE = re.compile(
    r"^(?P<prefix>- Action `(?P<name>search:\w+)`\s+reveals \[[^\]]+\]\s+reliability: )"
    r"(?P<val>\d+\.\d+)(?P<rest>.*)$")
THRESHOLD_LINE = re.compile(
    r"^(?P<prefix>- (?P<name>confidence_floor|entropy_explore_above|max_iterations): )"
    r"(?P<val>\d+(?:\.\d+)?)(?P<rest>.*)$")


def parse_prior(text: str) -> dict:
    """Parse sensor reliabilities + numeric thresholds out of environment-prior.md.

    Returns {"lines": [...], "sensors": {name: {value, idx, prefix, raw, rest}},
             "thresholds": {...same shape...}}. Raises on an empty parse (grammar drift).
    """
    lines = text.splitlines(keepends=True)
    sensors, thresholds = {}, {}
    for i, line in enumerate(lines):
        body = line.rstrip("\r\n")
        eol = line[len(body):]
        m = SENSOR_LINE.match(body)
        if m:
            sensors[m.group("name")] = {
                "value": float(m.group("val")), "idx": i, "prefix": m.group("prefix"),
                "raw": m.group("val"), "rest": m.group("rest"), "eol": eol}
            continue
        m = THRESHOLD_LINE.match(body)
        if m:
            thresholds[m.group("name")] = {
                "value": float(m.group("val")), "idx": i, "prefix": m.group("prefix"),
                "raw": m.group("val"), "rest": m.group("rest"), "eol": eol}
    if not sensors or not thresholds:
        raise ValueError(
            "prior-file grammar drift: parsed "
            f"{len(sensors)} sensors / {len(thresholds)} thresholds — refusing to proceed")
    return {"lines": lines, "sensors": sensors, "thresholds": thresholds}


def serialize_prior(parsed: dict) -> str:
    """Reconstruct the file from parsed components (round-trip guard support)."""
    lines = list(parsed["lines"])
    for group in (parsed["sensors"], parsed["thresholds"]):
        for item in group.values():
            lines[item["idx"]] = item["prefix"] + item["raw"] + item["rest"] + item["eol"]
    return "".join(lines)


def roundtrip_guard(text: str, parsed: dict) -> None:
    if serialize_prior(parsed) != text:
        raise ValueError("round-trip guard failed: parse->serialize is not byte-identical")


def patch_prior(prior_path: Path, new_reliabilities: dict[str, float]) -> list[str]:
    """Surgically replace reliability literals. Returns human-readable change list.

    Guards: round-trip before patch; post-patch diff must touch exactly the intended lines.
    Atomic write (temp file + replace).
    """
    text = prior_path.read_text(encoding="utf-8")
    parsed = parse_prior(text)
    roundtrip_guard(text, parsed)

    changes, intended_idx = [], set()
    lines = list(parsed["lines"])
    for name, new_val in new_reliabilities.items():
        if name not in parsed["sensors"]:
            raise ValueError(f"write-path guard: unknown sensor {name!r} — refusing")
        item = parsed["sensors"][name]
        new_raw = f"{new_val:.2f}"
        if new_raw == item["raw"]:
            continue
        lines[item["idx"]] = item["prefix"] + new_raw + item["rest"] + item["eol"]
        intended_idx.add(item["idx"])
        changes.append(f"{name}: {item['raw']} -> {new_raw}")

    new_text = "".join(lines)
    old_lines, cur_lines = text.splitlines(), new_text.splitlines()
    if len(old_lines) != len(cur_lines):
        raise ValueError("write-path guard: line count changed — refusing")
    diff_idx = {i for i, (a, b) in enumerate(zip(old_lines, cur_lines)) if a != b}
    if diff_idx != intended_idx:
        raise ValueError(
            f"write-path guard: unexpected lines changed {sorted(diff_idx - intended_idx)}")

    if changes:
        tmp = prior_path.with_suffix(".md.tmp")
        tmp.write_text(new_text, encoding="utf-8")
        tmp.replace(prior_path)
    return changes


# ---------------------------------------------------------------- trace loading

def load_traces(directory: Path, glob: str, expected_schema: int) -> dict[str, dict]:
    """Load JSONL traces -> {run_id: {"turns": [...], "final": {...}}}."""
    runs: dict[str, dict] = {}
    for path in sorted(directory.glob(glob)):
        with open(path, encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                if rec.get("schema_version") != expected_schema:
                    raise ValueError(
                        f"{path.name}:{line_no}: schema_version "
                        f"{rec.get('schema_version')!r} != expected {expected_schema}")
                run = runs.setdefault(rec["run_id"], {"turns": [], "final": None})
                if rec["type"] == "turn":
                    run["turns"].append(rec)
                elif rec["type"] == "final":
                    run["final"] = rec
    for run_id, run in runs.items():
        run["turns"].sort(key=lambda r: r["turn"])
        if run["final"] is None:
            raise ValueError(f"run {run_id}: missing final record")
        # Enforce the schema's turn-1 rule: the first turn must record the starting prior
        # for EVERY question dimension. Without it, a dimension that only ever saw null
        # observations has no recoverable value vocabulary, and replay/fit would silently
        # drop it — a wrong-but-quiet result. Fail loudly instead (G3: garbage traces
        # must never become quiet tuning input).
        if run["turns"]:
            first = run["turns"][0]
            missing = [d for d in first.get("question_dims", [])
                       if d not in first.get("prior", {})]
            if missing:
                raise ValueError(
                    f"run {run_id}: turn 1 violates the schema's turn-1 rule — no starting "
                    f"prior recorded for question dimension(s) {missing}; the run is not "
                    f"reconstructable offline (see reference/trace-schema.md)")
    return runs


def dim_values(run: dict) -> dict[str, list[str]]:
    """Recover each dimension's value vocabulary from recorded priors."""
    vocab: dict[str, list[str]] = {}
    for t in run["turns"]:
        for dim, dist in t.get("prior", {}).items():
            vocab.setdefault(dim, list(dist.keys()))
    return vocab


# ---------------------------------------------------------------- replay core

def replay_run(run: dict, reliabilities: dict[str, float],
               floor: float, entropy_gate: float) -> dict:
    """Deterministically re-compute one run under the given sensor reliabilities.

    Returns per-dimension finals at the candidate stop point, committed flags,
    turns_to_stop, and the max deviation from the recorded posteriors (champion parity).
    """
    qdims = run["turns"][0]["question_dims"] if run["turns"] else []
    vocab = dim_values(run)
    belief = {d: {v: 1.0 / len(vocab[d]) for v in vocab[d]} for d in vocab}
    max_dev, stop_turn = 0.0, None

    def committed(d):
        conf = max(belief[d].values())
        return conf >= floor and pb.normalized_entropy(belief[d]) <= entropy_gate

    snapshots = []
    for t in run["turns"]:
        for dim, val in t.get("points_at", {}).items():
            rel = reliabilities[t["sensor"]]
            belief[dim] = pb._update_one(vocab[dim], belief[dim], val, rel)
            for v, p_rec in t["posterior"].get(dim, {}).items():
                max_dev = max(max_dev, abs(belief[dim][v] - p_rec))
        snapshots.append({d: dict(belief[d]) for d in belief})
        tracked = [d for d in qdims if d in belief]
        if stop_turn is None and tracked and all(committed(d) for d in tracked):
            stop_turn = t["turn"]

    turns_to_stop = stop_turn if stop_turn is not None else run["final"]["turns_total"]
    final_belief = snapshots[turns_to_stop - 1] if snapshots else belief
    result = {}
    for d, dist in final_belief.items():
        conf = max(dist.values())
        lead = max(dist, key=dist.get)
        tie = len({round(p, 12) for p in dist.values()}) == 1
        result[d] = {
            "leading": None if tie else lead,
            "confidence": conf,
            "entropy_norm": pb.normalized_entropy(dist),
            "committed": conf >= floor and pb.normalized_entropy(dist) <= entropy_gate,
        }
    return {"dims": result, "turns_to_stop": turns_to_stop,
            "max_deviation_vs_recorded": max_dev}


def evaluate_dominance(runs: dict, champion_rel: dict, candidate_rel: dict,
                       floor: float, entropy_gate: float,
                       acceptance: dict, max_conf_shift: float) -> dict:
    """Proposal §5.3 (a)–(e) as named booleans."""
    champ = {rid: replay_run(run, champion_rel, floor, entropy_gate)
             for rid, run in runs.items()}
    cand = {rid: replay_run(run, candidate_rel, floor, entropy_gate)
            for rid, run in runs.items()}

    flips_vs_ground_truth, uncommitted_regressions, acceptance_failures = [], [], []
    conf_pairs = []

    for rid, run in runs.items():
        gt = run["final"].get("ground_truth") or {}
        for d, want in gt.items():
            if d in cand[rid]["dims"] and cand[rid]["dims"][d]["leading"] != want:
                flips_vs_ground_truth.append(f"{rid}/{d}: leading != ground truth {want!r}")
        for d, ch in champ[rid]["dims"].items():
            ca = cand[rid]["dims"][d]
            if ch["committed"] and not ca["committed"]:
                uncommitted_regressions.append(f"{rid}/{d}")
            if ch["committed"] and ca["committed"]:
                conf_pairs.append(ca["confidence"] - ch["confidence"])
        for d, want in acceptance.get(rid, {}).items():
            if d.startswith("_"):
                continue
            ca = cand[rid]["dims"].get(d)
            if ca is None or ca["leading"] != want["leading"] or ca["committed"] != want["committed"]:
                acceptance_failures.append(
                    f"{rid}/{d}: got leading={ca['leading'] if ca else None} "
                    f"committed={ca['committed'] if ca else None}, "
                    f"expected {want['leading']!r}/{want['committed']}")

    mean_turns_champ = sum(c["turns_to_stop"] for c in champ.values()) / len(champ)
    mean_turns_cand = sum(c["turns_to_stop"] for c in cand.values()) / len(cand)
    mean_conf_shift = (sum(conf_pairs) / len(conf_pairs)) if conf_pairs else 0.0

    checks = {
        "a_no_flip_vs_ground_truth": not flips_vs_ground_truth,
        "b_mean_turns_not_increased": mean_turns_cand <= mean_turns_champ,
        "c_no_commit_regressions": not uncommitted_regressions,
        "d_acceptance_criteria_hold": not acceptance_failures,
        "e_confidence_invariant": mean_conf_shift <= max_conf_shift,
    }
    return {
        "checks": checks, "dominates": all(checks.values()),
        "detail": {
            "flips_vs_ground_truth": flips_vs_ground_truth,
            "commit_regressions": uncommitted_regressions,
            "acceptance_failures": acceptance_failures,
            "mean_turns": {"champion": mean_turns_champ, "candidate": mean_turns_cand},
            "mean_confidence_shift": mean_conf_shift,
        },
        "champion": {rid: r["dims"] for rid, r in champ.items()},
        "candidate": {rid: r["dims"] for rid, r in cand.items()},
    }


# ---------------------------------------------------------------- EM fit

def em_fit(runs: dict, current_rel: dict[str, float], pseudo_count: float,
           max_iter: int, tol: float, min_obs: int) -> dict:
    """Dawid–Skene-style EM with Beta shrinkage anchored at current reliabilities.

    Items = (run_id, dim); votes = (sensor, value). Returns fitted (unclamped) values
    plus per-sensor evidence. Deterministic (seeded by the current reliabilities).
    """
    items: dict[tuple, list] = {}
    vocab_by_item: dict[tuple, list[str]] = {}
    for rid, run in runs.items():
        vocab = dim_values(run)
        for t in run["turns"]:
            for dim, val in t.get("points_at", {}).items():
                key = (rid, dim)
                items.setdefault(key, []).append((t["sensor"], val))
                vocab_by_item[key] = vocab[dim]

    counts: dict[str, int] = {}
    for votes in items.values():
        for s, _ in votes:
            counts[s] = counts.get(s, 0) + 1
    fit_sensors = {s for s, n in counts.items() if n >= min_obs}

    r = dict(current_rel)
    iterations = 0
    for iterations in range(1, max_iter + 1):
        agree = {s: 0.0 for s in fit_sensors}
        total = {s: 0 for s in fit_sensors}
        for key, votes in items.items():
            vals = vocab_by_item[key]
            belief = {v: 1.0 / len(vals) for v in vals}
            for s, v in votes:
                belief = pb.bayes_update(
                    belief, pb.likelihood_from_sensor(vals, v, r[s]))
            for s, v in votes:
                if s in fit_sensors:
                    agree[s] += belief[v]
                    total[s] += 1
        r_new = dict(r)
        for s in fit_sensors:
            r_new[s] = ((agree[s] + pseudo_count * current_rel[s])
                        / (total[s] + pseudo_count))
        delta = max((abs(r_new[s] - r[s]) for s in fit_sensors), default=0.0)
        r = r_new
        if delta < tol:
            break

    return {
        "fitted": r, "iterations": iterations,
        "evidence": {s: {"votes": counts.get(s, 0),
                         "in_fit": s in fit_sensors,
                         "current": current_rel[s],
                         "fitted_raw": r[s]} for s in current_rel},
    }


def clamp_fit(fitted: dict, current: dict, max_delta: float,
              floor: float, ceiling: float) -> dict:
    """Apply per-cycle clamps + absolute bounds; round to the file's 2-dp grid.

    Returns {sensor: {current, proposed, clamped: bool}} for real changes only.
    """
    out = {}
    for s, cur in current.items():
        raw = fitted[s]
        lo, hi = max(cur - max_delta, floor), min(cur + max_delta, ceiling)
        clamped_val = min(max(raw, lo), hi)
        proposed = round(clamped_val, 2)
        if f"{proposed:.2f}" != f"{cur:.2f}":
            out[s] = {"current": cur, "proposed": proposed,
                      "fitted_raw": raw, "clamped": clamped_val != raw}
    return out


# ---------------------------------------------------------------- subcommand helpers

def _now() -> str:
    return _dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def _path(cfg: Cfg, *keys) -> Path:
    """Config path accessor: supports `~` for user-local paths (e.g. the telemetry spool)."""
    return Path(cfg.req(*keys)).expanduser()


def _write_report(cfg: Cfg, stem: str, payload: dict) -> Path:
    rdir = _path(cfg, "paths", "reports_dir")
    rdir.mkdir(parents=True, exist_ok=True)
    path = rdir / f"{stem}-{_now()}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    keep = cfg.req("reports", "keep_last")
    reports = sorted(rdir.glob("*.json"))
    for old in reports[:-keep] if len(reports) > keep else []:
        old.unlink()
    return path


def _corpus(cfg: Cfg, source: str) -> dict:
    schema = cfg.req("schema_version")
    if source == "runs":
        directory = _path(cfg, "paths", "runs_dir")
    elif source == "fixtures":
        directory = _path(cfg, "gates", "fixtures_dir")
    else:
        raise ValueError(f"unknown --source {source!r}")
    return load_traces(directory, cfg.req("paths", "trace_glob"), schema)


def _prior(cfg: Cfg) -> tuple[Path, dict]:
    path = _path(cfg, "paths", "prior_file")
    text = path.read_text(encoding="utf-8")
    parsed = parse_prior(text)
    roundtrip_guard(text, parsed)
    return path, parsed


def _reliabilities(parsed: dict) -> dict[str, float]:
    return {name: item["value"] for name, item in parsed["sensors"].items()}


def _thresholds(parsed: dict) -> tuple[float, float]:
    return (parsed["thresholds"]["confidence_floor"]["value"],
            parsed["thresholds"]["entropy_explore_above"]["value"])


def _acceptance(cfg: Cfg) -> dict:
    path = _path(cfg, "gates", "acceptance_criteria_file")
    data = json.loads(path.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def _candidate_from_proposal(champion: dict, proposal: dict) -> dict:
    cand = dict(champion)
    for s, entry in proposal["deltas"].items():
        if s not in cand:
            raise ValueError(f"proposal names unknown sensor {s!r}")
        cand[s] = entry["proposed"]
    return cand


# ---------------------------------------------------------------- subcommands

def cmd_status(cfg: Cfg, args) -> int:
    runs = _corpus(cfg, "runs")
    w = cfg.req("trigger", "inconclusive_weight")
    eligible = sum(w if r["final"]["inconclusive"] else 1.0 for r in runs.values())
    need = cfg.req("trigger", "min_completed_runs")
    votes: dict[str, int] = {}
    for run in runs.values():
        for t in run["turns"]:
            if t.get("points_at"):
                votes[t["sensor"]] = votes.get(t["sensor"], 0) + len(t["points_at"])
    out = {"runs_found": len(runs), "eligible_weight": eligible,
           "min_completed_runs": need, "trigger_ready": eligible >= need,
           "sensor_votes": votes}
    print(json.dumps(out, indent=2))
    return 0


def cmd_replay(cfg: Cfg, args) -> int:
    runs = _corpus(cfg, args.source)
    if not runs:
        print(json.dumps({"error": f"no traces found in --source {args.source}"}))
        return 1
    _, parsed = _prior(cfg)
    champion = _reliabilities(parsed)
    floor, egate = _thresholds(parsed)

    if args.proposal:
        proposal = json.loads(Path(args.proposal).read_text(encoding="utf-8"))
        candidate = _candidate_from_proposal(champion, proposal)
        report = evaluate_dominance(
            runs, champion, candidate, floor, egate, _acceptance(cfg),
            cfg.req("gates", "max_mean_confidence_shift"))
    else:
        detail = {rid: replay_run(run, champion, floor, egate)
                  for rid, run in runs.items()}
        report = {
            "mode": "champion-parity",
            "max_deviation_vs_recorded": max(
                r["max_deviation_vs_recorded"] for r in detail.values()),
            "runs": {rid: {"turns_to_stop": r["turns_to_stop"], "dims": r["dims"]}
                     for rid, r in detail.items()},
        }
    path = _write_report(cfg, "replay", report)
    print(json.dumps({**report, "report_file": str(path)}, indent=2))
    return 0


def cmd_fit(cfg: Cfg, args) -> int:
    runs = _corpus(cfg, args.source)
    if not runs:
        print(json.dumps({"error": f"no traces found in --source {args.source}"}))
        return 1
    _, parsed = _prior(cfg)
    current = _reliabilities(parsed)
    fit = em_fit(runs, current,
                 pseudo_count=cfg.req("em", "shrinkage_pseudo_count"),
                 max_iter=cfg.req("em", "max_iterations"),
                 tol=cfg.req("em", "convergence_tol"),
                 min_obs=cfg.req("em", "min_observations"))
    deltas = clamp_fit(fit["fitted"], current,
                       max_delta=cfg.req("clamps", "max_reliability_delta"),
                       floor=cfg.req("clamps", "reliability_floor"),
                       ceiling=cfg.req("clamps", "reliability_ceiling"))
    proposal = {
        "created": _now(), "source": args.source,
        "corpus_runs": sorted(runs.keys()),
        "em_iterations": fit["iterations"],
        "deltas": deltas, "evidence": fit["evidence"],
    }
    path = _write_report(cfg, "fit-proposal", proposal)
    summary = {s: f"{d['current']:.2f} -> {d['proposed']:.2f}" for s, d in deltas.items()}
    print(json.dumps({"proposal_file": str(path),
                      "proposed_changes": summary or "none (fit within rounding of current)",
                      "em_iterations": fit["iterations"]}, indent=2))
    return 0


def cmd_apply(cfg: Cfg, args) -> int:
    proposal = json.loads(Path(args.proposal).read_text(encoding="utf-8"))
    if not proposal["deltas"]:
        print(json.dumps({"applied": False, "reason": "proposal contains no changes"}))
        return 0
    prior_path, parsed = _prior(cfg)
    champion = _reliabilities(parsed)
    floor, egate = _thresholds(parsed)
    candidate = _candidate_from_proposal(champion, proposal)
    gates: dict[str, bool] = {}

    if cfg.req("gates", "require_replay_dominance"):
        fixtures = load_traces(_path(cfg, "gates", "fixtures_dir"),
                               cfg.req("paths", "trace_glob"), cfg.req("schema_version"))
        dom = evaluate_dominance(fixtures, champion, candidate, floor, egate,
                                 _acceptance(cfg),
                                 cfg.req("gates", "max_mean_confidence_shift"))
        gates.update(dom["checks"])
        gates["replay_dominance"] = dom["dominates"]
    if cfg.req("gates", "require_pytest"):
        proc = subprocess.run(cfg.req("gates", "pytest_command"),
                              shell=True, capture_output=True, text=True)
        gates["pytest"] = proc.returncode == 0

    if not all(gates.values()):
        report = {"applied": False, "gates": gates}
        path = _write_report(cfg, "apply-rejected", report)
        print(json.dumps({**report, "report_file": str(path)}, indent=2))
        return 1

    changes = patch_prior(prior_path,
                          {s: d["proposed"] for s, d in proposal["deltas"].items()})

    ledger = _path(cfg, "paths", "ledger_file")
    text = ledger.read_text(encoding="utf-8")
    date = _dt.date.today().isoformat()
    gate_str = " ".join(f"{k}✓" for k in gates)
    row = (f"| {date} | autotune apply: {'; '.join(changes)} | "
           f"EM recalibration cycle over {len(proposal['corpus_runs'])} runs "
           f"({', '.join(proposal['corpus_runs'])}) | gates: {gate_str} |\n")
    ledger.write_text(text + ("" if text.endswith("\n") else "\n") + row, encoding="utf-8")

    archive = _path(cfg, "paths", "archive_dir")
    archive.mkdir(parents=True, exist_ok=True)
    runs_dir = _path(cfg, "paths", "runs_dir")
    archived = []
    for trace in runs_dir.glob(cfg.req("paths", "trace_glob")):
        dest = archive / f"{_now()}-{trace.name}"
        shutil.move(str(trace), str(dest))
        archived.append(dest.name)

    sync = (f"robocopy .claude\\skills\\aletheia "
            f"\"{cfg.req('paths', 'user_install_dir')}\" /E /XD __pycache__")
    report = {"applied": True, "changes": changes, "gates": gates,
              "traces_archived": archived,
              "reminder": f"user-wide install is now stale — sync it:  {sync}"}
    path = _write_report(cfg, "apply", report)
    print(json.dumps({**report, "report_file": str(path)}, indent=2))
    return 0


def cmd_audit(cfg: Cfg, args) -> int:
    runs = _corpus(cfg, args.source)
    if not runs:
        print(json.dumps({"error": f"no traces found in --source {args.source}"}))
        return 1
    _, parsed = _prior(cfg)
    floor, egate = _thresholds(parsed)

    voi: dict[str, dict] = {}
    stop_reasons: dict[str, int] = {}
    entropy_gate_work = 0  # turns where confidence cleared the floor but entropy blocked
    for run in runs.values():
        stop_reasons[run["final"]["stop_reason"]] = (
            stop_reasons.get(run["final"]["stop_reason"], 0) + 1)
        for t in run["turns"]:
            v = voi.setdefault(t["sensor"], {"predicted": 0.0, "realized": 0.0,
                                             "observations": 0, "null_observations": 0})
            v["predicted"] += t["predicted_gain_bits"]
            v["realized"] += t["realized_gain_bits"]
            if t.get("points_at"):
                v["observations"] += 1
            else:
                v["null_observations"] += 1
            for dim, dist in t.get("posterior", {}).items():
                if (max(dist.values()) >= floor
                        and pb.normalized_entropy(dist) > egate):
                    entropy_gate_work += 1

    flag_ratio = cfg.req("voi_audit", "undershoot_flag_ratio")
    min_obs = cfg.req("voi_audit", "min_observations")
    for s, v in voi.items():
        v["ratio"] = (v["realized"] / v["predicted"]) if v["predicted"] > 0 else None
        v["flagged"] = (v["observations"] >= min_obs and v["ratio"] is not None
                        and v["ratio"] < flag_ratio)

    report = {
        "voi_honesty": voi,
        "gate_statistics": {
            "stop_reasons": stop_reasons,
            "mean_turns": sum(r["final"]["turns_total"] for r in runs.values()) / len(runs),
            "inconclusive_rate": sum(
                1 for r in runs.values() if r["final"]["inconclusive"]) / len(runs),
            "entropy_gate_blocked_early_commit_turns": entropy_gate_work,
        },
        "note": "report-only: threshold changes are never auto-applied in v1",
    }
    path = _write_report(cfg, "audit", report)
    print(json.dumps({**report, "report_file": str(path)}, indent=2))
    return 0


# ---------------------------------------------------------------- main

def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", required=True, help="path to autotune-config.toml")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    r = sub.add_parser("replay")
    r.add_argument("--source", required=True, choices=["runs", "fixtures"])
    r.add_argument("--proposal", help="candidate proposal JSON -> dominance evaluation")
    f = sub.add_parser("fit")
    f.add_argument("--source", required=True, choices=["runs", "fixtures"])
    a = sub.add_parser("apply")
    a.add_argument("--proposal", required=True)
    d = sub.add_parser("audit")
    d.add_argument("--source", required=True, choices=["runs", "fixtures"])
    args = p.parse_args(argv)

    cfg = load_config(args.config)
    return {"status": cmd_status, "replay": cmd_replay, "fit": cmd_fit,
            "apply": cmd_apply, "audit": cmd_audit}[args.cmd](cfg, args)


if __name__ == "__main__":
    raise SystemExit(main())
