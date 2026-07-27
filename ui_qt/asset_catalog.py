from __future__ import annotations

import hashlib
from pathlib import Path
from urllib.parse import urlparse


GAMETORA_CHARACTER_BASE = "https://gametora.com/images/umamusume/characters"
GAMETORA_SUPPORT_BASE = "https://media.gametora.com/umamusume/supports/full/small"
GAMETORA_SKILL_BASE = "https://media.gametora.com/umamusume/skills/icon"
GAMETORA_RACE_BANNER_BASE = "https://media.gametora.com/umamusume/races/banners"
ALLOWED_IMAGE_HOSTS = frozenset({"gametora.com", "www.gametora.com", "media.gametora.com"})


def _positive_integer(value: object) -> int | None:
    try:
        integer = int(value)
    except (TypeError, ValueError):
        return None
    return integer if integer > 0 else None


def trainee_image_url(card_id: object) -> str | None:
    """Return GameTora's costume-aware square trainee artwork URL.

    Uma card IDs encode the base character in every digit except the final two;
    for example card ``100701`` uses ``chara_stand_1007_100701.png``.
    """

    resolved = _positive_integer(card_id)
    if resolved is None:
        return None
    character_id = resolved // 100
    if character_id <= 0:
        return None
    return f"{GAMETORA_CHARACTER_BASE}/chara_stand_{character_id}_{resolved}.png"


def support_card_image_url(support_id: object) -> str | None:
    """Return the small full-art support-card URL used by GameTora."""

    resolved = _positive_integer(support_id)
    if resolved is None:
        return None
    return f"{GAMETORA_SUPPORT_BASE}/{resolved}.png"


def skill_icon_url(skill_id: object) -> str | None:
    """Return a GameTora skill icon URL for a resolved MDB skill ID."""

    resolved = _positive_integer(skill_id)
    if resolved is None:
        return None
    return f"{GAMETORA_SKILL_BASE}/{resolved}.png"


def race_banner_url(race_id: object, language: str = "en") -> str | None:
    """Return GameTora's compact in-game race banner for a resolved race ID."""

    resolved = _positive_integer(race_id)
    if resolved is None:
        return None
    locale = "jp" if str(language).strip().lower().startswith("ja") else "en"
    return f"{GAMETORA_RACE_BANNER_BASE}/{locale}/{resolved}.png"


def is_allowed_image_url(url: str) -> bool:
    parsed = urlparse(str(url))
    return parsed.scheme == "https" and (parsed.hostname or "").lower() in ALLOWED_IMAGE_HOSTS


def image_cache_filename(url: str) -> str:
    """Stable opaque filename; source paths and query strings never reach disk."""

    return hashlib.sha256(str(url).encode("utf-8")).hexdigest() + ".img"


def image_cache_path(cache_dir: str | Path, url: str) -> Path:
    return Path(cache_dir) / image_cache_filename(url)
