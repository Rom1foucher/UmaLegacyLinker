# Qt UI preview 12

This branch now contains a complete first pass of the PySide6 redesign. It is deliberately shipped beside the Tkinter application while the new interface receives wider testing.

## Included

- a dashboard showing the current MDB, local collection and latest ranking state;
- shared paths and language preference with the stable interface;
- extraction through UmaExtractor, local `data.json` linking and skill-catalogue generation;
- searchable Ace, target-parent, course and racecourse selection with contains-based autocomplete;
- course presets and advanced static race conditions;
- local lineage optimisation in a background worker;
- sortable final-pair, parent-branch and future-grandparent tables;
- an embedded diagnostics pane instead of separate result windows;
- a top-down visual lineage inspector for every local and uma.moe ranking: final pairs, parent branches, future-grandparent candidates and grandparent pairs;
- game-inspired rank emblems, roomier score/P(S) cards and clearly separated aptitude/readiness/affinity diagnostics;
- two-column Spark cards that explicitly fill the Qt rich-text viewport, keeping stars, names and engine probabilities readable even in the narrow result pane;
- branch summaries that total each final parent with its two grandparents, condense duplicate Blue/Pink/White Sparks, keep Green sources distinct and mark Sparks carried by the direct parent;
- costume-aware trainee artwork and White Skill icons loaded asynchronously through a persistent, optional local cache;
- rich, colour-coded Spark chips ordered Blue → Pink → Green → White, with resolved skill icons, the existing full-run White inheritance probability and gold emphasis for the three strongest White score contributions;
- loading the latest generated ranking;
- export of a selected final pair to the uma.moe Lineage Planner format;
- live and imported uma.moe parent/grandparent searches, secure API-key persistence, costume filters and Friend ID copy;
- Transfer Helper with verdict/search filters and an embedded replacement diagnostic;
- a two-pane scoring-profile editor with search, 50 gameplay subcategories, plain-language help for every setting, hover summaries and visible draft/default states;
- unambiguous probability, threshold, multiplier and 100%-budget controls, including live donut charts for all nine genuinely normalised scoring groups;
- individual White Skill priority-file management and the diagnostic Umalator importer;
- live French/English switching;
- a direct fallback launcher for the stable Tkinter interface.

Pair ranking and every scoring formula remain unchanged. The lineage view retains the compact identities, Sparks and skill IDs required for rendering, then displays the White full-run probability already emitted by the scoring engine for its configured Inspiration Events. It neither substitutes the separate future-GP generation mechanic nor calculates a second rate in the UI.

## Visual QA

The Windows workflow renders every page, the embedded local and uma.moe result panes, and all four lineage variants in French and English at 1120×720, 1366×768 and 1600×900. Its fixtures deliberately include long names, dense White summaries and all aptitude ranks. It fails on clipped button/label text, hidden horizontal overflow or a root rich-text table that collapses into a narrow strip, and uploads the 108 screenshots plus `layout-report.json`. Unit tests also enforce readable semantic-colour contrast, English coverage for visible Qt copy and safe result-pane construction before table sorting emits model callbacks.

## Artwork and offline behaviour

The application does not bundle or redistribute game artwork. The lineage inspector derives costume-aware trainee and resolved White Skill icon URLs from current MDB IDs, downloads only assets needed by the opened view and caches them under Qt's per-user application cache directory. The exact directory is shown as a tooltip on the cache status. Cached artwork remains usable offline; online loading can be disabled and the cache can be cleared from the inspector.

The asset catalogue contains validated URL builders for trainee artwork, support-card artwork and skill icons. Trainee and skill assets are now used by the lineage inspector; support-card integration remains deliberately outside this project step. The shared asynchronous loader, strict HTTPS host allowlist, placeholders and cache are reusable by later views.

## Run from source

```powershell
py -m pip install -r requirements-qt.txt
py qt_app.py
```

`py qt_app.py --legacy` opens the Tkinter interface using the same configuration.

## Windows preview build

```powershell
.\build_windows_qt.ps1
```

The Qt build is an `onedir` bundle packaged as `dist\UmaLegacyLinkerQt-preview-win64.zip`. After extracting the complete directory, run `UmaLegacyLinkerQt.exe`. Python is not required on the destination PC.

The dedicated **Windows Qt preview** GitHub Actions workflow runs the tests and visual audit, builds the bundle, and uploads the ZIP plus its SHA-256 checksum. It is manual-only and does not create a GitHub release.

## Project layout

| Path | Purpose |
| --- | --- |
| `qt_app.py` | Qt entry point and stable-UI fallback switch |
| `ui_qt/core.py` | GUI-independent configuration and workflow orchestration |
| `ui_qt/main_window.py` | application shell, navigation, progress and log drawer |
| `ui_qt/pages_home_data.py` | dashboard and local linking workflow |
| `ui_qt/pages_optimizer.py` | optimisation form and embedded result explorer |
| `ui_qt/pages_online.py` | uma.moe search, filters, secure key controls and results |
| `ui_qt/pages_transfer.py` | Transfer Helper analysis and diagnostics |
| `ui_qt/pages_weights.py` | scoring and White Skill priority editor |
| `ui_qt/pages_tools.py` | diagnostic Umalator import |
| `ui_qt/models.py` | sortable Qt table model |
| `ui_qt/presentation.py` | safe HTML diagnostics rendering |
| `ui_qt/asset_catalog.py` | validated GameTora trainee, support and skill asset URLs |
| `ui_qt/image_assets.py` | asynchronous loading, allowlist and persistent disk cache |
| `ui_qt/lineage_nodes.py` | compatibility layer for current and older pair, branch and grandparent-result schemas |
| `ui_qt/lineage_view.py` | top-down lineage inspector, rich Spark cards and artwork controls |
| `ui_qt/weight_controls.py` | scoring taxonomy, normalised groups and slider semantics |
| `ui_qt/weight_help.py` | bilingual purpose, impact, scope and scale guidance for every weight |
| `ui_qt/distribution_chart.py` | dependency-free live donut chart for normalised weight groups |
| `ui_qt/layout_audit.py` | offscreen screenshots and overflow checks |

The reasoning and comparable-app patterns behind the weights redesign are recorded in [`WEIGHTS_UI_DESIGN.md`](WEIGHTS_UI_DESIGN.md).

## Packaging note

PySide6 is the official Qt for Python binding and is available under LGPLv3/GPLv3 or a commercial Qt licence. The preview uses an extracted `onedir` layout so the Qt runtime remains made of separate dynamically loaded libraries. Review [`THIRD_PARTY.md`](THIRD_PARTY.md) and the licence metadata included with the binary bundle before publishing a release.
