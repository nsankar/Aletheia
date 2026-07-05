#!/usr/bin/env python3
"""Generate codex/AGENTS.md from the canonical Claude Code sources — no hand-editing.

Run from the repo root:
    python build-codex-agents.py            # regenerate codex/AGENTS.md
    python build-codex-agents.py --check     # verify it is up to date (CI); exit 1 if stale

Why this exists
---------------
OpenAI Codex reads AGENTS.md natively but has no CLAUDE.md and no auto-triggering skill, so
the Codex build must be ONE self-contained file = governance + the full investigation
procedure inlined. That duplicates text that canonically lives in the repo's root AGENTS.md
(governance) and .claude/skills/aletheia/SKILL.md (procedure). This script regenerates the
Codex file from those two sources so they can never silently drift.

Robustness model
----------------
- Shared sections (Constitution, epistemic character, domain, operator/end-user, how-you-
  speak, the whole procedure §0-§6) are LIFTED VERBATIM — edits to the sources propagate on
  the next build automatically.
- The genuine harness-deltas (identity 2nd paragraph, deployment note, skill->procedure
  wording, the self-tuning "session-end hook" bullet, tool phrasing) are applied as
  whitespace-flexible ANCHORED transforms. Every REQUIRED transform asserts its anchor is
  present; if a source is reworded so an anchor no longer matches, the build FAILS LOUDLY
  naming the anchor — forcing a conscious re-sync rather than emitting stale text.
- Final validators: <= 32 KiB (Codex instruction cap), exactly 13 imperatives, no leftover
  ${CLAUDE_SKILL_DIR}, no stale "I1-I11", de-hashed Constitution preamble, and every
  referenced asset path exists on disk.
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC_GOV = ROOT / "AGENTS.md"
SRC_PROC = ROOT / ".claude" / "skills" / "aletheia" / "SKILL.md"
OUT = ROOT / "codex" / "AGENTS.md"

ASSETS = [
    ".claude/skills/aletheia/reference/environment-prior.md",
    ".claude/skills/aletheia/reference/trace-schema.md",
    ".claude/skills/aletheia/scripts/pomdp_belief.py",
    ".claude/skills/aletheia/scripts/autotune.py",
    ".claude/skills/aletheia/scripts/autotune_cycle.py",
]
CODEX_CAP_BYTES = 32 * 1024


class BuildError(Exception):
    pass


# ---------------------------------------------------------------- extraction

def read(p: Path) -> str:
    if not p.is_file():
        raise BuildError(f"source not found: {p}")
    return p.read_text(encoding="utf-8")


def section(text: str, needle: str) -> str:
    """Return the `## ...` section whose header contains `needle` (header -> next `## `)."""
    lines = text.splitlines(keepends=True)
    start = next((i for i, l in enumerate(lines)
                  if l.startswith("## ") and needle in l), None)
    if start is None:
        raise BuildError(f"section not found: '{needle}'")
    end = next((j for j in range(start + 1, len(lines))
                if lines[j].startswith("## ")), len(lines))
    return "".join(lines[start:end]).rstrip() + "\n"


def intro(text: str) -> str:
    """Return the text between the H1 title and the first `## ` section."""
    lines = text.splitlines(keepends=True)
    h1 = next(i for i, l in enumerate(lines)
              if l.startswith("# ") and not l.startswith("## "))
    end = next(j for j in range(h1 + 1, len(lines)) if lines[j].startswith("## "))
    return "".join(lines[h1 + 1:end]).strip() + "\n"


# ---------------------------------------------------------------- transforms

def flex_sub(text: str, anchor: str, replacement: str, *,
             required: bool = True, label: str = "") -> str:
    """Whitespace-flexible anchored replacement.

    Any run of whitespace in `anchor` matches any run of whitespace in `text` (so source
    line-wrapping never breaks a transform). If `required` and the anchor is absent, raise
    with the label — this is how source drift is caught instead of silently shipped.
    """
    # Tokenize on whitespace and rejoin escaped tokens with \s+ so any whitespace run in the
    # source (including line wraps) matches. (Avoids re.escape's space-escaping quirk.)
    pat = r"\s+".join(re.escape(tok) for tok in anchor.split())
    new, n = re.subn(pat, lambda _m: replacement, text)
    if n == 0 and required:
        raise BuildError(
            f"anchor not found for transform [{label or anchor[:48]!r}] — a canonical "
            f"source was reworded; update this transform in build-codex-agents.py")
    return new


def dehash_constitution(con: str) -> str:
    """Convert the `# HARD constraints...` comment preamble (before I1) to plain prose."""
    out, seen_i1 = [], False
    for l in con.splitlines(keepends=True):
        if re.match(r"- I1\b", l):
            seen_i1 = True
        if not seen_i1 and l.startswith("# ") and not l.startswith("## "):
            l = re.sub(r"^#\s?", "", l)
        out.append(l)
    return "".join(out)


def procedure_body(skill: str) -> str:
    """Strip frontmatter + Claude preamble; take `## 0. Initialize`->EOF; number as `## §N`."""
    parts = skill.split("---", 2)
    body = parts[2] if len(parts) == 3 else skill
    idx = body.find("## 0. Initialize")
    if idx < 0:
        raise BuildError("procedure start '## 0. Initialize' not found in SKILL.md")
    proc = body[idx:].rstrip() + "\n"
    proc = re.sub(r"^## (\d)", r"## §\1", proc, flags=re.M)
    # Neutralize Claude-specific tool phrasing (best-effort: cosmetic, don't fail on drift).
    proc = flex_sub(
        proc,
        "(via the Read tool — portable, and bundled with this procedure so it resolves "
        "whether this runs as a project skill or an installed plugin)",
        "(read it with your file tool)", required=False)
    proc = flex_sub(
        proc, "a targeted `WebSearch` (or `WebFetch` for a specific public",
        "a targeted web search (or fetch a specific public", required=False)
    proc = flex_sub(
        proc, "Rank them by expected information gain per unit cost:",
        "Rank them by expected information gain per unit cost (run in the shell):",
        required=False)
    return proc


# ---------------------------------------------------------------- static harness-delta blocks

HEADER = """\
<!-- AGENTS.md — Aletheia (OpenAI Codex build). GENERATED by build-codex-agents.py from the
     canonical AGENTS.md (governance) + .claude/skills/aletheia/SKILL.md (procedure). DO NOT
     EDIT BY HAND — edit those sources and rerun `python build-codex-agents.py`. Self-contained
     because Codex reads AGENTS.md natively and has no CLAUDE.md and no auto-triggering skill;
     the Python helper and parameter files are reused from the skill folder (see Deployment).
     Keep the merged AGENTS.md chain under Codex's 32 KiB instruction cap. -->
