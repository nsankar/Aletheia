# Statistical Recalibration (Approach A) — Implementation Plan

*Status: **PLANNED** (approved design; code not yet written). Implements §4 of
[`auto-tuner-workflow-proposal.md`](auto-tuner-workflow-proposal.md), covering build phases
1–3 of that proposal's §6. Operator/developer doc.*

**Two hard requirements this plan is built around:**
1. **Efficiency** — pure stdlib, no duplicated math, offline-only (zero live-path cost),
   two-step propose→apply so nothing is recomputed twice.
2. **Zero hardcoded configuration** — every tunable of the tuner itself lives in a config
   file the Claude agent (and the script) can always read; the code carries **no default
   values**. A missing key is a hard error, which is what *enforces* the rule instead of
   promising it.

---

## 1. Architecture & data flow

```
investigations (live path — unchanged, zero new code)
   └─ agent appends per-turn JSONL  →  runs/trace-<session>.jsonl     [trace-schema.md]

offline tuning (operator context, triggered every N runs)
   autotune.py status   ← reads runs/ + autotune-config.toml   → "trigger ready? corpus stats"
   autotune.py fit      ← traces + environment-prior.md        → proposal JSON + human summary (applies NOTHING)
   autotune.py replay   ← traces + candidate params            → deterministic re-computation report
   autotune.py apply    ← proposal JSON                        → gates → patch TUNABLE values → ledger → archive traces
   autotune.py audit    ← traces                               → VOI-honesty + gate-statistics report (report-only)
```

Everything below `runs/` is data; everything in `reference/` is agent-readable
configuration; the only file the tuner ever *writes* outside `runs/` is the TUNABLE content
of `environment-prior.md` (guarded, §5) and the ledger append.

## 2. The config file — `reference/autotune-config.toml`

**Format: TOML.** Stdlib parsing via `tomllib` (Python ≥ 3.11; this machine runs 3.12),
inline comments so every knob is self-documenting, and it sits in `reference/` beside
`environment-prior.md` — the established home for agent-readable operator config. The tuner
only *reads* it (no TOML writer needed, keeping stdlib-only).

Complete spec (values shown are the initial settings, not code defaults — the code has none):

```toml
schema_version = 1          # must match trace-schema.md; mismatch = refuse to run

[trigger]
min_completed_runs = 10     # N: tuning cycle eligibility
inconclusive_weight = 1.0   # proposal §10 open-Q1, resolved as config: how much an
                            # INCONCLUSIVE run counts toward N (set 0.5 to count them half)

[paths]                     # all relative to the repo root (absolute allowed)
runs_dir            = "runs"
archive_dir         = "runs/archive"
reports_dir         = "runs/tuning-reports"
trace_glob          = "trace-*.jsonl"
prior_file          = ".claude/skills/aletheia/reference/environment-prior.md"
ledger_file         = "Aletheia-loop-engg.md"     # tuning ledger lives at the bottom
user_install_dir    = "~/.claude/skills/aletheia" # for the post-apply sync reminder

[em]
max_iterations        = 200
convergence_tol       = 1e-6   # max abs reliability change between iterations
shrinkage_pseudo_count = 40    # Beta-prior strength: ~40 pseudo-votes anchored at the
                               # current reliability; 10 runs of real votes cannot swing it far
min_observations      = 5      # sensors with fewer votes in the corpus are skipped entirely

[clamps]
max_reliability_delta = 0.05   # per parameter, per cycle (proposal §4.1)
max_threshold_delta   = 0.03   # (report-only in v1; kept for A′)
reliability_floor     = 0.55   # absolute bounds — no fit may leave this range
reliability_ceiling   = 0.98

[gates]                        # ALL must pass before apply writes anything
require_replay_dominance   = true
require_pytest             = true
pytest_command             = "python -m pytest tests/ -q"
max_mean_confidence_shift  = 0.0   # §2.2 invariant, mechanical: upward shift in replayed
                                   # stated-confidence without structural change ⇒ reject
acceptance_fixtures        = ["A1", "A2", "H1"]  # replay fixtures that must keep passing

[voi_audit]
undershoot_flag_ratio = 0.6    # realized/predicted gain below this (cumulative) ⇒ flag sensor
min_observations      = 5

[reports]
keep_last = 20                 # tuning-report retention
```

