"""ffprobe + ffmpeg pipe.

Логика:
1. probe() читает кодек видео и список аудиодорожек.
2. make_session() решает direct / audio-only / transcode, оценивает суммарный битрейт
   и длительность — этого хватает, чтобы Chromecast мог делать seek.
3. open_stream() стартует ffmpeg-процесс, выдающий fragmented MP4 в stdout.
   При seek (Range-запрос с не-нулевого байта) ffmpeg рестартуется с -ss <время>.
   Маппинг байт↔время — через средний битрейт, это приближение, но достаточное.

Один ffmpeg на сессию. Сессии живут в реестре в main.py; здесь только примитивы.
"""
from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional

from config import Config

logger = logging.getLogger(__name__)

# Кодеки видео, которые Chromecast играет нативно (без транскода).
DIRECT_VIDEO_CODECS = {"h264"}

# Аудиокодеки, которые Chromecast играет нативно.
DIRECT_AUDIO_CODECS = {"aac", "mp3", "ac3", "eac3"}

OUTPUT_MIME = "video/mp4"

# Дефолтный целевой битрейт для транскода (бит/с). 6 Mbps хватает для 1080p H.264.
TRANSCODE_VIDEO_BITRATE = 6_000_000

# Битрейт AAC при перекодировании аудио (бит/с).
TRANSCODE_AUDIO_BITRATE = 192_000


@dataclass
class AudioTrack:
    index: int               # абсолютный stream index в файле (ffmpeg -map 0:<index>)
    audio_index: int         # порядковый номер среди аудио (0,1,2...) — для UI
    codec: str
    lang: Optional[str]
    title: Optional[str]
    channels: Optional[int]


@dataclass
class ProbeResult:
    duration: float
    video_codec: str
    audio_tracks: list[AudioTrack]
    container_bitrate: Optional[int]  # бит/с, если ffprobe смог посчитать


@dataclass
class StreamSession:
    token: str
    path: Path
    audio_track: AudioTrack
    video_codec: str
    duration: float
    mode: str                 # 'direct' | 'audio-transcode' | 'video-transcode'
    estimated_bitrate: int    # бит/с — для seek-маппинга
    title: str
    process: Optional[subprocess.Popen] = field(default=None, repr=False)

    @property
    def estimated_size(self) -> int:
        return int(self.estimated_bitrate * self.duration / 8)


