"""Загрузка config.yaml. Пути ffmpeg/ffprobe резолвятся относительно корня проекта."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import List, Optional

import yaml
from pydantic import BaseModel, Field


def _app_dir() -> Path:
    """Корень установки. В frozen-режиме (PyInstaller) — рядом с .exe,
    иначе — рядом с этим файлом. Используется для config.yaml, bin/, .cache/."""
    if getattr(sys, "frozen", False) or hasattr(sys, "_MEIPASS"):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


PROJECT_ROOT = _app_dir()


def lib_id_for(path: Path) -> str:
    """Стабильный 8-символьный идентификатор библиотеки по абсолютному пути."""
    return hashlib.md5(str(path).encode("utf-8")).hexdigest()[:8]


class Config(BaseModel):
    # Legacy single-root, авто-мигрируется в media_roots.
    media_root: Optional[Path] = None
    media_roots: List[Path] = Field(default_factory=list)
    ffmpeg_path: Path
    ffprobe_path: Path
    host_ip: str
    port: int = 8000
    hevc_encoder: str = "h264_nvenc"
    video_extensions: List[str] = Field(
        default_factory=lambda: [".mkv", ".mp4", ".avi", ".m4v", ".mov", ".webm"]
    )

    def model_post_init(self, _ctx) -> None:
        if not self.ffmpeg_path.is_absolute():
            self.ffmpeg_path = (PROJECT_ROOT / self.ffmpeg_path).resolve()
        if not self.ffprobe_path.is_absolute():
            self.ffprobe_path = (PROJECT_ROOT / self.ffprobe_path).resolve()
        # Миграция: старое media_root → одна библиотека в media_roots
        if self.media_root is not None and not self.media_roots:
            self.media_roots = [self.media_root]
        self.media_roots = [p.resolve() for p in self.media_roots]
        self.video_extensions = [e.lower() for e in self.video_extensions]

    def libraries(self) -> dict[str, Path]:
        """{lib_id: absolute_path}. Порядок сохраняется."""
        return {lib_id_for(p): p for p in self.media_roots}


def load_config(path: Path | None = None) -> Config:
    cfg_path = path or (PROJECT_ROOT / "config.yaml")
    if not cfg_path.exists():
        raise FileNotFoundError(
            f"{cfg_path} не найден. Скопируй config.example.yaml в config.yaml."
        )
    with cfg_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return Config.model_validate(data)
