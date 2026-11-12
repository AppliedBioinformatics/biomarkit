# Any new API client should be added here: publisher key -> (module path, class name). The router will handle the
# rest. Clients are imported on first access of `api_clients`, so importing this module stays cheap (no playwright
# or wiley_tdm import until a download actually starts).
_CLIENT_PATHS = {
    "wiley": ("biomarkit.text_download.apis.clients.wiley", "WileyClient"),
    "springer": ("biomarkit.text_download.apis.clients.springer", "SpringerClient"),
    "elsevier": ("biomarkit.text_download.apis.clients.elsevier", "ElsevierClient"),
    "mdpi": ("biomarkit.text_download.apis.clients.mdpi", "MdpiClient"),
    "frontiers": ("biomarkit.text_download.apis.clients.frontiers", "FrontiersClient"),
    "american_phytopathological_society": ("biomarkit.text_download.apis.clients.am_phyto_soc", "AmPhytoSocClient"),
    "taylor_and_francis": ("biomarkit.text_download.apis.clients.taylor_and_francis", "TaylorFrancisClient"),
    "copernicus": ("biomarkit.text_download.apis.clients.copernicus", "CopernicusClient"),
}

API_CLIENT_NAMES = frozenset(_CLIENT_PATHS)


def __getattr__(name):
    if name == "api_clients":
        from importlib import import_module
        clients = {key: getattr(import_module(module), cls) for key, (module, cls) in _CLIENT_PATHS.items()}
        globals()["api_clients"] = clients
        return clients
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
