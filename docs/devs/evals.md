# Evaluation of MinerU/Marker2/Docling for PDF to Markdown file conversion (23/11/2026).
OmniDocBench provides page-level ground-truth annotations for text blocks, display formulas (LaTeX), tables (HTML).
OmniDocBench (v1.7) was downloaded from the GitHub repository (https://github.com/opendatalab/OmniDocBench, commit `7ddb8df`), 
and the corresponding benchmark dataset was downloaded from Hugging Face (`opendatalab/OmniDocBench`, revision `aa1ee96d106dbe53d0ae59474d75c6e6d9b53fec`). 
215 pages (206 English, 9 Chinese or mixed) annotated with metadata: `data_source: academic_literature` were retained to
focus the benchmark exclusively on pages obtained from academic literature. These pages contained different format 
layouts: 86 single-column, 45 double-column, 53 one-and-more-column, 31 other layouts) and contained 1,162 text blocks,
591 display formulas and 123 tables.

## Tools and configurations
Each OCR tool was installed in its own isolated Python 3.12 environment, with PyTorch 2.9.1 and CUDA 12.8 wheels, The following
table summarises which processing modes were evaluated for each tool. MinerU v4.0.12 was used for the evaluation, as this 
is the version shipped with the latest version of biomarkit (V1.2). Marker2 was run with external LLM assistance disabled, 
Marker's VLM modes used Surya's llama.cpp backend (llama-server b12648). Docling's standard pipeline used EasyOCR with
formula enrichment enabled, because vLLM is unavailable on Windows. All other settings were left at each tool's defaults. 

| Tool | Version | Mode | Notes|
|---|---|---|---|
| MinerU | 4.0.12 | `flash` | |
| | | `basic` ||
| | | `standard` |(default in biomarkit) |
| | | `advanced` ||
| Marker | 2.2.0 | `fast` ||
| | | `balanced` |  |
| | | `accurate` ||
| Docling | 2.151.1 | `standard` | |

Docling's default (standard) pipeline was evaluated; its optional Granite-Docling VLM pipeline was not, due to
runtime constraints (> 30 s per page on the test hardware).

### Evaluation.
Each tool's Markdown output was saved per page, inline base64-encoded figure images were replaced with a placeholder 
link for all tools, as figure extraction accuracy is not scored by OmniDocBench.

OmniDocBench's official end-to-end evaluation (`pdf_validation.py`, `quick_match` matching), was used to calculate 
evaluation metrics. Metrics were:

- text: normalised edit distance (page average);
- display formulas: normalised edit distance;
- tables: Tree-Edit-Distance-based Similarity (TEDS) and structure-only TEDS;
- reading order: normalised edit distance.

Scores are reported for all academic pages and for English pages only. Overall score was calculated as the mean of 
(1 − text edit distance), table TEDS and (1 − formula edit distance), × 100.  Bootstrap 95% confidence intervals 
(2,000 resamples over pages) were calculated for the text edit distance. OmniDocBench's `tools/json2md.py` was used to 
convert the ground truth annotations to Markdown to ground the evaluation results (TED = 0.04, FED = 0, TEDS = 1, ROED = 0.02)

Due to discrepancies in the running the scoring pipeline on Windows rather than Linux, the reported scores are not directly comparable with the OmniDocBench leaderboard.
For each run, per-page wall-clock time was recorded for all 215 pages for each model.
All runs were performed on a single machine (NVIDIA GeForce RTX 4080 Laptop GPU, 12 GB VRAM; Intel Core 32-thread CPU; 32 GB RAM; Windows 11)

# Full-paper Biological PDF conversion benchmark: ground truth generation.
OmniDocBench scores single page images, so it cannot assess full-paper behaviour (running headers/footers, reading order
across pages, section structure), use of the PDF text layer, or differences between publishers. A second benchmark was
therefore built from complete publisher PDFs, using PMC BioC XML of the same articles as ground truth (GT).

