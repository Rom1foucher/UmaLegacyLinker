# Scoring contract

This document describes how UmaLegacyLinker ranks inheritance candidates. It is a contract for maintainers and for anyone interpreting the exported diagnostics; it is not a claim that the game exposes these scores.

The code and the resolved JSON profiles are authoritative:

- `uma_legacy_linker/parent_optimizer.py` implements local parent branches, final parent pairs, and individual future-grandparent scoring;
- `uma_legacy_linker/uma_moe.py` normalizes remote candidates, plans retrieval, and ranks remote parent or grandparent pairs;
- `uma_legacy_linker/g1_race_planning.py` builds G1 schedules and applies the Independent Training cutoff;
- `uma_legacy_linker/transfer_helper.py` reuses the scoring primitives to evaluate a collection;
- `resources/default_parent_scoring.json` defines structural weights, curves, and thresholds;
- `resources/default_skill_priorities.json` and its resolved override define contextual White Skill priorities.

See [Scoring configuration](SCORING_CONFIGURATION.md) for profile merging, validation, generated catalogs, and the deprecated Umalator diagnostic.

## 1. Scope and terminology

Four different concepts must remain separate:

| Concept               | Meaning                                                                                                   |
|-----------------------|-----------------------------------------------------------------------------------------------------------|
| Initial aptitude gain | Deterministic rank gain from the total matching Pink Spark stars at the start of a run                    |
| Spark proc            | One inheritance roll from an existing Pink, White, Race, or Scenario Spark during an Inspiration Event    |
| `P(A)` / `P(S)`       | Probability of accumulating enough Pink procs to reach the corresponding aptitude rank during the Ace run |
| Spark generation      | Chance that a newly trained veteran receives a new Spark; this is not an inheritance-proc probability     |

The application ranks contextual utility. A score is meaningful only for the Ace, surface, distance, style, course conditions, and resolved profiles with which it was computed. Scores from unrelated contexts are not calibrated performance predictions.

The model uses four evaluation contexts:

| Context            |                                                        Visible factors | Purpose                                             |
|--------------------|-----------------------------------------------------------------------:|-----------------------------------------------------|
| Parent branch      |                                       Parent plus its two grandparents | Rank one half of a future final pair                |
| Final parent pair  |                               Two parents plus their four grandparents | Rank the complete lineage used by the Ace           |
| Future grandparent | Candidate's own factors; its current lineage only for White generation | Rank material used to produce a future parent       |
| Transfer Helper    |         Repeated branch and future-GP evaluations across many profiles | Preserve a useful same-costume collection portfolio |

Only a complete final parent pair receives a final Distance viability verdict. A branch can be complementary, and a future GP represents only one of six eventual lineage members.

## 2. Shared score mechanics

### 2.1 Weighted totals

Component weights are normalized inside every formula:

``` text
weighted_score =
    sum(component_score[k] * max(0, weight[k]))
    / sum(max(0, weight[k]))
```

Changing all weights by the same factor has no effect. Components absent from the selected mode do not contribute, even if they are computed for diagnostics.

Piecewise curves use linear interpolation between configured points and hold their first or last value outside the defined interval.

Several components use exponential saturation:

``` text
saturating_score(raw, scale) = 100 * (1 - exp(-raw / scale))
```

### 2.2 Default structural weights

These defaults explain the relative structure of the shipped profile. Exact values belong in `resources/default_parent_scoring.json`.

| Component                | Parent branch | Final pair |        Future GP |
|--------------------------|--------------:|-----------:|-----------------:|
| Distance                 |           22% |        29% | included in Pink |
| Target surface           |            7% |         5% | included in Pink |
| Running style            |            3% |         2% | included in Pink |
| Pink (combined)          |             — |          — |              25% |
| White skills             |           47% |        35% |              13% |
| Blue stats               |            8% |        20% |              13% |
| Race Spark stat value    |            4% |         4% |                — |
| Unique                   |            9% |         5% |               2% |
| Future-branch affinity   |             — |          — |              15% |
| G1 potential             |             — |          — |              11% |
| White generation support |             — |          — |              21% |

