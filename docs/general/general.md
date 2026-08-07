# Documentation for general usage.

----
## Installation.
The easiest way to install the package is using [pip](https://pip.pypa.io/en/stable/installation/) and [uv](https://docs.astral.sh/uv/getting-started/installation/).
```bash
pip install --upgrade pip
pip install uv
uv pip install biomarkit
```

## Generating a new corpus for download.
Biomarkit takes a SCOPUS search export in .CSV format as an input. If you are unfamiliar with the process of generating
this file, follow the instructions below:

1) Write your SCOPUS query - tips available [here](https://www.scopus.com/standard/help.uri?topic=11365&anchor=tips).
2) Run your search [here]([https://www.scopus.com/search/form.uri?display=advanced]).
3) On the results page, add any additional filters you wish to apply using the right hand column, then click this box to 
select all results: ![]()
4) Next to the select all button, click "Export", then select "CSV", then select tick the boxes as shown below:
5) Wait for the export to complete, rename the downloaded CSV file to `scopus.csv`.
6) Run the function below to generate a new `biomarkit` corpus:

```python
from main import create_corpus
create_corpus(name="my_new_corpus")
```
7) Move your the `scopus.csv` file into the new corpus folder. The corpus folder should have
the following structure:
```
./corpora/
└── <my_new_corpus>/
    ├── scopus.csv       # Scopus query export (input — you need to place this here)
    ├── manuscripts/     # Downloaded full-text PDFs/XMLs  output of `download_corpus()`
    ├── intermediates/   # Intermediate MinerU output files and JSON structures - output of `transform_text()`
    ├── results/         # Final Markdown files - output of `standardise_text()`
    ├── reports/         # All HTML output reports.
    ├── logs/            # Run logs
    └── sqlite.db        # SQLite cache for this corpus
```

## Attempt download of all full-texts for a corpus.
Once your corpus is set up, download is handled automatically, and once a manuscript is downloaded successfully, it is 
saved in the corpus cache file (sqlite.db) to ensure that download is not repeated if the pipeline is restarted.

To start the download of a corpus run the following command: 
```python
from main import download_corpus
publications = download_corpus(check_opensource=True, generate_report=True)
```
Setting `check_opensource=False` will skip checking open-source download availablity for each publication using websites 
such as BioRxiv and Unpaywall and attempt to download the full-text directly from publisher-specific routes.

Setting `generate_report=True` will generate a HTML report that records various metrics associated with the success/failure 
rates of the download function. This includes information such as the total percentage of successful downloads. All 
reports for a corpus are saved inside the `/reports` folder.

The `download_corpus()` function will return a list of publication objects along with the filepath for the full-text
manuscript (if applicable). By default, these PDF/XML files are stored inside the corpus `/manuscripts` folder. To map
each folder to the associated DOI, you can query the sqlite.db cache, or use the Python `Publication` objects returned 
by the function. 

### Suggestions for maximising download performance.
For downloading full-text manuscripts, we recommend running the software from an institutional IP (if applicable). This 
often leads to a higher number of successful paper downloads, as institutional IPs are more likely to be able to have
access to full-texts of some manuscripts (particularly when downloading directly from publishers).

