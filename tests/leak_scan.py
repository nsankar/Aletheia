#!/usr/bin/env python3
"""leak_scan.py — confidentiality leak-scan for Aletheia's user-facing output (blueprint §8.2).

Greps a user-facing artifact (a Verdict, a transcript excerpt, etc.) for tokens that would
expose the internal POMDP method/IP (imperative I1). Exits non-zero on any hit.

The private `runs/belief-*.md` file is EXEMPT by design — this scanner is only meant to be
run against text that is shown to the end user (a rendered Verdict, or the user-facing half
of a scenario transcript), never against the belief file itself.

Usage:
    python leak_scan.py file1.txt [file2.txt ...]   # scan files
    echo "some verdict text" | python leak_scan.py  # scan stdin
"""
from __future__ import annotations
import re
import sys

FORBIDDEN_TOKENS = [
    # blueprint §8.2 baseline list:
    "POMDP",
    "belief",
    "entropy",
    "Bayes",
    "posterior",
    "reliability",
    "value-of-information",
    "VOI",
    "distribution:",
    "confidence_floor",
    "exhaustion_gate",
    "Jaccard",
    # extensions beyond the baseline — other names for the same internals that a leak could use.
    # (Deliberately NOT "prior": it collides with legitimate business phrasing like
    # "prior year" / "priority"; the concept is already covered by belief/Bayes/distribution.)
    "Markov",
    "coprocessor",
    "information gain",
    "information-gain",
    "value of information",
]

# Plain substring match (catches derived forms like "Bayesian", "beliefs", "reliabilities"),
# except for short acronyms that collide with common English words ("VOI" inside "avoid",
# "voice", "devoid") — those get strict word boundaries instead.
_WORD_BOUNDARY_TOKENS = {"VOI"}
_PATTERNS = [
    re.compile(
        r"(?<![\w-])" + re.escape(tok) + r"(?![\w-])" if tok in _WORD_BOUNDARY_TOKENS else re.escape(tok),
        re.IGNORECASE,
    )
    for tok in FORBIDDEN_TOKENS
]


def scan_text(text: str) -> list[tuple[str, str]]:
    """Return a list of (token, matching_line) for every forbidden token found."""
    hits = []
    for line in text.splitlines():
        for tok, pattern in zip(FORBIDDEN_TOKENS, _PATTERNS):
            if pattern.search(line):
                hits.append((tok, line.strip()))
    return hits


def main(argv: list[str]) -> int:
    if argv:
        text = ""
        for path in argv:
            with open(path, "r", encoding="utf-8") as f:
                text += f.read() + "\n"
    else:
        text = sys.stdin.read()

    hits = scan_text(text)
    if hits:
        print(f"LEAK SCAN FAILED — {len(hits)} forbidden token(s) found:", file=sys.stderr)
        for tok, line in hits:
            print(f"  [{tok}] {line}", file=sys.stderr)
        return 1
    print("LEAK SCAN OK — no forbidden tokens found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
