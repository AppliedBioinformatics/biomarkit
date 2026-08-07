from unittest.mock import MagicMock, patch
from text_download.apis.map import api_clients
from text_download.apis.clients.opensource import OpenSourceClient
from text_download.apis.router import ApiRouter
from text_download.basemodels.publication import Publication
import pytest


@pytest.fixture
def publication_list():
    pubs = []

    for i in ["springer", "wiley", "nature"] * 3:
        pub = Publication(
            doi=f"10.1037/{i}",
            publisher=i,
            title=f"Test publication {i}",
            year=2020
        )

        pubs.append(pub)

    return pubs

@pytest.fixture
def mock_api_mapper():

    # Base class.
    class MockApiMapper:
        def __init__(self, publication_list, name):
            self.publication_list = publication_list
            self.name = name

    # Build some mock apis.
    class SpringerApi(MockApiMapper):
        def __init__(self, publication_list):
            super().__init__(publication_list, name="springer")

    class WileyApi(MockApiMapper):
        def __init__(self, publication_list):
            super().__init__(publication_list, name="wiley")

    class NatureApi(MockApiMapper):
        def __init__(self, publication_list):
            super().__init__(publication_list, name="nature")

    class NoPublicationsApi(MockApiMapper):
        def __init__(self, publication_list):
            super().__init__(publication_list, name="no_publications")

    return {
        "wiley": WileyApi,
        "nature": NatureApi,
        "springer": SpringerApi,
        "no_publications": NoPublicationsApi,
    }

@pytest.fixture
def mock_publisher_working(publication_list):
    mock_pub = MagicMock()
    mock_pub.name = "TestSuccessClient"

    mock_pub.publication_list = publication_list
    mock_pub.download_all_papers = MagicMock()

    return mock_pub

@pytest.fixture
def mock_publisher_failure(publication_list):
    """Returns a mock PublisherApi instance that raises an Exception."""
    mock_pub = MagicMock()
    mock_pub.name = "TestFailureClient"

    # Needs a list to calculate len()
    mock_pub.publication_list = [publication_list]

    # Mock the method to raise an exception
    mock_pub.download_all_papers = MagicMock(
        side_effect=RuntimeError("Connection failed")
    )

    return mock_pub

def test_init(publication_list):
    router = ApiRouter(publication_list)
    assert router.publication_list == publication_list
    assert len(router.publication_list) == len(publication_list)
    assert router.finished_publications == []
    assert router.unfinished_publications == []
    assert router.try_opensource == True

def test__sort_publications(publication_list):
    res = ApiRouter._sort_publications(publication_list)

    assert type(res) == dict
    assert len(res) == 3

    for k, v in res.items():
        assert type(k) == str
        assert type(v) == list
        assert len(v) == 3
        assert type(v[0]) == Publication

    for i in ["springer", "wiley", "nature"]:
        assert i in res.keys()

def test_map_to_nodes(mock_api_mapper, publication_list):

    # SetUp.
    pub_dict = ApiRouter._sort_publications(publication_list)
    api_nodes = ApiRouter._map_to_nodes(pub_dict=pub_dict, client_mapper=mock_api_mapper)

    # Asserts that publishers without any publications to download from aren't instantiated.
    assert len(api_nodes) == 3

    # Assert: nodes only correspond to actual publishers
    assert all(node.name in mock_api_mapper for node in api_nodes)

    # Assert: each node is correct type and publications have matching publisher.
    for node in api_nodes:
        expected_type = mock_api_mapper[node.name]
        assert isinstance(node, expected_type)
        assert all(pub.publisher == node.name for pub in node.publication_list)

def test_run_publisher_success(mock_publisher_working, caplog):
    """Verifies successful execution returns the publication list."""

    with caplog.at_level("INFO"):
        result = ApiRouter._run_publisher(mock_publisher_working)

        mock_publisher_working.download_all_papers.assert_called_once()

        assert result is mock_publisher_working.publication_list
        assert len(result) == 9

        assert "Starting client for TestSuccessClient: Will attempt download for 9" in caplog.text
        assert "Finished attempting downloads for TestSuccessClient." in caplog.text

def test_run_publisher_failure(mock_publisher_failure, caplog):
    with caplog.at_level("INFO"):

        result = ApiRouter._run_publisher(mock_publisher_failure)
        mock_publisher_failure.download_all_papers.assert_called_once()
        assert result is mock_publisher_failure.publication_list

        assert "Finished attempting downloads for TestFailureClient." not in caplog.text

def test__download_in_parallel_success(publication_list, caplog):

    # Fake publishers.
    pub1 = MagicMock()
    pub1.name = "pub1"
    pub1.publication_list = [publication_list[0]]

    pub2 = MagicMock()
    pub2.name = "pub2"
    pub2.publication_list = [publication_list[1]]

    # Build client list.
    client_list = [pub1, pub2]

    # Patch run_publisher
    with patch("text_download.apis.router.ApiRouter._run_publisher") as mock_run:
        mock_run.side_effect = [
            pub1.publication_list,
            pub2.publication_list,
        ]

        results = ApiRouter._download_in_parallel(client_list, max_threads=4)

    assert set(results.keys()) == {"pub1", "pub2"}
    assert results["pub1"] == [publication_list[0]]
    assert results["pub2"] == [publication_list[1]]

    assert mock_run.call_count == 2
    assert isinstance(results["pub1"][0], Publication)
    assert isinstance(results["pub2"][0], Publication)
    assert "Unhandled exception in TestFailureClient" not in caplog.text

