from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from skill_catalog import generate_skill_catalogs


FACTOR_TYPE_LABELS = {
    1: "blue_stat",
    2: "red_aptitude",
    3: "unique",
    4: "white_skill",
    5: "white_race",
    6: "scenario",
    7: "event",
}

FACTOR_TYPE_DESCRIPTIONS = {
    "blue_stat": "Blue stat Spark",
    "red_aptitude": "Red aptitude Spark",
    "unique": "Unique Spark",
    "white_skill": "White skill Spark",
    "white_race": "White race Spark",
    "scenario": "Scenario Spark",
    "event": "Event Spark",
    "other": "Other Spark",
}

POSITION_TO_PARENT = {10: "grandparent_1", 20: "grandparent_2"}


class LinkerError(RuntimeError):
    pass


@dataclass(frozen=True)
class LinkResult:
    json_path: Path
    csv_path: Path
    report_path: Path
    skills_catalog_path: Path
    condition_types_path: Path
    weights_template_path: Path
    race_factor_skills_path: Path
    veteran_count: int
    unresolved_factor_ids: tuple[int, ...]
    unresolved_card_ids: tuple[int, ...]
    g1_validation_mismatch_count: int


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_json_root(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        veterans = payload
    elif isinstance(payload, dict):
        for key in ("trained_chara_array", "veterans", "data"):
            candidate = payload.get(key)
            if isinstance(candidate, list):
                veterans = candidate
                break
        else:
            raise LinkerError(
                "Le JSON ne contient pas de liste de vétérans reconnue "
                "(liste racine ou clé trained_chara_array/veterans/data)."
            )
    else:
        raise LinkerError("Le JSON vétérans doit contenir une liste ou un objet.")

    result: list[dict[str, Any]] = []
    for index, veteran in enumerate(veterans):
        if not isinstance(veteran, dict):
            raise LinkerError(f"Entrée vétéran #{index} invalide : objet JSON attendu.")
        result.append(veteran)
    return result


def require_tables(connection: sqlite3.Connection, tables: Iterable[str]) -> None:
    existing = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    missing = [table for table in tables if table not in existing]
    if missing:
        raise LinkerError(
            "MDB incompatible : tables manquantes : " + ", ".join(sorted(missing))
        )


def text_map(connection: sqlite3.Connection, category: int) -> dict[int, str]:
    return {
        int(row[0]): str(row[1])
        for row in connection.execute(
            'SELECT "index", text FROM text_data WHERE category = ?', (category,)
        )
    }


def grouped_factors(factors: list[dict[str, Any]]) -> dict[str, Any]:
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for factor in factors:
        by_type[factor["type"]].append(factor)
    return {
        "all": factors,
        "by_type": {
            factor_type: values
            for factor_type, values in sorted(by_type.items())
        },
    }


def factor_sort_key(factor: dict[str, Any]) -> tuple[int, str, int]:
    order = {
        "blue_stat": 0,
        "red_aptitude": 1,
        "unique": 2,
        "scenario": 3,
        "white_race": 4,
        "white_skill": 5,
        "event": 6,
        "other": 7,
    }
    return (order.get(factor["type"], 99), factor["name"], factor["factor_id"])


class MasterResolver:
    REQUIRED_TABLES = (
        "card_data",
        "text_data",
        "succession_factor",
        "single_mode_wins_saddle",
        "race_instance",
        "race",
        "single_mode_program",
    )

    def __init__(self, master_path: Path):
        self.master_path = master_path
        try:
            self.connection = sqlite3.connect(
                f"file:{master_path.as_posix()}?mode=ro", uri=True
            )
        except sqlite3.Error as exc:
            raise LinkerError(f"Impossible d'ouvrir le MDB comme SQLite : {exc}") from exc
        self.connection.row_factory = sqlite3.Row
        try:
            require_tables(self.connection, self.REQUIRED_TABLES)
        except Exception:
            self.connection.close()
            raise

        self.card_names = text_map(self.connection, 4)
        self.costume_names = text_map(self.connection, 5)
        self.chara_names = text_map(self.connection, 6)
        self.factor_names = text_map(self.connection, 147)
        self.factor_descriptions = text_map(self.connection, 172)
        self.race_names = text_map(self.connection, 28)
        self.race_short_names = text_map(self.connection, 29)

        self.cards: dict[int, dict[str, Any]] = {}
        for row in self.connection.execute("SELECT id, chara_id FROM card_data"):
            card_id = int(row["id"])
            chara_id = int(row["chara_id"])
            full_name = self.card_names.get(card_id)
            costume = self.costume_names.get(card_id)
            uma_name = self.chara_names.get(chara_id)
            if not full_name and costume and uma_name:
                full_name = f"{costume} {uma_name}".strip()
            self.cards[card_id] = {
                "card_id": card_id,
                "chara_id": chara_id,
                "uma_name": uma_name or f"Unknown chara {chara_id}",
                "card_name": full_name or uma_name or f"Unknown costume {card_id}",
                "costume_name": costume or "",
            }

        self.factors: dict[int, dict[str, Any]] = {}
        for row in self.connection.execute(
            "SELECT factor_id, factor_group_id, rarity, factor_type, effect_group_id "
            "FROM succession_factor"
        ):
            factor_id = int(row["factor_id"])
            factor_type_code = int(row["factor_type"])
            stars = int(row["rarity"])
            factor_type = FACTOR_TYPE_LABELS.get(factor_type_code, "other")
            self.factors[factor_id] = {
                "factor_id": factor_id,
                "factor_group_id": int(row["factor_group_id"]),
                "effect_group_id": int(row["effect_group_id"]),
                "name": self.factor_names.get(factor_id, f"Unknown factor {factor_id}"),
                "stars": stars,
                "stars_text": "★" * max(0, stars),
                "type": factor_type,
                "description": self.factor_descriptions.get(factor_id, ""),
            }

        self.g1_by_saddle_id = self._load_g1_saddles()
        self.g1_by_program_id = self._load_g1_programs()

    def close(self) -> None:
        self.connection.close()

    def _load_g1_saddles(self) -> dict[int, dict[str, Any]]:
        result: dict[int, dict[str, Any]] = {}
        query = """
            SELECT id, race_instance_id_1, race_instance_id_2,
                   race_instance_id_3, race_instance_id_4,
                   race_instance_id_5, race_instance_id_6,
                   race_instance_id_7, race_instance_id_8
            FROM single_mode_wins_saddle
            WHERE win_saddle_type = 3
        """
        for row in self.connection.execute(query):
            saddle_id = int(row["id"])
            instance_ids = [
                int(row[f"race_instance_id_{index}"])
                for index in range(1, 9)
                if row[f"race_instance_id_{index}"]
            ]
            selected = None
            for instance_id in instance_ids:
                race = self.connection.execute(
                    """
                    SELECT ri.id AS race_instance_id, r.id AS race_id, r.grade, r."group" AS race_group
                    FROM race_instance ri
                    JOIN race r ON r.id = ri.race_id
                    WHERE ri.id = ?
                    """,
                    (instance_id,),
                ).fetchone()
                if (
                    race
                    and int(race["grade"]) == 100
                    and int(race["race_group"]) == 1
                ):
                    selected = {
                        "saddle_id": saddle_id,
                        "race_instance_id": instance_id,
                        "race_id": int(race["race_id"]),
                        "name": self.race_names.get(
                            instance_id,
                            self.race_short_names.get(instance_id, f"G1 {instance_id}"),
                        ),
                    }
                    break
            if selected:
                result[saddle_id] = selected
        return result

    def _load_g1_programs(self) -> dict[int, dict[str, Any]]:
        result: dict[int, dict[str, Any]] = {}
        query = """
            SELECT p.id AS program_id,
                   ri.id AS race_instance_id,
                   r.id AS race_id,
                   r.grade AS grade
            FROM single_mode_program p
            JOIN race_instance ri ON ri.id = p.race_instance_id
            JOIN race r ON r.id = ri.race_id
            WHERE r.grade = 100 AND r."group" = 1
        """
        for row in self.connection.execute(query):
            program_id = int(row["program_id"])
            instance_id = int(row["race_instance_id"])
            result[program_id] = {
                "program_id": program_id,
                "race_instance_id": instance_id,
                "race_id": int(row["race_id"]),
                "name": self.race_names.get(
                    instance_id,
                    self.race_short_names.get(instance_id, f"G1 {instance_id}"),
                ),
            }
        return result

    def resolve_card(self, card_id: int) -> dict[str, Any]:
        return dict(
            self.cards.get(
                card_id,
                {
                    "card_id": card_id,
                    "chara_id": None,
                    "uma_name": f"Unknown costume {card_id}",
                    "card_name": f"Unknown costume {card_id}",
                    "costume_name": "",
                },
            )
        )

    def resolve_factors(
        self, factor_info_array: Any, unresolved: set[int]
    ) -> dict[str, Any]:
        resolved: list[dict[str, Any]] = []
        if not isinstance(factor_info_array, list):
            return grouped_factors(resolved)
        for raw_factor in factor_info_array:
            if not isinstance(raw_factor, dict):
                continue
            raw_id = raw_factor.get("factor_id")
            if not isinstance(raw_id, int):
                continue
            factor = self.factors.get(raw_id)
            if factor is None:
                unresolved.add(raw_id)
                factor = {
                    "factor_id": raw_id,
                    "name": f"Unknown factor {raw_id}",
                    "stars": None,
                    "stars_text": "",
                    "type": "other",
                    "description": "",
                }
            resolved.append(dict(factor))
        resolved.sort(key=factor_sort_key)
        return grouped_factors(resolved)

    def resolve_g1_saddles(self, saddle_ids: Any) -> dict[str, Any]:
        details_by_name: dict[str, dict[str, Any]] = {}
        if isinstance(saddle_ids, list):
            for raw_id in saddle_ids:
                if not isinstance(raw_id, int):
                    continue
                detail = self.g1_by_saddle_id.get(raw_id)
                if detail:
                    details_by_name.setdefault(detail["name"], dict(detail))
        details = sorted(details_by_name.values(), key=lambda item: item["name"])
        return {
            "count": len(details),
            "names": [detail["name"] for detail in details],
            "details": details,
        }

    def resolve_g1_results(self, race_results: Any) -> set[str]:
        names: set[str] = set()
        if not isinstance(race_results, list):
            return names
        for result in race_results:
            if not isinstance(result, dict) or result.get("result_rank") != 1:
                continue
            program_id = result.get("program_id")
            if not isinstance(program_id, int):
                continue
            race = self.g1_by_program_id.get(program_id)
            if race:
                names.add(race["name"])
        return names


def compact_factor(factor: dict[str, Any]) -> str:
    stars = factor.get("stars_text", "")
    return f"{factor.get('name', '')} {stars}".strip()


def summarize_factor_group(factors: dict[str, Any], factor_type: str) -> str:
    return " | ".join(
        compact_factor(factor)
        for factor in factors.get("by_type", {}).get(factor_type, [])
    )


def resolve_parent_snapshot(
    resolver: MasterResolver,
    snapshot: dict[str, Any] | None,
    local_trained_chara_id: Any,
    exported_ids: set[int],
    unresolved_factors: set[int],
    unresolved_cards: set[int],
) -> dict[str, Any] | None:
    if snapshot is None:
        return None
    card_id = snapshot.get("card_id")
    if not isinstance(card_id, int):
        return None
    if card_id not in resolver.cards:
        unresolved_cards.add(card_id)
    card = resolver.resolve_card(card_id)
    parent = {
        **card,
        "local_trained_chara_id": local_trained_chara_id
        if isinstance(local_trained_chara_id, int)
        else None,
        "present_in_export": isinstance(local_trained_chara_id, int)
        and local_trained_chara_id in exported_ids,
        "borrowed_or_external": bool(snapshot.get("owner_viewer_id")),
        "factors": resolver.resolve_factors(
            snapshot.get("factor_info_array"), unresolved_factors
        ),
        "g1_wins": resolver.resolve_g1_saddles(snapshot.get("win_saddle_id_array")),
    }
    return parent


def build_lineage_summary(
    self_entry: dict[str, Any], parent_1: dict[str, Any] | None, parent_2: dict[str, Any] | None
) -> dict[str, Any]:
    members = [
        ("parent", self_entry),
        ("grandparent_1", parent_1),
        ("grandparent_2", parent_2),
    ]
    factor_totals = Counter()
    factors_by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    g1_sources: dict[str, list[str]] = defaultdict(list)

    for source, member in members:
        if not member:
            continue
        for factor in member["factors"]["all"]:
            factor_totals[factor["type"]] += int(factor.get("stars") or 0)
            enriched = dict(factor)
            enriched["source"] = source
            enriched["source_uma"] = member["uma_name"]
            factors_by_type[factor["type"]].append(enriched)
        for race_name in member["g1_wins"]["names"]:
            g1_sources[race_name].append(source)

    all_g1 = sorted(g1_sources)
    repeated_g1 = {
        name: sources
        for name, sources in sorted(g1_sources.items())
        if len(sources) >= 2
    }
    return {
        "members_present": sum(member is not None for _, member in members),
        "total_stars_by_type": dict(sorted(factor_totals.items())),
        "factors_by_type": {
            factor_type: sorted(values, key=factor_sort_key)
            for factor_type, values in sorted(factors_by_type.items())
        },
        "g1_union": {
            "count": len(all_g1),
            "names": all_g1,
            "sources": dict(sorted(g1_sources.items())),
        },
        "g1_repeated_in_lineage": repeated_g1,
    }


def link_veterans(
    master_path: str | Path,
    veterans_json_path: str | Path,
    output_dir: str | Path,
    logger: Any | None = None,
) -> LinkResult:
    log = logger or (lambda _message: None)
    master = Path(master_path).expanduser().resolve()
    json_input = Path(veterans_json_path).expanduser().resolve()
    destination = Path(output_dir).expanduser().resolve()

    if not master.is_file():
        raise LinkerError(f"MDB introuvable : {master}")
    if not json_input.is_file():
        raise LinkerError(f"JSON vétérans introuvable : {json_input}")
    destination.mkdir(parents=True, exist_ok=True)

    log("Lecture du JSON vétérans…")
    with json_input.open("r", encoding="utf-8-sig") as stream:
        raw_payload = json.load(stream)
    veterans = normalize_json_root(raw_payload)
    exported_ids = {
        veteran["trained_chara_id"]
        for veteran in veterans
        if isinstance(veteran.get("trained_chara_id"), int)
    }
    log(f"{len(veterans)} vétérans chargés.")

    log("Lecture et indexation du master.mdb courant…")
    resolver = MasterResolver(master)
    unresolved_factors: set[int] = set()
    unresolved_cards: set[int] = set()
    linked_veterans: list[dict[str, Any]] = []
    validation_mismatches: list[dict[str, Any]] = []
    parent_snapshots = 0
    parents_present = 0

    try:
        for index, veteran in enumerate(veterans, start=1):
            card_id = veteran.get("card_id")
            if not isinstance(card_id, int):
                card_id = -1
            if card_id not in resolver.cards:
                unresolved_cards.add(card_id)
            card = resolver.resolve_card(card_id)
            own_factors = resolver.resolve_factors(
                veteran.get("factor_info_array"), unresolved_factors
            )
            own_g1 = resolver.resolve_g1_saddles(veteran.get("win_saddle_id_array"))
            result_g1 = resolver.resolve_g1_results(veteran.get("race_result_list"))
            saddle_g1 = set(own_g1["names"])
            if saddle_g1 != result_g1:
                validation_mismatches.append(
                    {
                        "trained_chara_id": veteran.get("trained_chara_id"),
                        "uma_name": card["uma_name"],
                        "only_in_win_saddle": sorted(saddle_g1 - result_g1),
                        "only_in_race_results": sorted(result_g1 - saddle_g1),
                    }
                )

            snapshots_by_position = {
                snapshot.get("position_id"): snapshot
                for snapshot in veteran.get("succession_chara_array", [])
                if isinstance(snapshot, dict)
                and snapshot.get("position_id") in POSITION_TO_PARENT
            }
            parent_1 = resolve_parent_snapshot(
                resolver,
                snapshots_by_position.get(10),
                veteran.get("succession_trained_chara_id_1"),
                exported_ids,
                unresolved_factors,
                unresolved_cards,
            )
            parent_2 = resolve_parent_snapshot(
                resolver,
                snapshots_by_position.get(20),
                veteran.get("succession_trained_chara_id_2"),
                exported_ids,
                unresolved_factors,
                unresolved_cards,
            )
            for parent in (parent_1, parent_2):
                if parent:
                    parent_snapshots += 1
                    if parent["present_in_export"]:
                        parents_present += 1

            entry = {
                "trained_chara_id": veteran.get("trained_chara_id"),
                "rank": veteran.get("rank"),
                "rank_score": veteran.get("rank_score"),
                "fans": veteran.get("fans"),
                "wins": veteran.get("wins"),
                "talent_level": veteran.get("talent_level"),
                "scenario_id": veteran.get("scenario_id"),
                "running_style": veteran.get("running_style"),
                "stats": {
                    "speed": veteran.get("speed"),
                    "stamina": veteran.get("stamina"),
                    "power": veteran.get("power"),
                    "guts": veteran.get("guts"),
                    "wiz": veteran.get("wiz"),
                },
                **card,
                "factors": own_factors,
                "g1_wins": own_g1,
                "when_used_as_parent": {
                    "grandparent_1": parent_1,
                    "grandparent_2": parent_2,
                },
            }
            entry["when_used_as_parent"]["lineage_summary"] = build_lineage_summary(
                entry, parent_1, parent_2
            )
            linked_veterans.append(entry)
            if index % 25 == 0 or index == len(veterans):
                log(f"Liaison : {index}/{len(veterans)}")
    finally:
        resolver.close()

    factor_count = Counter()
    g1_counts: list[int] = []
    for veteran in linked_veterans:
        for factor in veteran["factors"]["all"]:
            factor_count[factor["type"]] += 1
        g1_counts.append(veteran["g1_wins"]["count"])

    generated_at = datetime.now(timezone.utc).isoformat()
    metadata = {
        "format_version": 2,
        "generated_at_utc": generated_at,
        "purpose": "Legacy parent/grandparent analysis focused on Sparks/Factors and G1 wins.",
        "source_master_mdb": {
            "filename": master.name,
            "size_bytes": master.stat().st_size,
            "modified_at_utc": datetime.fromtimestamp(
                master.stat().st_mtime, timezone.utc
            ).isoformat(),
            "sha256": sha256_file(master),
        },
        "source_veterans_json": {
            "filename": json_input.name,
            "size_bytes": json_input.stat().st_size,
            "modified_at_utc": datetime.fromtimestamp(
                json_input.stat().st_mtime, timezone.utc
            ).isoformat(),
            "sha256": sha256_file(json_input),
        },
        "veteran_count": len(linked_veterans),
        "factor_type_labels": FACTOR_TYPE_DESCRIPTIONS,
        "g1_method": (
            "win_saddle_id_array resolved through single_mode_wins_saddle "
            "with win_saddle_type = 3 and race.grade = 100; compared with "
            "first-place official G1 race_result_list entries."
        ),
        "g1_validation_mismatch_count": len(validation_mismatches),
        "g1_validation_mismatches": validation_mismatches,
        "unresolved_factor_ids": sorted(unresolved_factors),
        "unresolved_card_ids": sorted(unresolved_cards),
        "direct_parent_snapshots": parent_snapshots,
        "direct_parents_still_present_in_export": parents_present,
        "direct_parent_snapshots_not_present_in_export": parent_snapshots
        - parents_present,
        "own_factor_count_by_type": dict(sorted(factor_count.items())),
        "g1_count_stats": {
            "min": min(g1_counts, default=0),
            "max": max(g1_counts, default=0),
            "average": round(sum(g1_counts) / len(g1_counts), 2)
            if g1_counts
            else 0,
        },
    }

    output_payload = {"metadata": metadata, "veterans": linked_veterans}
    json_path = destination / "veterans_legacy_linked.json"
    csv_path = destination / "veterans_legacy_summary.csv"
    report_path = destination / "veterans_legacy_report.txt"

    log("Écriture du JSON enrichi…")
    with json_path.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(output_payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")

    log("Écriture du CSV synthétique…")
    csv_columns = [
        "trained_chara_id",
        "uma_name",
        "card_name",
        "blue",
        "red",
        "unique",
        "scenario",
        "white_races",
        "white_skills",
        "g1_count",
        "g1_wins",
        "grandparent_1",
        "grandparent_1_blue",
        "grandparent_1_red",
        "grandparent_1_g1",
        "grandparent_2",
        "grandparent_2_blue",
        "grandparent_2_red",
        "grandparent_2_g1",
        "lineage_blue_stars",
        "lineage_red_stars",
        "lineage_unique_stars",
        "lineage_g1_union_count",
        "lineage_g1_union",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=csv_columns, delimiter=";")
        writer.writeheader()
        for veteran in linked_veterans:
            lineage = veteran["when_used_as_parent"]["lineage_summary"]
            parent_1 = veteran["when_used_as_parent"]["grandparent_1"]
            parent_2 = veteran["when_used_as_parent"]["grandparent_2"]
            totals = lineage["total_stars_by_type"]
            writer.writerow(
                {
                    "trained_chara_id": veteran["trained_chara_id"],
                    "uma_name": veteran["uma_name"],
                    "card_name": veteran["card_name"],
                    "blue": summarize_factor_group(veteran["factors"], "blue_stat"),
                    "red": summarize_factor_group(veteran["factors"], "red_aptitude"),
                    "unique": summarize_factor_group(veteran["factors"], "unique"),
                    "scenario": summarize_factor_group(veteran["factors"], "scenario"),
                    "white_races": summarize_factor_group(veteran["factors"], "white_race"),
                    "white_skills": summarize_factor_group(veteran["factors"], "white_skill"),
                    "g1_count": veteran["g1_wins"]["count"],
                    "g1_wins": " | ".join(veteran["g1_wins"]["names"]),
                    "grandparent_1": parent_1["card_name"] if parent_1 else "",
                    "grandparent_1_blue": summarize_factor_group(parent_1["factors"], "blue_stat") if parent_1 else "",
                    "grandparent_1_red": summarize_factor_group(parent_1["factors"], "red_aptitude") if parent_1 else "",
                    "grandparent_1_g1": " | ".join(parent_1["g1_wins"]["names"]) if parent_1 else "",
                    "grandparent_2": parent_2["card_name"] if parent_2 else "",
                    "grandparent_2_blue": summarize_factor_group(parent_2["factors"], "blue_stat") if parent_2 else "",
                    "grandparent_2_red": summarize_factor_group(parent_2["factors"], "red_aptitude") if parent_2 else "",
                    "grandparent_2_g1": " | ".join(parent_2["g1_wins"]["names"]) if parent_2 else "",
                    "lineage_blue_stars": totals.get("blue_stat", 0),
                    "lineage_red_stars": totals.get("red_aptitude", 0),
                    "lineage_unique_stars": totals.get("unique", 0),
                    "lineage_g1_union_count": lineage["g1_union"]["count"],
                    "lineage_g1_union": " | ".join(lineage["g1_union"]["names"]),
                }
            )

    log("Génération du catalogue skills et conditions…")
    catalogs = generate_skill_catalogs(master, destination, logger=log)

    report_lines = [
        "Uma Legacy Linker — rapport",
        "=" * 34,
        f"Généré : {generated_at}",
        f"MDB : {master}",
        f"JSON source : {json_input}",
        f"Vétérans : {len(linked_veterans)}",
        f"Parents/grands-parents analysés : {parent_snapshots}",
        f"Factors non résolus : {len(unresolved_factors)}",
        f"Cards non résolues : {len(unresolved_cards)}",
        f"Divergences de validation G1 : {len(validation_mismatches)}",
        "",
        "Sorties :",
        f"- {json_path.name}",
        f"- {csv_path.name}",
        f"- {catalogs.skills_path.name}",
        f"- {catalogs.condition_types_path.name}",
        f"- {catalogs.weights_template_path.name}",
        f"- {catalogs.race_factor_skills_path.name}",
    ]
    if unresolved_factors:
        report_lines.extend(
            ["", "Factor IDs non résolus :", ", ".join(map(str, sorted(unresolved_factors)))]
        )
    if unresolved_cards:
        report_lines.extend(
            ["", "Costume IDs non résolus :", ", ".join(map(str, sorted(unresolved_cards)))]
        )
    if validation_mismatches:
        report_lines.extend(["", "Divergences G1 :"])
        for mismatch in validation_mismatches:
            report_lines.append(json.dumps(mismatch, ensure_ascii=False))
    report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    log(f"Terminé : {json_path}")
    return LinkResult(
        json_path=json_path,
        csv_path=csv_path,
        report_path=report_path,
        skills_catalog_path=catalogs.skills_path,
        condition_types_path=catalogs.condition_types_path,
        weights_template_path=catalogs.weights_template_path,
        race_factor_skills_path=catalogs.race_factor_skills_path,
        veteran_count=len(linked_veterans),
        unresolved_factor_ids=tuple(sorted(unresolved_factors)),
        unresolved_card_ids=tuple(sorted(unresolved_cards)),
        g1_validation_mismatch_count=len(validation_mismatches),
    )
