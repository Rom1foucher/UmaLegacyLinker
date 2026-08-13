from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

LOOP_SCHEMA_VERSION = 2
TARGET_POLICIES = {"static", "dynamic"}
LEARNED_FORMS = {"normal", "circle", "gold"}
QUALITY_BANDS = {"below_ss", "ss_to_ue_plus", "ue_plus"}
LOOP_SURFACES = {"turf", "dirt"}
LOOP_DISTANCES = {"sprint", "mile", "medium", "long"}
LOOP_STYLES = {"front_runner", "pace_chaser", "late_surger", "end_closer"}
TRANSITION_STATUSES = {"pending", "completed"}
LOOP_VERDICTS = {"promote_core", "replace_core", "keep_side", "ignore"}
BRANCH_TYPES = {
    "core",
    "cm",
    "pink_infra",
    "blue",
    "reintroduction",
    "unique",
    "custom",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _integer(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _probability(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        probability = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, probability))


@dataclass
class LoopSkillTarget:
    key: str
    name: str
    factor_group_id: int | None = None
    skill_id: int | None = None
    policy: str = "dynamic"
    learned_form: str = "normal"
    acquisition_probability: float | None = None
    weight: float = 1.0

    def __post_init__(self) -> None:
        self.key = str(self.key or "").strip()
        self.name = str(self.name or self.key).strip()
        self.factor_group_id = _integer(self.factor_group_id)
        self.skill_id = _integer(self.skill_id)
        self.policy = self.policy if self.policy in TARGET_POLICIES else "dynamic"
        self.learned_form = (
            self.learned_form if self.learned_form in LEARNED_FORMS else "normal"
        )
        self.acquisition_probability = _probability(self.acquisition_probability)
        try:
            self.weight = max(0.0, float(self.weight))
        except (TypeError, ValueError):
            self.weight = 1.0
        if not self.key:
            raise ValueError("Une cible de looping doit posséder une identité de facteur.")

    @property
    def is_static(self) -> bool:
        return self.policy == "static"

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "factor_group_id": self.factor_group_id,
            "skill_id": self.skill_id,
            "policy": self.policy,
            "learned_form": self.learned_form,
            "acquisition_probability": self.acquisition_probability,
            "weight": self.weight,
        }

    @classmethod
    def from_dict(cls, payload: object) -> LoopSkillTarget:
        data = payload if isinstance(payload, dict) else {}
        return cls(
            key=str(data.get("key") or ""),
            name=str(data.get("name") or ""),
            factor_group_id=_integer(data.get("factor_group_id")),
            skill_id=_integer(data.get("skill_id")),
            policy=str(data.get("policy") or "dynamic"),
            learned_form=str(data.get("learned_form") or "normal"),
            acquisition_probability=_probability(data.get("acquisition_probability")),
            weight=float(data.get("weight") or 1.0),
        )


@dataclass
class LoopCarrier:
    carrier_id: str
    trained_chara_id: int | None
    branch: str
    status: str
    snapshot: dict[str, Any]
    source: str = "local"
    added_at: str = field(default_factory=utc_now)
    note: str = ""

    def __post_init__(self) -> None:
        self.carrier_id = str(self.carrier_id or "").strip()
        self.trained_chara_id = _integer(self.trained_chara_id)
        self.branch = self.branch if self.branch in BRANCH_TYPES else "custom"
        self.status = self.status if self.status in {"active", "archived"} else "active"
        self.snapshot = copy.deepcopy(self.snapshot if isinstance(self.snapshot, dict) else {})
        self.source = str(self.source or "local")
        self.note = str(self.note or "")
        if not self.carrier_id:
            raise ValueError("Un porteur de boucle doit posséder un identifiant stable.")

    @property
    def active(self) -> bool:
        return self.status == "active"

    def to_dict(self) -> dict[str, Any]:
        return {
            "carrier_id": self.carrier_id,
            "trained_chara_id": self.trained_chara_id,
            "branch": self.branch,
            "status": self.status,
            "snapshot": copy.deepcopy(self.snapshot),
            "source": self.source,
            "added_at": self.added_at,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, payload: object) -> LoopCarrier:
        data = payload if isinstance(payload, dict) else {}
        return cls(
            carrier_id=str(data.get("carrier_id") or ""),
            trained_chara_id=_integer(data.get("trained_chara_id")),
            branch=str(data.get("branch") or "custom"),
            status=str(data.get("status") or "active"),
            snapshot=copy.deepcopy(data.get("snapshot") or {}),
            source=str(data.get("source") or "local"),
            added_at=str(data.get("added_at") or utc_now()),
            note=str(data.get("note") or ""),
        )


