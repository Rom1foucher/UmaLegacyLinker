# White Loop Workshop — MVP

The White Loop Workshop manages repeated parent-building runs as persistent projects. It is
deliberately distinct from the old compatibility-only "legacy loop": its primary objective is to
increase and preserve useful White Skill Spark coverage across a reusable lineage portfolio.

## Workflow

1. Link the local collection from **Local Data**.
2. Create a project and add its White Skill targets.
3. Mark at most one or two indispensable targets as **Static**; keep the remaining targets
   **Dynamic**.
4. Select the target surface, distance and running style, then the next trainee. The two parent selectors are pre-ranked against the
   project's targets; the **Recommended pair** selector proposes the best local duos
   to start with. Every entry shows the local trained ID, in-game rank and in-game
   score so the veterans can be found quickly in the collection. Apply a proposal or
   pick another ranked candidate manually.
5. Inspect the six-slot coverage and the **optimal G1 plan** shown below the skill
   table. It is the existing one-race-per-turn planner: shared parent wins are `+6`,
   one-sided wins are `+3`, and objective/calendar conflicts stay visible in the
   diagnostic. Each planned row also shows the effective surface/distance ranks and
   Independent Training win probability.
6. Analyse the transition, then mark it pending before starting the run.
7. Link the collection again after extraction.
8. Select the new descendant, verify its parent provenance and record a verdict.

When succession-trained IDs are unavailable (notably in current umadump exports), provenance is
verified from the frozen parent card, exact factor/star set and G1 signature instead.

Pending parents and active project carriers are protected automatically by Transfer Helper.
The application still never changes or transfers any in-game veteran.

## Parent recommendations

The selector ranking is intentionally explainable and local. It is a helper score, not a
probability and not a replacement for the final transition analysis:

- the White subscore uses exact direct target-factor coverage (70%), static target
  coverage (20%) and matching target stars (10%);
- when the MDB aptitude context is available, the displayed pair recommendation is
  `80% White subscore + 20% aptitude subscore`;
- the aptitude subscore is the existing probability-aware parent-pair model over the
  six visible Pink factors, using the selected surface, distance and running style;
- before a target is configured, the linked collection rank score is used as a neutral fallback;
- pair proposals use the same matcher over the two parents and their four visible grandparents,
  so the displayed `x/6 slots` value is the actual input coverage used by the engine.

The in-game score is displayed for identification and fallback ordering; it is not presented as
an inheritance probability. The trainee's character is excluded from recommendations, and pairs with the same direct
character are filtered out. The final **Analyse** action remains the authority and checks all
identities again.

## Project management

Projects are stored in `output/white_loop_projects.json`. **Save project** persists the name,
surface/distance/style profile, quality band, G1 budget/signature and targets; adding or removing a target also saves immediately.
**Duplicate** creates a clean branch with the same target/configuration setup but without carrier
protection or transition history. **Delete** removes exactly the selected project after an explicit
confirmation; deleting it also removes its Transfer Helper protection because that protection is
derived from active projects.

This makes it safe to keep one project per experiment (for example, a conservative Core loop and
an exploratory side loop) without mixing their pending transitions.

## Probability contract

The workshop does not merge unrelated probabilities into one opaque score.

- `input coverage` is the exact number of matching direct White Skill factors among the six
  selected lineage members;
- `P(acquisition)` is optional and user-provided when the skill source is known;
- `P(generation | learned)` is `20% + 2.5% × coverage` for a normal learned skill,
  `25% + 2.5% × coverage` for an ◎ skill and `40% + 5% × coverage` for a gold skill;
- `full P(generation)` is only shown when `P(acquisition)` is known;
- 1★/2★/3★ quality is projected from the selected run-quality band;
- planned input coverage uses six slots, while an extracted descendant is evaluated on its
  three-member output branch.

Race Sparks that grant the same skill can help acquisition, but they never count as copies of the
direct White Skill factor. Factor matching prioritises the exact MDB `factor_group_id`; name
matching exists only for old linked exports missing that identifier.

## Aptitudes and the G1 plan

The aptitude contexts have two distinct jobs:

- surface, distance and style all contribute to the duo recommendation through the canonical
  Pink inheritance model;
- the executable G1 plan uses only surface and distance, matching Independent Training. For every
  G1 type it starts from the trainee costume's natural rank, adds the matching Pink stars present
  on the selected two parents and their four grandparents, then applies the existing win table and
  consecutive-race penalty. A race keeps its `+3`/`+6` value only at or above the 60% cutoff.

Running style is therefore intentionally absent from the G1 cutoff even though it remains relevant
to the target-profile recommendation. This keeps White generation probability, aptitude quality and
race-win viability as separate diagnostics.

## Portfolio and history

Each saved project contains:

