# Search workspace redesign notes

Companion to `WEIGHTS_UI_DESIGN.md`. Covers the second redesign pass on the
unified Search page introduced in `57e69d0` ("reworked and centralise UI").

## Why the centralised page still fights the user

The centralisation solved the right problems: one shared lineage context, both
sources visible, results embedded instead of floating windows. The remaining
friction is structural, and every recent layout fix is a symptom of it:

- **Single-column stacking.** `SearchPage` stacks header → context panel →
  two source cards → results. The configuration zone consumes a fixed slice of
  height on every visit, while the results — what the user actually reads —
  live in the leftover. The compact button styling hack, the two-column Spark
  card viewport work and the narrow-width fix in `0a8f06f` all fight the same
  vertical budget.
- **State hidden behind modal chains.** Advanced race conditions exist only
  inside `RaceConditionsDialog`; uma.moe options sit two levels deep
  (button → `QMenu` → `OnlineSearchOptionsDialog`). NN/g's progressive-
  disclosure guidance caps useful disclosure at **two levels** and warns that
  hiding frequently needed settings creates "disclosure debt": an interaction
  tax paid on every visit, plus invisible non-default state.
- **Destructive result switching.** The `result_stack` makes the six result
  kinds (`local:pairs`, `local:branches`, `local:future`,
  `uma.moe:online_parent`, `uma.moe:online_grandparent`,
  `local:online_grandparent`) mutually exclusive. Running one family visually
  destroys the previous one; the user cannot tell whether older results still
  exist, and the single `OnlineResultsPane` even makes remote-parent and
  remote-GP results overwrite each other.
- **Seven verbs, no workflow.** Five run buttons plus two menu buttons spread
  over two cards form a command surface, not a path. Selecting *what to look
  at* and *triggering a computation* are fused into the same buttons.

## Guidelines consulted

Interaction patterns, not visual copies:

