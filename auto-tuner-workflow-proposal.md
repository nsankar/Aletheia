# Aletheia Auto-Tuner — Workflow Proposal

*Status: **PROPOSED** (not implemented). Operator/developer doc — internals discussed freely.*
*Companion to [`Aletheia-loop-engg.md`](Aletheia-loop-engg.md) (the manual tuning field guide);
this proposal is that guide's automation.*

---

## 1. The idea

Aletheia already records what it does: per SKILL.md §0, every investigation persists its
belief evolution (`runs/belief-*.md`) and per-turn telemetry (`runs/trace-<session>.jsonl`).
After a batch of investigations (~5–10, including follow-ups in a session), those traces
contain enough signal to **tune Aletheia's own tunable parameters** — sensor reliabilities,
stopping thresholds, costs, even sensor-map structure — without a human in the loop for the
routine cases.

The auto-tuner closes the loop *around* the loop: the investigation loop reduces uncertainty
about companies; the tuning loop reduces uncertainty about **Aletheia's own parameters**.

## 2. The two constraints that shape everything

**2.1 Ground truth is scarce.** After 10 queries we have traces, not labels — we usually
don't know which verdicts were *right* yet. So the tuner's legitimate objectives are
**internal consistency** (do sensors agree with each other at the rates their reliabilities
claim?) and **efficiency** (turns, novelty, wasted searches) — plus deferred ground truth
folded in whenever reality resolves a past verdict (a collapse, a filing, an IPO).

**2.2 The prime invariant — never optimize confidence.** A tuner that maximizes "confident
verdicts" is reward-hacking calibrated honesty (I3) in algorithmic form, and would
manufacture exactly the false certainty the product exists to eliminate.

> **The tuner may make Aletheia cheaper, more consistent, and better-calibrated.
> It may never make Aletheia more confident.**

This is the auto-tuner's constitution-equivalent, and it is not tunable.

## 3. Shared substrate (build once, both approaches use it)

### 3.1 Trace schema — `runs/trace-<session>.jsonl`, one JSON object per turn

