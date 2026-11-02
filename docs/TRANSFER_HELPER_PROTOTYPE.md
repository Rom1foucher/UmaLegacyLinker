# Archive du premier prototype Transfer Helper

Cette procédure et les chiffres ci-dessous décrivent uniquement le premier
prototype Transfer Helper. L’interface actuelle est la liste triée par score en
jeu décrite dans le [guide utilisateur](USER_GUIDE.md). Les raisons explicites
sont enregistrées dans `transfer_reason` (format 10) ; les rapports antérieurs
doivent être recalculés.

---

Ce patch complet vise `origin/main`, vérifié le 11 octobre 2026 au commit
`c8df8fc953c041c4a194e2ec488cbfe6ab2d21c4`. Il inclut le rework moteur, les
correctifs de compatibilité et toutes les passes UI/UX. Aucun ancien patch
n’est nécessaire sur cette base propre.
Aucune modification n’a été poussée sur GitHub. L’utiliser dans une copie locale
propre du dépôt ; conserver une sauvegarde des réglages et du dossier de sortie.

## Appliquer et lancer

Depuis la racine du dépôt, placer le fichier `.patch` téléchargé dans le dépôt
puis exécuter :

```sh
git apply --check UmaLegacyLinker-transfer-helper-complete-main-c8df8fc.patch
git apply UmaLegacyLinker-transfer-helper-complete-main-c8df8fc.patch
python -m pip install -r requirements-qt.txt
python qt_app.py
```

Si la vérification échoue, comparer la base locale au commit indiqué avant
application. Ne pas forcer le patch sur des changements locaux non sauvegardés.
Pour retirer le patch après test, sur les fichiers encore inchangés depuis son
application :

```sh
git apply --reverse --check UmaLegacyLinker-transfer-helper-complete-main-c8df8fc.patch
git apply --reverse UmaLegacyLinker-transfer-helper-complete-main-c8df8fc.patch
```

## Parcours à étudier

1. Dans **Données**, choisir le dernier `master.mdb` et l’export de collection.
2. Choisir un dossier de sortie dédié au prototype.
3. Dans **Transfer Helper**, garder **Audit exhaustif**, les prochaines CM et
   cinq CM maximum. Lancer une nouvelle analyse : les anciens rapports conservent
   leurs anciennes pondérations, même lorsque leur visualisation reste lisible.
4. Rechercher Opera O ou un **score en jeu**, sélectionner une copie puis
   **Comparer…**. Le score/rang en jeu identifie la copie ; l’**indice du modèle**
   explique le classement. Les identifiants techniques ne figurent pas dans cette UX.
5. Dans **Lignée comparée**, lire les principaux écarts de points. Les deux
   branches sont alternatives : elles ne forment jamais une paire locale.
   Les contours des facteurs signalent un surplus/déficit d’étoiles dans une
   branche ; ils ne représentent ni une probabilité ni un verdict de qualité.
6. Cliquer une carte, ou choisir un membre dans le sélecteur, pour retrouver
   tous ses facteurs. Les inventaires des cartes sont volontairement abrégés.
   **Ajuster** et le zoom permettent de naviguer dans les petites fenêtres.
7. Basculer sur **Futur grand-parent** : seuls les facteurs propres comptent.
   **Afficher l’historique du farm** montre les anciens parents sans modifier
   l’indice. Le coût de refaire cette copie reste inconnu.
8. Consulter **Niches comparées**, **Composantes du score**, **Whites exactes**,
   **Facteurs et G1**, puis **Rôles préservés**. Changer l’Ace ou la copie comparée
   pour vérifier si une perte est couverte par une autre copie conservée.
9. Vérifier une copie protégée : elle reste analysée et comparable, avec badge.
   Son verrou ou mémo reste respecté. Les projets White Loop ne sont pas
   intégrés à ce prototype sur `main`.

Les portraits utilisent le cache et le réglage **Images en ligne** existants.
L’interface reste utilisable sans réseau. Un GP provenant d’un snapshot sans
score/rang conserve une valeur inconnue ; aucun score n’est inventé.

## Ce qui change dans le moteur

- Pondérations propres au Transfer Helper : Bleues 20% et Whites 35% pour une
  branche Parent. Stamina reste plus valorisée que Power en Long.
- GP : facteurs propres et G1 propres. Affinité future inconnue et génération
  White historique ont un poids nul.
- Les paires locales et leurs recouvrements G1 ne pilotent plus la conservation
  par défaut. L’ancienne règle reste une option avancée explicitement désactivée.
- Straightaway Adept, All I’ve Got et les packages génériques ne constituent
  plus des obligations de protection. Les Whites utiles gardent leur contribution
  au score, notamment Uma Stan. Seule la liste explicite de skills build-defining
  peut imposer une protection conditionnelle ; elle contient Straight Descent
  par défaut.
- Chaque niche est comparée pour le même Ace. Le portefeuille peut couvrir
  plusieurs niches avec plusieurs copies, sans inventer un remplaçant universel.
- Le calendrier vient des dates Global du MDB. CM20 reste un contexte de
  préparation jusqu’au verrouillage final de l’équipe, pas seulement jusqu’à
  la sélection de ligue. Les dates ultérieures inconnues sont affichées comme telles.

