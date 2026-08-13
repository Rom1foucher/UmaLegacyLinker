from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from loop_models import LOOP_SCHEMA_VERSION, LoopProject


class LoopRepositoryError(RuntimeError):
    pass


def loop_projects_path(output_dir: str | Path) -> Path:
    return Path(output_dir).expanduser() / "white_loop_projects.json"


class LoopProjectRepository:
    """Versioned JSON sidecar for durable White Loop Workshop projects."""

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()

    def load(self) -> list[LoopProject]:
        if not self.path.is_file():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except OSError as exc:
            raise LoopRepositoryError(
                f"Impossible de lire les projets de looping : {self.path}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise LoopRepositoryError(
                f"Le fichier de projets de looping est invalide : {self.path.name}"
            ) from exc
        if not isinstance(payload, dict):
            raise LoopRepositoryError(
                "Le fichier de projets de looping doit contenir un objet JSON."
            )
        try:
            schema_version = int(payload.get("schema_version") or 0)
        except (TypeError, ValueError):
            schema_version = 0
        if schema_version not in {1, LOOP_SCHEMA_VERSION}:
            raise LoopRepositoryError(
                "Version de projets de looping non prise en charge : "
                f"{schema_version}."
            )
        projects = payload.get("projects")
        if not isinstance(projects, list):
            raise LoopRepositoryError(
                "Le fichier de projets de looping ne contient pas de liste de projets."
            )
        try:
            return [
                LoopProject.from_dict(item)
                for item in projects
                if isinstance(item, dict)
            ]
        except (TypeError, ValueError) as exc:
            raise LoopRepositoryError(
                f"Projet de looping invalide : {exc}"
            ) from exc

    def save(self, projects: Iterable[LoopProject]) -> Path:
        ordered = sorted(
            projects,
            key=lambda project: (project.updated_at, project.name.casefold()),
            reverse=True,
        )
        payload: dict[str, Any] = {
            "schema_version": LOOP_SCHEMA_VERSION,
            "projects": [project.to_dict() for project in ordered],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp")
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.path)
        except OSError as exc:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise LoopRepositoryError(
                f"Impossible d’enregistrer les projets de looping : {self.path}"
            ) from exc
        return self.path

    def upsert(self, project: LoopProject) -> list[LoopProject]:
        projects = self.load()
        project.touch()
        for index, current in enumerate(projects):
            if current.project_id == project.project_id:
                projects[index] = project
                break
        else:
            projects.append(project)
        self.save(projects)
        return projects

    def delete(self, project_id: str) -> list[LoopProject]:
        """Delete exactly one project and return the remaining projects.

        The caller is responsible for the user-facing confirmation.  Keeping
        the operation ID-based avoids accidentally removing a project that only
        happens to share a display name.
        """

        requested = str(project_id or "").strip()
        if not requested:
            raise LoopRepositoryError("Projet de looping introuvable.")
        projects = self.load()
        remaining = [project for project in projects if project.project_id != requested]
        if len(remaining) == len(projects):
            raise LoopRepositoryError("Projet de looping introuvable.")
        self.save(remaining)
        return remaining

    def active_trained_ids(self) -> set[int]:
        return {
            trained_id
            for project in self.load()
            for trained_id in project.active_trained_ids()
        }