**The no-hardcode contract, precisely:** `autotune.py` loads this file once into a frozen
config object; **every** numeric or path decision in the code reads from it; `dict.get(key,
default)` is banned in config access; absence of any key raises `ConfigError` naming the
key. One unit test asserts this by deleting a key and expecting the error (§7).

## 3. Module design — `scripts/autotune.py` (stdlib only)

Sits beside `pomdp_belief.py` and **imports its math directly** (`bayes_update`, `entropy`,
`likelihood_from_sensor`, `_update_one`) — replay runs the *identical* code path that
produced the original numbers. Parity by construction; zero duplicated math; no drift risk.

Allowed imports: `argparse, json, math, re, pathlib, tomllib, datetime, statistics,
subprocess (gates only), shutil (archive only)`. Nothing else.

### Subcommands

| Command | Reads | Writes | Purpose |
|---|---|---|---|
| `status` | config, `runs/` | stdout JSON | Corpus stats: eligible-run count vs. `min_completed_runs`, per-sensor vote counts, schema-version check. The agent calls this to decide whether a tuning cycle is due |
| `replay [--candidate <proposal.json>]` | config, traces, prior file | report JSON | Re-computes every recorded turn's posterior + stop decision under champion (default) or candidate parameters. `--candidate` mode also emits the dominance comparison (§6) |
| `fit` | config, traces, prior file | proposal JSON + human-readable summary in `reports_dir` | EM + shrinkage + clamps → **proposed** reliability deltas with evidence (votes, agreement rates, pre/post values). **Applies nothing** |
| `apply --proposal <file>` | config, proposal JSON | prior file (TUNABLE values only), ledger append, trace archive | Runs ALL gates; on pass: surgical patch, ledger entry, move consumed traces to `archive_dir`, print user-install sync reminder. On any gate failure: report and exit non-zero, nothing written |
| `audit` | config, traces | report JSON | VOI-honesty (predicted vs. realized gain per sensor) + gate statistics (which stop conditions fired, threshold slack). **Report-only in v1** — threshold changes are surfaced for a human (or the future fuzzy A′ layer), never auto-applied |

The **two-step `fit` → `apply` separation** is deliberate: unattended mode is `fit` then
`apply` in sequence with gates deciding; supervised mode is `fit`, human reads the summary,
then `apply`. Same artifacts either way — one audit story.

## 4. The EM pass, exactly

**Data model.** Items = `(run_id, dimension)` instances. Votes = that run's per-turn sensor
observations on the dimension: sensor *s* voted value *v* (binary state space, per handoff
D3). Current reliabilities from the prior file are both the EM initialization and the
shrinkage anchor.

