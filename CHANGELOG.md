# Changelog

This project uses feature-level semantic versioning. Small internal iterations are consolidated into the nearest meaningful release instead of receiving their own public version.

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
