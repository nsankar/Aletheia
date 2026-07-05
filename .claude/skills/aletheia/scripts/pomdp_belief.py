#!/usr/bin/env python3
"""pomdp_belief.py — belief-update / entropy / value-of-information coprocessor.

The LLM does language; this file does math. It reads a tiny per-dimension model
(from AGENTS.md, passed as JSON) and returns an exact posterior + entropy + the
next action with the highest expected information gain.

Uses pomdp_py.Histogram + update_histogram_belief when available (see the Tiger
example: https://h2r.github.io/pomdp-py/html/examples.tiger.html); otherwise falls
back to a pure-stdlib Bayes filter so demos run with zero extra deps.
"""
from __future__ import annotations
import argparse, json, math
from typing import Dict

try:
    import pomdp_py  # optional; enables the library-backed path
    HAVE_POMDP_PY = True
except Exception:
    HAVE_POMDP_PY = False


def entropy(dist: Dict[str, float]) -> float:
    """Shannon entropy in bits."""
    return -sum(p * math.log2(p) for p in dist.values() if p > 0)


def normalized_entropy(dist: Dict[str, float]) -> float:
    n = len(dist)
    return entropy(dist) / math.log2(n) if n > 1 else 0.0


def bayes_update(prior: Dict[str, float], likelihood: Dict[str, float]) -> Dict[str, float]:
    """Static-state Bayes filter (transition = identity): b'(s) ∝ P(o|s)·b(s).

    `likelihood[s]` = P(observation | state=s). For a sensor with reliability r that
    'points at' value v: P(o|v)=r, P(o|other)=(1-r)/(k-1).
    """
    post = {s: prior[s] * likelihood.get(s, 1e-9) for s in prior}
    z = sum(post.values()) or 1e-12
    return {s: p / z for s, p in post.items()}


def likelihood_from_sensor(values, points_at: str, reliability: float) -> Dict[str, float]:
    k = len(values)
    off = (1.0 - reliability) / (k - 1) if k > 1 else 0.0
    return {v: (reliability if v == points_at else off) for v in values}


def expected_info_gain(prior: Dict[str, float], reliability: float) -> float:
    """VOI proxy: expected entropy reduction if we run a sensor of this reliability.

    Averages the posterior entropy over the possible (predicted) observations.
    Higher = better next action. Cost-adjust by dividing by the action's cost.
    """
    values = list(prior)
    h0 = entropy(prior)
    exp_post_h = 0.0
    for o in values:  # each possible observation "points at" value o
        lik = likelihood_from_sensor(values, o, reliability)
        p_o = sum(prior[s] * lik[s] for s in values)
        if p_o <= 0:
            continue
        post = bayes_update(prior, lik)
        exp_post_h += p_o * entropy(post)
    return h0 - exp_post_h  # information gain in bits


def _pomdp_py_update(values, prior, points_at, reliability):
    """Library-backed identical result, using pomdp_py.Histogram for the belief."""
    b = pomdp_py.Histogram({v: prior[v] for v in values})
    lik = likelihood_from_sensor(values, points_at, reliability)
    updated = {v: b[v] * lik[v] for v in values}
    z = sum(updated.values()) or 1e-12
    return pomdp_py.Histogram({v: p / z for v, p in updated.items()})


def _update_one(values, prior, points_at, reliability):
    """Shared posterior computation, used by both `update` and `map`."""
    if HAVE_POMDP_PY:
        hist = _pomdp_py_update(values, prior, points_at, reliability)
        return {v: hist[v] for v in values}
    lik = likelihood_from_sensor(values, points_at, reliability)
    return bayes_update(prior, lik)


def cmd_update(args):
    model = json.loads(args.model)           # {"values":[...], "prior":{...}}
    values, prior = model["values"], model["prior"]
    post = _update_one(values, prior, args.points_at, args.reliability)
    out = {
        "posterior": {k: round(v, 4) for k, v in post.items()},
        "entropy_bits": round(entropy(post), 4),
        "entropy_norm": round(normalized_entropy(post), 4),
        "leading": max(post, key=post.get),
        "confidence": round(max(post.values()), 4),
        "backend": "pomdp_py" if HAVE_POMDP_PY else "stdlib-fallback",
    }
    print(json.dumps(out, indent=2))