class Streamer:
    def __init__(self, config: Config) -> None:
        self.config = config

    # --- probe ---------------------------------------------------------------

    def probe(self, path: Path) -> ProbeResult:
        cmd = [
            str(self.config.ffprobe_path),
            "-v", "error",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(path),
        ]
        logger.debug("ffprobe: %s", cmd)
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)

        duration = float(data.get("format", {}).get("duration", 0) or 0)
        container_bitrate_raw = data.get("format", {}).get("bit_rate")
        container_bitrate = int(container_bitrate_raw) if container_bitrate_raw else None

        video_codec = ""
        audio_tracks: list[AudioTrack] = []
        audio_counter = 0

        for stream in data.get("streams", []):
            ctype = stream.get("codec_type")
            if ctype == "video" and not video_codec:
                video_codec = (stream.get("codec_name") or "").lower()
            elif ctype == "audio":
                tags = stream.get("tags", {}) or {}
                audio_tracks.append(
                    AudioTrack(
                        index=stream["index"],
                        audio_index=audio_counter,
                        codec=(stream.get("codec_name") or "").lower(),
                        lang=tags.get("language"),
                        title=tags.get("title"),
                        channels=stream.get("channels"),
                    )
                )
                audio_counter += 1

        return ProbeResult(
            duration=duration,
            video_codec=video_codec,
            audio_tracks=audio_tracks,
            container_bitrate=container_bitrate,
        )

    # --- session -------------------------------------------------------------

    def make_session(
        self,
        token: str,
        path: Path,
        audio_index: int,
        probe: Optional[ProbeResult] = None,
    ) -> StreamSession:
        probe = probe or self.probe(path)
        if not probe.audio_tracks:
            raise ValueError(f"В файле нет аудиодорожек: {path}")
        if audio_index < 0 or audio_index >= len(probe.audio_tracks):
            raise ValueError(f"audio_index {audio_index} вне диапазона")
        track = probe.audio_tracks[audio_index]

        video_ok = probe.video_codec in DIRECT_VIDEO_CODECS
        audio_ok = track.codec in DIRECT_AUDIO_CODECS

        if video_ok and audio_ok:
            mode = "direct"
        elif video_ok and not audio_ok:
            mode = "audio-transcode"
        else:
            mode = "video-transcode"

        if mode == "video-transcode":
            estimated = TRANSCODE_VIDEO_BITRATE + TRANSCODE_AUDIO_BITRATE
        elif mode == "audio-transcode":
            video_br = probe.container_bitrate or 6_000_000
            estimated = video_br + TRANSCODE_AUDIO_BITRATE
        else:
            estimated = probe.container_bitrate or 6_000_000

        return StreamSession(
            token=token,
            path=path,
            audio_track=track,
            video_codec=probe.video_codec,
            duration=probe.duration,
            mode=mode,
            estimated_bitrate=estimated,
            title=path.stem,
        )

    # --- ffmpeg --------------------------------------------------------------

    def _build_cmd(self, session: StreamSession, start_seconds: float) -> list[str]:
        cmd: list[str] = [str(self.config.ffmpeg_path), "-loglevel", "error", "-nostdin"]
        if start_seconds > 0:
            # -ss перед -i — быстрый seek по ключевым кадрам.
            cmd += ["-ss", f"{start_seconds:.3f}"]
        cmd += ["-i", str(session.path)]

        cmd += ["-map", "0:v:0", "-map", f"0:{session.audio_track.index}", "-sn"]

        if session.mode == "direct":
            cmd += ["-c:v", "copy", "-c:a", "copy"]
        elif session.mode == "audio-transcode":
            cmd += [
                "-c:v", "copy",
                "-c:a", "aac", "-b:a", str(TRANSCODE_AUDIO_BITRATE), "-ac", "2",
            ]
        else:  # video-transcode
            cmd += [
                "-c:v", self.config.hevc_encoder,
                "-preset", "fast",
                "-b:v", str(TRANSCODE_VIDEO_BITRATE),
                "-maxrate", str(TRANSCODE_VIDEO_BITRATE),
                "-bufsize", str(TRANSCODE_VIDEO_BITRATE * 2),
                "-pix_fmt", "yuv420p",
            ]
            if session.audio_track.codec in DIRECT_AUDIO_CODECS:
                cmd += ["-c:a", "copy"]
            else:
                cmd += [
                    "-c:a", "aac", "-b:a", str(TRANSCODE_AUDIO_BITRATE), "-ac", "2",
                ]

        cmd += [
            "-movflags", "frag_keyframe+empty_moov+default_base_moof+faststart",
            "-f", "mp4",
            "pipe:1",
        ]
        return cmd

    def byte_to_seconds(self, session: StreamSession, byte_offset: int) -> float:
        if session.estimated_bitrate <= 0:
            return 0.0
        seconds = byte_offset * 8 / session.estimated_bitrate
        return max(0.0, min(seconds, max(0.0, session.duration - 1.0)))

    def open_stream(
        self,
        session: StreamSession,
        start_byte: int = 0,
        chunk_size: int = 64 * 1024,
    ) -> Iterator[bytes]:
        """Стартует ffmpeg и итерирует чанки stdout. Процесс убивается, если генератор закрыт."""
        start_seconds = self.byte_to_seconds(session, start_byte)
        cmd = self._build_cmd(session, start_seconds)
        logger.info("ffmpeg start: token=%s start=%.1fs mode=%s", session.token, start_seconds, session.mode)
        logger.debug("ffmpeg cmd: %s", " ".join(cmd))

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        session.process = proc

        try:
            assert proc.stdout is not None
            while True:
                chunk = proc.stdout.read(chunk_size)
                if not chunk:
                    break
                yield chunk
        finally:
            self._terminate(proc)
            if session.process is proc:
                session.process = None

    @staticmethod
    def _terminate(proc: subprocess.Popen) -> None:
        if proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
            except Exception:
                pass

    @staticmethod
    def terminate_session(session: StreamSession) -> None:
        if session.process is not None:
            Streamer._terminate(session.process)
            session.process = None
