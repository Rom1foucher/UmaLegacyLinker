# Qt desktop UI

The PySide6 interface is the desktop application. It shares the engines, configuration and output formats used by the CLI (`cli.py`).

## Included

- a dashboard showing the current MDB, local collection and latest ranking state;
- shared paths and language preference across sessions;
- extraction through UmaExtractor or umadump, linking of `data.json` or
  `trained_chara_data.json`, and skill-catalogue generation;
- searchable Ace, target-parent, course and racecourse selection with contains-based autocomplete;
- course presets and advanced static race conditions;
- one Search workspace with a persistent Ace, target-parent, race, course and scoring context;
- clearly separated local and uma.moe source cards feeding one shared result area;
- independent background actions for final pairs, parent branches and future grandparents, so a local request computes only the requested result family;
- sortable final-pair, parent-branch and future-grandparent tables;
- an embedded diagnostics pane instead of separate result windows;
- a top-down visual lineage inspector for every local and uma.moe ranking: final pairs, parent branches, future-grandparent candidates and grandparent pairs;
- game-inspired rank emblems, roomier score/P(S) cards and clearly separated aptitude/readiness/affinity diagnostics;
- two-column Spark cards that explicitly fill the Qt rich-text viewport, keeping stars, names and engine probabilities readable even in the narrow result pane;
- branch summaries that total each final parent with its two grandparents, condense duplicate Blue/Pink/White Sparks, keep Green sources distinct and mark Sparks carried by the direct parent;
- costume-aware trainee artwork and White Skill icons loaded asynchronously through a persistent, optional local cache;
- explicit shared/local/remote G1 diagnostics and a themed three-year optimal calendar for both parent and grandparent pairs, with `+6`/`+3` link values, mandatory objective locks, an objective-free Trackblazer switch and cached GameTora race banners;
- rich, colour-coded Spark chips ordered Blue → Pink → Green → White, with resolved skill icons, the existing full-run White inheritance probability and gold emphasis for the three strongest White score contributions;
- loading the latest generated ranking;
- export of a selected final pair to the uma.moe Lineage Planner format;
- live and imported uma.moe parent/grandparent searches, explicit per-mode filter/import menus, costume filters and Friend ID copy;
- stable uma.moe API URL/key configuration under Settings, separate from scoring weights and per-search filters;
- Transfer Helper with verdict/search filters and an embedded replacement diagnostic;
- a two-pane scoring-profile editor with search, 51 gameplay subcategories, plain-language help for every setting, hover summaries and visible draft/default states;
- unambiguous probability, threshold, multiplier and 100%-budget controls, including live donut charts for all nine genuinely normalised scoring groups;
- live shared White Skill priority-file management across Search and Weights,
  plus the diagnostic Umalator importer under Settings;
- live French/English switching;
- cooperative cancellation of long-running tasks from the status bar;
- a fixed opposing-parent context and offline local GP-pair ranking in the uma.moe search.

Pair ranking and every scoring formula remain unchanged. The lineage view retains the compact identities, Sparks and skill IDs required for rendering, then displays the White full-run probability already emitted by the scoring engine for its configured Inspiration Events. G1 planning likewise renders the engine's pair comparison: a race carried by both selected legacies is worth two future `+3` links, while a one-sided race is worth one. The solver maximises obtainable affinity with one race per turn, then minimises streaks of four, three and two; fixed target-character objectives constrain the standard variant, while Trackblazer switches to a precomputed objective-free variant. It neither substitutes the separate future-GP generation mechanic nor calculates a second rate in the UI.

## Visual QA

The Windows workflow renders every page, the Search conditions and per-mode uma.moe option dialogs, the embedded local and remote result panes, and all four lineage variants in French and English at 1120×720, 1366×768 and 1600×900. Its fixtures deliberately include long names, dense White summaries and all aptitude ranks. It fails on clipped button/label text, hidden horizontal overflow or a root rich-text table that collapses into a narrow strip, and currently covers 102 screenshots plus `layout-report.json`. Unit tests also enforce readable semantic-colour contrast, English coverage for visible Qt copy and safe result-pane construction before table sorting emits model callbacks.