> **Bloat guard (design rule).** The schema below lives in its own bundled reference file —
> `reference/trace-schema.md`, beside `environment-prior.md` — **not** in SKILL.md. SKILL.md
> is loaded into context on every investigation, so it gets exactly **one pointer line**
> ("append per-turn telemetry per `reference/trace-schema.md`") and never grows with the
> schema. Raw data never enters any skill file: traces go to `runs/` on disk (per the
> blueprint's rule — *skills hold durable knowledge; state lives outside them*). The full
> schema is read only by the offline tuner, which is the only thing that needs it.

```json
{
  "run_id": "…", "turn": 2, "ts": "2026-07-02T09:41:00Z",
  "question_dims": ["D0", "D1"],
  "sensor": "search:customer_evidence",
  "query": "<the instantiated query_template>",
  "points_at": {"D0": "inflated"},
  "reliability_used": 0.82,
  "prior": {"D0": {"real": 0.5, "inflated": 0.5}},
  "posterior": {"D0": {"real": 0.18, "inflated": 0.82}},
  "predicted_gain_bits": 0.32,
  "realized_gain_bits": 0.32,
  "novelty": 0.85,
  "stop_check": {"fired": false, "reason": null}
}
```

Final-turn records add: `verdict_direction`, `stated_confidence`, `stop_reason`,
`turns_total`, and (if/when reality resolves it) `ground_truth` + `resolved_date`.

Two fields are **new** vs. today's telemetry: `predicted_gain_bits` (from the ranking step)
and `realized_gain_bits` (entropy before/after the update). They cost nothing to log and
enable the VOI-honesty audit below.

### 3.2 The offline replay harness (the key shared component)

Belief updates are **deterministic given observations**: replaying a recorded trace against
a *candidate* parameter set recomputes every posterior and every stop decision — no new
searches, no tokens, no network. This turns "would this tune have helped?" from speculation
into computation, and it is the promotion gate both approaches rely on.

### 3.3 Trigger, gates, ledger

- **Trigger:** every N completed investigations (default **N=10**), or on operator demand.
- **Promotion gates (all must pass):** replay dominance (§5.3) · `pytest tests/` green ·
  A1/A2/H1 acceptance criteria intact on replay · leak scan green on outward artifacts.
- **Every applied change appends to the tuning ledger** in `Aletheia-loop-engg.md` — the
  auto-tuner uses the same ledger as the human, so there is one history.
- **Retention:** after a tuning cycle consumes a batch of traces, it moves them to
  `runs/archive/` (kept for replay/audit; compressible or prunable by age). `runs/` holds
  only the current, not-yet-consumed batch — disk growth is bounded by design, matching the
  SKILL.md bloat guard in spirit: *nothing in the live path grows without bound*.

---

## 4. Approach A — Statistical recalibration (deterministic; no LLM in the tuning loop)

**What it tunes:** the numbers — sensor reliabilities, thresholds, costs.
**Cadence:** automatic, every N=10 runs, unattended.
**Implementation plan (approved, detailed):**
[`statistical-recalibration-implementation-plan.md`](statistical-recalibration-implementation-plan.md).

### 4.1 Mechanics — a pure-math offline pass (`autotune.py`, beside the coprocessor)

1. **Sensor-reliability re-estimation (Dawid–Skene-style EM).** Treat each investigated
   dimension-instance's true state as a latent variable and each sensor observation as a
   noisy annotator vote. EM alternates: infer likely true states from weighted votes →
   re-estimate each sensor's reliability from its agreement with those states → repeat.
   Sensors that persistently disagree with cross-sensor consensus drift down; consistently
   corroborated sensors drift up. **No labels required** — this is the classic unsupervised
   estimator for exactly our data shape.
2. **VOI-honesty audit.** Per sensor, compare cumulative `predicted_gain_bits` vs.
   `realized_gain_bits`. Persistent undershoot ⇒ reliability inflated, or the query template
   is returning noise (template problems are *flagged for Approach B*, never auto-edited here).
3. **Gate statistics ⇒ threshold proposals.** If `entropy_explore_above` never forced a turn
   in N runs, it is slack; if the exhaustion novelty branch fired on entities later shown
   findable, it is too eager; turn-count distributions sanity-check `max_iterations`.
4. **Bayesian shrinkage + clamps (what makes unattended safe).**
   - Each reliability carries a Beta prior centered on its current value; 10 runs of
     evidence *cannot* swing 0.90 → 0.55.
   - Hard clamp: **max ±0.05 per parameter per cycle**; thresholds ±0.03.
   - Writes touch **only** the `TUNABLE` block of `environment-prior.md`.
   - Full promotion gates (§3.3) before anything is applied.

### 4.2 Failure mode, stated honestly

Consensus-based estimation can reinforce **correlated errors** — every sensor fooled by the
same PR wave looks like agreement. Mitigations: shrinkage (above), the VOI-honesty audit
(catches sensors that "agree" while teaching nothing), and folding in deferred ground truth
as it arrives — resolved verdicts are the only cure for correlated delusion, and they
convert this whole pass from consistency-calibration into true calibration over time.

---

## 5. Approach B — Reflective champion–challenger tuning (agentic; structurally creative; gated)

**What it tunes:** structure — new sensors, query templates, scoping rules, plus bold
numeric moves outside A's clamps.
**Cadence:** every ~50 runs or on operator demand; human-approved at first (§6).

### 5.1 Mechanics

1. **Diagnose.** A dedicated tuning session (Aletheia reflecting on itself) reads the trace
   corpus, the tuning ledger, and the symptom→knob playbook in `Aletheia-loop-engg.md`, and
   names the dominant symptom with evidence — e.g. *"4 of 10 runs went INCONCLUSIVE on D3
   questions; D3 has one sensor; its realized gain is 0.4× predicted."*
2. **Propose a bounded challenger.** A concrete parameter-set diff, which — unlike Approach
   A — may be *structural*: a new sensor archetype with query template and a conservative
   starting reliability (how `search:customer_evidence` was born manually; here
   self-initiated), a rewritten template that keeps pulling namesake noise, a tightened
   dimension-scoping rule, a per-severity floor.
3. **The champion–challenger gate — the LLM proposes, the replay harness disposes.** The
   challenger is evaluated by deterministic replay (§3.2) plus the full promotion gates. It
   is promoted **only if it dominates**: same-or-better verdict directions on replayed runs,
   fewer wasted turns, no acceptance regression. The LLM's opinion of its own proposal
   carries zero weight in promotion.
4. **Genuinely new sensors get a probation flag**: replay can't validate a sensor that never
   ran, so new sensors enter at a conservative reliability, marked `probation: true` in the
   prior file, and Approach A's EM pass owns their reliability from their first real runs.

### 5.2 Why B exists at all

Approach A can only adjust numbers on existing structure. Every *qualitative* improvement
this project has made — the `customer_evidence` sensor, the exhaustion-gate novelty branch —
was structural, and each came from exactly the reflection B automates: reading run evidence
against the playbook and proposing a bounded change verified by re-running acceptance.

### 5.3 "Replay dominance," precisely

A challenger dominates iff, over the replayed corpus **and** the acceptance set:
(a) no replayed verdict flips direction against a known-good outcome; (b) mean turns-to-stop
does not increase; (c) no INCONCLUSIVE appears on a run that legitimately cleared the floor;
(d) A1/A2/H1 pass criteria all hold; (e) stated-confidence distribution does **not** shift
upward without new corroborating structure (the §2.2 invariant, made mechanical).

---

## 6. Recommendation — compose them; build in this order

**Run A continuously, B periodically.** A is the micro-tuner (numbers, unattended, safe by
construction); B is the macro-tuner (structure, gated, human-approved until trusted). They
share the substrate, so the build order is:

| Phase | Deliverable | Effort | Value unlocked |
|---|---|---|---|
| 1 | Trace schema v1 — new `reference/trace-schema.md` (the two gain fields + final-turn record); SKILL.md §0 gets a one-line pointer only (§3.1 bloat guard) | Small (doc edit) | Every future run becomes tuning food; SKILL.md stays constant-size |
| 2 | Replay harness (`autotune.py replay`) | Medium | Offline evaluation of *any* proposed tune — also upgrades the **manual** field-guide workflow immediately |
| 3 | Approach A pass (`autotune.py fit`) with shrinkage/clamps + gates + ledger append | Medium | Unattended numeric self-tuning at N=10 |
| 4 | Approach B protocol — a tuning-session procedure (skill or checklist) using 2+3 as its gate; human approval required for promotion | Small on top of 2–3 | Structural self-improvement, safely |
| 5 | Deferred ground-truth intake (`ground_truth` backfill + true calibration curve) | Ongoing | Converts consistency-tuning into real calibration; also closes the roadmap item |

Phases 1–3 deliver ~80% of B's infrastructure — which is the efficiency argument for this
ordering.

## 7. Hard rails (apply to both approaches, non-negotiable)

- **Never tunable, by anything:** the Constitution (I1–I13), the epistemic character, the
  §2.2 invariant, the leak-scan gate itself.
- Writes restricted to the `TUNABLE` block of `environment-prior.md`.
- Clamped deltas (A) / mandatory human approval for structural changes (B, initially).
- Every change: promotion gates + ledger entry + `robocopy` sync reminder for the user-wide
  install (it does not update itself).
- Rollback is one ledger-guided revert of the prior file — parameters are data, not code.

## 8. Agent-guidance requirements in `AGENTS.md` — per technique

Governance precedes capability: the always-in-force rules were added to `AGENTS.md` at
proposal time (imperative **I12** + the **Self-tuning discipline** section), because the
self-modification *risk* exists as soon as any session can edit the prior file — not when
the tuner ships. `AGENTS.md` is loaded in every session, so it carries only the compact
binding rules; this section is the full requirement map.

| # | Requirement (agent guidance) | Technique | Where it lives | Status |
|---|---|---|---|---|
| G1 | **Prime invariant**: tuning may make you cheaper / more consistent / better calibrated — never more confident | Both | `AGENTS.md` I12 (binding) + §2.2 here (rationale) + §5.3(e) (mechanical check) | ✅ in force |
| G2 | **No parameter changes outside the sanctioned workflow**; never tune to clean up a single answer; Constitution / character / leak gate untouchable by any pathway | Both | `AGENTS.md` I12 | ✅ in force |
| G3 | **Faithful telemetry** every investigation turn — complete, unshaped, embarrassing data included (I2 applied to self) | Both (feeds A; evidences B) | `AGENTS.md` Self-tuning discipline, bullet 1 | ✅ in force (schema arrives Phase 1) |
| G4 | **Operator-not-editor** role in the statistical pass: run the tool, apply only gated clamped output, no judgment overrides; objections → ledger + escalate | A | `AGENTS.md` Self-tuning discipline, bullet 2 | ✅ in force |
| G5 | **Proposer-not-judge** role in the reflective pass: symptoms cite run IDs; bounded diffs in TUNABLE space; replay+gates decide; self-flag overfitting risk; operator approval for structural changes | B | `AGENTS.md` Self-tuning discipline, bullet 3 | ✅ in force |
| G6 | **Role separation & silence**: never tune mid-investigation; tuning is operator-context; end users never learn tuning exists (I1) | Both | `AGENTS.md` Self-tuning discipline, bullet 4 | ✅ in force |
| G7 | Procedure-level mechanics (how to log per turn; how to invoke the tuner; probation handling) — deliberately **NOT** in `AGENTS.md` (bloat guard: governance file states *rules*, procedure files state *steps*) | Both | SKILL.md one-line telemetry pointer (Phase 1); tuner protocol doc (Phase 4) | ⬜ Phase 1 / 4 |

**Assessment note.** Technique A needs almost no *behavioral* guidance beyond G3/G4 — its
safety is structural (deterministic script, shrinkage, clamps, gates), which is precisely why
it can run unattended. Technique B is where agent guidance carries real weight: the agent
*is* the proposer, so its honesty norms (evidence-cited symptoms, self-flagged overfitting,
no advocacy past the gate) are load-bearing, not decorative. That asymmetry is reflected in
the AGENTS.md text: one bullet for A, the longest bullet for B.

## 9. Implementation checklist (track per phase; update in place)

### Phase 1 — Trace schema v1 ✅ (implemented 2026-07-03)
- [x] `reference/trace-schema.md` created (schema carries `schema_version: 1`; turn-1 rule:
  starting prior recorded for every question dimension so all-null runs stay replayable)
- [x] SKILL.md §0 gains exactly **one** pointer (existing telemetry line extended — bloat guard held)
- [x] All fields confirmed derivable from existing coprocessor output (zero new math in the live path)
- [x] Three recorded live investigations (A1/A2/H1) transcribed as schema-valid fixture
  traces (`tests/fixtures/trace-*.jsonl`), floats computed by `pomdp_belief` itself
- [x] G3 exercised: A2's three null turns and H1's null turn appear in the traces unshaped

### Phase 2 — Replay harness (`autotune.py replay`) ✅ (implemented 2026-07-03)
- [x] Determinism: champion replay of all three fixtures reproduces every recorded posterior
  exactly (`max_deviation_vs_recorded = 0.0`; `test_replay_reproduces_recorded_runs`)
- [x] Sensitivity smoke: weakening a sensor delays commitment as expected (`test_replay_sensitivity_smoke`)
- [x] Unit tests added; full suite green (29 passed)
- [x] Replay available for evaluating hand tunes (`replay --proposal <file>` emits the full
  dominance report — referenced from the field guide's workflow)

### Phase 3 — Statistical pass (`autotune.py fit`, Approach A) ✅ (implemented 2026-07-03)
- [x] EM + Beta-shrinkage implemented; recovers planted reliabilities on synthetic corpora
  (`test_em_recovers_planted_reliabilities`); shrinkage-damps + clamp-bounds verified
- [x] Clamp test: out-of-range fit clipped and the clip logged (`test_clamp_clips_and_logs`)
- [x] Write-path guard + byte-identical round-trip guard (tested); patches are atomic
- [x] Promotion gates wired and proven end-to-end: a live `apply` on a prior copy passed all
  7 named gates and patched exactly one numeric literal; a failing-pytest `apply` wrote nothing
- [x] **Confidence-invariant monitor**: upward mean shift ⇒ auto-reject (`test_confidence_invariant_autoreject`)
- [x] Ledger auto-append with the full gate vector; sync reminder emitted on every apply
- [x] `AGENTS.md` I12 + Self-tuning discipline confirmed in force (added at proposal time)
- [x] VOI-honesty report per cycle (`audit`), thresholds report-only, template problems flagged not edited

### Phase 4 — Reflective pass (Approach B protocol)
- [ ] Tuning-session protocol written (operator-triggered only; never fires from an end-user query)
- [ ] Proposal template enforced: symptom + cited run IDs + bounded diff + self-declared overfitting-risk note (G5)
- [ ] Human-approval gate ON by default for structural changes
- [ ] Probation mechanics for new sensors implemented (`probation: true`, conservative start; graduation rule decided — closes open question 4)
- [ ] Replay-dominance criteria §5.3 (a)–(e) produced as an automated pass/fail report
- [ ] Red-team check: a deliberately bad challenger (overfit to the archive) is correctly rejected by the gates

### Phase 5 — Deferred ground truth
- [ ] `ground_truth` backfill fields + intake procedure defined
- [ ] First calibration curve produced from resolved verdicts (also closes the README roadmap item)
- [ ] Correlated-error audit: EM run with labels vs. without; divergence reported

### Cross-cutting (verify at every phase)
- [ ] `runs/archive/` retention working; `runs/` holds only the unconsumed batch
- [ ] No forbidden tokens introduced into outward-facing artifacts (leak scan)
- [ ] Every applied change has a tuning-ledger entry (one history, human + machine)
- [ ] User-wide install re-synced after any prior-file change

## 10. Open questions (deliberately deferred)

1. N=10 trigger — right default, or should low-signal runs (INCONCLUSIVEs) count half?
2. Should follow-up user corrections in-session ("that's wrong, they IPO'd") be ingested as
   weak labels, and at what trust weight?
3. Multi-deployment learning: if several installs run Aletheia, do traces pool (privacy
   implications — traces contain investigated-entity names)?
4. When does a probation sensor graduate — fixed run count, or EM-confidence threshold?
