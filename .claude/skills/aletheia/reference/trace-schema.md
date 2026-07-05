<!-- trace-schema.md — Aletheia per-run telemetry schema (PRIVATE, operator-only) -->
# Trace Schema v1 — `~/.claude/aletheia-runs/trace-<session>.jsonl`

Traces are appended to the **central spool** above (same location from every folder a chat
runs in) so tuning sees all sessions without any gathering step. Belief files stay in the
chat folder's local `./runs/`.

One JSON object per line. Two record types: one `"turn"` record per investigation turn
(including null-observation turns), and exactly one `"final"` record when the run ends.
Written by the agent during the investigation (every field is derivable from coprocessor
output — no new math in the live path); consumed only by the offline tuner
(`scripts/autotune.py`). Never shown to the user (I1); honest and complete per the
Self-tuning discipline in `AGENTS.md` (G3) — null results and missed predictions are
recorded exactly as they happened.

## Turn record

```json
{
  "schema_version": 1,
  "type": "turn",
  "run_id": "<session or short id>",
  "turn": 2,
  "ts": "2026-01-15T09:41:00Z",
  "question_dims": ["D0", "D1"],
  "sensor": "search:customer_evidence",
  "query": "<the instantiated query_template>",
  "points_at": {"D0": "inflated"},
  "reliability_used": 0.82,
  "prior": {"D0": {"real": 0.5, "inflated": 0.5}},
  "posterior": {"D0": {"real": 0.18, "inflated": 0.82}},
  "predicted_gain_bits": 0.3199,
  "realized_gain_bits": 0.3199,
  "novelty": 0.85,
  "stop_check": {"fired": false, "reason": null}
}
```

Field notes:
- `question_dims` — the dimensions this run investigates (constant across the run's records).
- `points_at` — `{}` for a **null observation** (nothing usable found). Then
  `posterior == prior` and `realized_gain_bits = 0`. Null turns are valuable tuning data —
  never omit them.
- `prior` / `posterior` — **full precision** floats exactly as the coprocessor returned
  them (replay must reproduce them bit-for-bit). `posterior` covers only the dimensions
  this turn touched. `prior` likewise — **except turn 1, which must record the starting
  prior for every question dimension**, even untouched ones: that is what establishes each
  dimension's value vocabulary for offline replay (an all-null run would otherwise be
  unreconstructable). **This rule is enforced**: the tuner rejects any trace violating it
  at load time, naming the run and the missing dimension(s).
- `predicted_gain_bits` — the expected information gain the ranking step promised for this
  action (sum over touched dimensions). From the `voi` output at selection time.
- `realized_gain_bits` — entropy(prior) − entropy(posterior), summed over touched
  dimensions. **May be negative** (a disconfirming observation raises entropy) — that is
  signal, not error.
- `novelty` — new-source novelty estimate for the exhaustion gate (0–1).
- `stop_check` — whether the §5 gate fired after this turn, and on which reason
  (`"floor_cleared" | "max_iterations" | "exhaustion_repetition" | "exhaustion_novelty"`).

## Final record

```json
{
  "schema_version": 1,
  "type": "final",
  "run_id": "<same id>",
  "ts": "2026-01-15T09:55:00Z",
  "turns_total": 5,
  "stop_reason": "floor_cleared",
  "verdict_direction": {"D0": "inflated", "D1": "healthy"},
  "stated_confidence": {"D0": 0.93, "D1": 0.95},
  "inconclusive": false,
  "ground_truth": null,
  "resolved_date": null
}
```

Field notes:
- `verdict_direction` / `stated_confidence` — the per-dimension leading value and the
  confidence stated in the Verdict (business-rounded is fine here; replay compares
  directions and recomputes exact numbers from the turn records).
- `inconclusive` — `true` when the run ended INCONCLUSIVE on its asked dimension(s).
- `ground_truth` — `null` until reality resolves the verdict; then a per-dimension object
  (e.g. `{"D0": "inflated"}`) plus `resolved_date`. Backfilled later; enables true
  calibration (proposal Phase 5).

## Versioning
`schema_version` appears on every record. The tuner refuses a corpus whose records don't
match the `schema_version` in `autotune-config.toml`. Additive changes bump the version and
this file documents the migration.
