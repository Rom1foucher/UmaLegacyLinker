# Transfer Helper : étude de l’interface et mise à jour locale

## Conclusion de conception

L’interface doit permettre de juger un remplacement concret. L’utilisateur
doit pouvoir retrouver sa copie en jeu, comprendre le motif du diagnostic,
identifier une copie conservée et voir les concessions de ce remplacement.
L’indice et la lignée servent à vérifier cette lecture.

La proposition retenue combine une liste de copies, un panneau de décision
et un dialogue de vérification. Le panneau expose un gain et une perte
pertinents pour l’exemple sélectionné. Le dialogue développe ces différences
et permet d’inspecter leur provenance dans les deux branches. Les calculs
complets restent disponibles au même endroit.

Cette étude s’appuie sur les demandes de Romain, une revue du parcours
existant, les données de son rapport de référence, des vérifications du code
et des rendus Qt. Elle ne comprend pas de test d’utilisation observé avec
Romain ou d’autres joueurs. Il s’agit d’une proposition argumentée à tester
localement, pas d’une démonstration qu’une interface serait universellement
idéale.

## La tâche réelle

La collection contient de nombreuses copies produites pour remplir des rôles
proches. Faire le ménage exige plusieurs jugements liés, mais différents :

| Question du joueur | Réponse attendue de l’interface |
| --- | --- |
| Quelle est cette copie ? | Costume, portrait, rang et score en jeu |
| Pourquoi le modèle la propose-t-il ? | Remplacement individuel, couverture collective ou preuve insuffisante |
| Par quelle copie puis-je la remplacer ? | Copie réellement conservée, identifiable en jeu |
| Dans quel usage cette comparaison tient-elle ? | Rôle Parent/GP, course, profil et même Ace |
| Qu’est-ce que j’abandonne ? | Facteurs et probabilités qui diminuent, même si le total augmente |
| Pourquoi garder cette autre copie ? | Rôles ou actifs qui justifient sa conservation dans le rapport |
| Puis-je transférer en pratique ? | Vérification personnelle de l’usage actuel et du coût de reproduction |

Un score élevé en jeu aide à retrouver une Uma ; il ne prouve pas que ses
facteurs sont meilleurs. Un indice élevé dans le modèle est un résultat de
calcul ; il ne mesure pas directement le temps nécessaire pour refaire son
farm. Ces distinctions doivent rester visibles sans obliger le joueur à
apprendre le schéma interne du rapport.

Le scénario courant comporte un parent local et un parent distant emprunté.
Deux copies locales affichées côte à côte sont donc deux options pour le même
emplacement. Leur compatibilité mutuelle ne justifie pas le verdict. Une
grande lignée commune réunissant les deux options risquerait d’évoquer une
paire de parents et de donner un sens erroné à la comparaison.

## Les limites de la présentation précédente

Le tableau rendait les copies accessibles, mais les indices Parent/GP
apparaissaient comme l’explication principale. Leurs meilleurs contextes
peuvent différer entre copies : les soustraire mentalement ne démontre pas
un avantage sur le même Ace. Une colonne de couverture pouvait aussi lister
toute la sélection conservée du costume et laisser croire que chaque membre
était indispensable à chaque remplacement.

Les premiers exemples amélioraient la traçabilité : ils ouvraient le bon
remplaçant, le bon rôle et le bon Ace. Ils expliquaient encore surtout
« l’indice passe de X à Y ». Pour un joueur, la réponse utile est davantage
« cette branche apporte Power et améliore certains héritages, mais perd
Speed ou Groundwork ». La différence de facteurs donne un objet concret
à discuter et à vérifier.

La lignée apporte cette provenance, mais lire six cartes détaillées est un
travail de comparaison. Il faut retrouver les différences entre inventaires,
se rappeler le rôle et déterminer si une étoile supplémentaire intervient
dans le modèle. La mettre seule en première vue laisse ce travail au joueur.

Enfin, les réglages, les cinq compteurs et les commandes générales occupaient
une grande partie des petites fenêtres. Une première capture à 960 × 700
révélait aussi des contraintes de largeur incompatibles avec cette taille.
La revue des rendus a conduit à réduire cette surface et à conserver les
commandes de vérification en dehors de la zone de défilement.

## Comparaison des approches

| Approche | Apport | Limite dans ce cas | Choix |
| --- | --- | --- | --- |
| Grand tableau de tous les facteurs | Inventaire exhaustif, facile à trier | Beaucoup de bruit, contexte et provenance peu lisibles | Audit secondaire |
| Lignée comme premier écran | Sources des facteurs immédiatement visibles | Le joueur doit découvrir lui-même les différences importantes | Conservée comme outil de vérification |
| Explication textuelle seule | Verdict rapide à lire | Difficile de corroborer la phrase ou de repérer ce qu’elle omet | Reliée à des témoins et inventaires vérifiables |
| Assistant en plusieurs étapes | Parcours guidé | Allers-retours coûteux pour examiner plusieurs copies du même costume | Écarté pour cette passe |
| Liste et panneau de décision, puis comparaison | Identité, motif et exemple réunis ; exploration sur demande | Demande une sélection d’exemples explicite et honnête | Retenue |

