# Architecture

This is the implementation contract for the 1.9.0 tree. [Scoring](SCORING.md)
owns formulas and ranking semantics; [configuration](SCORING_CONFIGURATION.md)
owns profiles; [releasing](RELEASING.md) owns build and publication commands.
Paths below are relative to the repository root.

## Modules and boundaries

| Area | Code | Responsibility |
| --- | --- | --- |
| Entry points | `qt_app.py`, `cli.py` | Desktop startup and headless commands; multiprocessing main guards |
| Services | `uma_legacy_linker/application.py` | Settings, request snapshots, linking/catalogue/scoring orchestration |
| Inputs | `legacy_linker.py`, `skill_catalog.py`, `course_presets.py` in `uma_legacy_linker/` | MDB/export resolution and generated catalogues |
| Ranking | `parent_optimizer.py`, `uma_moe.py`, `g1_race_planning.py` in `uma_legacy_linker/` | Parent/GP scoring, remote retrieval and schedules |
| Solver execution | `solver_runtime.py`, `solver_math.py`, `solver_pairs.py`, `solver_parallel.py` in `uma_legacy_linker/` | Search-local caches, prepared pair inputs, ordered workers |
| Collection analysis | `uma_legacy_linker/transfer_helper.py`, `transfer_portfolio.py`, `spark_protection.py` | Matched-Ace evidence, bounded minimum portfolios and inheritance protection |
| Transfer explanations | `uma_legacy_linker/transfer_comparison.py`, `ui_qt/transfer_comparison_dialog.py` | Frozen scoring-model reconstruction and component-level copy comparisons |
| Shell | `ui_qt/main_window.py`, `context.py` | Lazy pages, navigation, shared state, task lifecycle |
| Results | `ui_qt/result_families.py`, `result_panes.py`, `presentation.py`, `lineage_view.py` | Independent result views and backend-produced explanations |
| Provenance/comparison | `uma_legacy_linker/output_history.py`, `result_comparison.py`; `ui_qt/provenance.py`, `comparison_dialog.py` | Retained generations, stable identities, original-value comparison |
| Configuration UI | `ui_qt/lineage_settings.py`, `online_options.py`, `pages_weights.py` | Shared context, remote constraints and minimal overrides |
| Resources | `uma_legacy_linker/paths.py`, `resources/` | Source/frozen paths, bundled profiles and icons |

`uma_legacy_linker` has no Qt dependency. UI pages assemble requests and render
results; they do not implement a second score formula. `ui_qt/core.py` and the
old separate optimizer/online pages are no longer modules. Legacy navigation
keys `optimizer` and `online` redirect to Search.

## Desktop task lifecycle

`MainWindow` constructs pages on demand and allows one global operation at a
time. Pages emit `task_requested`; the shell supervises progress, errors and
cancellation. `FunctionWorker` runs ordinary I/O preparation in a Qt pool thread.
Heavy Search and Transfer Helper requests use `ProcessTask` and
`ProcessFunctionWorker` instead.

The request path is deliberately layered: the Qt shell submits work to a
thread supervisor, the supervisor starts an isolated backend process, and the
backend performs evaluation either sequentially or through the ordered solver
pool. Results, progress and errors return through the same supervisor boundary;
Qt objects never enter the scoring process.

`uma_legacy_linker/backend_process.py` runs a picklable callable and sends typed
`log`, `progress`, `result`, `error` or `cancelled` messages through a pipe. The
supervisor performs a pickle preflight, polls IPC and emits Qt signals. Qt
objects, live SQLite connections and closures containing GUI state must not
cross this boundary. The CLI calls the same services without a GUI supervisor.

Cancellation first signals the backend event. Scoring and G1 loops propagate a
cooperative checkpoint, including a shared monotonic 10 ms scheduling check.
An unresponsive backend is terminated after the supervisor's one-second grace
period. Solver children separately watch their owner's pipe and exit if that
backend disappears. Completion and error paths close/reap processes and pipes.
`qt_app.py` calls `freeze_support()` before desktop startup for frozen Windows
spawn handling.

## Solver execution

Normal searches enter an optimized `SolverRuntime` unless a caller already owns
one. Its `ContextVar` scope owns numeric caches and diagnostics for that search;
each child worker has its own runtime. `SolverRuntime(False)` selects the
canonical evaluator for regression comparisons.

Prepared parent-pair evaluation caches factor sources, skill relevance, failure
probabilities, branch affinity inputs and G1 sets. It preserves canonical
insertion and floating-point accumulation order. Retained results are rebuilt
with canonical details. Curve and G1 transition caches avoid repeating numerical
work; they do not replace the planner's budget/streak state or scoring model.

| Environment variable | Behavior |
| --- | --- |
| `ULL_SOLVER_WORKERS=auto` or `0` (default) | Up to four workers, bounded by logical CPU count and eligible pair count |
| `ULL_SOLVER_WORKERS=1` | Optimized sequential execution |
| `ULL_SOLVER_WORKERS=N`, positive integer | Explicit worker count, bounded by pair count; small-pool thresholds are bypassed |
| `ULL_G1_RANKING=e2` (default) | Generic GP-pair screening followed by exact shortlist rescoring |
| `ULL_G1_RANKING=exact` | Exhaustive exact GP-pair scoring, retaining the all-pairs CSV |

