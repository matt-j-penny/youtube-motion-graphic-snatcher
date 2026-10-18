from __future__ import annotations

import asyncio
import json
import shutil
import threading
import time
import uuid
from collections.abc import Callable

from .config import AppConfig, ConfigStore
from .deepgram import DeepgramClient
from .errors import CancelledError, SnatcherError
from .media import MediaPipeline
from .models import (
    TERMINAL_STAGES,
    CaptureRequest,
    JobRecord,
    JobStage,
    TranscriptResult,
)
from .notion import NotionClient
from .secrets import SecretStore


class JobManager:
    def __init__(
        self,
        config: AppConfig,
        config_store: ConfigStore,
        secret_store: SecretStore,
        *,
        media_factory: Callable[[], MediaPipeline] = MediaPipeline,
        deepgram_factory: Callable[[str], DeepgramClient] = DeepgramClient,
        notion_factory: Callable[..., NotionClient] = NotionClient,
    ):
        self.config = config
        self.config_store = config_store
        self.secret_store = secret_store
        self.media_factory = media_factory
        self.deepgram_factory = deepgram_factory
        self.notion_factory = notion_factory
        self.records: dict[str, JobRecord] = {}
        self.tasks: dict[str, asyncio.Task] = {}
        self.cancel_events: dict[str, threading.Event] = {}
        self._load_records()

    def create(self, request: CaptureRequest) -> JobRecord:
        if request.end_seconds - request.start_seconds > self.config.max_clip_duration_seconds:
            minutes = self.config.max_clip_duration_seconds / 60
            raise SnatcherError(
                f"Selections are limited to {minutes:g} minutes.",
                code="clip_too_long",
            )
        record = JobRecord(id=uuid.uuid4().hex, request=request)
        self.records[record.id] = record
        self.cancel_events[record.id] = threading.Event()
        self._persist(record)
        self.tasks[record.id] = asyncio.create_task(self._run(record))
        return record

    def get(self, job_id: str) -> JobRecord:
        record = self.records.get(job_id)
        if record is None:
            raise KeyError(job_id)
        return record

    def recent(self, limit: int = 20) -> list[JobRecord]:
        return sorted(
            self.records.values(),
            key=lambda record: record.created_at,
            reverse=True,
        )[:limit]

    def cancel(self, job_id: str) -> JobRecord:
        record = self.get(job_id)
        if record.stage in TERMINAL_STAGES:
            return record
        self.cancel_events.setdefault(job_id, threading.Event()).set()
        record.update(message="Cancelling…")
        self._persist(record)
        return record

    def retry(self, job_id: str) -> JobRecord:
        record = self.get(job_id)
        if record.stage != JobStage.FAILED:
            raise SnatcherError("Only failed jobs can be retried.", code="job_not_retryable")
        if not record.retryable:
            raise SnatcherError(
                "Fix the configuration error before retrying.",
                code="job_not_retryable",
            )
        record.error_code = None
        record.error_message = None
        record.retryable = False
        record.update(stage=JobStage.QUEUED, progress=0, message="Queued for retry")
        self.cancel_events[job_id] = threading.Event()
        self._persist(record)
        self.tasks[job_id] = asyncio.create_task(self._run(record))
        return record

    async def _run(self, record: JobRecord) -> None:
        job_dir = self.config_store.jobs_dir / record.id
        job_dir.mkdir(parents=True, exist_ok=True)
        cancel_event = self.cancel_events[record.id]

        def set_stage(stage: JobStage, progress: float, message: str) -> None:
            record.update(stage=stage, progress=progress, message=message)
            self._persist(record)

        try:
            deepgram_key = self.secret_store.get_deepgram_key()
            notion_token = self.secret_store.get_notion_token()
            if not deepgram_key:
                raise SnatcherError(
                    "Deepgram is not configured. Run `snatcher configure`.",
                    code="deepgram_not_configured",
                )
            if not notion_token or not self.config.notion_parent_page_id:
                raise SnatcherError(
                    "Notion is not configured. Run `snatcher configure`.",
                    code="notion_not_configured",
                )

            media = self.media_factory()
            set_stage(JobStage.VALIDATING, 0.02, "Validating selection")
            metadata = await asyncio.to_thread(
                media.extract_metadata, str(record.request.youtube_url)
            )
            record.metadata = metadata
            if record.request.end_seconds > metadata.duration + 0.25:
                raise SnatcherError(
                    "The end time is beyond the video duration.",
                    code="invalid_time_range",
                )
            if cancel_event.is_set():
                raise CancelledError()

            set_stage(JobStage.METADATA, 0.08, "Video metadata ready")
            media_path = await asyncio.to_thread(
                media.download_section,
                url=str(record.request.youtube_url),
                start_seconds=record.request.start_seconds,
                end_seconds=record.request.end_seconds,
                output_dir=job_dir,
                cancel_event=cancel_event,
                progress=lambda value, message: set_stage(
                    JobStage.DOWNLOADING, 0.1 + value * 0.28, message
                ),
            )
            media_duration = await asyncio.to_thread(media.probe_duration, media_path, cancel_event)
            frames = await asyncio.to_thread(
                media.extract_frames,
                media_path=media_path,
                requested_start=record.request.start_seconds,
                requested_end=record.request.end_seconds,
                media_duration=media_duration,
                cancel_event=cancel_event,
                progress=lambda value, message: set_stage(
                    JobStage.EXTRACTING, 0.38 + value * 0.18, message
                ),
            )
            record.frame_count = len(frames)
            audio_path = await asyncio.to_thread(
                media.extract_mp3,
                media_path=media_path,
                cancel_event=cancel_event,
            )

            if cancel_event.is_set():
                raise CancelledError()
            set_stage(JobStage.TRANSCRIBING, 0.58, "Transcribing with Deepgram")
            deepgram = self.deepgram_factory(deepgram_key)
            transcript: TranscriptResult = await deepgram.transcribe(
                audio_path,
                selected_start=record.request.start_seconds,
                language=record.request.language,
            )
            record.transcript_status = (
                "No speech detected" if not transcript.transcript else "Transcribed"
            )

            if cancel_event.is_set():
                raise CancelledError()
            set_stage(
                JobStage.CREATING_NOTION_PAGE,
                0.7,
                "Creating Notion entry",
            )
            notion = self.notion_factory(
                notion_token,
                self.config,
                self.config_store,
            )
            page_id, page_url = await notion.save_capture(
                job=record,
                metadata=metadata,
                request=record.request,
                frames=frames,
                transcript=transcript,
                progress_callback=lambda value, message: set_stage(
                    JobStage.UPLOADING_FRAMES, 0.72 + value * 0.24, message
                ),
            )
            record.notion_page_id = page_id
            record.notion_url = page_url
            set_stage(JobStage.FINALIZING, 0.98, "Cleaning temporary media")
            shutil.rmtree(job_dir, ignore_errors=True)
            set_stage(JobStage.COMPLETE, 1, "Saved to Notion")
        except CancelledError:
            shutil.rmtree(job_dir, ignore_errors=True)
            record.update(
                stage=JobStage.CANCELLED,
                progress=record.progress,
                message="Capture cancelled",
            )
            record.error_code = "cancelled"
            record.error_message = None
            record.retryable = False
            self._persist(record)
        except SnatcherError as exc:
            record.update(
                stage=JobStage.FAILED,
                progress=record.progress,
                message="Capture failed",
            )
            record.error_code = exc.code
            record.error_message = str(exc)
            record.retryable = exc.retryable
            self._persist(record)
        except Exception as exc:  # pragma: no cover - final safety net
            record.update(
                stage=JobStage.FAILED,
                progress=record.progress,
                message="Unexpected failure",
            )
            record.error_code = "unexpected_error"
            record.error_message = str(exc)
            record.retryable = True
            self._persist(record)

    def cleanup_expired(self) -> int:
        removed = 0
        cutoff = time.time() - self.config.failed_job_retention_seconds
        if not self.config_store.jobs_dir.exists():
            return 0
        for child in self.config_store.jobs_dir.iterdir():
            if child.is_dir() and child.stat().st_mtime < cutoff:
                shutil.rmtree(child, ignore_errors=True)
                removed += 1
        return removed

    def _persist(self, record: JobRecord) -> None:
        path = self.config_store.jobs_dir / f"{record.id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            record.model_dump_json(indent=2, exclude_none=True) + "\n",
            encoding="utf-8",
        )

    def _load_records(self) -> None:
        self.config_store.jobs_dir.mkdir(parents=True, exist_ok=True)
        for path in self.config_store.jobs_dir.glob("*.json"):
            try:
                record = JobRecord.model_validate_json(path.read_text(encoding="utf-8"))
                if record.stage not in TERMINAL_STAGES:
                    record.stage = JobStage.FAILED
                    record.message = "Interrupted by companion restart"
                    record.error_code = "interrupted"
                    record.error_message = "The companion stopped before this job completed."
                    record.retryable = True
                    self._persist(record)
                self.records[record.id] = record
            except (ValueError, json.JSONDecodeError):
                continue
