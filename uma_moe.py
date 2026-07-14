from __future__ import annotations

import hashlib
import json
import math
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

try:
    import yaml  # PyYAML, bundled by the Windows build
except ImportError:  # pragma: no cover - handled with a clear runtime error
    yaml = None
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from legacy_linker import MasterResolver, grouped_factors
from parent_optimizer import (
    AffinityResolver,
    DISTANCE_FACTOR_NAMES,
    STYLE_FACTOR_NAMES,
    SURFACE_FACTOR_NAMES,
    OptimizerError,
    _affinity_score,
    _blue_score,
    _compile_static_condition_rules,
    _lineage_members,
    _member_g1,
    _pink_score,
    _race_skill_map,
    _read_json,
    _score_breakdown,
    _selected_weight_lookup,
    _static_condition_state,
    _white_generation_support_score,
    _white_score,
    evaluate_parent_branch,
    evaluate_parent_pair,
)

DEFAULT_API_BASE = "https://uma.moe/api"
DEFAULT_DOCS_URL = "https://uma.moe/api/docs"
MAX_FETCH_CANDIDATES = 2000


class UmaMoeError(RuntimeError):
    pass


@dataclass(frozen=True)
class OnlineSearchResult:
    rankings_json_path: Path
    rankings_csv_path: Path
    raw_response_path: Path
    diagnostics_path: Path
    result_count: int
    top_results: tuple[dict[str, Any], ...]
    fixed_grandparent: dict[str, Any] | None
    pair_mode: str
    local_pool_count: int
    remote_pool_count: int
    evaluated_pair_count: int
    ace: dict[str, Any]
    target_parent: dict[str, Any]
    api_operation: dict[str, Any] | None


@dataclass(frozen=True)
class OnlineParentSearchResult:
    rankings_json_path: Path
    rankings_csv_path: Path
    raw_response_path: Path
    diagnostics_path: Path
    result_count: int
    top_results: tuple[dict[str, Any], ...]
    fixed_parent: dict[str, Any] | None
    pair_mode: str
    local_pool_count: int
    remote_pool_count: int
    evaluated_pair_count: int
    ace: dict[str, Any]
    api_operation: dict[str, Any] | None


@dataclass(frozen=True)
class ApiOperation:
    method: str
    path: str
    score: int
    operation: dict[str, Any]
    path_item: dict[str, Any]


