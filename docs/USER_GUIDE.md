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

Transfer Helper shows veterans in descending in-game score order, with the score, Uma, verdict and reason. Switch between **List** and **Grid**; the grid echoes the game roster with portraits, rank, score and a clear keep/review/transfer badge. Choose the grid column count beside the view buttons; it defaults to five and is saved. Use **Transfer** to review recommended copies in the same order as the game, or **Keep** for retained, protected and uncertain copies. Search by name or score. Click a reason or press **Enter** to open the explanation panel; it follows the selected row. Select a role to compare its worst Ace and CM case on the score band. Aligned sparks show the factors relevant to that role, with parent-branch carriers marked as self, GP A and GP B. Blue stat rows show the whole lineage total, including stats that have no weight for the selected role. The lineage tree remains available even when the report has no scored role. Press **Escape** to close the panel.

The page menu contains analysis scope, report history and the output folder. Changing scope marks the report stale. Loop protection supports both free-form White Spark selection and four optional presets. Free-form skills retain their best local carriers independently. Presets add the shared Racing Spirit: Stamina skill and the selected running-style package; each keeps the two strongest complete lineage branches, then protects the best lineage presence for any package skill not covered by those branches or the performance portfolio. The report summarizes how many copies loop protection retained and how many were kept only for loops. Preset skill lists are editable in `transfer_helper.loop_protection.preset_skills` in the scoring profile. A missing direct Support card is shown as a badge but does not prevent selection. Reports older than format 13 do not contain current package and floor reasons; rerun the analysis to populate them.
The analysis never transfers veterans in game. Protected copies remain visible
and are not eligible. Check current racing use and the effort to refarm before
acting on any recommendation. Upcoming CMs use Global MDB dates; unknown dates
remain explicit and permanent roles stay in scope.

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
