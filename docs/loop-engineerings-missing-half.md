# Loop Engineering's Missing Half

*What agent loops look like when there is no compiler for the answer.*

---

In June 2026, the way we talk about working with AI agents reorganized itself around a
single idea. [Peter Steinberger argued](https://tosea.ai/blog/loop-engineering-ai-agents-complete-guide-2026)
that the real skill had shifted from prompting agents to designing the loops that prompt
them, and Addy Osmani gave the practice its name in an essay titled
[*Loop Engineering*](https://www.oreilly.com/radar/loop-engineering/). The phrase stuck
because it captured something true: what separates a great agent from a mediocre one
usually isn't the model. It's the loop.

The consensus that formed around the term is remarkably consistent. A well-engineered
agentic loop, the [guides](https://datasciencedojo.com/blog/agentic-loops-explained-from-react-to-loop-engineering-2026-guide/)
now agree, has a verifiable goal, explicit termination logic, an iteration cap, state
persisted outside the context window, and a verification step that grades each pass —
*act → verify → repeat until done*. The best coding agents of 2026 are exactly this:
long-running, self-checking while-not-done loops with strong stopping conditions.

All of that is right. And all of it quietly assumes something enormous: **that "done" is
checkable.**

## The assumption underneath the loop

The act-verify loop works because the environment grades your homework. Code compiles or
it doesn't. Tests pass or they don't. The linter, the type checker, the build — the loop
can *ask the world whether it's finished*, and the world answers honestly and instantly.
Loop engineering, as currently practiced, is the art of arranging those oracles around a
model so it can run unsupervised.

Now ask a different kind of question:

> *Is this vendor really at the $10M ARR they claim? Is that company financially healthy,
> or just loud? Is the science headline what the study actually measured?*

There is no compiler for reality. No test suite returns green when your assessment of a
company's traction is correct. The truth exists — the company either has those customers
or it doesn't — but it is **hidden**, and everything observable about it is a noisy,
partial, sometimes adversarial clue. The verify step of the standard loop has nothing to
call.

Watch what today's agents do when handed such a question: they run a few searches,
summarize whatever came back loudest, and format it confidently. The loop shape collapses
to *search → summarize → stop*, with the stopping condition "I've written enough
paragraphs." The result sounds most certain precisely when the evidence is thinnest —
confidence theater in place of verification.

This isn't a small gap at the edge of the discipline. Diligence, claim-checking,
competitive intelligence, vetting a contractor, triaging a viral headline — an enormous
share of what people actually want investigated has no oracle. Loop engineering solved
the half of the problem where the world grades your work. The other half needs a
different loop.

## The second shape

The second shape has been sitting in the decision-theory literature for decades: the
POMDP — a decision process where the true state is *partially observable*. You never see
the truth; you see observations correlated with it. The loop it prescribes is not
act → verify → repeat. It is:

**belief → act → observe → update.**

Five things change, and each one answers a failure mode of the summarizer:

**1. The state is a belief, not a task list.** The loop maintains an explicit position on
what's likely true — and therefore always knows exactly how uncertain it still is. "How
much don't I know yet?" is a number it can consult, not a vibe.

**2. Actions are chosen by value of information.** The next search isn't "more coverage."
It's the one observation most likely to *change the loop's mind*, at the least cost.
That's what replaces the verify step: you can't check the answer, but you can always name
the most decision-relevant unknown and attack it.

**3. Observations are weighed, not collected.** A clue matters in proportion to how
unlikely it would be *if the claim were false*. A company's own marketing is the cheapest
signal to fake; a third party publicly disputing a customer logo is among the most
expensive. The loop prices each observation before letting it move the belief.

**4. The loop can move backward — on purpose.** In an act-verify loop, progress is
monotone: each iteration gets closer to done. Here, a contradicting observation *raises*
uncertainty, and that is the loop working correctly. An investigator that only becomes
more confident with every search isn't investigating; it's rationalizing.

**5. Stopping is a calibration question, not a completion question.** Our implementation
stops only when two independent gates agree — the leading hypothesis is confident enough
*and* the belief has actually settled — under a hard iteration budget as a circuit
breaker. One lucky, loud search result can clear the first gate but not the second, so
the loop keeps looking instead of committing on a single observation. And when the budget
runs out before the gates clear, the loop returns **INCONCLUSIVE** — a first-class
verdict, not an error. A loop that can honestly say "the evidence isn't there" is the
only kind whose confident answers deserve trust.

Note what *didn't* change: this is still loop engineering, orthodox to the checklist.
Explicit termination logic — two gates plus a budget. A verifiable goal — verifiable
*calibration*, since stated confidence can be scored against outcomes over many runs even
when a single hidden truth can't be checked today. State persisted outside the context
window — the belief, on disk, every turn. Guardrails around a model running
unsupervised. The discipline transfers completely. What changes is the state variable
and the stop test.

## What we learned building one

We built this loop as [**Aletheia**](https://github.com/nsankar/Aletheia), an open-source
investigator that answers "is this claim real?" questions with calibrated verdicts. A few
lessons from live runs that we didn't fully appreciate until the loop was running:

- **Existence and faithfulness are different properties of evidence.** The hardest test
  case in our battery is one where the strongest *kind* of evidence — a named-customer
  logo wall — is itself the disputed artifact. A summarizer reads the logos as proof; the
  belief loop, once denials surface in reporting, reads the same page as evidence of
  inflation. Same observation, opposite update, because reliability is conditional on
  faithfulness, not existence.
- **One judgment per question, held in parallel, without bleed.** "Well-funded" and
  "honest about traction" are separate unknowns. Strong evidence on one must not leak
  into the other — which lets the loop conclude *genuinely well-backed and overstating
  its numbers* about the same company. That's exactly the verdict investor-halo reasoning
  can never reach.
- **The two-gate stop earns its keep in both directions.** Across live acceptance runs,
  the same mechanism rescued a claim that early evidence made look shaky *and* confirmed
  a debunk that early evidence made look solid. A single-gate loop would have committed
  early — and wrongly — in both.
- **Self-tuning needs an asymmetric invariant.** The loop re-weighs how much each kind of
  evidence deserves to move it, statistically, from its own recorded runs — but under one
  hard rule: tuning may make the loop cheaper, more consistent, or better calibrated,
  **never more confident**. Any optimization pressure that can buy reward by inflating
  certainty eventually will.

## Two shapes, one discipline

None of this replaces the act-verify loop. When "done" is checkable, arrange oracles and
let the loop run — that's the right tool, and the 2026 guides describe it well. But when
the answer is a hidden truth behind noisy evidence, verification isn't available and
calibration has to carry the load. Different loop, same engineering values: know your
state, know your stop, never let the model grade its own confidence.

Loop engineering taught everyone that the leverage lives in the loop. The uncertainty
loop is what that insight looks like on the half of the problem where the world doesn't
grade your work.

---

*Aletheia is MIT-licensed, 100% local, and runs on Claude Code and OpenAI Codex today:
[github.com/nsankar/Aletheia](https://github.com/nsankar/Aletheia).*
