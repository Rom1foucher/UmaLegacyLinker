# Changelog

## V28 — focused Transfer Helper scope

- Transfer Helper now evaluates only the first five upcoming Champion Meetings and the five Team Trials categories by default.
- With the current bundled catalogue, the CM scope is CM16 through CM20; CM21+ and archived CM9-CM15 remain available for manual lineage optimisation only.
- Generic Turf/Dirt × distance profiles are no longer included in cleanup verdicts by default.
- The ten selected race profiles are still evaluated across all four running styles, for a total of 40 parent/grandparent contexts.
- Added configurable `upcoming_cm_limit`, `include_team_trials`, and `include_generic_profiles` settings under `transfer_helper`.
- Transfer reports now record the exact course keys and context count used by the audit.

## V27 — expanded course presets and Team Trials profiles

- Fixed the preset selector remaining on **Generic profile** when `master.mdb` was unavailable or when the saved preset path pointed to an older installation.
- Course presets now load independently from the game database and stale bundled paths automatically fall back to the current `default_course_overrides.json`.
- The selector now exposes every preset instead of filtering the list to the current surface/distance. Selecting a preset automatically applies its surface, distance, racecourse when known, direction, season, weather and ground condition.
- Added CM16 through CM46 from the supplied schedule, while retaining CM9-CM15 as an archive. Future CMs are displayed first.
- Added generic Team Trials presets for Turf Sprint, Turf Mile, Turf Medium, Turf Long and Dirt Mile.
- Course conditions and category metadata are preserved in generated `course_skill_weights.json`; using a course key from the CLI now also applies its bundled static conditions.
- Transfer Helper includes upcoming CMs and Team Trials with their static conditions, but excludes archived CM9-CM15 from automatic cleanup weighting.

## V26 — global niche viability for Transfer Helper

- Same-card comparisons now use the complete local veteran pool to determine whether a parent or grandparent context is genuinely viable.
- A context where every copy of a card is globally outclassed is ignored for dominance; being the “least bad” copy in an unsuitable niche no longer forces a keep.
- Parent and grandparent roles are filtered independently. A replacement can therefore be proven from only the viable role when the card has no realistic use in the other one.
- Transfer reports now expose the number of viable parent and grandparent comparisons supporting each safe-transfer verdict.
- Updated bilingual interface explanations, report safety notes and README documentation.

## V25 — Transfer Helper

- Nouvel onglet **Transfer Helper** pour auditer toute la liste de vétérans locaux avant nettoyage.
- Évaluation exhaustive des profils génériques Turf/Dirt × Sprint/Mile/Medium/Long × quatre styles, avec ajout facultatif des presets de course.
- Analyse séparée des rôles **parent** et **futur grand-parent** : une mauvaise branche parent peut donc rester protégée grâce à une excellente niche GP.
- Le rôle parent utilise la branche actuelle complète et son affinité face aux Ace disponibles ; le rôle GP utilise les factors propres du candidat et sa lignée actuelle pour le support de génération des whites.
- Comparaison de remplacement volontairement limitée à la même card et à la même unique héritée ; les costumes alternatifs ne sont jamais considérés comme interchangeables.
- Verdicts distincts : **transfert sûr**, **à examiner**, **conserver**. Seul le premier exige un remplaçant unique non inférieur dans tous les contextes testés et sans perte de support G1 en paire.
- Aucun changement automatique de `data.json` et aucune suppression en jeu.
- Nouveaux exports `transfer_helper_report.json`, `transfer_helper_candidates.csv` et `transfer_helper_summary.txt`.
- Seuils configurables dans `default_parent_scoring.json > transfer_helper` et dans l’éditeur de pondérations.
- Nouveau mode CLI `--transfer-helper`.
- Interface et fenêtre de résultats disponibles en français et en anglais.

## V24 — interface bilingue français / anglais