@dataclass
class LoopDraftTransition:
    """Persisted UI recipe that is not yet an active farming batch."""

    trainee_card_id: int | None = None
    trainee_chara_id: int | None = None
    parent_1_trained_id: int | None = None
    parent_2_trained_id: int | None = None
    last_plan: dict[str, Any] | None = None
    updated_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.trainee_card_id = _integer(self.trainee_card_id)
        self.trainee_chara_id = _integer(self.trainee_chara_id)
        self.parent_1_trained_id = _integer(self.parent_1_trained_id)
        self.parent_2_trained_id = _integer(self.parent_2_trained_id)
        self.last_plan = copy.deepcopy(
            self.last_plan if isinstance(self.last_plan, dict) else None
        )
        self.updated_at = str(self.updated_at or utc_now())

    @property
    def empty(self) -> bool:
        return not any(
            value is not None
            for value in (
                self.trainee_card_id,
                self.trainee_chara_id,
                self.parent_1_trained_id,
                self.parent_2_trained_id,
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "trainee_card_id": self.trainee_card_id,
            "trainee_chara_id": self.trainee_chara_id,
            "parent_1_trained_id": self.parent_1_trained_id,
            "parent_2_trained_id": self.parent_2_trained_id,
            "last_plan": copy.deepcopy(self.last_plan),
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, payload: object) -> LoopDraftTransition | None:
        if not isinstance(payload, dict):
            return None
        draft = cls(
            trainee_card_id=_integer(payload.get("trainee_card_id")),
            trainee_chara_id=_integer(payload.get("trainee_chara_id")),
            parent_1_trained_id=_integer(payload.get("parent_1_trained_id")),
            parent_2_trained_id=_integer(payload.get("parent_2_trained_id")),
            last_plan=copy.deepcopy(payload.get("last_plan")),
            updated_at=str(payload.get("updated_at") or utc_now()),
        )
        return None if draft.empty and draft.last_plan is None else draft


@dataclass
class LoopRunResult:
    """One extracted veteran automatically or manually attached to a farming batch."""

    run_id: str
    trained_chara_id: int
    detected_at: str
    snapshot: dict[str, Any]
    analysis: dict[str, Any]
    learned_skills: list[dict[str, Any]] = field(default_factory=list)
    learned_skills_known: bool = False
    auto_detected: bool = True
    verdict: str | None = None
    branch: str | None = None
    replaces_trained_chara_id: int | None = None
    note: str = ""
    reviewed_at: str | None = None

    def __post_init__(self) -> None:
        self.run_id = str(self.run_id or "").strip()
        self.trained_chara_id = _integer(self.trained_chara_id) or 0
        self.detected_at = str(self.detected_at or utc_now())
        self.snapshot = copy.deepcopy(self.snapshot if isinstance(self.snapshot, dict) else {})
        self.analysis = copy.deepcopy(self.analysis if isinstance(self.analysis, dict) else {})
        self.learned_skills = [
            copy.deepcopy(item)
            for item in self.learned_skills
            if isinstance(item, dict)
        ]
        self.learned_skills_known = bool(self.learned_skills_known)
        self.auto_detected = bool(self.auto_detected)
        self.verdict = self.verdict if self.verdict in LOOP_VERDICTS else None
        self.branch = self.branch if self.branch in BRANCH_TYPES else None
        self.replaces_trained_chara_id = _integer(self.replaces_trained_chara_id)
        self.note = str(self.note or "")
        self.reviewed_at = str(self.reviewed_at) if self.reviewed_at else None
        if not self.run_id:
            raise ValueError("Un résultat de run doit posséder un identifiant stable.")
        if self.trained_chara_id <= 0:
            raise ValueError("Un résultat de run doit posséder un identifiant local.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "trained_chara_id": self.trained_chara_id,
            "detected_at": self.detected_at,
            "snapshot": copy.deepcopy(self.snapshot),
            "analysis": copy.deepcopy(self.analysis),
            "learned_skills": copy.deepcopy(self.learned_skills),
            "learned_skills_known": self.learned_skills_known,
            "auto_detected": self.auto_detected,
            "verdict": self.verdict,
            "branch": self.branch,
            "replaces_trained_chara_id": self.replaces_trained_chara_id,
            "note": self.note,
            "reviewed_at": self.reviewed_at,
        }

    @classmethod
    def from_dict(cls, payload: object) -> LoopRunResult:
        data = payload if isinstance(payload, dict) else {}
        return cls(
            run_id=str(data.get("run_id") or f"local:{_integer(data.get('trained_chara_id')) or 0}"),
            trained_chara_id=_integer(data.get("trained_chara_id")) or 0,
            detected_at=str(data.get("detected_at") or utc_now()),
            snapshot=copy.deepcopy(data.get("snapshot") or {}),
            analysis=copy.deepcopy(data.get("analysis") or {}),
            learned_skills=[
                copy.deepcopy(item)
                for item in data.get("learned_skills") or []
                if isinstance(item, dict)
            ],
            learned_skills_known=bool(data.get("learned_skills_known")),
            auto_detected=bool(data.get("auto_detected", True)),
            verdict=(str(data.get("verdict")) if data.get("verdict") else None),
            branch=(str(data.get("branch")) if data.get("branch") else None),
            replaces_trained_chara_id=_integer(data.get("replaces_trained_chara_id")),
            note=str(data.get("note") or ""),
            reviewed_at=(str(data.get("reviewed_at")) if data.get("reviewed_at") else None),
        )


@dataclass
class LoopTransition:
    transition_id: str
    created_at: str
    trainee_card_id: int
    trainee_chara_id: int
    trainee_name: str
    parent_1_trained_id: int
    parent_2_trained_id: int
    quality_band: str
    plan: dict[str, Any]
    status: str = "pending"
    completed_at: str | None = None
    baseline_trained_ids: list[int] = field(default_factory=list)
    runs: list[LoopRunResult] = field(default_factory=list)
    # Legacy single-outcome fields are kept so schema-v1 projects remain
    # readable and older callers keep a stable surface. New code uses runs[].
    outcome_trained_chara_id: int | None = None
    verdict: str | None = None
    branch: str | None = None
    replaces_trained_chara_id: int | None = None
    outcome_analysis: dict[str, Any] | None = None
    note: str = ""

    def __post_init__(self) -> None:
        self.transition_id = str(self.transition_id or "").strip()
        self.trainee_card_id = _integer(self.trainee_card_id) or 0
        self.trainee_chara_id = _integer(self.trainee_chara_id) or 0
        self.parent_1_trained_id = _integer(self.parent_1_trained_id) or 0
        self.parent_2_trained_id = _integer(self.parent_2_trained_id) or 0
        self.quality_band = (
            self.quality_band if self.quality_band in QUALITY_BANDS else "ss_to_ue_plus"
        )
        self.plan = copy.deepcopy(self.plan if isinstance(self.plan, dict) else {})
        self.status = self.status if self.status in TRANSITION_STATUSES else "pending"
        self.completed_at = str(self.completed_at) if self.completed_at else None
        self.baseline_trained_ids = sorted(
            {
                value
                for value in (_integer(item) for item in self.baseline_trained_ids)
                if value is not None and value > 0
            }
        )
        self.runs = [
            item if isinstance(item, LoopRunResult) else LoopRunResult.from_dict(item)
            for item in self.runs
            if isinstance(item, (LoopRunResult, dict))
        ]
        self.outcome_trained_chara_id = _integer(self.outcome_trained_chara_id)
        self.verdict = self.verdict if self.verdict in LOOP_VERDICTS else None
        self.branch = self.branch if self.branch in BRANCH_TYPES else None
        self.replaces_trained_chara_id = _integer(self.replaces_trained_chara_id)
        self.outcome_analysis = copy.deepcopy(
            self.outcome_analysis if isinstance(self.outcome_analysis, dict) else None
        )
        self.note = str(self.note or "")
        if not self.transition_id:
            raise ValueError("Une transition de looping doit posséder un identifiant.")

        # Schema-v1 migration: preserve the old completed outcome as one run.
        if self.outcome_trained_chara_id and not self.runs:
            legacy_snapshot = {}
            if isinstance(self.outcome_analysis, dict):
                identity = self.outcome_analysis.get("outcome")
                if isinstance(identity, dict):
                    legacy_snapshot = copy.deepcopy(identity)
            legacy_snapshot.setdefault("trained_chara_id", self.outcome_trained_chara_id)
            self.runs.append(
                LoopRunResult(
                    run_id=f"local:{self.outcome_trained_chara_id}",
                    trained_chara_id=self.outcome_trained_chara_id,
                    detected_at=self.completed_at or self.created_at,
                    snapshot=legacy_snapshot,
                    analysis=copy.deepcopy(self.outcome_analysis or {}),
                    learned_skills=[],
                    learned_skills_known=False,
                    auto_detected=False,
                    verdict=self.verdict,
                    branch=self.branch,
                    replaces_trained_chara_id=self.replaces_trained_chara_id,
                    note=self.note,
                    reviewed_at=self.completed_at,
                )
            )

    @property
    def active(self) -> bool:
        return self.status == "pending"

    def run(self, trained_chara_id: int) -> LoopRunResult | None:
        requested = _integer(trained_chara_id)
        return next(
            (item for item in self.runs if item.trained_chara_id == requested),
            None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "transition_id": self.transition_id,
            "created_at": self.created_at,
            "trainee_card_id": self.trainee_card_id,
            "trainee_chara_id": self.trainee_chara_id,
            "trainee_name": self.trainee_name,
            "parent_1_trained_id": self.parent_1_trained_id,
            "parent_2_trained_id": self.parent_2_trained_id,
            "quality_band": self.quality_band,
            "plan": copy.deepcopy(self.plan),
            "status": self.status,
            "completed_at": self.completed_at,
            "baseline_trained_ids": list(self.baseline_trained_ids),
            "runs": [run.to_dict() for run in self.runs],
            "outcome_trained_chara_id": self.outcome_trained_chara_id,
            "verdict": self.verdict,
            "branch": self.branch,
            "replaces_trained_chara_id": self.replaces_trained_chara_id,
            "outcome_analysis": copy.deepcopy(self.outcome_analysis),
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, payload: object) -> LoopTransition:
        data = payload if isinstance(payload, dict) else {}
        return cls(
            transition_id=str(data.get("transition_id") or ""),
            created_at=str(data.get("created_at") or utc_now()),
            trainee_card_id=_integer(data.get("trainee_card_id")) or 0,
            trainee_chara_id=_integer(data.get("trainee_chara_id")) or 0,
            trainee_name=str(data.get("trainee_name") or ""),
            parent_1_trained_id=_integer(data.get("parent_1_trained_id")) or 0,
            parent_2_trained_id=_integer(data.get("parent_2_trained_id")) or 0,
            quality_band=str(data.get("quality_band") or "ss_to_ue_plus"),
            plan=copy.deepcopy(data.get("plan") or {}),
            status=str(data.get("status") or "pending"),
            completed_at=(str(data.get("completed_at")) if data.get("completed_at") else None),
            baseline_trained_ids=[
                int(item)
                for item in data.get("baseline_trained_ids") or []
                if _integer(item) is not None
            ],
            runs=[
                LoopRunResult.from_dict(item)
                for item in data.get("runs") or []
                if isinstance(item, dict)
            ],
            outcome_trained_chara_id=_integer(data.get("outcome_trained_chara_id")),
            verdict=(str(data.get("verdict")) if data.get("verdict") else None),
            branch=(str(data.get("branch")) if data.get("branch") else None),
            replaces_trained_chara_id=_integer(data.get("replaces_trained_chara_id")),
            outcome_analysis=copy.deepcopy(data.get("outcome_analysis")),
            note=str(data.get("note") or ""),
        )


@dataclass
class LoopProject:
    project_id: str
    name: str
    created_at: str
    updated_at: str
    targets: list[LoopSkillTarget] = field(default_factory=list)
    surface: str = "turf"
    distance: str = "mile"
    style: str = "late_surger"
    quality_band: str = "ss_to_ue_plus"
    race_budget: int = 28
    g1_signature: list[str] = field(default_factory=list)
    carriers: list[LoopCarrier] = field(default_factory=list)
    transitions: list[LoopTransition] = field(default_factory=list)
    draft: LoopDraftTransition | None = None

    def __post_init__(self) -> None:
        self.project_id = str(self.project_id or "").strip()
        self.name = str(self.name or "").strip()
        self.surface = self.surface if self.surface in LOOP_SURFACES else "turf"
        self.distance = self.distance if self.distance in LOOP_DISTANCES else "mile"
        self.style = self.style if self.style in LOOP_STYLES else "late_surger"
        self.quality_band = (
            self.quality_band if self.quality_band in QUALITY_BANDS else "ss_to_ue_plus"
        )
        try:
            self.race_budget = max(1, min(40, int(self.race_budget)))
        except (TypeError, ValueError):
            self.race_budget = 28
        self.g1_signature = list(
            dict.fromkeys(
                str(name).strip()
                for name in self.g1_signature
                if str(name).strip()
            )
        )
        self.targets = [
            item if isinstance(item, LoopSkillTarget) else LoopSkillTarget.from_dict(item)
            for item in self.targets
            if isinstance(item, (LoopSkillTarget, dict))
        ]
        self.carriers = [
            item if isinstance(item, LoopCarrier) else LoopCarrier.from_dict(item)
            for item in self.carriers
            if isinstance(item, (LoopCarrier, dict))
        ]
        self.transitions = [
            item if isinstance(item, LoopTransition) else LoopTransition.from_dict(item)
            for item in self.transitions
            if isinstance(item, (LoopTransition, dict))
        ]
        if isinstance(self.draft, dict):
            self.draft = LoopDraftTransition.from_dict(self.draft)
        elif self.draft is not None and not isinstance(self.draft, LoopDraftTransition):
            self.draft = None
        if not self.project_id:
            raise ValueError("Un projet de looping doit posséder un identifiant.")
        if not self.name:
            raise ValueError("Donne un nom au projet de looping.")

    @classmethod
    def create(cls, name: str) -> LoopProject:
        now = utc_now()
        return cls(
            project_id=str(uuid4()),
            name=name,
            created_at=now,
            updated_at=now,
        )

    def touch(self) -> None:
        self.updated_at = utc_now()

    def upsert_carrier(self, carrier: LoopCarrier) -> None:
        for index, current in enumerate(self.carriers):
            if current.carrier_id == carrier.carrier_id:
                self.carriers[index] = carrier
                self.touch()
                return
        self.carriers.append(carrier)
        self.touch()

    def transition(self, transition_id: str) -> LoopTransition | None:
        return next(
            (item for item in self.transitions if item.transition_id == transition_id),
            None,
        )

    def active_trained_ids(self) -> set[int]:
        # Active carriers are protected. Pending parents are already promoted to
        # carriers by record_plan(), but include them explicitly for resilience
        # when loading older sidecars.
        result = {
            int(carrier.trained_chara_id)
            for carrier in self.carriers
            if carrier.active and carrier.trained_chara_id is not None
        }
        for transition in self.transitions:
            if not transition.active:
                continue
            result.update(
                {
                    transition.parent_1_trained_id,
                    transition.parent_2_trained_id,
                }
            )
        return {value for value in result if value > 0}

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "name": self.name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "targets": [target.to_dict() for target in self.targets],
            "surface": self.surface,
            "distance": self.distance,
            "style": self.style,
            "quality_band": self.quality_band,
            "race_budget": self.race_budget,
            "g1_signature": list(self.g1_signature),
            "carriers": [carrier.to_dict() for carrier in self.carriers],
            "transitions": [transition.to_dict() for transition in self.transitions],
            "draft": self.draft.to_dict() if self.draft is not None else None,
        }

    @classmethod
    def from_dict(cls, payload: object) -> LoopProject:
        data = payload if isinstance(payload, dict) else {}
        return cls(
            project_id=str(data.get("project_id") or ""),
            name=str(data.get("name") or ""),
            created_at=str(data.get("created_at") or utc_now()),
            updated_at=str(data.get("updated_at") or utc_now()),
            targets=[
                LoopSkillTarget.from_dict(item)
                for item in data.get("targets") or []
                if isinstance(item, dict)
            ],
            surface=str(data.get("surface") or "turf"),
            distance=str(data.get("distance") or "mile"),
            style=str(data.get("style") or "late_surger"),
            quality_band=str(data.get("quality_band") or "ss_to_ue_plus"),
            race_budget=int(data.get("race_budget") or 28),
            g1_signature=[str(item) for item in data.get("g1_signature") or []],
            carriers=[
                LoopCarrier.from_dict(item)
                for item in data.get("carriers") or []
                if isinstance(item, dict)
            ],
            transitions=[
                LoopTransition.from_dict(item)
                for item in data.get("transitions") or []
                if isinstance(item, dict)
            ],
            draft=LoopDraftTransition.from_dict(data.get("draft")),
        )


def new_transition(
    *,
    trainee: dict[str, Any],
    parent_1_trained_id: int,
    parent_2_trained_id: int,
    quality_band: str,
    plan: dict[str, Any],
    baseline_trained_ids: list[int] | set[int] | tuple[int, ...] = (),
) -> LoopTransition:
    return LoopTransition(
        transition_id=str(uuid4()),
        created_at=utc_now(),
        trainee_card_id=_integer(trainee.get("card_id")) or 0,
        trainee_chara_id=_integer(trainee.get("chara_id")) or 0,
        trainee_name=str(
            trainee.get("card_name") or trainee.get("uma_name") or "Trainee"
        ),
        parent_1_trained_id=int(parent_1_trained_id),
        parent_2_trained_id=int(parent_2_trained_id),
        quality_band=quality_band,
        plan=copy.deepcopy(plan),
        baseline_trained_ids=[
            int(value)
            for value in baseline_trained_ids
            if _integer(value) is not None and int(value) > 0
        ],
    )
