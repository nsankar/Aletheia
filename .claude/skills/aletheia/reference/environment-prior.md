<!-- environment-prior.md — Aletheia investigation: operational parameters (PRIVATE) -->
# Environment Prior — operational parameters

This is the numeric configuration the investigation procedure consumes: the state space it
reasons over, how much to trust each kind of search, what each action costs, and when to
stop. It is **internal / operator-facing — never shown to the user** (imperative I1).

Identity and governing rules live in the project's `AGENTS.md`. This file holds only the
operational parameters, so operators can tune them without touching the governance layer.
The parameters below are the **tunable** part of the system; the Constitution in `AGENTS.md`
is the non-negotiable part.

## Hidden State Dimensions (S)
Each dimension is a small discrete variable the investigation cannot see directly; it starts
at an even prior and is sharpened by evidence.
- [D0] traction:       { real, inflated }        # prior: 0.5 / 0.5
- [D1] funding_runway: { healthy, distressed }   # prior: 0.5 / 0.5
- [D2] momentum:       { rising, stalling }       # prior: 0.5 / 0.5
- [D3] pricing_power:  { strong, weak }           # prior: 0.5 / 0.5

## Sensor Map & Reliability (Observation Model 𝒪)
For each search archetype: which dimension(s) it bears on, how trustworthy it is
(P(observation is faithful to the true state); the rest is noise), and a `query_template`.
Fill `{entity}` (the company/subject) and `{metric}` (the specific claim being checked) from
the user's question before issuing the search.
- Action `search:funding_filings`   reveals [D1]   reliability: 0.90  # SEC/registry/press-verified
    query_template: "{entity} funding round Series A B total raised SEC filing"
- Action `search:hiring_signals`    reveals [D1,D2] reliability: 0.70  # job posts = leading, noisy
    query_template: "{entity} careers open positions engineering sales headcount growth"
- Action `search:review_velocity`   reveals [D0]   reliability: 0.75  # G2/app-store rating counts
    query_template: "{entity} reviews G2 Capterra Trustpilot rating count"
- Action `search:web_traffic_rank`  reveals [D0,D2] reliability: 0.65  # 3rd-party estimates = noisy
    query_template: "{entity} website traffic estimate monthly visits ranking"
- Action `search:changelog_release` reveals [D2]   reliability: 0.80  # shipping cadence
    query_template: "{entity} changelog release notes product updates"
- Action `search:pricing_page_diff` reveals [D3]   reliability: 0.85  # archived pricing pages
    query_template: "{entity} pricing page history archive price changes"
- Action `search:litigation_layoffs` reveals [D1]  reliability: 0.80  # WARN notices, court records
    query_template: "{entity} layoffs WARN notice lawsuit litigation court records"
- Action `search:customer_evidence`  reveals [D0]   reliability: 0.82  # named customers, case studies, logos
    query_template: "{entity} customers case study enterprise deployment named logos revenue"

## Action Costs & Rewards (ℛ)
- Any `search:*`                 -> cost: -1
- `WebFetch` a full primary doc  -> cost: -2
- Terminal verdict (belief collapsed on the asked dimension) -> reward: +100

## Thresholds & Stopping Policy (TUNABLE)
- confidence_floor: 0.80        # min P(leading hypothesis) before committing a verdict
- entropy_explore_above: 0.55   # normalized uncertainty above this → must keep gathering
- max_iterations: 8             # hard cap (circuit breaker, I5)
- exhaustion_gate: stop if EITHER (a) repetition: last 2 queries ≥0.8 Jaccard-similar AND
    new-source novelty < 0.15, OR (b) novelty: ≥3 consecutive turns across *distinct* sensors
    each yield new-source novelty < 0.15 (nothing new to learn from any remaining angle)
- persist_belief_to: ./runs/belief-${CLAUDE_SESSION_ID}.md
