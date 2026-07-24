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
- Exports detailed JSON, compact CSV and readable diagnostics.
- Provides an English and French desktop interface.

## Main workflows

### Local linking

Loads `data.json` and `master.mdb`, then resolves:

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

Evaluates every local veteran as both a parent and a future grandparent across the configured Champion Meeting and Team Trials profiles.

Verdicts are deliberately conservative:

- **Keep** — strong or repeatedly competitive role;
- **Likely keep** — narrow but plausible role;
- **Review** — no clear role, but no strict replacement;
- **Safe transfer** — a same-costume, same-Unique replacement is no worse in every viable context and retains G1 pair support.

The tool never edits the collection and never transfers or deletes anything automatically.

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

The active Ace, target parent, profile and course conditions come from the **Lineage Optimisation** tab and are displayed in the uma.moe tab before the search starts.

Friend IDs can be copied directly from result tables. Online retrieval is capped at **2,000 candidates per search**.
For final-parent searches, this budget is divided between a Distance cohort, a target-surface
cohort when the Ace needs it, and a broad White-preferred cohort. The cohorts are merged and
deduplicated before exact local × remote pair scoring; they guide sampling rather than acting
as final hard constraints.

The target-surface cohort can be disabled per search in the uma.moe panel, or by setting
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
Blue/White quality for the full remote lineage. The generated UQL text is kept only as an audit
and manual-copy representation because the public endpoint has no free-text UQL parameter.

Any selected final parent pair, whether fully local or local × uma.moe, can be exported in the native **Lineage Planner v1 JSON** format. In the planner, use **Save / Load** to import the generated file. Local branches retain their full `data.json` veteran and succession records; remote branches export every Spark and lineage member available from the API result.

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
- Tkinter, included with the standard Windows Python installer.
- A current Umamusume `master.mdb`.
- A veteran export in `data.json` format.
- `PyYAML` for live uma.moe searches when running from source.

Install the source dependency with:

```powershell
py -m pip install -r requirements.txt
```

## Veteran data extraction

Uma Legacy Linker does not bundle a game-memory reader.

- [UmaExtractor](https://github.com/xancia/UmaExtractor) is the extractor currently supported by the built-in **Extract and link** launcher.
- [umadump](https://github.com/Werseter/umadump) is a newer runtime memory reader and exporter with stronger layout validation and broader export capabilities. Using it as the preferred extraction backend instead of UmaExtractor is planned, but direct integration is not implemented yet.

Both are separate projects with their own requirements, licences and warnings. Tools that read a running game process are used at your own discretion.

## Quick start

```powershell
git clone https://github.com/Rom1foucher/UmaLegacyLinker.git
cd UmaLegacyLinker
py -m pip install -r requirements.txt
py app.py
```

On Windows, `run.bat` starts the same application.

Then select:

1. the current `master.mdb`;
2. the exported `data.json`;
3. an output directory.

Run **Link an existing data.json** before using the lineage optimiser, Transfer Helper or local × online pair calculation.

## Weights

The **Weights** tab exposes the structural scoring profile and per-skill White Spark priorities.

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

## Main files

| File | Purpose |
| --- | --- |
| `app.py` | Tkinter GUI, CLI entry point and workflow orchestration |
| `legacy_linker.py` | Links veteran exports to `master.mdb` |
| `parent_optimizer.py` | Local branch, pair and future-GP scoring |
| `transfer_helper.py` | Collection cleanup analysis and dominance checks |
| `uma_moe.py` | uma.moe API discovery, normalisation and online pairing |
| `lineage_planner.py` | Native uma.moe Lineage Planner JSON export |
| `scoring_config.py` | Scoring profile loading, migration and validation |
| `default_parent_scoring.json` | Bundled structural scoring defaults |
| `default_skill_priorities.json` | Bundled per-skill White Spark priorities |

Test modules are part of the source tree and are intentionally versioned.

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
py app.py --help
```

## Windows build

```powershell
.\build_windows.ps1
```

The script runs the complete test suite and generates:

- `dist\UmaLegacyLinker.exe`, a standalone one-file application containing Python, PyYAML and the default profiles;
- `dist\UmaLegacyLinker.exe.sha256`, used to verify the download.

No Python installation and no adjacent `default_*.json` files are required on the destination PC.

The uma.moe API key can be remembered from the application. On Windows it is encrypted with DPAPI for the current Windows account and stored under `%APPDATA%\UmaLegacyLinker`; it is never written in clear text to `config.json`.

### Publishing a GitHub release

The `Windows release` GitHub Actions workflow builds the same executable on every `v*` tag and attaches the EXE and checksum to the corresponding GitHub release:

```powershell
git tag v1.5.0
git push origin v1.5.0
```

The workflow can also be started manually to obtain a downloadable build artifact without creating a release.

## Documentation

- [`docs/SCORING.md`](docs/SCORING.md) — scoring model and formulas;
- [`docs/WEIGHTS_FORMAT.md`](docs/WEIGHTS_FORMAT.md) — White Spark priority format;
- [`docs/PERFORMANCE.md`](docs/PERFORMANCE.md) — proposed process-based multicore design;
- [`docs/RELEASING.md`](docs/RELEASING.md) — Windows build and GitHub release procedure;
- [`docs/THIRD_PARTY.md`](docs/THIRD_PARTY.md) — external tools and services;
- [`CHANGELOG.md`](CHANGELOG.md) — release history.

## Notes

- Always verify that an online Friend ID is still active before starting a career.
- Alternate costumes are never considered interchangeable by Transfer Helper.
- Expensive pair calculations are currently deterministic and sequential; process-based parallel execution is documented but not enabled yet.
- No game assets, executable files, `master.mdb`, extractor binaries or uma.moe datasets are distributed with this project.

Umamusume: Pretty Derby and related assets belong to their respective rights holders.
