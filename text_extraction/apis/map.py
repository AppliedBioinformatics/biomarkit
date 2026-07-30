from text_extraction.apis.clients.elsevier import ElsevierClient
from text_extraction.apis.clients.frontiers import FrontiersClient
from text_extraction.apis.clients.springer import SpringerClient
from text_extraction.apis.clients.wiley import WileyClient
from text_extraction.apis.clients.mdpi import MdpiClient
from text_extraction.apis.clients.am_phyto_soc import AmPhytoSocClient
from text_extraction.apis.clients.taylor_and_francis import TaylorFrancisClient
from text_extraction.apis.clients.copernicus import CopernicusClient

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