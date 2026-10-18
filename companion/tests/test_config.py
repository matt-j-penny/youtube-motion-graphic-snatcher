from snatcher.config import ConfigStore, normalize_notion_id
from snatcher.timecode import format_timecode, sample_timestamps


def test_normalize_notion_id_from_url() -> None:
    value = normalize_notion_id("https://www.notion.so/My-Library-1234567890abcdef1234567890abcdef")
    assert value == "12345678-90ab-cdef-1234-567890abcdef"


def test_config_store_generates_and_persists_pair_token(tmp_path) -> None:
    store = ConfigStore(tmp_path)
    first = store.load()
    second = store.load()
    assert first.pair_token
    assert second.pair_token == first.pair_token
    assert store.path.stat().st_mode & 0o777 == 0o600


def test_sample_timestamps_use_interior_deciles() -> None:
    assert sample_timestamps(10, 20) == [
        10.5,
        11.5,
        12.5,
        13.5,
        14.5,
        15.5,
        16.5,
        17.5,
        18.5,
        19.5,
    ]
    assert format_timecode(75.25, milliseconds=True) == "01:15.250"
