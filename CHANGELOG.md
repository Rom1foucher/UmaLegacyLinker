# Changelog

This project uses feature-level semantic versioning. Small internal iterations are consolidated into the nearest meaningful release instead of receiving their own public version.

## Unreleased

- Fixed course-preset persistence in the Qt interface, including the explicit no-preset state, complete condition replacement when switching presets and preserving a preset when only the running style changes.
- Unified the Ace, target parent, race profile, course preset, exact conditions and scoring inputs into one live context shared by the Lineage Optimisation and uma.moe pages. Both pages now display and edit every shared race/scoring input they consume.
- Applied an explicit dark palette to standard selectors, searchable dropdowns and detached completer popups so native Windows popup styling cannot produce white text on a white background.

## 1.7.0 - PySide6 becomes the only interface

- Added umadump as a second extraction backend, selected automatically from the tool's name. It is run once from the output folder so its exports land beside the other artefacts, and its `trained_chara_data.json` feeds the linker unchanged.
- Skipped borrowed veterans everywhere: the game reports the ones rented for an in-progress career with a non-zero `use_type`, and nothing filtered them, so they were ranked, counted and offered for transfer as if they were owned.
- Promoted the PySide6 interface to the sole desktop UI and removed the legacy Tkinter application (`app.py`, `autocomplete.py`, their tests, the old spec and launcher). The sidebar's "stable interface" switch and the Qt preview badge are gone.
- Exposed the 1.6.0 contextual grandparent search in the Qt uma.moe page: an opposing-parent context (none, a local veteran, or candidates extracted from an exported pair result or API response), an offline "Local GP pairs" ranking that skips the API entirely, per-factor lineage star filters mirroring the uma.moe sliders, and a dedicated Surface-cohort toggle. Aligned the page with 1.6.0's structured filters by dropping the stale Dirt-only option and the free-text/auto UQL controls; the generated UQL stays visible read-only.
- Added cooperative cancellation of long-running tasks from the status bar, reusing the logger/progress callbacks as checkpoints without any engine change.
- Extracted the headless command line into a standalone `cli.py` that imports the engines directly, so linking, catalogue generation, ranking and the Transfer Helper no longer depend on any UI toolkit.
- Reorganised the Qt weight editor into explicit scoring domains and 51 gameplay subcategories, with bilingual contextual help, purpose-built controls and collapsible calculation blocks.
- Made normalised group weights independently editable, with non-mutating distribution previews, live donut charts and separate value/block reset actions.
- Covered the contextual GP search in the Qt weight catalogue, including API retrieval cohorts, local × remote preselection, fixed-opposing-parent settings and target-surface aptitude policy.
- Added a top-down lineage inspector for local and uma.moe results, with costume artwork, White Skill icons, rich Spark summaries, inheritance probabilities, aptitude badges and result diagnostics.
- Added an optional bounded image cache with offline reuse, placeholders and direct cache controls.
- Kept the historical Umalator importer in a dedicated "Tools and diagnostics" page, separate from the primary scoring workflow.
- Switched the Windows build and release workflow to the Qt bundle only (`UmaLegacyLinkerQt-win64.zip`), removed the redundant preview workflow, and updated the docs, run script and release checklist accordingly.
- Added a bilingual visual layout audit covering every page, result pane and lineage variant at three viewport sizes; the Windows workflow uploads its screenshots and report.
- Fixed the standalone CLI configuration imports so parent ranking and Transfer Helper commands complete successfully, and covered both dispatch paths with regression tests.
- Closed extractor subprocess streams deterministically and aligned the 1.7.0 Windows metadata, PyInstaller manifest, release workflow and Qt-only documentation.
- Extended optional uma.moe API-key persistence to Linux and macOS with a versioned local-file fallback, atomic writes, strict `0700`/`0600` permissions and an explicit unencrypted-storage warning; Windows keeps DPAPI and remains compatible with legacy saved payloads.
- Added an independent Transfer Helper Spark-protection floor: direct White and skill-granting Race Sparks are normalised by effective skill, evaluated at their maximum utility over the active CM/Team Trials scope, enriched with current-MDB support-hint availability, and compared against the proposed replacement by carriers, stars, neutral inheritance probability, direct future-GP placement and configurable packages. Non-preserved assets now raise `safe_transfer` to `review` or `likely_keep` without altering the primary score, with bilingual UI and JSON/CSV diagnostics.

