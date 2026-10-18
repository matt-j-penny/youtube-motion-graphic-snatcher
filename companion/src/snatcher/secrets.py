from __future__ import annotations

import os

import keyring

SERVICE_NAME = "video-graphic-snatcher"
DEEPGRAM_ACCOUNT = "deepgram-api-key"
NOTION_ACCOUNT = "notion-token"


class SecretStore:
    def __init__(self) -> None:
        self._deepgram_key: str | None = None
        self._notion_token: str | None = None
        self._deepgram_loaded = False
        self._notion_loaded = False

    def get_deepgram_key(self) -> str | None:
        if not self._deepgram_loaded:
            self._deepgram_key = keyring.get_password(SERVICE_NAME, DEEPGRAM_ACCOUNT)
            self._deepgram_loaded = True
        return self._deepgram_key or os.environ.get("DEEPGRAM_API_KEY")

    def set_deepgram_key(self, value: str) -> None:
        self._deepgram_key = value.strip()
        self._deepgram_loaded = True
        keyring.set_password(SERVICE_NAME, DEEPGRAM_ACCOUNT, self._deepgram_key)

    def get_notion_token(self) -> str | None:
        if not self._notion_loaded:
            self._notion_token = keyring.get_password(SERVICE_NAME, NOTION_ACCOUNT)
            self._notion_loaded = True
        return self._notion_token or os.environ.get("NOTION_TOKEN")

    def set_notion_token(self, value: str) -> None:
        self._notion_token = value.strip()
        self._notion_loaded = True
        keyring.set_password(SERVICE_NAME, NOTION_ACCOUNT, self._notion_token)
