from standardisation.llms.providers.llama_section_classifier import LlamaSectionClassifier
from standardisation.llms.section_classifier_base import SectionClassifierBase


def test_is_section_classifier():
    """LlamaSectionClassifier should be a SectionClassifierBase."""
    assert issubclass(LlamaSectionClassifier, SectionClassifierBase)