The parent and final-pair affinity scores are diagnostic. Their component mappings do not include `affinity`; proc estimates instead use the individual affinity of each carrier.

## 3. Compatibility and individual inheritance affinity

The project uses the modern compatibility model:

- only shared G1 wins contribute race compatibility;
- every shared G1 adds `+3` per visible lineage link;
- G2, G3, and titles do not contribute;
- the parent-to-parent link is included in a complete final pair;
- base compatibility for a character repeated as its own grandparent is zero.

For Ace `A`, parents `P1` and `P2`, and `P1`'s grandparents `G11` and `G12`, the coefficient used for factors carried by `P1` is:

``` text
affinity(P1) =
    pair(A, P1)
  + pair(P1, P2)
  + triple(A, P1, G11)
  + triple(A, P1, G12)
  + 3 * G1(P1, P2)
  + 3 * G1(P1, G11)
  + 3 * G1(P1, G12)
```

For `G11`:

``` text
affinity(G11) =
    triple(A, P1, G11)
  + 3 * G1(P1, G11)
```

The other branch is symmetric. Parent factors tend to transmit better because their carrier has more compatibility links; the probability-aware Pink, White, and Scenario models do not apply an additional fixed parent-versus-grandparent multiplier.

An isolated parent branch omits the unknown parent-to-parent terms from its parent coefficient. The final-pair evaluator recomputes all six coefficients rather than adding two branch scores.

The displayed overall `◎/〇/△` compatibility is explanatory. It must not be substituted for the six carrier-specific coefficients.

## 4. Blue and Scenario Sparks

### 4.1 Guaranteed Blue factors

For each evaluated lineage member, the Blue contribution is:

``` text
blue_factor = star_quality(stars) * stat_relevance(stat, distance)
```

The shipped star qualities are `0.12`, `0.78`, and `1.00` for 1★, 2★, and 3★. Stat relevance and the final distance influence are profile data.

### 4.2 Scenario expected value

Scenario Sparks are Blue bonuses rather than extra Blue slots. For carrier `i`:

``` text
p_event(i) =
    min(probability_cap,
        scenario_base_rate(stars) * (1 + affinity(i) / 100))

expected_procs(i) = inspiration_event_count * p_event(i)

scenario_contribution(i) =
    blue_star_quality(stars)
  * sum(stat_relevance(granted_stat, distance))
  * expected_procs(i)
  * blue_equivalent_per_proc
```

The stat targets come from `succession_factor_effect` in the current `master.mdb`. Known Global-era names provide a compatibility fallback for older linked exports. Identity prefers `factor_group_id`, then `factor_id`, so similarly named variants are not collapsed.

### 4.3 Final Blue score

``` text
uncompressed_blue =
    100 * (sum(blue_factor) + sum(scenario_contribution))
    / evaluated_lineage_slots

blue_score =
    max(0,
        neutral_score
      + distance_influence * (uncompressed_blue - neutral_score))
```

The neutral score is 50 by default. Shorter-distance profiles compress differences toward that neutral value; Medium and Long retain more of the raw difference. Scenario bonuses can intentionally raise the component above 100.

Distance-B compensation uses `uncompressed_blue`, not the distance-compressed `blue_score`, because that gate asks whether the lineage's intrinsic Blue quality is exceptional.

## 5. Pink aptitude inheritance

### 5.1 Initial rank

Matching Pink stars are summed independently for surface, distance, and style:

| Matching stars | Initial gain |
|---------------:|-------------:|
|              0 |     +0 ranks |
|            1–3 |      +1 rank |
|            4–6 |     +2 ranks |
|            7–9 |     +3 ranks |
|            10+ |     +4 ranks |

The initial rank is capped at A. A natural F aptitude can therefore reach B with 10★ but cannot start at A.

