from unittest.mock import patch

from biomarkit.cli import main


def test_main_wires_flags_to_pipeline():
    with patch("biomarkit.cli.setup_logging") as mock_logging, \
            patch("biomarkit.cli.load_corpus", return_value=["pub"]) as mock_load, \
            patch("biomarkit.cli.download_corpus") as mock_download, \
            patch("biomarkit.cli.transform_text", return_value=["converted"]) as mock_transform, \
            patch("biomarkit.cli.standardise_text") as mock_standardise:
        main(["my_corpus", "--skip-download", "--mineru-tier", "basic", "--no-imrad", "--keep-tables",
              "--log-level", "DEBUG"])

    mock_logging.assert_called_once_with(level=10)
    mock_load.assert_called_once_with("my_corpus", scopus_file=None, build=None)
    mock_download.assert_not_called()
    mock_transform.assert_called_once_with(["pub"], mineru_tier="basic", mineru_batch_size=None,
                                           generate_report=False, xml_workers=None)
    kwargs = mock_standardise.call_args.kwargs
    assert mock_standardise.call_args.args == (["converted"],)
    assert kwargs["normalise_imrad"] is False
    assert kwargs["keep_tables"] is True
    assert kwargs["keep_figures"] is False
    assert kwargs["max_workers"] == 4


def test_main_build_and_skip_flags():
    with patch("biomarkit.cli.setup_logging"), \
            patch("biomarkit.cli.load_corpus", return_value=[]) as mock_load, \
            patch("biomarkit.cli.download_corpus", return_value=["d"]) as mock_download, \
            patch("biomarkit.cli.transform_text") as mock_transform, \
            patch("biomarkit.cli.standardise_text") as mock_standardise:
        main(["corpus_dir", "--scopus-file", "scopus.csv", "--build", "--report",
              "--skip-transform", "--skip-standardise"])

    mock_load.assert_called_once_with("corpus_dir", scopus_file="scopus.csv", build=True)
    mock_download.assert_called_once_with(generate_report=True)
    mock_transform.assert_not_called()
    mock_standardise.assert_not_called()
