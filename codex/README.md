# Aletheia — OpenAI Codex build

`AGENTS.md` in this folder is a **fully self-contained** Codex instruction for Aletheia:
governance (Constitution I1–I13, epistemic character, self-tuning discipline, engagement
rules) **plus the entire investigation procedure inlined**. Codex reads `AGENTS.md`
natively and has no `CLAUDE.md` and no auto-triggering skill mechanism, so — unlike the
Claude Code build (root `AGENTS.md` + thin `CLAUDE.md` + `SKILL.md` skill) — everything the
agent needs to *behave* lives in this one file.

## What it still reuses from the repo
Only data and code, never behavior:

| Reused asset | Path (relative to repo root) | Purpose |
|---|---|---|
| Parameter file | `.claude/skills/aletheia/reference/environment-prior.md` | state space, sensor map, thresholds |
| Trace schema | `.claude/skills/aletheia/reference/trace-schema.md` | telemetry format the tuner requires |
| Math helper | `.claude/skills/aletheia/scripts/pomdp_belief.py` | exact belief update / VOI |
| Tuner (operator) | `.claude/skills/aletheia/scripts/autotune.py`, `autotune_cycle.py` | offline recalibration |

`AGENTS.md` refers to that folder as `ALETHEIA_HOME = .claude/skills/aletheia`.

## Deploy
1. Make this file the `AGENTS.md` Codex loads for the session — either **copy it to the
   root** of the folder you open in Codex, or **launch Codex from this `codex/` directory**.
   (Personal global default: `~/.codex/AGENTS.md`.)
2. Keep the `.claude/skills/aletheia/` folder alongside it and **launch Codex from the repo
   root** so the `ALETHEIA_HOME` relative paths resolve. If you must launch elsewhere,
   substitute an absolute base path in `AGENTS.md`.
3. Ask a plain business question ("is this vendor's claimed ARR real?") — the procedure
   auto-engages; the user never names anything.

## Differences from the Claude Code build (by design)
- **Procedure is inlined**, not loaded as a skill (Codex has no equivalent auto-trigger).
- **Tuning is operator-run**, not automatic: Codex has no session-end hook, so run
  `python .claude/skills/aletheia/scripts/autotune.py status|fit|apply|audit` yourself, in
  operator context only. (In Claude Code a hook does this hands-free.)
- **Tool phrasing is harness-neutral** ("your web-search capability", "run in the shell").

## Keeping it in sync — it's generated, don't hand-edit
`AGENTS.md` here is **built** from the canonical sources (root `AGENTS.md` + the skill's
`SKILL.md`) by `build-codex-agents.py`. Do not edit it by hand.

```bash
python build-codex-agents.py          # regenerate after any governance/procedure change
python build-codex-agents.py --check  # CI/pre-commit: fail if it's stale
```

Shared sections (Constitution, epistemic character, domain, operator/end-user, how-you-
speak, the whole procedure §0–§6) are lifted verbatim, so source edits propagate on the next
build. The genuine harness-deltas (identity 2nd paragraph, Deployment note, skill→procedure
wording, the "session-end hook"→"operator-run" tuning bullet, tool phrasing) are applied as
whitespace-flexible **anchored** transforms — if a source is reworded so an anchor no longer
matches, the build **fails loudly** naming the anchor, forcing a conscious re-sync. The test
suite runs `--check`, so a stale file fails CI.
