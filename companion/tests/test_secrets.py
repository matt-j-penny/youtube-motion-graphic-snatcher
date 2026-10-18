from snatcher.secrets import SecretStore


def test_keychain_takes_precedence_over_environment(monkeypatch) -> None:
    monkeypatch.setenv("DEEPGRAM_API_KEY", "environment-key")
    monkeypatch.setattr(
        "snatcher.secrets.keyring.get_password",
        lambda *_args: "keychain-key",
    )

    assert SecretStore().get_deepgram_key() == "keychain-key"


def test_environment_is_used_when_keychain_is_empty(monkeypatch) -> None:
    monkeypatch.setenv("DEEPGRAM_API_KEY", "environment-key")
    monkeypatch.setattr(
        "snatcher.secrets.keyring.get_password",
        lambda *_args: None,
    )

    assert SecretStore().get_deepgram_key() == "environment-key"
