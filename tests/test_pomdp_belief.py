"""Unit tests for the pomdp_belief.py coprocessor (blueprint §8.1)."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

MODULE_PATH = (
    Path(__file__).resolve().parent.parent
    / ".claude" / "skills" / "aletheia" / "scripts" / "pomdp_belief.py"
)
spec = importlib.util.spec_from_file_location("pomdp_belief", MODULE_PATH)
pomdp_belief = importlib.util.module_from_spec(spec)
sys.modules["pomdp_belief"] = pomdp_belief
spec.loader.exec_module(pomdp_belief)


def test_bayes_update_matches_worked_trace():
    # blueprint §2.5 turn 1: prior {real:.5, inflated:.5}, points-at inflated, reliability .75
    prior = {"real": 0.5, "inflated": 0.5}
    lik = pomdp_belief.likelihood_from_sensor(["real", "inflated"], "inflated", 0.75)
    post = pomdp_belief.bayes_update(prior, lik)
    assert post["inflated"] == pytest.approx(0.75, abs=1e-9)
    assert post["real"] == pytest.approx(0.25, abs=1e-9)


def test_entropy_uniform_binary_is_one():
    dist = {"a": 0.5, "b": 0.5}
    assert pomdp_belief.normalized_entropy(dist) == pytest.approx(1.0, abs=1e-9)


def test_entropy_skewed_binary_is_low():
    dist = {"a": 0.94, "b": 0.06}
    assert pomdp_belief.normalized_entropy(dist) == pytest.approx(0.33, abs=0.01)


def test_voi_ranks_higher_reliability_lower_cost_first():
    prior = {"real": 0.5, "inflated": 0.5}
    actions = [
        {"name": "weak_cheap", "reliability": 0.60, "cost": 1},
        {"name": "strong_cheap", "reliability": 0.90, "cost": 1},
        {"name": "strong_expensive", "reliability": 0.90, "cost": 5},
    ]
    gains = {
        a["name"]: pomdp_belief.expected_info_gain(prior, a["reliability"]) / a["cost"]
        for a in actions
    }
    ranked = sorted(actions, key=lambda a: gains[a["name"]], reverse=True)
    assert ranked[0]["name"] == "strong_cheap"


def test_fallback_parity_with_and_without_pomdp_py():
    values, prior = ["real", "inflated"], {"real": 0.5, "inflated": 0.5}
    fallback_post = pomdp_belief.bayes_update(
        prior, pomdp_belief.likelihood_from_sensor(values, "inflated", 0.75)
    )
    if pomdp_belief.HAVE_POMDP_PY:
        lib_hist = pomdp_belief._pomdp_py_update(values, prior, "inflated", 0.75)
        lib_post = {v: lib_hist[v] for v in values}
        for v in values:
            assert lib_post[v] == pytest.approx(fallback_post[v], abs=1e-9)
    else:
        pytest.skip("pomdp_py not installed; nothing to compare against")


def test_map_updates_multiple_dimensions_independently():
    beliefs = {
        "D1": {"healthy": 0.5, "distressed": 0.5},
        "D2": {"rising": 0.5, "stalling": 0.5},
    }
    points_at = {"D1": "distressed", "D2": "rising"}
    reliability = 0.70
    d1_post = pomdp_belief._update_one(["healthy", "distressed"], beliefs["D1"], "distressed", reliability)
    d2_post = pomdp_belief._update_one(["rising", "stalling"], beliefs["D2"], "rising", reliability)
    assert d1_post["distressed"] == pytest.approx(0.70, abs=1e-9)
    assert d2_post["rising"] == pytest.approx(0.70, abs=1e-9)


def test_selftest_assertion_holds():
    prior = {"tiger-left": 0.5, "tiger-right": 0.5}
    lik = pomdp_belief.likelihood_from_sensor(list(prior), "tiger-left", 0.85)
    post = pomdp_belief.bayes_update(prior, lik)
    assert abs(post["tiger-left"] - 0.85) < 1e-9


# --- CLI-boundary tests: SKILL.md invokes these subcommands as a subprocess, so the JSON
# --- shapes (§5.1 "stable API") are tested here directly, not just the Python functions.

def _run_cli(*args):
    proc = subprocess.run(
        [sys.executable, str(MODULE_PATH), *args],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, f"CLI failed: {proc.stderr}"
    return json.loads(proc.stdout)


def test_cli_update_json_shape_and_values():
    out = _run_cli(
        "update",
        "--model", '{"values":["real","inflated"],"prior":{"real":0.5,"inflated":0.5}}',
        "--points-at", "inflated", "--reliability", "0.75",
    )
    assert set(out) >= {"posterior", "entropy_bits", "entropy_norm", "leading", "confidence", "backend"}
    assert out["posterior"]["inflated"] == pytest.approx(0.75, abs=1e-4)
    assert out["leading"] == "inflated"


def test_cli_voi_ranks_stronger_cheaper_sensor_first():
    spec_json = json.dumps({
        "prior": {"real": 0.5, "inflated": 0.5},
        "actions": [
            {"name": "web_traffic_rank", "reliability": 0.65, "cost": 1},
            {"name": "funding_filings", "reliability": 0.90, "cost": 1},
            {"name": "primary_doc_fetch", "reliability": 0.90, "cost": 2},
        ],
    })
    out = _run_cli("voi", "--spec", spec_json)
    ranked = out["ranked_next_actions"]
    assert ranked[0]["action"] == "funding_filings"
    # gain-per-cost must be monotonically non-increasing (it is sorted on that key)
    gains = [r["gain_per_cost"] for r in ranked]
    assert gains == sorted(gains, reverse=True)


def test_cli_voi_negative_costs_do_not_invert_ranking():
    # environment-prior.md states costs as negative rewards (search=-1, fetch=-2). Passing
    # them through verbatim must yield the SAME ranking as positive magnitudes — a raw
    # division by a negative cost would silently rank the weakest sensor first.
    actions = [
        {"name": "strong_cheap", "reliability": 0.90},
        {"name": "weak_cheap", "reliability": 0.60},
        {"name": "strong_expensive", "reliability": 0.95},
    ]
    prior = {"real": 0.5, "inflated": 0.5}
    neg = json.dumps({"prior": prior, "actions": [
        dict(actions[0], cost=-1), dict(actions[1], cost=-1), dict(actions[2], cost=-2)]})
    pos = json.dumps({"prior": prior, "actions": [
        dict(actions[0], cost=1), dict(actions[1], cost=1), dict(actions[2], cost=2)]})
    ranked_neg = [r["action"] for r in _run_cli("voi", "--spec", neg)["ranked_next_actions"]]
    ranked_pos = [r["action"] for r in _run_cli("voi", "--spec", pos)["ranked_next_actions"]]
    assert ranked_neg == ranked_pos
    assert ranked_neg[0] == "strong_cheap"
    assert ranked_neg[-1] == "weak_cheap"


def test_cli_map_updates_each_named_dimension():
    out = _run_cli(
        "map",
        "--beliefs", '{"D1":{"healthy":0.5,"distressed":0.5},"D2":{"rising":0.5,"stalling":0.5}}',
        "--points-at", '{"D1":"healthy","D2":"rising"}',
        "--reliability", "0.70",
    )
    dims = out["dimensions"]
    assert set(dims) == {"D1", "D2"}
    assert dims["D1"]["posterior"]["healthy"] == pytest.approx(0.70, abs=1e-4)
    assert dims["D2"]["leading"] == "rising"


def test_cli_map_ignores_dimensions_not_named_in_points_at():
    # A sensor that only touches D1 must not fabricate an update for D2.
    out = _run_cli(
        "map",
        "--beliefs", '{"D1":{"healthy":0.5,"distressed":0.5},"D2":{"rising":0.5,"stalling":0.5}}',
        "--points-at", '{"D1":"distressed"}',
        "--reliability", "0.80",
    )
    assert set(out["dimensions"]) == {"D1"}
