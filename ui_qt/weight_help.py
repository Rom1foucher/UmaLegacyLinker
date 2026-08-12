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
    if path and path[0] in {"uma_moe_pair", "uma_moe_parent_search"}:
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
        "scenario_inheritance",
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
    if root == "transfer_helper" and "spark_protection" in path:
        if leaf == "enabled":
            return (
                _pick(language, "Désactivée", "Disabled"),
                _pick(language, "Activée", "Enabled"),
            )
        if leaf == "replacement_probability_tolerance":
            return (
                _pick(language, "Aucune tolérance", "No tolerance"),
                _pick(language, "Plus permissif", "More permissive"),
            )
        if leaf == "important_packages":
            return (
                _pick(language, "Aucun package", "No package"),
                _pick(language, "Packages personnalisés", "Custom packages"),
            )
        return (
            _pick(language, "Protection plus large", "Broader protection"),
            _pick(language, "Protection plus sélective", "More selective protection"),
        )
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
        "surface_aptitude": (
            "Augmenter privilégie les lignées qui sécurisent le rang initial visé sur la surface de la course, avant les autres aptitudes roses.",
            "Increasing it favours lineages that secure the targeted initial surface rank ahead of the other pink aptitudes.",
        ),
        "pink_other": (
            "Augmenter donne davantage de valeur aux aptitudes de style, en plus des contraintes Distance S et Surface.",
            "Increasing it gives more value to running-style aptitudes beyond the Distance S and Surface constraints.",
        ),
        "white_skill": (
            "Augmenter privilégie les lignées qui transmettent des White Skills utiles avec une bonne probabilité.",
            "Increasing it favours lineages that can inherit useful White Skills with good probability.",
        ),
        "race_scenario": (
            "Augmenter renforce la petite valeur statistique propre des Race Sparks. Les Scenario Sparks sont déjà intégrées aux Blues.",
            "Increasing it gives the small intrinsic stat value of Race Sparks more influence. Scenario Sparks are already included in Blues.",
        ),
        "blue": (
            "Augmenter privilégie la qualité des Blue Sparks et la valeur attendue des Scenario Sparks pour la distance choisie.",
            "Increasing it favours Blue Spark quality and the expected value of Scenario Sparks for the selected distance.",
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


_PARENT_SEARCH_HELP: dict[tuple[str, str], tuple[str, str, str, str]] = {
    ("retrieval", "enabled"): (
        "Active la répartition du budget API en cohortes Distance, Surface et Large au lieu d’une seule requête triée par whites.",
        "Enables splitting the API budget into Distance, Surface, and Broad cohorts instead of a single white-sorted query.",
        "Désactiver revient à l’échantillon unique : les branches riches en roses nécessaires peuvent disparaître du pool avant tout scoring.",
        "Disabling it returns to the single sample, where branches rich in the required pinks can vanish from the pool before any scoring.",
    ),
    ("retrieval", "surface_cohort_enabled"): (
        "Autorise la cohorte dédiée aux étoiles de la surface cible pendant la récupération API.",
        "Allows the dedicated target-surface star cohort during API retrieval.",
        "Désactiver libère sa part pour Distance et Large, utile quand l’Ace démarre déjà A sur la surface.",
        "Disabling it frees its share for Distance and Broad, useful when the Ace already starts at A on the surface.",
    ),
    ("retrieval", "distance_share"): (
        "Part de base du budget API réservée à la cohorte triée par étoiles de distance.",
        "Base share of the API budget reserved for the distance-star-sorted cohort.",
        "L’augmenter sécurise davantage de porteurs de distance dans le pool, au détriment des cohortes Surface et Large.",
        "Increasing it secures more distance carriers in the pool at the expense of the Surface and Broad cohorts.",
    ),
    ("retrieval", "surface_share_below_minimum"): (
        "Part Surface utilisée tant que le rang initial de l’Ace reste sous le rang minimum configuré.",
        "Surface share used while the Ace’s initial rank stays below the configured minimum rank.",
        "L’augmenter va chercher plus de branches distantes porteuses de la surface quand le besoin est maximal.",
        "Increasing it fetches more remote branches carrying the surface when the need is greatest.",
    ),
    ("retrieval", "surface_share_at_minimum"): (
        "Part Surface utilisée quand l’Ace atteint le rang minimum sans atteindre le rang préféré.",
        "Surface share used once the Ace reaches the minimum rank but not the preferred rank.",
        "L’augmenter continue d’alimenter la surface après le seuil B, au lieu de basculer vers Distance et Large.",
        "Increasing it keeps feeding the surface cohort past the B threshold instead of shifting towards Distance and Broad.",
    ),
    ("retrieval", "surface_share_at_preferred"): (
        "Part Surface conservée quand l’Ace démarre déjà au rang préféré sur la surface.",
        "Surface share kept when the Ace already starts at the preferred surface rank.",
        "La laisser à zéro consacre tout le budget restant aux autres cohortes ; l’augmenter garde une marge de sécurité.",
        "Leaving it at zero devotes the remaining budget to the other cohorts; increasing it keeps a safety margin.",
    ),
    ("retrieval", "broad_minimum_share"): (
        "Part minimale garantie à la cohorte large triée par whites, quelles que soient les autres demandes.",
        "Minimum share guaranteed to the broad white-sorted cohort regardless of other demands.",
        "L’augmenter protège la diversité de whites du pool ; Distance et Surface sont redimensionnées si nécessaire.",
        "Increasing it protects white diversity in the pool; Distance and Surface are rescaled when needed.",
    ),
    ("retrieval", "balanced_branch_divisor"): (
        "Diviseur appliqué au besoin d’étoiles total pour demander une branche distante équilibrée plutôt que porteuse de tout.",
        "Divisor applied to the total star need so the remote branch is asked for a balanced share rather than everything.",
        "L’augmenter abaisse le seuil d’étoiles demandé au côté distant et suppose que le côté local complètera le reste.",
        "Increasing it lowers the star threshold requested from the remote side and assumes the local side completes the rest.",
    ),
    ("retrieval", "contextual_distance_star_target"): (
        "Référence d’étoiles de distance visée en mode parent opposé fixé, une fois le départ A assuré.",
        "Distance-star reference targeted in fixed-opposing-parent mode once the initial A start is covered.",
        "L’augmenter maintient plus de porteurs de distance dans l’échantillon pour viser P(S), au lieu de réduire la recherche au strict minimum.",
        "Increasing it keeps more distance carriers in the sample to aim at P(S) instead of shrinking the search to the bare minimum.",
    ),
    ("retrieval", "contextual_distance_need_floor"): (
        "Demande minimale conservée par la cohorte Distance même quand le parent opposé couvre déjà le besoin calculé.",
        "Minimum demand kept by the Distance cohort even when the opposing parent already covers the computed need.",
        "L’augmenter évite qu’une couverture apparente réduise la cohorte Distance à presque rien.",
        "Increasing it prevents apparent coverage from shrinking the Distance cohort to almost nothing.",
    ),
    ("retrieval", "contextual_surface_reallocation_to_distance"): (
        "Fraction de la part Surface libérée qui est réaffectée à la cohorte Distance en mode parent opposé fixé.",
        "Fraction of the freed Surface share reallocated to the Distance cohort in fixed-opposing-parent mode.",
        "L’augmenter convertit la surface déjà couverte en étoiles de distance supplémentaires ; le reste va à la cohorte large.",
        "Increasing it converts already-covered surface into extra distance stars; the remainder goes to the broad cohort.",
    ),
    ("preselection", "distance_share"): (
        "Places réservées aux branches distantes les plus riches en distance avant le produit cartésien local × distant.",
        "Slots reserved for the most distance-rich remote branches before the local × remote cartesian product.",
        "L’augmenter garde plus de spécialistes distance pour l’évaluation exacte, au prix de candidats au score global élevé.",
        "Increasing it keeps more distance specialists for exact evaluation at the cost of high-overall-score candidates.",
    ),
    ("preselection", "surface_share_below_minimum"): (
        "Places réservées aux branches riches en surface tant que l’Ace reste sous le rang minimum.",
        "Slots reserved for surface-rich branches while the Ace stays below the minimum rank.",
        "L’augmenter empêche deux branches moyennes mais complémentaires de disparaître avant le score exact à six membres.",
        "Increasing it prevents two individually average but complementary branches from vanishing before the exact six-member score.",
    ),
    ("preselection", "surface_share_at_minimum"): (
        "Places Surface réservées quand l’Ace atteint le rang minimum sans le rang préféré.",
        "Surface slots reserved once the Ace reaches the minimum but not the preferred rank.",
        "L’augmenter conserve des porteurs de surface au-delà du seuil B ; le reste des places revient au classement global.",
        "Increasing it keeps surface carriers past the B threshold; the remaining slots return to the overall ranking.",
    ),
    ("preselection", "surface_share_at_preferred"): (
        "Places Surface conservées quand l’Ace démarre déjà au rang préféré.",
        "Surface slots kept when the Ace already starts at the preferred rank.",
        "Zéro rend toutes les places au classement global ; une petite valeur garde quelques spécialistes par prudence.",
        "Zero returns every slot to the overall ranking; a small value keeps a few specialists as a precaution.",
    ),
}


_CONTEXTUAL_OPPONENT_HELP: dict[str, tuple[str, str, str, str]] = {
    "white_retrieval_coverage_decay": (
        "Atténuation appliquée, pendant la récupération API, au poids des whites déjà couvertes par le parent opposé.",
        "Attenuation applied during API retrieval to the weight of whites already covered by the opposing parent.",
        "L’augmenter oriente la requête vers des whites complémentaires ; zéro ignore la couverture du parent opposé.",
        "Increasing it steers the query towards complementary whites; zero ignores the opposing parent’s coverage.",
    ),
    "white_preselection_coverage_decay": (
        "Atténuation appliquée, pendant la présélection, à la valeur des whites déjà couvertes par le parent opposé.",
        "Attenuation applied during preselection to the value of whites already covered by the opposing parent.",
        "L’augmenter favorise les branches qui complètent la paire au lieu de dupliquer ses whites ; zéro désactive l’effet.",
        "Increasing it favours branches that complete the pair instead of duplicating its whites; zero disables the effect.",
    ),
    "preselection_affinity_weight": (
        "Poids de l’affinité du candidat dans la présélection quand un parent opposé est fixé.",
        "Weight of candidate affinity in preselection when an opposing parent is fixed.",
        "Le défaut quasi nul laisse le moteur exact parent_pair juger l’affinité ; l’augmenter réintroduit ce signal trop tôt.",
        "The near-zero default lets the exact parent_pair engine judge affinity; increasing it reintroduces the signal too early.",
    ),
    "preselection_g1_weight": (
        "Poids du potentiel G1 dans la présélection quand un parent opposé est fixé.",
        "Weight of G1 potential in preselection when an opposing parent is fixed.",
        "Le défaut quasi nul évite de doubler le moteur exact ; l’augmenter fait remonter les liens G1 dès la présélection.",
        "The near-zero default avoids duplicating the exact engine; increasing it surfaces G1 links as early as preselection.",
    ),
    "preselection_white_generation_weight": (
        "Poids de la capacité de génération de whites dans la présélection contextuelle.",
        "Weight of white-generation capacity in contextual preselection.",
        "L’augmenter favorise les branches qui répètent des whites utiles pendant la fabrication, avant le score exact.",
        "Increasing it favours branches that repeat useful whites during production, ahead of the exact score.",
    ),
}


_TRANSFER_HELP: dict[str, tuple[str, str, str, str]] = {
    "analysis_mode": (
        "Le mode rapide utilise le socle permanent et filtre les Aces naturellement viables ; l’audit exhaustif réactive tous les styles et toutes les variantes d’Ace.",
        "Fast mode uses the permanent baseline and naturally viable Aces; exhaustive audit restores every style and Ace variant.",
        "Le mode exhaustif sert de contrôle ponctuel, peut prendre plusieurs minutes et autorise le verdict strictement sûr.",
        "Exhaustive mode is intended as an occasional control, may take several minutes, and enables the strictly safe verdict.",
    ),
    "portfolio_regret_tolerance": (
        "Écart maximal accepté entre la meilleure copie du costume et le portefeuille conservé dans chaque niche compétitive.",
        "Maximum accepted gap between the costume's best copy and the retained portfolio in each competitive niche.",
        "L’augmenter transfère davantage de micro-variantes ; le réduire conserve plus de copies proches du meilleur score.",
        "Increasing it transfers more micro-variants; reducing it retains more copies close to the best score.",
    ),
    "portfolio_direct_white_minimum_context_weight": (
        "Poids contextuel minimal pour qu’une White directe devienne un actif obligatoire du portefeuille.",
        "Minimum contextual weight for a direct White to become a mandatory portfolio asset.",
        "L’augmenter réserve cette protection aux skills les plus stratégiques.",
        "Increasing it limits this protection to the most strategic skills.",
    ),
    "portfolio_direct_white_min_stars": (
        "Nombre minimal d’étoiles d’une White directe protégée collectivement.",
        "Minimum star count for a collectively protected direct White.",
        "Deux étoiles protège les sources directes déjà solides sans conserver toutes les White 1★.",
        "Two stars protects already solid direct sources without retaining every 1-star White.",
    ),
    "minimum_ace_aptitude_rank": (
        "Rang naturel minimal exigé en surface, distance et style pour qu’un Ace participe au mode rapide.",
        "Minimum natural surface, distance, and style rank required for an Ace to participate in fast mode.",
        "B écarte les couples théoriques sans sacrifier les Aces naturellement plausibles ; le mode exhaustif ignore ce filtre.",
        "B removes theoretical pairings without sacrificing naturally plausible Aces; exhaustive mode ignores this filter.",
    ),
    "include_permanent_archetypes": (
        "Active le socle stable Turf Sprint/Mile/Medium/Long et Dirt Sprint/Mile/Medium.",
        "Enables the stable Turf Sprint/Mile/Medium/Long and Dirt Sprint/Mile/Medium baseline.",
        "Le laisser activé empêche la rotation temporaire des CM d’autoriser un nettoyage irréversible.",
        "Keeping it enabled prevents the temporary CM rotation from authorising irreversible cleanup.",
    ),
    "include_upcoming_cm_context": (
        "Ajoute les prochaines Champion Meetings comme signal contextuel au-dessus du socle permanent.",
        "Adds upcoming Champion Meetings as contextual evidence on top of the permanent baseline.",
        "Activer peut conserver des spécialistes utiles prochainement et allonge le calcul ; leur absence ne retire jamais un archétype permanent.",
        "Enabling it may retain specialists useful soon and lengthens analysis; their absence never removes a permanent archetype.",
    ),
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
    "enabled": (
        "Active le plancher qui protège un patrimoine Spark non reproduit par le remplaçant.",
        "Enables the verdict floor that protects Spark heritage not reproduced by the replacement.",
        "Le désactiver rend le verdict dépendant de la seule dominance du score et du support G1.",
        "Disabling it makes the verdict depend only on score dominance and G1 support.",
    ),
    "minimum_context_weight": (
        "Utilité maximale requise dans au moins un profil actif avant qu’une Spark puisse être protégée.",
        "Maximum utility required in at least one active profile before a Spark can be protected.",
        "L’augmenter écarte les Sparks faibles ou trop situationnelles du garde-fou.",
        "Increasing it excludes weak or overly situational Sparks from the safeguard.",
    ),
    "hard_to_obtain_minimum_context_weight": (
        "Utilité contextuelle minimale exigée avant d’utiliser la rareté d’acquisition.",
        "Minimum contextual utility required before acquisition scarcity is considered.",
        "L’augmenter évite de protéger une Spark rare mais peu utile.",
        "Increasing it avoids protecting a scarce but low-value Spark.",
    ),
    "hard_to_obtain_max_support_hint_count": (
        "Nombre maximal de support cards donnant directement le hint pour qualifier une Spark de difficile à obtenir.",
        "Maximum number of support cards directly giving the hint for a Spark to count as hard to obtain.",
        "L’augmenter élargit la protection d’acquisition à des Sparks disponibles sur davantage de supports.",
        "Increasing it broadens acquisition protection to Sparks available from more support cards.",
    ),
    "repeated_review_min_carriers": (
        "Nombre minimal de membres distincts portant la même skill effective pour déclencher un examen.",
        "Minimum number of distinct members carrying the same effective skill to trigger review.",
        "L’augmenter réserve la protection aux lignées plus fortement répétées.",
        "Increasing it reserves protection for more strongly repeated lineages.",
    ),
    "repeated_review_min_total_stars": (
        "Somme minimale d’étoiles sur les sources normalisées d’une Spark répétée.",
        "Minimum total stars across the normalised sources of a repeated Spark.",
        "L’augmenter exige une meilleure qualité cumulée avant de relever le verdict.",
        "Increasing it requires stronger combined quality before raising the verdict.",
    ),
    "repeated_review_min_probability": (
        "Probabilité neutre minimale d’obtenir une Spark répétée au moins une fois.",
        "Minimum neutral probability of inheriting a repeated Spark at least once.",
        "L’augmenter ignore les répétitions dont les taux de proc cumulés restent faibles.",
        "Increasing it ignores repetitions whose combined proc rates remain low.",
    ),
    "repeated_strong_min_carriers": (
        "Nombre de porteurs distincts à partir duquel une répétition devient un signal fort.",
        "Number of distinct carriers at which repetition becomes a strong signal.",
        "L’augmenter rend le plancher « probablement conserver » plus rare.",
        "Increasing it makes the likely-keep floor less common.",
    ),
    "repeated_strong_min_probability": (
        "Probabilité neutre à partir de laquelle une répétition devient un signal fort.",
        "Neutral probability at which repetition becomes a strong signal.",
        "L’augmenter exige une couverture cumulée plus élevée pour atteindre « probablement conserver ».",
        "Increasing it requires higher combined coverage to reach likely keep.",
    ),
    "direct_future_gp_minimum_context_weight": (
        "Utilité contextuelle minimale d’une Spark portée directement par le futur grand-parent.",
        "Minimum contextual utility for a Spark carried directly by the future grandparent.",
        "L’augmenter limite cette protection forte aux skills les plus déterminantes.",
        "Increasing it limits this strong protection to the most decisive skills.",
    ),
    "direct_future_gp_min_stars": (
        "Nombre minimal d’étoiles directes pour protéger fortement un futur grand-parent.",
        "Minimum direct stars required to strongly protect a future grandparent.",
        "L’augmenter réserve ce garde-fou aux Sparks directes de meilleure qualité.",
        "Increasing it reserves this safeguard for higher-quality direct Sparks.",
    ),
    "replacement_probability_ratio": (
        "Fraction de la probabilité du vétéran que le remplaçant doit conserver.",
        "Fraction of the veteran’s inheritance probability the replacement must retain.",
        "L’augmenter exige une couverture plus proche de l’original.",
        "Increasing it requires coverage closer to the original.",
    ),
    "replacement_probability_tolerance": (
        "Écart absolu de probabilité toléré lors de la comparaison des patrimoines.",
        "Absolute probability gap tolerated when comparing inheritance assets.",
        "L’augmenter accepte une petite perte supplémentaire chez le remplaçant.",
        "Increasing it accepts a slightly larger loss in the replacement.",
    ),
    "important_packages": (
        "Liste avancée des ensembles de skills dont la couverture combinée doit être préservée.",
        "Advanced list of skill sets whose combined coverage should be preserved.",
        "Modifier cette liste change uniquement le plancher de verdict, jamais le score principal.",
        "Editing this list changes only the verdict floor, never the primary score.",
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

    if root == "future_grandparent_heuristics" and leaf == "g1_win_probability_cutoff":
        return WeightHelp(
            _pick(
                language,
                "Chance de victoire minimale requise pour compter une G1 pendant l’Independent Training du futur parent.",
                "Minimum win chance required for a G1 to count during the future parent’s Independent Training run.",
            ),
            _pick(
                language,
                "La G1 conserve toute sa valeur au-dessus du seuil et vaut zéro en dessous, après pénalité de courses consécutives.",
                "The G1 keeps its full value above the cutoff and is worth zero below it, after consecutive-race penalties.",
            ),
            scope,
            low,
            high,
        )

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
            "star_quality": "Race Spark",
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
        family = _pick(language, "White Skills", "White Skills") if root != "race_saturation" else "Race Sparks"
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
        family = "Race Sparks"
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

    if root == "scenario_inheritance":
        if "base_proc_rates" in path:
            stars = _label(leaf, language)
            summary = _pick(
                language,
                f"Probabilité de base par Inspiration Event pour une Scenario Spark {stars}, avant l’affinité individuelle.",
                f"Base probability per Inspiration Event for a {stars} Scenario Spark, before individual affinity.",
            )
        elif leaf == "inspiration_event_count":
            summary = _pick(
                language,
                "Nombre d’Inspiration Events inclus dans la valeur statistique attendue des Scenario Sparks.",
                "Number of Inspiration Events included in the expected stat value of Scenario Sparks.",
            )
        elif leaf == "per_event_probability_cap":
            summary = _pick(
                language,
                "Plafond de probabilité d’un proc de Scenario Spark sur un Inspiration Event.",
                "Per-Inspiration-Event probability cap for a Scenario Spark proc.",
            )
        else:
            summary = _pick(
                language,
                "Nombre de Blue Sparks équivalentes attribué à chaque stat donnée par un proc de Scenario Spark.",
                "Number of Blue-Spark equivalents assigned to every stat granted by one Scenario Spark proc.",
            )
        impact = _pick(
            language,
            "L’augmenter renforce le bonus attendu des Scenario Sparks dans la composante Blues, qui peut dépasser 100.",
            "Increasing it raises the expected Scenario-Spark bonus inside the Blue component, which may exceed 100.",
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
        if len(path) > 1 and path[1] == "contextual_opponent" and leaf in _CONTEXTUAL_OPPONENT_HELP:
            fr_summary, en_summary, fr_impact, en_impact = _CONTEXTUAL_OPPONENT_HELP[leaf]
            return WeightHelp(
                _pick(language, fr_summary, en_summary),
                _pick(language, fr_impact, en_impact),
                scope, low, high,
            )
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

    if root == "uma_moe_parent_search":
        stage = path[1] if len(path) > 1 else ""
        help_entry = _PARENT_SEARCH_HELP.get((stage, leaf))
        if help_entry is not None:
            fr_summary, en_summary, fr_impact, en_impact = help_entry
            return WeightHelp(
                _pick(language, fr_summary, en_summary),
                _pick(language, fr_impact, en_impact),
                scope, low, high,
            )

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
        elif leaf == "minimum_initial_rank":
            summary = _pick(language, f"Rang initial minimum visé en {dimension_label} (6 = B) : sous ce rang, la recherche uma.moe traite l’aptitude comme un besoin prioritaire.", f"Minimum initial {dimension_label} rank targeted (6 = B): below it, the uma.moe search treats the aptitude as a priority need.")
            impact = _pick(language, "L’augmenter élève le seuil qui déclenche les parts Surface maximales des cohortes et de la présélection.", "Increasing it raises the threshold that triggers the maximum Surface shares in cohorts and preselection.")
        elif leaf == "preferred_initial_rank":
            summary = _pick(language, f"Rang initial préféré en {dimension_label} (7 = A) : une fois atteint, la part Surface bascule sur sa valeur « au rang préféré ».", f"Preferred initial {dimension_label} rank (7 = A): once reached, the Surface share switches to its at-preferred value.")
            impact = _pick(language, "L’augmenter maintient l’objectif A plus longtemps et retarde la libération du budget vers Distance et Large.", "Increasing it keeps the A goal active longer and delays freeing budget towards Distance and Broad.")
        elif "below_b" in path:
            below_help = {
                "base_score": (
                    f"Score plancher attribué quand l’Ace démarre sous B en {dimension_label}.",
                    f"Floor score assigned when the Ace starts below B in {dimension_label}.",
                    "L’augmenter rend les départs très faibles moins pénalisés dans le diagnostic.",
                    "Increasing it makes very weak starts less penalised in the diagnostic.",
                ),
                "initial_minimum_readiness_weight": (
                    f"Poids de la progression d’étoiles vers le rang minimum quand le départ en {dimension_label} reste sous B.",
                    f"Weight of star progress towards the minimum rank while the {dimension_label} start stays below B.",
                    "L’augmenter récompense chaque étoile qui rapproche du seuil B, même avant de l’atteindre.",
                    "Increasing it rewards every star that moves closer to the B threshold, even before reaching it.",
                ),
                "minimum_probability_weight": (
                    f"Poids de la probabilité d’atteindre le rang minimum pendant la run, pour un départ sous B en {dimension_label}.",
                    f"Weight of the probability of reaching the minimum rank during the run, for a below-B {dimension_label} start.",
                    "L’augmenter favorise les lignées capables de rattraper le seuil B grâce à leurs procs roses.",
                    "Increasing it favours lineages able to catch up to the B threshold through their pink procs.",
                ),
                "a_probability_weight": (
                    f"Poids de la probabilité d’atteindre A pendant la run, pour un départ sous B en {dimension_label}.",
                    f"Weight of the probability of reaching A during the run, for a below-B {dimension_label} start.",
                    "L’augmenter valorise les remontées complètes jusqu’à A malgré le départ faible.",
                    "Increasing it rewards full climbs to A despite the weak start.",
                ),
                "s_probability_weight": (
                    f"Poids de la qualité de P(S) pour un départ sous B en {dimension_label}.",
                    f"Weight of P(S) quality for a below-B {dimension_label} start.",
                    "L’augmenter garde un petit signal S même dans les scénarios de départ très faibles.",
                    "Increasing it keeps a small S signal even in very weak starting scenarios.",
                ),
            }
            fr_summary, en_summary, fr_impact, en_impact = below_help.get(
                leaf,
                (
                    f"Paramètre du score {dimension_label} utilisé quand l’Ace démarre sous B.",
                    f"{dimension_label} score parameter used when the Ace starts below B.",
                    "L’augmenter donne plus de poids à ce scénario de départ dans le diagnostic final.",
                    "Increasing it gives this starting scenario more influence in the final diagnostic.",
                ),
            )
            summary = _pick(language, fr_summary, en_summary)
            impact = _pick(language, fr_impact, en_impact)
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
