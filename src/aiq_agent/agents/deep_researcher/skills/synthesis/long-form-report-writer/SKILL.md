---
name: long-form-report-writer
description: >
  Use this skill when the final answer strategy calls for a long-form report,
  publication-quality research writeup, comprehensive analysis, deep dive,
  whitepaper-style narrative, or detailed cited Markdown report.
  Triggers: "long_form_report", "long-form report", "comprehensive report",
  "publication-ready", "deep dive", "in-depth analysis", "whitepaper",
  "research report", "detailed report", "full report".
  Outputs: A polished, cited Markdown report with coherent structure, analytical
  depth, source-grounded claims, limitations, and a sources section.
---

# Long-Form Report Writer Skill

Write a publication-quality, well-cited Markdown report from the planned answer
strategy and ResearchNotes artifacts. This skill is for final synthesis only;
do not perform new research.

## When To Use

Use this skill when `answer_strategy.answer_type` is `long_form_report`, or when
the user's request clearly asks for a comprehensive report, deep analysis,
publication-ready writeup, or whitepaper-style answer.

Do not use this skill for brief answers, primary table outputs, data extraction,
multiple-choice selection, or numeric predictions unless the answer strategy also
requires a full report narrative.

If `answer_strategy.answer_type` is `prediction`, or the user asks for a
forecast, stock price, price target, probability, odds, expected value, or
next-period value, this skill is not the controlling skill. If
`prediction-report-writer` is available, read and follow that skill instead.

## Long-Form Planning

Before writing, complete the general cross-synthesis pass from the base writer
prompt. Then use `think` to turn that synthesis map into a report plan:
- Choose the report title, main sections, and subsection flow from the
  `answer_strategy`, the user's request, and the evidence.
- Decide which components need detailed prose, which need compact summary, and
  which need explicit caveat or gap treatment.
- Decide where report-specific elements such as tables, equations, timelines,
  case-study boxes, or comparison matrices materially improve the reader's
  understanding.
- Decide how to order the report so it moves from fundamentals to implications
  without exposing internal workflow steps.

## Report Writing

Write a comprehensive, in-depth report following the answer strategy and
satisfying the constraints. If you need to recall research findings during
writing, re-read the relevant research-note JSON files before drafting.

Each section should have detailed paragraphs, not just a few sentences. Ensure
all aspects of the user's query are addressed. Provide analytical depth: explain
mechanisms and causes, not just surface descriptions. Acknowledge trade-offs,
limitations, uncertainty, or open questions where the evidence warrants.

## Report Presentation

- Use clear Markdown headings: `#` for the title, `##` for main sections, and
  `###` for subsections when useful.
- Write in paragraphs for readability; avoid excessive bullet points.
- No self-referential language such as "I found" or "I researched".
- Each paragraph should be substantive and detailed.
- Structure from fundamentals to complex concepts.
- Provide contextual explanation of specialized terms.
- When appropriate, prefer clear language over jargon; explain technical terms
  when used.
- Use tables, equations, or code blocks when they materially improve the report.
- Keep the report human-facing; do not expose the internal planning workflow.

## Content To Never Include

Never include:
- References to agents, constraints, workflow, prompts, tools, or internal files.
- Methodology sections or meta-commentary about how the report was produced.
- Statements like "the user requested" or "this report satisfies".
- Word counts or length statements.
- Internal workflow tool names such as `get_verified_sources`, `write_file`,
  `read_file`, `think`, `task`, or `run_research_batch`.
- Descriptions of how sources were gathered, verified, or validated.

Exception: in the Sources section, a verified data-source tool name may appear
when the source has no URL or document locator. Preserve the raw tool/source name
exactly as shown by verified sources.

The report must read as if written by a professional human researcher.

## Citation Guidelines

- Number sources sequentially with inline citations like `[1]`, `[2]`, etc.
- Place citations immediately following the relevant claim.
- Citations are required for every material factual claim, number, date,
  sourced comparison, source-specific caveat, or analytical conclusion grounded
  in evidence.
- Never place bare URLs or hyperlinks in the report body; use only `[N]`
  citations inline. URLs belong exclusively in the Sources section.
- For information supported by multiple sources, use adjacent citations like
  `[1][4][7]`.
- Include the full source list at the end of the document.
- Assign each unique URL or source locator a single citation number across all
  findings. Each citation number must map to exactly one verified URL or one
  exact verified citation key/source locator.
- Do not group multiple publishers, tools, URLs, or source names under one
  citation number. Do not write unverifiable aggregate labels such as
  `[1] CNN; Yahoo Finance; Barchart`.
- Number sources sequentially without gaps.
- For internal documents, cite the filename/page locator from the ResearchNotes
  source locator verbatim.
- For URL-less structured tool sources, cite the raw tool/source name exactly as
  shown by `get_verified_sources`; do not invent friendly titles.
- Do not invent or recall URLs from memory. Use only ResearchNotes sources and
  verified sources.
- If a claim has no verified supporting source, remove it or state it as an
  evidence gap without pretending it is cited.

### Sources Section Format

Use this format:

```markdown
## Sources
[1] Source Title: https://example.com/source
[2] internal-report.pdf, p.15
[3] mcp_time__get_current_time
```

## Final Verification

Before finishing:
1. Confirm the report follows `answer_strategy.response_shape` and
   `assembly_instruction`.
2. Confirm every required answer component is covered or explicitly named as a
   gap.
3. Confirm every material factual claim has an inline citation.
4. Confirm the Sources section includes every cited source and no uncited filler.
   Each source line must contain one verified URL or one exact citation key.
5. Confirm the report does not mention internal files, agents, prompts, or tools.
6. Write the complete Markdown answer to `/shared/output.md`.
7. Do not use edit loops or search-and-replace passes to repair citation
   numbering. Deterministic post-processing verifies and sanitizes citations
   after `/shared/output.md` is written.