class UmaMoeApiClient:
    """Small stdlib-only client with OpenAPI runtime discovery.

    uma.moe exposes public API documentation. The concrete API can evolve, so this
    client deliberately discovers the search operation from the current OpenAPI
    document instead of hardcoding a single endpoint forever.
    """

    def __init__(
        self,
        base_url: str = DEFAULT_API_BASE,
        *,
        timeout: float = 25.0,
        user_agent: str = "UmaLegacyLinker/23 (+https://uma.moe/api/docs)",
        token: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.user_agent = user_agent
        self.token = token.strip() if token else None
        parsed = urllib.parse.urlparse(self.base_url)
        self.origin = f"{parsed.scheme}://{parsed.netloc}"
        self._spec: dict[str, Any] | None = None
        self._spec_url: str | None = None

    def _headers(self, *, json_body: bool = False) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": self.user_agent,
        }
        if json_body:
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
            headers["X-API-Key"] = self.token
        return headers

    def _request_document(
        self,
        url: str,
        *,
        method: str = "GET",
        query: dict[str, Any] | None = None,
        body: Any = None,
    ) -> Any:
        if query:
            # Confirmed empirically against uma.moe (2026-07): array-valued query
            # parameters (e.g. main_parent_pink_sparks) are NOT accepted as repeated
            # keys — that silently returns zero results. The server expects a single
            # comma-joined value per key.
            pairs: list[tuple[str, Any]] = []
            for key, raw in query.items():
                if raw is None:
                    continue
                if isinstance(raw, (list, tuple, set)):
                    values = [str(item) for item in raw if item is not None]
                    if not values:
                        continue
                    pairs.append((key, ",".join(values)))
                else:
                    pairs.append((key, raw))
            encoded = urllib.parse.urlencode(pairs)
            url = f"{url}{'&' if '?' in url else '?'}{encoded}"
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            method=method.upper(),
            headers=self._headers(json_body=body is not None),
        )
        context = ssl.create_default_context()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout, context=context) as response:
                raw = response.read()
                content_type = response.headers.get("content-type", "").lower()
                decoded = raw.decode("utf-8-sig")
                stripped = decoded.lstrip()
                if "json" in content_type or stripped.startswith(("{", "[")):
                    return json.loads(decoded)
                if (
                    "yaml" in content_type
                    or "yml" in content_type
                    or url.lower().endswith((".yaml", ".yml"))
                    or stripped.startswith(("openapi:", "swagger:"))
                ):
                    if yaml is None:
                        raise UmaMoeError(
                            "Le document OpenAPI est en YAML mais PyYAML n'est pas installé. "
                            "Réinstalle l'application complète ou lance: pip install pyyaml"
                        )
                    return yaml.safe_load(decoded)
                raise UmaMoeError(
                    f"Réponse ni JSON ni YAML depuis {url} ({content_type or 'type inconnu'})."
                )
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read(1200).decode("utf-8", errors="replace")
            except Exception:
                pass
            raise UmaMoeError(f"HTTP {exc.code} sur {url}: {detail[:500]}") from exc
        except urllib.error.URLError as exc:
            raise UmaMoeError(f"Connexion impossible à {url}: {exc.reason}") from exc
        except (TimeoutError, json.JSONDecodeError) as exc:
            raise UmaMoeError(f"Réponse API invalide depuis {url}: {exc}") from exc
        except Exception as exc:
            if isinstance(exc, UmaMoeError):
                raise
            raise UmaMoeError(f"Document API invalide depuis {url}: {exc}") from exc

    def _request_json(
        self,
        url: str,
        *,
        method: str = "GET",
        query: dict[str, Any] | None = None,
        body: Any = None,
    ) -> Any:
        payload = self._request_document(url, method=method, query=query, body=body)
        if not isinstance(payload, (dict, list)):
            raise UmaMoeError(f"Réponse JSON invalide depuis {url}.")
        return payload

    def discover_openapi(self) -> tuple[dict[str, Any], str]:
        if self._spec is not None and self._spec_url:
            return self._spec, self._spec_url
        candidates = []
        for url in (
            f"{self.origin}/api/docs/openapi.yaml",
            f"{self.origin}/api/docs/openapi.yml",
            f"{self.base_url}/docs/openapi.yaml",
            f"{self.base_url}/docs/openapi.yml",
            f"{self.base_url}/openapi.json",
            f"{self.base_url}/docs/openapi.json",
            f"{self.base_url}/docs-json",
            f"{self.base_url}-json",
            f"{self.origin}/api/openapi.json",
            f"{self.origin}/api/docs-json",
            f"{self.origin}/api-json",
            f"{self.origin}/openapi.json",
        ):
            if url not in candidates:
                candidates.append(url)
        errors: list[str] = []
        for url in candidates:
            try:
                payload = self._request_document(url)
                if isinstance(payload, dict) and (payload.get("openapi") or payload.get("swagger")) and isinstance(payload.get("paths"), dict):
                    self._spec = payload
                    self._spec_url = url
                    return payload, url
            except Exception as exc:
                errors.append(f"{url}: {exc}")
        raise UmaMoeError(
            "Impossible de découvrir le document OpenAPI de uma.moe. "
            "Utilise l'import d'une réponse JSON comme solution de secours.\n"
            + "\n".join(errors[-4:])
        )

    @staticmethod
    def _resolve_ref(spec: dict[str, Any], node: Any) -> Any:
        if not isinstance(node, dict) or "$ref" not in node:
            return node
        ref = str(node["$ref"])
        if not ref.startswith("#/"):
            return node
        current: Any = spec
        for part in ref[2:].split("/"):
            if not isinstance(current, dict):
                return node
            current = current.get(part.replace("~1", "/").replace("~0", "~"))
        return current if current is not None else node

    # NOTE (2026-07): no longer called by search(). Matching parameters by name
    # substring proved unsafe in practice (see search()'s docstring) — it silently
    # corrupted search_type and injected spurious min_*_count filters. Kept here
    # only in case a future uma.moe endpoint change requires re-deriving the
    # request shape; do not wire it back into search() without hand-verifying the
    # exact parameter list first, the way main_parent_pink_sparks was verified.
    def discover_search_operations(self) -> list[ApiOperation]:
        spec, _url = self.discover_openapi()
        result: list[ApiOperation] = []
        positive = {
            "inherit": 100,
            "legacy": 90,
            "parent": 85,
            "factor": 55,
            "spark": 55,
            "uql": 50,
            "database": 40,
            "search": 35,
            "record": 20,
        }
        negative = {
            "club": -100,
            "circle": -100,
            "activity": -100,
            "rankings": -80,
            "support card": -60,
            "timeline": -60,
        }
        for path, path_item in (spec.get("paths") or {}).items():
            if not isinstance(path_item, dict):
                continue
            for method in ("get", "post"):
                operation = path_item.get(method)
                if not isinstance(operation, dict):
                    continue
                haystack = " ".join(
                    str(value)
                    for value in (
                        path,
                        operation.get("operationId", ""),
                        operation.get("summary", ""),
                        operation.get("description", ""),
                        " ".join(operation.get("tags") or []),
                    )
                ).lower()
                score = sum(weight for token, weight in positive.items() if token in haystack)
                score += sum(weight for token, weight in negative.items() if token in haystack)
                if score > 0:
                    result.append(ApiOperation(method.upper(), str(path), score, operation, path_item))
        result.sort(key=lambda item: item.score, reverse=True)
        return result

    def _server_base(self, spec: dict[str, Any]) -> str:
        servers = spec.get("servers") or []
        if servers and isinstance(servers[0], dict) and servers[0].get("url"):
            url = str(servers[0]["url"])
            if url.startswith("/"):
                return self.origin + url.rstrip("/")
            return url.rstrip("/")
        return self.origin

    def _operation_request(
        self,
        op: ApiOperation,
        *,
        uql: str,
        limit: int,
        page: int = 0,
    ) -> tuple[str, dict[str, Any], Any]:
        spec, _ = self.discover_openapi()
        parameters: list[dict[str, Any]] = []
        for source in (op.path_item.get("parameters") or [], op.operation.get("parameters") or []):
            if isinstance(source, dict):
                parameters.append(source)
            elif isinstance(source, list):
                parameters.extend(item for item in source if isinstance(item, dict))
        query: dict[str, Any] = {}
        path_values: dict[str, Any] = {}

        def default_for_schema(schema: dict[str, Any]) -> Any:
            schema = self._resolve_ref(spec, schema) or {}
            for key in ("default", "example", "const"):
                if key in schema:
                    return schema[key]
            enum = schema.get("enum") or []
            return enum[0] if enum else None

        for parameter in parameters:
            parameter = self._resolve_ref(spec, parameter) or {}
            name = str(parameter.get("name") or "")
            location = str(parameter.get("in") or "query")
            schema = self._resolve_ref(spec, parameter.get("schema") or {}) or {}
            lname = name.lower()
            value: Any = None
            if lname in {"uql", "q", "query", "search", "filter", "where"} or any(token in lname for token in ("uql", "query", "search")):
                value = uql
            elif any(token in lname for token in ("limit", "count", "size", "take", "per_page", "pagesize")):
                value = limit
            elif any(token in lname for token in ("offset", "skip")):
                value = page * limit
            elif lname in {"page", "page_number", "pagenumber"}:
                value = page
            else:
                value = default_for_schema(schema)
            if value is None and parameter.get("required"):
                # Do not invent IDs. This operation is probably not the general search endpoint.
                raise UmaMoeError(f"Paramètre requis non résolu pour {op.method} {op.path}: {name}")
            if value is not None:
                (path_values if location == "path" else query)[name] = value

        url_path = op.path
        for name, value in path_values.items():
            url_path = url_path.replace("{" + name + "}", urllib.parse.quote(str(value), safe=""))
        url = self._server_base(spec) + (url_path if url_path.startswith("/") else "/" + url_path)

        body = None
        if op.method == "POST":
            request_body = op.operation.get("requestBody") or {}
            content = request_body.get("content") or {}
            media = content.get("application/json") or next(iter(content.values()), {})
            schema = self._resolve_ref(spec, media.get("schema") or {}) or {}
            if schema.get("type") == "string":
                body = uql
            else:
                properties = schema.get("properties") or {}
                body = {}
                for name, raw_schema in properties.items():
                    raw_schema = self._resolve_ref(spec, raw_schema) or {}
                    lname = str(name).lower()
                    value = None
                    if lname in {"uql", "q", "query", "search", "filter", "where"} or any(token in lname for token in ("uql", "query", "search")):
                        value = uql
                    elif any(token in lname for token in ("limit", "count", "size", "take", "per_page", "pagesize")):
                        value = limit
                    elif any(token in lname for token in ("offset", "skip")):
                        value = page * limit
                    elif lname in {"page", "page_number", "pagenumber"}:
                        value = page
                    elif "exclude" in lname and raw_schema.get("type") == "boolean":
                        value = False
                    else:
                        value = default_for_schema(raw_schema)
                    if value is not None:
                        body[name] = value
                required = set(schema.get("required") or [])
                unresolved = [name for name in required if name not in body]
                if unresolved:
                    raise UmaMoeError(
                        f"Corps requis non résolu pour {op.method} {op.path}: {', '.join(unresolved)}"
                    )
        return url, query, body

    @staticmethod
    def _contains_candidate_records(payload: Any) -> bool:
        tokens = ("factor", "spark", "inherit", "card_id", "chara_id", "character_id", "trained_chara")
        seen = 0

        def walk(value: Any, depth: int = 0) -> bool:
            nonlocal seen
            if depth > 7 or seen > 4000:
                return False
            seen += 1
            if isinstance(value, dict):
                keys = " ".join(str(key).lower() for key in value)
                if sum(1 for token in tokens if token in keys) >= 2:
                    return True
                return any(walk(item, depth + 1) for item in value.values())
            if isinstance(value, list):
                return any(walk(item, depth + 1) for item in value[:100])
            return False

        return walk(payload)

    def search(
        self, *, filters: dict[str, Any] | None = None, limit: int = 100, page: int = 0
    ) -> tuple[Any, dict[str, Any]]:
        """Call ``GET /api/v3/search`` directly with documented parameters.

        Earlier versions tried to discover the search operation from the OpenAPI
        document and guess which parameter should carry a free-text query, using
        substring matching on parameter names (``"uql"``, ``"query"``, ``"search"``
        tokens). That heuristic was confirmed broken in practice on 2026-07:
        - it matched ``search_type`` (an enum) because it contains "search" and
          stuffed the raw query text into it;
        - it matched any parameter containing "limit"/"count" (e.g.
          ``min_win_count``, ``min_white_count``, ``min_limit_break``) and set them
          to the page size, injecting nonsensical hard filters into every request.
        There is also no free-text query parameter on this endpoint at all — the
        site's own UQL editor targets a different, session-authenticated, browser-
        gated endpoint (``/search/query``) not meant for scripted/API-key access.

        The only reliable path is calling ``/api/v3/search`` directly with its
        documented parameter names (e.g. ``main_parent_pink_sparks``), built from
        game ``factor_id`` values resolved against ``master.mdb`` by the caller.
        Array-valued parameters must be a single comma-joined value (confirmed
        empirically; repeated keys silently return zero results).
        """
        limit = max(1, min(int(limit), 100))
        page = max(0, int(page))
        url = f"{self.origin}/api/v3/search"
        query: dict[str, Any] = {
            "search_type": "inheritance",
            "page": page,
            "limit": limit,
            "sort_order": "asc",
        }
        for key, value in (filters or {}).items():
            if value is not None:
                query[key] = value
        try:
            payload = self._request_json(url, query=query)
        except UmaMoeError as exc:
            raise UmaMoeError(
                f"Échec de GET /api/v3/search : {exc}\n"
                "Utilise le bouton d'import JSON si le problème persiste."
            ) from exc
        if not self._contains_candidate_records(payload):
            raise UmaMoeError(
                f"Réponse /api/v3/search sans records d'héritage détectables (query={sorted(query)})."
            )
        return payload, {
            "method": "GET",
            "path": "/api/v3/search",
            "url": url,
            "discovery_mode": "hardcoded_v3_search",
            "query_keys": sorted(query),
            "body_keys": None,
            "page": page,
            "limit": limit,
        }

    @staticmethod
    def _record_identity(record: Any) -> str:
        if not isinstance(record, dict):
            return json.dumps(record, ensure_ascii=False, sort_keys=True)
        inheritance = record.get("inheritance") if isinstance(record.get("inheritance"), dict) else record
        inheritance_id = inheritance.get("inheritance_id") if isinstance(inheritance, dict) else None
        if inheritance_id not in (None, ""):
            return f"inheritance:{inheritance_id}"
        account_id = record.get("account_id") or (inheritance.get("account_id") if isinstance(inheritance, dict) else None)
        main_parent = inheritance.get("main_parent_id") if isinstance(inheritance, dict) else None
        return f"fallback:{account_id}:{main_parent}:{hashlib.sha1(json.dumps(record, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()[:12]}"

    def search_many(
        self,
        *,
        filters: dict[str, Any] | None = None,
        desired_candidates: int = 250,
        page_size: int = 100,
        logger: Callable[[str], None] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        logger = logger or (lambda _message: None)
        desired_candidates = max(1, min(int(desired_candidates), MAX_FETCH_CANDIDATES))
        page_size = max(1, min(int(page_size), 100))
        merged_items: list[dict[str, Any]] = []
        seen: set[str] = set()
        first_payload: dict[str, Any] | None = None
        first_operation: dict[str, Any] | None = None
        pages_fetched: list[int] = []
        page = 0
        total_pages: int | None = None
        # Bound both the retained candidates and the amount requested from the API.
        # At the global cap this is at most 20 pages of 100 parents.
        max_pages = max(1, math.ceil(desired_candidates / page_size))

        while len(merged_items) < desired_candidates and len(pages_fetched) < max_pages:
            logger(f"uma.moe : page {page + 1}, objectif {desired_candidates} candidats…")
            payload, operation = self.search(filters=filters, limit=page_size, page=page)
            if first_operation is None:
                first_operation = dict(operation)
            if isinstance(payload, dict):
                if first_payload is None:
                    first_payload = dict(payload)
                items = payload.get("items")
                if not isinstance(items, list):
                    items = _extract_record_list(payload)
                try:
                    total_pages = int(payload.get("total_pages")) if payload.get("total_pages") is not None else total_pages
                except (TypeError, ValueError):
                    pass
            elif isinstance(payload, list):
                items = payload
            else:
                items = []

            pages_fetched.append(page)
            added = 0
            for item in items:
                if not isinstance(item, dict):
                    continue
                identity = self._record_identity(item)
                if identity in seen:
                    continue
                seen.add(identity)
                merged_items.append(item)
                added += 1
                if len(merged_items) >= desired_candidates:
                    break
            logger(f"uma.moe : page {page + 1} reçue, {added} nouveaux candidats, {len(merged_items)} cumulés.")

            if not items or added == 0 or len(items) < page_size:
                break
            page += 1
            if total_pages is not None and page >= total_pages:
                break

        merged = first_payload or {}
        merged["items"] = merged_items
        merged["page"] = 0
        merged["limit"] = page_size
        merged["pages_fetched"] = pages_fetched
        merged["requested_candidates"] = desired_candidates
        merged["unique_items"] = len(merged_items)
        if total_pages is not None:
            merged["total_pages"] = total_pages
        operation = first_operation or {"method": "GET", "path": "/api/v3/search"}
        operation.update({
            "pages_fetched": pages_fetched,
            "page_count": len(pages_fetched),
            "requested_candidates": desired_candidates,
            "received_candidates": len(merged_items),
            "page_size": page_size,
            "max_pages": max_pages,
            "filters": filters or {},
        })
        return merged, operation


def _normalize_course_condition_sets(
    course_conditions: dict[str, int | list[int] | tuple[int, ...] | set[int] | None] | None,
) -> dict[str, set[int]]:
    normalized: dict[str, set[int]] = {}
    for key, raw in (course_conditions or {}).items():
        if raw is None:
            continue
        values = raw if isinstance(raw, (list, tuple, set)) else [raw]
        selected: set[int] = set()
        for value in values:
            try:
                selected.add(int(value))
            except (TypeError, ValueError):
                continue
        if selected:
            normalized[str(key)] = selected
    return normalized


def _uql_list(predicate: str, names: list[str], directive: str) -> str:
    body = ",\n  ".join(names + [directive])
    return f"{predicate} (\n  {body}\n)"


def generate_auto_uql(
    manual_weights_path: str | Path,
    skill_catalog_path: str | Path,
    *,
    surface: str,
    distance: str,
    style: str,
    course_weights_path: str | Path | None = None,
    course_key: str | None = None,
    course_conditions: dict[str, int | list[int] | tuple[int, ...] | set[int] | None] | None = None,
    scoring_config_path: str | Path | None = None,
    max_optional_skills: int = 24,
    max_lineage_skills: int = 12,
    options: dict[str, Any] | None = None,
    master_path: str | Path | None = None,
) -> tuple[str, dict[str, Any]]:
    """Build a broad UQL with optional user-selected hard constraints.

    White-skill clauses are primarily sorting/prioritisation helpers. Pink and blue
    factors remain open by default; the user may explicitly require a factor on the
    online main parent (the distant GP candidate), for example ``Main Dirt >= 1``.
    """
    options = dict(options or {})
    use_optional_whites = bool(options.get("prefer_profile_whites", True))
    use_lineage_whites = bool(options.get("prefer_lineage_whites", True))
    min_pink_stars = max(1, min(int(options.get("pink_min_stars", 1) or 1), 3))

    weights_payload = _read_json(Path(manual_weights_path))
    skill_catalog = _read_json(Path(skill_catalog_path))
    course_payload = _read_json(Path(course_weights_path)) if course_weights_path and Path(course_weights_path).is_file() else None
    config = _read_json(Path(scoring_config_path)) if scoring_config_path and Path(scoring_config_path).is_file() else {}
    normalized_conditions = _normalize_course_condition_sets(course_conditions)
    course_config = config.get("course_conditions") or {}
    active_green_floor = float(course_config.get("active_green_floor", 0.12))
    green_floors = {str(key): float(value) for key, value in (course_config.get("floors") or {}).items()}
    green_modes = {str(key): str(value) for key, value in (course_config.get("modes") or {}).items()}
    lookup, source_label, diagnostics = _selected_weight_lookup(
        weights_payload,
        course_payload,
        skill_catalog,
        surface,
        distance,
        style,
        course_key,
        normalized_conditions,
        active_green_floor,
        green_floors,
        green_modes,
    )

    static_rules = _compile_static_condition_rules(skill_catalog)
    ranked: list[dict[str, Any]] = []
    for key, entry in (weights_payload.get("skills") or {}).items():
        name = str(entry.get("spark_name") or "").strip()
        if not name:
            continue
        weight = float(lookup(str(key)))
        if weight <= 0.0:
            continue
        static_state = "not_static"
        if key in static_rules:
            static_state = _static_condition_state(static_rules[key], normalized_conditions)
        ranked.append({
            "catalog_key": str(key),
            "name": name,
            "weight": round(weight, 6),
            "static_state": static_state,
        })
    ranked.sort(key=lambda row: (float(row["weight"]), row["name"]), reverse=True)

    optional_rows = [row for row in ranked if float(row["weight"]) >= 0.32]
    matched_greens = [row for row in ranked if row["static_state"] == "matched"]
    seen: set[str] = set()
    optional: list[dict[str, Any]] = []
    reserved_greens = matched_greens[: min(6, max_optional_skills)]
    regular_limit = max(0, max_optional_skills - len(reserved_greens))
    for row in optional_rows[:regular_limit] + reserved_greens:
        if row["name"] in seen:
            continue
        seen.add(str(row["name"]))
        optional.append(row)
    if len(optional) < min(12, max_optional_skills):
        for row in ranked:
            if row["name"] in seen:
                continue
            seen.add(str(row["name"]))
            optional.append(row)
            if len(optional) >= min(12, max_optional_skills):
                break

    lineage: list[dict[str, Any]] = []
    optional_names = {str(row["name"]) for row in optional}
    for row in ranked:
        if str(row["name"]) not in optional_names or float(row["weight"]) < 0.62:
            continue
        lineage.append(row)
        if len(lineage) >= max_lineage_skills:
            break
    if len(lineage) < min(6, len(optional)):
        lineage = optional[: min(max_lineage_skills, max(6, len(lineage)))]

    clauses: list[str] = []
    soft_clauses: list[str] = []
    if use_optional_whites and optional:
        soft_clauses.append(_uql_list("optional white in", [str(row["name"]) for row in optional], "priority = 0"))
    if use_lineage_whites and lineage:
        soft_clauses.append(_uql_list("lineage white in", [str(row["name"]) for row in lineage], "group = 1"))
    clauses.extend(soft_clauses)

    hard_filters: list[dict[str, Any]] = []
    requested_factor_names: list[str] = []
    if options.get("require_main_dirt"):
        requested_factor_names.append("Dirt")
    if options.get("require_main_surface"):
        requested_factor_names.append(SURFACE_FACTOR_NAMES[surface])
    if options.get("require_main_distance"):
        requested_factor_names.append(DISTANCE_FACTOR_NAMES[distance])
    if options.get("require_main_style"):
        requested_factor_names.append(STYLE_FACTOR_NAMES[style])
    # Preserve order while avoiding duplicate clauses (e.g. Dirt + target surface Dirt).
    deduped_names: list[str] = []
    for name in requested_factor_names:
        if name not in deduped_names:
            deduped_names.append(name)
    for name in deduped_names:
        clause = f"Main {name} >= {min_pink_stars}"
        clauses.append(clause)
        hard_filters.append({"slot": "main", "factor": name, "minimum_stars": min_pink_stars, "uql": clause})

    # An empty UQL is valid and intentionally broad. This text is kept for
    # display/audit (uma_moe_generated_uql.txt) and for manual copy-paste into
    # uma.moe's own editor — it is NOT sent to /api/v3/search, which has no
    # free-text query parameter (confirmed 2026-07). The actual live search uses
    # search_filters below.
    uql = " and\n".join(clauses)
    simple_parts = list(soft_clauses[:1]) + [item["uql"] for item in hard_filters]
    simple_uql = " and\n".join(simple_parts)
    main_parent_pink_sparks = (
        resolve_main_pink_factor_ids(master_path, hard_filters) if master_path and hard_filters else []
    )
    optional_main_white_factors = (
        resolve_white_factor_group_ids(master_path, [str(row["name"]) for row in optional])
        if master_path and use_optional_whites and optional
        else []
    )
    optional_white_sparks = (
        resolve_white_factor_group_ids(master_path, [str(row["name"]) for row in lineage])
        if master_path and use_lineage_whites and lineage
        else []
    )
    return uql, {
        "generator_version": 3,
        "profile": {"surface": surface, "distance": distance, "style": style},
        "weight_source": source_label,
        "course_key": course_key,
        "course_conditions": {key: sorted(values) for key, values in normalized_conditions.items()},
        "options": options,
        "optional_skills": optional if use_optional_whites else [],
        "lineage_skills": lineage if use_lineage_whites else [],
        "hard_filters": hard_filters,
        "simple_fallback_uql": simple_uql,
        "weight_diagnostics": diagnostics,
        "search_filters": {
            "main_parent_pink_sparks": main_parent_pink_sparks,
            "optional_main_white_factors": optional_main_white_factors,
            "optional_white_sparks": optional_white_sparks,
        },
        "policy": {
            "blue_filter": None,
            "pink_filter": hard_filters or None,
            "reason": "Keep the API pool broad unless the user explicitly checks a main-parent factor constraint.",
        },
    }

MAIN_RED_FACTOR_NAMES = tuple(
    dict.fromkeys(
        list(SURFACE_FACTOR_NAMES.values())
        + list(DISTANCE_FACTOR_NAMES.values())
        + list(STYLE_FACTOR_NAMES.values())
    )
)


def resolve_white_factor_group_ids(
    master_path: str | Path,
    skill_names: Iterable[str],
) -> list[int]:
    """Resolve white skill names to the group id uma.moe's soft filters expect.

    CORRECTED (2026-07): an earlier version used the game's own
    ``succession_factor.factor_group_id`` column, on the unverified assumption
    that it grouped a skill's three star variants together. That assumption
    was never checked against real data and turned out to be wrong — it
    caused every optional/lineage white search to silently resolve to IDs
    that match no real skill, yielding zero total results.

    What is actually confirmed (captured directly from the site's own
    compiled query, cross-checked against ``factor_id`` values read from
    ``master.mdb``): the group id is the per-star ``factor_id`` with its
    trailing star digit stripped — e.g. Head-On star 1/2/3 =
    2019001/2019002/2019003, all sharing group 201900 = 2019001 // 10.
    """
    names = {str(name) for name in skill_names if name}
    if not names:
        return []
    resolver = MasterResolver(Path(master_path))
    try:
        ids: set[int] = set()
        for factor in resolver.factors.values():
            if factor.get("type") == "white_skill" and str(factor.get("name") or "") in names:
                ids.add(int(factor["factor_id"]) // 10)
    finally:
        resolver.close()
    return sorted(ids)


def resolve_main_pink_factor_ids(
    master_path: str | Path,
    hard_filters: Iterable[dict[str, Any]],
) -> list[int]:
    """Resolve ``Main <name> >= N`` hard filters to game ``factor_id`` values.

    Confirmed empirically against uma.moe (2026-07): ``/api/v3/search``'s
    ``main_parent_pink_sparks`` parameter accepts the game's own
    ``succession_factor.factor_id`` directly (e.g. Dirt 1/2/3-star =
    1201/1202/1203), matched with OR semantics. ">= N stars" is therefore
    expressed as the set of factor_id values covering stars N..3.
    """
    hard_filters = list(hard_filters)
    if not hard_filters:
        return []
    resolver = MasterResolver(Path(master_path))
    try:
        ids: set[int] = set()
        for item in hard_filters:
            name = str(item.get("factor") or "")
            try:
                minimum = max(1, min(int(item.get("minimum_stars") or 1), 3))
            except (TypeError, ValueError):
                minimum = 1
            for factor in resolver.factors.values():
                if str(factor.get("name") or "") == name and int(factor.get("stars") or 0) >= minimum:
                    ids.add(int(factor["factor_id"]))
    finally:
        resolver.close()
    return sorted(ids)


def extract_main_factor_filters(uql: str) -> list[dict[str, Any]]:
    """Extract simple strict ``Main <pink> >= N`` predicates for local validation.

    uma.moe may evolve its HTTP parameter names independently from the UQL syntax.
    Re-applying checked hard constraints after normalization prevents an ignored API
    parameter from silently admitting candidates that violate the requested factor.
    """
    filters: list[dict[str, Any]] = []
    for factor_name in MAIN_RED_FACTOR_NAMES:
        pattern = re.compile(
            rf"(?im)\bMain\s+{re.escape(factor_name)}\s*>=\s*([123])\b"
        )
        match = pattern.search(uql or "")
        if not match:
            continue
        filters.append({
            "slot": "main",
            "factor": factor_name,
            "minimum_stars": int(match.group(1)),
            "source": "uql",
        })
    return filters


def _member_matches_main_factor_filters(
    member: dict[str, Any],
    filters: Iterable[dict[str, Any]],
) -> bool:
    red_factors = (
        ((member.get("factors") or {}).get("by_type") or {}).get("red_aptitude")
        or []
    )
    best_by_name: dict[str, int] = {}
    for factor in red_factors:
        if not isinstance(factor, dict):
            continue
        name = str(factor.get("name") or "")
        try:
            stars = int(factor.get("stars") or 0)
        except (TypeError, ValueError):
            stars = 0
        best_by_name[name] = max(best_by_name.get(name, 0), stars)
    for item in filters:
        name = str(item.get("factor") or "")
        try:
            minimum = int(item.get("minimum_stars") or 1)
        except (TypeError, ValueError):
            minimum = 1
        if best_by_name.get(name, 0) < minimum:
            return False
    return True


def _normalize_main_factor_filters(
    explicit: Iterable[dict[str, Any]] | None,
    uql: str,
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in list(explicit or []) + extract_main_factor_filters(uql):
        if not isinstance(item, dict):
            continue
        if str(item.get("slot") or "main").lower() != "main":
            continue
        name = str(item.get("factor") or "").strip()
        if name not in MAIN_RED_FACTOR_NAMES:
            continue
        try:
            minimum = max(1, min(int(item.get("minimum_stars") or 1), 3))
        except (TypeError, ValueError):
            minimum = 1
        previous = merged.get(name)
        if previous is None or minimum > int(previous["minimum_stars"]):
            merged[name] = {
                "slot": "main",
                "factor": name,
                "minimum_stars": minimum,
                "source": item.get("source") or "generated_uql",
            }
    return list(merged.values())


def _normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _first_value(mapping: dict[str, Any], names: Iterable[str]) -> Any:
    lowered = {str(key).lower(): value for key, value in mapping.items()}
    for name in names:
        if name.lower() in lowered and lowered[name.lower()] not in (None, ""):
            return lowered[name.lower()]
    return None


def _walk_dicts(value: Any, depth: int = 0) -> Iterable[dict[str, Any]]:
    if depth > 8:
        return
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child, depth + 1)


def _candidate_object_score(obj: dict[str, Any]) -> int:
    keys = {str(key).lower() for key in obj}
    joined = " ".join(keys)
    score = 0
    if any(key in keys for key in ("card_id", "chara_card_id", "character_card_id", "trained_chara_card_id")):
        score += 50
    if any(token in joined for token in ("factor", "spark", "inherit")):
        score += 40
    if any(token in joined for token in ("g1", "saddle", "race")):
        score += 15
    if any(token in joined for token in ("trainer", "viewer", "friend")):
        score += 10
    if any(token in joined for token in ("support_card", "club", "circle")):
        score -= 30
    return score


def _extract_record_list(payload: Any) -> list[dict[str, Any]]:
    candidates: list[tuple[int, list[dict[str, Any]]]] = []

    def walk(value: Any, depth: int = 0) -> None:
        if depth > 7:
            return
        if isinstance(value, list):
            dicts = [item for item in value if isinstance(item, dict)]
            if dicts:
                sample_score = sum(max(0, _candidate_object_score(item)) for item in dicts[:20])
                candidates.append((sample_score + min(len(dicts), 200), dicts))
            for item in value[:50]:
                walk(item, depth + 1)
        elif isinstance(value, dict):
            for key, child in value.items():
                bonus = 120 if str(key).lower() in {"results", "items", "records", "data", "parents", "inheritances", "rows"} else 0
                if isinstance(child, list):
                    dicts = [item for item in child if isinstance(item, dict)]
                    if dicts:
                        score = bonus + sum(max(0, _candidate_object_score(item)) for item in dicts[:20]) + min(len(dicts), 200)
                        candidates.append((score, dicts))
                walk(child, depth + 1)

    walk(payload)
    if not candidates and isinstance(payload, dict):
        return [payload]
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1] if candidates else []


class OnlineRecordNormalizer:
    def __init__(self, master_path: str | Path):
        self.master_path = Path(master_path)
        self.resolver = MasterResolver(self.master_path)
        self.factor_by_name_stars: dict[tuple[str, int], dict[str, Any]] = {}
        for factor in self.resolver.factors.values():
            stars = int(factor.get("stars") or 0)
            self.factor_by_name_stars[(_normalize_name(str(factor.get("name") or "")), stars)] = factor
        self.card_by_chara: dict[int, list[int]] = {}
        for card_id, card in self.resolver.cards.items():
            self.card_by_chara.setdefault(int(card["chara_id"]), []).append(card_id)

    def close(self) -> None:
        self.resolver.close()

    def _resolve_card_id(self, obj: dict[str, Any]) -> int | None:
        raw = _first_value(
            obj,
            (
                "card_id", "chara_card_id", "character_card_id", "trained_chara_card_id",
                "representative_card_id", "parent_card_id", "uma_card_id", "main_parent_id",
            ),
        )
        try:
            card_id = int(raw)
            if card_id in self.resolver.cards:
                return card_id
        except (TypeError, ValueError):
            pass
        chara_raw = _first_value(obj, ("chara_id", "character_id", "uma_id", "trainee_id"))
        try:
            chara_id = int(chara_raw)
            cards = self.card_by_chara.get(chara_id) or []
            return cards[0] if cards else None
        except (TypeError, ValueError):
            return None

    def _best_candidate_obj(self, record: dict[str, Any]) -> dict[str, Any]:
        objects = list(_walk_dicts(record))
        objects.sort(key=_candidate_object_score, reverse=True)
        return next((obj for obj in objects if self._resolve_card_id(obj) is not None), record)

    def _factor_arrays(self, obj: dict[str, Any]) -> list[Any]:
        arrays: list[Any] = []
        for node in _walk_dicts(obj):
            for key, value in node.items():
                lower = str(key).lower()
                if isinstance(value, list) and any(token in lower for token in ("factor", "spark", "inheritance")):
                    arrays.append(value)
        return arrays

    def _resolve_factors(self, obj: dict[str, Any]) -> dict[str, Any]:
        factor_ids: set[int] = set()
        resolved_direct: list[dict[str, Any]] = []
        for array in self._factor_arrays(obj):
            for item in array:
                if not isinstance(item, dict):
                    continue
                raw_id = _first_value(item, ("factor_id", "spark_id", "inheritance_factor_id"))
                try:
                    factor_id = int(raw_id)
                except (TypeError, ValueError):
                    factor_id = 0
                if factor_id and factor_id in self.resolver.factors:
                    factor_ids.add(factor_id)
                    continue
                name = _first_value(item, ("name", "factor_name", "spark_name", "label"))
                stars_raw = _first_value(item, ("stars", "star", "rarity", "level", "num"))
                try:
                    stars = int(stars_raw)
                except (TypeError, ValueError):
                    stars = 0
                if name and stars:
                    factor = self.factor_by_name_stars.get((_normalize_name(str(name)), stars))
                    if factor:
                        factor_ids.add(int(factor["factor_id"]))
                    else:
                        factor_type = str(_first_value(item, ("type", "factor_type", "spark_type")) or "other")
                        resolved_direct.append({
                            "factor_id": None,
                            "name": str(name),
                            "stars": stars,
                            "stars_text": "★" * stars,
                            "type": factor_type,
                            "description": "",
                        })
        resolved = [dict(self.resolver.factors[factor_id]) for factor_id in sorted(factor_ids)] + resolved_direct
        # Remove duplicates by (name, stars, type).
        unique: dict[tuple[str, int, str], dict[str, Any]] = {}
        for factor in resolved:
            key = (str(factor.get("name") or ""), int(factor.get("stars") or 0), str(factor.get("type") or "other"))
            unique[key] = factor
        return grouped_factors(sorted(unique.values(), key=lambda factor: (str(factor.get("type")), str(factor.get("name")), int(factor.get("stars") or 0))))

    def _g1(self, obj: dict[str, Any]) -> dict[str, Any]:
        names: set[str] = set()
        saddle_ids: set[int] = set()
        for node in _walk_dicts(obj):
            for key, value in node.items():
                lower = str(key).lower()
                if lower in {"win_saddle_id_array", "g1_saddle_ids", "saddle_ids"} and isinstance(value, list):
                    for raw in value:
                        try:
                            saddle_ids.add(int(raw))
                        except (TypeError, ValueError):
                            pass
                if any(token in lower for token in ("g1", "grade1", "grade_1")):
                    if isinstance(value, list):
                        for item in value:
                            if isinstance(item, str):
                                names.add(item)
                            elif isinstance(item, dict):
                                name = _first_value(item, ("name", "race_name", "label", "title"))
                                if name:
                                    names.add(str(name))
        resolved = self.resolver.resolve_g1_saddles(sorted(saddle_ids))
        names.update(resolved.get("names") or [])
        return {"count": len(names), "names": sorted(names), "details": resolved.get("details") or []}

    def _metadata(self, record: dict[str, Any], obj: dict[str, Any]) -> dict[str, Any]:
        merged = {**record, **obj}
        trainer_id = _first_value(merged, ("trainer_id", "viewer_id", "user_id", "owner_viewer_id", "profile_id"))
        friend_code = _first_value(merged, ("friend_code", "trainer_code", "friend_id", "viewer_id", "trainer_id"))
        name = _first_value(merged, ("trainer_name", "user_name", "owner_name", "display_name"))
        updated = _first_value(merged, ("updated_at", "last_updated", "updated", "scraped_at", "modified_at"))
        follow = _first_value(merged, ("follow_limit", "is_follow_full", "follow_full", "available", "is_available"))
        profile_url = _first_value(merged, ("profile_url", "url", "source_url"))
        return {
            "trainer_id": trainer_id,
            "friend_code": str(friend_code) if friend_code is not None else None,
            "trainer_name": name,
            "updated_at": updated,
            "follow_status": follow,
            "profile_url": profile_url,
        }

    def _parent_candidates(self, obj: dict[str, Any]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        preferred_keys = {
            "parent_1", "parent1", "parent_2", "parent2", "parents", "lineage_parents",
            "succession_chara_array", "grandparents", "inheritance_parents",
        }
        for node in _walk_dicts(obj):
            for key, value in node.items():
                if str(key).lower() not in preferred_keys:
                    continue
                if isinstance(value, dict):
                    result.append(value)
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict):
                            position = _first_value(item, ("position_id", "position", "slot"))
                            if position in (11, 12, 21, 22):
                                continue
                            result.append(item)
        # Keep only two usable direct parents.
        usable = [parent for parent in result if self._resolve_card_id(parent) is not None]
        return usable[:2]

    def _factors_from_ids(self, factor_ids: Iterable[Any]) -> dict[str, Any]:
        resolved: list[dict[str, Any]] = []
        seen: set[int] = set()
        for raw in factor_ids:
            try:
                factor_id = int(raw)
            except (TypeError, ValueError):
                continue
            if factor_id <= 0 or factor_id in seen:
                continue
            factor = self.resolver.factors.get(factor_id)
            if factor:
                resolved.append(dict(factor))
                seen.add(factor_id)
        return grouped_factors(sorted(resolved, key=lambda factor: (str(factor.get("type")), str(factor.get("name")), int(factor.get("stars") or 0))))

    def _uma_moe_member(
        self,
        inheritance: dict[str, Any],
        prefix: str,
        card_key: str,
        *,
        role: str,
        metadata: dict[str, Any],
        rank_score: int | None = None,
    ) -> dict[str, Any] | None:
        try:
            card_id = int(inheritance.get(card_key) or 0)
        except (TypeError, ValueError):
            card_id = 0
        if card_id not in self.resolver.cards:
            return None
        card = self.resolver.resolve_card(card_id)
        factor_ids: list[Any] = []
        for suffix in ("blue_factors", "pink_factors", "green_factors"):
            raw = inheritance.get(f"{prefix}_{suffix}")
            if raw not in (None, 0, ""):
                factor_ids.append(raw)
        white = inheritance.get(f"{prefix}_white_factors") or []
        if isinstance(white, list):
            factor_ids.extend(white)
        saddles = inheritance.get(f"{prefix}_win_saddles") or []
        g1 = self.resolver.resolve_g1_saddles(saddles if isinstance(saddles, list) else [])
        return {
            "trained_chara_id": f"uma.moe:{metadata.get('friend_code') or metadata.get('trainer_id') or 'unknown'}:{inheritance.get('inheritance_id') or card_id}:{prefix}",
            "rank_score": rank_score,
            "rank": inheritance.get("parent_rarity") if prefix == "main" else None,
            **card,
            "factors": self._factors_from_ids(factor_ids),
            "g1_wins": g1,
            "when_used_as_parent": {"grandparent_1": None, "grandparent_2": None},
            "online": metadata,
            "source_role": role,
        }

    def _normalize_uma_moe_record(self, record: dict[str, Any]) -> dict[str, Any] | None:
        inheritance = record.get("inheritance")
        if not isinstance(inheritance, dict):
            return None
        if "main_parent_id" not in inheritance:
            return None
        metadata = {
            "trainer_id": record.get("account_id"),
            "friend_code": str(record.get("account_id")) if record.get("account_id") is not None else None,
            "trainer_name": record.get("trainer_name"),
            "updated_at": record.get("last_updated"),
            "follow_status": None,
            "profile_url": None,
            "inheritance_id": inheritance.get("inheritance_id"),
            "follower_num": record.get("follower_num"),
            "borrow_view_count": record.get("borrow_view_count"),
            "borrow_copy_count": record.get("borrow_copy_count"),
            "api_affinity_score": inheritance.get("affinity_score"),
        }
        try:
            rank_score = int(inheritance.get("parent_rank")) if inheritance.get("parent_rank") is not None else None
        except (TypeError, ValueError):
            rank_score = None
        main = self._uma_moe_member(inheritance, "main", "main_parent_id", role="online_candidate", metadata=metadata, rank_score=rank_score)
        if main is None:
            return None
        left = self._uma_moe_member(inheritance, "left", "parent_left_id", role="online_candidate_parent_1", metadata=metadata)
        right = self._uma_moe_member(inheritance, "right", "parent_right_id", role="online_candidate_parent_2", metadata=metadata)
        main["when_used_as_parent"]["grandparent_1"] = left
        main["when_used_as_parent"]["grandparent_2"] = right
        return main

    def normalize_member(self, obj: dict[str, Any], *, role: str, online_metadata: dict[str, Any] | None = None) -> dict[str, Any] | None:
        card_id = self._resolve_card_id(obj)
        if card_id is None:
            return None
        card = self.resolver.resolve_card(card_id)
        rank_score = _first_value(obj, ("rank_score", "score", "evaluation_score", "rating"))
        try:
            rank_score = int(rank_score) if rank_score is not None else None
        except (TypeError, ValueError):
            rank_score = None
        member = {
            "trained_chara_id": f"uma.moe:{online_metadata.get('friend_code') if online_metadata else card_id}:{card_id}",
            "rank_score": rank_score,
            "rank": _first_value(obj, ("rank", "evaluation_rank", "grade")),
            **card,
            "factors": self._resolve_factors(obj),
            "g1_wins": self._g1(obj),
            "when_used_as_parent": {"grandparent_1": None, "grandparent_2": None},
            "online": online_metadata or {},
            "source_role": role,
        }
        parents = self._parent_candidates(obj)
        if parents:
            member["when_used_as_parent"]["grandparent_1"] = self.normalize_member(parents[0], role=f"{role}_parent_1", online_metadata=online_metadata)
        if len(parents) > 1:
            member["when_used_as_parent"]["grandparent_2"] = self.normalize_member(parents[1], role=f"{role}_parent_2", online_metadata=online_metadata)
        return member

    def normalize_records(self, payload: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        records = _extract_record_list(payload)
        normalized: list[dict[str, Any]] = []
        skipped = 0
        for record in records:
            member = self._normalize_uma_moe_record(record)
            if member is None:
                candidate_obj = self._best_candidate_obj(record)
                metadata = self._metadata(record, candidate_obj)
                member = self.normalize_member(candidate_obj, role="online_candidate", online_metadata=metadata)
            if member is None or not member.get("factors", {}).get("all"):
                skipped += 1
                continue
            normalized.append(member)
        # Deduplicate by friend code + card + factor signature.
        unique: dict[str, dict[str, Any]] = {}
        for candidate in normalized:
            signature = [
                candidate.get("online", {}).get("friend_code"),
                candidate.get("card_id"),
                sorted((factor.get("name"), factor.get("stars")) for factor in candidate.get("factors", {}).get("all", [])),
            ]
            key = hashlib.sha256(json.dumps(signature, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
            unique[key] = candidate
        return list(unique.values()), {
            "record_list_count": len(records),
            "normalized_count": len(unique),
            "skipped_count": skipped,
        }


def _full_production_affinity(
    resolver: AffinityResolver,
    target_parent_chara: int,
    gp1: dict[str, Any],
    gp2: dict[str, Any],
    g1_bonus_value: int,
) -> dict[str, Any]:
    def branch(gp: dict[str, Any], label: str) -> dict[str, Any]:
        gp_chara = int(gp.get("chara_id") or 0)
        lineage = gp.get("when_used_as_parent") or {}
        p1 = lineage.get("grandparent_1")
        p2 = lineage.get("grandparent_2")
        target_pair = resolver.pair(target_parent_chara, gp_chara)
        triple_1 = resolver.triple(target_parent_chara, gp_chara, int(p1.get("chara_id") or 0)) if p1 else 0
        triple_2 = resolver.triple(target_parent_chara, gp_chara, int(p2.get("chara_id") or 0)) if p2 else 0
        gp_g1 = _member_g1(gp)
        common_1 = sorted(gp_g1 & _member_g1(p1))
        common_2 = sorted(gp_g1 & _member_g1(p2))
        bonus_1 = g1_bonus_value * len(common_1)
        bonus_2 = g1_bonus_value * len(common_2)
        return {
            "label": label,
            "target_gp_pair": target_pair,
            "target_gp_parent_1_triple": triple_1,
            "target_gp_parent_2_triple": triple_2,
            "base": target_pair + triple_1 + triple_2,
            "parent_1_common_g1": common_1,
            "parent_2_common_g1": common_2,
            "parent_1_g1_bonus": bonus_1,
            "parent_2_g1_bonus": bonus_2,
            "g1_bonus": bonus_1 + bonus_2,
        }

    gp1_branch = branch(gp1, "fixed_gp1")
    gp2_branch = branch(gp2, "online_gp2")
    pair_base = resolver.pair(int(gp1.get("chara_id") or 0), int(gp2.get("chara_id") or 0))
    pair_common = sorted(_member_g1(gp1) & _member_g1(gp2))
    pair_bonus = g1_bonus_value * len(pair_common)
    base = int(gp1_branch["base"]) + int(gp2_branch["base"]) + pair_base
    bonus = int(gp1_branch["g1_bonus"]) + int(gp2_branch["g1_bonus"]) + pair_bonus
    relationship_g1_matches = (
        len(gp1_branch["parent_1_common_g1"])
        + len(gp1_branch["parent_2_common_g1"])
        + len(gp2_branch["parent_1_common_g1"])
        + len(gp2_branch["parent_2_common_g1"])
        + len(pair_common)
    )
    gp1_specific_base = int(gp1_branch["base"]) + pair_base
    gp2_specific_base = int(gp2_branch["base"]) + pair_base
    gp1_specific_g1_bonus = int(gp1_branch["g1_bonus"]) + pair_bonus
    gp2_specific_g1_bonus = int(gp2_branch["g1_bonus"]) + pair_bonus
    return {
        "base": base,
        "g1_bonus": bonus,
        "total": base + bonus,
        "g1_bonus_per_match": g1_bonus_value,
        "relationship_g1_match_count": relationship_g1_matches,
        "gp1_inheritance_modifier": {
            "base": gp1_specific_base,
            "g1_bonus": gp1_specific_g1_bonus,
            "total": gp1_specific_base + gp1_specific_g1_bonus,
        },
        "gp2_inheritance_modifier": {
            "base": gp2_specific_base,
            "g1_bonus": gp2_specific_g1_bonus,
            "total": gp2_specific_base + gp2_specific_g1_bonus,
        },
        "gp1_branch": gp1_branch,
        "gp2_branch": gp2_branch,
        # Compatibility aliases retained for existing exports/UI clients.
        "gp1_branch_base": gp1_branch["base"],
        "gp2_branch_base": gp2_branch["base"],
        "gp1_branch_g1_bonus": gp1_branch["g1_bonus"],
        "gp2_branch_g1_bonus": gp2_branch["g1_bonus"],
        "gp_pair_base": pair_base,
        "gp_pair_common_g1": pair_common,
        "gp_pair_common_g1_bonus": pair_bonus,
        "gp1_parent_common_g1": [gp1_branch["parent_1_common_g1"], gp1_branch["parent_2_common_g1"]],
        "gp2_parent_common_g1": [gp2_branch["parent_1_common_g1"], gp2_branch["parent_2_common_g1"]],
        "formula": "branch(GP1) + branch(GP2) + pair(GP1,GP2), with +3 per common G1 on each of the five lineage links",
    }


def _final_parent_affinity_potential(
    resolver: AffinityResolver,
    ace_chara: int,
    target_parent_chara: int,
    gp1: dict[str, Any],
    gp2: dict[str, Any],
    g1_bonus_value: int,
    planned_g1_budget: int,
    single_g1_weight: float = 0.6,
) -> dict[str, Any]:
    """Estimate the future parent branch in the final Ace run.

    Exact character compatibility only stops at the selected GP1/GP2. The current
    parents of those grandparents are deliberately excluded: they help generate
    the future parent, but are no longer present in the Ace's visible lineage.

    The future parent's actual race list does not exist yet. We therefore expose
    a budgeted optimistic estimate: common GP1/GP2 G1s are selected first because
    one target-parent win would create two +3 links; remaining race slots create
    one +3 link each. The other final parent and its cross-link are unknown and
    are not included.
    """
    budget = max(0, min(int(planned_g1_budget), 40))
    fixed_chara = int(gp1.get("chara_id") or 0)
    candidate_chara = int(gp2.get("chara_id") or 0)
    pair_ace_parent = resolver.pair(ace_chara, target_parent_chara)
    fixed_triple = resolver.triple(ace_chara, target_parent_chara, fixed_chara)
    candidate_triple = resolver.triple(ace_chara, target_parent_chara, candidate_chara)
    base = pair_ace_parent + fixed_triple + candidate_triple

    fixed_g1 = _member_g1(gp1)
    candidate_g1 = _member_g1(gp2)
    common = sorted(fixed_g1 & candidate_g1)
    fixed_only = sorted(fixed_g1 - candidate_g1)
    candidate_only = sorted(candidate_g1 - fixed_g1)

    double_count = min(len(common), budget)
    remaining = max(0, budget - double_count)
    single_pool_count = len(fixed_only) + len(candidate_only)
    single_count = min(single_pool_count, remaining)
    single_weight = max(0.0, min(float(single_g1_weight), 1.0))
    common_bonus = double_count * 2 * g1_bonus_value
    single_bonus_exact = single_count * g1_bonus_value
    single_bonus_weighted = single_bonus_exact * single_weight
    planned_bonus = common_bonus + single_bonus_weighted
    planned_bonus_exact_if_all_won = common_bonus + single_bonus_exact
    theoretical_unbounded_bonus = (
        len(common) * 2 * g1_bonus_value
        + (len(fixed_only) + len(candidate_only)) * g1_bonus_value * single_weight
    )
    theoretical_unbounded_bonus_exact = (len(fixed_g1) + len(candidate_g1)) * g1_bonus_value

    return {
        "pair_ace_parent": pair_ace_parent,
        "fixed_gp_triple": fixed_triple,
        "candidate_gp_triple": candidate_triple,
        "base": base,
        "planned_g1_budget": budget,
        "common_gp_g1": common,
        "fixed_only_g1": fixed_only,
        "candidate_only_g1": candidate_only,
        "common_g1_count": len(common),
        "fixed_only_g1_count": len(fixed_only),
        "candidate_only_g1_count": len(candidate_only),
        "planned_double_overlap_races": double_count,
        "planned_single_overlap_races": single_count,
        "single_g1_weight": single_weight,
        "planned_common_g1_bonus": common_bonus,
        "planned_single_g1_bonus_exact": single_bonus_exact,
        "planned_single_g1_bonus_weighted": single_bonus_weighted,
        "planned_g1_bonus": planned_bonus,
        "planned_g1_bonus_exact_if_all_won": planned_bonus_exact_if_all_won,
        "potential_total": base + planned_bonus,
        "potential_total_exact_if_all_won": base + planned_bonus_exact_if_all_won,
        "theoretical_unbounded_g1_bonus": theoretical_unbounded_bonus,
        "theoretical_unbounded_total": base + theoretical_unbounded_bonus,
        "theoretical_unbounded_g1_bonus_exact": theoretical_unbounded_bonus_exact,
        "theoretical_unbounded_total_exact": base + theoretical_unbounded_bonus_exact,
        "g1_bonus_per_link": g1_bonus_value,
        "other_final_parent_links_included": False,
        "formula": (
            "pair(Ace,parent) + triple(Ace,parent,GP1) + triple(Ace,parent,GP2) "
            "+ budgeted G1(parent,GP1/GP2), with one-sided G1 discounted by the configured realization factor; "
            "GP ancestors and the unknown other final parent are excluded"
        ),
    }


def _identity(member: dict[str, Any]) -> dict[str, Any]:
    return {
        "trained_chara_id": member.get("trained_chara_id"),
        "card_id": member.get("card_id"),
        "chara_id": member.get("chara_id"),
        "uma_name": member.get("uma_name"),
        "card_name": member.get("card_name"),
        "rank_score": member.get("rank_score"),
        "factors": member.get("factors"),
        "g1_wins": member.get("g1_wins"),
        "online": member.get("online"),
        "when_used_as_parent": member.get("when_used_as_parent"),
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    import csv

    fields = [
        "rank", "score",
        "local_id", "local_candidate", "local_rank_score",
        "friend_code", "trainer_name", "candidate", "rank_score",
        "final_parent_base", "planned_g1_budget", "planned_g1_bonus",
        "planned_g1_bonus_exact", "single_g1_weight", "final_parent_potential",
        "production_run_affinity", "common_gp_g1", "local_only_g1", "remote_only_g1",
        "blue", "pink", "white", "white_generation", "candidate_g1",
        "updated_at", "follow_status",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter=";")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def rank_online_grandparent_pairs(
    master_path: str | Path,
    linked_veterans_path: str | Path,
    manual_weights_path: str | Path,
    skill_catalog_path: str | Path,
    output_dir: str | Path,
    *,
    ace_card_id: int,
    target_parent_card_id: int,
    fixed_grandparent_trained_id: int | None = None,
    exhaustive_pairs: bool = False,
    local_pool_size: int = 100,
    remote_pool_size: int = 100,
    surface: str,
    distance: str,
    style: str,
    raw_payload: Any,
    course_weights_path: str | Path | None = None,
    course_key: str | None = None,
    course_conditions: dict[str, int | list[int] | tuple[int, ...] | set[int] | None] | None = None,
    scoring_config_path: str | Path | None = None,
    planned_g1_budget: int = 24,
    single_g1_weight: float = 0.6,
    top_n: int = 50,
    api_operation: dict[str, Any] | None = None,
    required_main_factors: Iterable[dict[str, Any]] | None = None,
    effective_uql: str = "",
    logger: Callable[[str], None] | None = None,
) -> OnlineSearchResult:
    log = logger or (lambda _message: None)
    master_path = Path(master_path).resolve()
    linked_veterans_path = Path(linked_veterans_path).resolve()
    manual_weights_path = Path(manual_weights_path).resolve()
    skill_catalog_path = Path(skill_catalog_path).resolve()
    output_dir = Path(output_dir).resolve()
    course_weights_path = Path(course_weights_path).resolve() if course_weights_path else None
    scoring_config_path = Path(scoring_config_path).resolve() if scoring_config_path else Path(__file__).resolve().parent / "default_parent_scoring.json"
    output_dir.mkdir(parents=True, exist_ok=True)

    linked = _read_json(linked_veterans_path)
    weights = _read_json(manual_weights_path)
    skill_catalog = _read_json(skill_catalog_path)
    course_payload = _read_json(course_weights_path) if course_weights_path and course_weights_path.is_file() else None
    config = _read_json(scoring_config_path)
    veterans = list(linked.get("veterans") or [])

    fixed: dict[str, Any] | None = None
    if fixed_grandparent_trained_id is not None:
        fixed = next(
            (veteran for veteran in veterans if int(veteran.get("trained_chara_id") or 0) == int(fixed_grandparent_trained_id)),
            None,
        )
        if fixed is None and not exhaustive_pairs:
            raise UmaMoeError(f"Grand-parent local introuvable : #{fixed_grandparent_trained_id}")

    normalizer = OnlineRecordNormalizer(master_path)
    try:
        online_candidates, normalization_diag = normalizer.normalize_records(raw_payload)
    finally:
        normalizer.close()
    if not online_candidates:
        raise UmaMoeError("La réponse uma.moe ne contient aucun candidat avec card/factors exploitables.")

    operation_uql = str((api_operation or {}).get("effective_uql") or effective_uql or "")
    generated_meta = (api_operation or {}).get("generated_uql_metadata") or {}
    generated_filters = generated_meta.get("hard_filters") if isinstance(generated_meta, dict) else None
    strict_main_filters = _normalize_main_factor_filters(
        list(required_main_factors or []) + list(generated_filters or []),
        operation_uql,
    )
    unfiltered_online_count = len(online_candidates)
    if strict_main_filters:
        online_candidates = [
            candidate
            for candidate in online_candidates
            if _member_matches_main_factor_filters(candidate, strict_main_filters)
        ]
        filter_text = ", ".join(
            f"Main {item['factor']} >= {item['minimum_stars']}"
            for item in strict_main_filters
        )
        log(
            f"Contrôle local strict des pinks : {len(online_candidates)}/{unfiltered_online_count} "
            f"candidats respectent {filter_text}."
        )
        normalization_diag["strict_main_factor_filters"] = strict_main_filters
        normalization_diag["pre_filter_count"] = unfiltered_online_count
        normalization_diag["post_filter_count"] = len(online_candidates)
        if not online_candidates:
            raise UmaMoeError(
                "Aucun candidat uma.moe ne respecte les contraintes Main sélectionnées "
                f"({filter_text}). L'API a peut-être ignoré le filtre UQL ou le pool demandé est trop petit."
            )
    else:
        normalization_diag["strict_main_factor_filters"] = []
        normalization_diag["pre_filter_count"] = unfiltered_online_count
        normalization_diag["post_filter_count"] = unfiltered_online_count
    log(f"uma.moe : {len(online_candidates)} candidats distants normalisés.")

    resolver = AffinityResolver(master_path)
    try:
        ace = resolver.ace_details(int(ace_card_id), surface, distance, style)
        target_parent = resolver.card_details(int(target_parent_card_id))
        ace_chara = int(ace["chara_id"])
        target_parent_chara = int(target_parent["chara_id"])
        normalized_conditions: dict[str, set[int]] = {}
        for key, raw in (course_conditions or {}).items():
            if raw is None or raw == "":
                continue
            values = raw if isinstance(raw, (list, tuple, set)) else [raw]
            normalized_conditions[str(key)] = {int(value) for value in values}
        course_cfg = config.get("course_conditions") or {}
        weight_lookup, weight_source, condition_diag = _selected_weight_lookup(
            weights,
            course_payload,
            skill_catalog,
            surface,
            distance,
            style,
            course_key,
            normalized_conditions,
            float(course_cfg.get("active_green_floor", 0.12)),
            {str(key): float(value) for key, value in (course_cfg.get("floors") or {}).items()},
            {str(key): str(value) for key, value in (course_cfg.get("modes") or {}).items()},
        )

        online_cfg = config.get("uma_moe_pair") or {}
        mode_weights = online_cfg.get("weights") or {
            "final_parent_affinity": 0.22,
            "production_run_affinity": 0.04,
            "pink": 0.24,
            "white_skill": 0.26,
            "white_generation": 0.18,
            "blue": 0.06,
        }
        preselection_weights = online_cfg.get("preselection_weights") or {
            "candidate_affinity": 0.18,
            "pink": 0.30,
            "white_skill": 0.24,
            "white_generation": 0.18,
            "blue": 0.06,
            "g1_potential": 0.04,
        }
        affinity_cfg = config.get("affinity") or {}
        g1_bonus_value = int(affinity_cfg.get("g1_common_bonus", 3))
        final_thresholds = online_cfg.get("final_parent_potential_thresholds") or affinity_cfg.get("parent_pair_thresholds") or [[0, 0], [151, 100]]
        production_thresholds = online_cfg.get("production_run_affinity_thresholds") or affinity_cfg.get("parent_pair_thresholds") or [[0, 0], [151, 100]]
        triple_thresholds = online_cfg.get("gp_triple_preselection_thresholds") or [[0, 0], [8, 35], [16, 70], [24, 100]]
        g1_thresholds = online_cfg.get("candidate_g1_thresholds") or [[0, 0], [6, 30], [12, 65], [16, 85], [20, 100]]
        single_g1_weight = max(0.0, min(float(single_g1_weight), 1.0))

        def full_score_threshold(points: Any) -> float | None:
            candidates: list[float] = []
            for point in points or []:
                try:
                    raw_value, score_value = point
                    if float(score_value) >= 100.0:
                        candidates.append(float(raw_value))
                except (TypeError, ValueError):
                    continue
            return min(candidates) if candidates else None

        final_full_score_at = full_score_threshold(final_thresholds)
        production_full_score_at = full_score_threshold(production_thresholds)

        def eligible(member: dict[str, Any]) -> bool:
            chara = int(member.get("chara_id") or 0)
            return chara > 0 and chara != target_parent_chara

        def individual_score(member: dict[str, Any]) -> dict[str, Any]:
            members = [(member, "grandparent", "candidate")]
            blue, _ = _blue_score(members, distance, config)
            pink, _ = _pink_score(members, ace, surface, distance, style, config)
            white, _ = _white_score(members, weight_lookup, config, "future_grandparent")
            white_generation, _ = _white_generation_support_score(_lineage_members(member), weight_lookup, config)
            triple_raw = resolver.triple(ace_chara, target_parent_chara, int(member.get("chara_id") or 0))
            g1_count = len(_member_g1(member))
            components = {
                "candidate_affinity": _affinity_score(triple_raw, triple_thresholds),
                "pink": pink,
                "white_skill": white,
                "white_generation": white_generation,
                "blue": blue,
                "g1_potential": _affinity_score(g1_count, g1_thresholds),
            }
            breakdown = _score_breakdown(components, preselection_weights)
            return {
                "member": member,
                "score": float(breakdown["total"]),
                "triple_raw": triple_raw,
                "g1_count": g1_count,
                "components": components,
            }

        remote_eligible = [member for member in online_candidates if eligible(member)]
        if exhaustive_pairs:
            local_eligible = [member for member in veterans if eligible(member)]
            log(f"Préclassement de {len(local_eligible)} GP locaux et {len(remote_eligible)} GP distants…")
            local_pre = sorted((individual_score(member) for member in local_eligible), key=lambda row: row["score"], reverse=True)
            remote_pre = sorted((individual_score(member) for member in remote_eligible), key=lambda row: row["score"], reverse=True)
            selected_locals = [row["member"] for row in local_pre[: max(1, min(int(local_pool_size), 250))]]
            selected_remotes = [row["member"] for row in remote_pre[: max(1, min(int(remote_pool_size), 500))]]
            pair_mode = "exhaustive_top_pools"
        else:
            if fixed is None:
                raise UmaMoeError("Sélectionne un GP local ou active le test automatique des paires.")
            selected_locals = [fixed]
            selected_remotes = remote_eligible
            local_pre = [individual_score(fixed)]
            remote_pre = []
            pair_mode = "fixed_local_gp"

        log(
            f"Comparaison exhaustive : {len(selected_locals)} locaux × {len(selected_remotes)} distants "
            f"(jusqu’à {len(selected_locals) * len(selected_remotes)} paires avant exclusions)."
        )

        def evaluate_pair(gp1: dict[str, Any], gp2: dict[str, Any], *, detailed: bool) -> dict[str, Any]:
            final_parent_affinity = _final_parent_affinity_potential(
                resolver,
                ace_chara,
                target_parent_chara,
                gp1,
                gp2,
                g1_bonus_value,
                planned_g1_budget,
                single_g1_weight,
            )
            final_parent_affinity["full_score_at"] = final_full_score_at
            production_affinity = _full_production_affinity(
                resolver,
                target_parent_chara,
                gp1,
                gp2,
                g1_bonus_value,
            )
            production_affinity["full_score_at"] = production_full_score_at
            # Both sides vary in exhaustive mode, therefore the complete farming-run
            # compatibility is the relevant low-weight diagnostic.
            production_affinity["scored_value"] = production_affinity["total"]
            production_affinity["scored_mode"] = "complete_farming_run"

            direct_members = [
                (gp1, "grandparent", "local_gp1"),
                (gp2, "grandparent", "online_gp2"),
            ]
            six_members = _lineage_members(gp1) + _lineage_members(gp2)
            blue, blue_detail = _blue_score(direct_members, distance, config)
            pink, pink_detail = _pink_score(direct_members, ace, surface, distance, style, config)
            white, white_detail = _white_score(direct_members, weight_lookup, config, "future_grandparent")
            white_generation, white_generation_detail = _white_generation_support_score(six_members, weight_lookup, config)
            components = {
                "final_parent_affinity": _affinity_score(final_parent_affinity["potential_total"], final_thresholds),
                "production_run_affinity": _affinity_score(production_affinity["scored_value"], production_thresholds),
                "pink": pink,
                "white_skill": white,
                "white_generation": white_generation,
                "blue": blue,
            }
            breakdown = _score_breakdown(components, mode_weights)
            row: dict[str, Any] = {
                "score": float(breakdown["total"]),
                "local_trained_id": gp1.get("trained_chara_id"),
                "local_card_name": gp1.get("card_name"),
                "local_rank_score": gp1.get("rank_score"),
                "remote_inheritance_id": ((gp2.get("online") or {}).get("inheritance_id")),
                "remote_card_name": gp2.get("card_name"),
                "remote_rank_score": gp2.get("rank_score"),
                "_gp1": gp1,
                "_gp2": gp2,
                "final_parent_affinity": final_parent_affinity,
                "production_affinity": production_affinity,
                "components": components,
                "score_breakdown": breakdown,
                "candidate_g1_count": len(_member_g1(gp2)),
            }
            if detailed:
                row.update({
                    "candidate": _identity(gp2),
                    "fixed_grandparent": _identity(gp1),
                    "final_branch_affinity": {**final_parent_affinity, "total": final_parent_affinity["potential_total"]},
                    "component_details": {
                        "blue": blue_detail,
                        "pink": pink_detail,
                        "white_skill": white_detail,
                        "white_generation": white_generation_detail,
                    },
                })
            return row

        summaries: list[dict[str, Any]] = []
        total_possible = len(selected_locals) * len(selected_remotes)
        processed = 0
        for gp1 in selected_locals:
            gp1_chara = int(gp1.get("chara_id") or 0)
            for gp2 in selected_remotes:
                processed += 1
                gp2_chara = int(gp2.get("chara_id") or 0)
                if gp1_chara <= 0 or gp2_chara <= 0 or gp1_chara == gp2_chara:
                    continue
                summaries.append(evaluate_pair(gp1, gp2, detailed=False))
            if exhaustive_pairs and (processed % max(1, len(selected_remotes) * 10) == 0 or processed == total_possible):
                log(f"Paires évaluées : {processed}/{total_possible} — {len(summaries)} valides.")

        summaries.sort(key=lambda row: (row["score"], row["final_parent_affinity"]["potential_total"]), reverse=True)
        detail_count = max(1, min(int(top_n), 500))
        top: list[dict[str, Any]] = []
        for summary in summaries[:detail_count]:
            top.append(evaluate_pair(summary["_gp1"], summary["_gp2"], detailed=True))
    finally:
        resolver.close()

    generated = datetime.now(timezone.utc).isoformat()
    raw_response_path = output_dir / "uma_moe_raw_response.json"
    raw_response_path.write_text(json.dumps(raw_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rankings_json_path = output_dir / "uma_moe_grandparent_pairs.json"
    payload = {
        "metadata": {
            "schema_version": 4,
            "generated_at_utc": generated,
            "source": "uma.moe public API or imported API response",
            "api_operation": api_operation,
            "weight_source": weight_source,
            "pair_mode": pair_mode,
            "local_pool_count": len(selected_locals),
            "remote_pool_count": len(selected_remotes),
            "evaluated_pair_count": len(summaries),
            "profile": {
                "surface": surface,
                "distance": distance,
                "style": style,
                "course_key": course_key,
                "course_conditions": {key: sorted(value) for key, value in normalized_conditions.items()},
                "planned_parent_g1_budget": max(0, min(int(planned_g1_budget), 40)),
                "single_g1_weight": single_g1_weight,
            },
            "normalization": normalization_diag,
            "condition_diagnostics": condition_diag,
            "white_star_model": {
                "meaning": "Stars modify inheritance comfort, not the intrinsic strategic value of the skill.",
                "coefficients": config.get("white_star_quality") or config.get("star_quality") or {},
                "saturation": config.get("white_saturation") or {},
            },
            "important": "Online records can become stale; verify follow availability and the profile on uma.moe before relying on a borrow.",
        },
        "ace": ace,
        "target_parent": target_parent,
        "fixed_grandparent": (_identity(fixed) if fixed is not None and not exhaustive_pairs else None),
        "scoring": {
            "weights": mode_weights,
            "preselection_weights": preselection_weights,
            "logic": "Preselect strong local/remote grandparents, then exhaustively score every cross-pair for final-parent affinity, factors, white stacking and low-weight farming compatibility.",
        },
        "results": top,
    }
    rankings_json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    csv_rows: list[dict[str, Any]] = []
    for rank, row in enumerate(summaries, 1):
        gp1 = row["_gp1"]
        gp2 = row["_gp2"]
        online = gp2.get("online") or {}
        final_aff = row["final_parent_affinity"]
        common_races = final_aff.get("common_gp_g1") or []
        local_only_races = final_aff.get("fixed_only_g1") or []
        remote_only_races = final_aff.get("candidate_only_g1") or []
        csv_rows.append({
            "rank": rank,
            "score": round(row["score"], 3),
            "local_id": gp1.get("trained_chara_id"),
            "local_candidate": gp1.get("card_name"),
            "local_rank_score": gp1.get("rank_score"),
            "friend_code": online.get("friend_code"),
            "trainer_name": online.get("trainer_name"),
            "candidate": gp2.get("card_name"),
            "rank_score": gp2.get("rank_score"),
            "final_parent_base": final_aff["base"],
            "planned_g1_budget": final_aff["planned_g1_budget"],
            "planned_g1_bonus": round(float(final_aff["planned_g1_bonus"]), 3),
            "planned_g1_bonus_exact": final_aff["planned_g1_bonus_exact_if_all_won"],
            "single_g1_weight": final_aff["single_g1_weight"],
            "final_parent_potential": round(float(final_aff["potential_total"]), 3),
            "production_run_affinity": row["production_affinity"]["total"],
            "common_gp_g1_count": final_aff["common_g1_count"],
            "local_only_g1_count": final_aff["fixed_only_g1_count"],
            "remote_only_g1_count": final_aff["candidate_only_g1_count"],
            "common_gp_g1_races": "; ".join(common_races),
            "local_only_g1_races": "; ".join(local_only_races),
            "remote_only_g1_races": "; ".join(remote_only_races),
            "blue": round(row["components"]["blue"], 2),
            "pink": round(row["components"]["pink"], 2),
            "white": round(row["components"]["white_skill"], 2),
            "white_generation": round(row["components"]["white_generation"], 2),
            "candidate_g1": row["candidate_g1_count"],
            "updated_at": online.get("updated_at"),
            "follow_status": online.get("follow_status"),
        })
    rankings_csv_path = output_dir / "uma_moe_grandparent_pairs.csv"
    _write_csv(rankings_csv_path, csv_rows)

    diagnostics_path = output_dir / "uma_moe_diagnostics.json"
    diagnostics_path.write_text(
        json.dumps({
            "generated_at_utc": generated,
            "api_operation": api_operation,
            "normalization": normalization_diag,
            "input_remote_candidate_count": len(online_candidates),
            "eligible_remote_candidate_count": len(remote_eligible),
            "selected_local_pool_count": len(selected_locals),
            "selected_remote_pool_count": len(selected_remotes),
            "evaluated_pair_count": len(summaries),
            "top_count": len(top),
            "pair_mode": pair_mode,
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return OnlineSearchResult(
        rankings_json_path=rankings_json_path,
        rankings_csv_path=rankings_csv_path,
        raw_response_path=raw_response_path,
        diagnostics_path=diagnostics_path,
        result_count=len(summaries),
        top_results=tuple(top),
        fixed_grandparent=(_identity(fixed) if fixed is not None and not exhaustive_pairs else None),
        pair_mode=pair_mode,
        local_pool_count=len(selected_locals),
        remote_pool_count=len(selected_remotes),
        evaluated_pair_count=len(summaries),
        ace=ace,
        target_parent=target_parent,
        api_operation=api_operation,
    )



def _has_complete_parent_branch(member: dict[str, Any]) -> bool:
    """Return whether a final-parent candidate exposes both visible grandparents."""
    lineage = member.get("when_used_as_parent") or {}
    for grandparent in (lineage.get("grandparent_1"), lineage.get("grandparent_2")):
        if not isinstance(grandparent, dict):
            return False
        try:
            if int(grandparent.get("chara_id") or 0) <= 0:
                return False
        except (TypeError, ValueError):
            return False
    return True


def _write_parent_pair_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    import csv

    fields = [
        "rank", "score",
        "local_id", "local_parent", "local_rank_score", "local_branch_score",
        "local_gp1", "local_gp2",
        "friend_code", "trainer_name", "remote_parent", "remote_rank_score", "remote_branch_score",
        "remote_gp1", "remote_gp2",
        "affinity_total", "affinity_base", "affinity_g1_bonus",
        "parent_parent_base", "parent_parent_common_g1_count", "parent_parent_common_g1",
        "affinity_component", "pink", "white", "race_scenario", "blue", "unique",
        "updated_at", "follow_status",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter=";")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def rank_online_parent_pairs(
    master_path: str | Path,
    linked_veterans_path: str | Path,
    manual_weights_path: str | Path,
    race_factor_catalog_path: str | Path,
    skill_catalog_path: str | Path,
    output_dir: str | Path,
    *,
    ace_card_id: int,
    fixed_parent_trained_id: int | None = None,
    exhaustive_pairs: bool = False,
    local_pool_size: int = 100,
    remote_pool_size: int = 100,
    surface: str,
    distance: str,
    style: str,
    raw_payload: Any,
    course_weights_path: str | Path | None = None,
    course_key: str | None = None,
    course_conditions: dict[str, int | list[int] | tuple[int, ...] | set[int] | None] | None = None,
    scoring_config_path: str | Path | None = None,
    top_n: int = 50,
    api_operation: dict[str, Any] | None = None,
    required_main_factors: Iterable[dict[str, Any]] | None = None,
    effective_uql: str = "",
    logger: Callable[[str], None] | None = None,
) -> OnlineParentSearchResult:
    """Rank uma.moe parents paired with a local parent for the selected Ace.

    The candidate Main from uma.moe is normalized to the same veteran structure
    as a local parent, including its two visible grandparents. Every final pair
    is then evaluated by :func:`parent_optimizer.evaluate_parent_pair`, which is
    also the engine used by the all-local optimizer.
    """
    log = logger or (lambda _message: None)
    master_path = Path(master_path).resolve()
    linked_veterans_path = Path(linked_veterans_path).resolve()
    manual_weights_path = Path(manual_weights_path).resolve()
    race_factor_catalog_path = Path(race_factor_catalog_path).resolve()
    skill_catalog_path = Path(skill_catalog_path).resolve()
    output_dir = Path(output_dir).resolve()
    course_weights_path = Path(course_weights_path).resolve() if course_weights_path else None
    scoring_config_path = (
        Path(scoring_config_path).resolve()
        if scoring_config_path
        else Path(__file__).resolve().parent / "default_parent_scoring.json"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    linked = _read_json(linked_veterans_path)
    weights = _read_json(manual_weights_path)
    race_catalog = _read_json(race_factor_catalog_path)
    skill_catalog = _read_json(skill_catalog_path)
    course_payload = _read_json(course_weights_path) if course_weights_path and course_weights_path.is_file() else None
    config = _read_json(scoring_config_path)
    veterans = list(linked.get("veterans") or [])
    if not veterans:
        raise UmaMoeError("Aucun parent local dans veterans_legacy_linked.json.")

    fixed: dict[str, Any] | None = None
    if fixed_parent_trained_id is not None:
        fixed = next(
            (
                veteran
                for veteran in veterans
                if int(veteran.get("trained_chara_id") or 0) == int(fixed_parent_trained_id)
            ),
            None,
        )
        if fixed is None and not exhaustive_pairs:
            raise UmaMoeError(f"Parent local introuvable : #{fixed_parent_trained_id}")

    normalizer = OnlineRecordNormalizer(master_path)
    try:
        online_candidates, normalization_diag = normalizer.normalize_records(raw_payload)
    finally:
        normalizer.close()
    if not online_candidates:
        raise UmaMoeError("La réponse uma.moe ne contient aucun parent avec Main/factors exploitables.")

    operation_uql = str((api_operation or {}).get("effective_uql") or effective_uql or "")
    generated_meta = (api_operation or {}).get("generated_uql_metadata") or {}
    generated_filters = generated_meta.get("hard_filters") if isinstance(generated_meta, dict) else None
    strict_main_filters = _normalize_main_factor_filters(
        list(required_main_factors or []) + list(generated_filters or []),
        operation_uql,
    )
    unfiltered_online_count = len(online_candidates)
    if strict_main_filters:
        online_candidates = [
            candidate
            for candidate in online_candidates
            if _member_matches_main_factor_filters(candidate, strict_main_filters)
        ]
        filter_text = ", ".join(
            f"Main {item['factor']} >= {item['minimum_stars']}"
            for item in strict_main_filters
        )
        log(
            f"Contrôle local strict des pinks : {len(online_candidates)}/{unfiltered_online_count} "
            f"parents respectent {filter_text}."
        )
        normalization_diag["strict_main_factor_filters"] = strict_main_filters
        normalization_diag["pre_filter_count"] = unfiltered_online_count
        normalization_diag["post_filter_count"] = len(online_candidates)
        if not online_candidates:
            raise UmaMoeError(
                "Aucun parent uma.moe ne respecte les contraintes Main sélectionnées "
                f"({filter_text}). Le pool demandé est peut-être trop petit."
            )
    else:
        normalization_diag["strict_main_factor_filters"] = []
        normalization_diag["pre_filter_count"] = unfiltered_online_count
        normalization_diag["post_filter_count"] = unfiltered_online_count
    log(f"uma.moe : {len(online_candidates)} branches parent distantes normalisées.")

    resolver = AffinityResolver(master_path)
    try:
        ace = resolver.ace_details(int(ace_card_id), surface, distance, style)
        ace_chara = int(ace["chara_id"])
        normalized_conditions = _normalize_course_condition_sets(course_conditions)
        course_cfg = config.get("course_conditions") or {}
        weight_lookup, weight_source, condition_diag = _selected_weight_lookup(
            weights,
            course_payload,
            skill_catalog,
            surface,
            distance,
            style,
            course_key,
            normalized_conditions,
            float(course_cfg.get("active_green_floor", 0.12)),
            {str(key): float(value) for key, value in (course_cfg.get("floors") or {}).items()},
            {str(key): str(value) for key, value in (course_cfg.get("modes") or {}).items()},
        )
        race_skills = _race_skill_map(race_catalog)
        affinity_cfg = config.get("affinity") or {}
        g1_bonus_value = int(affinity_cfg.get("g1_common_bonus", 3))
        branch_thresholds = affinity_cfg.get("parent_branch_thresholds") or [[0, 0], [95, 100]]
        pair_thresholds = affinity_cfg.get("parent_pair_thresholds") or [[0, 0], [151, 100]]
        pair_weights = (config.get("mode_weights") or {}).get("parent_final") or {}

        def eligible(member: dict[str, Any]) -> bool:
            chara = int(member.get("chara_id") or 0)
            return chara > 0 and chara != ace_chara

        branch_cache: dict[tuple[str, int], dict[str, Any]] = {}

        def cache_key(member: dict[str, Any], source: str) -> tuple[str, int]:
            if source == "local":
                raw_id = member.get("trained_chara_id")
            else:
                raw_id = (member.get("online") or {}).get("inheritance_id") or member.get("trained_chara_id")
            try:
                return source, int(raw_id)
            except (TypeError, ValueError):
                return source, id(member)

        def branch_score(member: dict[str, Any], source: str) -> dict[str, Any]:
            key = cache_key(member, source)
            cached = branch_cache.get(key)
            if cached is not None:
                return cached
            scored = evaluate_parent_branch(
                resolver,
                ace,
                member,
                surface=surface,
                distance=distance,
                style=style,
                weight_lookup=weight_lookup,
                race_skills=race_skills,
                config=config,
                g1_bonus_value=g1_bonus_value,
                affinity_thresholds=branch_thresholds,
            )
            branch_cache[key] = scored
            return scored

        remote_compatible = [member for member in online_candidates if eligible(member)]
        remote_eligible = [member for member in remote_compatible if _has_complete_parent_branch(member)]
        incomplete_remote_count = len(remote_compatible) - len(remote_eligible)
        normalization_diag["incomplete_parent_branches_excluded"] = incomplete_remote_count
        if incomplete_remote_count:
            log(
                f"Branches distantes incomplètes exclues : {incomplete_remote_count} "
                "(les deux grands-parents sont requis pour le calcul à six membres)."
            )
        if not remote_eligible:
            raise UmaMoeError(
                "Aucun parent distant compatible avec une branche complète "
                "(Main + deux grands-parents)."
            )

        if exhaustive_pairs:
            local_compatible = [member for member in veterans if eligible(member)]
            local_eligible = [member for member in local_compatible if _has_complete_parent_branch(member)]
            incomplete_local_count = len(local_compatible) - len(local_eligible)
            if incomplete_local_count:
                log(
                    f"Branches locales incomplètes exclues : {incomplete_local_count} "
                    "(les deux grands-parents sont requis)."
                )
            if not local_eligible:
                raise UmaMoeError(
                    "Aucun parent local compatible avec une branche complète "
                    "(parent + deux grands-parents)."
                )
            log(
                f"Préclassement via le moteur local : {len(local_eligible)} parents locaux et "
                f"{len(remote_eligible)} parents distants…"
            )
            local_pre = sorted(
                (branch_score(member, "local") for member in local_eligible),
                key=lambda row: (row["score"], row["affinity"]["total"]),
                reverse=True,
            )
            remote_pre = sorted(
                (branch_score(member, "remote") for member in remote_eligible),
                key=lambda row: (row["score"], row["affinity"]["total"]),
                reverse=True,
            )
            selected_locals = [
                row["veteran"]
                for row in local_pre[: max(1, min(int(local_pool_size), 250))]
            ]
            selected_remotes = [
                row["veteran"]
                for row in remote_pre[: max(1, min(int(remote_pool_size), 500))]
            ]
            pair_mode = "exhaustive_parent_top_pools"
        else:
            if fixed is None:
                raise UmaMoeError("Sélectionne un parent local ou active le test automatique des paires.")
            if not eligible(fixed):
                raise UmaMoeError("Le parent local sélectionné est l'Ace ou n'a pas pu être résolu.")
            if not _has_complete_parent_branch(fixed):
                raise UmaMoeError(
                    "Le parent local sélectionné ne contient pas ses deux grands-parents ; "
                    "le calcul exact sur six membres est impossible."
                )
            incomplete_local_count = 0
            selected_locals = [fixed]
            selected_remotes = remote_eligible
            branch_score(fixed, "local")
            pair_mode = "fixed_local_parent"

        log(
            f"Calcul exact des paires de parents : {len(selected_locals)} locaux × "
            f"{len(selected_remotes)} distants, sur les six membres visibles."
        )

        def evaluate_pair(local_parent: dict[str, Any], remote_parent: dict[str, Any], *, detailed: bool) -> dict[str, Any]:
            local_branch = branch_score(local_parent, "local")
            remote_branch = branch_score(remote_parent, "remote")
            pair = evaluate_parent_pair(
                resolver,
                ace,
                local_parent,
                remote_parent,
                surface=surface,
                distance=distance,
                style=style,
                weight_lookup=weight_lookup,
                race_skills=race_skills,
                config=config,
                parent_1_branch=local_branch,
                parent_2_branch=remote_branch,
                g1_bonus_value=g1_bonus_value,
                affinity_thresholds=pair_thresholds,
            )
            row: dict[str, Any] = {
                "score": float(pair["score"]),
                "local_trained_id": local_parent.get("trained_chara_id"),
                "local_card_name": local_parent.get("card_name"),
                "local_rank_score": local_parent.get("rank_score"),
                "local_branch_score": float(local_branch["score"]),
                "remote_inheritance_id": (remote_parent.get("online") or {}).get("inheritance_id"),
                "remote_card_name": remote_parent.get("card_name"),
                "remote_rank_score": remote_parent.get("rank_score"),
                "remote_branch_score": float(remote_branch["score"]),
                "affinity": pair["affinity"],
                "components": pair["components"],
                "score_breakdown": pair["score_breakdown"],
                "_local_parent": local_parent,
                "_remote_parent": remote_parent,
            }
            if detailed:
                row.update({
                    "fixed_parent": _identity(local_parent),
                    "candidate": _identity(remote_parent),
                    "component_details": pair["component_details"],
                    "local_branch": {
                        "score": local_branch["score"],
                        "affinity": local_branch["affinity"],
                        "components": local_branch["components"],
                        "score_breakdown": local_branch["score_breakdown"],
                    },
                    "remote_branch": {
                        "score": remote_branch["score"],
                        "affinity": remote_branch["affinity"],
                        "components": remote_branch["components"],
                        "score_breakdown": remote_branch["score_breakdown"],
                    },
                })
                row.pop("_local_parent", None)
                row.pop("_remote_parent", None)
            return row

        summaries: list[dict[str, Any]] = []
        total_possible = len(selected_locals) * len(selected_remotes)
        processed = 0
        for local_parent in selected_locals:
            local_chara = int(local_parent.get("chara_id") or 0)
            for remote_parent in selected_remotes:
                processed += 1
                remote_chara = int(remote_parent.get("chara_id") or 0)
                if local_chara <= 0 or remote_chara <= 0 or local_chara == remote_chara:
                    continue
                summaries.append(evaluate_pair(local_parent, remote_parent, detailed=False))
            if exhaustive_pairs and (
                processed % max(1, len(selected_remotes) * 10) == 0
                or processed == total_possible
            ):
                log(f"Paires parent évaluées : {processed}/{total_possible} — {len(summaries)} valides.")

        if not summaries:
            raise UmaMoeError("Aucune paire parent local × parent distant valide.")
        summaries.sort(
            key=lambda row: (row["score"], row["affinity"]["total"]),
            reverse=True,
        )
        detail_count = max(1, min(int(top_n), 500))
        top = [
            evaluate_pair(row["_local_parent"], row["_remote_parent"], detailed=True)
            for row in summaries[:detail_count]
        ]
    finally:
        resolver.close()

    generated = datetime.now(timezone.utc).isoformat()
    raw_response_path = output_dir / "uma_moe_parent_raw_response.json"
    raw_response_path.write_text(
        json.dumps(raw_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    rankings_json_path = output_dir / "uma_moe_parent_pairs.json"
    payload = {
        "metadata": {
            "schema_version": 1,
            "generated_at_utc": generated,
            "source": "uma.moe public API or imported API response",
            "search_mode": "parent_for_ace",
            "api_operation": api_operation,
            "weight_source": weight_source,
            "pair_mode": pair_mode,
            "local_pool_count": len(selected_locals),
            "remote_pool_count": len(selected_remotes),
            "evaluated_pair_count": len(summaries),
            "profile": {
                "surface": surface,
                "distance": distance,
                "style": style,
                "course_key": course_key,
                "course_conditions": {
                    key: sorted(value) for key, value in normalized_conditions.items()
                },
            },
            "normalization": normalization_diag,
            "complete_branch_validation": {
                "remote_incomplete_excluded": incomplete_remote_count,
                "local_incomplete_excluded": incomplete_local_count,
                "required_visible_members_per_pair": 6,
            },
            "condition_diagnostics": condition_diag,
            "scoring_engine": "parent_optimizer.evaluate_parent_pair",
            "lineage_model": (
                "Exact same six-member final-parent pair formula as the local optimizer: "
                "two complete parent branches, parent-parent compatibility, five G1 links, "
                "and all factors from both parents plus their four grandparents."
            ),
            "important": (
                "Online records can become stale; verify follow availability and the profile "
                "on uma.moe before relying on a borrow."
            ),
        },
        "ace": ace,
        "fixed_parent": (_identity(fixed) if fixed is not None and not exhaustive_pairs else None),
        "scoring": {
            "weights": pair_weights,
            "branch_affinity_thresholds": branch_thresholds,
            "pair_affinity_thresholds": pair_thresholds,
            "logic": (
                "Remote Main records are normalized as complete parent branches, then passed "
                "unchanged to the same scorer as local parent pairs."
            ),
        },
        "results": top,
    }
    rankings_json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    csv_rows: list[dict[str, Any]] = []
    for rank, row in enumerate(summaries, 1):
        local_parent = row["_local_parent"]
        remote_parent = row["_remote_parent"]
        online = remote_parent.get("online") or {}
        local_lineage = local_parent.get("when_used_as_parent") or {}
        remote_lineage = remote_parent.get("when_used_as_parent") or {}
        affinity = row["affinity"]
        common = affinity.get("parent_parent_common_g1") or []
        components = row["components"]
        csv_rows.append({
            "rank": rank,
            "score": round(float(row["score"]), 3),
            "local_id": local_parent.get("trained_chara_id"),
            "local_parent": local_parent.get("card_name"),
            "local_rank_score": local_parent.get("rank_score"),
            "local_branch_score": round(float(row["local_branch_score"]), 3),
            "local_gp1": (local_lineage.get("grandparent_1") or {}).get("card_name"),
            "local_gp2": (local_lineage.get("grandparent_2") or {}).get("card_name"),
            "friend_code": online.get("friend_code"),
            "trainer_name": online.get("trainer_name"),
            "remote_parent": remote_parent.get("card_name"),
            "remote_rank_score": remote_parent.get("rank_score"),
            "remote_branch_score": round(float(row["remote_branch_score"]), 3),
            "remote_gp1": (remote_lineage.get("grandparent_1") or {}).get("card_name"),
            "remote_gp2": (remote_lineage.get("grandparent_2") or {}).get("card_name"),
            "affinity_total": affinity.get("total"),
            "affinity_base": affinity.get("base"),
            "affinity_g1_bonus": affinity.get("g1_bonus"),
            "parent_parent_base": affinity.get("parent_parent_base"),
            "parent_parent_common_g1_count": len(common),
            "parent_parent_common_g1": "; ".join(common),
            "affinity_component": round(float(components.get("affinity") or 0), 2),
            "pink": round(float(components.get("pink") or 0), 2),
            "white": round(float(components.get("white_skill") or 0), 2),
            "race_scenario": round(float(components.get("race_scenario") or 0), 2),
            "blue": round(float(components.get("blue") or 0), 2),
            "unique": round(float(components.get("unique") or 0), 2),
            "updated_at": online.get("updated_at"),
            "follow_status": online.get("follow_status"),
        })
    rankings_csv_path = output_dir / "uma_moe_parent_pairs.csv"
    _write_parent_pair_csv(rankings_csv_path, csv_rows)

    diagnostics_path = output_dir / "uma_moe_parent_diagnostics.json"
    diagnostics_path.write_text(
        json.dumps({
            "generated_at_utc": generated,
            "search_mode": "parent_for_ace",
            "api_operation": api_operation,
            "normalization": normalization_diag,
            "complete_branch_validation": {
                "remote_incomplete_excluded": incomplete_remote_count,
                "local_incomplete_excluded": incomplete_local_count,
                "required_visible_members_per_pair": 6,
            },
            "input_remote_candidate_count": len(online_candidates),
            "eligible_remote_candidate_count": len(remote_eligible),
            "selected_local_pool_count": len(selected_locals),
            "selected_remote_pool_count": len(selected_remotes),
            "evaluated_pair_count": len(summaries),
            "top_count": len(top),
            "pair_mode": pair_mode,
            "scoring_engine": "parent_optimizer.evaluate_parent_pair",
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return OnlineParentSearchResult(
        rankings_json_path=rankings_json_path,
        rankings_csv_path=rankings_csv_path,
        raw_response_path=raw_response_path,
        diagnostics_path=diagnostics_path,
        result_count=len(summaries),
        top_results=tuple(top),
        fixed_parent=(_identity(fixed) if fixed is not None and not exhaustive_pairs else None),
        pair_mode=pair_mode,
        local_pool_count=len(selected_locals),
        remote_pool_count=len(selected_remotes),
        evaluated_pair_count=len(summaries),
        ace=ace,
        api_operation=api_operation,
    )
