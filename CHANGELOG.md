# Changelog

This project uses feature-level semantic versioning. Small internal iterations are consolidated into the nearest meaningful release instead of receiving their own public version.

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
