"""Command-line entry point: `biomarkit <corpus> [options]` runs the pipeline on one corpus."""
import argparse
import logging

from biomarkit.config import MINERU_TIER_CHOICES
from biomarkit.pipeline import load_corpus, download_corpus, transform_text, standardise_text
from biomarkit.text_download.utils.generics import setup_logging


def main(argv=None):
    p = argparse.ArgumentParser(prog="biomarkit", description="Download, convert and standardise a Scopus corpus.")
    p.add_argument("corpus", help="Corpus name (under BIOMARKIT_DIR/corpora) or path to a corpus folder.")
    p.add_argument("--scopus-file", help="Scopus export CSV; required to build a new corpus.")
    p.add_argument("--build", action="store_true", help="Build the corpus without asking if it doesn't exist.")
    for stage in ("download", "transform", "standardise"):
        p.add_argument(f"--skip-{stage}", action="store_true", help=f"Skip the {stage} stage.")
    p.add_argument("--mineru-tier", choices=MINERU_TIER_CHOICES, default="standard")
    p.add_argument("--mineru-batch-size", type=int, help="PDFs per MinerU worker process (default: all at once).")
    p.add_argument("--xml-workers", type=int, help="Processes for Elsevier XML parsing (default: CPU cores - 1).")
    for kind in ("figures", "tables", "latex", "references"):
        p.add_argument(f"--keep-{kind}", action="store_true", help=f"Keep {kind} in the final Markdown.")
    p.add_argument("--no-imrad", action="store_true", help="Don't normalise headings to IMRAD (no LLM needed).")
    p.add_argument("--max-workers", type=int, default=4, help="Publications standardised concurrently.")
    p.add_argument("--report", action="store_true", help="Write HTML reports for the download and transform stages.")
    p.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = p.parse_args(argv)

    setup_logging(level=getattr(logging, args.log_level))
    publications = load_corpus(args.corpus, scopus_file=args.scopus_file, build=True if args.build else None)

    if not args.skip_download:
        publications = download_corpus(generate_report=args.report)
    if not args.skip_transform:
        publications = transform_text(publications, mineru_tier=args.mineru_tier,
                                      mineru_batch_size=args.mineru_batch_size,
                                      generate_report=args.report, xml_workers=args.xml_workers)
    if not args.skip_standardise:
        standardise_text(publications, keep_figures=args.keep_figures, keep_tables=args.keep_tables,
                         keep_latex=args.keep_latex, keep_references=args.keep_references,
                         force_imrad_structure=not args.no_imrad, max_workers=args.max_workers)


if __name__ == "__main__":
    main()
