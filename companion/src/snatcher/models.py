from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator


class JobStage(StrEnum):
    QUEUED = "queued"
    VALIDATING = "validating"
    METADATA = "metadata"
    DOWNLOADING = "downloading"
    EXTRACTING = "extracting"
    TRANSCRIBING = "transcribing"
    CREATING_NOTION_PAGE = "creating_notion_page"
    UPLOADING_FRAMES = "uploading_frames"
    FINALIZING = "finalizing"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STAGES = {JobStage.COMPLETE, JobStage.FAILED, JobStage.CANCELLED}


class CaptureRequest(BaseModel):
    youtube_url: HttpUrl
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    custom_title: str = Field(default="", max_length=200)
    tags: list[str] = Field(default_factory=list, max_length=30)
    notes: str = Field(default="", max_length=2000)
    language: str = Field(default="auto", max_length=32)

    @field_validator("youtube_url")
    @classmethod
    def validate_youtube_url(cls, value: HttpUrl) -> HttpUrl:
        host = (value.host or "").lower()
        if host not in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
            raise ValueError("Only normal youtube.com/watch URLs are supported.")
        if value.path != "/watch":
            raise ValueError("Only normal youtube.com/watch URLs are supported.")
        query = value.query or ""
        if "v=" not in query:
            raise ValueError("The YouTube URL is missing a video ID.")
        return value

    @model_validator(mode="after")
    def validate_range(self) -> CaptureRequest:
        if self.end_seconds <= self.start_seconds:
            raise ValueError("End time must be after start time.")
        if self.end_seconds - self.start_seconds < 0.5:
            raise ValueError("Select at least 0.5 seconds.")
        self.tags = list(dict.fromkeys(tag.strip()[:100] for tag in self.tags if tag.strip()))
        return self


class PairRequest(BaseModel):
    code: str = Field(min_length=6, max_length=16)


class VideoMetadata(BaseModel):
    video_id: str
    title: str
    channel: str
    duration: float
    canonical_url: str
    thumbnail_url: str | None = None


class FrameArtifact(BaseModel):
    path: Path
    sequence: int
    clip_seconds: float
    source_seconds: float


class TranscriptUtterance(BaseModel):
    start: float
    end: float
    transcript: str
    confidence: float | None = None


class TranscriptResult(BaseModel):
    transcript: str
    utterances: list[TranscriptUtterance] = Field(default_factory=list)
    language: str | None = None
    confidence: float | None = None
    request_id: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict, exclude=True)


class JobRecord(BaseModel):
    id: str
    request: CaptureRequest
    stage: JobStage = JobStage.QUEUED
    progress: float = Field(default=0, ge=0, le=1)
    message: str = "Queued"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: VideoMetadata | None = None
    frame_count: int = 0
    transcript_status: str | None = None
    notion_page_id: str | None = None
    notion_url: str | None = None
    notion_summary_saved: bool = False
    notion_uploaded_frames: int = 0
    notion_transcript_saved: bool = False
    error_code: str | None = None
    error_message: str | None = None
    retryable: bool = False

    def update(
        self,
        *,
        stage: JobStage | None = None,
        progress: float | None = None,
        message: str | None = None,
    ) -> None:
        if stage is not None:
            self.stage = stage
        if progress is not None:
            self.progress = max(0, min(1, progress))
        if message is not None:
            self.message = message
        self.updated_at = datetime.now(UTC)


class HealthResponse(BaseModel):
    status: str
    version: str
    ffmpeg: bool
    ffprobe: bool
    yt_dlp: bool
    deepgram_configured: bool
    notion_configured: bool
    notion_database_configured: bool
    pairing_required: bool