La préférence pour cette dernière approche est une inférence de conception
à partir des tâches et contraintes décrites ici. Elle devra être confrontée
au test local du joueur.

## Architecture d’information retenue

### La collection

La liste affiche par défaut le verdict et l’identité en jeu. Les indices
globaux, percentiles et colonnes de diagnostic restent disponibles dans le
menu de l’en-tête. Une nouvelle clé de disposition évite de réutiliser une
ancienne configuration de colonnes trop chargée.

Le filtre par costume permet de revoir les 62 Opera O ensemble. Il commence
par le nom du personnage, pour que les longs noms de costume ne masquent
pas toute l’identité dans une petite liste. La recherche accepte les noms
et les scores en jeu. Les identifiants techniques ne servent pas de libellés
ni de critères de recherche visibles.

Le filtre de verdict inclut les copies protégées dont le diagnostic
correspond au filtre. Leur badge reste « Protégé » et distingue le diagnostic
de l’autorisation de transférer. Les protéger ne doit pas les rendre
incomparables : le joueur a besoin de voir qu’un verrou masque parfois une
redondance théorique.

Les réglages et le résumé global sont repliés. Le mode et le périmètre
effectifs restent écrits dans l’en-tête. Les dates CM inconnues restent
signalées même lorsque le calendrier détaillé est replié. Le statut périmé
reste visible lorsque les paramètres ou le calendrier invalident le rapport.

### Le panneau de décision

L’identité, le rang et le score en jeu restent visibles pendant le défilement.
Le nombre conservé pour le costume inclut les protections. Un ancien rapport
sans marqueur de sélection affiche seulement le nombre de copies : il ne
fabrique pas un nombre nul de copies conservées.

La phrase de verdict distingue les situations : une copie conservée suffit,
plusieurs copies conservées couvrent les rôles, un actif justifie la
conservation, ou le rapport ne suffit pas à conclure. Pour les copies
conservées, les skills stratégiques sont présentés avant les longues listes
de rôles. Opera O au score 22 100 expose ainsi Straight Descent directement.
Les codes de rôle internes sont remplacés par des libellés humains.

Les onglets Parent et Futur grand-parent sélectionnent l’exemple affiché.
Une perte nette ajoute « Perte à vérifier ». Le panneau donne l’identité du
remplaçant et l’écart pour ce cas, puis un gain et une concession pertinents.
Il indique que d’autres différences existent. Ce résumé est volontairement
court ; il ne prétend pas épuiser le contenu des deux copies.

« Vérifier cet exemple… » reste accessible en bas du panneau. « Explorer… »
permet d’étudier les autres comparaisons, y compris pour une copie conservée
ou un rapport sans témoin guidé. L’expansion des détails avancés reste possible.

### La vérification

Le dialogue s’ouvre sur « Gains et pertes » et sur le témoin exact choisi.
Les deux identités en jeu et les indices du modèle sont affichés séparément.
Le rôle, la course et l’Ace restent indiqués lorsque les quatre sélecteurs
sont repliés. Les aptitudes faibles produisent une indication exploratoire.

La lignée est un onglet adjacent. Elle montre les deux branches alternatives,
leurs sources de facteurs et les cartes inspectables. En Parent, les deux GP
de chaque branche participent au calcul. En futur GP, seuls les facteurs
propres interviennent dans le modèle du prototype ; l’historique du farm
reste consultable séparément. Pour un ancien modèle qui pondère encore la
génération White historique, l’explication le signale explicitement.

La matrice des niches et les tableaux de composantes, Whites exactes,
facteurs/G1 et rôles préservés restent accessibles. Explorer un autre cas
ne transforme pas cette comparaison en nouvelle preuve du verdict initial.

## Choisir des exemples utiles sans masquer une exception

Un bon exemple doit être à la fois traçable et compréhensible. Le premier
témoin le moins favorable pouvait utiliser un Ace avec Dirt G ou un style F.
Le calcul reste celui du rapport, mais il illustre mal un usage habituel.
Un tel exemple doit être signalé comme exploratoire, pas présenter un build
immédiatement réalisable.

Pour chaque rôle, la sélection applique donc cet ordre aux témoins vérifiables :

1. Toute perte nette est prioritaire ; le cas le plus défavorable est retenu.
2. Sans perte nette, préférer un Ace dont les trois aptitudes sont au moins B,
   puis retenir le cas le moins favorable de cet ensemble.