### 5.2 Proc distribution

Every matching factor rolls independently at each configured Inspiration Event. With the shipped two-event model:

``` text
p_event(i) =
    min(1,
        pink_base_rate(stars_i) * (1 + affinity(i) / 100))
```

The shipped base rates are 1%, 3%, and 5% for 1★, 2★, and 3★. The engine builds the exact Poisson-binomial distribution over all factor/event rolls, then derives `P(N >= k)`, `P(A)`, `P(S)`, and the probability of reaching configured minimum and preferred ranks. One proc is modeled as exactly one rank; rare multi-rank procs are deliberately ignored.

These rates, their linear affinity multiplier, and independence are configurable model assumptions, not official measured probabilities.

### 5.3 Final-pair Distance score and viability

Let `U(P(S))` be the configured, saturating piecewise utility expressed from 0 to 1. The shipped pair formulas are:

``` text
starts at A:  distance_score = 70 + 30 * U(P(S))
starts at B:  distance_score = 20 + 45 * P(A) + 35 * U(P(S))
below B:      distance_score = 0
```

A pair that starts at A but has no chance of S receives a zero Distance score.

Distance viability is a separate lexicographic tier:

| Priority | Status                     | Condition                                      |
|---------:|----------------------------|------------------------------------------------|
|        4 | `ready_for_s`              | Starts at A and `P(S) > 0`                     |
|        3 | `distance_b_compensated`   | Starts at B and passes all compensation checks |
|        1 | `distance_b_uncompensated` | Starts at B but fails at least one check       |
|        0 | `no_s_support`             | Starts at A with no chance of S                |
|        0 | `underprepared`            | Starts below B                                 |

The shipped compensation thresholds are `P(A) >= 55%`, `P(S) >= 15%`, White score `>= 85`, and uncompressed Blue score `>= 75`. All four checks are required.

### 5.4 Surface and style

For a final pair, target surface uses a configurable initial minimum and preference: B is the shipped minimum, while A is preferred.

``` text
starts at A:  surface_score = 80 + 20 * P(S)
starts at B:  surface_score = 55 + 30 * P(A) + 15 * P(S)
below B:      10 + 45 * readiness_to_B
                   + 25 * P(B) + 15 * P(A) + 5 * P(S)
```

Starting at or above B receives the same surface sort priority. A is a weighted preference, not another gate. Progress below B remains visible so that 0★ and a lineage close to B do not receive the same component score.

Style has no lexicographic gate. Its shipped pair formula is:

``` text
starts at A:  style_score = 90 + 10 * P(S)
starts at B:  style_score = 70 + 25 * P(A) + 5 * P(S)
below B:      style_score = 10 + 30 * P(A) + 5 * P(S)
```

### 5.5 Parent-branch Pink score

A branch does not pretend that its three members form a complete lineage. For each Pink dimension it combines:

- star readiness relative to the stars needed to start at A, or relative to the best legal +4-rank target when A is unreachable;
- probability of at least one proc relative to a configured reference.

The shipped branch mix is 60% star readiness and 40% proc readiness, with 40% as the full-proc reference. Branches also receive a non-blocking Distance label: `deficit`, `light`, `balanced`, or `distance_carrier`.

## 6. White Skill inheritance

The active priority for a skill comes from the resolved contextual White profile. A priority of zero contributes nothing. Course-static Greens can be set to zero, floored, or overridden before inheritance scoring as described in section 9.

For each source:

| Source                         |  1★ |  2★ |  3★ |
|--------------------------------|----:|----:|----:|
| Direct White Skill Spark       |  3% |  6% |  9% |
| Race Spark granting that skill |  1% |  2% |  3% |

``` text
p_event(source) =
    min(probability_cap,
        base_rate(type, stars) * (1 + affinity(carrier) / 100))
```

All direct and Race-Spark sources granting the same skill are grouped:

