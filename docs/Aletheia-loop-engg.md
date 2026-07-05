# Aletheia — Loop Engineering & Fine-Tuning Field Guide

*Operator/developer doc. This file discusses internals freely — like `tests/scenarios.md`,
it is never user-facing. The confidentiality gate (I1) applies to verdicts and outward
artifacts, not to this guide.*

---

## 1. Yes, it's a loop — here is its anatomy

The blueprint's definition of the discipline: **a loop = trigger + verifiable goal +
belief/state + stopping conditions.** Aletheia implements each part explicitly:

| Loop part | Aletheia's implementation | Where |
|---|---|---|
| **Trigger** | Investigation intent inferred from a plain business question (user never names a skill) | `AGENTS.md` engagement rules + skill `description` |
| **Verifiable goal** | Belief collapsed on the asked dimension(s) — confidence ≥ floor AND uncertainty settled | `SKILL.md` §5 |
| **Belief / state** | Per-dimension probability distributions, persisted to disk every turn (I7) | `runs/belief-*.md`, updated by the coprocessor |
| **Stopping conditions** | Three independent stops: floor cleared · hard budget (I5) · exhaustion (2 branches) | `environment-prior.md` thresholds block |

The cycle itself (`SKILL.md` §0.5–§5):

```
shield → choose next look (VOI ranking) → search → belief update → stopping gate → repeat
```

What makes it a *POMDP* loop rather than merely iterative is **what carries between turns**:
not a growing transcript but an explicit belief state that each observation updates via the
coprocessor (`pomdp_belief.py`). The loop never runs "until it feels done" — it runs until a
verifiable condition fires.

**Field evidence (live runs).** Three runs, three different stop reasons, none of
them vibes:
- **A1 (Anthropic):** 5 turns — stopped on *floor cleared* for D1/D2 + *sensor exhaustion*
  on D0 (honest "leans real .74, below floor").
- **A2 (Northwind):** 3 turns — stopped on the *exhaustion novelty branch* (three distinct
  sensors, zero signal → INCONCLUSIVE, no fabrication).
- **H1 (11x):** 5 turns — stopped on *floor cleared* (D0 inflated .93) after the entropy
  gate refused a one-observation commit at .82.
- `max_iterations` (8) has **never** been reached — the smarter gates always fire first,
  which is exactly the intended role of a circuit breaker.

---

## 2. Loop configuration reference

All loop knobs live in **one file** —
[`environment-prior.md`](../.claude/skills/aletheia/reference/environment-prior.md), the
`Thresholds & Stopping Policy (TUNABLE)` block — deliberately separated from the governance
layer so operators can tune without touching the Constitution.

| Knob | Current | What it controls | Tuning trade-off |
|---|---|---|---|
| `max_iterations` | 8 | Hard circuit breaker (I5) | Pure cost cap; insurance, not a tool. Lowering below ~6 risks truncating legitimate multi-dimension runs |
| `confidence_floor` | 0.80 | Minimum leading-hypothesis probability to commit a verdict | ↑ = fewer wrong calls, more searches, more INCONCLUSIVEs. ↓ = more decisive, higher overconfidence risk |
| `entropy_explore_above` | 0.55 | Forces continued gathering even when the floor is met | The anti-lucky-observation gate. In A1 it forced the turn that *disconfirmed*; in H1 the turn that *confirmed*. ↓ = demand more corroboration per verdict |
| `exhaustion_gate` | 2 branches | "More searching won't teach us anything": (a) repetition — last 2 queries ≥0.8 Jaccard AND novelty <0.15; (b) novelty — ≥3 consecutive distinct-sensor turns each <0.15 novelty | Sensitivity trades wasted searches against premature abstention. Branch (b) is what stops unfindable-entity runs at 3 turns instead of 8 |
| `persist_belief_to` | `./runs/belief-*.md` | Audit-trail location (I7) | Placement only |

