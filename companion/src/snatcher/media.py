from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

import yt_dlp

from .errors import CancelledError, SnatcherError
from .models import FrameArtifact, VideoMetadata
from .timecode import format_timecode, sample_timestamps

ProgressCallback = Callable[[float, str], None]


class MediaPipeline:
    def __init__(
        self,
        *,
        ffmpeg_path: str | None = None,
        ffprobe_path: str | None = None,
    ):
        self.ffmpeg_path = ffmpeg_path or shutil.which("ffmpeg") or "ffmpeg"
        self.ffprobe_path = ffprobe_path or shutil.which("ffprobe") or "ffprobe"

    def extract_metadata(self, url: str) -> VideoMetadata:
        options = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "ignoreconfig": True,
            "skip_download": True,
        }
        try:
            with yt_dlp.YoutubeDL(options) as downloader:
                info = downloader.extract_info(url, download=False)
        except Exception as exc:
            raise SnatcherError(
                "YouTube metadata could not be read. yt-dlp may need updating.",
                code="youtube_metadata_failed",
                retryable=True,
            ) from exc

        if not info or info.get("_type") == "playlist":
            raise SnatcherError(
                "Only a single normal YouTube video is supported.",
                code="unsupported_video",
            )
        if info.get("is_live") or info.get("live_status") in {"is_live", "is_upcoming"}:
            raise SnatcherError(
                "Livestreams and upcoming videos are not supported.",
                code="unsupported_video",
            )
        duration = float(info.get("duration") or 0)
        if duration <= 0:
            raise SnatcherError(
                "The video duration could not be determined.",
                code="missing_duration",
            )
        video_id = str(info.get("id") or "")
        if not video_id:
            raise SnatcherError("The YouTube video ID is missing.", code="missing_video_id")
        return VideoMetadata(
            video_id=video_id,
            title=str(info.get("title") or "Untitled YouTube video"),
            channel=str(info.get("channel") or info.get("uploader") or "Unknown channel"),
            duration=duration,
            canonical_url=str(
                info.get("webpage_url") or f"https://www.youtube.com/watch?v={video_id}"
            ),
            thumbnail_url=info.get("thumbnail"),
        )

    def download_section(
        self,
        *,
        url: str,
        start_seconds: float,
        end_seconds: float,
        output_dir: Path,
        cancel_event: threading.Event,
        progress: ProgressCallback,
    ) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        for stale in output_dir.glob("segment.*"):
            stale.unlink(missing_ok=True)
        duration = end_seconds - start_seconds
        section = f"*{start_seconds:.3f}-{end_seconds:.3f}"
        command = [
            sys.executable,
            "-m",
            "yt_dlp",
            "--ignore-config",
            "--no-playlist",
            "--download-sections",
            section,
            "--force-keyframes-at-cuts",
            "--format",
            "bv*[height<=1080]+ba/b[height<=1080]",
            "--merge-output-format",
            "mp4",
            "--no-warnings",
            "--newline",
            "--output",
            str(output_dir / "segment.%(ext)s"),
            url,
        ]
        progress(0.05, f"Downloading {format_timecode(duration)} from YouTube")
        self._run(command, output_dir / "yt-dlp.log", cancel_event)
        candidates = [
            path
            for path in output_dir.glob("segment.*")
            if path.suffix.lower() not in {".part", ".ytdl", ".log"}
        ]
        if not candidates:
            raise SnatcherError(
                "yt-dlp finished without producing a media file.",
                code="youtube_download_failed",
                retryable=True,
            )
        media_path = max(candidates, key=lambda path: path.stat().st_size)
        progress(1, "Selected section downloaded")
        return media_path

    def probe_duration(self, media_path: Path, cancel_event: threading.Event) -> float:
        command = [
            self.ffprobe_path,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(media_path),
        ]
        log_path = media_path.parent / "ffprobe.log"
        self._run(command, log_path, cancel_event)
        try:
            data = json.loads(log_path.read_text(encoding="utf-8") or "{}")
            duration = float(data["format"]["duration"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise SnatcherError(
                "FFprobe could not verify the downloaded section.",
                code="invalid_media",
            ) from exc
        if duration <= 0:
            raise SnatcherError("The downloaded section is empty.", code="invalid_media")
        return duration

    def extract_frames(
        self,
        *,
        media_path: Path,
        requested_start: float,
        requested_end: float,
        media_duration: float,
        cancel_event: threading.Event,
        progress: ProgressCallback,
    ) -> list[FrameArtifact]:
        requested_times = sample_timestamps(requested_start, requested_end, 10)
        local_times = sample_timestamps(0, media_duration, 10)
        frames: list[FrameArtifact] = []
        for index, (source_time, clip_time) in enumerate(
            zip(requested_times, local_times, strict=True),
            start=1,
        ):
            if cancel_event.is_set():
                raise CancelledError()
            frame_timecode = format_timecode(source_time, milliseconds=True).replace(":", "-")
            output = media_path.parent / (f"frame-{index:02d}_{frame_timecode}.jpg")
            command = [
                self.ffmpeg_path,
                "-v",
                "error",
                "-ss",
                f"{clip_time:.6f}",
                "-i",
                str(media_path),
                "-frames:v",
                "1",
                "-vf",
                "scale='min(1920,iw)':-2",
                "-q:v",
                "2",
                "-y",
                str(output),
            ]
            self._run(command, media_path.parent / f"ffmpeg-frame-{index:02d}.log", cancel_event)
            if not output.exists() or output.stat().st_size == 0:
                raise SnatcherError(
                    f"FFmpeg did not create frame {index}.",
                    code="frame_extraction_failed",
                )
            frames.append(
                FrameArtifact(
                    path=output,
                    sequence=index,
                    clip_seconds=clip_time,
                    source_seconds=source_time,
                )
            )
            progress(index / 10, f"Extracted frame {index} of 10")
        return frames

    def extract_mp3(
        self,
        *,
        media_path: Path,
        cancel_event: threading.Event,
    ) -> Path:
        output = media_path.parent / "audio.mp3"
        command = [
            self.ffmpeg_path,
            "-v",
            "error",
            "-i",
            str(media_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-b:a",
            "64k",
            "-map_metadata",
            "-1",
            "-y",
            str(output),
        ]
        self._run(command, media_path.parent / "ffmpeg-audio.log", cancel_event)
        if not output.exists() or output.stat().st_size == 0:
            raise SnatcherError(
                "FFmpeg did not create the transcription MP3.",
                code="audio_extraction_failed",
            )
        return output

    @staticmethod
    def _run(
        command: list[str],
        log_path: Path,
        cancel_event: threading.Event,
    ) -> None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("w+", encoding="utf-8") as log:
            process = subprocess.Popen(
                command,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
            )
            while process.poll() is None:
                if cancel_event.is_set():
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=3)
                    raise CancelledError()
                time.sleep(0.15)
            log.flush()
            if process.returncode != 0:
                log.seek(0)
                details = log.read()[-3000:].strip()
                message = details.splitlines()[-1] if details else "Media command failed."
                raise SnatcherError(
                    message,
                    code="media_command_failed",
                    retryable="HTTP Error" in details or "timed out" in details.lower(),
                )
