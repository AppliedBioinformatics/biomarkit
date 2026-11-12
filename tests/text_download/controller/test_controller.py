import pytest
from biomarkit.config import TMP_DIR
from biomarkit.text_download.controller.controller import Controller
from biomarkit.text_download.basemodels.publication import Publication
from biomarkit.text_download.database.database import insert_row, create_database

# Fixtures.
@pytest.fixture
def publications():
    pubs = []
    for i, doi in enumerate(["10.1037/arc14", "10.1037/arc15", "10.1037/arc16"]):
        pub = Publication(doi=doi, title=f"Test Publication {i}", publisher=f"TestPublisher {i}", year=2020)
        pubs.append(pub)

    return pubs

@pytest.fixture
def more_publications():
    pubs = []
    for i in range(100):
        publisher = ["Springer", "Elsevier", "Nature"][i % 3]
        pub = Publication(doi=f"10.1037/arc14{1}", title=f"Pub{i}", publisher=publisher, year=2020)
        pubs.append(pub)

    return pubs

def test_controller_instantiation(publications):
    controller = Controller(publication_list=publications)
    assert controller.publications == publications

def test_check_cache(publications):
    db_file = TMP_DIR / "tests_tmp" / "test.sqlite"

    if db_file.exists():
        db_file.unlink()

    controller = Controller(publication_list=publications)
    controller.cache = db_file
    controller._check_cache()
    assert db_file.exists()

def test__check_publications(publications):
    controller = Controller(publication_list=publications)
    assert controller._check_publications() is None

    # If empty:
    controller.publications = []
    with pytest.raises(AssertionError):
        assert controller._check_publications()

@pytest.fixture
def cached_db(tmp_path):
    """SQLite cache with rows for the first two publications, both pointing at files that exist."""
    db = tmp_path / "test.sqlite"
    create_database(db)
    for doi, name in (("10.1037/arc14", "Testfile1"), ("10.1037/arc15", "Testfile2")):
        (tmp_path / name).touch()
        insert_row(doi=doi, downloaded_from="TestPublisher", publication_filepath=str(tmp_path / name), db_path=db)
    return db

def test__update_publication_cache_state(publications, cached_db):
    controller = Controller(publication_list=publications)
    controller.cache = cached_db

    controller._update_publications_cache_state()

    # Assert that the files were matched and added to the relevant publications, publications[2] will be False.
    publications = controller.publications
    assert publications[0].is_cached == True
    assert publications[1].is_cached == True
    assert publications[2].is_cached == False

def test__update_publication_cache_state_missing_file_leaves_none(publications, cached_db, tmp_path, caplog):
    (tmp_path / "Testfile2").unlink()
    controller = Controller(publication_list=publications)
    controller.cache = cached_db

    with caplog.at_level("WARNING"):
        controller._update_publications_cache_state()

    assert publications[0].is_cached
    assert publications[1].publication_filepath is None
    assert "not found on disk" in caplog.text

def test_prepare_publications_for_router(publications, cached_db):
    controller = Controller(publication_list=publications)
    controller.cache = cached_db
    controller.prepare_publications_for_router()

    assert len(controller.cached_publications) == 2
    assert len(controller.uncached_publications) == 1
    assert int(len(controller.cached_publications)) + int(len(controller.uncached_publications)) == 3