from __future__ import annotations

import asyncio
import mimetypes
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from .config import AppConfig, ConfigStore
from .errors import SnatcherError
from .models import (
    CaptureRequest,
    FrameArtifact,
    JobRecord,
    TranscriptResult,
    VideoMetadata,
)
from .timecode import format_timecode

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2026-03-11"


def plain_rich_text(content: str, *, link: str | None = None) -> list[dict[str, Any]]:
    if not content:
        return []
    items: list[dict[str, Any]] = []
    for start in range(0, len(content), 1900):
        text: dict[str, Any] = {"content": content[start : start + 1900]}
        if link:
            text["link"] = {"url": link}
        items.append({"type": "text", "text": text})
    return items


def paragraph_blocks(content: str) -> list[dict[str, Any]]:
    content = content.strip()
    if not content:
        return [
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": plain_rich_text("No speech detected.")},
            }
        ]
    blocks: list[dict[str, Any]] = []
    for start in range(0, len(content), 1900):
        blocks.append(
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": plain_rich_text(content[start : start + 1900])},
            }
        )
    return blocks


class NotionClient:
    def __init__(
        self,
        token: str,
        config: AppConfig,
        config_store: ConfigStore,
        *,
        client: httpx.AsyncClient | None = None,
    ):
        self.token = token
        self.config = config
        self.config_store = config_store
        self._client = client
        self._rate_lock = asyncio.Lock()
        self._last_request_at = 0.0

    async def test_connection(self) -> dict[str, Any]:
        me = await self._request("GET", "/users/me")
        if self.config.notion_parent_page_id:
            await self._request("GET", f"/pages/{self.config.notion_parent_page_id}")
        if self.config.notion_data_source_id:
            await self._request("GET", f"/data_sources/{self.config.notion_data_source_id}")
        return me

    async def bootstrap_database(self) -> str:
        if self.config.notion_data_source_id:
            await self._request("GET", f"/data_sources/{self.config.notion_data_source_id}")
            return self.config.notion_data_source_id
        if not self.config.notion_parent_page_id:
            raise SnatcherError(
                "A Notion parent page has not been configured.",
                code="notion_parent_missing",
            )

        properties: dict[str, Any] = {
            "Name": {"title": {}},
            "Status": {
                "select": {
                    "options": [
                        {"name": "Processing", "color": "yellow"},
                        {"name": "Saved", "color": "green"},
                        {"name": "Failed", "color": "red"},
                    ]
                }
            },
            "YouTube URL": {"url": {}},
            "Video ID": {"rich_text": {}},
            "Video Title": {"rich_text": {}},
            "Channel": {"rich_text": {}},
            "Start Seconds": {"number": {"format": "number"}},
            "End Seconds": {"number": {"format": "number"}},
            "Start Time": {"rich_text": {}},
            "End Time": {"rich_text": {}},
            "Clip Duration": {"number": {"format": "number"}},
            "Tags": {"multi_select": {"options": []}},
            "Notes": {"rich_text": {}},
            "Language": {"rich_text": {}},
            "Confidence": {"number": {"format": "percent"}},
            "Captured At": {"date": {}},
            "Capture Job ID": {"rich_text": {}},
        }
        payload = {
            "parent": {
                "type": "page_id",
                "page_id": self.config.notion_parent_page_id,
            },
            "title": plain_rich_text("Motion Graphic Library"),
            "description": plain_rich_text(
                "YouTube motion graphic references captured by Video Graphic Snatcher."
            ),
            "is_inline": False,
            "icon": {"type": "emoji", "emoji": "🎞️"},
            "initial_data_source": {
                "title": plain_rich_text("Motion Graphic Library"),
                "properties": properties,
            },
        }
        database = await self._request("POST", "/databases", json=payload)
        database_id = database.get("id")
        data_source_id = self._find_data_source_id(database)
        if database_id and not data_source_id:
            retrieved = await self._request("GET", f"/databases/{database_id}")
            data_source_id = self._find_data_source_id(retrieved)
        if not database_id or not data_source_id:
            raise SnatcherError(
                "Notion created the database but did not return its data source ID.",
                code="notion_bootstrap_failed",
            )
        self.config.notion_database_id = database_id
        self.config.notion_data_source_id = data_source_id
        self.config.notion_database_url = database.get("url")
        self.config_store.save(self.config)
        return data_source_id

    async def save_capture(
        self,
        *,
        job: JobRecord,
        metadata: VideoMetadata,
        request: CaptureRequest,
        frames: list[FrameArtifact],
        transcript: TranscriptResult,
        progress_callback,
    ) -> tuple[str, str]:
        data_source_id = await self.bootstrap_database()
        page_title = request.custom_title.strip() or (
            f"{metadata.title} · {format_timecode(request.start_seconds)}–"
            f"{format_timecode(request.end_seconds)}"
        )
        page_properties = self._page_properties(
            page_title=page_title,
            job=job,
            metadata=metadata,
            request=request,
            transcript=transcript,
        )

        if job.notion_page_id:
            page = await self._request(
                "PATCH",
                f"/pages/{job.notion_page_id}",
                json={"properties": page_properties},
            )
        else:
            page = await self._request(
                "POST",
                "/pages",
                json={
                    "parent": {
                        "type": "data_source_id",
                        "data_source_id": data_source_id,
                    },
                    "icon": {"type": "emoji", "emoji": "🎬"},
                    "properties": page_properties,
                },
            )
            job.notion_page_id = page["id"]
            job.notion_url = page.get("url")
            progress_callback(0, "Notion entry created")

        if not job.notion_summary_saved:
            summary_blocks = self._summary_blocks(metadata, request)
            await self._append_blocks(job.notion_page_id, summary_blocks)
            job.notion_summary_saved = True
            progress_callback(0, "Notion entry prepared")

        for index, frame in enumerate(frames, start=1):
            if index <= job.notion_uploaded_frames:
                continue
            upload_id = await self._upload_file(frame.path)
            image_block = {
                "object": "block",
                "type": "image",
                "image": {
                    "type": "file_upload",
                    "file_upload": {"id": upload_id},
                    "caption": plain_rich_text(
                        f"Frame {frame.sequence:02d} · "
                        f"{format_timecode(frame.source_seconds, milliseconds=True)}"
                    ),
                },
            }
            await self._append_blocks(job.notion_page_id, [image_block])
            job.notion_uploaded_frames = index
            progress_callback(index / len(frames), f"Uploaded frame {index} of {len(frames)}")

        if not job.notion_transcript_saved:
            transcript_blocks = self._transcript_blocks(transcript)
            await self._append_blocks(job.notion_page_id, transcript_blocks)
            job.notion_transcript_saved = True
            progress_callback(1, "Transcript saved")
        await self._request(
            "PATCH",
            f"/pages/{job.notion_page_id}",
            json={
                "properties": {
                    "Status": {"select": {"name": "Saved"}},
                    "Captured At": {"date": {"start": datetime.now(UTC).isoformat()}},
                }
            },
        )
        return job.notion_page_id, page.get("url") or job.notion_url or ""

    def _page_properties(
        self,
        *,
        page_title: str,
        job: JobRecord,
        metadata: VideoMetadata,
        request: CaptureRequest,
        transcript: TranscriptResult,
    ) -> dict[str, Any]:
        return {
            "Name": {"title": plain_rich_text(page_title[:200])},
            "Status": {"select": {"name": "Processing"}},
            "YouTube URL": {"url": metadata.canonical_url},
            "Video ID": {"rich_text": plain_rich_text(metadata.video_id)},
            "Video Title": {"rich_text": plain_rich_text(metadata.title[:1900])},
            "Channel": {"rich_text": plain_rich_text(metadata.channel[:1900])},
            "Start Seconds": {"number": request.start_seconds},
            "End Seconds": {"number": request.end_seconds},
            "Start Time": {"rich_text": plain_rich_text(format_timecode(request.start_seconds))},
            "End Time": {"rich_text": plain_rich_text(format_timecode(request.end_seconds))},
            "Clip Duration": {"number": request.end_seconds - request.start_seconds},
            "Tags": {"multi_select": [{"name": tag[:100]} for tag in request.tags]},
            "Notes": {"rich_text": plain_rich_text(request.notes[:1900])},
            "Language": {"rich_text": plain_rich_text(transcript.language or "Unknown")},
            "Confidence": {"number": transcript.confidence},
            "Captured At": {"date": {"start": datetime.now(UTC).isoformat()}},
            "Capture Job ID": {"rich_text": plain_rich_text(job.id)},
        }

    def _summary_blocks(
        self,
        metadata: VideoMetadata,
        request: CaptureRequest,
    ) -> list[dict[str, Any]]:
        timestamped_url = f"{metadata.canonical_url}&t={int(request.start_seconds)}s"
        blocks: list[dict[str, Any]] = [
            {
                "object": "block",
                "type": "callout",
                "callout": {
                    "icon": {"type": "emoji", "emoji": "▶️"},
                    "rich_text": plain_rich_text(
                        (
                            f"{metadata.title} — {metadata.channel}\n"
                            f"{format_timecode(request.start_seconds)}–"
                            f"{format_timecode(request.end_seconds)}"
                        ),
                        link=timestamped_url,
                    ),
                },
            }
        ]
        if request.notes:
            blocks.extend(
                [
                    {
                        "object": "block",
                        "type": "heading_2",
                        "heading_2": {"rich_text": plain_rich_text("Notes")},
                    },
                    *paragraph_blocks(request.notes),
                ]
            )
        blocks.append(
            {
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": plain_rich_text("Frames")},
            }
        )
        return blocks

    def _transcript_blocks(self, transcript: TranscriptResult) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = [
            {
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": plain_rich_text("Transcript")},
            },
            *paragraph_blocks(transcript.transcript),
        ]
        if transcript.utterances:
            for chunk_index in range(0, len(transcript.utterances), 90):
                chunk = transcript.utterances[chunk_index : chunk_index + 90]
                suffix = "" if len(transcript.utterances) <= 90 else f" ({chunk_index // 90 + 1})"
                children = []
                for utterance in chunk:
                    line = (
                        f"[{format_timecode(utterance.start, milliseconds=True)}–"
                        f"{format_timecode(utterance.end, milliseconds=True)}] "
                        f"{utterance.transcript}"
                    )
                    children.append(
                        {
                            "object": "block",
                            "type": "paragraph",
                            "paragraph": {"rich_text": plain_rich_text(line)},
                        }
                    )
                blocks.append(
                    {
                        "object": "block",
                        "type": "toggle",
                        "toggle": {
                            "rich_text": plain_rich_text(f"Timestamped transcript{suffix}"),
                            "children": children,
                        },
                    }
                )
        details = (
            f"Model: nova-3-general · Language: {transcript.language or 'unknown'}"
            f" · Confidence: "
            f"{transcript.confidence:.1%}"
            if transcript.confidence is not None
            else f"Model: nova-3-general · Language: {transcript.language or 'unknown'}"
        )
        if transcript.request_id:
            details += f" · Deepgram request: {transcript.request_id}"
        blocks.extend(
            [
                {"object": "block", "type": "divider", "divider": {}},
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": plain_rich_text(details)},
                },
            ]
        )
        return blocks

    async def _upload_file(self, path: Path) -> str:
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        upload = await self._request(
            "POST",
            "/file_uploads",
            json={
                "mode": "single_part",
                "filename": path.name,
                "content_type": content_type,
            },
        )
        upload_id = upload.get("id")
        if not upload_id:
            raise SnatcherError(
                "Notion did not return a file upload ID.",
                code="notion_upload_failed",
                retryable=True,
            )
        await self._request(
            "POST",
            f"/file_uploads/{upload_id}/send",
            files={"file": (path.name, path.read_bytes(), content_type)},
        )
        return upload_id

    async def _append_blocks(
        self,
        page_id: str,
        blocks: list[dict[str, Any]],
    ) -> None:
        for start in range(0, len(blocks), 100):
            await self._request(
                "PATCH",
                f"/blocks/{page_id}/children",
                json={"children": blocks[start : start + 100]},
            )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response: httpx.Response | None = None
        async with self._client_context() as client:
            for attempt in range(4):
                async with self._rate_lock:
                    loop = asyncio.get_running_loop()
                    delay = 0.34 - (loop.time() - self._last_request_at)
                    if delay > 0:
                        await asyncio.sleep(delay)
                    response = await client.request(
                        method,
                        f"{NOTION_API_BASE}{path}",
                        headers={
                            "Authorization": f"Bearer {self.token}",
                            "Notion-Version": NOTION_VERSION,
                        },
                        json=json,
                        files=files,
                    )
                    self._last_request_at = loop.time()
                if response.status_code == 429:
                    retry_after = float(response.headers.get("Retry-After", 1))
                    await asyncio.sleep(max(1, retry_after))
                    continue
                if response.status_code >= 500 and attempt < 3:
                    await asyncio.sleep(2**attempt)
                    continue
                break

        assert response is not None
        if response.status_code in {401, 403}:
            raise SnatcherError(
                "Notion rejected the integration token or its capabilities.",
                code="notion_unauthorized",
            )
        if response.status_code == 404:
            raise SnatcherError(
                "Notion cannot access the configured page or database. "
                "Share it with the integration.",
                code="notion_not_shared",
            )
        if response.status_code >= 400:
            try:
                message = response.json().get("message")
            except ValueError:
                message = None
            raise SnatcherError(
                message or f"Notion request failed ({response.status_code}).",
                code="notion_failed",
                retryable=response.status_code == 429 or response.status_code >= 500,
            )
        return response.json()

    @staticmethod
    def _find_data_source_id(payload: dict[str, Any]) -> str | None:
        for key in ("data_sources", "data_source"):
            value = payload.get(key)
            if isinstance(value, list) and value:
                first = value[0]
                if isinstance(first, dict):
                    return first.get("id")
            if isinstance(value, dict):
                return value.get("id")
        initial = payload.get("initial_data_source")
        if isinstance(initial, dict):
            return initial.get("id")
        return None

    def _client_context(self):
        if self._client is not None:
            return _BorrowedClient(self._client)
        return httpx.AsyncClient(timeout=httpx.Timeout(60, connect=20))


class _BorrowedClient:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    async def __aenter__(self) -> httpx.AsyncClient:
        return self.client

    async def __aexit__(self, *_args) -> None:
        return None