## Ground truth source
BioC XML (https://www.ncbi.nlm.nih.gov/research/bionlp/APIs/BioC-PMC/) provides the full text of each article as passages,
each labelled by NCBI with a section type (e.g. INTRO, METHODS, RESULTS, DISCUSS, CONCL, ABSTRACT, REF, ACK_FUND, SUPPL,
FIG, TABLE). Section labels in the GT therefore come from NCBI rather than biomarkit's own heading classifier. BioC was
parsed directly (not with biomarkit's BioC converter), so the GT is independent of biomarkit's code.

## Paper selection
The candidate pool was all BioC XMLs downloaded during the three test queries (Q1–Q3) for the six publishers with
sufficient BioC coverage: Elsevier, Springer (incl. Nature and BMC), Frontiers, MDPI, PLOS and Wiley. Taylor & Francis
(no BioC papers) and Oxford University Press (blocks automated PDF downloads) were not included. No DOI used to develop 
biomarkit is included in the benchmark. The journal of each article was taken from its DOI suffix, and candidates were 
drawn per publisher round-robin across journals (fixed random seed 0), so each journal contributes one article before 
any contributes a second. Because Wiley journal layouts vary far more than those of other publishers, more Wiley 
articles were sampled: 30 Wiley candidates (target 20 articles) and 15 candidates for each other publisher 
(target 10 each), 105 candidates in total.

| Publisher | Candidates | Journals | Q1 / Q2 / Q3 |
|---|---|---|---|
| Wiley | 30 | 30 | 5 / 24 / 1 |
| Elsevier | 15 | 15 | 0 / 14 / 1 |
| Springer | 15 | 15 | 3 / 11 / 1 |
| Frontiers | 15 | 14 | 3 / 12 / 0 |
| MDPI | 15 | 15 | 3 / 12 / 0 |
| PLOS | 15 | 4 | 5 / 10 / 0 |

The sample is weighted towards the cancer query (Q2) because PMC holds proportionally more biomedical articles.

## Ground-truth definition
Each article was converted to an ordered list of blocks (title, headings, paragraphs, figures, tables, references and
other passages), each keeping its NCBI section type.
- Core text: headings and paragraphs labelled INTRO, METHODS, RESULTS, DISCUSS or CONCL. This matches the guideline of
  the original annotation set (IMRaD sections, conclusions treated as part of the discussion, abstract excluded).
- Figures and tables: treated as units containing their caption and footnotes, consistent with biomarkit's
  `keep_figures`/`keep_tables` options. Table bodies were rebuilt as HTML from the JATS table XML, keeping merged cells
  (`colspan`/`rowspan`) so that table structure can be scored with TEDS.
- Abstract, references and back matter (acknowledgements, funding, author contributions, competing interests,
  supplementary material) are retained as non-core blocks.

Articles were included if they had an INTRO section and at least one of METHODS, RESULTS or DISCUSS, and at least 10 core
paragraphs. This retains research articles in non-IMRaD formats (e.g. Nature-style "Main + Methods" articles, whose main
text NCBI labels INTRO) while excluding reviews and short communications without methods. Three candidates failed
this check (one Frontiers, two Wiley) and were replaced by the next articles in the sampling order (108 candidates in
total).

## Publisher PDFs
The version-of-record PDF of each candidate is downloaded with biomarkit's own publisher clients (Springer, Wiley, MDPI,
Frontiers), called directly so that open-access/BioC routes are bypassed; Elsevier PDFs via the Elsevier Article API
and PLOS PDFs via the journal's printable-PDF link. PDFs that cannot be downloaded automatically are downloaded manually
from the publisher or PMC website.

To confirm that each XML and PDF are the same version of the article, the text layer of each PDF was extracted with
PyMuPDF (no OCR). Both texts were Unicode-normalised (NFKC) and lower-cased, words hyphenated across lines (including
soft hyphens) were re-joined, and numeric and single-character tokens were removed so that inline citation numbers and
symbols in non-standard PDF font encodings did not cause false mismatches. A core paragraph was counted as present if at
least 80% of its word 5-grams occurred in the PDF text; paragraphs of fewer than five words (e.g. abbreviation or stock
lists) were not scored. Article pairs with fewer than 90% of core paragraphs present were excluded. All PDFs were
obtained automatically; 18 candidates failed the version check, three of them Elsevier PDFs truncated to the first page
and most of the rest consistent with PMC holding the author's accepted manuscript. The first passing articles per
publisher in sampling order (20 Wiley, 10 for each other publisher; 70 articles, 1,105 pages) form the final benchmark
set (Supplementary Table 7). DOIs, journals and reasons for any exclusion are recorded in `manifest.csv`.

The final GT contains 9,548 blocks (median 130 per article, range 39–300):

| Block type | Total | Core | Scored |
|---|---|---|---|
| Paragraphs | 3,436 | 2,631 | core paragraphs: text ED, recall, reading order |
| Headings | 1,793 | 1,378 | core headings: recall, precision, order, level changes |
| Tables | 82 | – | 81 with an HTML body: TEDS |
| Figures (caption units) | 499 | – | no |
| References | 3,608 | – | no |
| Article titles | 70 | – | no |
| Other (footnotes) | 60 | – | no |

Non-core paragraphs are the abstract and back matter (acknowledgements, funding, author contributions, competing
interests, supplementary material). BioC keeps only the title of each reference, and contains no display formulae.

## Reproducibility
Scripts are in `evals/fullpaper_benchmark/`: `select_papers.py` (sampling), `fetch_pdfs.py` (PDF download; run in the
biomarkit environment), `build_gt.py` (GT construction, inclusion and version checks; writes `gt/<id>.json` and a
readable `gt/<id>.md` per article).

# Full-paper conversion benchmark: evaluation
The 70 publisher PDFs were converted by MinerU 4.0.12 (`standard`, biomarkit's default) and Marker 2.2.0 (`balanced`),
using the same isolated environments and hardware as the OmniDocBench evaluation. MinerU was run with docvortex 0.5.16,
the version locked by biomarkit. Marker's `balanced` mode (its default on GPU) uses the PDF's embedded text layer but
re-reads any page with a flagged text block using Surya VLM OCR. Each whole PDF was converted to a single Markdown file,
and inline base64 images were replaced with a placeholder link. Marker aborted three times with a native fault in
pdfium; the run was resumed and all affected articles converted on retry, so both tools produced output for all 70
articles. Per-article wall-clock time was recorded; Marker timings were available for 31 articles.

## Core text
Text was scored on core paragraphs only (2,631 paragraphs). Ground truth and Markdown were normalised as in OmniDocBench
(HTML tags removed, NFKC, lower-cased, letters and digits only). Each GT paragraph was aligned to its best-matching span
anywhere in the article's Markdown (`rapidfuzz` partial alignment), and its normalised edit distance (ED) to that span
was recorded. Per article, text ED is the total edits divided by total GT characters. A paragraph was counted as:
- found: ED ≤ 0.2, i.e. reproduced as one contiguous block;
- present: found, found once digits are ignored (citation labels, see below), or at least 80% of its word 5-grams
  occurring in the Markdown. This includes paragraphs interrupted by a figure, table, running header or footer placed
  mid-paragraph in PDF reading order.

Reading order was scored as the normalised edit distance between the GT order of found paragraphs and their order in the
Markdown. All values are reported as means over articles, per publisher and overall (Supplementary Table 8).

## Headings
Matching headings against the whole Markdown is uninformative (short headings such as "Results" match body text), so
the 1,378 GT core headings were matched only against Markdown heading lines (`#`). A heading is found if a heading line,
or two adjacent heading lines joined (a heading split over two lines), has ED ≤ 0.2 to it; a heading line that starts or
ends with a GT heading counts two headings merged into one line. Matching follows GT order. Reported:
- heading recall: share of GT core headings found;
- heading precision: share of heading lines between the first and last found heading that match any GT heading
  (spurious headings in the main text, e.g. running headers; front and back matter are excluded because BioC does not
  mark headings such as Abstract or References);
- heading order ED: as for paragraphs (Supplementary Table 9).

GT rendered as Markdown and scored as a prediction gives perfect heading scores (and paragraph reading-order ED 0.013,
from very short or repeated paragraphs aligning to an earlier occurrence). Missed headings are mostly run-in headings
typeset inline with their paragraph ("Reporter assay. Saos2 cells…"), which both tools output as body text.

Heading levels are not reported: BioC levels follow the XML section nesting, not the PDF layout, MinerU emits every
section heading at the same level (`##`), and biomarkit assigns sections from heading text (`standardise_text()`).
`score_text.py` still prints a "hierarchy" column (share of BioC level changes reproduced: MinerU 0, Marker 0.46) for
reference.

OmniDocBench's `quick_match` was not used for text. It was designed for single pages (16 annotated blocks per page on
average in the academic subset) and, at full-paper scale (median 130 GT blocks per article), mis-paired paragraphs that were present in the output: 95 (MinerU) and 125 (Marker) of
2,631 core paragraphs were scored as > 80% wrong although at least 80% of their 5-grams occurred in the Markdown.

## Tables
Tables were scored with the OmniDocBench end-to-end scorer (same commit as above). The GT of each article was converted
to OmniDocBench format as one pseudo-page: tables with an HTML body (81) as `table`, core paragraphs and headings as
`text_block`/`title`, and all other blocks (abstract, references, captions, back matter) as categories that
OmniDocBench matches but does not score, so that predicted non-core text is not penalised. TEDS and structure-only TEDS
are reported. No article hit a matching timeout.

## Limitations
- BioC removes citation labels (numeric superscripts and the years of author–year citations), so correctly extracted
  citations count as edits for both tools.
- BioC contains no display formulae, so formulae were not scored (see the OmniDocBench evaluation).
- With 10 articles per publisher (20 for Wiley), per-publisher differences are indicative only.

Scripts: `evals/fullpaper_benchmark/to_omnidocbench.py` (GT conversion and PDF list), `evals/parser_benchmark/run_*.py
--pages fullpaper.txt [--resume]` (conversion), `evals/parser_benchmark/score.py --gt
evals/fullpaper_benchmark/gt/omnidocbench.json` (tables) and `evals/fullpaper_benchmark/score_text.py` (core text and
reading order).