3. Sans témoin de ce type, utiliser le cas disponible le moins favorable et
   signaler ses aptitudes exploratoires lorsqu’elles sont connues.

Le seuil B est un critère de lisibilité des exemples, pas une certification
de faisabilité ou d’optimalité du build. Il ne change aucune décision du
moteur. Il ne tient pas compte des supports, des compétences du joueur ou
du parent distant effectivement emprunté.

Chaque témoin doit identifier un membre de la sélection conservée, appartenir
au même groupe de costume, utiliser le même rôle et le même Ace, et retrouver
les valeurs enregistrées des deux vecteurs de scores. Un écart de reconstruction,
une valeur non finie ou des données absentes interdisent de présenter une
décomposition comme vérifiée.

Deux exemples ne prouvent pas à eux seuls toute la couverture collective.
Ils servent à comprendre et à contester le choix. La couverture complète
appartient aux obligations du portefeuille et à l’audit des niches. Le total
de copies conservées du costume ne doit pas être interprété comme le nombre
de remplaçants requis pour chaque copie proposée.

## Sens exact des gains et concessions

Les Whites sont retenues selon leur utilité dans le contexte et leur
contribution calculée. En Parent, leur comparaison peut montrer une
probabilité d’héritage issue du modèle. En GP, elle montre les étoiles des
sources propres ; une probabilité d’héritage future n’est pas inventée.

Les Bleues et les Roses pertinentes montrent leurs étoiles. Les étoiles
de toute la branche comptent en Parent, les facteurs propres en GP. Les
Roses étrangères au profil courant restent dans l’inventaire détaillé.
Les uniques et les G1 propres sont présentées lorsque leur composante
intervient dans le modèle.

L’ordre des différences de facteurs est une heuristique d’affichage basée
sur leur changement et leur pertinence contextuelle. Ce n’est pas une
attribution exacte de chaque point du score à une étoile. Une distribution
de facteurs, une affinité, un scénario ou une règle de plafonnement peuvent
modifier le résultat sans changer le simple total d’étoiles.

La section « Ce qui pèse dans l’indice » utilise, elle, les contributions
pondérées exactes reconstruites. Elle présente les trois principaux écarts
de composantes. Le tableau complet permet de retrouver le reste. Les
étoiles, les probabilités et les points ont des unités différentes ; ils
ne sont jamais additionnés entre eux dans l’explication.

Une absence de différence pertinente identifiée ne signifie pas « aucun
coût » ni « aucune perte possible ». Les facteurs non contextualisés, le
coût de refarm, l’usage actuel en course et les usages extérieurs au périmètre
ne sont pas couverts par cette phrase.

## Confrontation au rapport réel

Le rapport gelé du 11 octobre 2026 contient 258 copies et 48 contextes.
Les diagnostics sont 46 équivalences individuelles, 103 redondances
collectives, 99 conservations et 10 protections. Opera O conserve 16 copies
sur 62, protections incluses. Cette passe d’interface ne recalcule pas ce
portefeuille.

| Vérification sur les propositions du rapport | Résultat |
| --- | ---: |
| Propositions théoriques | 149 |
| Propositions avec au moins un témoin vérifiable | 148 |
| Un seul exemple de rôle disponible | 21 |
| Deux exemples de rôle disponibles | 127 |
| Aucun exemple exploitable | 1 |
| Comparaisons reconstruites | 275 |
| Comparaisons avec une concession parmi les différences retenues | 275 |
| Comparaisons positives avec une concession | 259 |
| Comparaisons avec perte nette | 16 |

Les 275 écarts correspondent aux vecteurs enregistrés. La somme des
contributions pondérées retrouve chaque écart total avec une erreur maximale
inférieure à 0,000000001 point. Cela vérifie la cohérence de l’explication
avec le modèle, pas l’exactitude absolue de ses hypothèses de jeu.

Air Groove [Empress Road] au score 17 342 n’a aucun témoin exploitable dans
ce rapport. L’interface le dit et conserve l’accès à l’exploration et aux
détails. Elle ne garantit pas qu’une nouvelle analyse suffirait à fournir
une preuve manquante.

Exemple concret : Opera O au score 11 496 est comparée à la copie conservée
11 240. Le score en jeu inférieur du remplaçant n’empêche pas ses facteurs
de produire un meilleur indice dans les cas retenus :