## 1.6.0 - Contextual grandparent search and full English coverage

- Added an optional opposing-parent branch to future-grandparent searches (local, imported or from uma.moe). With one set, GP1/GP2 are ranked through the canonical six-member final-pair engine instead of the generic heuristic, with a projected G1 plan spanning both candidate GPs and the opposing parent, and matching contextual diagnostics/CSV fields.
- Added a "Paires de GP locales" action on the Lineage Optimisation tab: ranks every local times local grandparent pair with the exact uma.moe GP engine (same settings, including the contextual opposing-parent mode above), fully offline. Symmetric duplicates are evaluated once.
- Split target-surface aptitude from running-style pinks throughout parent branches and final pairs, with a configurable policy (B as the minimum gate, A as a soft preference, Distance S as the primary constraint) and below-minimum readiness/probability scoring, and surfaced surface status, stars and probabilities across diagnostics and CSV exports.
- Reworked automatic uma.moe parent and grandparent retrieval into distance, target-surface and broad/White cohorts, with the surface cohort now independently optional per search and skipped automatically once a locked local branch already covers the target. Contextual API cohorts consume only the remaining aptitude deficit, and known White coverage is softly de-prioritized for retrieval.
- Added per-factor lineage filters on both uma.moe searches, mirroring the site's sliders: Blue and Pink star-sum minimums over the remote Main plus its two parents, applied locally after download since the API only confirms a Main-only pink parameter.
- Replaced the free-text UQL/Auto controls with the filters actually supported by `/api/v3/search`, and every search-filter group now carries a hint on what it does, what it applies to, and when to use it.
- Reworked the search popup: shows every match with a scrollable list and result counter instead of a hard 12-item cutoff, full keyboard navigation, and a native dropdown kept in sync with the filter. Fixed it not staying closed after picking an option or clicking away, and scrolling on its own, both caused by focus alone reopening the list.
- Fixed two related crashes in contextual grandparent search: the app's own retrieval-plan diagnostics could be mistaken for the real candidate list and silently drop every genuine candidate, and the detailed-row builder could read stale component keys once ranking swapped to the exact pair engine.
- Audited the full FR/EN coverage of the interface, logs and result panels with a dedicated checker (kept in the repo as `check_i18n.py`); status labels, breakdown labels and decimal separators now render correctly in either language, including in composite and log messages built by string concatenation.
- Simplified the interface: removed the legacy tools tab (its one diagnostic import moved under Pondérations) and the umadump discovery button, condensed the affinity columns and the Transfer Helper intro/verdict legend (added the missing "Probablement conserver" verdict with a direct link to its thresholds), and grouped the uma.moe G1 plan and API fetch limit under a collapsible "Options avancées" section.
- Selecting an Ace matching the parent to produce now clears the field with an explicit notice instead of silently substituting another character.
- Added cooperative task cancellation from the status bar, and linking completion now points to the next step in the status bar and log.
- Migrated pre-V17 `pink_other` overrides without changing their total pink allocation.

## 1.5.0 — uma.moe Lineage Planner export

