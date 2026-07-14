# Uma Legacy Linker

Uma Legacy Linker is a local desktop application for analysing and ranking inheritance lineages in **Umamusume: Pretty Derby**.

It links exported veteran data to the game's current `master.mdb`, reconstructs each veteran's factors, race history and ancestry, then evaluates parents and grandparents for a selected Ace, strategy and race profile.

The application is designed for players who want more than a simple compatibility score: it combines affinity, blue and pink factors, white skills, race factors, lineage potential, G1 overlap and configurable meta priorities into one explainable ranking model.

> This is an independent community tool. It is not affiliated with or endorsed by Cygames.

## Main features

### English and French interface

The desktop interface is available in **English** and **French**. Use the language selector in the top-right corner of the application to switch instantly. The selected language is saved in the user configuration and restored on the next launch.

The language setting applies to the main interface, dialogs, result windows, status messages, validation errors and the activity log. Internal profile keys and exported data remain language-independent so changing the interface language does not alter calculations or saved scoring profiles.

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

The bundled preset catalogue contains:

- **CM16 to CM46**, ordered from the next relevant Global Champion Meeting onward;
- five generic **Team Trials** profiles: Turf Sprint, Turf Mile, Turf Medium, Turf Long and Dirt Mile;
- **CM9 to CM15** as a lower-priority archive.

Selecting a Champion Meeting preset automatically applies its surface, distance, racecourse when known, direction, season, weather and ground condition. Team Trials presets intentionally keep exact race conditions unspecified and apply only their generic surface/distance profile. A manually selected condition can still override a preset value for quick what-if analysis.

The optimiser produces several complementary views:

- **final parent pairs** for the target Ace;
- **individual parent candidates**;
- **future grandparent candidates** for producing a stronger parent;
- affinity and G1-overlap breakdowns;
- blue, pink and white factor contributions;
- current value versus future lineage potential.

### Transfer Helper

The **Transfer Helper** audits the complete local veteran list before you clean it up in game.

It evaluates every veteran across all generic combinations of:

- Turf and Dirt;
- Sprint, Mile, Medium and Long;
- Front Runner, Pace Chaser, Late Surger and End Closer;
- parent and future-grandparent roles.

Upcoming Champion Meeting and Team Trials presets can also be included. Archived CM9-CM15 presets remain manually selectable in the optimiser but are excluded from the automatic cleanup scan so past courses do not receive the same weight as future-use categories. Parent potential uses the veteran's complete current branch and its affinity against the available Ace profiles. Grandparent potential evaluates the veteran as the direct GP while retaining its current parents for white-gene generation support.

The helper first measures viability against the **complete local veteran pool**, across all Uma cards. It does not create an artificial niche merely because a veteran is the least-bad copy of a specific Uma in an unsuitable context. For example, a marginally better Mejiro Ryan on Dirt does not need to be preserved when every Ryan is globally outclassed there.

Same-card dominance is therefore evaluated only in parent or grandparent contexts where at least one copy of that card is genuinely competitive. Non-viable contexts are ignored and cannot block an otherwise safe replacement.

The helper produces three conservative verdicts:

- **Safe transfer** — another copy of the same card and inherited unique is not worse in every globally viable parent or grandparent niche, remains at least as useful for G1 pair support and clears the configured average lead;
- **Review** — no competitive parent or grandparent role was detected, but no strict replacement exists;
- **Keep** — at least one globally competitive parent or grandparent niche remains, or the copy is not safely replaceable.

Alternate costumes are never considered interchangeable. The helper never edits `data.json` and never transfers or deletes anything automatically.

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
- Transfer Helper competitiveness and dominance thresholds.

Custom settings are stored as minimal overrides on top of the bundled defaults. This keeps user profiles compatible when new default parameters are introduced.

The exact profiles used for a calculation are exported to the output directory as:

- `active_parent_scoring.json`;
- `active_skill_priorities.json`.

### uma.moe integration

