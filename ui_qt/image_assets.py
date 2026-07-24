from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QByteArray, QObject, QStandardPaths, QUrl, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from ui_qt.asset_catalog import image_cache_path, is_allowed_image_url


if TYPE_CHECKING:
    from ui_qt.context import AppContext


MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_CACHE_BYTES = 256 * 1024 * 1024


def default_image_cache_dir() -> Path:
    root = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation)
    if root:
        return Path(root) / "images"
    return Path.home() / ".cache" / "UmaLegacyLinker" / "images"


def online_images_enabled(context: AppContext) -> bool:
    return context.store.get("online_images", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


class ImageRepository(QObject):
    """Small asynchronous image loader with an application-owned disk cache.

    Only HTTPS assets from the explicit GameTora allowlist can be requested.
    Cached files remain available when online illustrations are disabled.
    """

    image_ready = Signal(str, object)
    image_failed = Signal(str)
    cache_changed = Signal()

    def __init__(
        self,
        cache_dir: str | Path | None = None,
        *,
        enabled: bool = True,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.cache_dir = Path(cache_dir or default_image_cache_dir())
        self.enabled = bool(enabled)
        self._manager = QNetworkAccessManager(self)
        self._pixmaps: dict[str, QPixmap] = {}
        self._pending: dict[str, QNetworkReply] = {}
        self._failed: set[str] = set()

    def set_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if self.enabled == enabled:
            return
        self.enabled = enabled
        if enabled:
            self._failed.clear()
            return
        pending = tuple(self._pending.values())
        self._pending.clear()
        for reply in pending:
            reply.abort()

    def pixmap(self, url: str | None) -> QPixmap | None:
        if not url or not is_allowed_image_url(url):
            return None
        cached = self._pixmaps.get(url)
        if cached is not None and not cached.isNull():
            return cached

        path = image_cache_path(self.cache_dir, url)
        if path.is_file():
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                self._pixmaps[url] = pixmap
                try:
                    os.utime(path, None)
                except OSError:
                    pass
                return pixmap
            try:
                path.unlink()
            except OSError:
                pass

        self.request(url)
        return None

    def request(self, url: str | None, *, retry: bool = False) -> None:
        if (
            not url
            or not self.enabled
            or not is_allowed_image_url(url)
            or url in self._pending
            or (url in self._failed and not retry)
        ):
            return
        if url in self._pixmaps:
            self.image_ready.emit(url, self._pixmaps[url])
            return
        path = image_cache_path(self.cache_dir, url)
        if path.is_file():
            pixmap = self.pixmap(url)
            if pixmap is not None:
                self.image_ready.emit(url, pixmap)
            return

        request = QNetworkRequest(QUrl(url))
        request.setRawHeader(
            QByteArray(b"User-Agent"), QByteArray(b"UmaLegacyLinker/Qt image cache")
        )
        request.setRawHeader(
            QByteArray(b"Accept"),
            QByteArray(b"image/avif,image/webp,image/png,image/*;q=0.8"),
        )
        request.setTransferTimeout(15_000)
        reply = self._manager.get(request)
        self._pending[url] = reply
        reply.finished.connect(lambda source=url, current=reply: self._finished(source, current))

    def _finished(self, url: str, reply: QNetworkReply) -> None:
        current = self._pending.get(url) is reply
        if current:
            self._pending.pop(url, None)
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                if current and self.enabled:
                    self._failed.add(url)
                    self.image_failed.emit(url)
                return
            if not current:
                return
            payload = bytes(reply.readAll())
            if not payload or len(payload) > MAX_IMAGE_BYTES:
                self._failed.add(url)
                self.image_failed.emit(url)
                return
            pixmap = QPixmap()
            if not pixmap.loadFromData(payload):
                self._failed.add(url)
                self.image_failed.emit(url)
                return

            try:
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                destination = image_cache_path(self.cache_dir, url)
                temporary = destination.with_suffix(".tmp")
                temporary.write_bytes(payload)
                temporary.replace(destination)
                self._trim_cache()
            except OSError:
                # A read-only or full cache must not prevent the visual itself.
                pass

            self._pixmaps[url] = pixmap
            self._failed.discard(url)
            self.image_ready.emit(url, pixmap)
            self.cache_changed.emit()
        finally:
            reply.deleteLater()

    def _trim_cache(self) -> None:
        files = [path for path in self.cache_dir.glob("*.img") if path.is_file()]
        sizes: list[tuple[float, int, Path]] = []
        total = 0
        for path in files:
            try:
                stat = path.stat()
            except OSError:
                continue
            total += stat.st_size
            sizes.append((stat.st_mtime, stat.st_size, path))
        for _mtime, size, path in sorted(sizes):
            if total <= MAX_CACHE_BYTES:
                break
            try:
                path.unlink()
            except OSError:
                continue
            total -= size

    def cache_stats(self) -> tuple[int, int]:
        count = 0
        size = 0
        if not self.cache_dir.is_dir():
            return count, size
        for path in self.cache_dir.glob("*.img"):
            try:
                size += path.stat().st_size
                count += 1
            except OSError:
                pass
        return count, size

    def clear_cache(self) -> None:
        pending = tuple(self._pending.values())
        self._pending.clear()
        for reply in pending:
            reply.abort()
        self._pixmaps.clear()
        self._failed.clear()
        if self.cache_dir.is_dir():
            for path in self.cache_dir.glob("*.img"):
                try:
                    path.unlink()
                except OSError:
                    pass
            for path in self.cache_dir.glob("*.tmp"):
                try:
                    path.unlink()
                except OSError:
                    pass
        self.cache_changed.emit()


def image_repository(context: AppContext) -> ImageRepository:
    repository = getattr(context, "_image_repository", None)
    if not isinstance(repository, ImageRepository):
        repository = ImageRepository(
            enabled=online_images_enabled(context),
            parent=context,
        )
        setattr(context, "_image_repository", repository)
    return repository


def set_online_images_enabled(context: AppContext, enabled: bool) -> None:
    context.store.update({"online_images": "1" if enabled else "0"})
    image_repository(context).set_enabled(enabled)