**Related but outside the thresholds block:**
- **Action costs** (`ℛ` section): search = −1, full-document `WebFetch` = −2. These feed the
  VOI *gain-per-cost* ranking — cheapening WebFetch makes the loop reach for primary
  documents earlier (accuracy ↑, latency ↑). Note: the coprocessor treats costs as
  magnitudes (`abs()`), so the sign convention can't invert the ranking.
- **Per-turn web-call budget**: `SKILL.md` guardrails hold it to ~1–2 calls per turn.

---

## 3. Everything else that's configurable

### The sensor map (the biggest accuracy lever — with proof)
Each sensor = a search archetype: dimension(s) revealed + reliability + `query_template`.
Configurable per deployment, and **provably the highest-impact knob**: adding one sensor
(`search:customer_evidence`, 0.82, D0) flipped A1's traction read from leaning-inflated
(.38) to leaning-real (.74) — a verdict-direction change no threshold tweak could produce.
**Thresholds change *when* you stop; sensors change *what you can know*.**

Current known gaps (recorded, unfixed):
- **D3 (pricing power) is thin** — one sensor (`pricing_page_diff`, 0.85). A second (e.g.
  discount-chatter/deal-desk signals at low reliability) would let D3 verdicts survive a
  conflict the way D0 now can.
- **Recency is not a sensor property** — H5's stale-headlines trap is handled today by the
  epistemic character ("evidence decays"), not by the math. A `freshness_weight` per sensor
  is the clean future fix.

### State dimensions
Binary per dimension (v1, handoff decision D3). The coprocessor is k-ary already — widening
to `{real, mixed, inflated}` or adding dimensions (team stability, regulatory exposure) is a
prior-file edit, not new math.

### Scoping rules
`SKILL.md` §0 maps the user's question to implicated dimensions ("investigate ONLY those").
Editing these mappings changes what a query class costs — and is also the fix if runs answer
the wrong (easier) dimension.

### Safety configuration
- The **leak-scan token list** (`tests/leak_scan.py FORBIDDEN_TOKENS`) — extend it whenever a
  new internal term enters the vocabulary.
- **NOT configurable, by design:** the Constitution (I1–I13) and the epistemic character in
  `AGENTS.md`. Precedence is `imperatives > stopping policy > everything`. You can tune the
  floor to 0.6 and get an aggressive loop — no setting can make it fabricate a source or
  assert fraud.

---

## 4. Fine-tuning field guide

### Principles (read before touching anything)
1. **Measure, then tune.** The reliabilities (0.65–0.90) are informed estimates. The
   roadmapped calibration curve (~15–20 labeled multi-turn runs, predicted vs. actual
   hit-rate) is what turns them empirical. Tuning reliabilities before you have that data is
   guessing with extra steps.
2. **Sensors before thresholds.** If verdicts are *wrong*, the loop is missing or mis-weighing
   evidence — fix the map. If verdicts are *right but slow/hedgy*, then look at thresholds.
3. **Never tune to force a clean pass.** A1's honest .74-below-floor was deliberately left
   unforced (see `tests/scenarios.md`). The product IS the meaningfulness of the number; a
   manufactured .81 destroys the only thing being sold.
4. **One knob at a time**, re-run the acceptance set, record what changed.

### Symptom → knob playbook

| Symptom | Likely cause | Knob | Verify with |
|---|---|---|---|
| Too many INCONCLUSIVEs on answerable questions | Asked dimension has too few / too-weak sensors | Add a sensor for that dimension (the `customer_evidence` precedent) | Re-run A1; the dimension should move materially, honestly |
| Overconfident one-source verdicts | Entropy gate too loose | Lower `entropy_explore_above` (e.g. .55 → .50) | A1/H1 style runs must take the extra corroborating turn |
| Wrong verdicts with confident tone | Mis-weighted source types | Audit sensor reliabilities vs. what the source type can actually know; run the calibration curve | H1 pass criteria (denials must outweigh the logo wall) |
| Runs feel slow / expensive | Weak sensors being run on nearly-settled dimensions | Raise search costs asymmetrically, or tighten exhaustion novelty threshold | Turn counts on A1/A2/H1 (5/3/5 is the baseline) |
| Premature INCONCLUSIVE on findable entities | Exhaustion novelty branch too eager | Require 4 (not 3) zero-novelty distinct-sensor turns | A2 must still stop at 3–4; findable entities must not |
| Answers the easy dimension, not the asked one | Scoping mapping too loose | Tighten §0 dimension-implication rules | H7 (pricing-power question must yield a D3 verdict) |
| Severe claims feel under-guarded | One floor for all severities | Add a **per-severity floor** (e.g. fraud-adjacent verdicts need 0.90) to the thresholds block — one line, directly serves I10 | A3/H9: substance intact, framing hypothesis-labeled |
| New internal vocabulary appearing in docs | Leak list stale | Extend `FORBIDDEN_TOKENS` | `pytest tests/` + `python tests/leak_scan.py <outward-facing-file>` |

