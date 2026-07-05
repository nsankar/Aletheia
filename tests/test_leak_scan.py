"""Confidentiality leak-scan tests (blueprint §8.2) — CI gate for imperative I1.

Verifies the scanner itself catches forbidden tokens, and that the Verdict templates
shipped in SKILL.md stay clean of internal method/IP language.
"""
import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL_MD = ROOT / ".claude" / "skills" / "aletheia" / "SKILL.md"
SCENARIOS_MD = ROOT / "tests" / "scenarios.md"
HARD_CASES_MD = ROOT / "tests" / "hard-cases.md"

spec = importlib.util.spec_from_file_location("leak_scan", Path(__file__).resolve().parent / "leak_scan.py")
leak_scan = importlib.util.module_from_spec(spec)
sys.modules["leak_scan"] = leak_scan
spec.loader.exec_module(leak_scan)


def test_scanner_flags_forbidden_tokens():
    dirty = "Our confidence comes from a Bayesian posterior with entropy 0.3 and distribution: {a:0.7}"
    hits = leak_scan.scan_text(dirty)
    found_tokens = {tok for tok, _ in hits}
    assert "Bayes" in found_tokens
    assert "entropy" in found_tokens
    assert "posterior" in found_tokens
    assert "distribution:" in found_tokens


def test_scanner_passes_clean_business_text():
    clean = (
        "VERDICT - Acme \"$10M ARR\"\n"
        "- Bottom line: the claim looks OVERSTATED. Confidence: HIGH (~94%)\n"
        "- Evidence: third-party review counts are low and growing slowly (G2).\n"
    )
    assert leak_scan.scan_text(clean) == []


def _extract_verdict_templates(skill_md_text: str) -> list[str]:
    """Pull out the fenced code blocks under the '## 6. Verdict rendering' section."""
    section = skill_md_text.split("## 6. Verdict rendering", 1)[1]
    section = section.split("\n## ", 1)[0]  # stop at the next top-level section
    return re.findall(r"```\n(.*?)```", section, re.DOTALL)


def test_verdict_templates_are_leak_free():
    text = SKILL_MD.read_text(encoding="utf-8")
    templates = _extract_verdict_templates(text)
    assert len(templates) >= 2, "expected both the standard and INCONCLUSIVE Verdict templates"
    for template in templates:
        hits = leak_scan.scan_text(template)
        assert hits == [], f"Verdict template leaks internals: {hits}"


def test_scenario_verdicts_are_leak_free():
    """CI gate (§8.2): every rendered Verdict in the A1-A3 scenario transcripts must be
    clean of internal method/IP language. The private belief-evolution tables in the same
    file are intentionally exempt (they are the operator/private view, not user-facing)."""
    text = SCENARIOS_MD.read_text(encoding="utf-8")
    verdicts = re.findall(r"```\nVERDICT.*?\n```", text, re.DOTALL)
    assert len(verdicts) >= 3, "expected at least the A1, A2, and A3 Verdicts"
    for verdict in verdicts:
        hits = leak_scan.scan_text(verdict)
        assert hits == [], f"scenario Verdict leaks internals: {hits}"


def test_hard_case_verdicts_are_leak_free():
    """Same CI gate for any live-run Verdicts recorded in the hard-case battery."""
    text = HARD_CASES_MD.read_text(encoding="utf-8")
    verdicts = re.findall(r"```\nVERDICT.*?\n```", text, re.DOTALL)
    assert len(verdicts) >= 1, "expected at least the H1 live-run Verdict"
    for verdict in verdicts:
        hits = leak_scan.scan_text(verdict)
        assert hits == [], f"hard-case Verdict leaks internals: {hits}"
