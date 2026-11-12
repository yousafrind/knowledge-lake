from pathlib import Path

import pytest

PDF = Path(__file__).parent / "fixtures_data" / "sample.pdf"


def test_docling_parses_sample_pdf() -> None:
    pytest.importorskip("docling")
    from lake_parsers.docling_backend import DoclingParser

    try:
        parsed = DoclingParser().parse(PDF.read_bytes(), "sample.pdf")
    except Exception as e:  # model weights are downloaded on first use; may be unreachable
        pytest.skip(f"docling could not run here: {type(e).__name__}")
    assert "replication" in parsed.markdown