def test__download_in_parallel_api_error(mock_publisher_failure, mock_publisher_working, caplog):

    # Return a side effect for a client run.
    def fake_run(client):
        if client is failing_client:
            raise RuntimeError("Connection failed")
        return client.publication_list

    # Make publication lists predictable
    working_client = mock_publisher_working
    working_client.publication_list = ["OK"]

    failing_client = mock_publisher_failure
    failing_client.publication_list = ["FAIL"]

    client_list = [working_client, failing_client]

    with patch("text_download.apis.router.ApiRouter._run_publisher", side_effect=fake_run) as mock_run:
        results = ApiRouter._download_in_parallel(client_list, max_threads=4)

        assert set(results.keys()) == {"TestSuccessClient", "TestFailureClient"}
        assert results["TestSuccessClient"] == ["OK"]
        assert results["TestFailureClient"] == []
        assert mock_run.call_count == 2
        assert "Unhandled exception in TestFailureClient" in caplog.text

def test_throw_at_opensource_success(publication_list):

    # Spawn a router.
    router = ApiRouter(publication_list)

    with patch('text_download.apis.router.OpenSourceClient') as MockOpenSourceClient:
        mock_client = MockOpenSourceClient.return_value
        successful_pubs = publication_list[:2]

        for pub in successful_pubs:
            pub.publication_filepath = "/file.txt"

        mock_client.publication_list = publication_list
        mock_client.download_all_papers = MagicMock()
        router.throw_at_opensource()

        # Asserts.
        MockOpenSourceClient.assert_called_once_with(publication_list=publication_list)
        mock_client.download_all_papers.assert_called_once()

        assert router.finished_publications == successful_pubs
        assert len(router.finished_publications) == 2
        for pub in router.finished_publications:
            assert pub.is_cached

def test_throw_at_opensource_empty_pub_list():
    router = ApiRouter([])

    with patch('text_download.apis.router.OpenSourceClient') as MockOpenSourceClient:
        client = MockOpenSourceClient.return_value
        client.publication_list = []
        client.download_all_papers = MagicMock()
        router.throw_at_opensource()

        MockOpenSourceClient.assert_called_once_with(publication_list=[])
        client.download_all_papers.assert_called_once()

        assert router.finished_publications == []

def test_throw_at_opensource_when_flag_false(publication_list):
    router = ApiRouter(publication_list)
    router.try_opensource = False

    with patch("text_download.apis.router.OpenSourceClient") as MockOS:
        router.throw_at_opensource()

    MockOS.assert_not_called()
    assert router.finished_publications == []

def test_disperse_to_nodes(publication_list, mock_api_mapper):

    # Test only a few pubs to keep things simple.
    for pub in publication_list:
        pub.publication_filepath = "/already/downloaded"

    # Make some publications pass so aren't routed to nodes.
    publication_list[0].publication_filepath = None
    publication_list[1].publication_filepath = None
    router = ApiRouter(publication_list)

    # Mock internal methods
    sorted_dict = {"springer": [publication_list[0]], "wiley": [publication_list[1]]}
    download_results = {"springer": [publication_list[0]], "wiley": [publication_list[1]]}
    node_list = [
        mock_api_mapper["springer"]([publication_list[0]]),
        mock_api_mapper["wiley"]([publication_list[1]])
    ]

    with patch.object(ApiRouter, "_sort_publications", return_value=sorted_dict) as mock_sort, \
         patch.object(ApiRouter, "_map_to_nodes", return_value=node_list) as mock_map, \
         patch.object(ApiRouter, "_download_in_parallel", return_value=download_results) as mock_parallel:

        results = router.disperse_to_nodes()

        mock_sort.assert_called_once_with([publication_list[0], publication_list[1]])
        mock_map.assert_called_once_with(pub_dict=sorted_dict, client_mapper=api_clients)
        mock_parallel.assert_called_once_with(client_list=node_list, max_threads=10)
        assert results == download_results

def test_finalise_publication_list(publication_list):
    router = ApiRouter(publication_list[:5])
    finished = publication_list[:3]
    unfinished = publication_list[3:5]

    router.unfinished_publications = unfinished
    download_results = {
        "springer": [finished[0]],
        "wiley": [finished[1]],
        "nature": [finished[2]]
    }

    all_pubs = router.finalise_publication_list(download_results)

    assert router.finished_publications == finished
    assert router.unfinished_publications == unfinished
    assert all_pubs == finished + unfinished


    #assert len(all_pubs) == len(router.finished_publications) + len(router.unfinished_publications)