| Rôle et Ace de l’exemple | Indices étudiée → comparée | Gain concret | Concession concrète |
| --- | --- | --- | --- |
| Parent, Turf/Medium/Late Surger, Agnes Tachyon [Tach-nology] | 18,49 → 24,14 | Power 0★ → 3★ ; Corner Recovery environ 14% → 27% dans le modèle | Late Surger 2★ → 0★ ; Speed 1★ → 0★ |
| Futur GP, Turf/Medium/Late Surger, Admire Vega [Starry Nocturne] | 34,62 → 37,81 | Power propre 0★ → 3★ ; G1 propres 15 → 16 | Late Surger propre 2★ → 0★ ; Speed propre 1★ → 0★ |

Le dialogue permet de retrouver ces facteurs dans les cartes sources et
de discuter la valeur de la concession. Il n’impose pas que le joueur
considère ces usages comme les plus importants pour sa collection.

Une autre comparaison présente une perte nette de 2,109 points en futur GP
pour Oguri Cap [Starlight Beat] au score 12 354 face à la copie 11 849.
La copie étudiée peut donc rester meilleure dans un cas, tout en étant jugée
redondante sous la tolérance du portefeuille. La perte doit être visible,
pas remplacée par une explication disant simplement que l’autre est meilleure.

## Vérification visuelle et fonctionnelle

Des rendus natifs ont été inspectés à 1440 × 960 et 960 × 700, avec les
portraits en cache et sans réseau. Ils couvrent le panneau de décision,
les gains/pertes, le rôle Parent, le rôle GP et l’historique du farm.
À 960 × 700, l’identité et les boutons de vérification restent accessibles ;
les détails longs demandent du défilement. Les filtres ne doivent ni se
chevaucher ni faire disparaître la recherche.

Les vérifications automatisées portent sur la correspondance du témoin,
l’absence de fausse preuve historique, les concessions malgré un total
positif, l’exclusion de l’historique en GP, les modèles historiques pondérés,
les copies protégées, les comptes absents des anciens rapports, les états
périmés, les filtres, les petites fenêtres et la traduction FR/EN.

Le test local devrait répondre à ces questions, dans l’ordre :

1. En ouvrant une Opera O proposée, peut-on dire ce qui est couvert et nommer
   sa copie conservée sans lire les tableaux de calcul ?
2. Peut-on retrouver un facteur perdu, même si l’indice augmente ?
3. Le bouton de vérification ouvre-t-il exactement ce qu’on vient de lire ?
4. La lignée permet-elle de retrouver la provenance d’un facteur contesté ?
5. Une copie protégée reste-t-elle clairement un diagnostic seulement ?
6. Une copie conservée pour Straight Descent explique-t-elle cette obligation ?
7. Le cas sans preuve et les Aces exploratoires sont-ils reconnaissables ?
8. Peut-on passer rapidement à une autre copie du même costume et la retrouver
   dans le jeu grâce à son score/rang ?

Ces tâches constituent un protocole à essayer ; leur temps d’exécution et
leur taux de réussite n’ont pas encore été mesurés auprès de joueurs.

## Portée de l’implémentation

La mise à jour conserve Qt et réutilise la lignée et les assets existants.
Le choix repose sur les capacités nécessaires au prototype : tableau,
navigation, portraits en cache et inspection native. Une migration de
technologie ne résoudrait pas à elle seule les ambiguïtés de preuve et de
vocabulaire identifiées ici.

La production des motifs concrets est isolée de la présentation native.
Elle reconstruit les deux évaluations avec le modèle gelé du rapport et
refuse les données incohérentes. Cette séparation pourra être réutilisée
dans une autre interface sans réécrire les décisions du portefeuille.

Les pondérations, le solveur, les protections et les recommandations ne
changent pas dans cette passe. Les Whites ordinaires ne deviennent pas
des obligations de conservation. Aucune action de transfert n’est ajoutée.
Le coût de refarm et l’usage actuel en course restent à vérifier. White Loop
n’est pas réintroduit sur `main`.

## Références et interprétation

- [NN/g — Progressive Disclosure](https://www.nngroup.com/articles/progressive-disclosure/) :
  différer les outils spécialisés tout en gardant visibles les informations
  nécessaires à la tâche courante. Ici, les gains et concessions restent
  prioritaires ; les réglages détaillés et les tableaux complets sont secondaires.
- [NN/g — Recognition and Recall](https://www.nngroup.com/articles/recognition-and-recall/) :
  rendre les éléments utiles reconnaissables et disponibles plutôt que demander
  de les mémoriser. Ici, les identités en jeu, le rôle et le cas comparé restent
  visibles lors de la vérification.
- [Liao et Varshney — Human-Centered Explainable AI](https://arxiv.org/abs/2110.10790) :
  concevoir les explications à partir des besoins des utilisateurs. Ici, le
  besoin est de comprendre et de contester un remplacement de copie.

Le Transfer Helper est un moteur déterministe. Le dernier travail fournit
un cadre de réflexion sur les explications, pas une validation spécifique
du moteur ou de l’interface proposée.
