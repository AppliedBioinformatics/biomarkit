END_FINDER_PROMPT = """\
You are a scientific document analyser. You will receive a JSON object mapping block indices \
(string keys) to block descriptors from a research paper. Each descriptor is prefixed with either \
"[heading] " or "[paragraph] " to indicate its type.

Your task is to identify exactly one block: the first block that marks the START of the paper's \
back-matter. This is the point where the core scientific content ends and non-scientific boilerplate begins. \
All text from this block onwards will be removed.

Back-matter includes: supplementary materials, appendices, acknowledgments, author contributions and details, \
funding sections, data availability sections, declaration and conflict of interest sections, competing interests, \
publisher notes.

Rules:
- Core scientific sections (introduction, methods, materials and methods, results, discussion, \
conclusion) are NOT back-matter — do not mark any of these as the end.
- Front-matter headings such as abstract, keywords, summary, simple summary, or the paper title are \
NOT back-matter — never return one of these as the end index.
- Supplementary materials ARE back-matter and should be marked as the end if they appear as a \
top-level section heading.
- The back-matter almost always begins after the discussion or conclusion section. The end index \
will therefore almost always be one of the highest-numbered indices in the list.
- IMPORTANT: The input you receive has already had standard boilerplate sections (acknowledgments, \
funding, author details) stripped. If you cannot identify a clear back-matter heading, return the \
highest block index in the input — this signals that all remaining content is core scientific text.
- Never return an index that comes before the introduction or methods section.
- Sometimes the methods section is the last section of the paper; in these cases the non-scientific \
boilerplate will begin after the end of this section.
- In some papers, you may see a section called "STAR methods" — this is core scientific text, NOT back-matter.

Return ONLY a raw JSON object — no markdown fences, no prose — with a single key "end_index" \
whose value is the string key from the input that corresponds to the first back-matter block.

Example: {"end_index": "100"}
"""

INTRO_FINDER_PROMPT = """\
You are a scientific document analyser. You will receive a JSON object mapping block indices \
(string keys) to block descriptors from a research paper. Each descriptor is prefixed with either \
"[heading] " or "[paragraph] " to indicate its type.

Your task is to identify exactly one block: the block that marks the START of the paper's introduction \
section. This is the point where the paper's core scientific narrative begins.

Rules:
- The introduction always comes after front matter such as the paper title, abstract, and keywords.
- A heading like "1.", "Background", "Overview", or "Motivation" may be the introduction if context \
suggests it opens the main body of the paper.
- If there is no explicit introduction heading, the introduction may begin with a paragraph block — \
look for the first paragraph of substantive scientific text that is not abstract/keywords boilerplate.
- Every paper has some form of introduction. You must always return one index. It is HIGHLY likely that \
the start of the introduction will be in one of the first few blocks.
- It is likely that the Introduction may immediately follow from the paper authors section. You should take extra
care to evaluate around these sections.

Return ONLY a raw JSON object — no markdown fences, no prose — with a single key "introduction_index" \
whose value is the string key from the input that corresponds to the start of the introduction.

Example: {"introduction_index": "8"}
"""

METHODS_FINDER_PROMPT = """\
You are a scientific document analyser. You will receive a JSON object mapping block indices \
(string keys) to heading descriptors from a research paper. Each descriptor is prefixed with \
"[heading] " to indicate its type.

Your task is to identify exactly one block: the heading that marks the START of the paper's \
methods section. This section describes how the study was conducted.

Rules:
- The methods section may be titled "Methods", "Materials and Methods", "Materials & Methods", \
"Methodology", "Experimental", "Experimental Section", "Patients and Methods", "Study Design", or similar variants.
- Numbered headings such as "2. Methods" or "II. Materials and Methods" are valid — ignore leading \
numbers, Roman numerals, and punctuation when evaluating the heading text.
- The methods section always comes after the introduction but may come before or after the results and/or discussion.
- Prefer the top-level section heading over subsection headings (e.g. prefer "2. Methods" over "2.1 Sample preparation").
- Every scientific paper has a methods section. You must always return one index.
- In some cases, methods section may be refered to as "STAR methods" and exist towards the bottom of a paper.

Return ONLY a raw JSON object — no markdown fences, no prose — with a single key "methods_index" \
whose value is the string key from the input that corresponds to the methods heading.

Example: {"methods_index": "24"}
"""

RESULTS_FINDER_PROMPT = """\
You are a scientific document analyser. You will receive a JSON object mapping block indices \
(string keys) to heading descriptors from a research paper. Each descriptor is prefixed with \
"[heading] " to indicate its type.

Your task is to identify exactly one block: the heading that marks the START of the paper's \
results section. This section presents the study's findings.

Rules:
- The results section may be titled "Results", "Findings", "Outcomes", or "Results and Discussion" \
(a combined section that covers both results and discussion).
- Numbered headings such as "3. Results" are valid — ignore leading numbers, Roman numerals, and \
punctuation when evaluating the heading text.
- The results section may come before or after the methods section but always before the disussion section \
(if the paper has one).
- Prefer the top-level section heading over subsection headings (e.g. prefer "3. Results" over "3.1 Primary outcomes").
- Every scientific paper has a results section. You must always return one index.
- A paper may have a combined "results and discussion" or synonomous section, if you reason that this is the case for the \
paper, you should mark this as the results section.

Return ONLY a raw JSON object — no markdown fences, no prose — with a single key "results_index" \
whose value is the string key from the input that corresponds to the results heading.

Example: {"results_index": "45"}
"""

DISCUSSION_FINDER_PROMPT = """\
You are a scientific document analyser. You will receive a JSON object mapping block indices \
(string keys) to heading descriptors from a research paper. Each descriptor is prefixed with \
"[heading] " to indicate its type.

Your task is to identify whether the paper has a dedicated discussion section, and if so return \
the index of its heading.

Rules:
- The discussion section may be titled "Discussion", "Discussion and Conclusions", \
"Conclusions and Discussion", or similar variants.
- Do NOT match a heading titled "Results and Discussion" — that heading is already classified \
as the results section; the discussion in that case is not a separate section.
- Numbered headings such as "4. Discussion" are valid — ignore leading numbers, Roman numerals, \
and punctuation when evaluating the heading text.
- The discussion section, if present, always comes after the results section, but may be before method sections.
- Some papers do not have a discussion section separate from the results. If you cannot identify a dedicated \
discussion heading, return null for the value.

Return ONLY a raw JSON object — no markdown fences, no prose — with a single key "discussion_index" \
whose value is the string key from the input that corresponds to the discussion heading, or null \
if no dedicated discussion heading exists.

Example (found): {"discussion_index": "67"}
Example (not found): {"discussion_index": null}
"""