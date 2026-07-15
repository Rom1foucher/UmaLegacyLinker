# Modèle de score — état courant (V35)

La source de vérité est `default_parent_scoring.json` pour les pondérations et les courbes,
et `default_skill_priorities.json` pour la valeur des white skills par profil. Ce document
décrit le modèle fourni par défaut ; toutes les valeurs restent modifiables sans toucher au
code. L'historique des évolutions est dans `CHANGELOG.md`.

## Personnalisation dans l'application

L'onglet **Pondérations** expose les composantes globales, les blues, le modèle d'aptitudes
roses, les whites, les courbes d'affinité, les conditions de course, la génération de genes,
le classement uma.moe et le Transfer Helper.

Les réglages utilisateur sont enregistrés comme un diff récursif par rapport à
`default_parent_scoring.json`, puis fusionnés avec le profil courant à chaque calcul. Une mise
à jour qui ajoute de nouveaux paramètres reste donc compatible avec un ancien profil. Les
anciens profils contenant `mode_weights.parent_final` sont automatiquement répartis entre
`parent_branch` et `parent_pair`; les anciennes heuristiques roses V31 sont ignorées au profit
du modèle V32.

Les poids d'une même formule sont normalisés par le moteur : ils peuvent être exprimés en
fractions, pourcentages ou proportions arbitraires, sans obligation de totaliser 1 ou 100.
Les profils effectifs sont copiés dans le dossier de sortie sous les noms
`active_parent_scoring.json` et `active_skill_priorities.json`.

## Pondérations par mode

### Branche parent

| Composante | Poids |
|---|---:|
| White skills | 47 % |
| Aptitude de distance | 22 % |
| Autres aptitudes roses (terrain/style) | 10 % |
| Unique verte | 9 % |
| Blues | 8 % |
| Race/scénario | 4 % |

Une branche est une moitié de solution. Elle n'est pas éliminée parce qu'elle manque de
distance : l'autre branche peut compenser. Son affinité globale est calculée et affichée comme
diagnostic, mais n'est plus une composante additive du score parent.

### Paire de parents finale

| Composante | Poids |
|---|---:|
| White skills | 42 % |
| Aptitude de distance | 32 % |
| Autres aptitudes roses (terrain/style) | 7 % |
| Unique verte | 7 % |
| Blues | 8 % |
| Race/scénario | 4 % |

Le tri est lexicographique : le statut de distance est évalué avant le score pondéré. Une
paire qui commence la run à Distance A est donc toujours prioritaire sur une paire Distance B
non compensée, même si cette dernière possède davantage de whites.

À statut identique, le **score pondéré global** est désormais prioritaire sur la probabilité
brute de S. `P(S)` est déjà intégrée au score via une courbe saturante ; elle ne doit donc pas
écraser de bien meilleures whites ou blues pour un écart marginal proche du plafond pratique.

L'affinité globale ◎/〇/△ n'est pas pondérée. Les liens utiles sont déjà intégrés directement
dans les probabilités de proc des aptitudes roses.

### Futur grand-parent

| Composante | Poids |
|---|---:|
| Génération white (`white_generation`) | 21 % |
| Affinité de la future branche | 15 % |
| Pink propre | 25 % |
| White skills propres | 13 % |
| Blue propre | 13 % |
| Potentiel de G1 | 11 % |
| Unique verte propre | 2 % |

Un futur GP n'est qu'un des six membres de la future lignée. Une mauvaise rose y est donc
pénalisante sans devenir rédhibitoire. Le score reprend le modèle simple historique : qualité
des étoiles et pertinence distance/terrain/style, sans calcul de rang initial, de proc ou de
`P(S)`. Le futur autre parent et la branche finale ne sont pas encore connus.

### Paires GP1 + GP2 via uma.moe

| Composante | Poids |
|---|---:|
| White Sparks propres aux deux GP | 26 % |
| Pinks | 24 % |
| Potentiel d'affinité du futur parent avec l'Ace | 22 % |
| Soutien de génération white dans les deux lignées | 18 % |
| Blues | 6 % |
| Affinité du run de fabrication | 4 % |

Cette recherche vise la fabrication d'un futur parent et reste distincte du calcul exact
d'une paire finale pour l'Ace.

## Blues

Les blues restent volontairement simples. Le score combine uniquement :

```text
qualité du nombre d'étoiles × pertinence de la stat pour la distance
```