def cmd_voi(args):
    """Rank candidate actions by expected info gain per unit cost (which to ask/search next).

    Cost is treated as a magnitude: the environment prior states costs as negative rewards
    (e.g. search = -1, doc fetch = -2), so we take abs() — otherwise a negative cost would
    silently invert the ranking and put the WEAKEST sensor first. A zero cost falls back to 1.
    """
    spec = json.loads(args.spec)   # {"prior":{...}, "actions":[{"name","reliability","cost"}]}
    prior = spec["prior"]
    rows = []
    for a in spec["actions"]:
        gain = expected_info_gain(prior, a["reliability"])
        cost = abs(a.get("cost", 1)) or 1
        rows.append({"action": a["name"],
                     "info_gain_bits": round(gain, 4),
                     "gain_per_cost": round(gain / cost, 4)})
    ranked = sorted(rows, key=lambda r: r["gain_per_cost"], reverse=True)
    print(json.dumps({"ranked_next_actions": ranked}, indent=2))


def cmd_map(args):
    """Orchestration helper for a multi-dimensional belief (Aletheia's D0-D3).

    A single sensor observation can bear on several state dimensions at once
    (e.g. `search:hiring_signals` reveals both D1 and D2). This subcommand takes
    the current per-dimension priors, the value each dimension's observation
    "points at", and the sensor's reliability, and calls the SAME per-dimension
    Bayes update (`_update_one`) for each dimension named in --points-at. It does
    not introduce any new math — it only loops the existing `update` logic over
    however many dimensions one observation happens to touch.
    """
    beliefs = json.loads(args.beliefs)      # {"D0": {"real":0.5,"inflated":0.5}, ...}
    points_at = json.loads(args.points_at)  # {"D0": "inflated", ...} (subset of dims touched)
    reliability = args.reliability

    dimensions = {}
    for dim, target in points_at.items():
        if dim not in beliefs:
            continue
        values = list(beliefs[dim])
        post = _update_one(values, beliefs[dim], target, reliability)
        dimensions[dim] = {
            "posterior": {k: round(v, 4) for k, v in post.items()},
            "entropy_bits": round(entropy(post), 4),
            "entropy_norm": round(normalized_entropy(post), 4),
            "leading": max(post, key=post.get),
            "confidence": round(max(post.values()), 4),
        }
    print(json.dumps({
        "dimensions": dimensions,
        "backend": "pomdp_py" if HAVE_POMDP_PY else "stdlib-fallback",
    }, indent=2))


def cmd_selftest(_):
    # Tiger-flavored sanity check: a 0.85-reliable "growl-left" observation.
    prior = {"tiger-left": 0.5, "tiger-right": 0.5}
    lik = likelihood_from_sensor(list(prior), "tiger-left", 0.85)
    post = bayes_update(prior, lik)
    assert abs(post["tiger-left"] - 0.85) < 1e-9
    print("selftest OK:", json.dumps(post), "| backend:",
          "pomdp_py" if HAVE_POMDP_PY else "stdlib-fallback")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(required=True)
    u = sub.add_parser("update"); u.add_argument("--model", required=True)
    u.add_argument("--points-at", required=True); u.add_argument("--reliability", type=float, required=True)
    u.set_defaults(func=cmd_update)
    v = sub.add_parser("voi"); v.add_argument("--spec", required=True); v.set_defaults(func=cmd_voi)
    m = sub.add_parser("map"); m.add_argument("--beliefs", required=True)
    m.add_argument("--points-at", required=True); m.add_argument("--reliability", type=float, required=True)
    m.set_defaults(func=cmd_map)
    s = sub.add_parser("selftest"); s.set_defaults(func=cmd_selftest)
    a = p.parse_args(); a.func(a)
