#!/usr/bin/env python3
"""Build the Cowork-uploadable plugin package: dist/aletheia.zip + dist/aletheia.plugin.

Run from the repo root:  python build-cowork-plugin.py

Why this script exists (lessons already paid for — do not regress):
  * Cowork upload requires the CANONICAL plugin layout: `.claude-plugin/plugin.json` +
    `skills/` at the plugin ROOT (this repo keeps skills under `.claude/skills/`, which is
    fine for the repo but wrong inside the upload package). The manifest is therefore
    generated here, without a custom skills path.
  * Zip entry paths MUST use forward slashes (zip spec). PowerShell's Compress-Archive
    writes backslashes and Cowork rejects the archive with "Zip file contains path with
    invalid characters" — always build this archive with Python's zipfile, never
    Compress-Archive.
  * Both extensions are produced because some app builds only accept `.zip` in the
    upload dialog even though `.plugin` is the documented name.
  * The Cowork validator rejects SKILL.md descriptions containing anything that looks
    like an XML tag ("SKILL.md description cannot contain XML tags") — keep angle-bracket
    placeholders like <metric> out of the frontmatter description (natural phrasing only).
"""
from __future__ import annotations

import json
import shutil
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SKILL_SRC = ROOT / ".claude" / "skills" / "aletheia"
DIST = ROOT / "dist"
STAGE = DIST / "aletheia-plugin"

MANIFEST = {
    "name": "aletheia",
    "displayName": "Aletheia",
    "version": "0.2.0",
    "description": (
        "Competitive & market-intelligence investigator: verifies whether a company's or "
        "market's claimed traction, funding, momentum, or pricing is real, and returns a "
        "calibrated verdict with an evidence trail and residual unknowns."),
    "author": {"name": "POMDP-Loop"},
    "license": "MIT",
    "keywords": ["competitive-intelligence", "diligence", "claim-verification",
                 "market-research", "osint"],
}


def main() -> int:
    if not SKILL_SRC.is_dir():
        raise SystemExit(f"skill source not found: {SKILL_SRC} (run from the repo root)")
    stage = STAGE
    for attempt in range(3):          # OneDrive sync locks: retry, then fall back
        try:
            if stage.exists():
                shutil.rmtree(stage)
            break
        except PermissionError:
            time.sleep(1.0)
    else:
        stage = DIST / f"aletheia-plugin-{int(time.time())}"
        print(f"note: staging dir locked (OneDrive?); using {stage.name}")
    shutil.copytree(SKILL_SRC, stage / "skills" / "aletheia",
                    ignore=shutil.ignore_patterns("__pycache__"))
    (stage / ".claude-plugin").mkdir(parents=True)
    (stage / ".claude-plugin" / "plugin.json").write_text(
        json.dumps(MANIFEST, indent=2) + "\n", encoding="utf-8")

    out = DIST / "aletheia.zip"
    out.unlink(missing_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(stage.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(stage).as_posix())   # forward slashes, always
    shutil.copy(out, DIST / "aletheia.plugin")

    with zipfile.ZipFile(out) as z:
        bad = [n for n in z.namelist() if "\\" in n]
        if bad:
            raise SystemExit(f"BUG: backslash entries in archive: {bad}")
        print(f"OK: {out} ({out.stat().st_size / 1024:.1f} KB), "
              f"{len(z.namelist())} entries, all forward-slash. "
              f"Also wrote {DIST / 'aletheia.plugin'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