- [NN/g — Progressive Disclosure](https://www.nngroup.com/articles/progressive-disclosure/):
  at most two disclosure levels; split by real frequency of use; everything
  frequently needed stays on level 1; secondary levels need clear information
  scent.
- [NN/g — Tabs, Used Right](https://www.nngroup.com/articles/tabs-used-right/):
  tabs are for alternative related views of the same object — exactly what
  result families of one shared context are. Position them directly above
  their panel, put the highest-use tab first and selected by default, keep
  labels short. Caveat: tabs are poor when users must compare panels
  simultaneously (addressed under "Deferred").
- [NN/g — Accordions on Desktop](https://www.nngroup.com/articles/accordions-on-desktop/)
  and [Accordions for Complex Content](https://www.nngroup.com/articles/accordions-complex-content/):
  collapsing reduces visibility and adds interaction cost; headers must carry
  the information scent; essential information must never exist *only* inside
  a collapsed panel. This is why every collapsed section below keeps its
  effective values readable in the header.
- [NN/g — Applying Filters](https://www.nngroup.com/articles/applying-filters/):
  batch filtering with an explicit apply action fits expensive operations.
  Rail sections here parameterise an explicit **Run**; they never trigger
  computation themselves, and staleness badges bridge the gap between "edited"
  and "applied".
- [NN/g — Visibility of System Status](https://www.nngroup.com/articles/visibility-system-status/)
  (usability heuristic #1): the per-family state badges (empty / running /
  fresh / stale / loaded) exist to answer "what am I looking at, and does it
  still match my configuration?" without the user reconstructing it.
- VS Code / JetBrains settings precedents already recorded in
  `WEIGHTS_UI_DESIGN.md`: visible modified state, per-item reset, search over
  hierarchy. Rail sections reuse the same modified-dot + reset vocabulary so
  both pages speak one language.

## Target layout

```
┌──────────┬──────────────────────────────────────────────────────────────┐
│ app      │  Search                                                      │
│ sidebar  │ ┌───────────┬────────────────────────────────────────────────┤
│          │ │ CONTEXT   │ Ace → Target · CM17 Ooi Dirt 2000 · Late …     │
│          │ │ RAIL      │ ┌────────┬─────────┬──────────┬───────┬──────┐ │
│          │ │           │ │Paires ●│Parents ○│GP futurs◐│moe·P ○│moe·GP│ │
│          │ │ ▾ Objectif│ ├────────┴─────────┴──────────┴───────┴──────┤ │
│          │ │ ▸ Course… │ │ [Lancer] [Charger] [Exporter] [Lignée]  ⋯  │ │
│          │ │ ▸ Condit… │ │ computed-with summary · badge détail       │ │
│          │ │ ▸ moe Réc…│ │ ┌──────────────────────┬─────────────────┐ │ │
│          │ │ ▸ moe Par…│ │ │ table (sortable)     │ detail ≥ 520 px │ │ │
│          │ │ ▸ moe GP  │ │ │                      │ (or hidden)     │ │ │
│          │ │           │ │ └──────────────────────┴─────────────────┘ │ │
│          │ │ [⇤]       │ └────────────────────────────────────────────┘ │
└──────────┴─┴───────────┴────────────────────────────────────────────────┘
```

Badge legend: `●` fresh · `◐` stale · `○` empty · `⟳` running · `▣` loaded
from disk (freshness unknown).

Three rules govern the geometry:

1. **Results own the height.** The main area contains only the one-line
   context ribbon, the family tab bar, the active family's toolbar and its
   pane. Nothing configuration-shaped remains above the results.
2. **The rail owns the configuration.** Expanded width ≈ 300 px, collapsible
   to a ~44 px icon strip. Below a total window width threshold (proposal:
   1360 px) the rail starts collapsed; the user's manual choice is persisted
   in the store and wins afterwards.
3. **The detail viewport never renders between 0 and 520 px.** The rich-text
   Spark/diagnostic HTML was hardened for a ≥520 px viewport
   (`ResultPane.detail.setMinimumWidth(520)`, the two-column Spark card
   work). Instead of ever squeezing it, the table|detail splitter allows
   collapsing the detail side entirely (splitter handle or a toolbar toggle),
   and restores it at ≥520. This keeps the 1120 px minimum window honest:
   rail collapsed + detail hidden always leaves the table a full-width lane.

## Context rail specification

Two disclosure levels total: the rail itself (level 1, headers always
readable) and an expanded section (level 2). No third level — no menus, no
state-holding dialogs behind sections.

Every section header shows, left to right: title · **effective-value
summary** · modified dot when any value differs from default · reset action
on hover/expand. A collapsed section is a summary, never a hiding place.

| Section | Contents (mapped from current code) | Summary example |
| --- | --- | --- |
| **Objectif** (default expanded) | Ace, future parent, Top N — today's `objective` grid | `Oguri (Noël) → Tamamo · Top 30` |
| **Course & profil** | surface / distance / style / preset / racecourse — today's compact `LineageRaceEditor` panel | `CM17 · Ooi Dirt 2000 · Late Surger` |
| **Conditions statiques** | rotation, season, weather, ground, custom-scoring toggle, priorities file, course-overrides file — today's `advanced` grid, sole content of `RaceConditionsDialog` | `Été · Pluie · Lourd · scoring perso` |
| **uma.moe · Récupération** (shared) | `uql_*` retrieval flags, pink min stars, lineage blue/pink minima, costume allow/exclude lists | `Cohorte Surface · pink ≥ 3★ · 12 exclus` |
| **moe · Parents distants** | pairing (auto / fixed local **parent**), pools, fetch limit, import path, required costume | `appariement auto · 2000 candidats API · 100×100` |
| **moe · Grands-parents distants** | pairing (auto / fixed local **GP1**), pools, fetch limit, import path, opposing parent (local/external JSON), G1 budget, win-probability cutoff | `appariement auto · 500 candidats API · G1 20` |

Notes:

- `CardFilterDialog` **stays**. A modal *picker* for choosing items from a
  long searchable list is a selection tool, not hidden state — its outcome is
  summarised in the section header (`Autorisés (3)`). The rule being enforced
  is "state never lives only in a dialog", not "no dialogs".
- uma.moe API base/key remain in Settings; that separation from per-search
  filters is deliberate and correct today.
- The rail replaces `RaceConditionsDialog` and `OnlineSearchOptionsDialog`
  entirely; both classes are deleted. Their persistence moves behind new
  `AppContext` methods (see staleness model) so edits emit signals instead of
  writing `context.store` directly from a dialog.

### Shared versus per-mode storage

The two per-mode dialogs implied independent settings while persisting mostly
**shared** keys: `uma_moe_auto_pairs`, `uma_moe_fixed_gp_id`,
`uma_moe_local_pool`, `uma_moe_remote_pool`, `uma_moe_limit` and
`uma_moe_response_path` are written by both dialogs and read back by
`start_online()` regardless of mode. Editing the parent filters therefore
silently rewrites the grandparent search's pairing, and `uma_moe_fixed_gp_id`
is outright overloaded: the same stored veteran means *fixed local parent* in
one mode and *fixed local GP1* in the other — two different roles with
different sensible candidates. The confusion is not a presentation bug; the
presentation and the storage disagree, so one of them has to change.

The split follows what each setting *describes*:

- **Describes the target build → shared.** The `uql_*` retrieval preferences,
  pink minimum, lineage blue/pink minima and the costume allow/exclude lists
  constrain which remote candidates are acceptable at all, and derive from the
  one shared context exactly like surface or distance. They live once, in the
  common Récupération section, explicitly labelled as shared. The costume
  lists in particular were *already* consumed by both searches while only the
  parent dialog could edit them — the shared section makes that visible rather
  than changing it. (If real usage ever wants different lineage minima per
  mode, splitting them later is mechanical.)
- **Describes one search's strategy → per mode.** Pairing mode, the fixed
  local veteran, both pool sizes, the fetch limit and the import path are
  decisions about *this* search: a fixed parent is not a fixed GP1, and a
  2 000-candidate parent sweep does not imply the same appetite for a GP2
  scan. New keys `uma_moe_parent_*` / `uma_moe_gp_*` replace the shared ones.
- **Migration.** On first read each new key falls back to its legacy shared
  value, so existing configurations keep behaving identically until the user
  edits one side; only the new keys are written afterwards. The legacy keys
  stay in the store as inert history.

### The mode is the tab

An explicit parent/grandparent mode switch on the page was considered and
rejected: the family tabs already encode that choice, and a second selector
for the same state guarantees desynchronisation — a "grandparent" switch over
a visible parent-results tab leaves Run ambiguous. Instead, the active tab
*is* the mode, and it drives the rail:

- the three context sections and the shared Récupération section are always
  present;
- when an online tab becomes active, its mode section expands and the sibling
  mode section collapses — never hides. `SummarySection` keeps the collapsed
  sibling's effective values readable, so switching modes filters the
  *controls* in view without making any state invisible or moving sections
  around (spatial stability);
- when a local tab is active, both mode sections rest collapsed; they remain
  editable ahead of a future online run;
- the existing `uma_moe_search_mode` key simply tracks the last active online
  family, which also keeps JSON imports defaulting to the right mode.

Until the tabs land, the two mode sections simply coexist in the rail;
expanding one is the interim mode gesture, and nothing needs to be unlearned
when the coupling arrives.

- Later polish (not in scope now): when an online tab is active, softly
  highlight its relevant rail sections.

## Result families as tabs

Five tabs, ordered by frequency, first selected by default (NN/g):

| Tab (FR / EN) | Pane | Covers kind(s) |
| --- | --- | --- |
| Paires / Pairs | `ResultPane("pair")` | `local:pairs` |
| Parents / Parents | `ResultPane("branch")` | `local:branches` |
| GP futurs / Future GPs | `ResultPane("future")` | `local:future` |
| moe · Parents / moe · Parents | `OnlineResultsPane` #1 | `uma.moe:online_parent` |
| moe · GP / moe · GPs | `OnlineResultsPane` #2 | `uma.moe:online_grandparent`, `local:online_grandparent` |

- **Each tab keeps its last result.** Two `OnlineResultsPane` instances end
  the remote-parent/remote-GP overwrite. `local:online_grandparent` (local GP
  pairs) stays a source toggle inside the moe·GP toolbar — same family, same
  options, low frequency; the computed-with summary and badge name the
  variant. (Alternative rejected for now: a sixth tab — weak label scent,
  more chrome for a rare flow.)
- **Selecting ≠ computing.** The tab shows; the toolbar's primary **Lancer**
  computes the visible family with the current context. `Ctrl+Enter` runs the
  active family. This dissolves the seven-button command surface into one
  consistent verb per view.
- **Per-tab toolbar**: Lancer · Charger le dernier (per-family
  `load_latest`) · family-specific actions (Exporter on Paires, Importer JSON
  + local-GP-pairs toggle on moe·GP, Lignée where available) · Ouvrir le
  dossier. The global load/open buttons disappear.
- **Per-tab empty state**: one sentence on what the family answers + the Run
  button. Replaces the single generic placeholder and restores information
  scent for first-time club users.
- **Single-worker reality**: `MainWindow` runs one `FunctionWorker` at a
  time. While busy, every Lancer disables, the running tab shows `⟳`, other
  tabs keep their fresh/stale badges, cancel stays in the status bar.
  Queueing or concurrent runs are out of scope (engine `cancel_event` design
  and output-directory write collisions would need their own pass).
- Tab labels must pass the layout audit's button-text-width check in both
  languages; the proposals above are sized for that.
- **Run labels carry the verb only** ("Classer", "Rechercher"). The tab
  already names the subject, and a full sentence crowds the toolbar out of a
  1120 px workspace.
- **The rail yields to the width.** Below the threshold the rail and a result
  pane cannot both hold their minimum, and a splitter resolves that by
  squeezing everything: clipped toolbars, a rail scrolling sideways behind a
  hidden bar. The rail therefore stays closed while the window is narrow and
  reopens from the remembered preference once there is room. Rail sections
  also lay out in one column when hosted, so their own minimum fits.

## Staleness model: per-family input fingerprints

A global "context revision counter" would mark local results stale when only
a uma.moe fetch limit changed. Instead each family gets a **fingerprint of
exactly the inputs that feed it**:

```
fingerprint(kind) = sha1(canonical_json({
  lineage:  LineageContextState.normalized() as dict,
  scoring:  digest(active scoring overrides content),
  skills:   digest(skill priorities file content),
  courses:  course-overrides file path + mtime,
  master:   master.mdb path + mtime,
  data:     data.json path + mtime,          # all families use the local pool
  options:  family-specific store keys       # online families only:
            #   moe·Parents → uma_moe_required_parent_card_id,
            #     *_allowed/_excluded_card_ids, pools, limit, uql_*
            #   moe·GP      → uma_moe_auto_pairs, fixed_gp_id, pools, limit,
            #     opposing_*, parent_g1_budget, g1_win_probability_cutoff, uql_*
}))
```

- Computed by a new `AppContext.family_fingerprint(kind)`; panes store the
  fingerprint at result application (`set_rows` / `set_result` gain the
  parameter — they already receive the profile).
- Badges refresh on: `lineage_changed`, a new `online_options_changed` signal
  (emitted by the new `AppContext.update_online_options(...)` that replaces
  direct `store.update` writes from the dialog), `configuration_changed`,
  page shown / window activated (cheaply catches external edits to the
  overrides files via mtime/digest), and task completion.
- `load_latest` results carry no known fingerprint → badge `▣` "chargé"
  (loaded, freshness unknown) rather than pretending freshness. Honest state
  beats a guess.
- The existing `_last_profile` / `profile_summary` machinery stays as the
  human-readable "computed with" line; the fingerprint is its machine twin.

## Component inventory

New (in `ui_qt/components.py` unless noted):

- `SummarySection` — collapsible section with summary label, modified dot and
  reset; either extends `CollapsibleSection` or supersedes it.
- `FamilyTabBar` + `FamilyState` badge rendering (empty/running/fresh/stale/
  loaded).
- `ui_qt/result_panes.py` — extraction target for `ResultPane`,
  `OnlineResultsPane`, `CardFilterDialog` once `pages_search` rewires imports.

Deleted:

- `RaceConditionsDialog`, `OnlineSearchOptionsDialog`, the two source cards,
  `result_stack` + generic placeholder, both `QMenu` chains.
- Dead `OptimizerPage` / `OnlinePage` classes (not in `_nav_order` since the
  centralisation; only referenced by source-slicing tests).

## Migration plan

Each phase lands independently, is validated by `pytest tests/`,
`tests/check_i18n.py`, and a reviewed `layout_audit` re-baseline, and ships
with its i18n additions (French source strings + English entries).

**P1 — Geometry** *(landed)*. Rail/main `QSplitter`, the first three
`SummarySection`s, `RaceConditionsDialog` dissolved, rail collapse with
persistence and a width threshold. Source cards and result frame untouched in
the main column.

**P2 — Options dissolution** *(landed)*. Move `OnlineSearchOptionsDialog` content into
the three uma.moe rail sections behind `AppContext.update_online_options`,
applying the shared/per-mode storage split and its legacy-key migration; keep
`CardFilterDialog` as picker; port the dialog's validation (required ∉
excluded, required ∈ allowed) to inline section validation; delete the
dialog. Pulled ahead of the tab work because it fixes the live confusion
(per-mode entry points over shared storage) and shrinks `pages_search.py`
before the riskier rewiring touches it. The interim mode gesture is simply
expanding one of the two mode sections. Audit: `search-options-parent` /
`search-options-grandparent` scenarios become rail-section captures.

**P3 — Families** *(landed)*. Replace `result_stack` + source cards + the five run
buttons and two menus with `FamilyTabBar`, five persistent panes (two
`OnlineResultsPane` instances) and per-tab toolbars with empty states. Couple
the two mode sections to the active online tab (expand/collapse, never hide).
Extract panes to `ui_qt/result_panes.py`, delete dead `OptimizerPage` /
`OnlinePage`, update the source-slicing assertions in `test_qt_ui.py` and the
audit imports. Riskiest phase: `start_local` / `start_online` /
`_local_done` / `_online_done` / `_show_results` rewire onto tabs.

**P4 — State visibility.** Family fingerprints, badges, `▣` loaded state,
`Ctrl+Enter`, detail-pane collapse toggle if not already landed with P1's
splitter work.

## Deferred, with reasons

- **Side-by-side family comparison** (the NN/g tab caveat): tab persistence
  already turns comparison into free switching instead of re-running; a
  proper split view doubles the ≥520 px detail problem and the audit matrix.
  Revisit only if switching proves insufficient in real sessions.
- **Concurrent computations**: single-worker constraint documented above.
- **Ctrl+K command palette**: transversal to the whole app, deserves its own
  registry design; nothing in this redesign blocks it.
- **Free docking (`QDockWidget`)**: layout persistence complexity and a
  combinatorial audit matrix for marginal benefit over fixed splitters.

## QA impact summary

- `layout_audit`: 3 dialog scenarios replaced by rail-state variants; full
  screenshot re-baseline at 1120×720, 1366×768, 1600×900 with rail expanded
  and collapsed; button-width checks now also police tab labels in FR and EN.
- `test_qt_ui.py`: source-slicing assertions re-anchored after the
  `result_panes.py` extraction; new assertions worth adding: every
  `SummarySection` exposes a non-empty summary when collapsed; badge state
  transitions on fingerprint divergence.
- `i18n.py`: all new labels/summaries as French sources with English
  translations; `check_i18n` gates every phase.