- Ajout d’un sélecteur **Français / English** dans l’en-tête, avec changement immédiat sans redémarrage.
- Langue mémorisée dans la configuration utilisateur et restaurée au lancement.
- Traduction des onglets, contrôles, dialogues, fenêtres de résultats, messages de validation, statuts et journal d’activité.
- Le journal conserve les messages sources et les rerend dans la langue active après une bascule, sans mélange entre les deux langues.
- Les valeurs métier restent canoniques dans la configuration : changer la langue ne modifie ni les profils de course, ni les calculs, ni les exports.
- Libellés de l’éditeur de pondérations centralisés dans le module d’internationalisation.

## V23 — pondérations personnalisables

- Nouvel onglet **Pondérations** avec éditeur arborescent de l'ensemble de
  `default_parent_scoring.json` : poids des composantes, préférences blue par stat/distance,
  pinks par catégorie, paliers d'étoiles, saturations, affinité, green skills,
  génération white et réglages uma.moe.
- Les personnalisations sont stockées sous forme de surcharges minimales dans le dossier de
  configuration utilisateur. Le profil effectif est validé et matérialisé dans le dossier de
  sortie pour garantir la reproductibilité des classements.
- Priorités individuelles des white skills personnalisables via un JSON complet ou partiel,
  fusionné avec `default_skill_priorities.json`. Création d'une copie modifiable directement
  depuis l'interface.
- Ajout de `--scoring-config` et `--skill-priorities` en CLI pour charger des profils complets
  ou des surcharges.
- Fetch uma.moe porté à un maximum strict de 2 000 parents, contrôlé dans l'interface et dans
  `UmaMoeApiClient.search_many`.
- Les profils effectifs, y compris lorsqu'ils restent aux valeurs par défaut, sont copiés dans
  `active_parent_scoring.json` et `active_skill_priorities.json` pour audit et reproductibilité.
- Le script de diagnostic uma.moe lit désormais la clé via `UMA_MOE_API_KEY` au lieu de la
  conserver dans le code source.
- Tests automatiques du merge/diff des profils, de leur validation et du plafond de fetch.

## V22 — nettoyage et interface à onglets

- Interface réorganisée en quatre onglets : **Liaison & catalogue**, **Optimisation de lignée**, **uma.moe**, **Outils legacy**. Les fichiers communs (`master.mdb`, `data.json`, dossier de sortie) restent regroupés au-dessus des onglets ; statut, progression et journal restent toujours visibles en bas.
- Fenêtre réduite à 1240×900 (au lieu de 1380×1180), onglet actif mémorisé entre les sessions, bouton **Effacer** sur le journal, navigation Ctrl+Tab entre onglets.
- Le pipeline Umalator (batch + import) est déplacé dans l'onglet legacy ; aucun changement fonctionnel.
- Documentation consolidée : un seul `CHANGELOG.md`, modèle de score unique dans `docs/SCORING.md`, `README.md` réécrit à l'état courant, docs annexes déplacées dans `docs/`.
- Artefacts (`__pycache__/`, `output/`) retirés du projet.

## V21 — étoiles des white Sparks

- Les étoiles ne sont plus une valeur linéaire `1/3, 2/3, 1` : nouvelle courbe de confort d'héritage `1★ = 1.00`, `2★ = 1.35`, `3★ = 1.80`.
- La priorité stratégique du skill reste le facteur principal : une excellente white 1★ peut dépasser une white secondaire 3★.
- Seuils de saturation white multipliés par 1.8 pour conserver l'étalonnage des lignées majoritairement 3★ sans inflation générale.
- Le soutien de génération par répétition de lignée reste fondé sur la présence du gene, sans bonus d'étoiles.

## V20 — priorité aux white Sparks déjà présentes (uma.moe)

- `white_skill` passe de 22 % à 26 % ; `final_parent_affinity` de 26 % à 22 %.
- Une paire portant déjà les genes recherchés est préférée à une paire seulement plus simple à hériter. Génération de lignée inchangée à 18 % ; pink 24 %, blue 6 %, affinité du run de fabrication 4 %.

## V19 — validation locale des contraintes UQL

- Les cases `Exiger Dirt/surface/distance/style` sont réappliquées localement après normalisation : un candidat distant non conforme est exclu même si l'API ignore le paramètre UQL.
- Le journal indique les compteurs avant/après filtrage strict ; les diagnostics exportent les filtres appliqués.
- `/api/v3/search` utilise en priorité le contrat OpenAPI exact.

