import pytest
from unittest.mock import patch

from main import create_corpus


def test_create_corpus_builds_folder_structure(tmp_path):
    with patch("config.CORPORA_DIR", tmp_path):
        corpus_dir = create_corpus("my_corpus")

    assert corpus_dir == tmp_path / "my_corpus"
    for subdir in ("manuscripts", "markdowns", "results", "reports", "logs"):
        assert (corpus_dir / subdir).is_dir()


def test_create_corpus_is_idempotent(tmp_path):
    with patch("config.CORPORA_DIR", tmp_path):
        first = create_corpus("my_corpus")
        marker = first / "manuscripts" / "existing.pdf"
        marker.touch()

        second = create_corpus("my_corpus")

    assert first == second
    assert marker.exists()


def test_create_corpus_strips_whitespace(tmp_path):
    with patch("config.CORPORA_DIR", tmp_path):
        corpus_dir = create_corpus("  my_corpus  ")

    assert corpus_dir == tmp_path / "my_corpus"


@pytest.mark.parametrize("bad_name", ["", "   ", "a/b", "a\\b", "bad:name", "bad|name"])
def test_create_corpus_rejects_invalid_names(bad_name, tmp_path):
    with patch("config.CORPORA_DIR", tmp_path):
        with pytest.raises(ValueError, match="Invalid corpus name"):
            create_corpus(bad_name)