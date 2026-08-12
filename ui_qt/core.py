from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from course_presets import resolve_course_overrides_path
from legacy_linker import LinkResult, LinkerError, link_veterans, normalize_json_root
from manual_weights import generate_manual_skill_weights
from parent_optimizer import OptimizerError, OptimizerResult, load_ace_options, optimize_parents
from scoring_config import (
    ScoringConfigError,
    deep_merge,
    materialize_effective_scoring_config,
    read_json_object,
    validate_scoring_config,
    validate_skill_priorities_config,
    write_json_object,
)
from simulator_weights import SimulatorWeightResult, generate_simulator_weights
from skill_catalog import SkillCatalogResult, generate_skill_catalogs
from transfer_helper import (
    TransferHelperError,
    TransferHelperResult,
    analyze_transfer_candidates,
)
from uma_moe import (
    DEFAULT_API_BASE,
    MAX_FETCH_CANDIDATES,
    OnlineParentSearchResult,
    OnlineSearchResult,
    UmaMoeApiClient,
    UmaMoeError,
    build_lineage_factor_api_filters,
    extract_opposing_parent_candidates,
    generate_auto_uql,
    rank_online_grandparent_pairs,
    rank_online_parent_pairs,
)


APP_NAME = "Uma Legacy Linker"
APP_VERSION = "1.7.2"

LogCallback = Callable[[str], None]
ProgressCallback = Callable[[int, str], None]


def app_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_base_dir() -> Path:
    bundle_dir = getattr(sys, "_MEIPASS", None)
    if getattr(sys, "frozen", False) and bundle_dir:
        return Path(bundle_dir).resolve()
    return Path(__file__).resolve().parent.parent


def config_path() -> Path:
    if os.name == "nt":
        root = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "UmaLegacyLinker" / "config.json"


def api_key_path(settings_path: str | Path | None = None) -> Path:
    parent = Path(settings_path).expanduser().parent if settings_path else config_path().parent
    return parent / "uma_moe_api_key.dat"


def default_scoring_path() -> Path:
    return resource_base_dir() / "default_parent_scoring.json"


def user_scoring_overrides_path() -> Path:
    return config_path().parent / "parent_scoring_overrides.json"


def default_skill_priorities_path() -> Path:
    return resource_base_dir() / "default_skill_priorities.json"


def user_skill_priorities_path() -> Path:
    return config_path().parent / "skill_priorities_custom.json"


