"""Tests for the statistical recalibration pass (autotune.py) — plan §7.

Covers: EM recovery, shrinkage damping, clamps, prior-file guards, replay determinism
and sensitivity, the confidence invariant, the fail-fast config contract, and the
apply gates. Fixture traces in tests/fixtures/ are the three recorded live runs.
"""
import importlib.util
import json
import random
import shutil
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / ".claude" / "skills" / "aletheia" / "scripts"
FIXTURES = ROOT / "tests" / "fixtures"
PRIOR = ROOT / ".claude" / "skills" / "aletheia" / "reference" / "environment-prior.md"
CONFIG = ROOT / ".claude" / "skills" / "aletheia" / "reference" / "autotune-config.toml"

spec = importlib.util.spec_from_file_location("autotune", SCRIPTS / "autotune.py")
autotune = importlib.util.module_from_spec(spec)
sys.modules["autotune"] = autotune
spec.loader.exec_module(autotune)


# ---------------------------------------------------------------- helpers

def synthetic_runs(planted: dict[str, float], n_items: int, seed: int) -> dict:
    """One-vote-per-sensor-per-item synthetic corpus with known reliabilities."""
    rng = random.Random(seed)
    vals = ["x", "y"]
    runs = {}
    for i in range(n_items):
        true = rng.choice(vals)
        turns = []
        for turn_no, (sensor, r) in enumerate(planted.items(), start=1):
            vote = true if rng.random() < r else [v for v in vals if v != true][0]
            turns.append({"turn": turn_no, "sensor": sensor,
                          "points_at": {"D0": vote},
                          "prior": {"D0": {v: 0.5 for v in vals}},
                          "posterior": {}, "question_dims": ["D0"]})
        runs[f"R{i}"] = {"turns": turns, "final": {"turns_total": len(turns)}}
    return runs


def champion_reliabilities():
    parsed = autotune.parse_prior(PRIOR.read_text(encoding="utf-8"))
    return {name: item["value"] for name, item in parsed["sensors"].items()}


def thresholds():
    parsed = autotune.parse_prior(PRIOR.read_text(encoding="utf-8"))
    return (parsed["thresholds"]["confidence_floor"]["value"],
            parsed["thresholds"]["entropy_explore_above"]["value"])


def fixture_runs():
    return autotune.load_traces(FIXTURES, "trace-*.jsonl", 1)


