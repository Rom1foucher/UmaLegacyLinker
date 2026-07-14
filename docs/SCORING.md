# Modèle de score — état courant (V23)

La source de vérité est `default_parent_scoring.json` (pondérations, paliers, courbes) et
`default_skill_priorities.json` (valeur des white skills par profil). Ce document décrit le
modèle tel qu'implémenté ; les chiffres cités sont ceux des fichiers fournis et peuvent être
édités sans toucher au code. L'historique des évolutions est dans `CHANGELOG.md`.

## Personnalisation dans l'application

L'onglet **Pondérations** permet de modifier toutes les valeurs numériques et les courbes du
profil de score : composantes globales, blues, pinks, whites, affinité, race/scénario,
conditions de course, génération de genes et classement uma.moe. Les modifications sont
enregistrées comme un diff récursif par rapport à `default_parent_scoring.json`, puis fusionnées
avec le profil courant à chaque calcul. Une mise à jour qui ajoute de nouveaux paramètres reste
donc compatible avec un ancien profil utilisateur.

Les priorités individuelles de `default_skill_priorities.json` peuvent également être
remplacées par un JSON complet ou partiel. Le profil est validé puis fusionné avec les valeurs
par défaut avant de produire `manual_skill_weights.json`. À chaque calcul, les deux profils
effectifs sont copiés dans `active_parent_scoring.json` et `active_skill_priorities.json` dans
le dossier de sortie pour permettre de reproduire exactement le classement.

Les poids d'une même formule sont normalisés par le moteur : ils peuvent être exprimés en
fractions, pourcentages ou proportions arbitraires, sans obligation de totaliser 1 ou 100.

## Pondérations par mode

Parent final :

| Composante | Poids |
|---|---:|
| White skills | 36 % |
| Pinks | 28 % |
| Affinité | 22 % |
| Verte unique | 6 % |
| Blues | 5 % |
| Race/scénario | 3 % |

Futur grand-parent :

| Composante | Poids |
|---|---:|
| Pink propre | 25 % |
| Génération white (`white_generation`) | 21 % |
| Affinité de la future branche | 15 % |
| White skills propres | 13 % |
| Blue propre | 13 % |
| Potentiel de G1 | 11 % |
| Verte unique propre | 2 % |

Paires GP1 + GP2 via uma.moe :

| Composante | Poids |
|---|---:|
| White Sparks propres aux deux GP | 26 % |
| Pinks | 24 % |
| Potentiel d'affinité du futur parent avec l'Ace | 22 % |
| Soutien de génération white dans les deux lignées | 18 % |
| Blues | 6 % |
| Affinité du run de fabrication | 4 % |

Principe : l'affinité augmente les chances d'acquérir les genes mais ne remplace pas leur
présence. Une paire qui porte déjà les white Sparks recherchées est préférée à une paire
seulement plus simple à hériter.

## Blues

Palier d'étoiles multiplié par la pertinence de la stat pour la distance
(`blue_stat_weights_by_distance`) :

- 1★ : 0,12 — mauvais, à compenser ;
- 2★ : 0,78 — acceptable ;
- 3★ : 1,00 — mieux, sans être une obligation.

## Pinks

Palier d'étoiles : 1★ = 0,55 ; 2★ = 0,72 ; 3★ = 1,00.
Valeur de catégorie : distance 1,00 > surface 0,72 > style 0,55.
Une aptitude de base inférieure à A reçoit un multiplicateur de besoin ×1,1.

## White skills

Contribution directe d'une white Spark :

```text
priorité du skill (profil surface × distance × style)
× coefficient d'étoiles
× position (parent 1.0 / grand-parent 0.5)
```

Les étoiles sont un confort d'héritage modéré, pas une valeur linéaire :
`1★ = 1.00`, `2★ = 1.35`, `3★ = 1.80`. La priorité stratégique reste dominante : une
excellente white 1★ peut dépasser une white secondaire 3★.

Les contributions sont additionnées puis saturées :

```text
score = 100 × (1 − exp(−somme / échelle))
```

La saturation empêche qu'un grand volume de whites médiocres écrase quelques whites
excellentes. Les échelles (`white_saturation`) sont calibrées pour qu'une lignée
entièrement 3★ garde l'étalonnage maximal.

## Génération white (`white_generation`)

Pour un futur grand-parent, ses propres white Sparks et celles de ses deux parents actuels
comptent comme support de génération du futur parent :

```text
bonus_lignée = nombre_de_membres_avec_le_gene × 0,025
contribution = priorité_du_skill × bonus_lignée
```

Pas de distinction blanche/◎/gold, pas d'estimation de chance de base, pas de bonus
d'étoiles. Race et scenario Sparks exclues. Le score agrégé passe par la même saturation.

## Affinité

Formule brute du MDB : groupes de relation communs + 3 points par G1 commune sur les liens
pertinents. Un grand-parent identique à l'Ace apporte 0 en compatibilité de base (la simple
intersection des groupes du personnage avec lui-même donnerait un faux maximum) mais
conserve ses factors transmissibles.

Le score final passe par des courbes à seuils (`affinity.*_thresholds`) : une base faible
est pénalisée, une bonne base valorisée, puis le gain plafonne progressivement.

## Green skills et conditions de course

Sur les conditions sélectionnées (hippodrome, rotation, saison, météo, terrain) :

- incompatibilité explicite → poids 0 ;
- correspondance explicite → activation avec un plancher configuré
  (`course_conditions.floors`) ;
- condition non renseignée → poids générique conservé.

Hiérarchie : saison forte (0,65) ; gauche (0,52) > droite (0,32), car plus rare à obtenir ;
hippodrome modéré (0,26) ; météo/terrain petits bonus (0,12–0,14).

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

Le futur parent n'existant pas encore, un budget configurable de G1 (24 par défaut) estime
le bonus : les G1 communes à GP1 et GP2 sont retenues d'abord (une victoire crée deux liens,
+6), puis les G1 d'un seul côté (+3, pondérées par un coefficient de réalisation, 60 % par
défaut).

```text
potentiel final de la branche = base + bonus G1 prévu
```

L'autre parent final de l'Ace n'étant pas connu, son lien avec `P` n'est pas inclus. La
compatibilité complète du run de fabrication (GP1, GP2 et leurs propres parents) reste
calculée comme diagnostic, à 4 % du classement.

Les contraintes UQL cochées (Dirt, surface, distance, style, minimum pink) sont strictes :
envoyées à l'API puis revérifiées localement sur les factors résolus avec le `master.mdb`.