## V18 — paires uma.moe automatiques

- Mode automatique : préclasse les meilleurs GP locaux et distants (100 × 100 par défaut, fetch jusqu'à 1000), puis évalue toutes les paires local × distant. Le GP local fixe devient un mode manuel optionnel.
- Options UQL à cases : whites du profil, répétition de lignée, filtres Dirt/surface/distance/style avec minimum d'étoiles pink.
- G1 : les communes aux deux GP restent prioritaires ; les G1 d'un seul côté comptent avec un coefficient configurable (60 % par défaut).

## V17 — sémantique de l'affinité uma.moe

- Le score principal vise l'affinité potentielle du **futur parent** dans la lignée finale de l'Ace ; les propres parents de GP1/GP2 en sont exclus (une génération trop loin).
- Budget configurable de G1 prévues sur le futur parent (24 par défaut) : communes = 6 points potentiels, uniques = 3.
- La compatibilité du run de fabrication devient un diagnostic secondaire à faible pondération.

## V16 — sélecteur de GP local

- Le long dropdown de GP local fixe est remplacé par un sélecteur dédié, recherchable et trié par score d'évaluation.
- Audit explicite des cinq liens G1 pour l'appariement en ligne ; séparation du total de compatibilité de lignée et du modificateur propre à GP2.
- Courbe d'affinité GP2 rééquilibrée en rendements décroissants (plus de plafond dur à 151).

## V15 — UQL automatique et pagination

- Génération automatique de l'UQL depuis surface, distance, style, preset et conditions ; `optional white` large + sous-groupe `lineage white`, sans filtre blue/pink obligatoire.
- Pagination zéro-indexée de `/api/v3/search` par lots de 100, déduplication par `inheritance_id`, repli vers une UQL simplifiée si la requête complète est refusée.
- Export `uma_moe_generated_uql.txt` / `.json` pour audit.

## V14 — normaliseur `/api/v3/search`

- Lecture de `items[].inheritance`, résolution des parents (`main/left/right`), décodage direct des IDs de factors, G1 depuis `*_win_saddles`, métadonnées entraîneur depuis `account_id`.

## V13 — découverte OpenAPI

- Prise en charge de `/api/docs/openapi.yaml` (PyYAML ajouté au build Windows) ; appel direct prioritaire de `GET /api/v3/search` avec `X-API-Key`, OpenAPI dynamique en fallback.

## V12 — clé API uma.moe

- Champ masqué en mémoire seulement (jamais dans `config.json`), variable `UMA_MOE_API_KEY` supportée, envoi via `Authorization: Bearer` et `X-API-Key`.

## V11 — liaison uma.moe

- Recherche d'un GP2 en ligne à associer à un GP1 local ; découverte runtime du document OpenAPI ; UQL facultative et limite de résultats ; import d'une réponse JSON en fallback.
- Affinité additive `pair(Ace, parent) + triple(…, GP1) + triple(…, GP2)`, affinité complète du run de fabrication, scoring des factors propres et du support white sur les six membres des lignées.
- Exports JSON, CSV, réponse brute et diagnostics.

## V10 — white genes de production simplifiés

- Plus de distinction blanche/◎/gold ni d'estimation de chance de base : chaque membre de lignée portant le gene apporte +2,5 points de pourcentage, pondérés par la priorité manuelle du skill.
- Race et scenario Sparks exclues ; suppression du multiplicateur séparé de rareté (encodé directement dans les priorités).

## V9 — priorités manuelles

- Le classement n'utilise plus Umalator : les whites sont pondérées par `default_skill_priorities.json`, éditable sans toucher au code.
- Nouveau sous-score `white_generation` : les white Sparks du candidat et de ses deux parents comptent comme support de génération du futur parent.
- Le batch Umalator reste disponible en outil legacy/diagnostic.

## V8 — scoring explicable

- Affinité en courbe à seuils/plafond ; contribution nulle pour un grand-parent identique à l'Ace (au lieu d'un faux maximum).
- Blues et pinks en paliers d'étoiles ; pinks par catégorie distance > surface > style ; greens de course hiérarchisées (saison forte, gauche > droite, météo/terrain mineurs).
- Détail complet du calcul dans la fenêtre de résultats ; CSV enrichis (rank_score, affinité, potentiel G1).

