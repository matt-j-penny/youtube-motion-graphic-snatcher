import shutil
import subprocess
import threading

import pytest

from snatcher.media import MediaPipeline


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is required")
def test_extracts_ten_frames_and_mp3_from_fixture(tmp_path) -> None:
    media = tmp_path / "fixture.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=640x360:rate=30:duration=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-y",
            str(media),
        ],
        check=True,
    )
    pipeline = MediaPipeline()
    cancel = threading.Event()
    duration = pipeline.probe_duration(media, cancel)
    frames = pipeline.extract_frames(
        media_path=media,
        requested_start=10,
        requested_end=12,
        media_duration=duration,
        cancel_event=cancel,
        progress=lambda *_args: None,
    )
    audio = pipeline.extract_mp3(media_path=media, cancel_event=cancel)

    assert len(frames) == 10
    assert all(frame.path.exists() and frame.path.stat().st_size > 0 for frame in frames)
    assert frames[0].source_seconds == 10.1
    assert frames[-1].source_seconds == 11.9
    assert audio.exists() and audio.stat().st_size > 0
