# Uma Legacy Linker

Uma Legacy Linker is a local desktop application for analysing and ranking inheritance lineages in **Umamusume: Pretty Derby**.

It links exported veteran data to the game's current `master.mdb`, reconstructs each veteran's factors, race history and ancestry, then evaluates parents and grandparents for a selected Ace, strategy and race profile.

The application is designed for players who want more than a simple compatibility score: it combines affinity, blue and pink factors, white skills, race factors, lineage potential, G1 overlap and configurable meta priorities into one explainable ranking model.

> This is an independent community tool. It is not affiliated with or endorsed by Cygames.

## Main features

### Local veteran linking

- Links an exported `data.json` to the current game database.
- Resolves trainees, cards, factors, skills and races from the selected `master.mdb` instead of relying on permanent internal IDs.
- Reconstructs each veteran's:
  - blue, pink, green and white factors;
  - factor star levels;
  - learned skills;
  - G1 victories;
  - two parents and inherited lineage data.
- Generates readable JSON, CSV and text summaries for further analysis.

### Parent and lineage ranking

Rank your local veterans for a specific target build using:

- target Ace;
- future parent being produced;
- surface: Turf or Dirt;
- distance: Sprint, Mile, Medium or Long;
- running style: Front Runner, Pace Chaser, Late Surger or End Closer;
- track, direction, season, weather and ground condition;
- exact course presets when available.

The optimiser produces several complementary views:

- **final parent pairs** for the target Ace;
- **individual parent candidates**;
- **future grandparent candidates** for producing a stronger parent;
- affinity and G1-overlap breakdowns;
- blue, pink and white factor contributions;
- current value versus future lineage potential.

### Skill-aware scoring

White factors are evaluated by actual usefulness for the selected profile rather than by raw quantity alone.

The bundled model can account for:

- skill relevance by surface, distance and running style;
- rare or difficult-to-source skills;
- star level and duplicate copies;
- lineage-supported acquisition potential;
- course-specific conditions;
- diminishing returns and score caps;
- manual skill-level priorities.

The default priorities are intended to provide a practical starting point, not an immutable definition of the meta.

### Fully customisable weights

The **Weights** tab exposes the complete scoring model.

Users can customise, among other things:

- which blue factor types should be favoured;
- blue priorities by distance or build profile;
- pink factor categories and star multipliers;
- white skill importance;
- affinity thresholds and saturation curves;
- G1 overlap value;
- lineage-potential weighting;
- race-condition bonuses;
- uma.moe-specific ranking weights.

Custom settings are stored as minimal overrides on top of the bundled defaults. This keeps user profiles compatible when new default parameters are introduced.

The exact profiles used for a calculation are exported to the output directory as:

- `active_parent_scoring.json`;
- `active_skill_priorities.json`.

### uma.moe integration