Puis ce score est rapproché d'une valeur neutre selon l'importance des blues sur la distance :

```text
score final = 50 + influence_distance × (score brut - 50)
```

Influence fournie : Sprint `0,45`, Mile `0,65`, Medium `0,90`, Long `1,00`.
Les mauvaises blues différencient donc peu les lignées en Sprint/Mile, où la statline visée
est généralement plus facile à atteindre, mais restent nettement plus structurantes en
Medium/Long.

Préférences fournies :

| Distance | Speed | Stamina | Power | Guts | Wit |
|---|---:|---:|---:|---:|---:|
| Sprint | 0,65 | 0,05 | 1,00 | 0,35 | 0,45 |
| Mile | 0,65 | 0,25 | 1,00 | 0,40 | 0,50 |
| Medium | 0,65 | 1,00 | 0,80 | 0,45 | 0,50 |
| Long | 0,65 | 1,00 | 0,75 | 0,45 | 0,50 |

Barème fourni :

- 1★ : 0,12 — mauvais, à compenser ;
- 2★ : 0,78 — acceptable ;
- 3★ : 1,00 — meilleur, sans être obligatoire.

Aucun calcul d'affinité individuel ni multiplicateur parent/GP n'est appliqué aux blues. Leur
fort taux de transmission et leur rôle secondaire ne justifient pas cette complexité dans le
classement.

## Modèle probabiliste des aptitudes roses

Le même moteur est utilisé pour la distance, le terrain et le style. Son interprétation est
cependant beaucoup plus stricte pour la distance.

### Rang au début de la run

Les étoiles correspondant à l'aptitude ciblée donnent :

| Étoiles cumulées | Rangs gagnés au départ |
|---:|---:|
| 0 | +0 |
| 1–3 | +1 |
| 4–6 | +2 |
| 7–9 | +3 |
| 10+ | +4 |

Le rang initial est plafonné à A. Exemple pour une aptitude naturelle C :

- 3★ donnent B au départ ;
- 4★ donnent A au départ.

### Affinités individuelles modernes

Le symbole global ◎/〇/△ est seulement diagnostique. Le moteur calcule un coefficient propre
à chacun des six porteurs, avec le système moderne `modern_g1` : G1 uniquement, +3 par G1
commune, lien parent↔parent inclus, aucun G2/G3 ni titre.

Pour le parent `P1`, ses GP `G11/G12`, l'autre parent `P2` et l'Ace `A` :

```text
inheritance_affinity(P1) =
    pair(A, P1)
  + pair(P1, P2)
  + triple(A, P1, G11)
  + triple(A, P1, G12)
  + 3 × G1(P1, P2)
  + 3 × G1(P1, G11)
  + 3 × G1(P1, G12)
```

Pour `G11` :

```text
inheritance_affinity(G11) =
    triple(A, P1, G11)
  + 3 × G1(P1, G11)
```

Les formules symétriques s'appliquent à l'autre branche. La meilleure transmission des
parents directs apparaît naturellement parce qu'ils cumulent davantage de liens ; aucun
multiplicateur fixe parent/GP n'est ajouté.

### Probabilité de proc

Chaque facteur rose correspondant effectue un roll indépendant lors des deux Inspiration
Events. Les taux de base fournis sont :

| Étoiles | Taux de base par événement |
|---:|---:|
| 1★ | 1 % |
| 2★ | 3 % |
| 3★ | 5 % |

```text
p_i = base_rate(stars) × (1 + inheritance_affinity(i) / 100)
```

Le moteur calcule ensuite exactement la distribution de Poisson binomiale sur les deux
événements afin d'obtenir `P(N≥1)`, `P(N≥2)`, etc. Un proc est traité comme exactement un rang.
Les rares montées de deux rangs sont volontairement ignorées.

### Résultat exporté

Pour chaque aptitude, les JSON détaillent notamment :

- aptitude naturelle et aptitude au début de la run ;
- étoiles totales et nombre de porteurs ;
- procs nécessaires pour atteindre A et S ;
- `probability_reach_a` et `probability_reach_s` ;
- coefficient d'affinité et probabilité de proc de chaque facteur ;
- distribution complète du nombre de procs.

## Distance : contrainte de viabilité

La distance est prioritaire parce qu'un Ace vise normalement Distance S.

### Départ à A

