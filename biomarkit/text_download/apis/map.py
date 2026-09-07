from biomarkit.text_download.apis.clients.elsevier import ElsevierClient
from biomarkit.text_download.apis.clients.frontiers import FrontiersClient
from biomarkit.text_download.apis.clients.springer import SpringerClient
from biomarkit.text_download.apis.clients.wiley import WileyClient
from biomarkit.text_download.apis.clients.mdpi import MdpiClient
from biomarkit.text_download.apis.clients.am_phyto_soc import AmPhytoSocClient
from biomarkit.text_download.apis.clients.taylor_and_francis import TaylorFrancisClient
from biomarkit.text_download.apis.clients.copernicus import CopernicusClient

# Any new API clients should be added to this list as well as their publisher name to this list. Router will handle
# The rest.

api_clients = {
    "wiley": WileyClient,
    "springer": SpringerClient,
    "elsevier": ElsevierClient,
    "mdpi": MdpiClient,
    "frontiers": FrontiersClient,
    "american_phytopathological_society": AmPhytoSocClient,
    "taylor_and_francis": TaylorFrancisClient,
    "copernicus": CopernicusClient,
}