## V7 — résultats et recherche

- Colonnes plus lisibles, score Uma affiché, panneau de détail au clic ; sélecteurs Ace/parent/hippodrome/preset recherchables ; rééquilibrage des pinks.

## V6 — parent à produire et conditions de course

- Second sélecteur **Parent à produire** ; classement des futurs grands-parents par contribution exacte `triple(Ace, parent, candidat)`, base `pair(Ace, parent)` affichée séparément.
- Sélecteurs hippodrome/rotation/saison/météo/terrain : incompatibilité explicite → 0, correspondance → plancher configurable, non renseigné → poids générique.
- Nouveaux arguments CLI (`--future-parent-card-id`, `--track-id`, `--rotation`, `--season`, `--weather`, `--ground-condition`).

## V5 — optimisation de lignée

- Moteur de classement pour une Ace cible : recherche exhaustive des paires de parents finales (affinités pair/triple + bonus G1 sur les cinq liens), classements séparés des lignées et des futurs grands-parents.
- Configuration dans `default_parent_scoring.json` ; exports `legacy_parent_rankings.json`, `legacy_parent_pairs.csv`, `legacy_parent_candidates.csv`, `legacy_future_grandparents.csv` ; fenêtre de résultats à trois onglets ; mode CLI `--rank-parents`.

## V4 — pondération Umalator consolidée

- Corrections des faux zéros (Groundwork, Dodging Danger, Prudent Positioning, Tail Held High, Updrafters) ; Nimble Navigator plafonnée en Front Runner ; Uma Stan relevée hors Front.
- Sous-score de positionnement indépendant ; presets de course exacts CM9–CM16 dans `default_course_overrides.json` ; sortie `course_skill_weights.json`.
- JSON distinguant `auto_weight`, `performance_weight`, `positioning_bonus`, `weight`.

## V28.1 — Transfer Helper condition hotfix

- Fixed a crash when course presets supplied scalar static-condition values (for example `rotation: 1`) to the Transfer Helper.
- Static condition comparison now accepts scalar and collection values consistently across GUI, CLI and preset-driven analyses.
- Added regression coverage for scalar preset conditions.

## V29 — Selective Transfer Helper

- Reworked Transfer Helper retention rules to avoid keeping veterans for a single lucky Ace/context combination.
- Added four verdicts: Safe transfer, Review, Likely keep, and Keep.
- Keep now requires either an elite global result or repeated competitiveness across multiple contexts and at least two distinct course profiles.
- Added configurable thresholds: `elite_top_percent`, `minimum_competitive_contexts`, and `minimum_distinct_profiles`.
- Tightened default competitiveness thresholds and slightly relaxed same-card dominance tolerance.
- Added parent/grandparent evidence counts to JSON and CSV reports.

## V30 — In-game veteran identification

- Added in-game rank and evaluation score columns to the Transfer Helper results window.
- Added full stat line and both grandparents to the selected veteran details.
- Added rank and evaluation score for the recommended replacement.
- Expanded `transfer_helper_candidates.csv` with rank, evaluation score, five stats, and both grandparents.
- The JSON report already exposed the veteran identity fields and now also embeds the replacement's in-game identity fields.

## V31 — Distribution-aware Transfer Helper

- Replaced percentile-only Transfer Helper viability with a composite utility score.
- Utility now combines absolute score, proximity to the best score in the context, and a small percentile component.
- Added configurable competitive and elite utility thresholds.
- Added a minimum absolute-score ratio so the least-bad candidate in a weak field is not protected.
- Parent and grandparent profile exports now include utility, leader score, relative-to-leader score, and score gap to the leader.
- Percentile remains available for diagnostics but no longer grants competitiveness by itself.