Uma Legacy Linker can query [uma.moe](https://uma.moe/) to search for public grandparents that complement a local lineage.

Available workflows include:

- automatically pairing local and remote candidates;
- fixing a specific local GP1 and searching for the best remote GP2;
- generating UQL filters from the selected build profile;
- using a manually written UQL query;
- importing a previously saved API response;
- verifying strict requirements locally after retrieval;
- exporting ranked pairs, diagnostics and raw responses.

Online retrieval is strictly limited to **2,000 parents per search**.

An uma.moe API key can be entered in the masked field inside the application. It is kept in memory for the current session and is not written to the configuration files. It can also be provided through the `UMA_MOE_API_KEY` environment variable.

Always verify that a listed parent is still available and that its friend ID is current before starting a career.

### Catalogues and diagnostics

The application can generate detailed catalogues directly from `master.mdb`, including:

- skills and activation conditions;
- parsed condition expressions and their original source expression;
- condition-variable vocabulary;
- race factors that grant skills;
- white-skill weighting templates.

A legacy Umalator batch importer is retained for diagnostics and comparison. Current rankings use the manual priority model by default.

## Requirements

- Windows is the primary supported platform.
- Python **3.10 or newer**.
- Tkinter, included with the standard Windows Python installer.
- A current Umamusume `master.mdb` file.
- An exported veteran `data.json` for collection analysis.
- `PyYAML` for uma.moe functionality when running from source.

Install the optional Python dependency with:

```powershell
py -m pip install PyYAML
```

The core local linking and ranking pipeline otherwise uses Python's standard library.

## Getting started

### 1. Download or clone the project

Keep the Python files and bundled `default_*.json` files in the same directory.

### 2. Obtain the required game data

You need:

- the current `master.mdb` from your game installation;
- a veteran export in `data.json` format.

The application can launch a separately installed copy of [UmaExtractor](https://github.com/xancia/UmaExtractor) in CLI mode to produce the export. UmaExtractor is not included, modified or redistributed by this project.

Read the external project's documentation and warnings before using it. Software that reads data from a running game process is used at your own discretion.

### 3. Launch the application

On Windows, double-click:

```text
run.bat
```

Or launch it manually from PowerShell:

```powershell
py app.py
```

### 4. Select the input files

At the top of the interface, select:

- `master.mdb`;
- your exported `data.json`;
- the desired output directory.

You can then link the collection, generate catalogues, configure a target build and run the lineage optimiser.

## Application tabs

### Link & Catalogue

Link an existing veteran export, launch UmaExtractor, or generate database catalogues without running a full ranking.

### Lineage Optimisation

Configure the Ace, future parent, course profile and conditions, then rank local parents, parent pairs and future grandparents.

### uma.moe

Search public parent data, generate or enter UQL filters, combine remote candidates with a local grandparent and inspect detailed pair diagnostics.

### Legacy Tools

Import older Umalator Skill Chart batch results for diagnostic purposes.

### Weights

Inspect, edit, import, export or reset the complete scoring profile and per-skill white-factor priorities.

## Main output files

Depending on the selected operation, the output directory may contain:

| File | Purpose |
| --- | --- |
| `veterans_legacy_linked.json` | Fully linked local veteran data |
| `veterans_legacy_summary.csv` | Compact collection summary |
| `veterans_legacy_report.txt` | Human-readable linking report |
| `legacy_parent_rankings.json` | Complete local lineage ranking |
| `legacy_parent_candidates.csv` | Individual parent candidates |
| `legacy_parent_pairs.csv` | Final parent-pair ranking |
| `legacy_future_grandparents.csv` | Future grandparent ranking |
| `uma_moe_grandparent_pairs.json` | Detailed online pair results |
| `uma_moe_grandparent_pairs.csv` | Compact online pair ranking |
| `uma_moe_diagnostics.json` | Search and filtering diagnostics |
| `skill_condition_catalog.json` | Parsed skill-condition catalogue |
| `condition_type_catalog.json` | Condition-variable catalogue |
| `race_factor_skill_catalog.json` | Race factors that grant skills |
| `active_parent_scoring.json` | Effective structural scoring profile |
| `active_skill_priorities.json` | Effective per-skill priority profile |

Raw uma.moe requests and responses are also retained where applicable for reproducibility and debugging.

## Command-line usage

The graphical interface is the recommended workflow, but the main local operations are also available from the command line.

### Link a collection

```powershell
py app.py --cli `
  --master "C:\path\to\master.mdb" `
  --json "C:\path\to\data.json" `
  --output ".\output"
```

### Generate catalogues only

```powershell
py app.py --cli --catalog-only `
  --master "C:\path\to\master.mdb" `
  --output ".\output"
```

### Rank lineages

```powershell
py app.py --cli --rank-parents `
  --master "C:\path\to\master.mdb" `
  --json "C:\path\to\data.json" `
  --ace-card-id 100401 `
  --future-parent-card-id 101001 `
  --surface turf `
  --distance medium `
  --style front_runner `
  --course-key cm15_hanshin_2200_turf `
  --scoring-config ".\my_scoring_overrides.json" `
  --skill-priorities ".\my_skill_priorities.json" `
  --top 30 `
  --output ".\output"
```

Both custom JSON files may contain either a complete profile or only the values that should override the defaults.

## Windows executable build

A standalone Windows build can be created with:

```powershell
.\build_windows.ps1
```

The generated executable is placed in `dist\UmaLegacyLinker.exe`. Keep the bundled `default_*.json` files next to the executable.

## Documentation

Additional technical details are available in:

- [`docs/SCORING.md`](docs/SCORING.md) — scoring model and formulas;
- [`docs/WEIGHTS_FORMAT.md`](docs/WEIGHTS_FORMAT.md) — white-skill weight format;
- [`docs/SIMULATOR_WEIGHTS.md`](docs/SIMULATOR_WEIGHTS.md) — legacy Umalator pipeline;
- [`docs/THIRD_PARTY.md`](docs/THIRD_PARTY.md) — external-tool notes;
- [`CHANGELOG.md`](CHANGELOG.md) — version history.

## Credits and acknowledgements

Uma Legacy Linker builds on data and services made available by other community projects.

Special thanks to:

- [uma.moe](https://uma.moe/) for its public Umamusume database, parent search tools and API;
- [xancia/UmaExtractor](https://github.com/xancia/UmaExtractor) for providing the external veteran-export workflow used by the application.

Neither project is bundled with Uma Legacy Linker, and each remains governed by its own licence, documentation and usage conditions.

## Licence and game assets

No game assets, game executable files, `master.mdb`, UmaExtractor binaries or uma.moe data are distributed with this project.

Umamusume: Pretty Derby and its related assets are property of their respective rights holders.