Automatic pooling starts at 2,000 parent pairs or 200 GP pairs. Explicit counts
are not capped at four. Invalid settings raise errors when the relevant search
reads them. These variables apply to processes launched after setting them;
they are not persistent profile fields.

The solver pool handles local final-parent pairs, local/remote parent pairs and
GP pairs. This policy does not parallelize every loop in the application:
Transfer Helper has desktop process isolation but no solver-pool dispatch.
Workers receive serializable affinity/weight snapshots and then pair indices.
Batches are consumed in enumeration order, with bounded in-flight work, so
completion timing cannot reorder exact ties. No pool survives the search.

Generic E2 screening runs in those same workers. Exact Standard rescoring of the
shortlist runs in the coordinator; only finalists receive full Standard and
Trackblazer details. Parent-pair searches and contextual GP searches remain
exact. [The scoring contract](SCORING.md#104-generic-gp-screening-and-exact-reranking)
defines selection limits and CSV/JSON semantics.

Runtime diagnostics include worker policy, batch counts, reaping status,
`g1_estimator_calls`, `g1_solver_calls`, screening and reranking time. They are
in-memory execution statistics, not a promised standalone benchmark export.
Production does not write prototype captures. Historical timing numbers do not
establish performance or top recall for the current tree; reproduce with the
same inputs, profiles, candidate limits, mode and worker count.

## Search state and presentation

Search has one shared Ace/target-parent/race context and five persistent result
families: local pairs, local branches, individual future GPs, online parents and
online GP pairs. Each family owns its pane and latest result. Selecting a family
does not launch a search. Its fingerprint includes only inputs consumed by that
family. Loaded results remain explicitly loaded; they are not guessed current.

The context rail uses summaries and modified indicators to expose effective
settings when collapsed. Shared retrieval settings and per-mode options have
separate storage keys with migration from older keys. UI-only preferences,
including zoom, splitters, sorting and disclosures, do not affect score inputs.

Result details use backend scores, viability and source records. Comparisons
retain both original datasets and show `right - left`; cross-family and
unidentifiable cross-run matches are rejected. Veteran identity is costume plus
evaluation score; technical training IDs remain keys/tooltips. Independent
75–200% zoom transforms both lineage/calendar painting and pointer hit testing.

Construct child controls with a parent before calling `setVisible(True)`.
Otherwise Qt can create an unintended native top-level window before layout
insertion. Initial Search option/result refreshes are timer-scheduled; this is
not a claim that every refresh operation is asynchronous.

## Inputs, persistence and resources

Collection/MDB inputs are read-only. The linker checks a versioned manifest and
SHA-256 fingerprints to distinguish ready, stale and missing generated data.
Effective scoring profiles and generated catalogues live in the selected output
directory. Main Search/Transfer JSON writes retain one `.prev` predecessor and
replace the current file atomically. This is one-generation history, not a
multi-version database. Provenance displays generation, schema, source and
available input hashes; absent hashes remain absent.

`SettingsStore` uses `%APPDATA%/UmaLegacyLinker` on Windows and
`${XDG_CONFIG_HOME:-~/.config}/UmaLegacyLinker` elsewhere. A remembered API key
uses a separate `uma_moe_api_key.dat`; Windows DPAPI protects it for the current
account, while non-Windows storage relies on restricted filesystem permissions.
`UMA_MOE_API_KEY` takes precedence when set. Keys are not written into `config.json`.

`app_base_dir()` is the source root or executable directory; `resource_base_dir()`
is source `resources/` or frozen `_MEIPASS/resources/`. The `.spec` packages the
four default JSON files, vendored SVGs, third-party notices and optional branding.
Application branding uses a separate `resources/branding/app.ico` or `app.png`;
see [application branding](RELEASING.md#application-icon).

GameTora artwork uses one application-owned `ImageRepository` with asynchronous
network requests, URL validation and bounded disk cache. Cached image decoding
and painting occur on the GUI thread. Failed/missing images leave text and score
interpretation available. Artwork does not affect scoring.

## Validation and maintenance

- Solver changes: compare canonical, optimized sequential and spawned results;
  preserve exact sort values, stable ties and exported details in exact mode.
- E2 changes: compare finalists against an exhaustive oracle on the same eligible
  pool, check shortlist/export counts, cancellation and deterministic ties.
  Fixture equality is not proof of global recall on arbitrary data.
- Process changes: exercise cancellation, failure/crash, backend termination and
  Windows frozen startup. A Linux test pass does not validate Windows packaging.
- UI changes: use runtime tests, bilingual audit and the Windows layout audit;
  isolated runtime tests avoid shared-interpreter Qt teardown failures.

No live workflow depends on the old inferred OpenAPI-operation mapper, vertical
scroll-height helper or result-family callable factory. The old Transfer classifier (used only by
old tests), redundant rankings reader and unused Spark-total helper are also
removed; their useful regression checks now target the production paths. Umalator's CLI diagnostic, navigation/settings migrations and lineage
export helpers remain supported; their names alone do not make them dead code.

The README introduces the application; `USER_GUIDE.md` covers operation,
`SCORING.md` defines the model and `SCORING_CONFIGURATION.md` covers overrides.
The old UI, performance and skill-priority pages have been consolidated into
these contracts rather than retained as parallel references.
