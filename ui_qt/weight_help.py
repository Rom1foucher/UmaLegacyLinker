from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from i18n import normalise_language, scoring_label
from ui_qt.weight_controls import is_percentage_setting, is_probability_setting


@dataclass(frozen=True)
class WeightHelp:
    summary: str
    impact: str
    scope: str
    low_label: str
    high_label: str
    advanced: bool = False


def _pick(language: str, french: str, english: str) -> str:
    return english if normalise_language(language) == "en" else french


def _label(key: str, language: str) -> str:
    return scoring_label(key, language)


def _scope(path: Sequence[str], language: str) -> str:
    if "parent_pair" in path:
        return _pick(language, "Paire finale", "Final pair")
    if "parent_branch" in path:
        return _pick(language, "Branche parent", "Parent branch")
    if "future_grandparent" in path:
        return _pick(language, "Futur grand-parent", "Future grandparent")
    if path and path[0] == "uma_moe_pair":
        return "uma.moe"
    if path and path[0] == "transfer_helper":
        return "Transfer Helper"
    if path and path[0] == "future_grandparent_heuristics":
        return _pick(language, "Futur grand-parent", "Future grandparent")
    if path and path[0] in {"aptitude_inheritance", "future_grandparent_heuristics"}:
        return _pick(language, "Aptitudes", "Aptitudes")
    if path and path[0] in {
        "blue_stat_weights_by_distance",
        "blue_star_quality",
        "blue_score_influence_by_distance",
        "blue_neutral_score",
    }:
        return "Blue Sparks"
    if path and path[0] in {
        "white_inheritance",
        "white_saturation",
        "white_generation",
        "position_transmission",
    }:
        return "White Skills"
    if path and path[0] == "course_conditions":
        return _pick(language, "Conditions de course", "Race conditions")
    return _pick(language, "Score de lignée", "Lineage score")


def _scale_labels(path: Sequence[str], value: object, language: str) -> tuple[str, str]:
    root = path[0] if path else ""
    leaf = path[-1] if path else ""
    if root == "transfer_helper" and any(
        token in leaf for token in ("floor", "minimum", "margin", "tolerance")
    ):
        return (
            _pick(language, "Plus permissif", "More permissive"),
            _pick(language, "Plus strict", "Stricter"),
        )
    if root == "course_conditions" and (
        leaf == "active_green_floor" or "floors" in path
    ):
        return (
            _pick(language, "Aucun plancher", "No floor"),
            _pick(language, "Plancher maximal", "Maximum floor"),
        )
    if is_probability_setting(path):
        return (
            _pick(language, "Aucune chance", "No chance"),
            _pick(language, "Chance maximale", "Maximum chance"),
        )
    if is_percentage_setting(path, value):
        return (
            _pick(language, "Ignoré", "Ignored"),
            _pick(language, "Plus prioritaire", "Higher priority"),
        )
    if root in {"white_saturation", "race_saturation"} or (
        root == "white_generation" and path[-1:] == ("saturation",)
    ):
        return (
            _pick(language, "Sature tôt", "Earlier saturation"),
            _pick(language, "Sature tard", "Later saturation"),
        )
    return (_pick(language, "Moins", "Less"), _pick(language, "Plus", "More"))