## Generate JSON document structures for a corpus.
Once you have downloaded your full-text manuscripts, you can begin document conversion by generating JSON document
structure files for each manuscript. For PDF files, this is done using OCR with the [MinerU](https://github.com/opendatalab/mineru)
tool. For XML files, a built-in parser is used. To generate the JSON document structure files for all publications in the 
active corpus, run the following code:

```python
from main import download_corpus, transform_text
publications = download_corpus()
publications = transform_text(publications, mineru_backend="local-cpu", generate_report=True)
```

This begins the process of generating JSON structure files. Depending on the size of your corpus, this may take a long 
time. All outputs from this function are stored in the `/intermediates` folder. This includes all JSON structure files,
as well as other MinerU output files, such as raw Markdown text, figure .png files and other intermediates that may be
useful for developers. For information on the `mineru_backend` parameter, see the documentation [here](general.md#instructions-for-gpu-integration).
Caching via the `sqlite.db` file is also enabled for this function, meaning that heavy computation does not need to be
repeated if the pipeline is restarted and manuscripts have already been processed.

The `generate_report=True` parameter will generate a HTML report that records various metrics associated with the success/failure 
rates of function.

## Generate the final Markdown files for a corpus.
Once you have generated JSON document structure files for all manuscripts in your corpus, you can generate the final
structured markdown files with:

```python
from main import download_corpus, transform_text, standardise_text
publications = download_corpus()
publications = transform_text(publications, mineru_backend="local-cpu", generate_report=True)
publications = standardise_text(publications, 
                                keep_figures=False, 
                                keep_tables=True, 
                                keep_references=False, 
                                keep_latex=False, 
                                force_imrad_structure=True)
```

Running the `standardise_text()` function will generate structured markdown files for each manuscript. These outputs can
be customised to your needs using the set parameters:

* `keep_figures` - If True, figure lines will be included within the final markdown file. If false, figure lines will
be removed and replaced with a <figure_removed> tag.
* `keep_tables` - If True, tables will be rendered within the final markdown file. If false, table blocks will be
removed and replaced with a <table_removed> tag.
* `keep_latex` - If True, LaTeX equations will be rendered within the final markdown file. If false, LaTeX equations
will be removed and replaced with a <latex_removed> tag.
* `keep_references` - If True, references will be rendered within the final markdown file. If false, The software will 
attempt to locate the references block in the manuscript and remove it, along with any text below the references block.

### Removing paper boilerplate with `force_imrad_structure` flag.
`force_imrad_structure` - If set to True, the software will attempt to classify paper headings as "core" to the 
manuscript or "boilerplate" text that will be cut from the final version. This is done by passing manuscript text block 
headers to a classifer model hosted locally by [Ollama](). Setting this flag attempts to remove all paper boilerplate,
whilst retaining all core scientific text. It will also force all output markdown files to contain the following 
headers: `# Introduction`, `# Methods`, `# Results` and `# Discussion` (can be absent if no synonomous discussion block 
is found).

If [Ollama](https://ollama.com/) is not installed locally, but this parameter is set to True,
the software will raise a runtime error. See [here](general.md#instructions-for-ollama-integration) for more information
on running the software with Ollama integration.

## Instructions for GPU integration.
We strongly recommend running biomarkit on a computer with access to a GPU. GPU integration allows the MinerU OCR tool 
to perform both faster and more accurate OCR on PDF documents with [MinerU](https://opendatalab.github.io/MinerU/).
For more information see [here](https://github.com/opendatalab/mineru#local-deployment).

To allow Python access to an onboard NVIDIA GPU, ensure that a CUDA-capable version of PyTorch is installed within your
Python environment –
for example:
```bash
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
```

```python
import torch
available = torch.cuda.is_available()
if available:
    print(f"GPU recognised: {torch.cuda.get_device_name(0)} ({torch.cuda.device_count()} device(s))")
```

To run the `biomarkit.text_transformation()` using the GPU set the parameter `mineru_backend="local-gpu"` Optionally,
you can also set MINERU_VIRTUAL_VRAM_SIZE in `secrets.env` to optimise performance. To run the function in CPU-only mode,
set the parameter `mineru_backend="local-cpu"`.

## Instructions for Ollama integration.
We recommend running biomarkit on a computer with access to a GPU. This enables the use of a local classifier LLM that 
will increase the accuracy of text-conversion and decrease the time taken to batch process PDF's.

Note: The biomarkit package installation uses [Ollama](https://ollama.com/) for interacting with a local classifier LLM.
For installation instructions for Ollama please follow the documentation available [here](https://docs.ollama.com/quickstart). 

We recommend pre-downloading the gemma3:12b model using the command: ` ollama pull gemma3:12b`. This will pre-download 
the model weights (~8GB). Alternatively, Biomarkit will attempt to download these automatically the first time the
`biomarkit.standardise_text()` function is called.

**Note**:`biomarkit.download_text()` and `biomarkit.transform_text()` functions do not require gemma3:12b for full
functionality.