## Artwork and offline behaviour

The application does not bundle or redistribute game artwork. The lineage inspector derives costume-aware trainee, resolved White Skill icon and G1 banner URLs from current MDB IDs, downloads only assets needed by the opened view and caches them under Qt's per-user application cache directory. The exact directory is shown as a tooltip on the cache status. Cached artwork remains usable offline; online loading can be disabled and the cache can be cleared from the inspector. The G1 planning is a fixed-size canvas inside a scroll area: resizing the dialog does not stretch the calendar or upscale low-resolution banners.

The asset catalogue contains validated URL builders for trainee artwork, support-card artwork and skill icons. Trainee and skill assets are now used by the lineage inspector; support-card integration remains deliberately outside this project step. The shared asynchronous loader, strict HTTPS host allowlist, placeholders and cache are reusable by later views.

## Run from source

```powershell
py -m pip install -r requirements-qt.txt
py qt_app.py
```

## Windows build

```powershell
.\build_windows_qt.ps1
```

The build is an `onedir` bundle packaged as `dist\UmaLegacyLinkerQt-win64.zip`. After extracting the complete directory, run `UmaLegacyLinkerQt.exe`. Python is not required on the destination PC.

The **Windows release** GitHub Actions workflow runs the tests and visual audit, builds the bundle, and attaches the ZIP plus its SHA-256 checksum to the release on every `v*` tag.

## Project layout

| Path | Purpose |
| --- | --- |
| `qt_app.py` | Qt entry point |
| `cli.py` | Headless CLI sharing the same engines |
| `ui_qt/core.py` | GUI-independent configuration and workflow orchestration |
| `ui_qt/main_window.py` | application shell, navigation, progress and log drawer |
| `ui_qt/pages_home_data.py` | dashboard and local linking workflow |
| `ui_qt/pages_search.py` | unified context, local/uma.moe actions, static filter dialogs and shared results workspace |
| `ui_qt/pages_optimizer.py` | reusable local result explorer and diagnostics |
| `ui_qt/pages_online.py` | reusable uma.moe result explorer and costume-filter dialog |
| `ui_qt/pages_transfer.py` | Transfer Helper analysis and diagnostics |
| `ui_qt/pages_weights.py` | scoring and White Skill priority editor |
| `ui_qt/pages_tools.py` | Settings: uma.moe integration and diagnostic Umalator import |
| `ui_qt/models.py` | sortable Qt table model |
| `ui_qt/presentation.py` | safe HTML diagnostics rendering |
| `ui_qt/asset_catalog.py` | validated GameTora trainee, support, skill and race-banner asset URLs |
| `ui_qt/image_assets.py` | asynchronous loading, allowlist and persistent disk cache |
| `ui_qt/lineage_nodes.py` | compatibility layer for current and older pair, branch and grandparent-result schemas |
| `ui_qt/lineage_view.py` | top-down lineage inspector, G1 planning calendar, rich Spark cards and artwork controls |
| `ui_qt/weight_controls.py` | scoring taxonomy, normalised groups and slider semantics |
| `ui_qt/weight_help.py` | bilingual purpose, impact, scope and scale guidance for every weight |
| `ui_qt/distribution_chart.py` | dependency-free live donut chart for normalised weight groups |
| `ui_qt/layout_audit.py` | offscreen screenshots and overflow checks |

The reasoning and comparable-app patterns behind the weights redesign are recorded in [`WEIGHTS_UI_DESIGN.md`](WEIGHTS_UI_DESIGN.md).

## Packaging note

PySide6 is the official Qt for Python binding and is available under LGPLv3/GPLv3 or a commercial Qt licence. The build uses an extracted `onedir` layout so the Qt runtime remains made of separate dynamically loaded libraries. Review [`THIRD_PARTY.md`](THIRD_PARTY.md) and the licence metadata included with the binary bundle before publishing a release.
