from snatcher.notion import NotionClient, paragraph_blocks, plain_rich_text


def test_rich_text_and_paragraphs_split_large_content() -> None:
    content = "a" * 4000
    assert len(plain_rich_text(content)) == 3
    assert len(paragraph_blocks(content)) == 3


def test_finds_data_source_from_database_response() -> None:
    assert (
        NotionClient._find_data_source_id({"data_sources": [{"id": "data-source-id"}]})
        == "data-source-id"
    )
    assert (
        NotionClient._find_data_source_id({"initial_data_source": {"id": "initial-id"}})
        == "initial-id"
    )