# Aletheia — Agent Governance & Procedure (Codex build)"""

IDENTITY_P2_OLD = (
    "This file governs how you behave. It is always in force. It does **not** contain the "
    "operational parameters of the investigation procedure — those are loaded by the "
    "procedure itself when it runs.")
IDENTITY_P2_NEW = (
    "This file is always in force. It contains everything: the non-negotiable rules, your\n"
    "epistemic character, the domain, and the investigation procedure itself. The only things\n"
    "loaded from disk at run time are the numeric operational parameters and the math helper\n"
    "(see **Deployment** below).")

DEPLOYMENT = """\
## Deployment (Codex) — how this file runs
- **Placement.** Codex auto-reads `AGENTS.md` from the repo root down to the working
  directory and merges them (nearest wins). To activate Aletheia, this file must be the
  `AGENTS.md` that Codex loads for the session — either copy it to the root of the folder
  you open in Codex, or run Codex from this `codex/` directory. Personal global default:
  `~/.codex/AGENTS.md`.
- **`ALETHEIA_HOME`** = `.claude/skills/aletheia` (relative to the repo root). It holds the
  reused assets — the parameter file, the trace schema, and the Python helpers. Keep that
  folder alongside this file and launch Codex from the repo root so the relative paths
  below resolve. (If you must launch elsewhere, substitute an absolute base path.)
- **Tools.** Where the procedure says *search*, use your web-search capability; where it
  says *fetch a document*, fetch the public page; where it says *run the helper*, run the
  Python command in the shell. Read the parameter/schema files with your file-read tool.
  Never use write/patch tools for anything except the belief file and the telemetry trace."""

DOMAIN_SUFFIX = (
    "The domain is not the limit — the same machinery applies to any hidden-truth question\n"
    "with noisy public signals (contractor credentials, viral research claims, …); only the\n"
    "parameter file's state space and sensor map change.")

PROCEDURE_INTRO = """\
---

# The investigation procedure (§0–§6) — PRIVATE working method

The true state of the entity is HIDDEN; every search result is a NOISY clue. Never guess
while uncertainty is high — act to reduce uncertainty first, then commit to a calibrated
Verdict. Everything in §0–§5 is private working state; only the final Verdict (§6) is shown
to the user. This procedure operationalizes the Constitution (I1–I13); it does not weaken it."""

SELFTUNE_HOOK_OLD = (
    "- **Automated cycles are sanctioned — and they are the harness's job, not yours.** A "
    "session-end hook runs the same sanctioned workflow (same gates, clamps, ledger) with no "
    "one asking. Therefore: never launch a tuning pass mid-conversation on your own "
    "initiative, never delay answering a question to tune first, and never announce that "
    "automated tuning exists to an end user. If an operator asks why parameters changed, the "
    "tuning ledger is the answer.")