- A est garanti dès le début ;
- un proc suffit pour S ;
- `P(S) = P(N≥1)`.

Le score de distance fourni est :

```text
70 + 30 × utilité(P(S))
```

La courbe par défaut traduit les repères pratiques suivants :

| `P(S)` | Utilité |
|---:|---:|
| 15 % | 10/100 |
| 25 % | 30/100 |
| 40 % | 70/100 |
| 50 % | 90/100 |
| 60 % | 100/100 |

Le gain 40→50 % reste significatif ; le gain 50→60 % est volontairement plus faible. Au-delà
de 60 %, aucune valeur additionnelle n'est accordée par défaut. La courbe complète est
modifiable via `aptitude_inheritance.distance.s_probability_curve`.

Une lignée A sans aucun facteur de distance reçoit cependant le statut `no_s_support` et un
score de distance nul : A seul reste jouable, mais ne correspond pas à l'objectif d'un Ace.

### Départ à B

- un proc est nécessaire pour atteindre A ;
- deux procs sont nécessaires pour atteindre S ;
- `P(A+) = P(N≥1)` ;
- `P(S) = P(N≥2)`.

Le score brut est :

```text
20 + 45 × P(A+) + 35 × utilité(P(S))
```

Un départ à B n'est recommandé que si les quatre conditions suivantes sont simultanément
remplies :

| Condition de compensation | Défaut |
|---|---:|
| `P(A+)` minimale | 55 % |
| `P(S)` minimale | 15 % |
| score white minimal | 85/100 |
| score blue minimal | 75/100 |

Il reçoit alors le statut `distance_b_compensated`. Sinon il reste
`distance_b_uncompensated` et est classé derrière toutes les paires prêtes pour S.

### Départ à C ou moins

Le statut est `underprepared`. La paire reste exportée pour diagnostic, mais elle n'entre pas
dans les recommandations normales, même si une succession de procs pourrait théoriquement
la sauver.

### Ordre de classement

Les paires sont triées selon :

```text
1. statut de viabilité distance
2. score pondéré global
3. score white
4. score blue
5. probabilité brute d'atteindre S, comme départage
```

Statuts de paire finale :

- `ready_for_s` : départ à A avec au moins une chance de S ;
- `distance_b_compensated` : départ à B, mais pinks + whites + blues exceptionnels ;
- `distance_b_uncompensated` : départ à B insuffisamment compensé ;
- `no_s_support` : départ à A mais aucun support de S ;
- `underprepared` : départ à C ou moins.

## Terrain et style

Terrain et style utilisent les mêmes étoiles, affinités individuelles et probabilités, mais
avec une exigence moindre.

### Terrain

- départ A : `80 + 20 × P(S)` ;
- départ B : `55 + 30 × P(A+) + 15 × P(S)` ;
- sous B : faible score résiduel, sans gate de viabilité.

### Style

- départ A : `90 + 10 × P(S)` ;
- départ B : `70 + 25 × P(A+) + 5 × P(S)` ;
- sous B : faible score résiduel, sans gate de viabilité.

Dans le score rose d'une paire finale, la répartition est : distance 72 %, terrain 18 %,
style 10 %. Surface/style ne peuvent jamais compenser un statut de distance inférieur, car le
tri de viabilité intervient avant le score additif.

## Branches incomplètes et futurs GP

Une branche seule ne connaît pas encore l'autre parent. Son coefficient parent est donc
partiel : le lien parent↔parent et leurs G1 communes seront ajoutés lors du calcul final sur
six membres. Les coefficients des deux GP de la branche sont déjà complets.

La branche reçoit un diagnostic non bloquant (`deficit`, `light`, `balanced`,
`distance_carrier`) et conserve le modèle probabiliste partiel, car ses trois membres seront
directement visibles dans la run finale de l'Ace.

Le futur GP utilise au contraire un score heuristique simple. Il ne reçoit aucun statut de
viabilité distance et aucune probabilité de S : sa rose, sa blue et ses whites propres sont
seulement jugées acceptables ou utiles à l'échelle d'un membre sur six.

## White skills

Chaque white Skill Spark utilise les taux communautaires de base :

```text
1★ = 3 %
2★ = 6 %
3★ = 9 %
```

Pour chaque porteur :

```text
p/événement = taux de base × (1 + affinité individuelle / 100)
```

