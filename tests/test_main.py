import pytest
from unittest.mock import patch

from main import create_corpus
from text_download.utils.generics import build_new_corpus


def test_create_corpus_builds_folder_structure(tmp_path):
    with patch("config.CORPORA_DIR", tmp_path):
        corpus_dir = create_corpus("my_corpus")

    assert corpus_dir == tmp_path / "my_corpus"
    for subdir in ("manuscripts", "intermediates", "results", "reports", "logs"):
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


# --- build_new_corpus ---

def test_build_new_corpus_creates_structure_and_copies_csv(tmp_path):
    scopus_csv = tmp_path / "scopus.csv"
    scopus_csv.write_text("doi,title\n10.1/x,Paper X")

    with patch("config.CORPORA_DIR", tmp_path):
        corpus_dir = build_new_corpus(name="test_corpus", scopus_file=scopus_csv, set_active=False)

    assert corpus_dir == tmp_path / "test_corpus"
    for subdir in ("manuscripts", "intermediates", "results", "reports", "logs"):
        assert (corpus_dir / subdir).is_dir()
    assert (corpus_dir / "scopus.csv").read_text() == "doi,title\n10.1/x,Paper X"


def test_build_new_corpus_raises_if_scopus_missing(tmp_path):
    with patch("config.CORPORA_DIR", tmp_path):
        with pytest.raises(FileNotFoundError, match="Scopus CSV not found"):
            build_new_corpus(name="test_corpus", scopus_file=tmp_path / "missing.csv", set_active=False)


def test_build_new_corpus_does_not_overwrite_existing_csv(tmp_path):
    scopus_csv = tmp_path / "scopus.csv"
    scopus_csv.write_text("new content")

    with patch("config.CORPORA_DIR", tmp_path):
        corpus_dir = build_new_corpus(name="test_corpus", scopus_file=scopus_csv, set_active=False)
        existing = corpus_dir / "scopus.csv"
        existing.write_text("original content")

        build_new_corpus(name="test_corpus", scopus_file=scopus_csv, set_active=False)

    assert existing.read_text() == "original content"


def test_build_new_corpus_set_active_updates_existing_secrets_env(tmp_path):
    scopus_csv = tmp_path / "scopus.csv"
    scopus_csv.write_text("doi,title")
    secrets = tmp_path / "secrets.env"
    secrets.write_text("CORPUS_NAME=old_corpus\nUSER_EMAIL=x@x.com\n")

    with patch("config.CORPORA_DIR", tmp_path), \
         patch("text_download.utils.generics._secrets_path", return_value=secrets):
        build_new_corpus(name="new_corpus", scopus_file=scopus_csv, set_active=True)

    updated = secrets.read_text(encoding="utf-8")
    assert "CORPUS_NAME=new_corpus" in updated
    assert "USER_EMAIL=x@x.com" in updated


def test_build_new_corpus_set_active_creates_secrets_env_if_absent(tmp_path):
    scopus_csv = tmp_path / "scopus.csv"
    scopus_csv.write_text("doi,title")
    secrets = tmp_path / "secrets.env"

    with patch("config.CORPORA_DIR", tmp_path), \
         patch("text_download.utils.generics._secrets_path", return_value=secrets):
        build_new_corpus(name="fresh_corpus", scopus_file=scopus_csv, set_active=True)

    assert "CORPUS_NAME=fresh_corpus" in secrets.read_text(encoding="utf-8")