- target definitions and their static/dynamic policy;
- an optional G1 signature and race budget;
- frozen snapshots of active carriers;
- pending and completed transitions;
- actual outcome diagnostics, verdicts and notes.

Available outcome verdicts are **Promote to Core**, **Replace in Core**, **Keep in side branch**
and **Ignore**. Replacing a carrier archives its project snapshot but keeps the full transition
history.

## MVP boundaries

This first version plans one generation at a time and recalculates after the actual stochastic
outcome. It does not yet:

- infer every support-card, character-event or scenario-specific acquisition rate;
- optimise a multi-generation search tree;
- automatically rank the complete portfolio on a Pareto frontier;
- add future signature-only G1 races that are absent from both selected parents;
- import or synchronise remote carriers directly from the Workshop page.

These omissions are explicit: an unknown acquisition probability stays unknown instead of being
replaced by a fabricated estimate.

## Farming par batch et reprise automatique (schema v2)

À partir du schéma de projet `2`, le Workshop distingue trois états qui étaient confondus dans le MVP :

1. **draft de transition** : trainee + Parent 1 + Parent 2 + dernière analyse. Il est sauvegardé dès la configuration et restauré après redémarrage sans protéger les parents ni prétendre qu'une run est en cours ;
2. **batch actif** : recette gelée explicitement lancée. Les parents sont protégés et les identifiants de vétérans déjà présents au lancement forment la baseline ;
3. **runs du batch** : chaque nouveau vétéran correspondant au costume/personnage planifié et aux deux parents gelés est rattaché automatiquement au batch.

Un batch reste actif après l'analyse ou le verdict d'un résultat. Il doit être clôturé explicitement. Cette sémantique permet de farmer plusieurs Independent Trainings avec la même recette et d'obtenir des statistiques empiriques cohérentes. Un verdict de run devient immuable une fois enregistré afin de conserver une chaîne d'audit cohérente avec les mutations du Core ; corriger un verdict déjà appliqué demande donc une opération dédiée future plutôt qu'une réécriture silencieuse.

### Détection automatique

Après chaque nouvelle liaison de la collection, le Workshop examine uniquement les vétérans qui ne faisaient pas partie de la baseline du batch et qui n'ont pas déjà été rattachés à un batch. Un résultat est auto-importé si :

- le `card_id` de la trainee correspond, avec `chara_id` en fallback historique ;
- les deux parents correspondent par IDs locaux ;
- ou, lorsque les IDs de succession manquent, les deux fingerprints gelés correspondent aux snapshots.

`mismatch` et `unknown` ne sont jamais auto-importés. L'ajout manuel reste disponible comme outil de diagnostic.
L'UI refuse également deux batches actifs portant exactement le même costume trainee et les mêmes deux parents dans deux projets différents : leur provenance serait indiscernable lors d'une détection automatique.

### Acquisition et forme du skill

Le linker conserve désormais `skill_array` sous une forme résolue `learned_skills`. Pour chaque skill :

- `skill_id` ;
- `group_id` MDB ;
- nom ;
- niveau extrait ;
- rareté MDB ;
- forme normalisée `normal`, `single_circle`, `double_circle` ou `gold`.

Le matching d'une cible White utilise d'abord le groupe MDB. Une cible normale peut donc être comptée comme acquise si la run a acheté sa variante ○, ◎ ou gold. Pour la comparaison théorie/observé, `○` utilise le modèle de génération normal, `◎` le modèle historique `circle` (25 % de base) et gold le modèle gold. Si l'export ne contient pas les skills appris, `learned_skills_known = false` et l'acquisition reste `unknown` : un facteur White généré n'est jamais utilisé comme preuve rétroactive d'acquisition.

### Statistiques d'un batch

Les métriques sont conservées séparément pour chaque cible :

- taux d'acquisition sur les runs où la liste de skills est observable ;
- répartition normal / ○ / ◎ / gold ;
- taux de génération du facteur sur toutes les runs ;
- taux de génération conditionnellement à l'acquisition ;
- taux de facteurs ≥2★ et 3★ ;
- comparaison du taux conditionnel observé au modèle théorique gelé dans le plan.

Le résumé du batch expose aussi les runs avec au moins un facteur cible, au moins un facteur cible ≥2★, toutes les Static générées, les verdicts humains et le taux de promotion sur les runs revues. Il n'existe volontairement pas de « score de succès » opaque unique.

## Planning G1 visuel

La page de planification réutilise `RaceCalendarWidget`, la même brique que l'affichage de lignée. Le planning optimal est présenté sur les trois années avec les cartes de courses, les badges +3/+6, les objectifs, les courses non placées et les warnings de séries. Le tableau compact reste disponible sous le calendrier comme vue détaillée ; aucun second solveur G1 n'est introduit.
