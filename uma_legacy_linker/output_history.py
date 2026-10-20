from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CURRENT_REVISION = "current"
PREVIOUS_REVISION = "previous"
REVISION_KEYS = (CURRENT_REVISION, PREVIOUS_REVISION)


@dataclass(frozen=True)
class OutputRevision:
    """One retained generation of an output file."""

    key: str
    path: Path
    modified_at_utc: str


@dataclass(frozen=True)
class SourceArtifact:
    """A source file recorded in an output's metadata."""

    role: str
    filename: str
    sha256: str


@dataclass(frozen=True)
class OutputProvenance:
    """Display-safe provenance shared by CLI outputs and the Qt UI."""

    revision: OutputRevision
    generated_at_utc: str
    source: str
    schema_version: str
    sources: tuple[SourceArtifact, ...]


def previous_output_path(path: str | Path) -> Path:
    resolved = Path(path)
    return resolved.with_name(f"{resolved.stem}.prev{resolved.suffix}")


def output_revision_path(path: str | Path, revision_key: str) -> Path:
    """Resolve a retained revision without accepting arbitrary paths."""
    current = Path(path)
    if revision_key == CURRENT_REVISION:
        return current
    if revision_key == PREVIOUS_REVISION:
        return previous_output_path(current)
    raise ValueError(f"Unknown output revision: {revision_key}")


def available_output_revisions(path: str | Path) -> tuple[OutputRevision, ...]:
    """Return the current generation followed by its retained predecessor."""
    revisions: list[OutputRevision] = []
    for key in REVISION_KEYS:
        candidate = output_revision_path(path, key)
        if not candidate.is_file():
            continue
        modified = datetime.fromtimestamp(
            candidate.stat().st_mtime,
            tz=timezone.utc,
        ).isoformat()
        revisions.append(OutputRevision(key, candidate, modified))
    return tuple(revisions)


def format_output_timestamp(value: object) -> str:
    """Render an ISO timestamp in the user's local timezone when possible."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone().strftime("%Y-%m-%d %H:%M")


def output_provenance(
    revision: OutputRevision,
    payload: dict[str, Any],
) -> OutputProvenance:
    """Extract the stable provenance subset emitted by every main report."""
    metadata = payload.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    sources: list[SourceArtifact] = []
    for key, value in metadata.items():
        if not key.startswith("source_") or not isinstance(value, dict):
            continue
        filename = str(value.get("filename") or "").strip()
        sha256 = str(value.get("sha256") or "").strip()
        if filename or sha256:
            sources.append(
                SourceArtifact(key.removeprefix("source_"), filename, sha256)
            )
    version = metadata.get("schema_version", metadata.get("format_version", ""))
    source = metadata.get("source", metadata.get("purpose", ""))
    return OutputProvenance(
        revision=revision,
        generated_at_utc=str(metadata.get("generated_at_utc") or ""),
        source=str(source or ""),
        schema_version=str(version or ""),
        sources=tuple(sorted(sources, key=lambda item: item.role)),
    )


def read_json_output_revision(
    path: str | Path,
    revision_key: str = CURRENT_REVISION,
) -> tuple[dict[str, Any], OutputProvenance]:
    """Read one retained JSON generation and return its provenance."""
    revision_path = output_revision_path(path, revision_key)
    payload = json.loads(revision_path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("La sortie doit contenir un objet JSON.")
    revision = OutputRevision(
        revision_key,
        revision_path,
        datetime.fromtimestamp(
            revision_path.stat().st_mtime,
            tz=timezone.utc,
        ).isoformat(),
    )
    return payload, output_provenance(revision, payload)


def write_text_with_history(
    path: str | Path,
    content: str,
    *,
    encoding: str = "utf-8",
) -> Path:
    """Atomically replace one output while retaining exactly one predecessor."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    history_temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding=encoding,
            newline="\n",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            stream.write(content)
            temporary = Path(stream.name)
        if destination.is_file():
            with tempfile.NamedTemporaryFile(
                dir=destination.parent,
                prefix=f".{destination.name}.history.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                history_temporary = Path(stream.name)
            shutil.copy2(destination, history_temporary)
            history_temporary.replace(previous_output_path(destination))
        temporary.replace(destination)
        return destination
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        if history_temporary is not None:
            history_temporary.unlink(missing_ok=True)


def write_json_with_history(path: str | Path, payload: Any, *, indent: int | None = 2) -> Path:
    return write_text_with_history(
        path,
        json.dumps(payload, ensure_ascii=False, indent=indent) + "\n",
    )