Le mode exhaustif conserve aussi les Aces aux aptitudes faibles pour examiner
les possibilités expérimentales. Le dialogue affiche leurs aptitudes et un
badge exploratoire ; une telle comparaison n’atteste pas la faisabilité ni le
coût de monter ces aptitudes. La vue s’ouvre sur un usage enregistré de la copie,
puis la matrice permet d’inspecter les témoins les moins favorables.

## Résultat de référence et limites

Sur l’export fourni (258 copies) et `master(9).mdb`, avec les profils intégrés,
les réglages par défaut et le calendrier du **11 octobre 2026** :

| Diagnostic | Copies |
| --- | ---: |
| Conservées par le modèle | 99 |
| Protégées et conservées | 10 |
| Redondantes par couverture collective | 103 |
| Équivalentes avec un remplaçant individuel | 46 |
| Total conservé, protections incluses | 109 |
| Opera O conservées | 16 sur 62 |

Le portefeuille conserve chaque obligation modélisée, dans la tolérance de
2,5 points configurée. Les 516 meilleurs scores Parent/GP ont été reconstruits
à partir du rapport gelé, avec un écart maximal inférieur à 0,000001 point.
Ces chiffres permettent d’étudier les hypothèses du prototype. Ils ne constituent
pas une autorisation de transférer les 149 autres copies.

**Le coût de refarm et l’utilisation en course ne sont pas encore modélisés.**
Tous les enregistrements du prototype portent `transfer_eligible=false`.
`model_transfer_candidate` conserve le diagnostic théorique, distinct d’une
validation manuelle. Aucune copie n’est supprimée et aucune action en jeu n’est
exécutée. Le nombre conservé est un minimum sous les obligations et la tolérance
choisies, pas une mesure absolue de la valeur de la collection.

## Vérification développeur

```sh
python -m pip install pytest
python -m pytest -q
```

Pour un environnement Qt sans affichage, définir `QT_QPA_PLATFORM=offscreen`.
Le prototype a été vérifié avec Python 3.12 et PySide6 6.8.3, conformément aux
dépendances Qt du dépôt. Les rapports JSON/CSV gardent leurs clés techniques
pour la traçabilité ; les libellés visibles présentent les identités en jeu.


### Passe de lisibilité supplémentaire

- Le tableau affiche le costume puis le rang et le score en jeu sur une seconde
  ligne. Les colonnes de percentile et de diagnostic restent disponibles via
  le menu de l’en-tête ; la nouvelle disposition est mémorisée séparément.
- Double-cliquer une copie ouvre la comparaison des branches. Les deux indices
  et l’écart « comparée − étudiée » sont affichés côte à côte, avec le sens de
  l’avantage écrit en toutes lettres.
- Changer de copie comparée conserve le contexte et l’Ace sélectionnés. Cliquer
  une niche ouvre toujours son Ace critique. La carte inspectée est entourée.
- La lignée s’ajuste à la largeur à l’ouverture et au redimensionnement, jusqu’à
  un zoom minimal lisible de 75 %. Un zoom manuel reste respecté jusqu’à Ajuster.
  L’inspecteur détaillé est replié au départ ; cliquer une carte l’ouvre.
- Une recherche sans résultat propose de réinitialiser les filtres.

Cette passe ne change ni les scores, ni les protections, ni les décisions du moteur.


### Comprendre le verdict avant d’explorer le calcul

Le panneau de la copie commence par une explication courte du verdict et jusqu’à
deux exemples vérifiés dans le rapport, un par rôle Parent/GP. Les pertes nettes
sont prioritaires. Sans perte nette, le cas le moins favorable parmi les Aces
aux aptitudes utilisables est préféré ; à défaut, un cas exploratoire est montré.
Une perte éventuelle est explicitement affichée, même si elle est acceptée par le
modèle. Le lien de chaque exemple ouvre sa copie conservée, son rôle, son contexte
et son Ace exacts dans la lignée. Les diagnostics complets restent accessibles
via Afficher les détails avancés. Les exemples sont individuels ; ils ne forment
pas une paire locale et ne suffisent pas, seuls, à démontrer toute la couverture.

### Mise à jour de l’interface de décision

Cette mise à jour est incluse dans
`UmaLegacyLinker-transfer-helper-complete-main-c8df8fc.patch`. Le patch complet
s’applique directement sur la base propre indiquée plus haut. Il remplace la
succession des anciens patches ; ne pas les appliquer ensuite :

```sh
git apply --check UmaLegacyLinker-transfer-helper-complete-main-c8df8fc.patch
git apply UmaLegacyLinker-transfer-helper-complete-main-c8df8fc.patch
python qt_app.py
```

Le filtre par costume regroupe les copies à revoir. Le panneau garde le portrait,
le rang et le score en jeu visibles, puis expose le remplaçant, un gain et une
concession pertinents. **Vérifier cet exemple…** ouvre le témoin exact dans
**Gains et pertes** ; **Lignée comparée** permet d’en inspecter les sources.
**Explorer…** permet de changer de cas. Les détails complets restent disponibles.

Les réglages, le calendrier détaillé et les compteurs globaux sont repliés.
Le périmètre, les dates inconnues et l’état du rapport restent visibles.
Les indices globaux du tableau se réactivent via le menu de l’en-tête.

L’étude et le protocole de test local sont dans
[TRANSFER_HELPER_UX_STUDY.md](TRANSFER_HELPER_UX_STUDY.md).
