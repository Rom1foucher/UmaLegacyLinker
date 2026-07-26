"""Command-line interface for Uma Legacy Linker.

The GUI (``qt_app.py``) is the recommended workflow. This module keeps the
headless linking, catalogue-generation, ranking and Transfer Helper commands
available without any UI toolkit, wrapping the same engines the Qt shell uses.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from legacy_linker import LinkerError, link_veterans
from manual_weights import generate_manual_skill_weights
from parent_optimizer import OptimizerError, optimize_parents
from scoring_config import (
    deep_merge,
    migrate_scoring_overrides,
    read_json_object,
    validate_scoring_config,
    validate_skill_priorities_config,
    write_json_object,
)
from simulator_weights import generate_simulator_weights
from skill_catalog import generate_skill_catalogs
from transfer_helper import TransferHelperError, analyze_transfer_candidates
from ui_qt.core import (
    APP_NAME,
    default_scoring_path,
    default_skill_priorities_path,
    resource_base_dir,
)


def run_cli(args: argparse.Namespace) -> int:
    try:
        if args.transfer_helper:
            if not args.json:
                raise TransferHelperError("--transfer-helper requiert --json.")
            linked = link_veterans(
                args.master,
                args.json,
                args.output,
                logger=lambda message: print(message, flush=True),
            )
            default_course_overrides = resource_base_dir() / "default_course_overrides.json"
            course_overrides = args.course_overrides or (
                str(default_course_overrides) if default_course_overrides.is_file() else None
            )
            default_priorities = read_json_object(default_skill_priorities_path())
            effective_priorities = default_priorities
            if args.skill_priorities:
                custom_priorities = read_json_object(args.skill_priorities)
                effective_priorities = deep_merge(default_priorities, custom_priorities)
            validate_skill_priorities_config(effective_priorities)
            priorities = write_json_object(
                Path(args.output).expanduser().resolve() / "active_skill_priorities.json",
                effective_priorities,
            )
            manual_weights = generate_manual_skill_weights(
                linked.skills_catalog_path,
                priorities,
                args.output,
                course_overrides_path=course_overrides,
                logger=lambda message: print(message, flush=True),
            )
            default_payload = read_json_object(default_scoring_path())
            effective_payload = default_payload
            if args.scoring_config:
                custom_payload = read_json_object(args.scoring_config)
                effective_payload = deep_merge(
                    default_payload,
                    migrate_scoring_overrides(default_payload, custom_payload),
                )
            validate_scoring_config(effective_payload)
            scoring = write_json_object(
                Path(args.output).expanduser().resolve() / "active_parent_scoring.json",
                effective_payload,
            )
            result = analyze_transfer_candidates(
                args.master,
                linked.json_path,
                manual_weights.weights_path,
                linked.race_factor_skills_path,
                linked.skills_catalog_path,
                args.output,
                course_weights_path=manual_weights.course_weights_path,
                scoring_config_path=scoring,
                logger=lambda message: print(message, flush=True),
            )
            print(f"Rapport : {result.report_json_path}")
            print(f"CSV : {result.candidates_csv_path}")
            print(f"Résumé : {result.summary_txt_path}")
            print(
                f"Verdicts : {result.safe_transfer_count} transfert(s) sûr(s), "
                f"{result.review_count} à examiner, "
                f"{result.likely_keep_count} probablement à conserver, "
                f"{result.keep_count} à conserver."
            )
            return 0
        if args.rank_parents:
            if not args.json or not args.ace_card_id or not args.future_parent_card_id:
                raise OptimizerError("--rank-parents requiert --json, --ace-card-id et --future-parent-card-id.")
            linked = link_veterans(
                args.master,
                args.json,
                args.output,
                logger=lambda message: print(message, flush=True),
            )
            default_course_overrides = resource_base_dir() / "default_course_overrides.json"
            course_overrides = args.course_overrides or (
                str(default_course_overrides) if default_course_overrides.is_file() else None
            )
            default_priorities = read_json_object(default_skill_priorities_path())
            effective_priorities = default_priorities
            if args.skill_priorities:
                custom_priorities = read_json_object(args.skill_priorities)
                effective_priorities = deep_merge(default_priorities, custom_priorities)
            validate_skill_priorities_config(effective_priorities)
            priorities = write_json_object(
                Path(args.output).expanduser().resolve() / "active_skill_priorities.json",
                effective_priorities,
            )
            manual_weights = generate_manual_skill_weights(
                linked.skills_catalog_path,
                priorities,
                args.output,
                course_overrides_path=course_overrides,
                logger=lambda message: print(message, flush=True),
            )
            default_payload = read_json_object(default_scoring_path())
            effective_payload = default_payload
            if args.scoring_config:
                custom_payload = read_json_object(args.scoring_config)
                effective_payload = deep_merge(
                    default_payload,
                    migrate_scoring_overrides(default_payload, custom_payload),
                )
            validate_scoring_config(effective_payload)
            scoring = write_json_object(
                Path(args.output).expanduser().resolve() / "active_parent_scoring.json",
                effective_payload,
            )
            result = optimize_parents(
                args.master,
                linked.json_path,
                manual_weights.weights_path,
                linked.race_factor_skills_path,
                linked.skills_catalog_path,
                args.output,
                ace_card_id=args.ace_card_id,
                future_parent_card_id=args.future_parent_card_id,
                surface=args.surface,
                distance=args.distance,
                style=args.style,
                course_weights_path=manual_weights.course_weights_path,
                course_key=args.course_key,
                course_conditions={
                    key: value for key, value in {
                        "track_id": args.track_id,
                        "rotation": args.rotation,
                        "season": ([1, 5] if args.season == 1 else args.season),
                        "weather": args.weather,
                        "ground_condition": args.ground_condition,
                    }.items() if value is not None
                },
                scoring_config_path=scoring,
                top_n=args.top,
                logger=lambda message: print(message, flush=True),
            )
            print(f"Classements : {result.rankings_json_path}")
            print(f"Paires : {result.parent_pairs_csv_path}")
            print(f"Futurs grands-parents : {result.future_grandparents_csv_path}")
            return 0
        if args.catalog_only or args.umalator_batch:
            catalog = generate_skill_catalogs(
                args.master,
                args.output,
                logger=lambda message: print(message, flush=True),
            )
            print(f"Skills/conditions : {catalog.skills_path}")
            print(f"Types de conditions : {catalog.condition_types_path}")
            print(f"Template de poids : {catalog.weights_template_path}")
            print(f"Race factors : {catalog.race_factor_skills_path}")
            if args.umalator_batch:
                adjustments = resource_base_dir() / "default_manual_adjustments.json"
                default_course_overrides = resource_base_dir() / "default_course_overrides.json"
                course_overrides = args.course_overrides or (
                    str(default_course_overrides)
                    if default_course_overrides.is_file()
                    else None
                )
                result = generate_simulator_weights(
                    args.umalator_batch,
                    catalog.skills_path,
                    catalog.weights_template_path,
                    args.output,
                    manual_adjustments_path=(adjustments if adjustments.is_file() else None),
                    course_overrides_path=course_overrides,
                    logger=lambda message: print(message, flush=True),
                )
                print(f"Poids simulateur : {result.weights_path}")
                print(f"File de revue : {result.review_queue_path}")
                print(f"Synthèse CSV : {result.summary_csv_path}")
                if result.course_weights_path:
                    print(f"Poids par course : {result.course_weights_path}")
            return 0
        result = link_veterans(
            args.master,
            args.json,
            args.output,
            logger=lambda message: print(message, flush=True),
        )
    except (LinkerError, OptimizerError, TransferHelperError, OSError, ValueError, json.JSONDecodeError, sqlite3.Error) as exc:  # type: ignore[name-defined]
        print(f"Erreur : {exc}", file=sys.stderr)
        return 1
    print(f"JSON : {result.json_path}")
    print(f"CSV : {result.csv_path}")
    print(f"Rapport : {result.report_path}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--master", help="Chemin de master.mdb")
    parser.add_argument(
        "--json",
        help="Chemin de data.json ou trained_chara_data.json",
    )
    parser.add_argument("--output", help="Dossier de sortie", default="output")
    parser.add_argument(
        "--catalog-only",
        action="store_true",
        help="Génère uniquement les catalogues skills/conditions depuis le MDB.",
    )
    parser.add_argument(
        "--umalator-batch",
        help="Mode legacy : importe un batch Skill Chart Umalator v2 pour diagnostic. Le classement utilise les poids manuels.",
    )
    parser.add_argument(
        "--course-overrides",
        help="Fichier JSON facultatif d'overrides liés au tracé exact.",
    )
    parser.add_argument("--rank-parents", action="store_true", help="Lance le classement complet des lignées.")
    parser.add_argument(
        "--transfer-helper",
        action="store_true",
        help="Analyse les vétérans locaux et identifie les doublons strictement dominés.",
    )
    parser.add_argument("--ace-card-id", type=int, help="Costume ID de l'Ace cible.")
    parser.add_argument("--future-parent-card-id", type=int, help="Costume ID du parent à produire pour le calcul exact des futurs grands-parents.")
    parser.add_argument("--track-id", type=int, help="Hippodrome cible (track_id MDB).")
    parser.add_argument("--rotation", type=int, choices=(1, 2), help="1=droite, 2=gauche.")
    parser.add_argument("--season", type=int, choices=(1, 2, 3, 4), help="1=printemps, 2=été, 3=automne, 4=hiver.")
    parser.add_argument("--weather", type=int, choices=(1, 2, 3, 4), help="1=soleil, 2=nuageux, 3=pluie, 4=neige.")
    parser.add_argument("--ground-condition", type=int, choices=(1, 2, 3, 4), help="1=firm, 2=good, 3=soft, 4=heavy.")
    parser.add_argument("--surface", choices=("turf", "dirt"), default="turf")
    parser.add_argument("--distance", choices=("sprint", "mile", "medium", "long"), default="medium")
    parser.add_argument("--style", choices=("front_runner", "pace_chaser", "late_surger", "end_closer"), default="pace_chaser")
    parser.add_argument("--course-key", help="Preset exact de course, par exemple cm15_hanshin_2200_turf.")
    parser.add_argument(
        "--scoring-config",
        help="Profil JSON de pondération complet ou surcharges à fusionner avec le profil par défaut.",
    )
    parser.add_argument(
        "--skill-priorities",
        help="Priorités white skills complètes ou partielles à fusionner avec le profil par défaut.",
    )
    parser.add_argument("--top", type=int, default=30, help="Nombre de résultats détaillés dans le JSON.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.master:
        print("--master est requis.", file=sys.stderr)
        return 2
    if (
        not args.catalog_only
        and not args.umalator_batch
        and not args.rank_parents
        and not args.transfer_helper
        and not args.json
    ):
        print(
            "--json est requis sauf avec --catalog-only ou --umalator-batch.",
            file=sys.stderr,
        )
        return 2
    return run_cli(args)


if __name__ == "__main__":
    raise SystemExit(main())
