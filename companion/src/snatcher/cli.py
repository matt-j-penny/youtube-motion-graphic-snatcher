from __future__ import annotations

import argparse
import getpass
import sys

import uvicorn

from .api import create_app
from .config import ConfigStore, normalize_notion_id
from .secrets import SecretStore


def configure(config_store: ConfigStore, secret_store: SecretStore) -> int:
    config = config_store.load()
    print("Credentials are stored in macOS Keychain and are never written to this repository.")
    deepgram = getpass.getpass(
        "Deepgram API key (leave blank to keep the existing value): "
    ).strip()
    if deepgram:
        secret_store.set_deepgram_key(deepgram)
    notion = getpass.getpass(
        "Notion integration token (leave blank to keep the existing value): "
    ).strip()
    if notion:
        secret_store.set_notion_token(notion)
    current = f" [{config.notion_parent_page_id}]" if config.notion_parent_page_id else ""
    parent = input(f"Notion parent page URL or ID{current}: ").strip()
    if parent:
        try:
            config.notion_parent_page_id = normalize_notion_id(parent)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        config.notion_database_id = None
        config.notion_data_source_id = None
        config.notion_database_url = None
    max_minutes = input(
        f"Maximum clip minutes [{config.max_clip_duration_seconds / 60:g}]: "
    ).strip()
    if max_minutes:
        try:
            minutes = float(max_minutes)
            if minutes <= 0:
                raise ValueError
            config.max_clip_duration_seconds = minutes * 60
        except ValueError:
            print("Maximum clip minutes must be a positive number.", file=sys.stderr)
            return 2
    config_store.save(config)
    print("Configuration saved.")
    return 0


def status(config_store: ConfigStore, secret_store: SecretStore) -> int:
    config = config_store.load()
    print(f"Data directory: {config_store.data_dir}")
    print(f"Port: {config.port}")
    print(f"Deepgram key: {'configured' if secret_store.get_deepgram_key() else 'missing'}")
    print(f"Notion token: {'configured' if secret_store.get_notion_token() else 'missing'}")
    print(f"Notion parent: {config.notion_parent_page_id or 'missing'}")
    print(f"Notion data source: {config.notion_data_source_id or 'not created yet'}")
    return 0


def serve(config_store: ConfigStore, secret_store: SecretStore) -> int:
    config = config_store.load()
    app = create_app(config_store=config_store, secret_store=secret_store)
    print()
    print(f"Extension pairing code: {app.state.pairing_code}")
    print(f"Companion listening on http://127.0.0.1:{config.port}")
    print()
    uvicorn.run(app, host="127.0.0.1", port=config.port, log_level="info")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="snatcher")
    parser.add_argument(
        "command",
        choices=["configure", "serve", "status"],
        nargs="?",
        default="serve",
    )
    args = parser.parse_args()
    config_store = ConfigStore()
    secret_store = SecretStore()
    if args.command == "configure":
        return configure(config_store, secret_store)
    if args.command == "status":
        return status(config_store, secret_store)
    return serve(config_store, secret_store)


if __name__ == "__main__":
    raise SystemExit(main())
