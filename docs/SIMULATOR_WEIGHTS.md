> **Legacy.** Depuis la V9, le classement n'utilise plus Umalator ; ce pipeline reste disponible comme outil de diagnostic (onglet « Outils legacy » et `--umalator-batch`).

# Poids Umalator, corrections manuelles et tracés exacts

## Pipeline V4

Pour chaque white skill et chaque profil `surface × distance × style` :

```text
1. incompatibilité mécanique du MDB → 0
2. score Umalator normalisé
3. correction manuelle de performance
4. petit bonus stratégique de positionnement
5. éventuel override lié à la course exacte
```

Le score générique final est :

```text
robust_value = 0.75 × mean + 0.25 × median
performance_weight = correction(clamp(robust_value / p95_profil, 0, 1.2))
weight = clamp(performance_weight + positioning_bonus, 0, 1.2)
```

La `positive_rate` n'est pas remultipliée : `mean` inclut déjà les runs sans gain.

## Corrections globales fournies

`default_manual_adjustments.json` utilise des `catalog_key` stables et contient :

- Nimble Navigator : plafonnée seulement en Front Runner ;
- Uma Stan : planchers hors Front pour refléter ses activations multiples ;
- Groundwork : faux zéro corrigé pour Front Runner ;
- Dodging Danger : faux zéro lié au trafic/lane movement ;
- Prudent Positioning : valeur de navigation initiale ;
- Tail Held High : faux zéro lié au nombre insuffisant de skills activées ;
- Updrafters : faux zéro corrigé en Mile pour les styles arrière.

## Sous-score de positionnement

Certaines skills ont une valeur stratégique qui n'apparaît pas entièrement dans les
longueurs gagnées : gagner une contestation de position, éviter un enfermement ou
arriver au bon rang avant l'accélération.

Le fichier manuel peut donc contenir des `positioning_rules`. Elles ajoutent un
petit bonus séparé, plafonné à `0.30` par skill et profil.

Les bonus fournis concernent principalement :

- Groundwork, Dodging Danger et Prudent Positioning ;
- Leader's Pride et Ramp Up ;
- les Distance Corners et Style Corners compatibles.

Le JSON de sortie expose séparément :

```json
{
  "auto_weight": 0.52,
  "performance_weight": 0.58,
  "positioning_bonus": 0.14,
  "weight": 0.72
}
```

## Opérations manuelles

Une règle peut filtrer `surface`, `distance`, `style`, ou leurs formes plurielles :

- `override` : remplace le poids de performance ;
- `multiplier` : multiplie le poids ;
- `floor` : impose un minimum ;
- `cap` : impose un maximum.

Exemple :

```json
{
  "match": {"style": "front_runner"},
  "operation": "floor",
  "value": 0.58,
  "reason": "Valeur stratégique non représentée par le simulateur."
}
```

## Overrides liés au tracé

`default_course_overrides.json` contient des presets CM9 à CM16. Ils ne remplacent
jamais les poids génériques tant qu'aucune course cible n'est sélectionnée.

Les opérations supplémentaires acceptent `bonus` pour ajouter une petite valeur
spécifique au tracé.

Exemples fournis :

- Final Push sur Tokyo Turf 1600 ;
- 1,500,000 CC sur Tokyo Turf 2400 ;
- Nimble Navigator sur Hanshin Turf 3200 ;
- Highlander sur Tokyo Dirt 1600 et Chukyo Turf 1200 ;
- bonus de corners sur les Sprints où la position avant accélération est critique.

La sortie `course_skill_weights.json` matérialise les poids complets de chaque preset
et conserve le poids générique, le poids final et la justification de chaque écart.

## File de revue

`manual_review_queue.json` reste ciblé. Il liste :

- les corrections globales configurées ;
- les skills rejetées par le parseur ;
- les skills de trafic/lane à forte valeur automatique.

Le but n'est pas de refaire manuellement les 217 skills, mais d'isoler les cas où le
simulateur ne modélise pas la mécanique déterminante.