``` text
P(skill inherited at least once) =
    1 - product((1 - p_event(source)) ^ event_count)

raw_white =
    sum(skill_priority * distinct_skill_utility(P(skill)))

white_score =
    100 * (1 - exp(-raw_white / mode_saturation))
```

The distinct-skill curve suppresses very low probabilities and saturates repeated coverage. Duplicate factors increase the probability of one skill; they do not create additional diversity entries. Consequently, several useful skills with meaningful probabilities can outrank one heavily duplicated skill.

Race Sparks need no arbitrary discount when they grant a relevant skill: their lower base rates already provide it. Their generic stat value is scored separately.

## 7. Race Sparks and Uniques

For parent branches and final pairs, the `race_scenario` component now contains only the small generic stat value of Race Sparks:

``` text
raw_race =
    sum(base_per_star_quality
        * generic_star_quality(stars)
        * position_weight)

race_score = saturating_score(raw_race, mode_scale)
```

The shipped `base_per_star_quality` is `0.025`. A Race Spark's granted skill is scored in the White component, and Scenario Sparks are scored in Blue; neither is double-counted here. The legacy component name is retained for output compatibility.

Unique scoring is intentionally simple:

``` text
unique_score =
    min(100,
        100 * sum(unique_star_quality(stars) * position_weight)
        / evaluated_lineage_slots)
```

The shipped position weights are 1.0 for a parent and 0.5 for a grandparent. There is currently no course-aware Unique relevance table. Required, allowed, and excluded parent costumes are selection constraints outside this generic component.

## 8. Final parent-pair ranking

Local-local and local-remote final pairs call the same `evaluate_parent_pair(...)` function. Missing imported lineage remains subject to the normalizer and evaluator fallbacks; it must not be described as a complete known lineage.

Pairs are ordered descending by:

1.  Distance viability priority;
2.  whether the initial target-surface rank reaches the configured minimum;
3.  normalized weighted score;
4.  White score;
5.  Blue score;
6.  probability of reaching the preferred surface rank;
7.  raw Distance `P(S)`.

The weighted score precedes raw `P(S)` because the Distance component already maps that probability through a diminishing-return curve. A small change near the practical ceiling must not override a substantially better White or Blue lineage.

Starting at Surface A does not create a higher sort tier than starting at the configured minimum B. Conversely, no amount of weighted quality can overtake a higher Distance viability tier.

Parent branches are ranked by weighted score, then total diagnostic affinity. Branch scores are useful for preselection, not additive substitutes for final-pair evaluation.

## 9. Contextual skill priorities

Before White scoring, the engine resolves a skill priority for the selected surface, distance, style, and optional course:

- the course-specific profile is used when present; otherwise the generic matrix is used;
- a statically incompatible course condition sets the priority to zero;
- a matching static condition applies the configured `floor` or `override`;
- an unresolved condition preserves the profile priority;
- dynamic race conditions that cannot be determined from the selected course remain manual profile judgments.

Static categories currently include season, rotation, track, weather, ground condition, and time. This mechanism contextualizes the priority; it does not prove that a skill will activate in every race state.

## 10. Future-grandparent scoring

### 10.1 Simple factor model

Without a fixed opposing final parent, future-GP scoring deliberately remains heuristic. It does not compute a final initial rank, inheritance proc distribution, or `P(S)`.

For a single local future-GP candidate:

- `pink` scores only its matching direct Pink factor using star quality, dimension relevance, and whether the Ace naturally starts below A;
- `white_skill` scores direct useful White factors by priority, configured star quality, and GP position; a Race Spark granting a skill uses the Race/White base-rate ratio;
- `blue` scores its own Blue and expected Scenario value;
- `unique` scores its own Unique;
- `affinity` uses the exact `triple(Ace, target parent, candidate)` contribution plus `pair(Ace, target parent)` when a target parent is known, or `pair(Ace, candidate)` as a fallback;
- `g1_potential` maps the candidate's number of distinct G1 wins through the configured threshold curve;
- `white_generation` evaluates the candidate and its two current parents.

