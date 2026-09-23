# Orchestration reference — artifacts + inline phase briefs

How an AI-Q researcher worker records the model-build phases while the deep-research orchestrator
controls the overall job. See the "Running this skill in AI-Q" section of `SKILL.md` for the pipeline
overview. Write phase outputs below the exact `sandbox_workdir` supplied in the system prompt.

**Capability gate:** first check your tools. `execute` is required for build and verification. AI-Q
researcher workers perform the EXTRACT and QA phases inline for their assigned query.

## Working files (small JSON under `sandbox_workdir`, so your context stays light)

`evidence/<section>.json` — one per delegated extraction (pnl, balance_sheet, cash_flow, deal, business):
```jsonc
{
  "section": "pnl",
  "currency": "EUR", "unit": "m",
  "period_boundary": { "last_actual_year": 2024, "forecast_from": 2025 },
  "lines": [ { "metric": "revenue", "years": {"2020":578,"2021":671,"2022":860,"2023":827,"2024":835},
              "source": "p6 revenue chart", "basis": "reported" } ],
  "trap_flags": [ "slide 'EBITDA %' is % of gross margin, not EBITDA/revenue — recomputed ~21%" ],
  "notes": "run-rate EBITDA series also disclosed (RR Adj): 143/170/176/168/174"
}
```
`evidence/pack.json` — you merge the sections into the shape the reasoning procedure consumes (the
canonical skeleton keys: revenue/ebitda/da/interest/tax/nwc/capex/debt/cash + boundary + currency).

`assumptions.json` — per gap: `{ "key": "da_capex_pct", "value": 0.35, "method": "% of capex",
"basis": "capex-heavy packaging; D&A trails capex", "confidence": "med", "material": false }`. Plus a
top-level `open_questions` array (the material ones you'll put to CHECKPOINT 2).

`spec.json` — the mxm deal spec (schema in `SKILL.md` / `references/operating-canonical.md` /
`references/valuation.md`). Every number traces to `evidence` or a documented `assumptions` entry.

`qa/<lens>.json` — `{ "lens": "grounding", "findings": [ { "severity": "high",
"issue": "EBITDA 2024 in spec is 174 but source shows 140 reported / 174 run-rate — basis mismatch?",
"fix": "confirm run-rate basis at CHECKPOINT, or switch series" } ], "verdict": "changes_needed" }`.

## Inline phase briefs

**EXTRACT — apply to the assigned source evidence:**
> "Use the configured source tools for the ⟨PnL / balance sheet / cash flow / deal terms /
> business description⟩. Extract every disclosed figure onto these canonical lines where present:
> revenue, EBITDA (note reported vs adjusted/run-rate), D&A, interest, tax, ΔNWC, capex (split if given),
> debt, cash — with the year for each and a short source cite (page/section). Record units, currency, and
> the last-actual→forecast boundary. FLAG definition traps: is any 'margin' on gross profit not revenue?
> reported vs adjusted EBITDA? a headline CAGR vs recent trend? Write it all to
> ⟨sandbox_workdir/evidence/<section>.json⟩ (schema in references/orchestration.md). Return a 3-line summary:
> what you found, the boundary, and any trap flags. Do NOT assume missing values — only report what's
> disclosed."

**QA — run each lens inline; each writes `qa/<lens>.json` and records a verdict:**
- **grounding / anti-hallucination — BLOCKING:**
  > "Re-check the configured sources. For every BLUE (sourced) number in
  > `sandbox_workdir/spec.json` (revenue,
  > EBITDA, debt, capex, per year), find it in a source and compute the % difference. Any number that is
  > **>10% off the source, or absent**, is a HARD FAIL — the model must not ship with it. Also flag basis
  > mismatches (reported vs run-rate, currency, year). Write qa/grounding.json with each number, its
  > source value, and the % diff; return verdict `blocked` if any >10% divergence, else `ok`."
  (On `blocked`, fix the extraction or flag the question for the user — never ship.)
- **plausibility:** > "Open `sandbox_artifact_dir/out.xlsx` with Python/openpyxl and check drivers+outputs against the
  bands in references/operating-canonical.md. FLAG specifically: D&A > ~15% of revenue; cost of debt
  outside 4–10%; flat revenue growth on a levered deal; rollover = 0 on a sponsor deal; NWC > ~10% of
  revenue; capex wildly off sector; margin/tax/leverage/IRR out of band. Write qa/plausibility.json;
  a flag → the orchestrator revisits the assumption or asks the user."
- **assumption defensibility:** > "Read `sandbox_workdir/assumptions.json`. Challenge each rationale — is the
  method the best-anchored one given the evidence, or a lazy default? Write qa/defensibility.json."
- **trap re-check:** > "Verify the EBITDA basis (reported vs adjusted), the margin denominator, and the
  forward growth vs recent trend against the sources. Write qa/traps.json; return the verdict."

## Checkpoint question shapes for the orchestrator
- **CP1 confirm extraction:** e.g. "Which EBITDA basis should price the deal?" → ["Reported", "Run-rate /
  adjusted", "Show both as a toggle"]; "Actual→forecast boundary looks like ⟨2024⟩ — correct?" → [yes / pick].
- **CP2 assumptions (ASK every material driver, recommended default pre-selected):** scope → ["Operating
  only", "Full valuation (all-equity deal + DCF)"]; **D&A basis** → ["% of capex (capex-heavy)", "% of revenue
  (asset-light)"]; **LTM basis** → ["Trailing (last actual)", "Forward (FY+1 run-rate)"]; entry multiple;
  **cost of debt %**; **rollover %**; growth stance; capex %. single/multi/rank. Only genuinely
  immaterial gaps get a silent placeholder — the drivers above are what past bad models got wrong.
- **CP3 final review:** "The model is built and QA is clean except ⟨…⟩. Proceed to save?" →
  ["Save to the company report", "Download only", "Change ⟨X⟩ first"].

## Scoping rules
- Keep each phase at a **distinct output path** so evidence and QA records never overwrite one another.
- Use source tools for extraction and `execute` for openpyxl/build/verification.
- If the worker reaches its tool or model-call cap, return the unfinished phase as an explicit gap rather
  than trusting a partial result.
