"""Загрузка config.yaml. Пути ffmpeg/ffprobe резолвятся относительно корня проекта."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List

import yaml
from pydantic import BaseModel, Field


def _app_dir() -> Path:
    """Корень установки. В frozen-режиме (PyInstaller) — рядом с .exe,
    иначе — рядом с этим файлом. Используется для config.yaml, bin/, .cache/."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


PROJECT_ROOT = _app_dir()


class Config(BaseModel):
    media_root: Path
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
        self.media_root = self.media_root.resolve()
        self.video_extensions = [e.lower() for e in self.video_extensions]


def load_config(path: Path | None = None) -> Config:
    cfg_path = path or (PROJECT_ROOT / "config.yaml")
    if not cfg_path.exists():
        raise FileNotFoundError(
            f"{cfg_path} не найден. Скопируй config.example.yaml в config.yaml."
        )
    with cfg_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return Config.model_validate(data)