Le moteur applique les deux Inspiration Events. Lorsque plusieurs membres portent la même
skill, leurs rolls sont combinés en une seule probabilité d'obtenir la skill au moins une fois :

```text
P(skill) = 1 − produit(1 − p_i)²
utilité(skill) = courbe_distincte(P(skill))
contribution = priorité du skill × utilité(skill)
```

Cette agrégation évite de surévaluer plusieurs copies situées sur des GP à faible affinité.
Une copie parent à forte affinité peut donc valoir davantage que plusieurs copies éloignées.
Les copies identiques augmentent uniquement la probabilité de leur skill commune. Elles ne créent
pas plusieurs entrées de diversité.

La courbe `distinct_skill_probability_curve` applique ensuite deux principes :

- une probabilité très faible, autour de 5–10 %, apporte peu ;
- les rendements diminuent lorsque la même skill approche déjà 60–80 %.

Avec les valeurs par défaut, trois skills utiles à 20 % chacune produisent davantage de valeur
qu'une seule skill à 80 %, même si la somme brute des probabilités est inférieure. Le modèle vise
ainsi le meilleur potentiel de high roll sur plusieurs runs plutôt que la seule régularité d'un
facteur déjà très concentré.

Les contributions par skill sont enfin saturées globalement :

```text
score = 100 × (1 − exp(−somme / échelle))
```

Les taux, la courbe de diversité, le nombre d'événements et les échelles restent configurables via
`white_inheritance` et `white_saturation`.

### Différence entre recherche de parent et recherche de GP

**Parent ou paire finale**

Les six membres visibles de la lignée participent directement aux Inspiration Events de
l’Ace. Le score white combine donc les probabilités des deux parents et de leurs quatre GP,
avec leurs six affinités individuelles exactes.

**Futur GP**

Le candidat restera un GP visible dans la lignée finale, mais le reste de cette lignée n'est
pas encore suffisamment défini pour produire une estimation de proc utile. Ses propres whites
sont donc évaluées simplement selon la priorité du skill, les étoiles et son rôle de GP. Aucune
affinité individuelle, probabilité par événement ou probabilité cumulée n'est calculée.

Les parents actuels du candidat ne seront plus visibles dans la lignée de l’Ace. Leurs whites
ne sont donc jamais ajoutées au score d’héritage direct. Elles interviennent uniquement dans
`white_generation`, qui estime leur soutien à la création d’une white Spark sur le futur parent.

La compatibilité de la run intermédiaire qui fabrique ce parent est conservée séparément ;
elle ne remplace pas l’affinité finale du GP pour valoriser ses propres factors.

## Génération white (`white_generation`)

Pour un futur grand-parent, ses propres white Sparks et celles de ses deux parents actuels
comptent comme support de génération du futur parent :

```text
bonus_lignée = nombre_de_membres_avec_le_gene × 0,025
contribution = priorité_du_skill × bonus_lignée
```

Pas de distinction blanche/◎/gold, pas d'estimation de chance de base, pas de bonus
d'étoiles. Race et scenario Sparks exclues. Le score agrégé passe par la même saturation.

## Affinité globale et potentiel G1

La compatibilité globale moderne reste calculée pour l'explication des résultats et pour les
modes où la lignée finale n'existe pas encore. Elle utilise les groupes de relation communs,
les triples Ace-parent-GP, le lien parent-parent et +3 par G1 commune sur les cinq liens
visibles.

Pour une paire finale ou une branche parent, ce total global n'est plus pondéré dans le score :
les coefficients individuels sont déjà utilisés dans les probabilités roses et whites. Pour un
futur GP et la recherche de fabrication uma.moe, l'affinité/potentiel G1 conserve une pondération
distincte et n'est jamais convertie en pourcentage de proc.

Un grand-parent identique à l'Ace apporte 0 en compatibilité de base, afin d'éviter qu'une
intersection du personnage avec lui-même crée un faux maximum, mais conserve ses factors
transmissibles.

## Green skills et conditions de course

Sur les conditions sélectionnées (hippodrome, rotation, saison, météo, terrain) :

- incompatibilité explicite → poids 0 ;
- correspondance explicite → activation avec un plancher configurable
  (`course_conditions.floors`) ;
- condition non renseignée → poids générique conservé.

Hiérarchie fournie : saison forte (0,65) ; gauche (0,52) > droite (0,32), car plus rare à
obtenir ; hippodrome modéré (0,26) ; météo/terrain petits bonus (0,12–0,14).

