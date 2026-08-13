# UmaLegacyLinker — White Loop Workshop batch tracking upgrade

Date : 2026-08-13
Base attendue : UmaLegacyLinker v1.7.2 avec le patch `UmaLegacyLinker-v1.7.2-white-loop-workshop-mvp.patch` déjà appliqué.

## Ce que contient l'upgrade

- persistance automatique du draft de transition (trainee + Parent 1 + Parent 2 + dernière analyse), sans lancer implicitement un batch ;
- migration du sidecar White Loop `schema_version 1 -> 2` lors de la prochaine sauvegarde ;
- réutilisation de `RaceCalendarWidget` pour afficher le planning G1 optimal visuellement dans le Workshop ;
- transformation d'une transition active en batch pouvant recevoir plusieurs runs ;
- détection automatique des nouveaux descendants après relink de la collection, avec déduplication par `trained_chara_id` et contrôle trainee + parents/provenance ;
- baseline des vétérans présents au lancement du batch pour ne pas importer des résultats historiques ;
- propagation de `skill_array` par `legacy_linker.py` vers `learned_skills`, avec `learned_skills_known` pour conserver `unknown` lorsque la source n'est pas observable ;
- matching des acquisitions par `group_id` MDB afin de reconnaître les variantes ○ / ◎ / gold du même skill cible ;
- journal par run : rank/score, skills acquis et forme, factors cibles générés et étoiles, provenance, verdict ;
- statistiques par cible : acquisition, distribution des formes, génération conditionnelle, génération globale, >=2★, 3★, théorie et écart observé ;
- métriques batch séparées (pas de score de succès arbitraire unique) ;
- verdict attaché au run sans fermer le batch ; fermeture explicite du batch ;
- verdict déjà appliqué rendu immuable pour préserver les mutations du Core ;
- protection Transfer Helper conservée pour les parents d'un batch actif et les carriers actifs ;
- garde-fou UI empêchant deux batches actifs indiscernables (même costume trainee + mêmes parents) dans deux projets différents ;
- compatibilité maintenue pour `complete_transition()` : l'ancien chemin ajoute un run puis clôture le batch.

## Application sur une installation où le MVP est déjà présent

PowerShell :

```powershell
git status --short
git apply --check .\UmaLegacyLinker-v1.7.2-white-loop-batch-tracking-upgrade.patch
git apply --index .\UmaLegacyLinker-v1.7.2-white-loop-batch-tracking-upgrade.patch
```

Bash :

```bash
git status --short
git apply --check ./UmaLegacyLinker-v1.7.2-white-loop-batch-tracking-upgrade.patch
git apply --index ./UmaLegacyLinker-v1.7.2-white-loop-batch-tracking-upgrade.patch
```

Si le Workshop MVP n'est pas encore appliqué, appliquer d'abord le patch MVP fourni dans `reference/`, puis cet upgrade.

## Validation recommandée dans le vrai checkout

```bash
python -m unittest tests.test_loop_workshop -v
python tests/check_i18n.py
python -m unittest discover -s tests -p "test_*.py"
python -m unittest tests.test_qt_runtime tests.test_qt_ui -v
python -m ui_qt.layout_audit
```

Le nom exact de la commande de layout audit peut dépendre de la procédure Windows du dépôt ; utiliser le script habituel du projet si nécessaire.

## Validation effectuée pendant la préparation

- `git apply --check` : OK sur une base post-MVP reconstruite avec les contextes v1.7.2 exacts pour `legacy_linker.py` et `i18n.py` ;
- application réelle du patch sur cette base : OK ;
- `git diff --check` : OK ;
- `py_compile` : OK pour les fichiers complets reconstruits (`loop_models.py`, `loop_repository.py`, `loop_engine.py`, `ui_qt/pages_loop.py`, `tests/test_loop_workshop.py`) ;
- suite White Loop ciblée : **13/13 tests OK** avec les dépendances du moteur simulées pour le checkout partiel ;
- couverture ajoutée : draft round-trip, migration v1->v2, détection/dédup batch, matching par groupe MDB, forme ◎, factor 2★, acquisition unknown lorsque les skills ne sont pas observables, verdict sans fermeture, verdict immuable, fermeture explicite.

La suite complète du dépôt et le layout audit Qt/Windows n'ont pas été exécutés dans l'environnement de préparation, car le ZIP de passation ne contenait pas le checkout complet et le conteneur n'avait pas d'accès réseau Git. Ils doivent donc être relancés localement après application.

## Migration des anciens projets

- Un projet schema v1 est accepté et sera réécrit en schema v2 à la prochaine sauvegarde.
- Un ancien résultat `completed` est converti en run de batch historique.
- Une ancienne transition `pending` sans baseline n'importe pas rétroactivement toute la collection : son premier scan v2 établit la baseline. Un résultat ancien non documenté peut toujours être ajouté manuellement.
- Un draft n'active aucune protection Transfer Helper ; seuls les batches effectivement lancés et les carriers actifs sont protégés.
