# Desktop workflow

For installation, see the [README](../README.md). This page covers operation;
formulas and model limits belong in [Scoring](SCORING.md), and editable profiles
in [Scoring configuration](SCORING_CONFIGURATION.md).

## Prepare and link

On **Data**, select the current `master.mdb`, the local collection export
(`data.json` or `trained_chara_data.json`) and an output directory. Select
**Link an existing export**. Alternatively, configure a separate UmaExtractor or
umadump executable and select **Extract my collection**. Exporters and game data
are not bundled; see [Third-party tools](THIRD_PARTY.md).

Linking resolves costumes, factors, stars, skills, G1 wins and frozen ancestry.
It writes `veterans_legacy_linked.json` and supporting catalogues, leaving the
input files untouched. The source fingerprints determine whether linked data is
ready or stale. Relink after either source changes; **Relink anyway** forces a rebuild.

## Search

Set the shared Ace, parent to produce, race profile, course conditions and
scoring profiles. Rotation is derived from the MDB course layout. Collapsing the
context rail preserves summaries of the effective settings.

| Result family | Use |
| --- | --- |
| Final parent pairs | Compare two local parents as a complete six-member lineage |
| Individual parents | Compare parent branches as complementary halves of a pair |
| Future grandparents | Compare local material for producing a future parent |
| Remote parents | Pair a local parent with uma.moe candidates |
| Remote GPs | Pair a local GP with remote candidates, or use a local-only second pool |

The toolbar follows the selected family. Switching families preserves their
independent results. **Ctrl+Enter** runs the current page's primary action.
Shared retrieval constraints and per-mode pairing options live in the context rail.
Configure the uma.moe API URL and optional key under **Settings**. Previously
saved remote JSON can be ranked offline through the import action.

Retrieval is capped at 2,000 candidates per search. Parent discovery combines
aptitude and broad/White cohorts before scoring; constraints and pool limits
still determine which candidates are considered. Verify a remote Friend ID's
availability in game before starting a career.

Generic GP-pair searches use E2 screening followed by exact shortlist rescoring.
Their JSON and CSV contain only the final top; exhaustive GP mode retains the
all-pairs CSV. A fixed opposing parent uses the projected final-pair model with
unknown future-parent Sparks left empty. See [GP ranking](SCORING.md#104-generic-gp-screening-and-exact-reranking)
for the exact scope and [execution settings](ARCHITECTURE.md#solver-execution)
for `ULL_G1_RANKING` and worker overrides.

## Inspect, compare and revisit

Select a row to inspect its scores, factor sources, aptitude probabilities and
G1 evidence. The lineage inspector and calendar have independent 75–200% zoom;
Ctrl+wheel changes zoom and Ctrl+0 resets it. Optional artwork can be disabled or
cleared; missing images do not affect ranking.

The Standard G1 schedule includes mandatory character objectives. Trackblazer
shows the variant without them. Inspect conflicts, missing race metadata and
streak penalties before using a projected schedule.

Compare two candidates within one family, or matching identities between the
current and previous retained run. Numeric deltas are `right - left`; both sides
keep their original diagnostics. History retains one predecessor of each supported
main output, with generation time, schema and available input hashes.

A freshly computed result is **current** for its inputs. A relevant input change
makes it **stale**. A disk result is **loaded**, without asserting equivalence to
current inputs. Rerun that family when a current result is needed.

## Transfer Helper and profiles

Transfer Helper is a prototype. It evaluates individual branches and never
transfers a veteran in game. **Protected** copies have a lock, memo or an
explicitly supplied protected ID. White Loop project files are not read on `main`.
Protected copies remain visible in comparisons and redundant-copy filters.
**Keep** copies are required by the portfolio. **Equivalent in the model** and
**Redundant in the model** explain different forms of redundancy; verify racing
use and refarming effort before acting. No prototype record is transfer-eligible.

Select a row and use **Compare…**. The **Compared lineage** tab presents two
alternative branches, not a local pair. Portraits and actual game rank/score help
find each copy. Click a card or use the member selector to inspect every factor.
Parent mode counts the copy and its two GPs. Future-GP mode counts only own
factors. The optional farming-history view does not add old ancestors to score.
Zoom and Fit controls support narrow windows. Text works with images disabled.

Use the other tabs to inspect the same Ace/course/role: worst matched-target
witnesses, weighted index points, exact Whites, factors/G1 and retained roles.
For collective redundancy, one comparison can have a negative delta: another
retained copy covers that niche. Historical reports freeze their model. Rerun old
reports to obtain the new prototype rules.

Upcoming CMs are selected dynamically from Global MDB dates, through final team
registration when the round schedule is available. Future dates are explicitly
unknown. Permanent roles remain evaluated when the CM rotation changes.
See [local prototype instructions](TRANSFER_HELPER_PROTOTYPE.md).

The Weights page edits overrides over bundled defaults. **Save profile** persists
and activates the draft. Structural weights and White priorities are separate.
For unexpected results, inspect the run's `active_parent_scoring.json` and
`active_skill_priorities.json` before editing generated weight files. See
[Configuration](SCORING_CONFIGURATION.md) for merge rules and diagnostic outputs.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Linked data is stale | Select the intended MDB/export and relink on Data |
| Remote search is empty | Read the log; inspect hard filters, URL/key and network errors |
| Result is loaded/stale | Rerun the selected family against current inputs |
| Artwork is missing | Check optional artwork settings and network access; text remains usable |
| Windows application does not start from the ZIP | Extract the complete archive with its runtime files |

Settings and API-key storage are described in [Architecture](ARCHITECTURE.md#inputs-persistence-and-resources).
The [release guide](RELEASING.md) covers source tests and Windows packaging.