def _component_impact(component: str, language: str) -> str:
    impacts = {
        "distance_s": (
            "Augmenter favorise les lignées qui sécurisent le rang S en distance, même si leurs autres Sparks sont moins forts.",
            "Increasing it favours lineages that secure an S distance rank, even when their other Sparks are weaker.",
        ),
        "pink_other": (
            "Augmenter donne davantage de valeur aux aptitudes de surface et de style, en plus de la contrainte Distance S.",
            "Increasing it gives more value to surface and running-style aptitudes beyond the Distance S constraint.",
        ),
        "white_skill": (
            "Augmenter privilégie les lignées qui transmettent des White Skills utiles avec une bonne probabilité.",
            "Increasing it favours lineages that can inherit useful White Skills with good probability.",
        ),
        "race_scenario": (
            "Augmenter renforce la valeur des Race et Scenario Sparks dans le score final.",
            "Increasing it gives Race and Scenario Sparks more influence on the final score.",
        ),
        "blue": (
            "Augmenter privilégie la qualité et la pertinence des Blue Sparks pour la distance choisie.",
            "Increasing it favours Blue Spark quality and relevance for the selected distance.",
        ),
        "unique": (
            "Augmenter donne davantage de poids aux Uniques vertes héritées dans la lignée.",
            "Increasing it gives inherited green Unique Sparks more influence.",
        ),
        "affinity": (
            "Augmenter favorise les candidats dont l’affinité moderne avec l’Ace et le parent est élevée.",
            "Increasing it favours candidates with strong modern affinity to the Ace and target parent.",
        ),
        "g1_potential": (
            "Augmenter valorise davantage les G1 communes et le potentiel de liens G1 du futur parent.",
            "Increasing it gives more value to shared G1 races and future-parent G1-link potential.",
        ),
        "pink": (
            "Augmenter favorise les futurs grands-parents qui portent des Pink Sparks directement utiles.",
            "Increasing it favours future grandparents carrying directly useful Pink Sparks.",
        ),
        "white_generation": (
            "Augmenter favorise les lignées capables de générer de bons White Sparks pendant la fabrication du parent.",
            "Increasing it favours lineages that can generate useful White Sparks while producing the parent.",
        ),
    }
    french, english = impacts.get(
        component,
        (
            "Augmenter donne davantage d’influence à cette composante dans le classement.",
            "Increasing it gives this component more influence in the ranking.",
        ),
    )
    return _pick(language, french, english)