class SettingsStore:
    """Compatibility layer for configuration created by earlier releases."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path).expanduser() if path is not None else config_path()
        self._values = self._read()

    def _read(self) -> dict[str, str]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return {str(key): str(value) for key, value in payload.items()}

    def get(self, key: str, default: str = "") -> str:
        return self._values.get(key, default)

    def as_dict(self) -> dict[str, str]:
        return dict(self._values)

    def update(self, values: dict[str, object]) -> None:
        for key, value in values.items():
            self._values[str(key)] = str(value)
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._values, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def candidate_master_paths() -> list[Path]:
    candidates: list[Path] = []
    local_low = Path.home() / "AppData" / "LocalLow" / "Cygames"
    for game_dir in ("umamusume", "Umamusume"):
        candidates.append(local_low / game_dir / "master" / "master.mdb")

    steam_roots = [
        Path(value) / "Steam"
        for value in (os.environ.get("PROGRAMFILES(X86)"), os.environ.get("PROGRAMFILES"))
        if value
    ]
    steam_roots.extend(
        [Path("C:/Steam"), Path("D:/Steam"), Path("D:/SteamLibrary"), Path("E:/SteamLibrary")]
    )
    relatives = [
        Path("steamapps/common/UmamusumePrettyDerby/UmamusumePrettyDerby_Data/Persistent/master/master.mdb"),
        Path("steamapps/common/UmamusumePrettyDerby/Umamusume_Data/Persistent/master/master.mdb"),
        Path("steamapps/common/UmamusumePrettyDerby_Global/UmamusumePrettyDerby_Global_Data/Persistent/master/master.mdb"),
    ]
    for root in steam_roots:
        candidates.extend(root / relative for relative in relatives)
    return candidates


def auto_detect_master() -> Path | None:
    valid = [path for path in candidate_master_paths() if path.is_file()]
    return max(valid, key=lambda path: path.stat().st_mtime) if valid else None


def auto_detect_extractor() -> Path | None:
    base = app_base_dir()
    candidates = (
        base / "umadump.exe",
        base / "tools" / "umadump.exe",
        base / "umaextractor.exe",
        base / "UmaExtractor.exe",
        base / "tools" / "umaextractor.exe",
        base / "tools" / "UmaExtractor.exe",
    )
    return next((path for path in candidates if path.is_file()), None)


def default_output_dir() -> Path:
    return app_base_dir() / "output"


def default_course_overrides_path() -> Path:
    return resource_base_dir() / "default_course_overrides.json"


def active_course_overrides_path(configured: str | Path | None) -> Path | None:
    return resolve_course_overrides_path(configured, default_course_overrides_path())


def open_path(path: str | Path) -> None:
    resolved = Path(path).expanduser().resolve()
    if os.name == "nt":
        os.startfile(str(resolved))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(resolved)])
    else:
        subprocess.Popen(["xdg-open", str(resolved)])


def collection_size(path: str | Path) -> int | None:
    candidate = Path(path).expanduser()
    if not candidate.is_file():
        return None
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8-sig"))
        return len(normalize_json_root(payload))
    except (OSError, json.JSONDecodeError, LinkerError):
        return None


def latest_rankings_path(output_dir: str | Path) -> Path:
    return Path(output_dir).expanduser() / "legacy_parent_rankings.json"


def linked_veterans_path(output_dir: str | Path) -> Path:
    return Path(output_dir).expanduser() / "veterans_legacy_linked.json"


def load_rankings_payload(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise OptimizerError(f"Classement introuvable : {resolved}") from exc
    except json.JSONDecodeError as exc:
        raise OptimizerError(f"Classement JSON invalide : {resolved.name}") from exc
    if not isinstance(payload, dict):
        raise OptimizerError("Le classement doit contenir un objet JSON.")
    return payload


@dataclass(frozen=True)
class LinkRequest:
    master_path: Path
    veterans_json_path: Path
    output_dir: Path


@dataclass(frozen=True)
class OptimizationRequest:
    master_path: Path
    veterans_json_path: Path
    output_dir: Path
    ace_card_id: int
    future_parent_card_id: int
    surface: str
    distance: str
    style: str
    course_overrides_path: Path | None = None
    course_key: str | None = None
    course_conditions: dict[str, object] | None = None
    top_n: int = 30
    use_custom_scoring: bool = False
    skill_priorities_path: Path | None = None
    search_kind: str = "all"


@dataclass(frozen=True)
class TransferRequest:
    master_path: Path
    veterans_json_path: Path
    output_dir: Path
    course_overrides_path: Path | None = None
    use_custom_scoring: bool = False
    skill_priorities_path: Path | None = None
    analysis_mode: str = "fast"
    include_upcoming_cm_context: bool = True
    upcoming_cm_limit: int = 5
    include_team_trials: bool = False
    include_generic_profiles: bool = False


@dataclass(frozen=True)
class OnlineSearchRequest:
    search_mode: str
    master_path: Path
    veterans_json_path: Path
    output_dir: Path
    ace_card_id: int
    target_parent_card_id: int | None
    fixed_local_id: int | None
    automatic_pairs: bool
    local_pool_size: int
    remote_pool_size: int
    surface: str
    distance: str
    style: str
    course_overrides_path: Path | None = None
    course_key: str | None = None
    course_conditions: dict[str, object] | None = None
    top_n: int = 30
    use_import: bool = False
    response_path: Path | None = None
    api_base: str = DEFAULT_API_BASE
    uql: str = ""
    auto_uql: bool = True
    uql_options: dict[str, object] | None = None
    limit: int = 500
    planned_g1_budget: int = 20
    g1_win_probability_cutoff: float = 0.6
    required_parent_card_id: int | None = None
    allowed_parent_card_ids: tuple[int, ...] = ()
    excluded_parent_card_ids: tuple[int, ...] = ()
    token: str = ""
    use_custom_scoring: bool = False
    skill_priorities_path: Path | None = None
    opposing_parent_trained_id: int | None = None
    opposing_parent_payload: dict[str, Any] | None = None
    local_pair_mode: bool = False
    lineage_blue_filter: tuple[str, int] | None = None
    lineage_pink_filter: tuple[str, int] | None = None


class OperationCancelled(Exception):
    """Raised inside worker threads when the user requests cancellation."""


@dataclass(frozen=True)
class ExtractRequest:
    extractor_path: Path
    master_path: Path
    output_dir: Path


@dataclass(frozen=True)
class ExtractLinkResult:
    data_json_path: Path
    link_result: LinkResult


@dataclass(frozen=True)
class CatalogRequest:
    master_path: Path
    output_dir: Path


@dataclass(frozen=True)
class SimulatorImportRequest:
    master_path: Path
    batch_path: Path
    output_dir: Path
    course_overrides_path: Path | None = None


@dataclass(frozen=True)
class VeteranOption:
    trained_chara_id: int
    card_id: int
    chara_id: int
    uma_name: str
    card_name: str
    rank_score: int

    @property
    def display_name(self) -> str:
        score = f"{self.rank_score:,}".replace(",", " ") if self.rank_score else "?"
        return f"{self.uma_name} — {self.card_name} — {score} — #{self.trained_chara_id}"


def validate_link_request(request: LinkRequest) -> None:
    if not request.master_path.is_file():
        raise LinkerError("Sélectionne un master.mdb valide.")
    if not request.veterans_json_path.is_file():
        raise LinkerError("Sélectionne un export JSON de collection valide.")
    request.output_dir.mkdir(parents=True, exist_ok=True)


def _materialize_scoring_profile(output_dir: Path, use_custom: bool) -> Path:
    default_path = default_scoring_path()
    if not default_path.is_file():
        raise ScoringConfigError(
            f"Configuration de pondération par défaut introuvable : {default_path}"
        )
    override = user_scoring_overrides_path() if use_custom else None
    return materialize_effective_scoring_config(
        default_path,
        override,
        output_dir / "active_parent_scoring.json",
    )


def _materialize_skill_priorities(
    output_dir: Path,
    custom_path: Path | None,
) -> Path:
    default_path = default_skill_priorities_path()
    default_payload = read_json_object(default_path)
    validate_skill_priorities_config(default_payload)
    effective = default_payload
    if custom_path is not None:
        if not custom_path.is_file():
            raise ScoringConfigError(
                f"Profil de priorités white introuvable : {custom_path}"
            )
        effective = deep_merge(default_payload, read_json_object(custom_path))
        validate_skill_priorities_config(effective)
    return write_json_object(output_dir / "active_skill_priorities.json", effective)


def materialize_scoring_profile(output_dir: Path, use_custom: bool) -> Path:
    return _materialize_scoring_profile(output_dir, use_custom)


def materialize_skill_priorities(
    output_dir: Path, custom_path: Path | None
) -> Path:
    return _materialize_skill_priorities(output_dir, custom_path)


def run_link(
    request: LinkRequest,
    *,
    logger: LogCallback,
    progress: ProgressCallback,
) -> LinkResult:
    validate_link_request(request)
    progress(12, "Lecture de la collection locale…")
    result = link_veterans(
        request.master_path,
        request.veterans_json_path,
        request.output_dir,
        logger,
    )
    progress(100, "Liaison terminée.")
    return result


def run_optimization(
    request: OptimizationRequest,
    *,
    logger: LogCallback,
    progress: ProgressCallback,
) -> OptimizerResult:
    validate_link_request(
        LinkRequest(request.master_path, request.veterans_json_path, request.output_dir)
    )
    if request.search_kind not in {"all", "pairs", "branches", "future"}:
        raise OptimizerError("Type de recherche locale invalide.")
    if request.ace_card_id <= 0:
        raise OptimizerError("Sélectionne l’Ace cible.")
    if request.search_kind in {"all", "future"} and request.future_parent_card_id <= 0:
        raise OptimizerError("Sélectionne le parent à produire.")
    if request.top_n < 1:
        raise OptimizerError("Le nombre de résultats doit être positif.")

    progress(5, "Préparation des profils de pondération…")
    scoring_config = _materialize_scoring_profile(
        request.output_dir, request.use_custom_scoring
    )
    skill_priorities = _materialize_skill_priorities(
        request.output_dir, request.skill_priorities_path
    )
    logger(f"Profil de pondération utilisé : {scoring_config}")
    logger(f"Priorités white skills utilisées : {skill_priorities}")

    progress(12, "Liaison des vétérans avec le MDB courant…")
    linked = link_veterans(
        request.master_path,
        request.veterans_json_path,
        request.output_dir,
        logger,
    )

    progress(46, "Génération des pondérations manuelles des white skills…")
    manual_weights = generate_manual_skill_weights(
        linked.skills_catalog_path,
        skill_priorities,
        request.output_dir,
        course_overrides_path=request.course_overrides_path,
        logger=logger,
    )

    calculation_labels = {
        "all": "Calcul des lignées et des paires de parents…",
        "pairs": "Calcul des paires finales…",
        "branches": "Classement des parents locaux…",
        "future": "Classement des grands-parents locaux…",
    }
    progress(70, calculation_labels[request.search_kind])
    result = optimize_parents(
        request.master_path,
        linked.json_path,
        manual_weights.weights_path,
        linked.race_factor_skills_path,
        linked.skills_catalog_path,
        request.output_dir,
        ace_card_id=request.ace_card_id,
        future_parent_card_id=request.future_parent_card_id,
        surface=request.surface,
        distance=request.distance,
        style=request.style,
        course_weights_path=manual_weights.course_weights_path,
        course_key=request.course_key,
        course_conditions=request.course_conditions or {},
        scoring_config_path=scoring_config,
        top_n=request.top_n,
        search_kind=request.search_kind,
        logger=logger,
    )
    progress(100, "Optimisation terminée.")
    return result


def load_local_veteran_options(
    master_path: str | Path, veterans_json_path: str | Path
) -> list[VeteranOption]:
    """Return local copies with stable IDs and MDB-resolved costume names."""
    master = Path(master_path).expanduser()
    data_path = Path(veterans_json_path).expanduser()
    if not master.is_file():
        raise OptimizerError("Sélectionne un master.mdb valide.")
    if not data_path.is_file():
        raise OptimizerError("Sélectionne un export JSON de collection valide.")
    identities = {option.card_id: option for option in load_ace_options(master)}
    try:
        payload = json.loads(data_path.read_text(encoding="utf-8-sig"))
        veterans = normalize_json_root(payload)
    except (OSError, json.JSONDecodeError, LinkerError) as exc:
        raise OptimizerError(f"Impossible de charger les vétérans locaux : {exc}") from exc

    records: list[VeteranOption] = []
    for veteran in veterans:
        try:
            trained_id = int(veteran.get("trained_chara_id"))
            card_id = int(veteran.get("card_id"))
        except (TypeError, ValueError):
            continue
        identity = identities.get(card_id)
        try:
            rank_score = int(veteran.get("rank_score") or 0)
        except (TypeError, ValueError):
            rank_score = 0
        records.append(
            VeteranOption(
                trained_chara_id=trained_id,
                card_id=card_id,
                chara_id=int(identity.chara_id if identity else card_id // 100),
                uma_name=str(identity.uma_name if identity else f"Chara {card_id}"),
                card_name=str(identity.card_name if identity else f"Card {card_id}"),
                rank_score=rank_score,
            )
        )
    records.sort(
        key=lambda item: (
            item.uma_name.casefold(),
            item.card_name.casefold(),
            -item.rank_score,
            item.trained_chara_id,
        )
    )
    return records


def run_transfer_analysis(
    request: TransferRequest,
    *,
    logger: LogCallback,
    progress: ProgressCallback,
) -> TransferHelperResult:
    validate_link_request(
        LinkRequest(request.master_path, request.veterans_json_path, request.output_dir)
    )
    if request.course_overrides_path is not None and not request.course_overrides_path.is_file():
        raise TransferHelperError("Le fichier d’overrides de course est invalide.")

    progress(5, "Préparation des profils de pondération…")
    scoring_config = _materialize_scoring_profile(
        request.output_dir, request.use_custom_scoring
    )
    scoring_payload = read_json_object(scoring_config)
    helper_config = scoring_payload.setdefault("transfer_helper", {})
    if not isinstance(helper_config, dict):
        raise ScoringConfigError("transfer_helper doit être un objet JSON.")
    helper_config.update(
        {
            "analysis_mode": request.analysis_mode,
            "include_upcoming_cm_context": request.include_upcoming_cm_context,
            "upcoming_cm_limit": request.upcoming_cm_limit,
            "include_team_trials": request.include_team_trials,
            "include_generic_profiles": request.include_generic_profiles,
        }
    )
    validate_scoring_config(scoring_payload)
    scoring_config = write_json_object(scoring_config, scoring_payload)
    skill_priorities = _materialize_skill_priorities(
        request.output_dir, request.skill_priorities_path
    )
    logger(f"Profil de pondération utilisé : {scoring_config}")
    logger(f"Priorités white skills utilisées : {skill_priorities}")
    progress(12, "Liaison des vétérans avec le MDB courant…")
    linked = link_veterans(
        request.master_path, request.veterans_json_path, request.output_dir, logger
    )
    progress(40, "Génération des pondérations manuelles des white skills…")
    manual_weights = generate_manual_skill_weights(
        linked.skills_catalog_path,
        skill_priorities,
        request.output_dir,
        course_overrides_path=request.course_overrides_path,
        logger=logger,
    )
    progress(62, "Analyse de tous les rôles et profils…")
    result = analyze_transfer_candidates(
        request.master_path,
        linked.json_path,
        manual_weights.weights_path,
        linked.race_factor_skills_path,
        linked.skills_catalog_path,
        request.output_dir,
        course_weights_path=manual_weights.course_weights_path,
        scoring_config_path=scoring_config,
        logger=logger,
    )
    progress(100, "Transfer Helper terminé.")
    return result


def _validated_online_request(request: OnlineSearchRequest) -> None:
    validate_link_request(
        LinkRequest(request.master_path, request.veterans_json_path, request.output_dir)
    )
    if request.search_mode not in {"parent", "grandparent"}:
        raise UmaMoeError("Type de recherche uma.moe invalide.")
    if request.ace_card_id <= 0:
        raise UmaMoeError("Sélectionne l’Ace cible.")
    if request.search_mode == "grandparent" and not request.target_parent_card_id:
        raise UmaMoeError("Sélectionne le parent à produire.")
    if request.search_mode == "grandparent" and request.target_parent_card_id:
        chara_by_card = {
            option.card_id: option.chara_id for option in load_ace_options(request.master_path)
        }
        ace_chara = chara_by_card.get(request.ace_card_id)
        target_chara = chara_by_card.get(request.target_parent_card_id)
        if ace_chara is not None and ace_chara == target_chara:
            raise UmaMoeError("L’Ace et le parent à produire doivent être différents.")
        if request.fixed_local_id is not None and target_chara is not None:
            fixed = next(
                (
                    option
                    for option in load_local_veteran_options(
                        request.master_path, request.veterans_json_path
                    )
                    if option.trained_chara_id == request.fixed_local_id
                ),
                None,
            )
            if fixed is not None and fixed.chara_id == target_chara:
                raise UmaMoeError(
                    "Un grand-parent ne peut pas être la même Uma que le parent à produire, quel que soit le costume."
                )
    if not request.automatic_pairs and request.fixed_local_id is None:
        role = "parent" if request.search_mode == "parent" else "GP"
        raise UmaMoeError(
            f"Sélectionne un {role} local ou active le test automatique des paires."
        )
    if request.use_import and (
        request.response_path is None or not request.response_path.is_file()
    ):
        raise UmaMoeError("Sélectionne une réponse JSON uma.moe à importer.")
    if request.required_parent_card_id in set(request.excluded_parent_card_ids):
        raise UmaMoeError("Le costume requis est également exclu.")
    if (
        request.allowed_parent_card_ids
        and request.required_parent_card_id is not None
        and request.required_parent_card_id not in set(request.allowed_parent_card_ids)
    ):
        raise UmaMoeError(
            "Le costume requis doit être présent dans les costumes autorisés."
        )
    if request.course_overrides_path is not None and not request.course_overrides_path.is_file():
        raise UmaMoeError("Le fichier d’overrides de course est invalide.")


def run_online_search(
    request: OnlineSearchRequest,
    *,
    logger: LogCallback,
    progress: ProgressCallback,
) -> OnlineSearchResult | OnlineParentSearchResult:
    """Run the same online/local ranking pipeline used by the legacy UI."""
    _validated_online_request(request)
    output = request.output_dir
    output.mkdir(parents=True, exist_ok=True)
    scoring_config = _materialize_scoring_profile(output, request.use_custom_scoring)
    skill_priorities = _materialize_skill_priorities(
        output, request.skill_priorities_path
    )
    logger(f"Profil de pondération utilisé : {scoring_config}")
    logger(f"Priorités white skills utilisées : {skill_priorities}")

    progress(8, "Liaison des vétérans locaux avec le MDB…")
    linked = link_veterans(
        request.master_path, request.veterans_json_path, output, logger
    )
    progress(32, "Génération des priorités manuelles…")
    manual_weights = generate_manual_skill_weights(
        linked.skills_catalog_path,
        skill_priorities,
        output,
        course_overrides_path=request.course_overrides_path,
        logger=logger,
    )

    if request.local_pair_mode:
        if request.search_mode != "grandparent":
            raise UmaMoeError(
                "Les paires de GP locales nécessitent le mode grand-parent."
            )
        progress(55, "Classement des paires de GP locales…")
        result = rank_online_grandparent_pairs(
            request.master_path,
            linked.json_path,
            manual_weights.weights_path,
            linked.skills_catalog_path,
            output,
            race_factor_catalog_path=linked.race_factor_skills_path,
            ace_card_id=request.ace_card_id,
            target_parent_card_id=int(request.target_parent_card_id or 0),
            fixed_grandparent_trained_id=request.fixed_local_id,
            opposing_parent_trained_id=request.opposing_parent_trained_id,
            opposing_parent=request.opposing_parent_payload,
            exhaustive_pairs=bool(request.automatic_pairs),
            local_pool_size=max(1, min(int(request.local_pool_size), 250)),
            remote_pool_size=max(1, min(int(request.remote_pool_size), 500)),
            surface=request.surface,
            distance=request.distance,
            style=request.style,
            course_weights_path=manual_weights.course_weights_path,
            course_key=request.course_key,
            course_conditions=request.course_conditions or {},
            scoring_config_path=scoring_config,
            planned_g1_budget=max(0, min(int(request.planned_g1_budget), 40)),
            g1_win_probability_cutoff=max(
                0.0, min(float(request.g1_win_probability_cutoff), 1.0)
            ),
            top_n=max(1, int(request.top_n)),
            local_pair_mode=True,
            lineage_blue_filter=request.lineage_blue_filter,
            lineage_pink_filter=request.lineage_pink_filter,
            logger=logger,
        )
        progress(100, "Paires de GP locales classées.")
        return result

    linked_payload = (
        read_json_object(linked.json_path)
        if linked.json_path.is_file()
        else {}
    )
    linked_veterans = list(linked_payload.get("veterans") or [])

    def linked_member(trained_id: int | None) -> dict[str, Any] | None:
        if trained_id is None:
            return None
        return next(
            (
                member
                for member in linked_veterans
                if int(member.get("trained_chara_id") or 0) == int(trained_id)
            ),
            None,
        )

    fixed_local_context = linked_member(request.fixed_local_id)
    opposing_context = request.opposing_parent_payload or linked_member(
        request.opposing_parent_trained_id
    )

    effective_uql = request.uql.strip()
    auto_uql_text, generated_meta = generate_auto_uql(
        manual_weights.weights_path,
        linked.skills_catalog_path,
        surface=request.surface,
        distance=request.distance,
        style=request.style,
        course_weights_path=manual_weights.course_weights_path,
        course_key=request.course_key,
        course_conditions=request.course_conditions or {},
        scoring_config_path=scoring_config,
        options=request.uql_options or {},
        master_path=request.master_path,
        ace_card_id=request.ace_card_id,
        search_mode=request.search_mode,
        opposing_parent=opposing_context,
        fixed_local_parent=fixed_local_context,
    )
    search_filters = dict(generated_meta.get("search_filters") or {})
    lineage_api_filters, lineage_api_diagnostics = build_lineage_factor_api_filters(
        request.master_path,
        request.lineage_blue_filter,
        request.lineage_pink_filter,
    )
    search_filters.update(lineage_api_filters)
    generated_meta["search_filters"] = search_filters
    generated_meta["lineage_api_filters"] = lineage_api_diagnostics
    operation: dict[str, Any] | None

    if request.auto_uql and not request.use_import:
        effective_uql = auto_uql_text
        (output / "uma_moe_generated_uql.txt").write_text(
            effective_uql + "\n", encoding="utf-8"
        )
        (output / "uma_moe_generated_uql.json").write_text(
            json.dumps(generated_meta, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if request.use_import:
        assert request.response_path is not None
        progress(48, "Lecture de la réponse JSON uma.moe…")
        raw_payload = json.loads(
            request.response_path.read_text(encoding="utf-8-sig")
        )
        operation = {
            "mode": "import",
            "path": str(request.response_path),
            "effective_uql": effective_uql,
            "generated_uql_metadata": generated_meta,
        }
    else:
        desired = max(100, min(int(request.limit), MAX_FETCH_CANDIDATES))
        progress(48, f"Recherche uma.moe paginée — objectif {desired} candidats…")
        client = UmaMoeApiClient(
            request.api_base.strip() or DEFAULT_API_BASE,
            token=(request.token.strip() or None),
        )
        api_filters: dict[str, Any] = {
            key: value
            for key, value in search_filters.items()
            if value not in (None, "", [], (), {})
        }
        if lineage_api_diagnostics:
            logger(
                "Filtres lignée appliqués par l’API avant pagination puis "
                "revalidés localement : "
                + ", ".join(
                    f"{item['factor']} ≥ {item['minimum_stars']}★"
                    for item in lineage_api_diagnostics.values()
                )
            )
        if request.search_mode == "parent" and (
            request.allowed_parent_card_ids or request.excluded_parent_card_ids
        ):
            documented = client.documented_parent_card_filter_keys()
            allowed_key = documented.get("allowed")
            excluded_key = documented.get("excluded")
            if allowed_key and request.allowed_parent_card_ids:
                api_filters[allowed_key] = list(request.allowed_parent_card_ids)
            if excluded_key and request.excluded_parent_card_ids:
                api_filters[excluded_key] = list(request.excluded_parent_card_ids)
            if not documented:
                logger(
                    "Filtres costume non détectés dans l’OpenAPI : contrôle local uniquement."
                )
        raw_payload, operation = client.search_many_planned(
            base_filters=api_filters,
            retrieval_plan=generated_meta.get("retrieval_plan") or {},
            desired_candidates=desired,
            page_size=100,
            logger=logger,
        )
        operation["auto_uql"] = bool(request.auto_uql)
        operation["generated_uql_metadata"] = generated_meta
        operation["effective_uql"] = effective_uql
        (output / "uma_moe_api_response.json").write_text(
            json.dumps(raw_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    progress(72, "Calcul des meilleures paires — toutes les paires compatibles…")
    common: dict[str, Any] = {
        "exhaustive_pairs": bool(request.automatic_pairs),
        "local_pool_size": max(1, min(int(request.local_pool_size), 250)),
        "remote_pool_size": max(1, min(int(request.remote_pool_size), 500)),
        "surface": request.surface,
        "distance": request.distance,
        "style": request.style,
        "raw_payload": raw_payload,
        "course_weights_path": manual_weights.course_weights_path,
        "course_key": request.course_key,
        "course_conditions": request.course_conditions or {},
        "scoring_config_path": scoring_config,
        "top_n": max(1, int(request.top_n)),
        "api_operation": operation,
        "required_main_factors": (generated_meta.get("hard_filters") or []),
        "effective_uql": effective_uql,
        "lineage_blue_filter": request.lineage_blue_filter,
        "lineage_pink_filter": request.lineage_pink_filter,
        "logger": logger,
    }
    if request.search_mode == "parent":
        result = rank_online_parent_pairs(
            request.master_path,
            linked.json_path,
            manual_weights.weights_path,
            linked.race_factor_skills_path,
            linked.skills_catalog_path,
            output,
            ace_card_id=request.ace_card_id,
            fixed_parent_trained_id=request.fixed_local_id,
            required_parent_card_id=request.required_parent_card_id,
            allowed_parent_card_ids=list(request.allowed_parent_card_ids),
            excluded_parent_card_ids=list(request.excluded_parent_card_ids),
            **common,
        )
    else:
        result = rank_online_grandparent_pairs(
            request.master_path,
            linked.json_path,
            manual_weights.weights_path,
            linked.skills_catalog_path,
            output,
            race_factor_catalog_path=linked.race_factor_skills_path,
            ace_card_id=request.ace_card_id,
            target_parent_card_id=int(request.target_parent_card_id or 0),
            fixed_grandparent_trained_id=request.fixed_local_id,
            opposing_parent_trained_id=request.opposing_parent_trained_id,
            opposing_parent=request.opposing_parent_payload,
            planned_g1_budget=max(0, min(int(request.planned_g1_budget), 40)),
            g1_win_probability_cutoff=max(
                0.0, min(float(request.g1_win_probability_cutoff), 1.0)
            ),
            **common,
        )
    progress(100, "Recherche uma.moe terminée.")
    return result


def load_opposing_parent_candidates(
    master_path: Path, payload_path: Path
) -> list[dict[str, Any]]:
    """Extract selectable complete opposing-parent branches from a JSON file."""
    payload = json.loads(Path(payload_path).read_text(encoding="utf-8-sig"))
    return extract_opposing_parent_candidates(master_path, payload)


UMADUMP_COLLECTION_FILE = "trained_chara_data.json"
UMAEXTRACTOR_COLLECTION_FILE = "data.json"


def extractor_backend(extractor: Path) -> str:
    """Tell the two supported extraction backends apart.

    umadump reads the game memory and writes several JSON files next to the
    working directory; UmaExtractor intercepts a cached API response and
    writes a single ``data.json``. Detection is by name so the user only has
    to point at the executable, with no extra switch to keep in sync.
    """
    haystack = f"{extractor.stem} {extractor.parent.name}".lower()
    return "umadump" if "umadump" in haystack else "umaextractor"


def run_extractor(
    extractor: Path,
    *,
    output_dir: Path | None = None,
    logger: LogCallback,
) -> Path:
    if not extractor.is_file():
        raise LinkerError(
            "Sélectionne umaextractor.exe ou umadump.exe, ou utilise un export JSON existant."
        )
    backend = extractor_backend(extractor)
    if backend == "umadump":
        return _run_umadump(extractor, output_dir=output_dir, logger=logger)
    return _run_umaextractor(extractor, logger=logger)


def _extractor_command(extractor: Path, arguments: list[str]) -> list[str]:
    if extractor.suffix.lower() != ".py":
        return [str(extractor), *arguments]
    if getattr(sys, "frozen", False):
        raise LinkerError(
            "La version Windows autonome nécessite un exécutable ; un script .py requiert une installation Python séparée."
        )
    return [sys.executable, str(extractor), *arguments]


def _stream_extractor(command: list[str], cwd: Path, label: str, logger: LogCallback) -> None:
    with subprocess.Popen(
        command,
        cwd=str(cwd),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    ) as process:
        assert process.stdout is not None
        for line in process.stdout:
            clean = line.rstrip()
            if clean:
                logger(f"{label}: {clean}")
        code = process.wait()
    if code != 0:
        raise LinkerError(f"{label} s'est terminé avec le code {code}.")


def _run_umaextractor(extractor: Path, *, logger: LogCallback) -> Path:
    logger(f"Lancement de {extractor.name} en mode CLI…")
    _stream_extractor(
        _extractor_command(extractor, ["--cli"]),
        extractor.parent,
        "UmaExtractor",
        logger,
    )
    candidates = (
        extractor.parent / UMAEXTRACTOR_COLLECTION_FILE,
        Path.home() / "Documents" / UMAEXTRACTOR_COLLECTION_FILE,
    )
    for data_json in candidates:
        if data_json.is_file():
            logger(f"JSON extrait : {data_json}")
            return data_json
    raise LinkerError("UmaExtractor a terminé, mais aucun data.json n'a été trouvé.")


def _run_umadump(
    extractor: Path, *, output_dir: Path | None, logger: LogCallback
) -> Path:
    # umadump writes its exports relative to the working directory, so run it
    # from the output folder instead of leaving the files next to the tool.
    destination = Path(output_dir).expanduser() if output_dir else extractor.parent
    destination.mkdir(parents=True, exist_ok=True)
    logger(f"Lancement de {extractor.name} — lecture de la mémoire du jeu…")
    _stream_extractor(
        _extractor_command(extractor, ["--rerun-mode", "once", "--no-update-check"]),
        destination,
        "umadump",
        logger,
    )
    candidates = (
        destination / UMADUMP_COLLECTION_FILE,
        extractor.parent / UMADUMP_COLLECTION_FILE,
    )
    for export in candidates:
        if export.is_file():
            logger(f"JSON extrait : {export}")
            return export
    raise LinkerError(
        "umadump a terminé, mais aucun trained_chara_data.json n'a été trouvé."
    )


def run_extract_and_link(
    request: ExtractRequest,
    *,
    logger: LogCallback,
    progress: ProgressCallback,
) -> ExtractLinkResult:
    if not request.master_path.is_file():
        raise LinkerError("Sélectionne un master.mdb valide.")
    request.output_dir.mkdir(parents=True, exist_ok=True)
    progress(6, "Connexion au jeu et extraction…")
    data_json = run_extractor(
        request.extractor_path, output_dir=request.output_dir, logger=logger
    )
    progress(48, "Extraction terminée ; liaison…")
    linked = link_veterans(
        request.master_path, data_json, request.output_dir, logger
    )
    progress(100, "Extraction et liaison terminées.")
    return ExtractLinkResult(data_json, linked)


def run_catalog(
    request: CatalogRequest,
    *,
    logger: LogCallback,
    progress: ProgressCallback,
) -> SkillCatalogResult:
    if not request.master_path.is_file():
        raise LinkerError("Sélectionne un master.mdb valide.")
    request.output_dir.mkdir(parents=True, exist_ok=True)
    progress(20, "Génération du catalogue skills…")
    result = generate_skill_catalogs(request.master_path, request.output_dir, logger)
    progress(100, "Catalogue généré.")
    return result


def run_simulator_import(
    request: SimulatorImportRequest,
    *,
    logger: LogCallback,
    progress: ProgressCallback,
) -> SimulatorWeightResult:
    if not request.master_path.is_file():
        raise LinkerError("Sélectionne un master.mdb valide.")
    if not request.batch_path.is_file():
        raise LinkerError("Sélectionne un batch Umalator JSON valide.")
    if request.course_overrides_path is not None and not request.course_overrides_path.is_file():
        raise LinkerError("Sélectionne un fichier d'overrides de course valide.")
    request.output_dir.mkdir(parents=True, exist_ok=True)
    progress(18, "Actualisation du catalogue depuis le MDB…")
    catalog = generate_skill_catalogs(request.master_path, request.output_dir, logger)
    progress(58, "Normalisation des résultats Umalator…")
    adjustments = resource_base_dir() / "default_manual_adjustments.json"
    result = generate_simulator_weights(
        request.batch_path,
        catalog.skills_path,
        catalog.weights_template_path,
        request.output_dir,
        manual_adjustments_path=(adjustments if adjustments.is_file() else None),
        course_overrides_path=request.course_overrides_path,
        logger=logger,
    )
    progress(100, "Import Umalator terminé.")
    return result