- Unified future-grandparent weights across local ranking, Transfer Helper and uma.moe pair searches.
- Removed the obsolete independent uma.moe GP-pair weight tables and migrated legacy overrides.
- Added effective-weight diagnostics, unique-Spark scoring and separate affinity/G1 components to online GP pairs.
- Kept production-run affinity as a balanced non-weighted diagnostic instead of a hidden saturated component.
- Added a standalone, one-file Windows executable build with embedded default profiles and version metadata.
- Added tag-driven GitHub releases containing the Windows executable and its SHA-256 checksum.
- Added optional uma.moe API-key persistence protected by Windows DPAPI for the current user account.
- Added native Lineage Planner v1 JSON export for selected final parent pairs.
- Added export actions to both local optimiser results and local × uma.moe parent results.
- Preserved complete local veteran, Spark, race and succession data from `data.json`, including great-grandparents when present.
- Added compact Spark-based fallback export for remote lineage members returned by uma.moe.
- Completed English translations for optimiser detail panels and related runtime diagnostics.
- Prevented a target parent Uma from being selected as its own grandparent, including alternate costumes; the target Ace remains eligible.

## 1.4.0 — Interface polish, diagnostics and terminology

- Completed the English coverage of dynamic UI text, runtime logs and scoring details, with consistent terminology for costume variants, trained veterans and Sparks.
- Made result-table columns sortable in ascending or descending order.
- Made uma.moe Friend IDs copyable by clicking their table cell, with an explicit clipboard confirmation.
- Added Transfer Helper filtering by verdict followed by in-game score ordering.
- Added current and replacement Spark details to Transfer Helper reports, logs and the result inspector.
- Added an explicit summary of the Ace, target parent, active profile, course conditions and pairing mode used by uma.moe.
- Fixed optional uma.moe costume filters so an omitted exclusion list no longer aborts a search.
- Documented a safe process-based parallelisation path for expensive pair searches and Transfer Helper scans.
- Clarified repository hygiene: tests are source code and are intentionally versioned.
- Reworked the README into a shorter operational overview and documented the planned migration from UmaExtractor to umadump.

## 1.3.0 — Ace inheritance model and online constraints

- Split scoring into dedicated future-grandparent, parent-branch and final-parent-pair modes.
- Added modern G1-only individual affinity calculations and conservative aptitude inheritance probabilities.
- Strongly prioritised starting at Distance A, with configurable Distance B compensation and diminishing returns for Distance S probability.
- Reworked white-skill scoring around real inheritance probabilities, lineage carriers and distinct-skill diversity.
- Rebalanced blue-stat value by target distance profile.
- Added required, allowed and excluded parent costume constraints to uma.moe parent searches.
- Integrated skills granted by Race Sparks using their real inheritance rates and merged duplicate race/white sources.
- Improved production-run affinity, future-grandparent saturation and detailed inheritance diagnostics.

## 1.2.0 — Configurable scoring and optimiser UX

- Added editable scoring profiles with automatic migration of older configurations.
- Added autocomplete and alphabetical sorting to Ace, parent, grandparent and preset selectors.
- Improved searchable pickers, filtering behaviour and editor section persistence.
- Added percentage and decimal weight input and clearer override status reporting.
- Fixed course-preset mapping for Ooi/Ohi.
- Recalibrated manual white-skill priorities around parent-farming rarity and practical inheritance value.

## 1.1.0 — Transfer Helper and English interface

- Added an English interface and language-aware activity log.
- Added Transfer Helper to evaluate each local veteran as both a parent and future grandparent.
- Limited cleanup analysis by default to the next five Champion Meetings and five Team Trials profiles.
- Added conservative same-costume dominance checks and four verdict levels: Keep, Likely Keep, Review and Safe Transfer.
- Added distribution-aware usefulness scoring, configurable thresholds and detailed JSON/CSV reports.
- Included in-game rank, evaluation score, stats, grandparents, context evidence and proposed replacements.

## 1.0.0 — Initial release

- Linked local veteran exports against the current `master.mdb`.
- Added parent-lineage analysis, affinity and Spark scoring.
- Added uma.moe integration for remote grandparent and parent searches.
- Added GUI and CLI workflows.
- Added project documentation and reproducible JSON/CSV outputs.