_TRANSFER_HELP: dict[str, tuple[str, str, str, str]] = {
    "competitive_score_floor": (
        "Score absolu à partir duquel un rôle commence à être considéré comme compétitif.",
        "Absolute score at which a role starts to count as competitive.",
        "L’augmenter ignore davantage de niches faibles et rend le verdict plus conservateur.",
        "Increasing it ignores more weak niches and makes verdicts more conservative.",
    ),
    "dominance_tolerance": (
        "Petit écart autorisé lorsqu’une copie est comparée à son remplaçant dans chaque niche viable.",
        "Small allowed deficit when a copy is compared with its replacement in each viable niche.",
        "L’augmenter tolère un remplaçant légèrement moins bon dans une niche isolée.",
        "Increasing it allows a replacement to be slightly worse in an isolated niche.",
    ),
    "dominance_mean_margin": (
        "Avance moyenne minimale exigée pour confirmer qu’un remplaçant domine réellement une copie.",
        "Minimum average lead required to confirm that a replacement truly dominates a copy.",
        "L’augmenter exige un avantage moyen plus net avant de proposer un transfert sûr.",
        "Increasing it requires a clearer average advantage before suggesting a safe transfer.",
    ),
    "include_course_presets": (
        "Ajoute les Champion Meetings configurées aux contextes analysés.",
        "Adds configured Champion Meetings to the analysed contexts.",
        "Désactiver accélère l’analyse mais peut masquer une niche propre à une course précise.",
        "Disabling it speeds up analysis but can hide a niche tied to a specific race.",
    ),
    "upcoming_cm_limit": (
        "Nombre de prochaines Champion Meetings incluses dans l’audit de collection.",
        "Number of upcoming Champion Meetings included in the collection audit.",
        "L’augmenter couvre plus de courses, au prix d’un calcul plus long et de verdicts plus conservateurs.",
        "Increasing it covers more races at the cost of longer analysis and more conservative verdicts.",
    ),
    "include_team_trials": (
        "Ajoute les profils Team Trials aux contextes parent et grand-parent.",
        "Adds Team Trials profiles to parent and grandparent contexts.",
        "Activer protège les vétérans utiles hors Champion Meeting.",
        "Enabling it protects veterans that are useful outside Champion Meetings.",
    ),
    "include_generic_profiles": (
        "Ajoute des profils génériques surface × distance en plus des courses connues.",
        "Adds generic surface × distance profiles in addition to known races.",
        "Activer élargit fortement la couverture et réduit le nombre de transferts considérés sûrs.",
        "Enabling it greatly broadens coverage and reduces the number of transfers considered safe.",
    ),
    "minimum_competitive_contexts": (
        "Nombre de contextes compétitifs nécessaires pour qualifier une valeur comme répétée.",
        "Number of competitive contexts required for a value to count as recurring.",
        "L’augmenter distingue mieux les profils polyvalents des niches ponctuelles.",
        "Increasing it separates versatile profiles from one-off niches more strictly.",
    ),
    "minimum_distinct_profiles": (
        "Nombre de profils de course différents nécessaires pour confirmer une valeur polyvalente.",
        "Number of distinct race profiles required to confirm versatile value.",
        "L’augmenter demande une utilité plus variée avant de renforcer un verdict de conservation.",
        "Increasing it requires broader usefulness before strengthening a keep verdict.",
    ),
    "competitive_utility_floor": (
        "Seuil de qualité relative combinant score absolu, proximité au leader et percentile.",
        "Relative-quality threshold combining absolute score, leader proximity, and percentile.",
        "L’augmenter réserve le statut compétitif aux meilleures copies du pool.",
        "Increasing it reserves competitive status for the strongest copies in the pool.",
    ),
    "elite_utility_floor": (
        "Seuil de qualité relative utilisé pour identifier les performances élite.",
        "Relative-quality threshold used to identify elite performance.",
        "L’augmenter rend le label élite plus rare sans changer directement le score brut.",
        "Increasing it makes the elite label rarer without directly changing raw scores.",
    ),
    "minimum_absolute_floor_ratio": (
        "Part minimale du seuil absolu qu’une niche doit atteindre avant d’être jugée viable.",
        "Minimum share of the absolute floor a niche must reach before it can be viable.",
        "L’augmenter élimine les niches où toutes les copies restent globalement faibles.",
        "Increasing it removes niches where every copy remains globally weak.",
    ),
    "utility_absolute_weight": (
        "Part du score absolu dans la qualité compétitive du Transfer Helper.",
        "Share of absolute score in Transfer Helper competitive utility.",
        "L’augmenter favorise les copies fortes en valeur brute, même dans un pool très relevé.",
        "Increasing it favours copies with strong raw value, even in a very strong pool.",
    ),
    "utility_leader_weight": (
        "Part de la proximité au meilleur candidat local dans la qualité compétitive.",
        "Share of proximity to the best local candidate in competitive utility.",
        "L’augmenter privilégie les copies proches du leader de leur contexte.",
        "Increasing it favours copies that stay close to the leader in their context.",
    ),
    "utility_percentile_weight": (
        "Part du rang percentile dans la qualité compétitive.",
        "Share of percentile rank in competitive utility.",
        "L’augmenter donne plus d’importance à la position relative dans l’ensemble du pool.",
        "Increasing it gives relative position in the whole pool more importance.",
    ),
}


