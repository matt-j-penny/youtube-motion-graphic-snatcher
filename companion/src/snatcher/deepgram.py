from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from .errors import SnatcherError
from .models import TranscriptResult, TranscriptUtterance

DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"


class DeepgramClient:
    def __init__(
        self,
        api_key: str,
        *,
        client: httpx.AsyncClient | None = None,
    ):
        self.api_key = api_key
        self._client = client

    async def test_connection(self) -> None:
        if not self.api_key:
            raise SnatcherError("Deepgram is not configured.", code="deepgram_not_configured")
        # A zero-byte media request returns a media error only after authentication.
        async with self._client_context() as client:
            response = await client.post(
                DEEPGRAM_URL,
                headers={
                    "Authorization": f"Token {self.api_key}",
                    "Content-Type": "audio/mpeg",
                },
                content=b"",
                params={"model": "nova-3-general"},
            )
        if response.status_code in {401, 403}:
            raise SnatcherError(
                "Deepgram rejected the API key.",
                code="deepgram_invalid_key",
            )
        if response.status_code == 402:
            raise SnatcherError(
                "The Deepgram project has insufficient credit.",
                code="deepgram_no_credit",
            )

    async def transcribe(
        self,
        audio_path: Path,
        *,
        selected_start: float,
        language: str = "auto",
    ) -> TranscriptResult:
        params: dict[str, str] = {
            "model": "nova-3-general",
            "smart_format": "true",
            "utterances": "true",
            "punctuate": "true",
        }
        if language == "auto":
            params["detect_language"] = "true"
        else:
            params["language"] = language

        content = audio_path.read_bytes()
        response: httpx.Response | None = None
        async with self._client_context() as client:
            for attempt in range(3):
                response = await client.post(
                    DEEPGRAM_URL,
                    headers={
                        "Authorization": f"Token {self.api_key}",
                        "Content-Type": "audio/mpeg",
                    },
                    content=content,
                    params=params,
                )
                if response.status_code != 429 and response.status_code < 500:
                    break
                if attempt < 2:
                    await asyncio.sleep(2**attempt)

        assert response is not None
        if response.status_code == 401:
            raise SnatcherError(
                "Deepgram rejected the API key.",
                code="deepgram_invalid_key",
            )
        if response.status_code == 402:
            raise SnatcherError(
                "The Deepgram project has insufficient credit.",
                code="deepgram_no_credit",
            )
        if response.status_code >= 400:
            raise SnatcherError(
                f"Deepgram transcription failed ({response.status_code}).",
                code="deepgram_failed",
                retryable=response.status_code == 429 or response.status_code >= 500,
            )

        payload = response.json()
        results = payload.get("results") or {}
        channels = results.get("channels") or []
        channel = channels[0] if channels else {}
        alternatives = channel.get("alternatives") or []
        alternative = alternatives[0] if alternatives else {}
        transcript = str(alternative.get("transcript") or "").strip()

        utterances: list[TranscriptUtterance] = []
        for utterance in results.get("utterances") or []:
            text = str(utterance.get("transcript") or "").strip()
            if not text:
                continue
            utterances.append(
                TranscriptUtterance(
                    start=selected_start + float(utterance.get("start") or 0),
                    end=selected_start + float(utterance.get("end") or 0),
                    transcript=text,
                    confidence=utterance.get("confidence"),
                )
            )

        return TranscriptResult(
            transcript=transcript,
            utterances=utterances,
            language=channel.get("detected_language") or (None if language == "auto" else language),
            confidence=alternative.get("confidence"),
            request_id=(payload.get("metadata") or {}).get("request_id"),
            raw=payload,
        )

    def _client_context(self):
        if self._client is not None:
            return _BorrowedClient(self._client)
        return httpx.AsyncClient(timeout=httpx.Timeout(180, connect=20))


class _BorrowedClient:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    async def __aenter__(self) -> httpx.AsyncClient:
        return self.client

    async def __aexit__(self, *_args) -> None:
        return None
