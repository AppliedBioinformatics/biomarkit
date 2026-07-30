"""
Abstract base class for LLM-backed section classification fallback.

Unlike StandardiserBase (which classifies heading *levels*), this classifier
determines the *role* of each heading â€” mapping it to one of the four target
sections (introduction, methods, results, discussion), marking it for deletion,
or demoting it to body text.

The LLM never sees paper content â€” only heading line numbers and text.
"""
from typing import Optional
import json
import logging
from standardisation.llms.standardiser_base import StandardiserBase


SECTION_CLASSIFIER_PROMPT = """\
You are a scientific document heading classifier. You will receive a JSON object \
mapping markdown file line numbers to markdown heading strings from a research paper.
These headings could NOT be classified by regex and need your judgement to decide which section of the paper they \
belong to.

For each heading, decide whether it relates to one of the core scientific sections. You can assign each of these \
sections exactly once per paper:

"introduction" â€” this heading likely starts the introduction section of the paper. 
"methods"      â€” this heading likely starts the methods section of the paper. 
"results"      â€” this heading likely denotes the start of the papers results section.
"discussion"   â€” this heading likely denotes the start of the papers discussion section. Sometimes this section may \
be integrated with the results section, so sometimes may not need to be defined. 

In addition to assigning the above to the best of your ability, the markdown heading likley also contain headers that  \
define paper boilerplate sections such as "abstract", "references", "acknowledgments", "funding", "author info",  \
"keywords", paper titles etc. 

For headings not classified above, classify each row as one of the following: 
"delete"       â€” this defines the start of a paper boilerplate section, metadata, back matter, or boilerplate. This \
should be assigned to headings that will be removed (along with the associated text below it) from the final markdown \
file. 
"body"         â€” this should be assigned to headings that are likely still core-scientific text such as subheading 
rows within the introduction, methods, results or discussion sections. Assigning this classification means that the 
heading and text below it will be "flattened" into body text within one of the major IMRaD sections and NOT removed from
the final markdown file.   

"delete" and "body" classifications can be assigned more than once.

Tips for improving accuracy of classification:
- You will receive the headings IN ORDER of where they appear in the paper. You should weigh the order of the headings
when assigning your classifications. For example, paper boilerplate sections are more likley to appear at the beggining 
and end of the paper. Subheadings that should be marked as "body" will likley appear between rows that define the start
of the introduction and other major IMRaD sections.

- "Conclusion" or synonymous should be classed as core-scientific text within the discussion and marked as either
 "discussion" or "body", never "delete".
- Some papers may include a merged results and discussion section. If you feel this is the case, mark it as "results".
- "introduction" will ALWAYS come before the other major sections.
- "methods" may be after introduction or after results and/or discussion. 


Return ONLY a raw JSON object â€” no markdown fences, no prose. \
Keys must be identical strings to those in the input. \
Each Value you assign must be exactly one of: "introduction", "methods", "results", "discussion", "delete", "body".
"""

_VALID_ACTIONS = {"introduction", "methods", "results", "discussion", "delete", "body"}


class SectionClassifierBase(StandardiserBase):
    """LLM fallback for headings that regex couldn't classify."""

    @staticmethod
    def _build_response_schema(headings: dict[int, str]) -> dict:
        """Builds a strict JSON schema constraining the model's output.

        Every input line number must appear as a key, each value is restricted to
        the valid action enum, and no extra keys are allowed. Passed to the model
        as a response_format so it cannot emit invalid JSON or bogus action values
        (e.g. echoing the heading text back, or paraphrasing "discussion" as
        "discuss") — the two failure modes the retry loop was papering over.
        """
        keys = [str(k) for k in headings.keys()]
        return {
            "name": "section_classification",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    key: {"type": "string", "enum": sorted(_VALID_ACTIONS)}
                    for key in keys
                },
                "required": keys,
                "additionalProperties": False,
            },
        }

    @staticmethod
    def _validate_classification(result: dict, input_headings: dict[int, str]) -> list[str]:
        errors: list[str] = []
        if not isinstance(result, dict):
            errors.append("Response is not a JSON object")
            return errors

        input_keys = {str(k) for k in input_headings.keys()}
        result_keys = set(result.keys())

        missing = input_keys - result_keys
        extra = result_keys - input_keys
        if missing:
            errors.append(f"Missing keys: {sorted(missing)}")
        if extra:
            errors.append(f"Unexpected keys: {sorted(extra)}")

        for key, value in result.items():
            if not isinstance(value, str):
                errors.append(f"Value for '{key}' is not a string")
            elif value not in _VALID_ACTIONS:
                errors.append(f"Invalid action for '{key}': {value!r}")

        return errors

    def classify(
        self,
        headings: dict[int, str],
        max_retries: int = 2,
    ) -> Optional[dict[str, str]]:
        """Classify unresolved headings via LLM.

        Args:
            headings: {line_number: heading_text} for unresolved headings only.
            max_retries: additional attempts if validation fails.

        Returns:
            {line_number_str: action} or None if all attempts fail.
        """
        user_prompt = json.dumps(
            {str(k): v for k, v in headings.items()},
            indent=2,
        )
        response_schema = self._build_response_schema(headings)

        for attempt in range(1, max_retries + 2):
            logging.debug(f"[{self.__class__.__name__}] classify attempt {attempt}")
            try:
                raw = self._complete(
                    SECTION_CLASSIFIER_PROMPT,
                    user_prompt,
                    response_schema=response_schema,
                )
            except Exception as exc:
                logging.error(f"LLM call failed on attempt {attempt}: {exc}")
                continue

            try:
                result = json.loads(raw)
            except json.JSONDecodeError as exc:
                logging.warning(f"Attempt {attempt}: invalid JSON â€” {exc}")
                continue

            errors = self._validate_classification(result, headings)
            if not errors:
                logging.debug(f"Attempt {attempt}: classification valid")
                return result

            logging.warning(
                f"Attempt {attempt}: classification failed:\n"
                + "\n".join(f"  - {e}" for e in errors)
            )

        logging.error(f"[{self.__class__.__name__}] all classify attempts failed")
        return None