Uma Legacy Linker can query [uma.moe](https://uma.moe/) for two distinct workflows: finding a remote grandparent to produce a future parent, or finding a complete remote parent branch for the final Ace.

Available workflows include:

- automatically pairing local and remote candidates;
- fixing a specific local GP1 and searching for the best remote GP2;
- fixing a local final parent and searching for the best remote final parent;
- automatically testing top local-parent × remote-parent pools;
- generating UQL filters from the selected build profile;
- using a manually written UQL query;
- importing a previously saved API response;
- verifying strict requirements locally after retrieval;
- exporting ranked pairs, diagnostics and raw responses.

The final-parent workflow uses the exact same six-member scoring engine as the local parent-pair optimiser. The remote Main and its two parents form one complete branch; the local parent and its two parents form the other. Affinity, five G1 links and every factor across the six visible members are therefore evaluated identically for local-only and local × online pairs.

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

Choose **English** or **Français** from the selector in the top-right corner. The choice is persisted automatically.

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

Configure the Ace, future parent, course profile and conditions, then rank local parents, parent pairs and future grandparents. The course selector is available even before `master.mdb` is loaded. Choosing a preset updates the compatible profile and static race conditions automatically.

### Transfer Helper

Analyse the entire local collection, inspect safe same-card replacements, and review low-ceiling veterans that have no detected competitive role. By default, the audit evaluates only the next five Champion Meetings and the five Team Trials categories, each across all four running styles. Older and later course presets remain available in the normal lineage optimiser but do not affect cleanup verdicts.

### uma.moe

Search public parent data in either grandparent mode or final-parent mode. Remote final parents can be combined with a fixed local parent or with an automatically selected local pool, using the same exact pair calculation as the local optimiser.

### Legacy Tools

Import older Umalator Skill Chart batch results for diagnostic purposes.

### Weights

Inspect, edit, import, export or reset the complete scoring profile and per-skill white-factor priorities.

## Course preset catalogue

Course presets are defined in `default_course_overrides.json`. Custom files using the same schema can be selected from the interface. The application falls back to the bundled file when an absolute path saved by an older installation no longer exists.

Champion Meeting entries may contain exact static conditions and optional skill-specific course corrections. Team Trials entries are generic category presets without fixed green-skill conditions. Their reference notes link to [GameTora's Team Trials scoring guide](https://gametora.com/umamusume/team-trials-pvp-scoring).

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
| `transfer_helper_report.json` | Detailed cleanup audit and evidence |
| `transfer_helper_candidates.csv` | Compact keep/review/safe-transfer list |
| `transfer_helper_summary.txt` | Human-readable safe-transfer summary |
| `uma_moe_grandparent_pairs.json` | Detailed online pair results |
| `uma_moe_grandparent_pairs.csv` | Compact online pair ranking |
| `uma_moe_diagnostics.json` | Grandparent search and filtering diagnostics |
| `uma_moe_parent_pairs.json` | Detailed local-parent × remote-parent results |
| `uma_moe_parent_pairs.csv` | Complete compact online parent-pair ranking |
| `uma_moe_parent_diagnostics.json` | Parent-search normalization and scoring diagnostics |
| `uma_moe_parent_raw_response.json` | Raw API/import payload retained for the parent search |
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
  --course-key cm16_nakayama_1200_turf `
  --scoring-config ".\my_scoring_overrides.json" `
  --skill-priorities ".\my_skill_priorities.json" `
  --top 30 `
  --output ".\output"
```

Both custom JSON files may contain either a complete profile or only the values that should override the defaults.

### Audit the local veteran list

```powershell
py app.py --cli --transfer-helper `
  --master "C:\path\to\master.mdb" `
  --json "C:\path\to\data.json" `
  --scoring-config ".\my_scoring_overrides.json" `
  --skill-priorities ".\my_skill_priorities.json" `
  --output ".\output"
```

Transfer Helper thresholds and scope are stored under `transfer_helper` in `default_parent_scoring.json` and are available in the graphical weight editor. The default scope uses `upcoming_cm_limit: 5`, enables all five Team Trials profiles, and disables generic surface/distance profiles.

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

### Transfer Helper verdicts

The Transfer Helper uses four verdicts:

- **Safe transfer**: a same-card, same-unique replacement is demonstrably no worse across every viable parent and grandparent use case.
- **Review**: no meaningful role was detected; manual inspection is still required.
- **Likely keep**: the veteran has a plausible but narrow or isolated niche.
- **Keep**: the veteran reaches an elite global rank or remains competitive repeatedly across multiple contexts and distinct course profiles.

Default retention thresholds are intentionally selective: top 7.5% counts as elite, while repeated value requires at least three competitive contexts across at least two distinct profiles.

### Finding a veteran in game

Transfer Helper outputs include the local training ID, card identity, in-game rank, evaluation score, five final stats, and both grandparents. The results window shows rank and evaluation score directly, while the detail panel exposes the complete identification line. When a replacement is recommended, its in-game rank and evaluation score are shown as well.

### Distribution-aware Transfer Helper ranking

The Transfer Helper does not classify veterans from percentile alone. Each parent and grandparent result receives a composite utility score based on:

- its absolute lineage score;
- its score relative to the best local candidate in the same context;
- its percentile rank, with a deliberately smaller weight.

This prevents a weak veteran from being kept merely because it ranks well inside a poor field, while preserving genuinely useful veterans in dense, high-quality score clusters. The default weights and thresholds are editable under `transfer_helper` in the scoring configuration.