### The tuning workflow (every time)

```powershell
# 1. Edit the dev copy only
#    .claude\skills\aletheia\reference\environment-prior.md  (thresholds / sensors / costs)

# 2. Re-verify: unit + CI gates
python -m pytest tests/ -q

# 3. Re-verify: behavior — re-run the cheap acceptance set by hand or in a fresh session
#    A1 (mixed evidence), A2 (must stay INCONCLUSIVE), H1 (must stay OVERSTATED ~.9)
#    plus the leak scan on anything outward-facing:
python tests/leak_scan.py <outward-facing-file>

# 4. Sync the user-wide install (it does NOT update itself)
robocopy .claude\skills\aletheia "$env:USERPROFILE\.claude\skills\aletheia" /E /XD __pycache__

# 5. Record the change: what knob, why, what the acceptance runs showed
#    (append a dated line at the bottom of this file)
```

> **Automating this guide:** the playbook and workflow below are designed to be executable
> by Aletheia itself — see [`auto-tuner-workflow-proposal.md`](auto-tuner-workflow-proposal.md)
> for the self-tuning design (statistical recalibration + gated champion–challenger, both
> promoted only via deterministic trace replay). Status: proposed, not implemented.

### Where tuning effort actually pays (priority order)
1. **Sensor-map enrichment** — proven verdict-direction impact (D3 and a recency property
   are the known gaps).
2. **The calibration curve** — converts reliability guesses into measured values; everything
   downstream sharpens (roadmapped in `README.md` / `tests/scenarios.md`).
3. **Exhaustion-gate tuning** — the proven efficiency lever (the research line this gate
   comes from reports ~39% fewer tokens vs. letting the model decide when to stop).
4. **Per-severity floors** — cheap, high-value effectiveness upgrade for I10.
5. **Thresholds themselves** — last, only with acceptance evidence, never to force a pass.

---

## Tuning ledger

| Date | Change | Reason | Acceptance result |
|---|---|---|---|
| — | Added `search:customer_evidence` (D0, 0.82) | D0 under-served; strongest traction evidence had no home | A1: D0 .38→.74 (honest, below floor); H1 live: pivotal disconfirming read; 16 tests green |
| — | Exhaustion gate: added explicit novelty branch (b) | A2's stop wasn't licensed by the repetition-only spec | A2 stop now spec-conformant at 3 turns |
| — | Auto-tuner Approach A implemented: `scripts/autotune.py` (status/replay/fit/apply/audit) + `reference/autotune-config.toml` + `reference/trace-schema.md` + fixtures | Proposal §6 Phases 1–3; no parameter values changed | 29 tests green; champion replay bit-exact (dev 0.0); full-gates `apply` proven on a prior copy (7/7 gates); real prior untouched |
| — | Hands-free automation: central telemetry spool (`~/.claude/aletheia-runs/`), `scripts/autotune_cycle.py` (throttled, quarantining, auto-syncing), user-level SessionEnd hook, `[automation]` config section, AGENTS.md automated-cycle + retention governance | "Only when you ask" fails non-technical/forgetful users; scattering fixed at source | 32 tests green (hook contract + master-guard tests); wrapper pipe-tested: silent/0.2s no-op, quarantine self-heal verified on the real nonconforming real-world trace |
