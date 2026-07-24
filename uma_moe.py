from __future__ import annotations

import hashlib
import copy
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
    _future_grandparent_pink_score,
    _future_grandparent_white_score,
    _initial_aptitude_rank,
    _lineage_members,
    _member_g1,
    _mode_weights,
    _pink_score,
    _race_skill_map,
    _read_json,
    _score_breakdown,
    _selected_weight_lookup,
    _static_condition_state,
    _unique_score,
    _valid_grandparent_for_target_parent,
    _white_generation_support_score,
    _white_score,
    evaluate_parent_branch,
    evaluate_parent_pair,
    parent_pair_sort_key,
)

DEFAULT_API_BASE = "https://uma.moe/api"
DEFAULT_DOCS_URL = "https://uma.moe/api/docs"
MAX_FETCH_CANDIDATES = 2000


_FUTURE_GP_COMPONENT_KEYS = (
    "affinity",
    "g1_potential",
    "blue",
    "pink",
    "white_skill",
    "white_generation",
    "unique",
)


def _future_gp_scoring_weights(config: dict[str, Any]) -> dict[str, float]:
    """Return the single source of truth for future-GP scoring weights.

    Local future-grandparent ranking, Transfer Helper and uma.moe pair ranking
    must all use ``mode_weights.future_grandparent``. Older releases exposed a
    second, independent ``uma_moe_pair.weights`` mapping; keeping two editable
    weight sets made online results silently ignore the active profile.
    """
    configured = _mode_weights(config, "future_grandparent")
    return {
        key: max(0.0, float(configured.get(key, 0.0)))
        for key in _FUTURE_GP_COMPONENT_KEYS
    }


def _future_gp_preselection_weights(config: dict[str, Any]) -> dict[str, float]:
    """Map the final future-GP profile to individual-candidate preselection."""
    weights = _future_gp_scoring_weights(config)
    return {
        "candidate_affinity": weights["affinity"],
        "g1_potential": weights["g1_potential"],
        "blue": weights["blue"],
        "pink": weights["pink"],
        "white_skill": weights["white_skill"],
        "white_generation": weights["white_generation"],
        "unique": weights["unique"],
    }


def _future_gp_pair_g1_score(final_parent_affinity: dict[str, Any]) -> float:
    """Score the usable G1 plan independently from base character affinity.

    A shared GP race can create two final-parent links, while a one-sided race
    creates one discounted link. The score is normalized against the maximum
    double-link bonus achievable with the configured race budget.
    """
    budget = max(0, int(final_parent_affinity.get("planned_g1_budget") or 0))
    bonus_per_link = max(0.0, float(final_parent_affinity.get("g1_bonus_per_link") or 0.0))
    maximum_bonus = budget * 2.0 * bonus_per_link
    if maximum_bonus <= 0:
        return 0.0
    planned_bonus = max(0.0, float(final_parent_affinity.get("planned_g1_bonus") or 0.0))
    return min(100.0, 100.0 * planned_bonus / maximum_bonus)


def _matching_factor_stars(
    member: dict[str, Any] | None,
    factor_name: str,
    *,
    include_lineage: bool = True,
) -> int:
    """Return known stars for one factor on a complete parent branch."""
    if not isinstance(member, dict):
        return 0
    members = _lineage_members(member) if include_lineage else [(member, "parent", "member")]
    total = 0
    for candidate, _position, _role in members:
        for factor in ((candidate.get("factors") or {}).get("by_type") or {}).get("red_aptitude", []):
            if str(factor.get("name") or "") == factor_name:
                total += max(0, int(factor.get("stars") or 0))
    return total


def _lineage_factor_type_stars(
    member: dict[str, Any] | None,
    factor_name: str,
    factor_type: str,
) -> int:
    """Sum a named factor's stars over a member and its two parents.

    Mirrors the uma.moe site's per-factor sliders, which filter on the
    lineage aggregate (Main + both parents), e.g. "Stamina 7-9★"."""
    if not isinstance(member, dict):
        return 0
    total = 0
    for candidate, _position, _role in _lineage_members(member):
        factors = ((candidate.get("factors") or {}).get("by_type") or {}).get(factor_type, [])
        for factor in factors:
            if str(factor.get("name") or "").casefold() == factor_name.casefold():
                total += max(0, int(factor.get("stars") or 0))
    return total


def _apply_lineage_factor_filters(
    candidates: list[dict[str, Any]],
    lineage_blue_filter: tuple[str, int] | None,
    lineage_pink_filter: tuple[str, int] | None,
    log: Callable[[str], None],
) -> list[dict[str, Any]]:
    """Post-fetch hard filter on lineage per-factor star sums (Main + parents).

    Applied locally on normalized candidates rather than pushed to the API:
    the only empirically confirmed per-factor parameter on /api/v3/search is
    main_parent_pink_sparks (Main only), and unknown parameters are unsafe to
    guess (see UmaMoeApiClient.search). Over-fetching compensates."""
    for label, ftype, spec in (
        ("Blue", "blue_stat", lineage_blue_filter),
        ("Pink", "red_aptitude", lineage_pink_filter),
    ):
        if not spec:
            continue
        name, minimum = spec
        name = str(name).strip()
        minimum = int(minimum)
        if name and minimum > 0:
            candidates = [
                candidate
                for candidate in candidates
                if _lineage_factor_type_stars(candidate, name, ftype) >= minimum
            ]
            log(
                f"Filtre lignée {label} {name} ≥ {minimum}★ (Main + parents) : "
                f"{len(candidates)} candidats restants."
            )
    return candidates


def _opposing_white_coverage(member: dict[str, Any] | None) -> dict[str, float]:
    """Approximate already-known white coverage for API/preselection guidance.

    This is deliberately not the final white score.  The exact pair evaluator
    still combines per-carrier probabilities.  Here we only need a stable soft
    signal so the API does not spend most of its limited sample on skills that
    the fixed branch already carries several times.
    """
    if not isinstance(member, dict):
        return {}
    coverage: dict[str, float] = {}
    for candidate, position, _role in _lineage_members(member):
        position_weight = 1.0 if position == "parent" else 0.5
        for factor in ((candidate.get("factors") or {}).get("by_type") or {}).get("white_skill", []):
            key = str(factor.get("name") or "").strip()
            if not key:
                continue
            stars = max(0, min(3, int(factor.get("stars") or 0)))
            coverage[key] = coverage.get(key, 0.0) + position_weight * stars / 3.0
    return coverage


def _planned_future_parent_g1(
    gp1: dict[str, Any],
    gp2: dict[str, Any],
    opposing_parent: dict[str, Any],
    *,
    budget: int,
    single_g1_weight: float,
) -> dict[str, Any]:
    """Build a deterministic projected G1 history for an untrained parent.

    Races overlapping two or three visible relatives are always selected first.
    Single-link races are retained only in proportion to the configured
    realization factor.  This turns the former fractional G1 heuristic into a
    concrete branch that the canonical six-member evaluator can consume.
    """
    capped_budget = max(0, min(int(budget), 40))
    single_weight = max(0.0, min(float(single_g1_weight), 1.0))
    sources = {
        "gp1": _member_g1(gp1),
        "gp2": _member_g1(gp2),
        "opposing_parent": _member_g1(opposing_parent),
    }
    races: dict[str, list[str]] = {}
    for source, names in sources.items():
        for name in names:
            races.setdefault(str(name), []).append(source)

    shared = sorted(
        ((name, owners) for name, owners in races.items() if len(owners) >= 2),
        key=lambda item: (-len(item[1]), item[0]),
    )
    selected_shared = shared[:capped_budget]
    remaining = max(0, capped_budget - len(selected_shared))

    single_buckets: dict[str, list[str]] = {key: [] for key in sources}
    for name, owners in races.items():
        if len(owners) == 1:
            single_buckets[owners[0]].append(name)
    for names in single_buckets.values():
        names.sort()
    single_available = sum(len(names) for names in single_buckets.values())
    single_target = min(remaining, int(round(single_available * single_weight)))
    selected_single: list[tuple[str, list[str]]] = []
    while len(selected_single) < single_target:
        progressed = False
        for owner in ("gp1", "gp2", "opposing_parent"):
            bucket = single_buckets[owner]
            if bucket and len(selected_single) < single_target:
                selected_single.append((bucket.pop(0), [owner]))
                progressed = True
        if not progressed:
            break

    selected = selected_shared + selected_single
    return {
        "names": [name for name, _owners in selected],
        "details": [
            {"name": name, "matching_members": owners, "link_count": len(owners)}
            for name, owners in selected
        ],
        "budget": capped_budget,
        "single_g1_weight": single_weight,
        "shared_selected": len(selected_shared),
        "single_available": single_available,
        "single_selected": len(selected_single),
        "selected_count": len(selected),
    }