def describe_weight(path: Sequence[str], value: Any, language: str) -> WeightHelp:
    path = tuple(path)
    root = path[0] if path else ""
    leaf = path[-1] if path else ""
    scope = _scope(path, language)
    low, high = _scale_labels(path, value, language)
    advanced = isinstance(value, (list, dict))

    if root == "mode_weights" and len(path) >= 3:
        component = path[-1]
        summary = _pick(
            language,
            f"Poids indépendant de « {_label(component, language)} » dans le score {scope.lower()}. Le moteur le normalise avec les poids voisins sans modifier leurs valeurs.",
            f"Independent weight of “{_label(component, language)}” in the {scope.lower()} score. The engine normalises it with neighbouring weights without changing their values.",
        )
        return WeightHelp(summary, _component_impact(component, language), scope, low, high)

    if root == "blue_stat_weights_by_distance" and len(path) == 3:
        distance = _label(path[1], language)
        stat = _label(path[2], language)
        summary = _pick(
            language,
            f"Importance relative de {stat} parmi les Blue Sparks pour les courses {distance}.",
            f"Relative importance of {stat} among Blue Sparks for {distance} races.",
        )
        impact = _pick(
            language,
            f"L’augmenter fait monter les lignées qui cumulent des Blue Sparks {stat} sur ce profil de distance.",
            f"Increasing it raises lineages carrying more {stat} Blue Sparks for this distance profile.",
        )
        return WeightHelp(summary, impact, scope, low, high)

    if root in {"blue_star_quality", "unique_star_quality", "star_quality"}:
        stars = _label(leaf, language)
        family = {
            "blue_star_quality": "Blue Spark",
            "unique_star_quality": _pick(language, "Unique verte", "green Unique"),
            "star_quality": _pick(language, "Race ou Scenario Spark", "Race or Scenario Spark"),
        }[root]
        summary = _pick(
            language,
            f"Qualité relative attribuée à un {family} {stars}, comparée au palier 3★.",
            f"Relative quality assigned to a {stars} {family}, compared with the 3★ tier.",
        )
        impact = _pick(
            language,
            f"L’augmenter réduit l’écart de valeur entre ce palier et les meilleurs {family}s.",
            f"Increasing it narrows the value gap between this tier and the best {family}s.",
        )
        return WeightHelp(summary, impact, scope, low, high)

    if root == "position_transmission":
        position = _label(leaf, language)
        summary = _pick(
            language,
            f"Coefficient appliqué aux Sparks portés à la position « {position} » dans la lignée.",
            f"Multiplier applied to Sparks carried in the “{position}” lineage position.",
        )
        impact = _pick(
            language,
            "L’augmenter rend les facteurs de cette génération plus importants par rapport aux autres positions.",
            "Increasing it makes factors from this generation more important than those in other positions.",
        )
        return WeightHelp(summary, impact, scope, low, high)

    if root in {"white_saturation", "race_saturation"} or (
        root == "white_generation" and leaf == "saturation"
    ):
        family = _pick(language, "White Skills", "White Skills") if root != "race_saturation" else _pick(language, "Race et Scenario Sparks", "Race and Scenario Sparks")
        summary = _pick(
            language,
            f"Échelle de rendement décroissant utilisée quand plusieurs {family} utiles s’additionnent.",
            f"Diminishing-return scale used when several useful {family} contributions are added together.",
        )
        impact = _pick(
            language,
            "L’augmenter retarde la saturation : les lignées très riches continuent à gagner davantage de score.",
            "Increasing it delays saturation, so very dense lineages continue gaining more score.",
        )
        return WeightHelp(summary, impact, scope, low, high)

    if root == "race_factor":
        is_scenario = leaf == "scenario_per_star_quality"
        family = _pick(language, "Scenario Sparks", "Scenario Sparks") if is_scenario else _pick(language, "Race Sparks", "Race Sparks")
        summary = _pick(
            language,
            f"Valeur brute apportée par les {family}, avant la saturation et le poids global.",
            f"Raw value contributed by {family} before saturation and the global component weight.",
        )
        impact = _pick(
            language,
            f"L’augmenter rend chaque {family[:-1] if family.endswith('s') else family} plus rentable dans le classement.",
            f"Increasing it makes each {family[:-1] if family.endswith('s') else family} more valuable in the ranking.",
        )
        return WeightHelp(summary, impact, scope, low, high)

    if root == "affinity":
        if leaf.endswith("thresholds"):
            summary = _pick(
                language,
                "Courbe qui convertit une affinité ou un nombre de G1 brut en un score normalisé de 0 à 100.",
                "Curve that converts raw affinity or G1 count into a normalised score from 0 to 100.",
            )
            impact = _pick(
                language,
                "Monter un point de la courbe rend ce niveau brut plus récompensé ; déplacer son entrée change le palier requis.",
                "Raising a curve point rewards that raw level more; moving its input changes the required threshold.",
            )
            return WeightHelp(summary, impact, scope, low, high, True)
        if leaf == "g1_common_bonus":
            return WeightHelp(
                _pick(language, "Bonus d’affinité ajouté pour chaque G1 commune sur un lien visible.", "Affinity bonus added for each shared G1 race on a visible link."),
                _pick(language, "L’augmenter favorise les lignées qui répètent les mêmes G1 entre leurs membres.", "Increasing it favours lineages whose members repeat the same G1 races."),
                scope, low, high,
            )
        if leaf == "same_character_compatibility":
            return WeightHelp(
                _pick(language, "Compatibilité de base utilisée lorsque deux costumes représentent le même personnage.", "Base compatibility used when two costumes represent the same character."),
                _pick(language, "La valeur par défaut n’accorde aucun bonus ; l’augmenter atténue cette incompatibilité.", "The default grants no bonus; increasing it softens this incompatibility."),
                scope, low, high, True,
            )
        return WeightHelp(
            _pick(language, "Moteur d’affinité utilisé pour calculer les liens de la lignée.", "Affinity engine used to calculate lineage links."),
            _pick(language, "Ce choix structure le calcul complet ; ne le change que pour un profil compatible.", "This choice shapes the full calculation; change it only for a compatible profile."),
            scope, low, high, True,
        )

    if root == "course_conditions":
        condition = _label(leaf, language)
        if "modes" in path:
            summary = _pick(
                language,
                f"Méthode utilisée pour appliquer la condition « {condition} » à une Green Skill.",
                f"Method used to apply the “{condition}” condition to a Green Skill.",
            )
            impact = _pick(
                language,
                "« Plancher » conserve la meilleure valeur existante ; « Remplacement » impose la valeur configurée.",
                "“Minimum floor” keeps the better existing value; “Override” enforces the configured value.",
            )
            return WeightHelp(summary, impact, scope, low, high, True)
        summary = _pick(
            language,
            f"Valeur minimale conservée lorsqu’une Green Skill correspondant à « {condition} » est active.",
            f"Minimum retained value when a Green Skill matching “{condition}” is active.",
        )
        impact = _pick(
            language,
            "L’augmenter récompense davantage les Greens compatibles avec la course exacte.",
            "Increasing it rewards Greens that match the exact race conditions more strongly.",
        )
        return WeightHelp(summary, impact, scope, low, high)

    if root == "white_generation":
        if leaf == "bonus_per_lineage_copy":
            summary = _pick(language, "Bonus de génération ajouté pour chaque membre portant déjà la même White Skill.", "Generation bonus added for each lineage member already carrying the same White Skill.")
            impact = _pick(language, "L’augmenter favorise les répétitions de Whites utiles dans la branche de fabrication.", "Increasing it favours repeated useful Whites in the production branch.")
        else:
            summary = _pick(language, "Nombre maximal de copies d’une même White Skill prises en compte dans la lignée.", "Maximum number of copies of the same White Skill counted in the lineage.")
            impact = _pick(language, "L’augmenter permet aux lignées très redondantes de continuer à recevoir un bonus.", "Increasing it lets highly redundant lineages keep receiving a bonus.")
        return WeightHelp(summary, impact, scope, low, high)

    if root == "uma_moe_pair":
        if len(path) > 1 and path[1] in {"weights", "preselection_weights"}:
            component = leaf
            stage = _pick(language, "score final", "final score") if path[1] == "weights" else _pick(language, "présélection rapide", "fast preselection")
            summary = _pick(language, f"Part de « {_label(component, language)} » dans le {stage} des paires uma.moe.", f"Share of “{_label(component, language)}” in the uma.moe pair {stage}.")
            impact = _component_impact(component, language)
            return WeightHelp(summary, impact, scope, low, high)
        if leaf.endswith("thresholds"):
            return WeightHelp(
                _pick(language, "Courbe de conversion utilisée pour normaliser cette mesure uma.moe sur 100 points.", "Conversion curve used to normalise this uma.moe measure to 100 points."),
                _pick(language, "Modifier les points change les paliers à partir desquels une paire est considérée faible, bonne ou excellente.", "Editing the points changes the thresholds at which a pair is considered weak, good, or excellent."),
                scope, low, high, True,
            )
        if leaf == "planned_g1_budget_default":
            summary = _pick(language, "Nombre de G1 supposées réalisables pendant la fabrication du parent.", "Number of G1 races assumed achievable while producing the parent.")
            impact = _pick(language, "L’augmenter donne plus de place au potentiel G1, sans inventer de lien déjà acquis.", "Increasing it gives G1 potential more room without treating an unearned link as guaranteed.")
        elif leaf == "single_g1_weight_default":
            summary = _pick(language, "Valeur relative d’une G1 présente sur un seul des deux grands-parents.", "Relative value of a G1 race present on only one of the two grandparents.")
            impact = _pick(language, "L’augmenter rapproche une G1 unilatérale de la valeur d’une G1 commune aux deux côtés.", "Increasing it brings a one-sided G1 closer to the value of a G1 shared by both sides.")
        else:
            summary = _pick(language, "Courbe de présélection du potentiel combiné des trois membres de la branche GP.", "Preselection curve for the combined potential of the three GP-branch members.")
            impact = _pick(language, "La rendre plus généreuse conserve davantage de candidats pour l’évaluation complète.", "Making it more generous keeps more candidates for full evaluation.")
            advanced = True
        return WeightHelp(summary, impact, scope, low, high, advanced)

    if root == "transfer_helper" and leaf in _TRANSFER_HELP:
        fr_summary, en_summary, fr_impact, en_impact = _TRANSFER_HELP[leaf]
        return WeightHelp(
            _pick(language, fr_summary, en_summary),
            _pick(language, fr_impact, en_impact),
            scope, low, high,
        )

    if root == "aptitude_inheritance":
        dimension = next((part for part in path if part in {"distance", "surface", "style"}), None)
        dimension_label = _label(dimension, language) if dimension else _pick(language, "aptitude", "aptitude")
        if "pink_base_proc_rates" in path:
            stars = _label(leaf, language)
            summary = _pick(language, f"Chance de base qu’un Pink Spark {stars} proc pendant un Inspiration Event.", f"Base chance for a {stars} Pink Spark to proc during an Inspiration Event.")
            impact = _pick(language, "L’augmenter améliore directement P(A) et P(S) pour les lignées qui portent ce palier d’étoiles.", "Increasing it directly improves P(A) and P(S) for lineages carrying this star tier.")
        elif leaf == "inspiration_event_count":
            summary = _pick(language, "Nombre d’Inspiration Events indépendants simulés pour chaque Spark d’aptitude.", "Number of independent Inspiration Events simulated for each aptitude Spark.")
            impact = _pick(language, "L’augmenter accroît fortement les probabilités finales ; utilise uniquement le nombre réellement disponible en jeu.", "Increasing it strongly raises final probabilities; use only the number actually available in game.")
        elif leaf == "ignore_multi_rank_procs":
            summary = _pick(language, "Force le modèle à compter chaque proc comme exactement un rang d’aptitude.", "Forces the model to count each proc as exactly one aptitude rank.")
            impact = _pick(language, "Désactiver demanderait un modèle fiable des rares procs multi-rangs ; le réglage sûr est activé.", "Disabling it requires a reliable model of rare multi-rank procs; enabled is the safe setting.")
        elif "dimension_weights_by_mode" in path:
            summary = _pick(language, f"Importance relative de l’aptitude {dimension_label} dans ce score d’héritage.", f"Relative importance of {dimension_label} aptitude in this inheritance score.")
            impact = _pick(language, f"L’augmenter favorise les lignées qui améliorent surtout {dimension_label}, par rapport aux deux autres aptitudes.", f"Increasing it favours lineages that mainly improve {dimension_label} over the other two aptitudes.")
        elif "partial_scoring" in path:
            summary = _pick(language, "Paramètre du score partiel utilisé lorsqu’une branche seule ne permet pas encore de connaître la paire finale.", "Partial-score parameter used when a single branch does not yet reveal the final pair.")
            impact = _pick(language, "L’augmenter donne davantage d’importance à ce signal dans l’estimation provisoire de Distance S.", "Increasing it gives this signal more influence in the provisional Distance S estimate.")
        elif leaf == "s_probability_curve":
            summary = _pick(language, f"Courbe qui transforme P(S) en utilité pour l’aptitude {dimension_label}.", f"Curve that converts P(S) into utility for {dimension_label} aptitude.")
            impact = _pick(language, "Relever une sortie récompense davantage cette probabilité ; déplacer une entrée change le palier requis.", "Raising an output rewards that probability more; moving an input changes the required threshold.")
            advanced = True
        elif "b_compensation" in path:
            summary = _pick(language, f"Seuil de compensation permettant d’accepter un départ B en {dimension_label}.", f"Compensation threshold used to accept a B start in {dimension_label}.")
            impact = _pick(language, "L’augmenter rend la compensation plus exigeante et écarte davantage de paires fragiles.", "Increasing it makes compensation stricter and rejects more fragile pairs.")
        else:
            start = "A" if "start_a" in leaf else ("B" if "start_b" in leaf else _pick(language, "sous B", "below B"))
            summary = _pick(language, f"Contribution de « {_label(leaf, language)} » au score {dimension_label} quand l’Ace démarre {start}.", f"Contribution of “{_label(leaf, language)}” to the {dimension_label} score when the Ace starts at {start}.")
            impact = _pick(language, "L’augmenter donne plus de poids à ce scénario de départ dans le diagnostic final.", "Increasing it gives this starting scenario more influence in the final diagnostic.")
        return WeightHelp(summary, impact, scope, low, high, advanced)

    if root == "blue_score_influence_by_distance":
        distance = _label(leaf, language)
        return WeightHelp(
            _pick(language, f"Influence globale des Blue Sparks sur le classement en {distance}.", f"Overall Blue Spark influence on rankings for {distance} races."),
            _pick(language, "La réduire rapproche un score Blue faible de la valeur neutre ; l’augmenter rend les Blues plus discriminantes.", "Reducing it pulls a weak Blue score towards neutral; increasing it makes Blues more discriminating."),
            scope, low, high,
        )

    if root == "blue_neutral_score":
        return WeightHelp(
            _pick(language, "Point neutre vers lequel le score Blue est ramené quand son influence par distance est réduite.", "Neutral point towards which the Blue score is pulled when distance-specific influence is reduced."),
            _pick(language, "L’augmenter rend les profils à faible influence Blue plus généreux ; le diminuer les rend plus sévères.", "Increasing it makes low-Blue-influence profiles more generous; decreasing it makes them harsher."),
            scope, low, high,
        )

    if root == "white_inheritance":
        if "base_proc_rates" in path or "race_base_proc_rates" in path:
            race = "race_base_proc_rates" in path
            stars = _label(leaf, language)
            family = "Race Spark" if race else "White Skill Spark"
            summary = _pick(language, f"Chance de base d’héritage d’un {family} {stars} par Inspiration Event.", f"Base inheritance chance of a {stars} {family} per Inspiration Event.")
            impact = _pick(language, "L’augmenter accroît la probabilité finale après affinité et répétitions dans la lignée.", "Increasing it raises final probability after affinity and repeated lineage copies are applied.")
        elif leaf == "inspiration_event_count":
            summary = _pick(language, "Nombre d’Inspiration Events indépendants utilisés pour projeter l’héritage des Whites.", "Number of independent Inspiration Events used to project White inheritance.")
            impact = _pick(language, "L’augmenter fait monter toutes les probabilités d’héritage ; conserve la valeur réelle du jeu.", "Increasing it raises every inheritance probability; keep the real in-game value.")
        elif leaf == "per_event_probability_cap":
            summary = _pick(language, "Plafond appliqué à la chance d’une White Skill pendant un seul événement.", "Cap applied to a White Skill chance during a single event.")
            impact = _pick(language, "Le réduire limite les lignées extrêmement empilées ; 100 % n’ajoute aucune limitation artificielle.", "Reducing it limits extremely stacked lineages; 100% adds no artificial cap.")
        else:
            summary = _pick(language, "Courbe qui transforme la probabilité d’obtenir une White Skill distincte en utilité de score.", "Curve that converts the probability of obtaining a distinct White Skill into score utility.")
            impact = _pick(language, "Elle permet de peu récompenser les chances anecdotiques et de valoriser la diversité utile avec rendement décroissant.", "It suppresses anecdotal chances and rewards useful diversity with diminishing returns.")
            advanced = True
        return WeightHelp(summary, impact, scope, low, high, advanced)

    if root == "future_grandparent_heuristics":
        stars = _label(leaf, language) if leaf in {"1", "2", "3"} else ""
        if "pink_dimension_weights" in path:
            dimension = _label(leaf, language)
            summary = _pick(language, f"Pertinence relative d’un Pink Spark de {dimension} sur un futur grand-parent.", f"Relative relevance of a {dimension} Pink Spark on a future grandparent.")
            impact = _pick(language, f"L’augmenter privilégie les GP qui portent l’aptitude {dimension} ciblée.", f"Increasing it favours GPs carrying the targeted {dimension} aptitude.")
        elif "pink_star_quality" in path:
            summary = _pick(language, f"Qualité attribuée à un Pink Spark {stars} dans le modèle simplifié du futur GP.", f"Quality assigned to a {stars} Pink Spark in the simplified future-GP model.")
            impact = _pick(language, "L’augmenter réduit l’écart avec les Pink Sparks 3★ lors de la présélection.", "Increasing it narrows the gap with 3★ Pink Sparks during preselection.")
        elif "pink_need_multiplier" in path:
            rank = _pick(language, "inférieure à A", "below A") if leaf == "below_a" else _pick(language, "déjà A ou S", "already A or S")
            summary = _pick(language, f"Multiplicateur de besoin quand l’aptitude de base de l’Ace est {rank}.", f"Need multiplier when the Ace’s base aptitude is {rank}.")
            impact = _pick(language, "L’augmenter donne davantage de valeur aux Pink Sparks qui répondent à ce niveau de besoin.", "Increasing it gives Pink Sparks that address this need level more value.")
        else:
            summary = _pick(language, f"Qualité directe attribuée à une White Skill {stars} sur un futur grand-parent.", f"Direct quality assigned to a {stars} White Skill on a future grandparent.")
            impact = _pick(language, "L’augmenter favorise ce palier d’étoiles avant que la lignée finale complète soit connue.", "Increasing it favours this star tier before the complete final lineage is known.")
        return WeightHelp(summary, impact, scope, low, high)

    title = _label(leaf, language) if leaf else _pick(language, "réglage", "setting")
    parent = _label(path[-2], language) if len(path) > 1 else _label(root, language)
    summary = _pick(
        language,
        f"Règle « {title} » dans le groupe « {parent} » du modèle de score.",
        f"Controls “{title}” in the “{parent}” scoring group.",
    )
    impact = _pick(
        language,
        "L’augmenter donne généralement plus d’importance à ce signal ; utilise le défaut si son rôle n’est pas clair.",
        "Increasing it generally gives this signal more influence; keep the default if its role is unclear.",
    )
    return WeightHelp(summary, impact, scope, low, high, advanced)
