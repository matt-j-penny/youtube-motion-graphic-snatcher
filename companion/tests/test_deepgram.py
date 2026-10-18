import httpx
import pytest

from snatcher.deepgram import DeepgramClient


@pytest.mark.asyncio
async def test_transcription_is_shifted_to_source_time(tmp_path) -> None:
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"fake mp3")

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Token test-key"
        assert request.url.params["model"] == "nova-3-general"
        return httpx.Response(
            200,
            json={
                "metadata": {"request_id": "request-123"},
                "results": {
                    "channels": [
                        {
                            "detected_language": "en",
                            "alternatives": [
                                {
                                    "transcript": "Animate the headline.",
                                    "confidence": 0.97,
                                }
                            ],
                        }
                    ],
                    "utterances": [
                        {
                            "start": 1.25,
                            "end": 3.5,
                            "transcript": "Animate the headline.",
                            "confidence": 0.96,
                        }
                    ],
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await DeepgramClient("test-key", client=client).transcribe(
            audio,
            selected_start=60,
        )

    assert result.transcript == "Animate the headline."
    assert result.language == "en"
    assert result.request_id == "request-123"
    assert result.utterances[0].start == 61.25
    assert result.utterances[0].end == 63.5