def acceptance():
    data = json.loads((FIXTURES / "acceptance.json").read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


# ---------------------------------------------------------------- EM

def test_em_recovers_planted_reliabilities():
    planted = {"s_good": 0.92, "s_mid": 0.80, "s_weak": 0.60}
    runs = synthetic_runs(planted, n_items=400, seed=7)
    current = {s: 0.75 for s in planted}          # deliberately wrong start
    fit = autotune.em_fit(runs, current, pseudo_count=1,
                          max_iter=500, tol=1e-9, min_obs=5)
    for s, r_true in planted.items():
        assert abs(fit["fitted"][s] - r_true) <= 0.06, (s, fit["fitted"][s], r_true)


def test_shrinkage_damps_and_clamp_bounds_small_corpora():
    # Adversarial small corpus: one sensor always contradicts two corroborating ones.
    rng_runs = {}
    vals = ["x", "y"]
    for i in range(6):
        rng_runs[f"R{i}"] = {"turns": [
            {"turn": 1, "sensor": "s_anchor1", "points_at": {"D0": "x"},
             "prior": {"D0": {v: 0.5 for v in vals}}, "posterior": {}, "question_dims": ["D0"]},
            {"turn": 2, "sensor": "s_anchor2", "points_at": {"D0": "x"},
             "prior": {"D0": {v: 0.5 for v in vals}}, "posterior": {}, "question_dims": ["D0"]},
            {"turn": 3, "sensor": "s_victim", "points_at": {"D0": "y"},
             "prior": {"D0": {v: 0.5 for v in vals}}, "posterior": {}, "question_dims": ["D0"]},
        ], "final": {"turns_total": 3}}
    current = {"s_anchor1": 0.85, "s_anchor2": 0.85, "s_victim": 0.90}

    heavy = autotune.em_fit(rng_runs, current, pseudo_count=40,
                            max_iter=200, tol=1e-9, min_obs=5)
    light = autotune.em_fit(rng_runs, current, pseudo_count=0.001,
                            max_iter=200, tol=1e-9, min_obs=5)
    # Shrinkage damps: the anchored fit stays much closer to the current value.
    assert abs(heavy["fitted"]["s_victim"] - 0.90) < abs(light["fitted"]["s_victim"] - 0.90)
    # And whatever the raw fit says, the clamped proposal moves at most 0.05.
    deltas = autotune.clamp_fit(heavy["fitted"], current,
                                max_delta=0.05, floor=0.55, ceiling=0.98)
    for s, d in deltas.items():
        assert abs(d["proposed"] - current[s]) <= 0.05 + 1e-9


def test_clamp_clips_and_logs():
    deltas = autotune.clamp_fit({"s": 0.60}, {"s": 0.90},
                                max_delta=0.05, floor=0.55, ceiling=0.98)
    assert deltas["s"]["proposed"] == pytest.approx(0.85)
    assert deltas["s"]["clamped"] is True
    assert deltas["s"]["fitted_raw"] == pytest.approx(0.60)


# ---------------------------------------------------------------- prior-file guards

def test_prior_roundtrip_byte_identical():
    text = PRIOR.read_text(encoding="utf-8")
    parsed = autotune.parse_prior(text)
    assert autotune.serialize_prior(parsed) == text
    assert len(parsed["sensors"]) >= 8
    assert {"confidence_floor", "entropy_explore_above", "max_iterations"} <= set(
        parsed["thresholds"])


def test_write_path_guard_refuses_offgrammar_change(tmp_path):
    work = tmp_path / "prior.md"
    shutil.copy(PRIOR, work)
    with pytest.raises(ValueError, match="write-path guard"):
        autotune.patch_prior(work, {"search:not_a_sensor": 0.80})
    # a legitimate patch touches exactly one line
    before = work.read_text(encoding="utf-8").splitlines()
    changes = autotune.patch_prior(work, {"search:review_velocity": 0.78})
    after = work.read_text(encoding="utf-8").splitlines()
    assert changes == ["search:review_velocity: 0.75 -> 0.78"]
    assert sum(1 for a, b in zip(before, after) if a != b) == 1


# ---------------------------------------------------------------- replay

def test_replay_reproduces_recorded_runs():
    runs = fixture_runs()
    champion = champion_reliabilities()
    floor, egate = thresholds()
    assert set(runs) == {"A1", "A2", "H1"}
    for rid, run in runs.items():
        rep = autotune.replay_run(run, champion, floor, egate)
        assert rep["max_deviation_vs_recorded"] < 1e-12, rid
    # Mechanical stop model: H1's gate conditions were met after turn 4; the recorded
    # 5th turn was a judgment corroboration beyond the mechanical gate. Replay models
    # the mechanical policy, so it stops at 4 — champion and candidate are compared
    # under the same model, which is what dominance needs.
    h1 = autotune.replay_run(runs["H1"], champion, floor, egate)
    assert h1["turns_to_stop"] == 4
    assert h1["dims"]["D0"]["leading"] == "inflated" and h1["dims"]["D0"]["committed"]
    a1 = autotune.replay_run(runs["A1"], champion, floor, egate)
    assert a1["dims"]["D0"]["committed"] is False        # the honest below-floor result
    a2 = autotune.replay_run(runs["A2"], champion, floor, egate)
    assert a2["dims"]["D0"]["leading"] is None            # stayed at the even prior


def test_replay_sensitivity_smoke():
    # Weakening a sensor must delay (or prevent) commitment — stop turn moves the
    # expected direction under the candidate parameters.
    runs = fixture_runs()
    champion = champion_reliabilities()
    floor, egate = thresholds()
    candidate = dict(champion, **{"search:review_velocity": 0.60})
    h1_champ = autotune.replay_run(runs["H1"], champion, floor, egate)
    h1_cand = autotune.replay_run(runs["H1"], candidate, floor, egate)
    assert h1_cand["turns_to_stop"] > h1_champ["turns_to_stop"]
    assert h1_cand["dims"]["D0"]["confidence"] < h1_champ["dims"]["D0"]["confidence"]


def test_confidence_invariant_autoreject():
    runs = fixture_runs()
    champion = champion_reliabilities()
    floor, egate = thresholds()
    candidate = dict(champion, **{"search:customer_evidence": 0.87,
                                  "search:review_velocity": 0.80})
    dom = autotune.evaluate_dominance(runs, champion, candidate, floor, egate,
                                      acceptance(), max_conf_shift=0.0)
    assert dom["detail"]["mean_confidence_shift"] > 0
    assert dom["checks"]["e_confidence_invariant"] is False
    assert dom["dominates"] is False


def test_dominance_accepts_identity_candidate():
    runs = fixture_runs()
    champion = champion_reliabilities()
    floor, egate = thresholds()
    dom = autotune.evaluate_dominance(runs, champion, dict(champion), floor, egate,
                                      acceptance(), max_conf_shift=0.0)
    assert dom["dominates"] is True, dom["detail"]


def test_turn1_rule_enforced_at_load(tmp_path):
    """A trace whose first turn omits a question dimension's starting prior must be
    rejected loudly at load time — otherwise an all-null dimension would be silently
    dropped from replay/fit (the A2/D0 failure mode, made impossible to miss)."""
    bad = [
        {"schema_version": 1, "type": "turn", "run_id": "BAD", "turn": 1,
         "question_dims": ["D0", "D1"], "sensor": "search:funding_filings",
         "points_at": {"D1": "healthy"},
         "prior": {"D1": {"healthy": 0.5, "distressed": 0.5}},   # D0's prior missing!
         "posterior": {"D1": {"healthy": 0.9, "distressed": 0.1}},
         "predicted_gain_bits": 0.5, "realized_gain_bits": 0.5, "novelty": 0.9,
         "stop_check": {"fired": False, "reason": None}},
        {"schema_version": 1, "type": "final", "run_id": "BAD", "turns_total": 1,
         "stop_reason": "floor_cleared", "verdict_direction": {"D1": "healthy"},
         "stated_confidence": {"D1": 0.9}, "inconclusive": False,
         "ground_truth": None, "resolved_date": None},
    ]
    p = tmp_path / "trace-BAD.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in bad) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"turn-1 rule.*D0"):
        autotune.load_traces(tmp_path, "trace-*.jsonl", 1)
    # and the shipped fixtures all satisfy the rule (loads without error)
    assert set(fixture_runs()) == {"A1", "A2", "H1"}


# ---------------------------------------------------------------- config contract

def test_missing_config_key_is_hard_error(tmp_path):
    cfg_text = CONFIG.read_text(encoding="utf-8").replace(
        "convergence_tol        = 1e-6", "")
    p = tmp_path / "cfg.toml"
    p.write_text(cfg_text, encoding="utf-8")
    cfg = autotune.load_config(p)
    with pytest.raises(autotune.ConfigError, match="em.convergence_tol"):
        cfg.req("em", "convergence_tol")
    # and the real config satisfies every key the code requires
    real = autotune.load_config(CONFIG)
    for keys in [("schema_version",), ("trigger", "min_completed_runs"),
                 ("em", "shrinkage_pseudo_count"), ("clamps", "max_reliability_delta"),
                 ("gates", "pytest_command"), ("voi_audit", "undershoot_flag_ratio"),
                 ("reports", "keep_last"), ("automation", "enabled"),
                 ("automation", "auto_sync"), ("automation", "min_interval_hours"),
                 ("automation", "marker_file")]:
        real.req(*keys)


def test_missing_config_file_is_hard_error(tmp_path):
    with pytest.raises(autotune.ConfigError, match="not found"):
        autotune.load_config(tmp_path / "nope.toml")


# ---------------------------------------------------------------- hands-free cycle (hook contract)

CYCLE = SCRIPTS / "autotune_cycle.py"


def test_cycle_hook_contract_silent_fast_throttled(tmp_path):
    """The SessionEnd wrapper must exit 0 and print nothing when there's nothing to do,
    and must throttle repeat invocations — a hook may never disturb the session."""
    import subprocess
    env = {**__import__("os").environ, "USERPROFILE": str(tmp_path), "HOME": str(tmp_path)}
    for expectation in ("cold run (empty spool)", "throttled run"):
        proc = subprocess.run([sys.executable, str(CYCLE)], capture_output=True,
                              text=True, env=env, timeout=60)
        assert proc.returncode == 0, (expectation, proc.stderr)
        assert proc.stdout.strip() == "", (expectation, proc.stdout)
    assert (tmp_path / ".claude" / "aletheia-runs" / ".last-cycle").is_file()


def test_cycle_noops_outside_master_repo(tmp_path):
    """A deployed copy (no test suite at the repo-root position) must stand down."""
    import subprocess
    deploy = tmp_path / "fake" / ".claude" / "skills" / "aletheia"
    shutil.copytree(SCRIPTS.parent, deploy,
                    ignore=shutil.ignore_patterns("__pycache__"))
    proc = subprocess.run([sys.executable, str(deploy / "scripts" / "autotune_cycle.py")],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0 and proc.stdout.strip() == ""
    # and it must not have created a throttle marker anywhere under the fake root
    assert not list((tmp_path / "fake").rglob(".last-cycle"))


# ---------------------------------------------------------------- apply gates

def _temp_config(tmp_path, prior_copy, pytest_cmd):
    text = f"""
schema_version = 1
[trigger]
min_completed_runs = 10
inconclusive_weight = 1.0
[paths]
runs_dir = "{(tmp_path / 'runs').as_posix()}"
archive_dir = "{(tmp_path / 'runs/archive').as_posix()}"
reports_dir = "{(tmp_path / 'reports').as_posix()}"
trace_glob = "trace-*.jsonl"
prior_file = "{prior_copy.as_posix()}"
ledger_file = "{(tmp_path / 'ledger.md').as_posix()}"
user_install_dir = "~/.claude/skills/aletheia"
[em]
max_iterations = 200
convergence_tol = 1e-6
shrinkage_pseudo_count = 40
min_observations = 5
[clamps]
max_reliability_delta = 0.05
max_threshold_delta = 0.03
reliability_floor = 0.55
reliability_ceiling = 0.98
[gates]
require_replay_dominance = false
require_pytest = true
pytest_command = "{pytest_cmd}"
max_mean_confidence_shift = 0.0
acceptance_fixtures = ["A1", "A2", "H1"]
fixtures_dir = "{FIXTURES.as_posix()}"
acceptance_criteria_file = "{(FIXTURES / 'acceptance.json').as_posix()}"
[voi_audit]
undershoot_flag_ratio = 0.6
min_observations = 5
[reports]
keep_last = 20
"""
    p = tmp_path / "cfg.toml"
    p.write_text(text, encoding="utf-8")
    return p


def test_gates_block_apply_on_pytest_failure(tmp_path):
    prior_copy = tmp_path / "prior.md"
    shutil.copy(PRIOR, prior_copy)
    (tmp_path / "runs").mkdir()
    (tmp_path / "ledger.md").write_text("| ledger |\n", encoding="utf-8")
    cfg_path = _temp_config(tmp_path, prior_copy,
                            'python -c \\"import sys; sys.exit(1)\\"')
    proposal = tmp_path / "prop.json"
    proposal.write_text(json.dumps({
        "corpus_runs": ["T"],
        "deltas": {"search:review_velocity": {"current": 0.75, "proposed": 0.78}},
    }), encoding="utf-8")

    before = prior_copy.read_bytes()
    cfg = autotune.load_config(cfg_path)
    args = types.SimpleNamespace(proposal=str(proposal))
    rc = autotune.cmd_apply(cfg, args)
    assert rc == 1
    assert prior_copy.read_bytes() == before           # nothing written
    assert (tmp_path / "ledger.md").read_text(encoding="utf-8") == "| ledger |\n"


def test_apply_succeeds_and_patches_when_gates_pass(tmp_path, capsys):
    prior_copy = tmp_path / "prior.md"
    shutil.copy(PRIOR, prior_copy)
    (tmp_path / "runs").mkdir()
    (tmp_path / "ledger.md").write_text("| ledger |\n", encoding="utf-8")
    cfg_path = _temp_config(tmp_path, prior_copy,
                            'python -c \\"import sys; sys.exit(0)\\"')
    proposal = tmp_path / "prop.json"
    proposal.write_text(json.dumps({
        "corpus_runs": ["T"],
        "deltas": {"search:review_velocity": {"current": 0.75, "proposed": 0.73}},
    }), encoding="utf-8")

    cfg = autotune.load_config(cfg_path)
    args = types.SimpleNamespace(proposal=str(proposal))
    rc = autotune.cmd_apply(cfg, args)
    assert rc == 0
    assert "reliability: 0.73" in prior_copy.read_text(encoding="utf-8")
    ledger = (tmp_path / "ledger.md").read_text(encoding="utf-8")
    assert "autotune apply" in ledger and "0.75 -> 0.73" in ledger