**E-step** — for each item, posterior over its true state from an even prior and the
current reliability estimates (this is `bayes_update` folded over the item's votes — the
coprocessor's own function).

**M-step** — for each sensor *s* with ≥ `min_observations` votes:

```
agree(s)  = Σ over s's votes of P(item state = voted value)     # soft agreement mass
total(s)  = number of s's votes
r_new(s)  = (agree(s) + pseudo_count · r_current(s)) / (total(s) + pseudo_count)
```

The pseudo-count term **is** the Beta shrinkage: the fit behaves as if `pseudo_count` prior
votes at the current reliability were already observed. With `pseudo_count = 40` and a
10-run corpus, *typical* (mostly-agreeing) evidence moves a sensor only marginally —
but a fully **adversarial** corpus (every vote contradicting consensus) can still push the
raw fit past ±0.05, so the clamp is the **primary** restraint at small N and shrinkage is
the damper (verified by `test_shrinkage_damps_and_clamp_bounds_small_corpora`). The two
guards are complementary, not redundant.

**Convergence** — iterate E/M until max |Δr| < `convergence_tol` or `max_iterations`.
Deterministic (no random init — current reliabilities seed it), so runs are reproducible.

**Correlated-error mitigation (honest limits)** — shrinkage + the VOI-honesty audit are the
in-scope mitigations; true correction needs deferred ground truth (proposal Phase 5, out of
scope here).

## 5. Prior-file patch protocol (markdown stays canonical)

`environment-prior.md` remains the single source of truth the *skill* reads; the tuner
parses and patches it with a strict grammar rather than owning a parallel store:

1. **Parse** — regex grammar for exactly two line shapes: sensor lines
   (`reliability: <float>` within the Sensor Map section) and TUNABLE threshold lines
   (`<name>: <float>`). Anything unparseable in those sections = hard error, no patch.
2. **Round-trip guard** — parse → re-serialize → must be byte-identical to the file on disk
   *before* any value is changed. Guarantees the grammar still matches the file and the
   patch can only touch numbers.
3. **Write-path guard** — the patcher substitutes numeric literals on matched lines only;
   a post-patch diff is computed and refused if any line outside the matched set changed.
4. Patch is written atomically (temp file + replace), and only inside `apply` after gates.

## 6. Replay dominance — the promotion gate, mechanically

`apply` promotes a proposal only if the `--candidate` replay report satisfies all of
(proposal §5.3, unchanged): no verdict-direction flip against a known-good outcome ·
mean turns-to-stop not increased · no INCONCLUSIVE on a run that legitimately cleared the
floor · acceptance fixtures (`A1`, `A2`, `H1` recorded traces, committed under
`tests/fixtures/`) still meet their pass criteria · mean stated confidence not shifted
upward beyond `max_mean_confidence_shift`. Plus `pytest_command` green. Each criterion is a
named boolean in the report — the ledger entry records the full vector.

## 7. Test plan — `tests/test_autotune.py`

Maps 1:1 onto proposal §9 Phase 2–3 checkboxes:

| Test | Asserts | §9 item |
|---|---|---|
| `test_em_recovers_planted_reliabilities` | Synthetic corpus generated with known reliabilities (deterministic seed); EM (shrinkage weakened via config) recovers them within tolerance | Phase 3 ✓1 |
| `test_shrinkage_limits_movement_at_small_n` | 10-run corpus cannot move a 0.90 sensor beyond ±0.05 even with adversarial votes | Phase 3 ✓1 |
| `test_clamp_clips_and_logs` | A fit demanding a larger swing is clipped; clip recorded in proposal JSON | Phase 3 ✓2 |
| `test_write_path_guard_refuses_offgrammar_change` | Patcher refuses when a non-parameter line would change | Phase 3 ✓3 |
| `test_prior_roundtrip_byte_identical` | Parse→serialize of the real `environment-prior.md` is byte-identical | Phase 3 ✓3 |
| `test_replay_reproduces_recorded_run` | Fixture trace replayed under champion params reproduces every posterior + stop decision exactly | Phase 2 ✓1 |
| `test_replay_sensitivity_smoke` | A perturbed candidate changes stop decisions in the expected direction | Phase 2 ✓2 |
| `test_confidence_invariant_autoreject` | Candidate that raises mean replayed confidence w/o structural change is rejected | Phase 3 ✓5 |
| `test_missing_config_key_is_hard_error` | Delete one key from a temp config → `ConfigError` naming it (**the no-hardcode test**) | req. 2 |
| `test_gates_block_apply_on_pytest_failure` | `apply` with a failing `pytest_command` writes nothing | Phase 3 ✓4 |

## 8. Build order (each step lands green before the next)

1. `reference/trace-schema.md` + the one-line SKILL.md §0 pointer (bloat guard: diff must
   show exactly one added line in SKILL.md). Log one manual investigation as the first
   fixture.
2. `reference/autotune-config.toml` + config loader with the fail-fast contract + its tests.
3. Prior-file parser + round-trip/write-path guards + tests.
4. `replay` + determinism/sensitivity tests (fixtures: recorded A1/A2/H1 traces).
5. `fit` (EM + shrinkage + clamps) + synthetic-recovery tests.
6. `apply` (gates → patch → ledger → archive → sync reminder) + gate tests.
7. `audit` (VOI-honesty + gate statistics reports).
8. Update proposal §9 checkboxes; ledger entry for the implementation itself.

## 9. Verification (end-to-end, after build)

```powershell
python -m pytest tests/ -q                                        # full suite green
python .claude/skills/aletheia/scripts/autotune.py status         # reads config, reports corpus
python .claude/skills/aletheia/scripts/autotune.py fit            # proposal JSON, applies nothing
python .claude/skills/aletheia/scripts/autotune.py apply --proposal <file>   # gates → patch → ledger
git diff .claude/skills/aletheia/reference/environment-prior.md   # ONLY numeric literals changed
```

Plus the governance check from proposal §9: AGENTS.md I12 + Self-tuning discipline verified
in place **before** any unattended `fit`+`apply` scheduling is set up.
