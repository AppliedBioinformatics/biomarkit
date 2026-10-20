from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv
from os import getenv

# Source-checkout fallback only — resolves correctly in dev but points into site-packages when installed.
_REPO_ROOT = Path(__file__).resolve().parents[1]

# Resolve secrets.env: (1) BIOMARKIT_SECRETS env var, (2) cwd, (3) repo root (dev fallback).
_secrets_candidates = [
    Path(getenv("BIOMARKIT_SECRETS")) if getenv("BIOMARKIT_SECRETS") else None,
    Path.cwd() / "secrets.env",
    _REPO_ROOT / "secrets.env",
]
SECRETS_FILE = next((p for p in _secrets_candidates if p and p.exists()), None)
if SECRETS_FILE:
    load_dotenv(dotenv_path=SECRETS_FILE)

# Workspace root: users set BIOMARKIT_DIR in secrets.env or the environment;
# falls back to cwd so installed usage works without any extra configuration.
BASE_DIR = Path(getenv("BIOMARKIT_DIR", Path.cwd())).resolve()

# Default parent folder for corpora referenced by name in load_corpus().
CORPORA_DIR = BASE_DIR / "corpora"


@dataclass(frozen=True)
class CorpusPaths:
    """Folder layout of a single corpus."""
    root: Path

    @property
    def scopus_csv(self) -> Path:
        return self.root / "scopus.csv"

    @property
    def db(self) -> Path:
        return self.root / "sqlite.db"

    @property
    def download_dir(self) -> Path:
        return self.root / "manuscripts"

    @property
    def json_dir(self) -> Path:
        return self.root / "intermediates"

    @property
    def final_md_dir(self) -> Path:
        return self.root / "results"

    @property
    def report_dir(self) -> Path:
        return self.root / "reports"

    @property
    def log_dir(self) -> Path:
        return self.root / "logs"


# Active corpus — set at runtime by biomarkit.load_corpus().
_active_corpus: CorpusPaths | None = None


def set_active_corpus(root: Path) -> CorpusPaths:
    global _active_corpus
    _active_corpus = CorpusPaths(Path(root).resolve())
    return _active_corpus


def get_corpus() -> CorpusPaths:
    if _active_corpus is None:
        raise RuntimeError("No corpus loaded — call biomarkit.load_corpus(...) first.")
    return _active_corpus

# Shared scratch space (not corpus-specific).
TMP_DIR = BASE_DIR / "tmp"

# Client Parameters.
USER_EMAIL = getenv("USER_EMAIL")
WILEY_TDM_TOKEN = getenv("WILEY_TDM_TOKEN")
SPRINGER_API_KEY = getenv("SPRINGER_API_KEY")
ELSEVIER_API_KEY = getenv("ELSEVIER_API_KEY")

# LLM Settings - fallback section classifier, served by a local Ollama instance by default.
# Any OpenAI-compatible endpoint can be substituted via secrets.env.
LLM_BASE_URL = getenv("LLM_BASE_URL", "http://localhost:11434/v1")
LLM_MODEL_NAME = getenv("LLM_MODEL_NAME", "gemma3:12b")

# MinerU parsing tiers accepted by transform_text(mineru_tier=...). "basic" uses small models only;
# "standard" and "advanced" also run the MinerU VLM.
MINERU_TIER_CHOICES = ("basic", "standard", "advanced")

# MinerU remote VLM (optional). When MINERU_VLM_SERVER_URL is set in secrets.env, the VLM tiers send
# inference to this OpenAI-compatible server (e.g. vLLM serving MinerU2.5-Pro-2605-1.2B) instead of
# running the VLM locally. The API key is only needed if the server was started with one.
MINERU_VLM_SERVER_URL = getenv("MINERU_VLM_SERVER_URL")
MINERU_VLM_API_KEY = getenv("MINERU_VLM_API_KEY")

# Program settings (don't touch these unless you know what you are doing).
MAX_THREADS = 10
PLOTLY_THEME = "plotly_white"

# MAPS.
API_URL_TO_NAME = {
    # "opensource" is the open-source download client (preprint routes + Unpaywall fallback); its api_url is
    # the Unpaywall endpoint. The "unpaywall" key is kept for clients that do their own Unpaywall lookups.
    "opensource": "https://api.unpaywall.org/v2/",
    "unpaywall": "https://api.unpaywall.org/v2/",
    "wiley": "https://api.wiley.com/onlinelibrary/tdm/v1/",
    "springer": "https://link.springer.com",
    "elsevier": "https://api.elsevier.com/",
    "mdpi": "https://www.mdpi.com",
    "frontiers": "https://www.frontiersin.org/journals",
    "american_phytopathological_society": "https://apsjournals.apsnet.org",
    "taylor_and_francis": "https://www.tandfonline.com",
    "copernicus": "https://www.copernicus.org"
}

API_KEY_TO_NAME = {
    "opensource": "",
    "unpaywall": "",
    "wiley": WILEY_TDM_TOKEN,
    "springer": SPRINGER_API_KEY,
    "elsevier": ELSEVIER_API_KEY,
    "mdpi": "",
    "frontiers": "",
    "american_phytopathological_society": "",
    "taylor_and_francis": "",
    "copernicus": ""
}