def _project_future_parent_branch(
    target_parent: dict[str, Any],
    gp1: dict[str, Any],
    gp2: dict[str, Any],
    opposing_parent: dict[str, Any],
    *,
    planned_g1_budget: int,
    single_g1_weight: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Create the known portion of the future parent branch.

    The target parent's own Sparks do not exist yet and therefore remain empty.
    Its selected GP pair and projected G1 history are the only assumptions added.
    """
    g1_plan = _planned_future_parent_g1(
        gp1,
        gp2,
        opposing_parent,
        budget=planned_g1_budget,
        single_g1_weight=single_g1_weight,
    )
    projected = {
        **copy.deepcopy(target_parent),
        "trained_chara_id": "planned:future-parent",
        "rank_score": None,
        "rank": None,
        "factors": grouped_factors([]),
        "g1_wins": {
            "count": len(g1_plan["names"]),
            "names": list(g1_plan["names"]),
            "details": [],
        },
        "when_used_as_parent": {
            "grandparent_1": gp1,
            "grandparent_2": gp2,
        },
        "source_role": "projected_future_parent",
    }
    return projected, g1_plan


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
    opposing_parent: dict[str, Any] | None
    scoring_context: str
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


    def documented_parent_card_filter_keys(self) -> dict[str, str]:
        """Return exact /api/v3/search costume filter parameter names from OpenAPI.

        The uma.moe API has changed parameter naming over time. We therefore only
        send costume filters that are explicitly present in the live OpenAPI
        document, while retaining local filtering as the correctness fallback.
        """
        try:
            spec, _ = self.discover_openapi()
        except Exception:
            return {}
        path_item = (spec.get("paths") or {}).get("/api/v3/search") or {}
        operation = path_item.get("get") or {}
        params: list[dict[str, Any]] = []
        for source in (path_item.get("parameters") or [], operation.get("parameters") or []):
            if isinstance(source, list):
                params.extend(item for item in source if isinstance(item, dict))
            elif isinstance(source, dict):
                params.append(source)
        names: dict[str, str] = {}
        for raw in params:
            param = self._resolve_ref(spec, raw) or {}
            name = str(param.get("name") or "")
            lname = name.lower()
            description = str(param.get("description") or "").lower()
            haystack = f"{lname.replace('_', ' ')} {description}"
            if not name or "parent" not in haystack:
                continue
            if not any(token in haystack for token in ("card", "costume", "character card", "main parent")):
                continue
            is_exclusion = any(token in haystack for token in ("exclude", "excluded", "blacklist", "deny"))
            is_inclusion = any(token in haystack for token in ("include", "included", "whitelist", "allow", "main_parent"))
            if is_exclusion and "excluded" not in names:
                names["excluded"] = name
            elif is_inclusion and "allowed" not in names:
                names["allowed"] = name
        return names

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
            "retrieval_plan_applied": False,
        })
        return merged, operation

    def search_many_planned(
        self,
        *,
        base_filters: dict[str, Any] | None = None,
        retrieval_plan: dict[str, Any] | None = None,
        desired_candidates: int = 250,
        page_size: int = 100,
        logger: Callable[[str], None] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Fetch several complementary candidate cohorts under one global cap.

        A single white-sorted query can consume all 2,000 slots before a rare
        aptitude branch appears. Parent mode and contextual future-GP mode
        therefore reserve parts of the same cap for aptitude cohorts, then
        spend the remainder on the broad white-preferred search. Results are
        deduplicated before local scoring.
        """
        logger = logger or (lambda _message: None)
        desired = max(1, min(int(desired_candidates), MAX_FETCH_CANDIDATES))
        page_size = max(1, min(int(page_size), 100))
        cohorts = list((retrieval_plan or {}).get("cohorts") or [])
        if not cohorts:
            return self.search_many(
                filters=base_filters,
                desired_candidates=desired,
                page_size=page_size,
                logger=logger,
            )

        weighted = [
            cohort
            for cohort in cohorts
            if max(0.0, float(cohort.get("share") or 0.0)) > 0.0
        ]
        if not weighted:
            return self.search_many(
                filters=base_filters,
                desired_candidates=desired,
                page_size=page_size,
                logger=logger,
            )
        broad = next((item for item in weighted if item.get("kind") == "broad"), None)
        targeted = [item for item in weighted if item is not broad]
        total_share = sum(max(0.0, float(item.get("share") or 0.0)) for item in weighted) or 1.0

        merged_items: list[dict[str, Any]] = []
        seen: set[str] = set()
        strategy_diagnostics: list[dict[str, Any]] = []
        total_api_items = 0
        first_payload: dict[str, Any] | None = None

        def run_cohort(cohort: dict[str, Any], budget: int) -> None:
            nonlocal total_api_items, first_payload
            if budget <= 0:
                return
            name = str(cohort.get("name") or cohort.get("kind") or "cohort")
            filters = dict(base_filters or {})
            filters.update(dict(cohort.get("filters") or {}))
            logger(f"uma.moe : cohorte {name} — budget {budget} candidats…")
            try:
                payload, operation = self.search_many(
                    filters=filters,
                    desired_candidates=budget,
                    page_size=page_size,
                    logger=logger,
                )
            except UmaMoeError as exc:
                strategy_diagnostics.append({
                    "name": name,
                    "kind": cohort.get("kind"),
                    "budget": budget,
                    "filters": filters,
                    "received": 0,
                    "unique_added": 0,
                    "error": str(exc),
                })
                logger(f"uma.moe : cohorte {name} indisponible ({exc}); budget rendu à la recherche large.")
                return
            if first_payload is None:
                first_payload = dict(payload)
            items = list(payload.get("items") or []) if isinstance(payload, dict) else []
            total_api_items += len(items)
            added = 0
            for item in items:
                identity = self._record_identity(item)
                if identity in seen:
                    continue
                seen.add(identity)
                merged_items.append(item)
                added += 1
            strategy_diagnostics.append({
                "name": name,
                "kind": cohort.get("kind"),
                "share": round(float(cohort.get("share") or 0.0), 6),
                "budget": budget,
                "filters": filters,
                "received": len(items),
                "unique_added": added,
                "operation": operation,
            })

        allocated = 0
        for cohort in targeted:
            share = max(0.0, float(cohort.get("share") or 0.0)) / total_share
            budget = min(desired - allocated, max(1, int(round(desired * share))))
            if budget <= 0:
                break
            run_cohort(cohort, budget)
            allocated += budget

        broad_cohort = broad or {
            "name": "recherche large",
            "kind": "broad",
            "share": 0.0,
            "filters": {},
        }
        # A targeted cohort that returns fewer rows yields its unused allowance
        # to the broad cohort. The number of API records retained never exceeds
        # the same global 2,000-candidate cap.
        broad_budget = max(0, desired - total_api_items)
        run_cohort(broad_cohort, broad_budget)

        merged = first_payload or {}
        merged["items"] = merged_items[:desired]
        merged["page"] = 0
        merged["limit"] = page_size
        merged["requested_candidates"] = desired
        merged["unique_items"] = len(merged["items"])
        merged["retrieval_plan"] = retrieval_plan
        operation = {
            "method": "GET",
            "path": "/api/v3/search",
            "discovery_mode": "planned_complementary_cohorts",
            "retrieval_plan_applied": True,
            "requested_candidates": desired,
            "received_api_items": total_api_items,
            "received_candidates": len(merged["items"]),
            "page_size": page_size,
            "filters": base_filters or {},
            "retrieval_plan": retrieval_plan,
            "strategies": strategy_diagnostics,
        }
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


def _initial_star_target(base_rank: int, target_rank: int) -> int:
    """Stars needed for the best useful initial-rank step, capped at +4."""
    base = max(1, min(7, int(base_rank)))
    target = max(1, min(7, int(target_rank)))
    ranks = max(0, target - base)
    if ranks <= 0:
        return 0
    capped = min(4, ranks)
    return 1 + 3 * (capped - 1)


def resolve_lineage_pink_group_ids(
    master_path: str | Path,
    factor_names: Iterable[str],
) -> dict[str, int]:
    """Resolve target aptitude names to uma.moe lineage aggregate prefixes.

    The API's global ``pink_sparks`` field stores an aptitude's total stars over
    Main + GP1 + GP2. Turf 5★ is therefore 1105, while the underlying per-slot
    game factor is 1101/1102/1103. The aggregate prefix is ``factor_id // 10``.
    """
    requested = {str(name) for name in factor_names if name}
    if not requested:
        return {}
    resolver = MasterResolver(Path(master_path))
    try:
        result: dict[str, int] = {}
        for factor in resolver.factors.values():
            name = str(factor.get("name") or "")
            if (
                name in requested
                and factor.get("type") == "red_aptitude"
                and name not in result
            ):
                result[name] = int(factor["factor_id"]) // 10
        return result
    finally:
        resolver.close()


def build_parent_retrieval_plan(
    *,
    ace_target_aptitudes: dict[str, Any],
    surface: str,
    distance: str,
    config: dict[str, Any],
    pink_group_ids: dict[str, int],
    fixed_parent: dict[str, Any] | None = None,
    surface_cohort_enabled: bool | None = None,
) -> dict[str, Any]:
    """Build complementary API cohorts from the Ace's remaining aptitude deficit.

    When a local parent is locked, its complete three-member branch is already
    known.  Targeted API cohorts must therefore search only for the stars still
    missing from the distant branch.  In particular, a target surface already
    starting at A never receives an automatic Surface cohort.
    """
    parent_cfg = config.get("uma_moe_parent_search") or {}
    retrieval_cfg = parent_cfg.get("retrieval") or {}
    enabled = bool(retrieval_cfg.get("enabled", True))
    if not enabled:
        return {"enabled": False, "cohorts": []}

    aptitude_cfg = config.get("aptitude_inheritance") or {}
    surface_cfg = aptitude_cfg.get("surface") or {}
    minimum_surface_rank = int(surface_cfg.get("minimum_initial_rank", 6))
    preferred_surface_rank = int(surface_cfg.get("preferred_initial_rank", 7))
    surface_rank = int(((ace_target_aptitudes.get("surface") or {}).get("rank")) or 7)
    distance_rank = int(((ace_target_aptitudes.get("distance") or {}).get("rank")) or 7)
    divisor = max(1.0, float(retrieval_cfg.get("balanced_branch_divisor", 2.0)))
    surface_name = SURFACE_FACTOR_NAMES[surface]
    distance_name = DISTANCE_FACTOR_NAMES[distance]
    configured_surface_enabled = bool(
        retrieval_cfg.get("surface_cohort_enabled", True)
    )
    use_surface_cohort = configured_surface_enabled and (
        True if surface_cohort_enabled is None else bool(surface_cohort_enabled)
    )

    fixed_surface_stars = _matching_factor_stars(fixed_parent, surface_name)
    fixed_distance_stars = _matching_factor_stars(fixed_parent, distance_name)
    known_surface_rank = _initial_aptitude_rank(surface_rank, fixed_surface_stars)

    distance_total_target = (
        1 if distance_rank >= 7 else _initial_star_target(distance_rank, 7)
    )
    remaining_distance_stars = max(0, distance_total_target - fixed_distance_stars)
    distance_branch_minimum = max(
        1,
        min(
            9,
            (
                remaining_distance_stars
                if fixed_parent is not None
                else int(math.ceil(distance_total_target / divisor))
            ),
        ),
    ) if remaining_distance_stars > 0 else 0

    maximum_surface_rank = min(7, surface_rank + 4)
    if surface_rank >= preferred_surface_rank:
        surface_total_target = 0
    elif maximum_surface_rank >= preferred_surface_rank:
        surface_total_target = _initial_star_target(
            surface_rank, preferred_surface_rank
        )
    else:
        surface_total_target = _initial_star_target(
            surface_rank, minimum_surface_rank
        )
    remaining_surface_stars = max(0, surface_total_target - fixed_surface_stars)

    if known_surface_rank >= preferred_surface_rank:
        surface_share = float(retrieval_cfg.get("surface_share_at_preferred", 0.0))
        if fixed_parent is not None:
            # A locked branch that already starts the target surface at A fully
            # covers the automatic Surface search, regardless of a legacy
            # non-zero preferred-rank share.
            surface_share = 0.0
    elif known_surface_rank >= minimum_surface_rank:
        surface_share = float(retrieval_cfg.get("surface_share_at_minimum", 0.20))
    else:
        surface_share = float(
            retrieval_cfg.get("surface_share_below_minimum", 0.40)
        )
    if not use_surface_cohort or remaining_surface_stars <= 0:
        surface_share = 0.0
    surface_branch_minimum = (
        max(
            1,
            min(
                9,
                (
                    remaining_surface_stars
                    if fixed_parent is not None
                    else int(math.ceil(surface_total_target / divisor))
                ),
            ),
        )
        if remaining_surface_stars > 0
        else 0
    )

    distance_share = (
        max(0.0, float(retrieval_cfg.get("distance_share", 0.45)))
        if remaining_distance_stars > 0
        else 0.0
    )
    surface_share = max(0.0, surface_share)
    broad_minimum = max(0.0, float(retrieval_cfg.get("broad_minimum_share", 0.15)))
    if distance_share + surface_share > 1.0 - broad_minimum:
        scale = (1.0 - broad_minimum) / max(0.000001, distance_share + surface_share)
        distance_share *= scale
        surface_share *= scale
    broad_share = max(broad_minimum, 1.0 - distance_share - surface_share)

    cohorts: list[dict[str, Any]] = []
    distance_prefix = pink_group_ids.get(distance_name)
    if distance_share > 0 and distance_prefix:
        cohorts.append({
            "name": f"distance {distance_name} >= {distance_branch_minimum}★",
            "kind": "distance",
            "share": round(distance_share, 8),
            "filters": {
                "pink_sparks": [
                    distance_prefix * 10 + stars
                    for stars in range(distance_branch_minimum, 10)
                ]
            },
            "target_factor": distance_name,
            "target_branch_stars": distance_branch_minimum,
        })
    else:
        broad_share += distance_share

    surface_prefix = pink_group_ids.get(surface_name)
    if surface_share > 0 and surface_branch_minimum > 0 and surface_prefix:
        cohorts.append({
            "name": f"surface {surface_name} >= {surface_branch_minimum}★",
            "kind": "surface",
            "share": round(surface_share, 8),
            "filters": {
                "pink_sparks": [
                    surface_prefix * 10 + stars
                    for stars in range(surface_branch_minimum, 10)
                ]
            },
            "target_factor": surface_name,
            "target_branch_stars": surface_branch_minimum,
        })
    else:
        broad_share += surface_share
    cohorts.append({
        "name": "recherche large / whites",
        "kind": "broad",
        "share": round(broad_share, 8),
        "filters": {},
    })

    total_share = sum(float(item["share"]) for item in cohorts) or 1.0
    for cohort in cohorts:
        cohort["share"] = round(float(cohort["share"]) / total_share, 8)
    return {
        "enabled": True,
        "policy": (
            "Separate distance, target-surface and broad cohorts are merged under "
            "the same global fetch cap; this is sampling guidance, not a final hard filter."
        ),
        "surface": {
            "factor": surface_name,
            "base_rank": surface_rank,
            "minimum_rank": minimum_surface_rank,
            "preferred_rank": preferred_surface_rank,
            "final_pair_star_target": surface_total_target,
            "known_locked_parent_stars": fixed_surface_stars,
            "remaining_stars": remaining_surface_stars,
            "initial_rank_with_locked_parent": known_surface_rank,
            "cohort_enabled": use_surface_cohort,
            "balanced_remote_branch_minimum": surface_branch_minimum,
        },
        "distance": {
            "factor": distance_name,
            "base_rank": distance_rank,
            "final_pair_star_target": distance_total_target,
            "known_locked_parent_stars": fixed_distance_stars,
            "remaining_stars": remaining_distance_stars,
            "balanced_remote_branch_minimum": distance_branch_minimum,
        },
        "cohorts": cohorts,
    }


def build_contextual_grandparent_retrieval_plan(
    *,
    ace_target_aptitudes: dict[str, Any],
    opposing_parent: dict[str, Any],
    surface: str,
    distance: str,
    config: dict[str, Any],
    main_pink_factor_ids: dict[str, list[int]],
    fixed_grandparent: dict[str, Any] | None = None,
    surface_cohort_enabled: bool | None = None,
) -> dict[str, Any]:
    """Allocate GP API cohorts from the deficit left by a fixed parent branch.

    Unlike parent-mode cohorts, a returned Main is itself the future GP.  The
    targeted query must therefore use ``main_parent_pink_sparks`` rather than
    aggregate lineage stars.  Shares only guide sampling; the final result is
    still evaluated on the complete projected six-member lineage.
    """
    parent_cfg = config.get("uma_moe_parent_search") or {}
    retrieval_cfg = parent_cfg.get("retrieval") or {}
    if not bool(retrieval_cfg.get("enabled", True)):
        return {"enabled": False, "cohorts": []}

    aptitude_cfg = config.get("aptitude_inheritance") or {}
    surface_cfg = aptitude_cfg.get("surface") or {}
    minimum_surface_rank = int(surface_cfg.get("minimum_initial_rank", 6))
    preferred_surface_rank = int(surface_cfg.get("preferred_initial_rank", 7))
    surface_rank = int(((ace_target_aptitudes.get("surface") or {}).get("rank")) or 7)
    distance_rank = int(((ace_target_aptitudes.get("distance") or {}).get("rank")) or 7)
    surface_name = SURFACE_FACTOR_NAMES[surface]
    distance_name = DISTANCE_FACTOR_NAMES[distance]
    configured_surface_enabled = bool(
        retrieval_cfg.get("surface_cohort_enabled", True)
    )
    use_surface_cohort = configured_surface_enabled and (
        True if surface_cohort_enabled is None else bool(surface_cohort_enabled)
    )

    maximum_surface_rank = min(7, surface_rank + 4)
    if surface_rank >= preferred_surface_rank:
        surface_total_target = 0
        surface_base_share = float(retrieval_cfg.get("surface_share_at_preferred", 0.0))
    elif maximum_surface_rank >= preferred_surface_rank:
        surface_total_target = _initial_star_target(
            surface_rank, preferred_surface_rank
        )
        surface_base_share = float(
            retrieval_cfg.get(
                "surface_share_at_minimum"
                if surface_rank >= minimum_surface_rank
                else "surface_share_below_minimum",
                0.20 if surface_rank >= minimum_surface_rank else 0.40,
            )
        )
    else:
        surface_total_target = _initial_star_target(surface_rank, minimum_surface_rank)
        surface_base_share = float(retrieval_cfg.get("surface_share_below_minimum", 0.40))
    opposing_surface_stars = _matching_factor_stars(opposing_parent, surface_name)
    locked_local_surface_stars = _matching_factor_stars(
        fixed_grandparent, surface_name, include_lineage=False
    )
    fixed_surface_stars = opposing_surface_stars + locked_local_surface_stars
    remaining_surface_stars = max(0, surface_total_target - fixed_surface_stars)
    known_surface_rank = _initial_aptitude_rank(surface_rank, fixed_surface_stars)
    surface_need = (
        min(1.0, remaining_surface_stars / max(1.0, float(surface_total_target)))
        if surface_total_target > 0 else 0.0
    )
    if known_surface_rank >= preferred_surface_rank:
        surface_need = 0.0

    # Initial-A is a hard prerequisite when the Ace starts below A.  Once that
    # is covered, a configurable six-star reference keeps enough distance
    # carriers in the sample for the practical P(S) target instead of reducing
    # the search to a single matching factor.
    contextual_distance_target = max(
        1,
        min(18, int(retrieval_cfg.get("contextual_distance_star_target", 6))),
    )
    distance_initial_target = (
        1 if distance_rank >= 7 else _initial_star_target(distance_rank, 7)
    )
    distance_total_target = max(distance_initial_target, contextual_distance_target)
    opposing_distance_stars = _matching_factor_stars(opposing_parent, distance_name)
    locked_local_distance_stars = _matching_factor_stars(
        fixed_grandparent, distance_name, include_lineage=False
    )
    fixed_distance_stars = opposing_distance_stars + locked_local_distance_stars
    remaining_distance_stars = max(0, distance_total_target - fixed_distance_stars)
    distance_need = min(
        1.0,
        remaining_distance_stars / max(1.0, float(distance_total_target)),
    )

    base_distance_share = max(0.0, float(retrieval_cfg.get("distance_share", 0.45)))
    base_surface_share = (
        max(0.0, surface_base_share) if use_surface_cohort else 0.0
    )
    broad_minimum = max(0.0, float(retrieval_cfg.get("broad_minimum_share", 0.15)))
    freed_surface = base_surface_share * (1.0 - surface_need)
    distance_floor = max(
        0.0, min(1.0, float(retrieval_cfg.get("contextual_distance_need_floor", 0.25)))
    )
    distance_demand = max(distance_floor, distance_need)
    distance_share = base_distance_share * distance_demand
    distance_share += (
        freed_surface
        * max(0.0, min(1.0, float(retrieval_cfg.get("contextual_surface_reallocation_to_distance", 0.70))))
        * distance_demand
    )
    surface_share = base_surface_share * surface_need
    if distance_share + surface_share > 1.0 - broad_minimum:
        scale = (1.0 - broad_minimum) / max(0.000001, distance_share + surface_share)
        distance_share *= scale
        surface_share *= scale
    broad_share = max(broad_minimum, 1.0 - distance_share - surface_share)

    def targeted_ids(name: str, minimum_stars: int) -> list[int]:
        values = []
        for raw in main_pink_factor_ids.get(name, []):
            try:
                factor_id = int(raw)
            except (TypeError, ValueError):
                continue
            if factor_id % 10 >= minimum_stars:
                values.append(factor_id)
        return sorted(set(values))

    cohorts: list[dict[str, Any]] = []
    distance_minimum = max(
        1,
        min(
            3,
            (
                remaining_distance_stars
                if fixed_grandparent is not None
                else int(math.ceil(remaining_distance_stars / 2.0))
            ),
        ),
    )
    distance_ids = targeted_ids(distance_name, distance_minimum)
    if distance_share > 0 and remaining_distance_stars > 0 and distance_ids:
        cohorts.append({
            "name": f"GP distance {distance_name} >= {distance_minimum}★",
            "kind": "distance",
            "share": round(distance_share, 8),
            "filters": {"main_parent_pink_sparks": distance_ids},
            "target_factor": distance_name,
            "target_main_stars": distance_minimum,
        })
    else:
        broad_share += distance_share

    surface_minimum = max(
        1,
        min(
            3,
            (
                remaining_surface_stars
                if fixed_grandparent is not None
                else int(math.ceil(remaining_surface_stars / 2.0))
            ),
        ),
    )
    surface_ids = targeted_ids(surface_name, surface_minimum)
    if surface_share > 0 and remaining_surface_stars > 0 and surface_ids:
        cohorts.append({
            "name": f"GP surface {surface_name} >= {surface_minimum}★",
            "kind": "surface",
            "share": round(surface_share, 8),
            "filters": {"main_parent_pink_sparks": surface_ids},
            "target_factor": surface_name,
            "target_main_stars": surface_minimum,
        })
    else:
        broad_share += surface_share
    cohorts.append({
        "name": "recherche complémentaire / whites",
        "kind": "broad",
        "share": round(broad_share, 8),
        "filters": {},
    })
    total_share = sum(float(item["share"]) for item in cohorts) or 1.0
    for cohort in cohorts:
        cohort["share"] = round(float(cohort["share"]) / total_share, 8)
    return {
        "enabled": True,
        "contextual_opposing_parent": True,
        "policy": (
            "Distance/surface cohorts target only the future GP Main and are reduced by "
            "the known opposing branch plus any locked local GP. The local GP contributes "
            "only its own factors. Freed surface budget is mostly reassigned to distance; "
            "broad/white search keeps the remainder."
        ),
        "opposing_parent": _identity(opposing_parent),
        "surface": {
            "factor": surface_name,
            "base_rank": surface_rank,
            "minimum_rank": minimum_surface_rank,
            "preferred_rank": preferred_surface_rank,
            "target_stars": surface_total_target,
            "known_opposing_stars": opposing_surface_stars,
            "known_locked_local_stars": locked_local_surface_stars,
            "known_total_stars": fixed_surface_stars,
            "remaining_stars": remaining_surface_stars,
            "initial_rank_with_known_branches": known_surface_rank,
            "cohort_enabled": use_surface_cohort,
            "need_ratio": round(surface_need, 6),
        },
        "distance": {
            "factor": distance_name,
            "base_rank": distance_rank,
            "target_stars": distance_total_target,
            "known_opposing_stars": opposing_distance_stars,
            "known_locked_local_stars": locked_local_distance_stars,
            "known_total_stars": fixed_distance_stars,
            "remaining_stars": remaining_distance_stars,
            "need_ratio": round(distance_need, 6),
        },
        "cohorts": cohorts,
    }


def _prune_locked_surface_hard_filter(
    hard_filters: list[dict[str, Any]],
    retrieval_plan: dict[str, Any],
    *,
    surface_name: str,
    fixed_local_parent: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Drop a redundant remote-Main Surface constraint after locked coverage.

    A persisted explicit Surface filter used to survive independently from the
    automatic cohort plan.  That could still force a Dirt/Turf-only API search
    even when the locked local branch already started the Ace at A.  Explicit
    filters remain untouched in every other case.
    """
    if fixed_local_parent is None:
        return list(hard_filters), []
    surface_plan = retrieval_plan.get("surface") or {}
    try:
        preferred_rank = int(surface_plan.get("preferred_rank") or 7)
        known_rank = int(
            surface_plan.get("initial_rank_with_locked_parent")
            or surface_plan.get("initial_rank_with_known_branches")
            or 0
        )
    except (TypeError, ValueError):
        return list(hard_filters), []
    if known_rank < preferred_rank:
        return list(hard_filters), []
    kept: list[dict[str, Any]] = []
    suppressed: list[dict[str, Any]] = []
    for item in hard_filters:
        if str(item.get("factor") or "") == surface_name:
            suppressed.append({
                **item,
                "reason": "covered_at_preferred_rank_by_locked_local_context",
            })
        else:
            kept.append(item)
    return kept, suppressed


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
    ace_card_id: int | None = None,
    search_mode: str = "grandparent",
    opposing_parent: dict[str, Any] | None = None,
    fixed_local_parent: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Build a broad UQL with optional user-selected hard constraints.

    White-skill clauses are primarily sorting/prioritisation helpers. Pink and blue
    factors remain open by default; the user may explicitly require the target
    surface, distance or style on the online Main (the distant candidate). Numeric
    lineage-quality thresholds are emitted as documented ``/api/v3/search``
    parameters rather than invented free-text UQL predicates.
    """
    options = dict(options or {})
    use_optional_whites = bool(options.get("prefer_profile_whites", True))
    use_lineage_whites = bool(options.get("prefer_lineage_whites", True))
    use_surface_retrieval = bool(options.get("enable_surface_retrieval", True))
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
    opposing_coverage = _opposing_white_coverage(opposing_parent)
    coverage_decay = max(
        0.0,
        float(
            (((config.get("uma_moe_pair") or {}).get("contextual_opponent") or {}).get(
                "white_retrieval_coverage_decay", 0.75
            ))
        ),
    )
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
        known_coverage = max(0.0, float(opposing_coverage.get(name, 0.0)))
        retrieval_weight = weight / (1.0 + coverage_decay * known_coverage)
        ranked.append({
            "catalog_key": str(key),
            "name": name,
            "weight": round(retrieval_weight, 6),
            "profile_weight": round(weight, 6),
            "opposing_parent_coverage": round(known_coverage, 6),
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
    if options.get("require_main_surface"):
        requested_factor_names.append(SURFACE_FACTOR_NAMES[surface])
    if options.get("require_main_distance"):
        requested_factor_names.append(DISTANCE_FACTOR_NAMES[distance])
    if options.get("require_main_style"):
        requested_factor_names.append(STYLE_FACTOR_NAMES[style])
    # Preserve order defensively even though the three target dimensions are distinct.
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
    ace_target_aptitudes: dict[str, Any] = {}
    retrieval_plan: dict[str, Any] = {"enabled": False, "cohorts": []}
    suppressed_hard_filters: list[dict[str, Any]] = []
    if master_path and ace_card_id is not None and (
        search_mode == "parent" or opposing_parent is not None
    ):
        affinity_resolver = AffinityResolver(master_path)
        try:
            ace_target_aptitudes = affinity_resolver.ace_details(
                int(ace_card_id), surface, distance, style
            )["target_aptitudes"]
        finally:
            affinity_resolver.close()
        target_pinks = [SURFACE_FACTOR_NAMES[surface], DISTANCE_FACTOR_NAMES[distance]]
        if search_mode == "parent":
            pink_group_ids = resolve_lineage_pink_group_ids(master_path, target_pinks)
            retrieval_plan = build_parent_retrieval_plan(
                ace_target_aptitudes=ace_target_aptitudes,
                surface=surface,
                distance=distance,
                config=config,
                pink_group_ids=pink_group_ids,
                fixed_parent=fixed_local_parent,
                surface_cohort_enabled=use_surface_retrieval,
            )
        elif opposing_parent is not None:
            main_factor_ids = {
                name: resolve_main_pink_factor_ids(
                    master_path,
                    [{"factor": name, "minimum_stars": 1}],
                )
                for name in target_pinks
            }
            retrieval_plan = build_contextual_grandparent_retrieval_plan(
                ace_target_aptitudes=ace_target_aptitudes,
                opposing_parent=opposing_parent,
                surface=surface,
                distance=distance,
                config=config,
                main_pink_factor_ids=main_factor_ids,
                fixed_grandparent=fixed_local_parent,
                surface_cohort_enabled=use_surface_retrieval,
            )
    hard_filters, suppressed_hard_filters = _prune_locked_surface_hard_filter(
        hard_filters,
        retrieval_plan,
        surface_name=SURFACE_FACTOR_NAMES[surface],
        fixed_local_parent=fixed_local_parent,
    )
    if suppressed_hard_filters:
        clauses = list(soft_clauses) + [item["uql"] for item in hard_filters]
        uql = " and\n".join(clauses)
        simple_parts = list(soft_clauses[:1]) + [
            item["uql"] for item in hard_filters
        ]
        simple_uql = " and\n".join(simple_parts)
        main_parent_pink_sparks = (
            resolve_main_pink_factor_ids(master_path, hard_filters)
            if master_path and hard_filters
            else []
        )
    quality_filters: dict[str, int] = {}
    for key, maximum in (
        ("min_blue_stars_sum", 9),
        ("min_white_count", 60),
        ("min_white_stars_sum", 99),
    ):
        try:
            value = max(0, min(int(options.get(key, 0) or 0), maximum))
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            quality_filters[key] = value

    search_filters: dict[str, Any] = {
        "main_parent_pink_sparks": main_parent_pink_sparks,
        "optional_main_white_factors": optional_main_white_factors,
        "optional_white_sparks": optional_white_sparks,
    }
    search_filters.update(quality_filters)
    if (
        opposing_parent is not None
        and main_parent_pink_sparks
        and retrieval_plan.get("enabled")
    ):
        retrieval_plan = {
            **retrieval_plan,
            "enabled": False,
            "disabled_reason": (
                "An explicit hard Main-pink constraint already occupies the API's "
                "main_parent_pink_sparks parameter; contextual cohorts cannot express an "
                "additional independent Main-pink condition safely."
            ),
        }

    return uql, {
        "generator_version": 7,
        "search_mode": search_mode,
        "profile": {"surface": surface, "distance": distance, "style": style},
        "ace_target_aptitudes": ace_target_aptitudes,
        "weight_source": source_label,
        "course_key": course_key,
        "course_conditions": {key: sorted(values) for key, values in normalized_conditions.items()},
        "options": options,
        "optional_skills": optional if use_optional_whites else [],
        "lineage_skills": lineage if use_lineage_whites else [],
        "hard_filters": hard_filters,
        "suppressed_hard_filters": suppressed_hard_filters,
        "quality_filters": quality_filters,
        "simple_fallback_uql": simple_uql,
        "weight_diagnostics": diagnostics,
        "opposing_parent_context": (
            {
                "identity": _identity(opposing_parent),
                "white_coverage": opposing_coverage,
                "white_retrieval_coverage_decay": coverage_decay,
                "policy": (
                    "Known whites are softly de-prioritized for retrieval only; "
                    "the final six-member scorer still values repeated copies through exact cumulative probability."
                ),
            }
            if opposing_parent is not None else None
        ),
        "fixed_local_context": (
            {
                "identity": _identity(fixed_local_parent),
                "role": (
                    "complete_locked_parent_branch"
                    if search_mode == "parent"
                    else "locked_local_grandparent_only"
                ),
                "policy": (
                    "The locked local parent contributes its complete branch to the known aptitude coverage."
                    if search_mode == "parent"
                    else "A locked local GP contributes only its own factors; its ancestors are outside the final six-member lineage."
                ),
            }
            if fixed_local_parent is not None else None
        ),
        "search_filters": search_filters,
        "retrieval_plan": retrieval_plan,
        "policy": {
            "blue_filter": quality_filters.get("min_blue_stars_sum"),
            "pink_filter": hard_filters or None,
            "lineage_quality_filters": quality_filters or None,
            "reason": (
                "Explicit Main pink constraints and non-zero lineage-quality minima remain "
                "hard. Parent mode samples complete-branch aptitude cohorts. Contextual GP mode "
                "samples only the remaining Main-GP deficits before exact projected pair scoring."
            ),
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

    # This key holds diagnostic metadata the app itself injects (retrieval
    # strategy, and — for contextual GP searches — a full resolved copy of
    # the opposing-parent branch with its own factor lists). It is never
    # part of the uma.moe API response and must not be mistaken for one:
    # its small, uniformly well-formed factor-object lists can outscore the
    # real (but more heterogeneous) candidate list in the heuristic below.
    METADATA_KEYS_TO_SKIP = {"retrieval_plan"}

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
                if str(key).lower() in METADATA_KEYS_TO_SKIP:
                    continue
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


def _empty_candidates_diagnostic(records: list[dict[str, Any]]) -> str:
    """Build a short, PII-free diagnostic appended when zero candidates normalize.

    Surfaces the record count and the top-level key names of the first record
    (structure only, no values) so a schema change on the uma.moe side can be
    spotted from the log without needing to share the raw response.
    """
    if not records:
        return " Diagnostic : la réponse ne contient aucun enregistrement détectable."
    sample_keys = sorted(str(key) for key in records[0].keys())[:25]
    return (
        f" Diagnostic : {len(records)} enregistrement(s) détecté(s), 0 exploitable. "
        f"Clés du premier enregistrement : {', '.join(sample_keys) or '(aucune)'}."
    )


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


def extract_opposing_parent_candidates(
    master_path: str | Path,
    payload: Any,
) -> list[dict[str, Any]]:
    """Extract selectable complete parent branches from supported JSON files.

    Supported inputs include this application's parent-pair result JSON, one
    already-normalized member object, and a raw uma.moe API response.  Only
    branches containing the parent plus both visible grandparents are returned.
    """
    candidates: list[dict[str, Any]] = []

    def add(member: Any) -> None:
        if not isinstance(member, dict):
            return
        if not _has_complete_parent_branch(member):
            return
        if int(member.get("card_id") or 0) <= 0 or int(member.get("chara_id") or 0) <= 0:
            return
        if not isinstance(member.get("factors"), dict):
            return
        candidates.append(copy.deepcopy(member))

    add(payload)
    if isinstance(payload, dict):
        add(payload.get("fixed_parent"))
        for row in payload.get("results") or []:
            if not isinstance(row, dict):
                continue
            for key in ("candidate", "fixed_parent", "parent_1", "parent_2"):
                add(row.get(key))

    if not candidates:
        normalizer = OnlineRecordNormalizer(master_path)
        try:
            normalized, _diagnostics = normalizer.normalize_records(payload)
        finally:
            normalizer.close()
        for member in normalized:
            add(member)

    unique: dict[str, dict[str, Any]] = {}
    for member in candidates:
        lineage = member.get("when_used_as_parent") or {}
        signature = [
            member.get("trained_chara_id"),
            member.get("card_id"),
            (member.get("online") or {}).get("inheritance_id"),
            sorted(
                (factor.get("name"), int(factor.get("stars") or 0))
                for factor in (member.get("factors") or {}).get("all", [])
                if isinstance(factor, dict)
            ),
            int((lineage.get("grandparent_1") or {}).get("card_id") or 0),
            int((lineage.get("grandparent_2") or {}).get("card_id") or 0),
        ]
        key = hashlib.sha256(
            json.dumps(signature, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        unique[key] = member
    return list(unique.values())


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

    # The selected GP1/GP2 remain visible grandparents in the final Ace lineage.
    # Their direct pink/white inheritance odds therefore use their projected
    # final GP coefficients, not the compatibility of the intermediate run that
    # creates the target parent. Common races benefit both GP links; one-sided
    # races are distributed proportionally across the available unique pools.
    if single_pool_count > 0:
        fixed_single_share = single_count * len(fixed_only) / single_pool_count
        candidate_single_share = single_count * len(candidate_only) / single_pool_count
    else:
        fixed_single_share = 0.0
        candidate_single_share = 0.0
    fixed_projected_g1_links = double_count + fixed_single_share * single_weight
    candidate_projected_g1_links = double_count + candidate_single_share * single_weight
    fixed_projected_inheritance = fixed_triple + fixed_projected_g1_links * g1_bonus_value
    candidate_projected_inheritance = candidate_triple + candidate_projected_g1_links * g1_bonus_value

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
        "projected_gp1_inheritance_modifier": {
            "base_triple": fixed_triple,
            "planned_common_links": double_count,
            "planned_single_links_weighted": fixed_single_share * single_weight,
            "total": fixed_projected_inheritance,
        },
        "projected_gp2_inheritance_modifier": {
            "base_triple": candidate_triple,
            "planned_common_links": double_count,
            "planned_single_links_weighted": candidate_single_share * single_weight,
            "total": candidate_projected_inheritance,
        },
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
        "rank", "score", "scoring_context", "opposing_parent",
        "local_id", "local_candidate", "local_rank_score",
        "friend_code", "trainer_name", "candidate", "rank_score",
        "final_parent_base", "planned_g1_budget", "planned_g1_bonus",
        "planned_g1_bonus_exact", "single_g1_weight", "final_parent_potential",
        "affinity_component", "g1_potential_component", "production_run_affinity",
        "production_run_scored_value", "common_gp_g1_count", "local_only_g1_count",
        "remote_only_g1_count", "common_gp_g1_races", "local_only_g1_races",
        "remote_only_g1_races", "blue", "pink", "white", "white_generation",
        "unique", "candidate_g1",
        "final_pair_affinity_total", "projected_parent_g1_count",
        "distance_status", "distance_stars", "distance_probability_s",
        "surface_status", "surface_stars", "surface_probability_a",
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
    race_factor_catalog_path: str | Path | None = None,
    ace_card_id: int,
    target_parent_card_id: int,
    fixed_grandparent_trained_id: int | None = None,
    opposing_parent_trained_id: int | None = None,
    opposing_parent: dict[str, Any] | None = None,
    exhaustive_pairs: bool = False,
    local_pool_size: int = 100,
    remote_pool_size: int = 100,
    surface: str,
    distance: str,
    style: str,
    raw_payload: Any = None,
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
    local_pair_mode: bool = False,
    lineage_blue_filter: tuple[str, int] | None = None,
    lineage_pink_filter: tuple[str, int] | None = None,
    logger: Callable[[str], None] | None = None,
) -> OnlineSearchResult:
    log = logger or (lambda _message: None)
    master_path = Path(master_path).resolve()
    linked_veterans_path = Path(linked_veterans_path).resolve()
    manual_weights_path = Path(manual_weights_path).resolve()
    skill_catalog_path = Path(skill_catalog_path).resolve()
    race_factor_catalog_path = Path(race_factor_catalog_path).resolve() if race_factor_catalog_path else None
    output_dir = Path(output_dir).resolve()
    course_weights_path = Path(course_weights_path).resolve() if course_weights_path else None
    scoring_config_path = Path(scoring_config_path).resolve() if scoring_config_path else Path(__file__).resolve().parent / "default_parent_scoring.json"
    output_dir.mkdir(parents=True, exist_ok=True)

    linked = _read_json(linked_veterans_path)
    weights = _read_json(manual_weights_path)
    skill_catalog = _read_json(skill_catalog_path)
    race_catalog = _read_json(race_factor_catalog_path) if race_factor_catalog_path and race_factor_catalog_path.is_file() else {"race_factors": []}
    race_skills = _race_skill_map(race_catalog)
    course_payload = _read_json(course_weights_path) if course_weights_path and course_weights_path.is_file() else None
    config = _read_json(scoring_config_path)
    veterans = list(linked.get("veterans") or [])

    contextual_opposing_parent: dict[str, Any] | None = None
    if opposing_parent is not None:
        contextual_opposing_parent = copy.deepcopy(opposing_parent)
    elif opposing_parent_trained_id is not None:
        contextual_opposing_parent = next(
            (
                veteran
                for veteran in veterans
                if int(veteran.get("trained_chara_id") or 0)
                == int(opposing_parent_trained_id)
            ),
            None,
        )
        if contextual_opposing_parent is None:
            raise UmaMoeError(
                f"Parent opposé local introuvable : #{opposing_parent_trained_id}"
            )

    fixed: dict[str, Any] | None = None
    if fixed_grandparent_trained_id is not None:
        fixed = next(
            (veteran for veteran in veterans if int(veteran.get("trained_chara_id") or 0) == int(fixed_grandparent_trained_id)),
            None,
        )
        if fixed is None and not exhaustive_pairs:
            raise UmaMoeError(f"Grand-parent local introuvable : #{fixed_grandparent_trained_id}")

    if local_pair_mode:
        online_candidates = [copy.deepcopy(veteran) for veteran in veterans]
        for member in online_candidates:
            online_meta = dict(member.get("online") or {})
            online_meta.setdefault("local_pool", True)
            member["online"] = online_meta
        normalization_diag: dict[str, Any] = {
            "mode": "local_second_pool",
            "count": len(online_candidates),
        }
        log(f"Second pool : {len(online_candidates)} GP locaux (aucune requête uma.moe).")
    else:
        normalizer = OnlineRecordNormalizer(master_path)
        try:
            online_candidates, normalization_diag = normalizer.normalize_records(raw_payload)
        finally:
            normalizer.close()
        if not online_candidates:
            raise UmaMoeError(
                "La réponse uma.moe ne contient aucun candidat avec costume/factors exploitables."
                + _empty_candidates_diagnostic(_extract_record_list(raw_payload))
            )

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
                f"({filter_text}). L'API a peut-être ignoré le filtre strict ou le pool demandé est trop petit."
            )
    else:
        normalization_diag["strict_main_factor_filters"] = []
        normalization_diag["pre_filter_count"] = unfiltered_online_count
        normalization_diag["post_filter_count"] = unfiltered_online_count
    if not local_pair_mode:
        log(f"uma.moe : {len(online_candidates)} candidats distants normalisés.")
    online_candidates = _apply_lineage_factor_filters(
        online_candidates, lineage_blue_filter, lineage_pink_filter, log
    )
    if not online_candidates:
        raise UmaMoeError(
            "Aucun candidat ne respecte les filtres lignée demandés. "
            "Assouplis le minimum d'étoiles ou augmente la limite de récupération API."
        )
    normalization_diag["lineage_filters"] = {
        "blue": list(lineage_blue_filter) if lineage_blue_filter else None,
        "pink": list(lineage_pink_filter) if lineage_pink_filter else None,
        "post_lineage_filter_count": len(online_candidates),
    }

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
        mode_weights = _future_gp_scoring_weights(config)
        preselection_weights = _future_gp_preselection_weights(config)
        pair_weights = _mode_weights(config, "parent_pair")
        contextual_mode = contextual_opposing_parent is not None
        effective_preselection_weights = dict(preselection_weights)
        if contextual_mode:
            contextual_settings = online_cfg.get("contextual_opponent") or {}
            effective_preselection_weights = {
                "candidate_affinity": float(
                    contextual_settings.get("preselection_affinity_weight", 0.01)
                ),
                "g1_potential": float(
                    contextual_settings.get("preselection_g1_weight", 0.01)
                ),
                "blue": float(pair_weights.get("blue", 0.0)),
                "pink": sum(
                    float(pair_weights.get(key, 0.0))
                    for key in ("distance_s", "surface_aptitude", "pink_other")
                ),
                "white_skill": float(pair_weights.get("white_skill", 0.0)),
                "white_generation": float(
                    contextual_settings.get(
                        "preselection_white_generation_weight", 0.02
                    )
                ),
                "unique": float(pair_weights.get("unique", 0.0)),
            }
        opposing_branch: dict[str, Any] | None = None
        if contextual_opposing_parent is not None:
            if not _has_complete_parent_branch(contextual_opposing_parent):
                raise UmaMoeError(
                    "Le parent opposé doit contenir sa branche complète "
                    "(parent + deux grands-parents)."
                )
            opposing_chara = int(contextual_opposing_parent.get("chara_id") or 0)
            if opposing_chara <= 0:
                raise UmaMoeError("Le parent opposé n'a pas pu être résolu.")
            if opposing_chara == ace_chara:
                raise UmaMoeError("L'Ace ne peut pas être utilisé comme parent opposé.")
            if opposing_chara == target_parent_chara:
                raise UmaMoeError(
                    "Le parent opposé et le parent à produire doivent être deux Umas différentes."
                )
            opposing_branch = evaluate_parent_branch(
                resolver,
                ace,
                contextual_opposing_parent,
                surface=surface,
                distance=distance,
                style=style,
                weight_lookup=weight_lookup,
                race_skills=race_skills,
                config=config,
                g1_bonus_value=int((config.get("affinity") or {}).get("g1_common_bonus", 3)),
            )
            log(
                "Contexte final activé : parent opposé "
                f"{contextual_opposing_parent.get('card_name') or contextual_opposing_parent.get('uma_name')}. "
                "Les paires de GP seront classées par leur contribution marginale dans la lignée à six membres."
            )
        log(
            "Pondération future GP effective (locale / Transfer Helper / uma.moe) : "
            + ", ".join(f"{key}={value:.1%}" for key, value in mode_weights.items())
        )
        if contextual_mode:
            log(
                "Pondération finale contextuelle (moteur paire de parents) : "
                + ", ".join(f"{key}={value:.1%}" for key, value in pair_weights.items())
            )
        affinity_cfg = config.get("affinity") or {}
        g1_bonus_value = int(affinity_cfg.get("g1_common_bonus", 3))
        final_thresholds = (
            online_cfg.get("final_branch_thresholds")
            or affinity_cfg.get("future_branch_base_thresholds")
            or [[0, 0], [48, 100]]
        )
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

        contextual_white_coverage = _opposing_white_coverage(
            contextual_opposing_parent
        )
        contextual_cfg = online_cfg.get("contextual_opponent") or {}
        contextual_white_decay = max(
            0.0, float(contextual_cfg.get("white_preselection_coverage_decay", 0.75))
        )
        contextual_pink_need: dict[str, float] = {
            "distance": 1.0,
            "surface": 1.0,
            "style": 1.0,
        }
        if contextual_opposing_parent is not None:
            aptitude_cfg = config.get("aptitude_inheritance") or {}
            surface_cfg = aptitude_cfg.get("surface") or {}
            surface_rank = int((ace["target_aptitudes"].get("surface") or {}).get("rank") or 7)
            surface_minimum = int(surface_cfg.get("minimum_initial_rank", 6))
            surface_target = (
                0 if surface_rank >= 7
                else (
                    1 if surface_rank >= surface_minimum
                    else _initial_star_target(surface_rank, surface_minimum)
                )
            )
            known_surface = _matching_factor_stars(
                contextual_opposing_parent, SURFACE_FACTOR_NAMES[surface]
            )
            remaining_surface = max(0, surface_target - known_surface)
            surface_ratio = (
                remaining_surface / max(1.0, float(surface_target))
                if surface_target > 0 else 0.0
            )
            distance_target = max(
                1,
                int(
                    ((config.get("uma_moe_parent_search") or {}).get("retrieval") or {}).get(
                        "contextual_distance_star_target", 6
                    )
                ),
            )
            known_distance = _matching_factor_stars(
                contextual_opposing_parent, DISTANCE_FACTOR_NAMES[distance]
            )
            distance_ratio = max(0.0, min(1.0, (distance_target - known_distance) / distance_target))
            contextual_pink_need = {
                "distance": 0.65 + 0.75 * distance_ratio,
                "surface": 0.20 + 1.20 * max(0.0, min(1.0, surface_ratio)),
                "style": 0.55,
            }

        def eligible(member: dict[str, Any]) -> bool:
            return _valid_grandparent_for_target_parent(
                member, target_parent_chara
            )

        def individual_score(member: dict[str, Any]) -> dict[str, Any]:
            members = [(member, "grandparent", "candidate")]
            triple_raw = resolver.triple(ace_chara, target_parent_chara, int(member.get("chara_id") or 0))
            blue, _ = _blue_score(members, distance, config)
            pink, pink_detail = _future_grandparent_pink_score(
                members, ace, surface, distance, style, config
            )
            white, white_detail = _future_grandparent_white_score(
                members, weight_lookup, config, race_skills
            )
            if contextual_mode:
                pink_raw = 0.0
                for factor in pink_detail.get("factors") or []:
                    dimension = factor.get("matched_dimension")
                    pink_raw += float(factor.get("contribution") or 0.0) * float(
                        contextual_pink_need.get(str(dimension), 0.0)
                    )
                pink = min(100.0, 100.0 * pink_raw)

                white_raw = 0.0
                for factor in white_detail.get("top_factors") or []:
                    factor_name = str(factor.get("source_factor_name") or factor.get("name") or "")
                    coverage = max(0.0, float(contextual_white_coverage.get(factor_name, 0.0)))
                    white_raw += float(factor.get("contribution") or 0.0) / (
                        1.0 + contextual_white_decay * coverage
                    )
                white_scale = max(0.000001, float(white_detail.get("scale") or 1.0))
                white = 100.0 * (1.0 - math.exp(-white_raw / white_scale))
            white_generation, _ = _white_generation_support_score(_lineage_members(member), weight_lookup, config)
            unique, _ = _unique_score(members, config, "future_grandparent")
            g1_count = len(_member_g1(member))
            components = {
                "candidate_affinity": _affinity_score(triple_raw, triple_thresholds),
                "pink": pink,
                "white_skill": white,
                "white_generation": white_generation,
                "blue": blue,
                "g1_potential": _affinity_score(g1_count, g1_thresholds),
                "unique": unique,
            }
            breakdown = _score_breakdown(components, effective_preselection_weights)
            return {
                "member": member,
                "score": float(breakdown["total"]),
                "triple_raw": triple_raw,
                "g1_count": g1_count,
                "components": components,
            }

        remote_eligible = [member for member in online_candidates if eligible(member)]
        if not remote_eligible:
            raise UmaMoeError(
                "Aucun GP distant valide après exclusion du parent à produire."
            )
        if exhaustive_pairs:
            local_eligible = [member for member in veterans if eligible(member)]
            if not local_eligible:
                raise UmaMoeError(
                    "Aucun GP local valide après exclusion du parent à produire."
                )
            second_pool_label = "GP locaux (2ᵉ pool)" if local_pair_mode else "GP distants"
            log(f"Préclassement de {len(local_eligible)} GP locaux et {len(remote_eligible)} {second_pool_label}…")
            local_pre = sorted((individual_score(member) for member in local_eligible), key=lambda row: row["score"], reverse=True)
            remote_pre = sorted((individual_score(member) for member in remote_eligible), key=lambda row: row["score"], reverse=True)
            selected_locals = [row["member"] for row in local_pre[: max(1, min(int(local_pool_size), 250))]]
            selected_remotes = [row["member"] for row in remote_pre[: max(1, min(int(remote_pool_size), 500))]]
            pair_mode = "exhaustive_top_pools"
        else:
            if fixed is None:
                raise UmaMoeError("Sélectionne un GP local ou active le test automatique des paires.")
            if not eligible(fixed):
                raise UmaMoeError(
                    "Le GP local sélectionné est la même Uma que le parent à produire."
                )
            selected_locals = [fixed]
            selected_remotes = remote_eligible
            local_pre = [individual_score(fixed)]
            remote_pre = []
            pair_mode = "fixed_local_gp"

        log(
            f"Comparaison exhaustive : {len(selected_locals)} locaux × {len(selected_remotes)} "
            + ("locaux (2ᵉ pool) " if local_pair_mode else "distants ")
            + f"(jusqu’à {len(selected_locals) * len(selected_remotes)} paires avant exclusions)."
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
            final_parent_affinity["base_full_score_at"] = final_full_score_at
            production_affinity = _full_production_affinity(
                resolver,
                target_parent_chara,
                gp1,
                gp2,
                g1_bonus_value,
            )
            production_affinity["full_score_at"] = production_full_score_at
            gp1_modifier = float(
                (production_affinity.get("gp1_inheritance_modifier") or {}).get("total") or 0.0
            )
            gp2_modifier = float(
                (production_affinity.get("gp2_inheritance_modifier") or {}).get("total") or 0.0
            )
            production_affinity["scored_value"] = (
                0.60 * min(gp1_modifier, gp2_modifier)
                + 0.40 * ((gp1_modifier + gp2_modifier) / 2.0)
            )
            production_affinity["scored_mode"] = "balanced_individual_gp_modifiers"
            production_affinity["score"] = _affinity_score(
                production_affinity["scored_value"], production_thresholds
            )
            production_affinity["included_in_weighted_score"] = False

            direct_members = [
                (gp1, "grandparent", "local_gp1"),
                (gp2, "grandparent", "online_gp2"),
            ]
            six_members = _lineage_members(gp1) + _lineage_members(gp2)
            blue, blue_detail = _blue_score(direct_members, distance, config)
            pink, pink_detail = _future_grandparent_pink_score(
                direct_members, ace, surface, distance, style, config
            )
            white, white_detail = _future_grandparent_white_score(
                direct_members, weight_lookup, config, race_skills
            )
            white_generation, white_generation_detail = _white_generation_support_score(six_members, weight_lookup, config)
            unique, unique_detail = _unique_score(
                direct_members, config, "future_grandparent"
            )
            g1_potential = _future_gp_pair_g1_score(final_parent_affinity)
            final_parent_affinity["g1_potential_score"] = g1_potential
            components = {
                "affinity": _affinity_score(final_parent_affinity["base"], final_thresholds),
                "g1_potential": g1_potential,
                "pink": pink,
                "white_skill": white,
                "white_generation": white_generation,
                "blue": blue,
                "unique": unique,
            }
            # In contextual mode `components` below gets reassigned to the
            # parent_pair engine's own component keys (distance_s,
            # surface_aptitude, ...) for ranking purposes, which do not
            # include "affinity"/"g1_potential". Keep this snapshot so the
            # future-grandparent's own diagnostic sub-scores stay available
            # for the component_details block further down, even though
            # that block is fully replaced by contextual_pair's own detail
            # a few lines later when contextual mode is active.
            diagnostic_components = components
            breakdown = _score_breakdown(components, mode_weights)
            contextual_pair: dict[str, Any] | None = None
            projected_parent: dict[str, Any] | None = None
            projected_g1_plan: dict[str, Any] | None = None
            if contextual_opposing_parent is not None:
                assert opposing_branch is not None
                projected_parent, projected_g1_plan = _project_future_parent_branch(
                    target_parent,
                    gp1,
                    gp2,
                    contextual_opposing_parent,
                    planned_g1_budget=planned_g1_budget,
                    single_g1_weight=single_g1_weight,
                )
                contextual_pair = evaluate_parent_pair(
                    resolver,
                    ace,
                    projected_parent,
                    contextual_opposing_parent,
                    surface=surface,
                    distance=distance,
                    style=style,
                    weight_lookup=weight_lookup,
                    race_skills=race_skills,
                    config=config,
                    parent_2_branch=opposing_branch,
                    g1_bonus_value=g1_bonus_value,
                    affinity_thresholds=(
                        (config.get("affinity") or {}).get("parent_pair_thresholds")
                        or [[0, 0], [151, 100]]
                    ),
                )
                components = dict(contextual_pair["components"])
                # Keep generation support visible as a non-scoring diagnostic.
                components["white_generation"] = white_generation
                breakdown = dict(contextual_pair["score_breakdown"])
            row: dict[str, Any] = {
                "score": float(
                    contextual_pair["score"]
                    if contextual_pair is not None else breakdown["total"]
                ),
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
                "scoring_context": (
                    "fixed_opposing_parent_exact_pair"
                    if contextual_pair is not None
                    else "generic_future_grandparent"
                ),
            }
            if contextual_pair is not None:
                row.update({
                    "affinity": contextual_pair["affinity"],
                    "distance_viability": contextual_pair["distance_viability"],
                    "distance_s_summary": contextual_pair["distance_s_summary"],
                    "surface_viability": contextual_pair["surface_viability"],
                    "surface_aptitude_summary": contextual_pair["surface_aptitude_summary"],
                    "aptitude_summaries": contextual_pair["aptitude_summaries"],
                    "projected_g1_plan": projected_g1_plan,
                })
            if detailed:
                row.update({
                    "candidate": _identity(gp2),
                    "fixed_grandparent": _identity(gp1),
                    "final_branch_affinity": {**final_parent_affinity, "total": final_parent_affinity["potential_total"]},
                    "component_details": {
                        "affinity": {
                            "raw_base": final_parent_affinity["base"],
                            "thresholds": final_thresholds,
                            "score": diagnostic_components["affinity"],
                            "formula": "pair(Ace,parent) + triple(Ace,parent,GP1) + triple(Ace,parent,GP2)",
                        },
                        "g1_potential": {
                            "planned_bonus": final_parent_affinity["planned_g1_bonus"],
                            "maximum_bonus_for_budget": (
                                final_parent_affinity["planned_g1_budget"]
                                * 2
                                * final_parent_affinity["g1_bonus_per_link"]
                            ),
                            "score": diagnostic_components["g1_potential"],
                            "formula": "100 × planned G1 bonus / maximum double-link bonus for the configured race budget",
                        },
                        "blue": blue_detail,
                        "pink": {
                            **pink_detail,
                            "evaluation_context": "future_grandparent_simple_quality",
                        },
                        "white_skill": {
                            **white_detail,
                            "evaluation_context": "future_grandparent_direct_factor_quality",
                        },
                        "white_generation": {
                            **white_generation_detail,
                            "evaluation_context": "intermediate_run_that_creates_target_parent",
                        },
                        "unique": unique_detail,
                    },
                })
                if contextual_pair is not None:
                    row.update({
                        "opposing_parent": _identity(contextual_opposing_parent),
                        "projected_future_parent": _identity(projected_parent or {}),
                        "contextual_final_pair": {
                            "affinity": contextual_pair["affinity"],
                            "components": contextual_pair["components"],
                            "score_breakdown": contextual_pair["score_breakdown"],
                            "distance_viability": contextual_pair["distance_viability"],
                            "distance_s_summary": contextual_pair["distance_s_summary"],
                            "surface_viability": contextual_pair["surface_viability"],
                            "surface_aptitude_summary": contextual_pair["surface_aptitude_summary"],
                            "aptitude_summaries": contextual_pair["aptitude_summaries"],
                        },
                        "component_details": {
                            **contextual_pair["component_details"],
                            "white_generation": {
                                **white_generation_detail,
                                "included_in_weighted_score": False,
                                "evaluation_context": "intermediate_run_that_creates_target_parent",
                            },
                        },
                    })
            return row

        summaries: list[dict[str, Any]] = []
        total_possible = len(selected_locals) * len(selected_remotes)
        processed = 0
        evaluated_local_pairs: set[frozenset[int]] = set()
        for gp1 in selected_locals:
            gp1_chara = int(gp1.get("chara_id") or 0)
            for gp2 in selected_remotes:
                processed += 1
                gp2_chara = int(gp2.get("chara_id") or 0)
                if gp1_chara <= 0 or gp2_chara <= 0 or gp1_chara == gp2_chara:
                    continue
                if local_pair_mode:
                    # Both pools draw from the same veterans: (A, B) and (B, A)
                    # are the same unordered pair, evaluate it once.
                    pair_key = frozenset((
                        int(gp1.get("trained_chara_id") or 0),
                        int(gp2.get("trained_chara_id") or 0),
                    ))
                    if len(pair_key) < 2 or pair_key in evaluated_local_pairs:
                        continue
                    evaluated_local_pairs.add(pair_key)
                summaries.append(evaluate_pair(gp1, gp2, detailed=False))
            if exhaustive_pairs and (processed % max(1, len(selected_remotes) * 10) == 0 or processed == total_possible):
                log(f"Paires évaluées : {processed}/{total_possible} — {len(summaries)} valides.")

        if contextual_mode:
            summaries.sort(key=parent_pair_sort_key, reverse=True)
        else:
            summaries.sort(
                key=lambda row: (
                    row["score"],
                    row["final_parent_affinity"]["potential_total"],
                    row["production_affinity"]["scored_value"],
                ),
                reverse=True,
            )
        detail_count = max(1, min(int(top_n), 500))
        top: list[dict[str, Any]] = []
        for summary in summaries[:detail_count]:
            top.append(evaluate_pair(summary["_gp1"], summary["_gp2"], detailed=True))
    finally:
        resolver.close()

    generated = datetime.now(timezone.utc).isoformat()
    raw_response_path = output_dir / "uma_moe_raw_response.json"
    raw_response_path.write_text(
        json.dumps(
            raw_payload
            if raw_payload is not None
            else {"local_pair_mode": True, "note": "No uma.moe request: both pools come from local veterans."},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    rankings_json_path = output_dir / "uma_moe_grandparent_pairs.json"
    payload = {
        "metadata": {
            "schema_version": 7,
            "generated_at_utc": generated,
            "source": (
                "local veterans (both pools)"
                if local_pair_mode
                else "uma.moe public API or imported API response"
            ),
            "api_operation": api_operation,
            "weight_source": weight_source,
            "pair_mode": (f"local_{pair_mode}" if local_pair_mode else pair_mode),
            "scoring_context": (
                "fixed_opposing_parent_exact_pair"
                if contextual_mode else "generic_future_grandparent"
            ),
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
            "future_grandparent_factor_model": {
                "meaning": (
                    "With a fixed opposing parent, GP1/GP2 are inserted below a projected empty-factor future parent and scored by the canonical six-member final-pair engine. Without one, direct factors keep the simple future-grandparent quality model. Current GP ancestors only contribute to separate white-generation support."
                ),
                "parameters": config.get("future_grandparent_heuristics") or {},
                "saturation": config.get("white_saturation") or {},
            },
            "important": "Online records can become stale; verify follow availability and the profile on uma.moe before relying on a borrow.",
        },
        "ace": ace,
        "target_parent": target_parent,
        "opposing_parent": (
            _identity(contextual_opposing_parent)
            if contextual_opposing_parent is not None else None
        ),
        "fixed_grandparent": (_identity(fixed) if fixed is not None and not exhaustive_pairs else None),
        "scoring": {
            "weights": pair_weights if contextual_mode else mode_weights,
            "preselection_weights": effective_preselection_weights,
            "generic_preselection_weights": preselection_weights,
            "weight_source": (
                "mode_weights.parent_pair"
                if contextual_mode else "mode_weights.future_grandparent"
            ),
            "logic": (
                "When an opposing parent is fixed, the final ranking is the marginal value of GP1+GP2 in the projected complete lineage: exact individual proc affinities, cumulative white probabilities, aptitude viability, blues, uniques and all five visible G1 links. The future parent's own unknown Sparks stay empty. Without an opposing parent, the generic future-GP heuristic remains unchanged."
            ),
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
        distance_summary = row.get("distance_s_summary") or {}
        surface_summary = row.get("surface_aptitude_summary") or {}
        csv_rows.append({
            "rank": rank,
            "score": round(row["score"], 3),
            "scoring_context": row.get("scoring_context"),
            "opposing_parent": (
                contextual_opposing_parent.get("card_name")
                if contextual_opposing_parent is not None else ""
            ),
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
            "affinity_component": round(row["components"]["affinity"], 2),
            "g1_potential_component": round(float(row["components"].get("g1_potential") or 0.0), 2),
            "production_run_affinity": row["production_affinity"]["total"],
            "production_run_scored_value": round(float(row["production_affinity"]["scored_value"]), 3),
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
            "unique": round(row["components"]["unique"], 2),
            "candidate_g1": row["candidate_g1_count"],
            "final_pair_affinity_total": (row.get("affinity") or {}).get("total"),
            "projected_parent_g1_count": (row.get("projected_g1_plan") or {}).get("selected_count"),
            "distance_status": (row.get("distance_viability") or {}).get("key"),
            "distance_stars": distance_summary.get("total_stars"),
            "distance_probability_s": round(100.0 * float(distance_summary.get("probability_reach_s") or 0.0), 3),
            "surface_status": (row.get("surface_viability") or {}).get("key"),
            "surface_stars": surface_summary.get("total_stars"),
            "surface_probability_a": round(100.0 * float(surface_summary.get("probability_reach_a") or 0.0), 3),
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
            "pair_mode": (f"local_{pair_mode}" if local_pair_mode else pair_mode),
            "scoring_context": (
                "fixed_opposing_parent_exact_pair"
                if contextual_mode else "generic_future_grandparent"
            ),
            "opposing_parent": (
                _identity(contextual_opposing_parent)
                if contextual_opposing_parent is not None else None
            ),
            "scoring": {
                "weight_source": (
                    "mode_weights.parent_pair"
                    if contextual_mode else "mode_weights.future_grandparent"
                ),
                "weights": pair_weights if contextual_mode else mode_weights,
                "preselection_weights": effective_preselection_weights,
                "generic_preselection_weights": preselection_weights,
                "production_run_affinity_included_in_weighted_score": False,
            },
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
        pair_mode=(f"local_{pair_mode}" if local_pair_mode else pair_mode),
        local_pool_count=len(selected_locals),
        remote_pool_count=len(selected_remotes),
        evaluated_pair_count=len(summaries),
        ace=ace,
        target_parent=target_parent,
        opposing_parent=(
            _identity(contextual_opposing_parent)
            if contextual_opposing_parent is not None else None
        ),
        scoring_context=(
            "fixed_opposing_parent_exact_pair"
            if contextual_mode else "generic_future_grandparent"
        ),
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
        "distance_status", "distance_tier", "distance_stars", "distance_carriers",
        "distance_parent_carriers", "distance_support", "distance_initial_required", "distance_initial_met",
        "distance_initial_rank", "distance_probability_a", "distance_probability_s",
        "surface_status", "surface_tier", "surface_stars", "surface_carriers",
        "surface_initial_rank", "surface_probability_a", "surface_probability_s",
        "style_initial_rank", "style_probability_a", "style_probability_s",
        "affinity_component", "distance_s", "surface_aptitude", "pink_other", "pink", "white", "race_scenario", "blue", "unique",
        "updated_at", "follow_status",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter=";")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def _select_diverse_parent_branch_pool(
    rows: list[dict[str, Any]],
    *,
    pool_size: int,
    ace_target_aptitudes: dict[str, Any],
    config: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Reserve preselection space for complementary aptitude branches."""
    limit = max(1, int(pool_size))
    if len(rows) <= limit:
        return list(rows), {
            "requested": limit,
            "available": len(rows),
            "selected": len(rows),
            "strategy": "all_available",
        }

    parent_cfg = config.get("uma_moe_parent_search") or {}
    selection_cfg = parent_cfg.get("preselection") or {}
    aptitude_cfg = config.get("aptitude_inheritance") or {}
    surface_cfg = aptitude_cfg.get("surface") or {}
    surface_rank = int(
        ((ace_target_aptitudes.get("surface") or {}).get("rank")) or 7
    )
    minimum_surface_rank = int(surface_cfg.get("minimum_initial_rank", 6))
    preferred_surface_rank = int(surface_cfg.get("preferred_initial_rank", 7))
    if surface_rank < minimum_surface_rank:
        surface_share = float(
            selection_cfg.get("surface_share_below_minimum", 0.40)
        )
    elif surface_rank < preferred_surface_rank:
        surface_share = float(
            selection_cfg.get("surface_share_at_minimum", 0.20)
        )
    else:
        surface_share = float(
            selection_cfg.get("surface_share_at_preferred", 0.0)
        )
    distance_share = max(
        0.0, float(selection_cfg.get("distance_share", 0.35))
    )
    surface_share = max(0.0, surface_share)
    if distance_share + surface_share > 0.85:
        scale = 0.85 / max(0.000001, distance_share + surface_share)
        distance_share *= scale
        surface_share *= scale
    overall_share = max(0.15, 1.0 - distance_share - surface_share)
    share_total = overall_share + distance_share + surface_share
    quotas = {
        "overall": max(1, int(round(limit * overall_share / share_total))),
        "distance": int(round(limit * distance_share / share_total)),
        "surface": int(round(limit * surface_share / share_total)),
    }
    while sum(quotas.values()) > limit:
        key = max(quotas, key=lambda item: quotas[item])
        if key == "overall" and quotas[key] <= 1:
            break
        quotas[key] -= 1
    while sum(quotas.values()) < limit:
        quotas["overall"] += 1

    def dimension_key(
        row: dict[str, Any], key: str
    ) -> tuple[float, float, float, float]:
        summary = (
            row.get("distance_s_summary")
            if key == "distance"
            else row.get("surface_aptitude_summary")
        ) or {}
        component = (row.get("components") or {}).get(
            "distance_s" if key == "distance" else "surface_aptitude"
        ) or 0.0
        return (
            float(summary.get("total_stars") or 0),
            float(summary.get("probability_any_proc") or 0),
            float(component),
            float(row.get("score") or 0),
        )

    rankings = {
        "overall": sorted(
            rows,
            key=lambda row: (
                float(row.get("score") or 0),
                float((row.get("affinity") or {}).get("total") or 0),
            ),
            reverse=True,
        ),
        "distance": sorted(
            rows, key=lambda row: dimension_key(row, "distance"), reverse=True
        ),
        "surface": sorted(
            rows, key=lambda row: dimension_key(row, "surface"), reverse=True
        ),
    }
    selected: list[dict[str, Any]] = []
    seen: set[int] = set()
    selected_by_strategy: dict[str, int] = {}

    def take(strategy: str, count: int) -> None:
        added = 0
        for row in rankings[strategy]:
            identity = id(row.get("veteran") or row)
            if identity in seen:
                continue
            seen.add(identity)
            selected.append(row)
            added += 1
            if added >= count or len(selected) >= limit:
                break
        selected_by_strategy[strategy] = (
            selected_by_strategy.get(strategy, 0) + added
        )

    take("overall", quotas["overall"])
    take("distance", quotas["distance"])
    take("surface", quotas["surface"])
    if len(selected) < limit:
        take("overall", limit - len(selected))
    return selected[:limit], {
        "requested": limit,
        "available": len(rows),
        "selected": min(limit, len(selected)),
        "strategy": "overall_plus_reserved_aptitude_cohorts",
        "quotas": quotas,
        "selected_by_strategy": selected_by_strategy,
        "surface_base_rank": surface_rank,
        "surface_minimum_rank": minimum_surface_rank,
        "surface_preferred_rank": preferred_surface_rank,
    }


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
    required_parent_card_id: int | None = None,
    allowed_parent_card_ids: Iterable[int] | None = None,
    excluded_parent_card_ids: Iterable[int] | None = None,
    effective_uql: str = "",
    lineage_blue_filter: tuple[str, int] | None = None,
    lineage_pink_filter: tuple[str, int] | None = None,
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
    allowed_parent_card_ids = {int(value) for value in (allowed_parent_card_ids or []) if int(value) > 0}
    excluded_parent_card_ids = {int(value) for value in (excluded_parent_card_ids or []) if int(value) > 0}

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
        raise UmaMoeError(
            "La réponse uma.moe ne contient aucun parent avec Main/factors exploitables."
            + _empty_candidates_diagnostic(_extract_record_list(raw_payload))
        )

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
    online_candidates = _apply_lineage_factor_filters(
        online_candidates, lineage_blue_filter, lineage_pink_filter, log
    )
    if not online_candidates:
        raise UmaMoeError(
            "Aucun candidat ne respecte les filtres lignée demandés. "
            "Assouplis le minimum d'étoiles ou augmente la limite de récupération API."
        )
    normalization_diag["lineage_filters"] = {
        "blue": list(lineage_blue_filter) if lineage_blue_filter else None,
        "pink": list(lineage_pink_filter) if lineage_pink_filter else None,
        "post_lineage_filter_count": len(online_candidates),
    }

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
        pair_weights = _mode_weights(config, "parent_pair")

        def eligible(member: dict[str, Any]) -> bool:
            chara = int(member.get("chara_id") or 0)
            card_id = int(member.get("card_id") or 0)
            if chara <= 0 or chara == ace_chara or card_id <= 0:
                return False
            if allowed_parent_card_ids and card_id not in allowed_parent_card_ids:
                return False
            if card_id in excluded_parent_card_ids:
                return False
            return True

        def pair_matches_card_filters(parent_1: dict[str, Any], parent_2: dict[str, Any]) -> bool:
            if required_parent_card_id is None:
                return True
            return required_parent_card_id in {
                int(parent_1.get("card_id") or 0),
                int(parent_2.get("card_id") or 0),
            }

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
            selected_local_rows, local_preselection_diag = _select_diverse_parent_branch_pool(
                local_pre,
                pool_size=max(1, min(int(local_pool_size), 250)),
                ace_target_aptitudes=ace["target_aptitudes"],
                config=config,
            )
            selected_remote_rows, remote_preselection_diag = _select_diverse_parent_branch_pool(
                remote_pre,
                pool_size=max(1, min(int(remote_pool_size), 500)),
                ace_target_aptitudes=ace["target_aptitudes"],
                config=config,
            )
            selected_locals = [
                row["veteran"]
                for row in selected_local_rows
            ]
            selected_remotes = [
                row["veteran"]
                for row in selected_remote_rows
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
            local_preselection_diag = {
                "strategy": "fixed_local_parent",
                "selected": 1,
            }
            remote_preselection_diag = {
                "strategy": "all_remote_with_fixed_parent",
                "selected": len(selected_remotes),
            }
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
                "distance_viability": pair["distance_viability"],
                "distance_s_summary": pair["distance_s_summary"],
                "surface_viability": pair["surface_viability"],
                "surface_aptitude_summary": pair["surface_aptitude_summary"],
                "aptitude_summaries": pair["aptitude_summaries"],
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
                        "distance_viability": local_branch["distance_viability"],
                        "distance_s_summary": local_branch["distance_s_summary"],
                        "surface_viability": local_branch["surface_viability"],
                        "surface_aptitude_summary": local_branch["surface_aptitude_summary"],
                    },
                    "remote_branch": {
                        "score": remote_branch["score"],
                        "affinity": remote_branch["affinity"],
                        "components": remote_branch["components"],
                        "score_breakdown": remote_branch["score_breakdown"],
                        "distance_viability": remote_branch["distance_viability"],
                        "distance_s_summary": remote_branch["distance_s_summary"],
                        "surface_viability": remote_branch["surface_viability"],
                        "surface_aptitude_summary": remote_branch["surface_aptitude_summary"],
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
                if not pair_matches_card_filters(local_parent, remote_parent):
                    continue
                summaries.append(evaluate_pair(local_parent, remote_parent, detailed=False))
            if exhaustive_pairs and (
                processed % max(1, len(selected_remotes) * 10) == 0
                or processed == total_possible
            ):
                log(f"Paires parent évaluées : {processed}/{total_possible} — {len(summaries)} valides.")

        if not summaries:
            raise UmaMoeError("Aucune paire parent local × parent distant valide.")
        summaries.sort(key=parent_pair_sort_key, reverse=True)
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
            "schema_version": 3,
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
            "parent_card_filters": {
                "required_any": required_parent_card_id,
                "allowed": sorted(allowed_parent_card_ids),
                "excluded": sorted(excluded_parent_card_ids),
                "scope": "costume_variant/card_id",
            },
            "complete_branch_validation": {
                "remote_incomplete_excluded": incomplete_remote_count,
                "local_incomplete_excluded": incomplete_local_count,
                "required_visible_members_per_pair": 6,
            },
            "branch_preselection": {
                "local": local_preselection_diag,
                "remote": remote_preselection_diag,
            },
            "condition_diagnostics": condition_diag,
            "scoring_engine": "parent_optimizer.evaluate_parent_pair",
            "lineage_model": (
                "Exact same six-member final-parent pair formula as the local optimizer: "
                "two complete parent branches, parent-parent compatibility, five G1 links, "
                "and all factors from both parents plus their four grandparents."
            ),
            "ranking_order": (
                "Distance-S viability tier first, then the configured target-surface minimum gate, "
                "then weighted pair score, white score, blue score, preferred-surface probability "
                "and raw Distance-S probability as tie-breakers. Surface A remains a weighted soft "
                "preference; target-surface or style Sparks cannot compensate a lower distance tier."
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
                "unchanged to the same scorer as local parent pairs. Final ranking is lexicographic: "
                "Distance-S viability before weighted quality. Target-surface aptitude is a separate "
                "secondary minimum gate plus weighted component (B minimum, A preferred), so strong "
                "surrounding Sparks can compensate B versus A while surface never outranks distance. Raw P(S) no longer "
                "overrides better white/blue lineages inside the same distance tier."
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
        distance_summary = row.get("distance_s_summary") or {}
        viability = row.get("distance_viability") or {}
        surface_summary = row.get("surface_aptitude_summary") or {}
        surface_viability = row.get("surface_viability") or {}
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
            "distance_status": viability.get("key"),
            "distance_tier": viability.get("tier"),
            "distance_stars": distance_summary.get("total_stars"),
            "distance_carriers": distance_summary.get("carrier_count"),
            "distance_parent_carriers": distance_summary.get("parent_carrier_count"),
            "distance_support": distance_summary.get("weighted_support"),
            "distance_initial_required": distance_summary.get("initial_required_stars"),
            "distance_initial_met": viability.get("is_initial_requirement_met"),
            "distance_initial_rank": distance_summary.get("initial_rank_label"),
            "distance_probability_a": round(100.0 * float(distance_summary.get("probability_reach_a") or 0), 3),
            "distance_probability_s": round(100.0 * float(distance_summary.get("probability_reach_s") or 0), 3),
            "surface_status": surface_viability.get("key"),
            "surface_tier": surface_viability.get("tier"),
            "surface_stars": surface_summary.get("total_stars"),
            "surface_carriers": surface_summary.get("carrier_count"),
            "surface_initial_rank": surface_summary.get("initial_rank_label"),
            "surface_probability_a": round(100.0 * float(surface_summary.get("probability_reach_a") or 0), 3),
            "surface_probability_s": round(100.0 * float(surface_summary.get("probability_reach_s") or 0), 3),
            "style_initial_rank": ((row.get("aptitude_summaries") or {}).get("style") or {}).get("initial_rank_label"),
            "style_probability_a": round(100.0 * float((((row.get("aptitude_summaries") or {}).get("style") or {}).get("probability_reach_a") or 0)), 3),
            "style_probability_s": round(100.0 * float((((row.get("aptitude_summaries") or {}).get("style") or {}).get("probability_reach_s") or 0)), 3),
            "affinity_component": round(float(components.get("affinity") or 0), 2),
            "distance_s": round(float(components.get("distance_s") or 0), 2),
            "surface_aptitude": round(float(components.get("surface_aptitude") or 0), 2),
            "pink_other": round(float(components.get("pink_other") or 0), 2),
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
            "branch_preselection": {
                "local": local_preselection_diag,
                "remote": remote_preselection_diag,
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
