import pytest

from snatcher.config import AppConfig, ConfigStore
from snatcher.jobs import JobManager
from snatcher.models import (
    CaptureRequest,
    FrameArtifact,
    JobStage,
    TranscriptResult,
    VideoMetadata,
)


class FakeSecrets:
    def get_deepgram_key(self):
        return "deepgram"

    def get_notion_token(self):
        return "notion"


class FakeMedia:
    def extract_metadata(self, _url):
        return VideoMetadata(
            video_id="abc123",
            title="Test video",
            channel="Test channel",
            duration=120,
            canonical_url="https://www.youtube.com/watch?v=abc123",
        )

    def download_section(self, *, output_dir, progress, **_kwargs):
        progress(1, "Downloaded")
        path = output_dir / "segment.mp4"
        path.write_bytes(b"media")
        return path

    def probe_duration(self, _path, _cancel):
        return 10

    def extract_frames(self, *, media_path, progress, **_kwargs):
        frames = []
        for index in range(1, 11):
            path = media_path.parent / f"frame-{index}.jpg"
            path.write_bytes(b"image")
            frames.append(
                FrameArtifact(
                    path=path,
                    sequence=index,
                    clip_seconds=index - 0.5,
                    source_seconds=10 + index - 0.5,
                )
            )
            progress(index / 10, f"Frame {index}")
        return frames

    def extract_mp3(self, *, media_path, **_kwargs):
        path = media_path.parent / "audio.mp3"
        path.write_bytes(b"audio")
        return path


class FakeDeepgram:
    async def transcribe(self, *_args, **_kwargs):
        return TranscriptResult(transcript="Test transcript", language="en")


class FakeNotion:
    async def save_capture(self, *, job, progress_callback, **_kwargs):
        progress_callback(1, "Uploaded")
        return "page-id", "https://notion.so/page-id"


@pytest.mark.asyncio
async def test_job_manager_completes_pipeline(tmp_path) -> None:
    store = ConfigStore(tmp_path)
    config = AppConfig(notion_parent_page_id="parent-id", pair_token="pair")
    store.save(config)
    manager = JobManager(
        config,
        store,
        FakeSecrets(),
        media_factory=FakeMedia,
        deepgram_factory=lambda _key: FakeDeepgram(),
        notion_factory=lambda *_args: FakeNotion(),
    )
    record = manager.create(
        CaptureRequest(
            youtube_url="https://www.youtube.com/watch?v=abc123",
            start_seconds=10,
            end_seconds=20,
        )
    )
    await manager.tasks[record.id]

    assert record.stage == JobStage.COMPLETE
    assert record.progress == 1
    assert record.frame_count == 10
    assert record.notion_url == "https://notion.so/page-id"
    assert not (store.jobs_dir / record.id).exists()
    assert (store.jobs_dir / f"{record.id}.json").exists()
