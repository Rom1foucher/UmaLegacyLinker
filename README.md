# Uma Legacy Linker

Local desktop tool for analysing inheritance lineages in **Umamusume: Pretty Derby**.

Uma Legacy Linker links an exported veteran collection to the current `master.mdb`, reconstructs Sparks, skills, G1 history and ancestry, then ranks parents, parent pairs and future grandparents for a selected Ace and race profile.

> Independent community project. Not affiliated with or endorsed by Cygames.

## What it does

- Resolves local veterans and costume variants against the current game database.
- Ranks complete six-member parent lineages for a target Ace.
- Evaluates future grandparents for producing stronger parents.
- Searches public parents through [uma.moe](https://uma.moe/) and combines them with local candidates.
- Audits duplicate local veterans with the conservative **Transfer Helper**.
- Opens every parent, pair and grandparent result as a context-aware top-down lineage with costume artwork, resolved skill icons, rich Spark details and optional ancestry history in the Qt interface.
- Exports detailed JSON, compact CSV and readable diagnostics.
- Provides an English and French desktop interface.

## Main workflows

### Local linking

Loads a supported veteran export (`data.json` from UmaExtractor or
`trained_chara_data.json` from umadump) and `master.mdb`, then resolves:

- Blue, Pink, Green, White and Race Sparks;
- star levels and granted skills;
- learned skills and G1 victories;
- parents, grandparents and local training identifiers.

The linked export is the input used by the optimiser and Transfer Helper.

### Lineage optimisation

Configure the target Ace, the parent being produced, surface, distance, running style and optional course conditions.

The optimiser produces three complementary rankings:

- **final parent pairs** for the Ace;
- **individual parent branches**;
- **future grandparents** for the next breeding step.

Final pairs use the complete visible lineage: both parents and all four grandparents.

### Transfer Helper

Evaluates every local veteran as both a parent and a future grandparent against a stable baseline:
Turf Sprint/Mile/Medium/Long and Dirt Sprint/Mile/Medium, each split into Front, Pace and Backline.
The default fast mode only tests Aces with natural B or better in surface, distance and style.
The bundled profile adds up to five upcoming Champion Meetings as optional extra evidence; they
can be disabled, and a temporary calendar gap can never make a permanent archetype disappear from
the cleanup baseline. The Transfer Helper panel exposes Fast (recommended) and Exhaustive (slow)
modes, the upcoming-CM limit, Team Trials and generic profiles; selections persist between runs.
Team Trials and generic profiles are disabled by default.

The helper builds the smallest same-costume portfolio that remains within 2.5 score points of the
best copy in every globally competitive niche. It also covers direct 3-star Distance/Surface
Sparks, high-value direct White Sparks from 2 stars, repeated/hard-to-obtain skills and configured
packages collectively across the retained copies.

Verdicts are:

- **Protected** — locked in game or carrying a memo;
- **Keep** — required by the collection portfolio;
- **Strictly safe transfer** — in exhaustive mode only, one retained same-costume, same-Unique replacement is no worse in every viable profile envelope, retains G1 pair support and individually preserves protected heritage;
- **Recommended transfer** — redundant at collection level, possibly covered by several retained copies rather than one universal replacement;
- **Review** — incomplete or insufficiently modelled coverage requiring manual inspection.

The detail pane and JSON/CSV reports expose the retained coverage, portfolio reasons, lock/memo
metadata, exact strict replacement when one exists and the permanent/dynamic context split.

The tool never edits the collection and never transfers or deletes anything automatically. An
optional exhaustive audit restores all four styles and unfiltered Ace variants for occasional
cross-checking; it is intentionally much slower than the default mode and is the only mode allowed
to issue the **Strictly safe transfer** verdict. Fast-mode redundancies remain recommendations.

### uma.moe search

Two online search modes are available:

- remote grandparent paired with a local GP;
- remote final parent paired with a local parent.

Future-grandparent search can optionally receive a complete **opposing parent branch**, either
from the local veteran collection or imported from an application parent-pair/raw uma.moe JSON.
When present, every GP1+GP2 candidate is inserted under the not-yet-trained target parent and
ranked against that fixed branch with the same six-member engine as a final parent pair. The
future parent's own unknown Sparks remain empty; the selected GPs, the opposing branch and a
projected G1 plan are evaluated exactly. Leaving the field empty preserves the generic future-GP model.

The active Ace, target parent, profile, course preset, exact conditions and scoring files form one live shared context at the top of **Search**. Local and uma.moe searches sit side by side beneath it and write into the same result area. Stable integration values (API URL and key) live separately under **Settings**.

Friend IDs can be copied directly from result tables. Online retrieval is capped at **2,000 candidates per search**.
For final-parent searches, this budget is divided between a Distance cohort, a target-surface
cohort when the Ace needs it, and a broad White-preferred cohort. The cohorts are merged and
deduplicated before exact local × remote pair scoring; they guide sampling rather than acting
as final hard constraints.

The target-surface cohort can be disabled per search in the uma.moe filter dialog, or by setting
`uma_moe_parent_search.retrieval.surface_cohort_enabled` to `false` in the active scoring
profile. This only changes API sampling; target-surface scoring remains active. In manual
pair mode, the locked local parent/GP is resolved before retrieval. If the already-known
surface Sparks start the Ace at A, no automatic Turf/Dirt cohort is emitted and a persisted
remote-Main Surface constraint is suppressed as redundant.

Contextual future-GP searches use the same global cap but subtract the opposing branch's known
aptitude coverage and, in manual mode, the locked local GP's own Sparks first. The locked GP's
ancestors are not counted because they sit outside the final six-member lineage. For example,
7 known target-surface stars toward a 10-star minimum leave only a 3-star surface deficit, so
most of the released surface budget moves to Distance and broad White discovery. Whites already
carried by the fixed branch are softly down-ranked for retrieval, not excluded; the final scorer
still combines duplicate copies through cumulative probability.

The search panel only exposes filters supported by `/api/v3/search`: soft White preferences,
optional target-surface/distance/style constraints on the remote Main, and optional minimum
Blue/White quality for the full remote lineage. Per-factor Blue/Pink lineage minima use the
same aggregate IDs as the uma.moe sliders (for example, Stamina `>=5★` is sent as
`blue_sparks=205,206,207,208,209`) before the 2,000-result pagination cap, then revalidated
locally after normalisation. Explicit hard filters are copied into every retrieval cohort.
If a hard lineage filter conflicts with a soft aptitude cohort on the same API parameter, the
hard filter wins and that cohort's budget returns to the broad search.

Automatic-pair preselection still uses the canonical local scorer and keeps dedicated
Distance/Surface coverage. As a recall guard, a hard-filtered remote pool is kept in full up
to 500 candidates before exact pair scoring, even when the configured remote preselection
pool is smaller. Fixed-local searches already score every valid remote candidate without a
remote preselection cut.

The generated UQL text is kept only as an audit and manual-copy representation because the
public endpoint has no free-text UQL parameter.

Any selected final parent pair, whether fully local or local × uma.moe, can be exported in the native **Lineage Planner v1 JSON** format used by the current uma.moe frontend. In the planner, use **Save / Load** to import the generated file. Local branches retain every veteran and succession record available in the source export; normalized and remote branches retain every available Spark, lineage member and race-saddle ID.

## Scoring model

The model is configurable and intentionally differs by workflow.

**Final parents and parent pairs** use:

- modern individual inheritance affinity;
- initial aptitude ranks and estimated `P(A)` / `P(S)`;
- probability-aware White Skill Spark inheritance;
- distance-aware Blue Spark priorities;
- G1 overlap and course-specific Green Skills.

**Future grandparents** use a simpler pre-production model based on:

- direct Pink, Blue and White Spark quality;
- Ace × parent × GP affinity;
- G1 overlap;
- current-lineage support for generating useful White Sparks.

This avoids pretending that the full final lineage is already known during a generic future-GP
search. When the opposing branch is explicitly supplied, the application instead uses the exact
final-pair model for every candidate GP pair.

See [`docs/SCORING.md`](docs/SCORING.md) for formulas and implementation details.

## Requirements

- Windows is the primary supported platform.
- The Windows release executable requires no Python installation.
- Running from source requires Python **3.10+**.
- PySide6 for the desktop interface.
- A current Umamusume `master.mdb`.
- A veteran export from UmaExtractor (`data.json`) or umadump
  (`trained_chara_data.json`).
- `PyYAML` for live uma.moe searches when running from source.

Install the source dependencies with:

```powershell
py -m pip install -r requirements-qt.txt
```

## Veteran data extraction

Uma Legacy Linker does not bundle a game-memory reader.

Two backends are supported by the built-in **Extract and link** launcher, which picks the right one from the tool's name:

- [umadump](https://github.com/Werseter/umadump) reads the running game's memory and validates its wrapper layouts against `global-metadata.dat`, so it survives game updates better than cache interception. It is run with `--rerun-mode once` from the output folder, and its `trained_chara_data.json` is linked directly. Note that it leaves `succession_trained_chara_id_1/2` at zero, so the informational "referenced by" column of the Transfer Helper stays empty; scoring and rankings are unaffected because every lineage member's Sparks come from the frozen `succession_chara_array` snapshot.
- [UmaExtractor](https://github.com/xancia/UmaExtractor) intercepts a cached API response and writes a single `data.json`. It still provides the local lineage links above.

Both are separate projects with their own requirements (umadump needs Python 3.14+ when run from source), licences and warnings.

Tools that read a running game process are used at your own discretion.

## Quick start

```powershell
git clone https://github.com/Rom1foucher/UmaLegacyLinker.git
cd UmaLegacyLinker
py -m pip install -r requirements-qt.txt
py qt_app.py
```

On Windows, `run.bat` starts the same application.

Then select:

1. the current `master.mdb`;
2. the exported `data.json` or `trained_chara_data.json`;
3. an output directory.

Run **Link collection** before using lineage search, Transfer Helper or
local × online pair calculation.

### Desktop interface

The PySide6 interface covers the full workflow: dashboard, extraction and linking, one unified local/uma.moe Search workspace (including fixed opposing-parent context and offline local GP-pair ranking), Transfer Helper, scoring-profile editing, Settings and diagnostics, sortable embedded results, a visual lineage inspector and Lineage Planner export. The three local buttons calculate final pairs, parent branches or future grandparents independently. Long-running tasks can be cancelled from the status bar.

Preferences live in `%APPDATA%\UmaLegacyLinker\config.json` and the interface renders in French and English. The Windows workflow also renders every page at three viewport sizes in both languages and rejects detected text overflow. See [`docs/QT_UI.md`](docs/QT_UI.md) for the UI architecture and build instructions.

The Qt lineage inspector loads costume-aware trainee artwork, resolved White Skill icons and G1 race banners on demand from GameTora. Images are never bundled with the source or executable: they are kept in a bounded per-user cache, remain available offline once cached, and can be disabled or cleared directly in the inspector. Missing or unavailable artwork falls back to a generated card.

Parent and grandparent pair diagnostics distinguish shared G1 wins from races won on only one side, including whether that one-sided source is local or remote. A dedicated three-year planning tab builds an executable one-race-per-turn schedule: winning a shared race with the new trainee creates two `+3` links (`+6`), while a one-sided race creates one `+3` link. For future-grandparent searches, each race keeps that full value only when the future parent's Independent Training win chance reaches the configurable cutoff after consecutive-race penalties; otherwise it contributes zero. The standard plan locks the target character's fixed race objectives resolved from `master.mdb`; **Schedule for Trackblazer** ignores those objectives and shows the affinity-only optimum. Objective/calendar conflicts remain visible below the schedule, and unavoidable streaks of four or more races stay present with a risk warning. The JSON diagnostics retain both variants, the objective races, ownership, MDB IDs, dates, distance/surface, win chances and every available calendar slot.

White Sparks show the inheritance probability already calculated by the scoring engine across the run's configured Inspiration Events, and the three strongest White contributions receive a gold outline. Result diagnostics also show game-inspired aptitude rows, score/P(S) cards and a compact direct-Spark recap. The view does not introduce a second probability formula.

## Weights

The **Weights** tab uses a two-pane settings editor: search, gameplay categories and 51 ordered subcategories on the left, then a complete explanation and the appropriate control on the right. Every visible setting has bilingual purpose, impact and scope guidance, plus a quick hover summary. Probabilities and bounded thresholds use percentages, independent coefficients use an explicit `×1` reference, and the nine scoring groups normalised by the engine use a live 100% distribution preview with a donut chart. Adjusting a coefficient changes only that stored value; the displayed effective shares are recalculated without rewriting its siblings. Booleans, integers and curves receive controls suited to their type. Draft/default states are explicit and internal JSON paths remain out of the interface.

Values are stored as minimal overrides on top of the bundled defaults, so new settings can be introduced without replacing the user's whole profile.

Practical examples:

- increase the Long Stamina preference to favour Stamina lineages in Long races;
- reduce Blue Spark influence for Sprint to make weak Blue Sparks less punitive there;
- change the Distance-S utility curve to adjust the value of 40%, 50% or 60% `P(S)`;
- raise Distance-B compensation thresholds to accept B-start pairs only with exceptional support;
- tune the target-surface component or its minimum/preferred ranks (B/A by default) for low-natural-aptitude Aces.

The effective profiles used by a run are exported as:

- `active_parent_scoring.json`;
- `active_skill_priorities.json`.

The White Skill priority selector used by **Search** and shown in the advanced
section of **Weights** is one live shared setting. Its input
may be a complete profile or a minimal recursive override of
`default_skill_priorities.json`; see
[`docs/SKILL_PRIORITIES.md`](docs/SKILL_PRIORITIES.md) for the exact schema,
merge rules and examples. These per-skill priorities remain distinct from the
structural scoring settings stored in `parent_scoring_overrides.json`.

## Main files

| File | Purpose |
| --- | --- |
| `qt_app.py` | PySide6 desktop entry point |
| `cli.py` | Headless CLI: linking, catalogues, ranking and Transfer Helper |
| `ui_qt/` | Qt shell, pages, visual lineage/artwork system, table model and shared workflow orchestration |
| `legacy_linker.py` | Links veteran exports to `master.mdb` |
| `parent_optimizer.py` | Local branch, pair and future-GP scoring |
| `transfer_helper.py` | Collection-portfolio cleanup analysis and exhaustive strict-replacement checks |
| `spark_protection.py` | Strategic Spark-heritage coverage and strict replacement comparison |
| `uma_moe.py` | uma.moe API discovery, normalisation and online pairing |
| `lineage_planner.py` | Native uma.moe Lineage Planner JSON export |
| `scoring_config.py` | Scoring profile loading, migration and validation |
| `default_parent_scoring.json` | Bundled structural scoring defaults |
| `default_skill_priorities.json` | Bundled per-skill White Spark priorities |
| `tests/` | Automated engine, UI, release, documentation and i18n checks |

Test modules are project source code, intentionally versioned and kept outside the application
root so the runtime files remain easy to scan.

## Main outputs

| File | Purpose |
| --- | --- |
| `veterans_legacy_linked.json` | Fully linked local collection |
| `legacy_parent_rankings.json` | Detailed local lineage rankings |
| `legacy_parent_pairs.csv` | Compact final parent-pair ranking |
| `legacy_future_grandparents.csv` | Future-grandparent ranking |
| `transfer_helper_report.json` | Complete cleanup evidence and replacements |
| `transfer_helper_candidates.csv` | Compact cleanup list |
| `uma_moe_grandparent_pairs.json` | Local-GP × remote-GP results |
| `uma_moe_parent_pairs.json` | Local-parent × remote-parent results |

Additional diagnostics, raw API responses and catalogues are written alongside these files.

## Command line

The GUI is the recommended workflow. Local linking, catalogue generation, lineage ranking and Transfer Helper are also available through the CLI:

```powershell
py cli.py --help
```

## Tests

Install the build dependencies, then run the portable suite and bilingual audit:

```powershell
py -m pip install -r requirements-build-qt.txt
py -m pytest -q tests --ignore=tests/test_qt_runtime.py
py tests/check_i18n.py
```

`build_windows_qt.ps1` additionally discovers every Qt runtime test and executes each one in a
fresh process before the visual layout audit and packaging. This avoids native Qt teardown issues
without silently omitting newly added runtime tests.

## Windows build

```powershell
.\build_windows_qt.ps1
```

The script runs the complete test suite and produces `dist\UmaLegacyLinkerQt-win64.zip` (plus its `.sha256`). Extract the whole directory before launching `UmaLegacyLinkerQt.exe`. It bundles Python, PySide6, PyYAML and the default profiles, so no Python installation and no adjacent `default_*.json` files are required on the destination PC.

The uma.moe API key can be remembered from the application. On Windows it is encrypted with DPAPI for the current Windows account and stored under `%APPDATA%\UmaLegacyLinker`. On Linux and macOS it is stored unencrypted under `${XDG_CONFIG_HOME:-~/.config}/UmaLegacyLinker/uma_moe_api_key.dat`, with `0700` permissions on the application directory and `0600` on the file. It is never written to `config.json`; `UMA_MOE_API_KEY` keeps priority when present.

### Publishing a GitHub release

The `Windows release` GitHub Actions workflow builds the same package on every `v*` tag and attaches the archive and checksum to the corresponding GitHub release:

```powershell
git tag v1.7.2
git push origin v1.7.2
```

The workflow can also be started manually to obtain a downloadable build artifact without creating a release.

## Documentation

- [`docs/SCORING.md`](docs/SCORING.md) — scoring model and formulas;
- [`docs/WEIGHTS_FORMAT.md`](docs/WEIGHTS_FORMAT.md) — White Spark priority format;
- [`docs/PERFORMANCE.md`](docs/PERFORMANCE.md) — proposed process-based multicore design;
- [`docs/QT_UI.md`](docs/QT_UI.md) — desktop UI architecture and packaging;
- [`docs/RELEASING.md`](docs/RELEASING.md) — Windows build and GitHub release procedure;
- [`docs/THIRD_PARTY.md`](docs/THIRD_PARTY.md) — external tools and services;
- [`CHANGELOG.md`](CHANGELOG.md) — release history.

## Notes

- Always verify that an online Friend ID is still active before starting a career.
- Alternate costumes are never considered interchangeable by Transfer Helper.
- Expensive pair calculations are currently deterministic and sequential; process-based parallel execution is documented but not enabled yet.
- No game assets, executable files, `master.mdb`, extractor binaries or uma.moe datasets are distributed with this project.

Umamusume: Pretty Derby and related assets belong to their respective rights holders.
