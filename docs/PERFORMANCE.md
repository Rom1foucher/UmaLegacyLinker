# Performance and parallelisation design

UmaLegacyLinker already runs long GUI operations outside Tk's main thread, which keeps the interface responsive. That thread does not, however, make CPU-bound scoring use multiple cores because most of the workload is Python code constrained by the GIL.

## Main hotspots

1. Final parent-pair searches: Cartesian products of pre-ranked parent branches.
2. uma.moe automatic pairing: local pool × remote pool, followed by detailed scoring.
3. Transfer Helper: every veteran evaluated across every Ace/profile/role context, plus same-costume dominance comparisons.

## Recommended implementation

Use `concurrent.futures.ProcessPoolExecutor`, not a larger thread pool.

- Initialise one `AffinityResolver` and one read-only SQLite connection per worker process. SQLite connections and resolver instances must never be shared between processes.
- Pass coarse batches of pair indexes, typically 256–1,024 pairs per task, instead of serialising a full lineage payload for every pair.
- Keep immutable candidates, scoring configuration and lookup tables in process-local globals created by the executor initializer.
- Return compact ranking summaries from workers. Recompute or retain full diagnostics only for the final top-N results to reduce inter-process transfer costs.
- Use a configurable worker count, with a conservative default such as `max(1, min((os.cpu_count() or 2) - 1, 8))`.
- Preserve a serial fallback for small workloads, frozen builds and worker failures.
- Merge results with stable secondary keys so serial and parallel executions produce the same order.

## Windows and packaged builds

The application targets Windows and may be packaged with PyInstaller. The executable entry point must call `multiprocessing.freeze_support()`. Worker functions must remain at module scope and must not capture Tk widgets, callbacks, locks or open database handles.

Progress should be reported by completed batches through the existing application queue. Cancellation can be added later through a shared event checked between batches.

## Suggested rollout

1. Parallelise uma.moe pair summaries first. It is the most isolated Cartesian workload.
2. Apply the same batch executor to local final-parent pairs.
3. Parallelise Transfer Helper by profile/context chunks, then deterministically merge each veteran's maxima, percentile evidence and dominance accumulators.

Transfer Helper is the most delicate stage because percentile distributions and dominance relations are global. Parallel workers should emit raw per-context scores; verdicts and final dominance decisions should remain in the parent process.

## Validation

Before enabling parallel mode by default:

- compare serial and parallel JSON outputs on fixed fixtures;
- require identical top-N identities and scores within floating-point tolerance;
- benchmark process startup separately from scoring time;
- keep serial execution for workloads below a measured break-even threshold;
- test both source execution and the packaged Windows executable.