## Race et scenario Sparks

Valeur de base volontairement faible (0,025 par palier d'étoiles ; scénario 0,06). Une race
Spark donnant une green skill utile est décotée à 20 % de la valeur du skill
(`granted_skill_multiplier`) : sa chance de transmission reste inférieure à celle du white
spark direct.

## Recherche uma.moe

Pour un Ace `A`, un parent à produire `P`, un GP1 et un GP2 :

```text
base = pair(A, P) + triple(A, P, GP1) + triple(A, P, GP2)
```

Les propres parents de GP1/GP2 sont exclus de cette base : ils servent pendant le run de
fabrication de `P` mais ne figurent plus dans la future lignée visible de l'Ace.

Le futur parent n'existant pas encore, un budget configurable de G1 (24 par défaut) estime le
bonus. Les G1 communes à GP1 et GP2 sont retenues d'abord (une victoire crée deux liens, +6),
puis les G1 d'un seul côté (+3, pondérées par un coefficient de réalisation, 60 % par défaut).

```text
potentiel final de la branche = base + bonus G1 prévu
```

L'autre parent final de l'Ace n'étant pas connu, son lien avec `P` n'est pas inclus. La
compatibilité complète du run de fabrication reste calculée comme diagnostic, à 4 % du
classement GP.

Le mode de recherche d'un parent distant final utilise, lui, exactement le moteur à six
membres décrit plus haut : aptitude initiale, six coefficients individuels et probabilités
A/S incluses.

Les contraintes UQL cochées (Dirt, surface, distance, style, minimum pink) sont strictes :
envoyées à l'API puis revérifiées localement sur les factors résolus avec le `master.mdb`.

## Transfer Helper

Le Transfer Helper réutilise les modèles existants sur un périmètre volontairement proche des
usages à venir :

- les cinq premières Champion Meetings classées comme à venir dans le catalogue ;
- les cinq catégories génériques Team Trials ;
- chacun de ces dix profils décliné sur les quatre styles, soit 40 contextes ;
- toutes les variantes d'Ace distinctes utiles pour l'affinité et le besoin en pinks ;
- rôle parent avec la branche actuelle complète ;
- rôle futur grand-parent avec factors propres et support de génération issu de sa lignée.

Les profils génériques `surface × distance × style`, les CM plus lointaines et les CM archivées
restent utilisables dans l'optimiseur normal, mais ne participent pas aux verdicts de nettoyage
par défaut.

Le potentiel GP utilise une affinité constante optimiste à 100. Ce choix volontaire évite de
classer comme inutile un personnage dont la niche de compatibilité ne correspond simplement
pas à une cible sélectionnée : le classement relatif mesure donc surtout sa valeur intrinsèque
comme GP.

Un vétéran est marqué **transfert sûr** uniquement si un autre exemplaire du même `card_id` et
de la même unique héritée :

1. n'est inférieur au candidat dans aucun contexte parent testé, à la tolérance configurée ;
2. n'est inférieur dans aucun contexte futur GP ;
3. conserve au moins autant de G1 communes avec chaque partenaire local potentiel ;
4. dépasse la marge moyenne minimale `dominance_mean_margin`.

Les costumes alternatifs ne sont jamais regroupés. Un verdict **à examiner** signifie seulement
que le vétéran ne dépasse ni `competitive_score_floor`, ni le top percentile
`competitive_top_percent` dans aucun des deux rôles. Il ne s'agit pas d'une suppression sûre.

Paramètres disponibles dans `transfer_helper` :

| Paramètre | Défaut | Rôle |
|---|---:|---|
| `competitive_top_percent` | 20 | meilleur percentile suffisant pour protéger une niche |
| `competitive_score_floor` | 65 | score absolu suffisant pour protéger une niche |
| `dominance_tolerance` | 0,25 | recul maximal accepté dans un contexte lors d'une comparaison |
| `dominance_mean_margin` | 1,5 | avance moyenne minimale du remplaçant |
| `include_course_presets` | `true` | active l'utilisation du catalogue de presets |
| `upcoming_cm_limit` | 5 | nombre de prochaines CM évaluées, dans l'ordre du catalogue |
| `include_team_trials` | `true` | ajoute les cinq catégories Team Trials |
| `include_generic_profiles` | `false` | ajoute les 32 profils génériques surface × distance × style |