For a generic GP1+GP2 search, direct-factor components use only GP1 and GP2. Their current parents are not part of the future Ace lineage and contribute only to `white_generation` and production-run diagnostics.

### 10.2 White-generation support

`white_generation` is a relative production heuristic:

``` text
lineage_bonus(skill) =
    bonus_per_lineage_copy
  * min(number_of_current_lineage_members_with_direct_white(skill),
        maximum_copies)

raw_generation =
    sum(skill_priority * lineage_bonus(skill))

white_generation_score =
    100 * (1 - exp(-raw_generation / generation_scale))
```

The shipped bonus is 0.025 per carrier. It excludes Race and Scenario Sparks and ignores learned basic/◎/gold forms and the base generation chance. It must not be presented as an absolute chance of generating a Spark.

### 10.3 Planned G1 potential

For GP1+GP2 intended to produce parent `P`, the future branch base is:

``` text
pair(Ace, P) + triple(Ace, P, GP1) + triple(Ace, P, GP2)
```

The current parents of GP1 and GP2 are excluded from this final-lineage base. Within the configured race budget:

- a G1 shared by GP1 and GP2 can create two links and contributes `+6`;
- a one-sided G1 can create one link and contributes `+3`;
- the race keeps that value only when the projected parent's effective Independent Training win probability reaches the cutoff.

The projected training aptitudes combine the target parent's natural surface/distance aptitudes with the initial Pink gains from GP1, GP2, and their four current ancestors. Running style is not used by this cutoff.

The Independent Training probability table is implemented as:

``` text
base_probability =
    clamp((distance_rank + surface_rank - 3) * 10%, 0%, 110%)
```

The exact schedule subtracts 10, 25, 35, and 50 percentage points at the third, fourth, fifth, and sixth-or-later consecutive race. The shipped cutoff is 60%. Flexible races may move between Classic and Senior years; fixed objectives and turn collisions are respected. Missing MDB race metadata preserves legacy eligibility and is reported.

The G1 component is normalized against the theoretical all-shared maximum:

``` text
g1_potential =
    min(100,
        100 * planned_G1_bonus
        / (planned_race_budget * 2 * G1_bonus_per_link))
```

There is currently no single code-wide default for the planned G1 budget. The desktop request and control default to 20, while the low-level `rank_online_grandparent_pairs()` parameter still defaults to 24. Callers should pass the value explicitly. This mismatch is implementation debt, not two different scoring policies.

### 10.4 Generic GP screening and exact reranking

`rank_online_grandparent_pairs()` uses E2 by default for generic GP searches,
including the local-only second-pool mode. Individual future-GP ranking in
`optimize_parents()` does not use this pair-screening pipeline.

For X requested results, clamped to 1–500:

1. Score every eligible pair using the E2 G1 estimate and the other normal components.
2. Keep at most 2X pairs. Restore their original enumeration order, recompute their
   complete score using the exact Standard schedule, and sort again.
3. Rebuild complete Standard/Trackblazer diagnostics for the final X pairs only.

E2 reserves mandatory objectives, checks the base surface/distance cutoff, valid
calendar years and turn conflicts, and respects the affinity-race budget. Optional
races are placed greedily by descending bonus, then increasing number of slots,
then deterministic name/index ties. It does not optimize consecutive-race penalties.
Unresolved imported race metadata retains the planner's explicit fallback.

Generic pairs sort descending by score, final-branch potential affinity, then
production scored affinity. Exact ties retain enumeration order. The final scores
and schedules are exact **for the selected pairs**; E2 does not guarantee recovery
of the exhaustive global top. Upstream candidate-pool limits also still apply.

