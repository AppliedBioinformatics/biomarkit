import pytest
from unittest.mock import patch

from biomarkit.text_download.apis.abc.publisher_api import PublisherApi


@pytest.mark.parametrize("module, cls, expected", [
    ("opensource", "OpenSourceClient", 1),
    ("elsevier", "ElsevierClient", 1),
    ("mdpi", "MdpiClient", 1),
    ("frontiers", "FrontiersClient", 5),
    ("springer", "SpringerClient", 1),
    ("taylor_and_francis", "TaylorFrancisClient", 10),
    ("am_phyto_soc", "AmPhytoSocClient", 10),
    ("copernicus", "CopernicusClient", 10),
])
def test_client_rate_limit_delay(module, cls, expected):
    from importlib import import_module
    client_cls = getattr(import_module(f"biomarkit.text_download.apis.clients.{module}"), cls)
    with patch.object(PublisherApi, "_test_url", return_value=True):
        client = client_cls(publication_list=[])
    assert client.rate_limit_delay == expected


def test_wiley_rate_limit_delay():
    from biomarkit.text_download.apis.clients.wiley import WileyClient
    with patch.object(WileyClient, "connect_wiley_tdm"):
        client = WileyClient(publication_list=[])
    assert client.rate_limit_delay == 10