SELFTUNE_HOOK_NEW = (
    "- **On Codex there is no session-end hook** (that is a Claude Code harness feature), so\n"
    "  the automated cycle does not fire on its own here. Tuning is **operator-run** and only\n"
    "  in operator context: `python ${ALETHEIA_HOME}/scripts/autotune.py status | fit | apply\n"
    "  | audit` (or the guarded wrapper `autotune_cycle.py`). Never launch a tuning pass\n"
    "  mid-investigation on your own initiative; never delay answering to tune first. The\n"
    "  tuning ledger is the record of why parameters changed.")


# ---------------------------------------------------------------- assembly

def build() -> str:
    gov = read(SRC_GOV)
    skill = read(SRC_PROC)

    # Identity intro (verbatim p1) with the harness-specific 2nd paragraph swapped in.
    identity = flex_sub(intro(gov), IDENTITY_P2_OLD, IDENTITY_P2_NEW, label="identity p2")

    constitution = dehash_constitution(section(gov, "NON-NEGOTIABLE CONTROL IMPERATIVES"))
    character = section(gov, "Epistemic character")
    domain = section(gov, "What you investigate").rstrip() + "\n" + DOMAIN_SUFFIX

    when = section(gov, "When to run an investigation")
    when = flex_sub(when,
                    "run the **aletheia investigation procedure** (the `aletheia` skill) "
                    "and return a Verdict.",
                    "run the **investigation procedure** inlined below\n(§0–§6) and return "
                    "a Verdict.", label="when: skill->procedure")
    when = flex_sub(when, "They will never name a skill, a method, or a file.",
                    "They will never name a method\n  or a file.", label="when: name-skill")
    when = flex_sub(when,
                    "Never ask the user to invoke anything, and never mention the skill by "
                    "name.",
                    "Never ask the user to invoke anything, and never mention the procedure\n"
                    "  or its files.", label="when: mention-skill")

    proc = procedure_body(skill)

    selftune = flex_sub(section(gov, "Self-tuning discipline"),
                        SELFTUNE_HOOK_OLD, SELFTUNE_HOOK_NEW, label="self-tuning hook bullet")

    operator = section(gov, "Operator vs. end user")
    speak = section(gov, "How you speak")

    blocks = [
        HEADER,
        identity.rstrip(),
        DEPLOYMENT,
        constitution.rstrip(),
        character.rstrip(),
        domain.rstrip(),
        when.rstrip(),
        PROCEDURE_INTRO,
        proc.rstrip(),
        "---",
        selftune.rstrip(),
        operator.rstrip(),
        speak.rstrip(),
    ]
    doc = "\n\n".join(blocks).rstrip() + "\n"
    doc = doc.replace("${CLAUDE_SKILL_DIR}", "${ALETHEIA_HOME}")
    validate(doc)
    return doc


def validate(doc: str) -> None:
    size = len(doc.encode("utf-8"))
    if size > CODEX_CAP_BYTES:
        raise BuildError(f"output {size} bytes exceeds Codex 32 KiB instruction cap")
    n_imp = len(re.findall(r"^- I\d+ ", doc, re.M))
    if n_imp != 13:
        raise BuildError(f"expected 13 imperatives, found {n_imp}")
    if "${CLAUDE_SKILL_DIR}" in doc:
        raise BuildError("leftover ${CLAUDE_SKILL_DIR} — path variable not swapped")
    if "${ALETHEIA_HOME}" not in doc:
        raise BuildError("no ${ALETHEIA_HOME} references — procedure paths missing")
    for stale in ("I1–I11", "I1-I11"):
        if stale in doc:
            raise BuildError(f"stale imperative range {stale!r} present")
    if re.search(r"^# HARD", doc, re.M):
        raise BuildError("Constitution preamble not de-hashed (# HARD line remains)")
    missing = [a for a in ASSETS if not (ROOT / a).is_file()]
    if missing:
        raise BuildError(f"referenced assets missing on disk: {missing}")


def _write(doc: str) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(3):                       # OneDrive can hold a transient lock
        try:
            OUT.write_text(doc, encoding="utf-8")
            return
        except PermissionError:
            time.sleep(1.0)
    OUT.write_text(doc, encoding="utf-8")     # final attempt: let it raise


def main(argv: list[str]) -> int:
    try:
        doc = build()
    except BuildError as e:
        print(f"BUILD FAILED: {e}", file=sys.stderr)
        return 2
    size_kib = len(doc.encode("utf-8")) / 1024
    if "--check" in argv:
        current = OUT.read_text(encoding="utf-8") if OUT.is_file() else ""
        if current != doc:
            print("STALE: codex/AGENTS.md is out of date — run: python build-codex-agents.py",
                  file=sys.stderr)
            return 1
        print(f"OK: codex/AGENTS.md is up to date ({size_kib:.1f} KiB, 13 imperatives).")
        return 0
    _write(doc)
    print(f"OK: wrote {OUT} ({size_kib:.1f} KiB / 32 KiB cap, 13 imperatives, "
          f"assets verified).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