`ULL_G1_RANKING=exact` evaluates all eligible pairs with the exact planner. Parent
searches and GP searches with a fixed opposing parent remain exact regardless of
this setting. Execution options are documented in [Architecture](ARCHITECTURE.md#solver-execution).

In E2 mode, JSON and CSV both contain only the final X results. `result_count` is
that exported count; `evaluated_pair_count` counts all screened pairs. JSON
`metadata.g1_ranking` records `mode=e2_then_exact`, the shortlist multiplier/count,
`csv_scope=exact_final_top` and `global_recall_guaranteed=false`. Exact mode retains
the all-pairs CSV. Consumers must not assume the CSV is exhaustive in both modes.

### 10.5 Fixed opposing parent

When a complete opposing final parent is supplied, GP1 and GP2 are evaluated by their exact marginal contribution to the projected six-member final lineage:

1.  create the future parent below GP1 and GP2;
2.  keep that future parent's unknown own Sparks empty;
3.  project only its executable G1 wins within the configured budget;
4.  pair it with the fixed opposing parent;
5.  call the canonical final-pair evaluator and use its viability tiers and weighted score.

White generation and the compatibility of the intermediate production run remain diagnostics and do not enter this contextual final score. Whites already covered by the opposing parent are softened during retrieval and preselection, not blacklisted; the exact final evaluator still combines every visible source.

## 11. Retrieval, preselection, and scoring

Candidate retrieval is not part of the numeric final score, but it determines which candidates can reach that scorer.

Parent search shares the global remote cap across complementary Distance, Surface, and broad/White cohorts. The plan targets the aptitude deficit left by any fixed local branch. When Surface is already covered, its cohort is omitted and most of that budget is reallocated to Distance. Returned records are merged and deduplicated.

Before the local/remote Cartesian product, branch pools reserve places for overall, Distance-rich, and Surface-rich candidates. Explicit hard Main or lineage filters are rechecked locally. The final ranking always uses the canonical six-member parent-pair engine.

Generic grandparent search preselects individual candidates with the future-GP component weights, then evaluates GP pairs. With a fixed opposing parent, retrieval needs and preselection account for the already visible Pink and White coverage before the exact contextual final-pair evaluation.

UQL text is an audit/copy representation. The live `/api/v3/search` request uses structured API parameters, not free-form UQL.

## 12. Transfer Helper prototype

This prototype analyzes **individual alternative branches**. It never transfers
an Uma, and never publishes a machine-actionable transfer authorization.
`transfer_eligible=false` on every prototype record; `model_transfer_candidate`
records the pre-review model result. Refarming effort and current racing/team
use remain unknown and require manual review.

### 12.1 Evaluation and dates

Exhaustive mode evaluates seven permanent surface/distance archetypes, all four
styles, and all viable Ace variants (28 permanent contexts). Additional CM
contexts use the current UTC date and the Global MDB's `champions_schedule`.
When available, `champions_round_schedule` final team registration (round 3,
detail 1) is the preparation cutoff. League selection is not the preparation
cutoff. Without round data, the inclusive event end is the fallback. Later
numbered presets have explicitly unknown Global dates; JP dates are ignored.
The report records calendar provenance and the next transition. Open reports
become stale on input changes, calendar day changes or cutoff expiry.

A Parent is evaluated with its own factors and two frozen GP snapshots.
A future GP uses **its own factors and G1 wins**. Future compatibility is unknown:
its affinity has zero weight. Historical White-generation support also has zero
weight and remains a farming-history diagnostic. This is not an exact simulation
of the future production run or a refarming-cost estimate.

The Transfer Helper has dedicated weights, isolated from other optimizers:

| Component | Parent branch | Own future GP |
| --- | ---: | ---: |
| Distance S | 29% | — |
| Surface aptitude | 5% | — |
| Other Pinks | 2% | — |
| Own Pinks heuristic | — | 35% |
| Whites | 35% | 20% |
| Race/scenario | 4% | — |
| Blue/stat factors | 20% | 25% |
| Unique | 5% | 3% |
| Own G1 potential | — | 17% |

These are prototype assumptions, configurable under
`transfer_helper.branch_weights` and `grandparent_weights`. They do not encode
any local pair combination. Long-distance stat weighting favors Stamina over
Power. Ordinary useful Whites, including Uma Stan, still contribute to score.

### 12.2 Same-costume portfolio

A bounded exact set-cover search preserves each competitive role/context for
**the same Ace**, within `portfolio_regret_tolerance` (2.5 index points by default).
It also retains at least one copy per costume/Unique signature, represented own
3★ stat Blue and 3★ Distance/Surface Pink specialists, and every lock, memo or
explicitly supplied protected ID. White Loop project files are not read on
`main`. A feasible solution survives search-budget exhaustion;
`optimal` certifies minimum cardinality only under these model requirements.

Local-partner G1 overlap is not a default requirement. The advanced opt-in
`preserve_local_g1_pair_support` restores the previous behavior. Ordinary White
coverage and generic multi-White packages cannot impose retention. Only the
explicit `build_defining_skill_keys` list (default: `straight_descent`) may create
conditional White protection, subject to contextual utility and source quality.

### 12.3 Diagnostic verdicts and comparison

**Equivalent in the model** requires an exhaustive same-target dominance witness
from a retained same-costume/same-Unique copy. **Redundant in the model** can rely
on several retained copies, each covering different contexts. Neither certifies
an affordable refarm or absence of racing use. **Keep** means required by the
portfolio, and **Review** means evidence is insufficient. **Protected** copies
participate in comparisons and have a separate leave-one-out `analysis_status`,
but their final lock remains effective.

The comparison dialog presents two disconnected alternative branches. Parent
mode shows each copy and its two GPs. GP mode shows only the candidate's own
factors; optional historical parents are explicitly excluded from score.
Portraits, game rank and evaluation score identify copies. Missing snapshot
scores remain unknown. Technical IDs are confined to report data.

Selecting a context/Ace shows matched-target index deltas, additive contributions,
exact Whites, source-specific stars, G1 differences and exclusive retained roles.
Every visible shortened inventory has a full card inspector. GP White values
are heuristics, not Ace inheritance probabilities. Frozen configuration, factors,
affinities, scenario effects and game identity allow historical reconstruction.
An incompatible historical engine disables the breakdown instead of inventing
an explanation.

## 13. Diagnostics and reproducibility

Detailed results expose:

- component scores, normalized weights, and point contributions;
- initial aptitude ranks, proc requirements, `P(A)`, `P(S)`, and complete proc distributions;
- every scored White source and its grouped skill probability;
- six-member individual affinities and visible G1 links;
- G1 schedule eligibility, streak penalties, objective conflicts, and assumptions;
- retrieval cohorts, filters, pool sizes, preselection strategy and E2 export scope;
- Transfer Helper context evidence, portfolio coverage, and Spark-protection reasons.

Runs copy the effective structural and White-priority profiles to `active_parent_scoring.json` and `active_skill_priorities.json`. When investigating a ranking, inspect those files before changing defaults.

## 14. Model boundaries

The following are deliberate limits:

- the proc-rate tables, linear affinity multiplier, independent rolls, and one-rank Pink proc are configurable assumptions;
- `white_generation` is a relative lineage-support heuristic, not an absolute generation probability;
- E2 shortlist selection has no global top-recall guarantee;
- generic future-GP scoring cannot know the eventual second branch and therefore must not expose final `P(S)`;
- static MDB conditions cannot infer the full race meta or dynamic activation value of a skill;
- Unique relevance is generic rather than course-aware;
- uma.moe results can be incomplete or stale, so retrieval quality and follow availability remain separate from score correctness;
- no score authorizes an automatic in-game action.

Changes to this model should preserve the separation between retrieval, preselection, and final scoring; recompute complete final pairs over all six visible members; keep Distance viability lexicographically ahead of additive quality; and export enough evidence to explain why a candidate was retrieved, retained, ranked, or rejected.
