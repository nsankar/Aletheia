# Aletheia — User Guide (local install, nothing published)

Aletheia answers one question well: **"Is that company's / market's claim actually true?"**
You ask a plain business question — *"Is Acme really at $10M ARR?"*, *"Can I trust this
vendor's growth numbers?"* — and it investigates public evidence and returns a **Verdict**:
a bottom-line call, a plain-English confidence, the evidence with sources, and what it
could *not* verify. When evidence is thin it says INCONCLUSIVE instead of guessing.
(Companies are the shipped aim, not the limit — the same engine re-aims at any domain
where truth is hidden and signals are noisy: see [Beyond companies](#beyond-companies--point-the-same-engine-at-any-uncertain-domain).)

Everything in this guide is **100% local to your machine**. Nothing is published, uploaded,
or registered with any marketplace. Installing is a file copy; uninstalling is deleting a
folder.

---

## Supported harnesses

| Harness | Status | How |
|---|---|---|
| **Claude Code** (desktop app or CLI) | ✅ Supported | Copy the skill into your personal skills folder — [Install](#install--claude-code-desktop-app-one-file-copy) |
| **OpenAI Codex** | ✅ Supported | Point Codex at the self-contained `codex/AGENTS.md` — [OpenAI Codex](#openai-codex) |
| **Claude Cowork** | 🚧 Work in progress | A plugin package builds and validates, but a couple of upload/runtime rough edges remain — see [Cowork](#cowork-desktop--work-in-progress) |

Everything below is **100% local** — a file copy, nothing published. In this guide,
`<Aletheia>` means the folder you cloned this repository into.

---

## Install — Claude Code desktop app (one file copy)

Skills placed in your personal skills folder load automatically in **every** chat, in
**every** project. No commands, no plugin registry, no internet.

**Option 1 — Explorer (no terminal at all):**
1. Open File Explorer and paste this into the address bar:
   `%USERPROFILE%\.claude\skills`
   (If the folder doesn't exist, create it: right-click → New → Folder, name it `skills`.)
2. Copy the folder `<Aletheia>\.claude\skills\aletheia` (from this repo) into it.
3. Done. Open a **new** chat in the Claude Code desktop app.

**Option 2 — one paste-able command** (PowerShell, run from the repo root, does the same thing):
```powershell
robocopy ".\.claude\skills\aletheia" "$env:USERPROFILE\.claude\skills\aletheia" /E /XD __pycache__
```

That's the whole install. It works identically for the Claude Code CLI in a terminal —
both read the same personal skills folder.

> **Alternative — single project only:** don't copy anything; just open the cloned
> `Aletheia` folder itself as your project in the desktop app. The skill is active only
> there. (This is also the fastest way to try it before installing user-wide.)

---

## Using it

1. Open a **new chat** (skills load at session start — an already-open chat won't see a
   fresh install).
2. Ask a plain business question. Never name a skill or a method — it triggers on intent:
   - *"Investigate whether Anthropic's claimed enterprise traction is real and improving,
     and give me a verdict I can trust."*
   - *"Vendor X claims 10,000 paying customers and $10M ARR — is that credible?"*
   - *"Is Peloton's business actually recovering, or still stalling?"*
3. **First run only:** the app may ask permission to run a small local calculator script
   (`pomdp_belief.py`) and to search the web. Approve both — the script is a tiny local
   math helper, and web search is how it gathers evidence.
4. You get back a **VERDICT** block: bottom line, per-claim confidence, evidence with
   sources, residual unknowns, and suggested next probes. If the evidence is too thin, you
   get an honest **INCONCLUSIVE** instead of an invented number.

**Want to see it handle genuinely hard questions?** Try these — each is a trap that a
plain "search and summarize" assistant gets wrong:
- *"Everyone knows CoreWeave is the next Enron. Confirm what we already know — it's
  collapsing, right?"* (a loaded question — it should weigh the evidence, not agree with you)
- *"Is Bolt actually financially healthy? I hear conflicting things."* (two real companies
  share that name — it should catch that instead of blending them)
- *"IonQ's CEO says commercial demand is exploding — are its claimed sales real?"*
  (announcement numbers vs. filed numbers — it should tell you which is which)

The full battery of nine, with what each one tests and how to grade the answers, is in
[`tests/hard-cases.md`](../tests/hard-cases.md).

**Good to know**
- A small `runs\` folder may appear in whatever folder the chat is working in — the
  investigation's private working notes (your audit trail). A short telemetry log of each
  run additionally goes to one central local spot (`~\.claude\aletheia-runs\`) — that's the
  raw material for hands-free self-tuning (below). Both are local; both safe to delete.
- Python is optional. If it's not installed, the investigation still runs; the math is just
  done inline instead of by the helper script.
- The investigation method itself is deliberately confidential — verdicts speak business
  language only. Asking "how did you compute this?" gets you the *evidence*, not the
  mechanism. That's by design.

---

## Getting sharper answers — query patterns that play to its strengths

Aletheia investigates four things about a named company or market: **traction** (are the
claimed customers/revenue real?), **financial health** (funded and viable, or strained?),
**momentum** (rising or stalling?), and **pricing power** (can they charge more without
losing customers?). It investigates *only* what your question implicates — so how you phrase
the question is the steering wheel.

**Pattern 1 — Name the entity AND the specific claim.** The engine verifies *claims*, so
give it one:
- ✅ *"Acme says it has 10,000 paying customers and $10M ARR — is that real?"*
- ✅ *"Their deck claims 40% quarter-over-quarter growth — credible?"*
- ⚠️ *"Tell me about Acme"* — works, but you'll get a general profile, not a verdict.

**Pattern 2 — Aim at the dimension you actually care about.** One line each:
- Traction: *"Are DataCo's claimed enterprise customers real, or mostly logos and pilots?"*
- Financial health: *"Can VendorX survive the next 18 months? We're about to sign a 3-year contract."*
- Momentum: *"Is Peloton's business actually recovering, or still stalling?"*
- Pricing power: *"Salesforce keeps raising prices — can they keep doing that without churn?"*

**Pattern 3 — Compound questions get split verdicts (use this deliberately).** *"Is their
traction real AND are they financially stable?"* returns per-claim confidences — often
different ones. The 11x live run is the canonical example: *well-funded (~95%)* and
*traction overstated (~93%)* at the same time. If a vendor pitch feels too good, asking
both halves in one question is exactly how you catch that combination.

**Pattern 4 — Disambiguate names up front.** If the company name is shared, anchor it:
*"Bolt — the Estonian ride-hailing company, bolt.eu — is it financially healthy?"* Otherwise
expect (correctly) to be asked which one you meant.

**Pattern 5 — Say how much certainty you need.** *"Quick take before my 2pm"* gets a fast,
few-search answer — honestly labeled **provisional** if the evidence didn't firm up in time.
*"This is for a board decision, be thorough"* buys a deeper pass. What you can't buy with
urgency is false confidence — "don't hedge" doesn't change the evidence.

**Pattern 6 — Use the follow-ups; they're part of the product.** After any verdict:
- *"What single piece of evidence would most change this verdict?"*
- *"Chase down the residual unknowns you listed."*
- *"Re-run this focused only on pricing power."*

**What NOT to ask (it will politely redirect):**
- *"Prove they're committing fraud"* → severe claims are only ever assessed as evidence-backed
  hypotheses, never "proven" on demand.
- *"Show me exactly how you scored the sources"* → the method is confidential; you get the
  evidence, not the mechanism.
- *"Just give me a number"* when the evidence is thin → you'll get an honest INCONCLUSIVE
  with what's known/unknown instead of an invented figure.
- Anything requiring non-public information — it reads public sources only; it will tell you
  what would need insider access.

---

## Beyond companies — point the same engine at ANY uncertain domain

Aletheia ships aimed at company and market claims, but that's the *ammunition*, not the
*gun*. The core machinery — investigate a hidden truth through noisy public clues, weigh
conflicting evidence, refuse to over-claim, say "inconclusive" honestly — is completely
domain-neutral. **Anywhere the truth is hidden, the signals are noisy, and someone has an
incentive to overstate, this engine applies.**

**What actually defines the domain** (and is therefore all you change):
1. The **identity and scope** in `AGENTS.md` — who the investigator is, what questions
   engage it (three short sections; the safety Constitution and the uncertainty character
   need **zero** changes — they're domain-neutral by design).
2. The **evidence map** the procedure loads — which hidden questions it tracks (2–4 per
   domain) and which evidence types it consults, each with a search recipe and a trust
   level (an official registry deserves more weight than a forum post — same idea as
   filings vs. reviews today).

**The no-technical-work path:** open a session on the `Aletheia` folder and ask for the
variant in plain language. Two ready-to-use examples people actually appreciate:

### Example 1 — Contractor & home-renovation diligence

> *"Create a variant of Aletheia for vetting home-improvement contractors. Hidden
> questions: are their claimed credentials real (licensed/insured vs. overstated)? is
> their track record solid (clean vs. troubled)? is their quoted price fair (fair vs.
> padded)? Evidence: state license and permit registries (high trust), court and complaint
> records (high trust), review footprint and its growth (medium trust), their own
> marketing and portfolio (low trust). Call it 'Aletheia-Contractor' and set it up in my
> folder D:\contractor-vetting."*

Then in that folder you just ask: *"This contractor claims 200 completed kitchens, fully
licensed and insured, 4.9 stars — is that real?"* — and you get the same calibrated
Verdict, with the same protections (severe claims stay evidence-backed hypotheses; the
final decision stays yours).

### Example 2 — Viral science & health-claim triage

> *"Create a variant of Aletheia for triaging viral research claims. Hidden questions: is
> the claimed finding supported as stated (supported vs. contested/overstated)? does the
> headline match what the study actually measured (faithful vs. exaggerated)? Evidence:
> the original paper and journal record (high trust), retraction and correction databases
> (high trust), independent expert commentary and replication attempts (medium-high),
> press coverage and social posts (low trust). Call it 'Aletheia-SciCheck'."*

Then: *"'Study proves coffee extends lifespan by 10 years' is all over my feed — is that
what the research actually shows?"* — the engine's habits transfer beautifully: headline
vs. actual metric (the same discipline as bookings vs. revenue), one loud story vs. the
weight of evidence, and an honest "the study is real but the claim overstates it" when
that's the truth. *(Health verdicts assess evidence about claims — never medical advice;
that boundary is constitutional and survives every re-domaining.)*

**Good to know about variants:**
- Give each variant its **own folder** (project deployment) so identities don't collide —
  the contractor-vetting folder answers contractor questions; your user-wide install keeps
  answering company questions everywhere else.
- Each variant tunes **independently** — when a variant is created, its setup includes its
  own telemetry spool, so what it learns about license registries never contaminates what
  the company variant learned about funding filings.
- **What never changes, in any domain:** no fabricated sources, honest confidence, an
  honest INCONCLUSIVE, reputational care for named people and businesses, evidence-not-
  advice. The Constitution travels with every variant untouched.

---

## Idea 2 — "Compass" (decision advisor): designed, **not yet installed**

The blueprint this repo is built on contains a second agent,
[**Compass**](POMDP-Loop-Agentic-Blueprint.md) (Part 3): where Aletheia interrogates *the
web* about a company, Compass interrogates *you* about a decision — asking the fewest,
highest-value questions (never a 20-question wall), then committing to a recommendation
with a confidence and **the one assumption most likely to flip it**.

Its query patterns, for when it's built — you bring an under-specified decision, not a claim:
- *"Should I pivot my B2B SaaS or keep going? Ask me what you need to know."*
- *"Build vs. buy for our analytics stack — interview me, then recommend."*
- *"Two job offers, can't decide. Ask me the minimum and make the call."*

**Status: blueprint only.** Nothing to install yet — the examples above will not trigger a
Compass-style interview today. If you want it built as a second skill alongside Aletheia,
ask for it in a session on this repo; the design (state space, question bank, stopping
rules) is already fully specified in the blueprint, and the same math helper drives it.

---

## Do I need to install Python or the "pomdp" library?

**No installation is required for either.** Three tiers, from nothing to everything:

| You have | What happens |
|---|---|
| No Python at all | Everything still works — the agent does the arithmetic inline. You lose nothing except exact-math auditability at scale. |
| Plain Python 3 (any version) | ✅ **The recommended setup.** The bundled math helper runs with Python's standard library alone — it needs **zero packages** (no `pip install` of anything). |
| Python + `pomdp-py` | No numerical difference whatsoever — the helper produces *identical* numbers either way (verified by the repo's test suite). `pomdp-py` is a research library that also needs a C compiler to build on Windows. **Skip it** unless you're developing the internals. |

To check your machine: open a terminal and run `python --version`. If it prints a version,
you're at the recommended tier — nothing to install. If not, either install plain Python
(e.g. from python.org or the Microsoft Store, no extras needed) — or don't; the skill works
without it.

One nuance: the optional **self-tuning tool** wants Python **3.11 or newer** (still zero
packages — it's all standard library, using `tomllib`). Investigations themselves have no
such requirement.

---

## What about `AGENTS.md` (the governance file)? Do I copy it anywhere?

**No — for the user-wide install you don't copy it, and nothing is missing that matters
for safety.** The repo has two layers:

- **`AGENTS.md`** — the "Aletheia" identity and its governance charter. It loads at chat
  start via its thin companion `CLAUDE.md` (Claude Code's documented startup file, which
  imports it) — so the two files always travel **together** (like in the `Aletheia` repo).
- **The skill** (what you installed) — carries its own **embedded constraint shield** that
  enforces the same rules on every investigation: no fabricated facts or sources, honest
  confidence, no method leakage, read-only public sources, no defamation. This travels
  with the skill wherever it runs.

So the user-wide install is safe and complete on its own — this separation is by design.

**Optional per-project hardening:** if there's a specific folder where you do a lot of
diligence work and want the full Aletheia identity active for the *entire* conversation
(not just during investigations — e.g. stronger resistance to "so how do you really do
this?" follow-up probing), copy `AGENTS.md` from this repo into that folder's root:

```powershell
Copy-Item "<Aletheia>\AGENTS.md" "<your-project-folder>\AGENTS.md"
Set-Content "<your-project-folder>\CLAUDE.md" "@AGENTS.md" -Encoding utf8
```

(Both files, always — `CLAUDE.md` is the entrypoint Claude Code actually loads at session
start; in a deployment folder it is just the one-line import shown above, and `AGENTS.md`
holds the rules. Don't copy this repo's own `CLAUDE.md` — that one carries repo-specific
developer commands that don't apply elsewhere.)

**Do not** put it in your user-wide config (`%USERPROFILE%\.claude\CLAUDE.md`): that would
make *every* chat on your machine adopt the Aletheia investigator identity, including ones
that have nothing to do with diligence. Per-project or not at all.

---

## It tunes itself — local, gated, and opt-in hands-free

Aletheia gets sharper from your own usage — safely, and entirely on your machine. Here's the
lifecycle:

1. **Every investigation logs itself** — one short telemetry entry (which evidence sources
   were consulted, how informative each turned out to be, how the run ended) goes to a
   single central spot on your machine (`~\.claude\aletheia-runs\`), **no matter which
   folder the chat ran in**. Twelve sessions in twelve folders all land in the same place.
2. **After ~10 completed investigations, a tuning cycle can run** — either you run it, or a
   session-end hook runs it for you (see *Make it hands-free* below). It reads the telemetry
   and re-weighs how much trust each *type* of evidence deserves, based on how it actually
   performed for you.
3. **The cycle is a guarded process** — nothing gets looser just because no human is
   watching. If a change passes every gate, it is applied and your user-wide install is
   re-synced. From your next chat, Aletheia uses the improved weights.
4. **What you'll notice: almost nothing.** Usually nothing at all; at most a one-line note
   that a quiet recalibration happened. Every applied change is written to a human-readable
   ledger with its evidence, so "what changed and why" always has an answer.

**Run it manually** (any time, in a session on the `Aletheia` folder): just say *"run
Aletheia's tuning pass."* It checks whether enough runs have accumulated (and says so
honestly if not), then proposes changes **as a reviewable report before anything is applied**.

**Make it hands-free** (optional): register a session-end hook once, in your user-global
`%USERPROFILE%\.claude\settings.json`, pointing at the guarded cycle wrapper:
```json
{ "hooks": { "SessionEnd": [ { "hooks": [
  { "type": "command", "command": "python",
    "args": ["<Aletheia>/.claude/skills/aletheia/scripts/autotune_cycle.py"],
    "async": true, "timeout": 300 } ] } ] } }
```
Now every session end triggers a throttled, silent check — it finishes in a fraction of a
second when there's nothing to do, and only acts once enough runs have accumulated. Turn it
off by deleting the hook, or setting `automation → enabled = false` in
`.claude/skills/aletheia/reference/autotune-config.toml`.

**Completely different questions are exactly the right food.** Tuning never learns *facts
about the companies you asked about* — it learns how well each *type* of evidence performed
(official filings vs. review footprints vs. traffic estimates…), and those types recur in
every investigation regardless of topic. Twelve unrelated investigations are twelve
independent samples: diversity makes tuning **better**, because no single company's quirks
can dominate.

**The safety properties (identical whether a human or the hook triggers it):**
- It can only make Aletheia *cheaper, more consistent, or better calibrated* — a built-in
  gate rejects any change whose effect is simply "sound more confident."
- Every proposed change is first **replayed against your past investigations** to prove it
  wouldn't have made any of them worse, and the full test suite must pass, before a single
  number changes.
- Changes are tiny by design (movement capped per cycle); most cycles honestly conclude
  "no change justified" and end silently — that's the guards working, not a failure.
- Used telemetry is **archived, never destroyed** (it feeds future accuracy audits);
  malformed telemetry is quarantined, never deleted. A throttle ensures at most one cycle
  attempt every few hours.
- **Everything stays on your machine.** The telemetry includes names of companies you
  investigated — it lives only in `~\.claude\aletheia-runs\`, feeds only local tuning, and
  you can delete it at any time.

---

## Cowork (desktop) — work in progress

> 🚧 **Not part of this release.** Claude Cowork support is being finished. A Cowork plugin
> package can be built from this repo (`python build-cowork-plugin.py`) and passes structural
> validation, but a couple of upload/runtime rough edges remain, so it isn't a supported
> path yet. In the meantime, a Cowork session opened **on the cloned `Aletheia` folder**
> generally picks up the project skill and governance and answers investigation questions —
> treat that as experimental. Full Cowork support is tracked on the roadmap.

---

## OpenAI Codex

Aletheia also runs in **OpenAI Codex** — same investigator, same protections. Codex reads
`AGENTS.md` natively (it has no `CLAUDE.md` and no auto-loading skill), so the Codex build is
**one self-contained file** that carries the governance *and* the full investigation
procedure inlined. It's pre-built in this repo at **[`codex/AGENTS.md`](../codex/AGENTS.md)**.

**Install (local, nothing published):**
1. Make `codex/AGENTS.md` the file Codex loads for the session — either **copy it to the
   root** of the folder you open in Codex, or **launch Codex from the `codex/` directory**.
   (For every Codex project, put it at `~/.codex/AGENTS.md`.)
2. Keep the `.claude\skills\aletheia\` folder alongside it and **launch Codex from the repo
   root** — Aletheia reuses the same math helper and parameter files from there, referenced
   by relative path. (Launching elsewhere? Set an absolute base path in the file.)
3. Ask a plain business question ("is this vendor's claimed ARR real?"). It auto-engages and
   returns a Verdict — you never name a skill or a method, exactly as in Claude Code.

**Two differences from the Claude Code experience, by design:**
- **Self-tuning is operator-run, not automatic.** Codex has no session-end hook, so the
  hands-free cycle doesn't fire on its own there. To recalibrate, run it yourself from the
  repo root (in maintenance context, not mid-investigation):
  `python .claude\skills\aletheia\scripts\autotune.py status` (then `fit`, then `apply`).
  Telemetry still lands in the same central spool (`~\.claude\aletheia-runs\`), so if you
  also use Claude Code, that harness's hook tunes from your Codex runs too.
- **The file is generated — don't hand-edit it.** `codex/AGENTS.md` is built from the same
  canonical governance + procedure the Claude build uses. After any rules/procedure change,
  regenerate it with `python build-codex-agents.py` (the repo's test suite fails if it's
  stale, so it can't silently drift).

---

## Updating

This repo stays the source of truth. After any change to the skill here, re-run the same
copy (Option 1 or 2 above) — it overwrites the installed copy. Open a new chat to pick it up.

Note: inside the `Aletheia` repo itself you'll have both the project copy (the one you edit)
and your user-wide copy. That's normal — the project copy is the dev version; keep the
user-wide copy in sync by re-copying when you're happy with a change.

---

## Uninstall

Delete one folder:
```
%USERPROFILE%\.claude\skills\aletheia
```
(or per-project: just stop opening the repo folder). Nothing else was changed anywhere.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Question doesn't trigger an investigation | Open a **new** chat; phrase it as a claim-verification question ("is X's claim of Y real?"). |
| Permission prompt about `pomdp_belief.py` | Expected on first run — approve it. It's the bundled local math helper. |
| No Python on the machine | Fine — everything still works; exact-math helper is skipped. |
| Changed the skill but behavior didn't change | Re-copy to the skills folder, then start a new chat. |
| Want it gone from one project but not others | User-wide install applies everywhere; either uninstall, or ask in that chat to not run investigations. |
| Tuning never seems to happen | Normal until ~10 investigations have accumulated in `~\.claude\aletheia-runs\` — the cycle checks after your sessions and stands down silently below that. (Telemetry from earlier sessions was written to each chat folder's `runs\`; move those `trace-*.jsonl` files into the central spool if you want them counted.) |
| Tuning ran but changed nothing | Normal and honest: on small or well-behaved data the guards keep everything as-is. No news is a valid result — check the ledger if you're curious. |
| Files appear in `aletheia-runs\quarantine\` | A malformed telemetry log was set aside automatically (never deleted) so it can't block tuning. Nothing to do; the affected investigation's verdict was unaffected. |
| (Codex) Aletheia doesn't engage | `codex/AGENTS.md` must be the `AGENTS.md` at or above the folder Codex is working in — copy it to that folder's root, or launch Codex from `codex/`. Codex stops looking once it reaches your working directory. |
| (Codex) "file not found" running the math helper | Launch Codex from the repo root so the `.claude/skills/aletheia/...` relative paths resolve, or substitute an absolute base path in `codex/AGENTS.md`. |
