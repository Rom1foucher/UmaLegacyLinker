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

The active Ace, target parent, profile and course conditions come from the **Lineage Optimisation** tab and are displayed in the uma.moe tab before the search starts.

Friend IDs can be copied directly from result tables. Online retrieval is capped at **2,000 candidates per search**.

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

This avoids pretending that the full final lineage is already known during a future-GP search.

See [`docs/SCORING.md`](docs/SCORING.md) for formulas and implementation details.

## Requirements

- Windows is the primary supported platform.
- Python **3.10+**.
- Tkinter, included with the standard Windows Python installer.
- A current Umamusume `master.mdb`.
- A veteran export in `data.json` format.
- `PyYAML` for live uma.moe searches when running from source.

Install the optional dependency with:

```powershell
py -m pip install PyYAML
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
py -m pip install PyYAML
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
- raise Distance-B compensation thresholds to accept B-start pairs only with exceptional support.

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

The executable is generated in `dist\UmaLegacyLinker.exe`. Keep the bundled `default_*.json` files next to it.

## Documentation

- [`docs/SCORING.md`](docs/SCORING.md) — scoring model and formulas;
- [`docs/WEIGHTS_FORMAT.md`](docs/WEIGHTS_FORMAT.md) — White Spark priority format;
- [`docs/PERFORMANCE.md`](docs/PERFORMANCE.md) — proposed process-based multicore design;
- [`docs/THIRD_PARTY.md`](docs/THIRD_PARTY.md) — external tools and services;
- [`CHANGELOG.md`](CHANGELOG.md) — release history.

## Notes

- Always verify that an online Friend ID is still active before starting a career.
- Alternate costumes are never considered interchangeable by Transfer Helper.
- Expensive pair calculations are currently deterministic and sequential; process-based parallel execution is documented but not enabled yet.
- No game assets, executable files, `master.mdb`, extractor binaries or uma.moe datasets are distributed with this project.

Umamusume: Pretty Derby and related assets belong to their respective rights holders.
