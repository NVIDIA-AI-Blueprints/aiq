---
name: model-x-math
description: Build a compact, single-sheet integrated investment model ("Model X Math") from a company's financials and deal terms. Use when the user wants a private-equity style all-equity deal model — entry valuation, sources & uses, a top-down P&L, cash flow, capex, debt schedule, dividends, exit, and IRR/MoM — all live formulas on one professionally styled sheet. The visual design is fixed and identical every time (a stable house style); only the line-item content flexes per deal. Output is an interactive Excel workbook where changing any blue assumption re-drives the whole model. Verified post-generation by real-engine (LibreOffice) recalculation.
---

# Model X Math — single-sheet integrated deal model

You are a private-equity analyst. Build a **compact, one-sheet investment model** from
the company's historical financials and the deal terms. The output looks exactly like the
firm's house standard (the "Model X Math" style) and is fully formula-driven: change a blue
input and the whole sheet re-computes.

## Running this skill in AI-Q

You are an AI-Q researcher worker assigned by the deep-research orchestrator. Work only from the assigned
research query, available research context, and configured source tools.

### STEP 0 — check your tools FIRST, then follow the matching path (do not skip this)
Look at the tools you actually have and announce the mode you'll run in:
- **`execute` — REQUIRED.** You need it to run `python -m mxm.build` + LibreOffice. If you do NOT have
  `execute`, STOP and say the skill can't run here (it needs a sandbox) — never fake a model.
- AI-Q researcher workers do not perform nested delegation or interactive user checkpoints. Run the EXTRACT
  and QA phases inline for the assigned query. Use documented placeholders for unresolved inputs and flag
  them in the returned notes for the orchestrator to surface.

This is a MUST-do pipeline, not a suggestion. The artifact schemas + copy-paste sub-agent briefs are in
`references/orchestration.md`.

**Runtime (use these exact tools/paths):**
- This skill's executable code is seeded at `/workspace/skills/model-x-math/`.
- The current job's exact `sandbox_workdir` and `sandbox_artifact_dir` are supplied in your system prompt.
  Write `spec.json` and intermediate files under `sandbox_workdir`. Write `out.xlsx` under
  `sandbox_artifact_dir` so AI-Q can harvest it.
- Run via `execute`:
  `cd /workspace/skills/model-x-math/scripts && python3 -m mxm.build <sandbox_workdir>/spec.json <sandbox_artifact_dir>/out.xlsx`
  then `python3 -m mxm.verify <sandbox_artifact_dir>/out.xlsx`. LibreOffice recalc is slow; use the
  **180s** execute window.
- Read assigned plan/context files under `/shared/` with `read_file`; shell commands cannot access
  `/shared/`. Use the configured source tools, including knowledge retrieval for uploaded documents.
- Return a short **reasoning report** (sourced / assumed-why / asked / flagged) in `ResearchNotes`.
  AI-Q automatically harvests the workbook from `sandbox_artifact_dir`.

**Pipeline:**
1. **EXTRACT — run inline for the assigned query.** Use the configured source tools to collect the relevant
   P&L, balance sheet, cash flow, deal terms, and business-description evidence. Write
   `evidence/<section>.json` under `sandbox_workdir` and merge it into `evidence/pack.json`.
2. **CHECKPOINT 1 — extraction review.** Record headline figures and trap flags (is that "margin" on
   revenue or gross profit? reported vs adjusted EBITDA? where is the actual→forecast boundary?) in the
   reasoning report for the orchestrator to surface.
3. **FRAME + ASSUMPTIONS (you).** Apply "How to REASON" (below): classify each line
   sourced/derivable/must-assume, reason each gap; produce the drivers + a shortlist of MATERIAL unknowns.
4. **CHECKPOINT 2 — assumptions review.** Flag every material driver you couldn't pin from the source:
   **scope** (operating vs
   valuation); **entry multiple / leverage**; **EBITDA basis** (reported vs run-rate) & **LTM basis**
   (trailing vs forward); **revenue growth** stance; **D&A basis & %** (capex-linked vs revenue);
   **cost of debt %**; **SPV stake / seller rollover %**; **capex %**. Present each as single/multi/rank
   options with your recommended default pre-selected. "If unsure → ASK." Only genuinely immaterial gaps
   get a silent documented placeholder. (These are exactly the assumptions past bad models got wrong.)
   - **SPV stake is NOT 100% by default.** The sponsor rarely buys out the whole equity — ask the seller
     **rollover %** (sponsor stake = 1 − rollover) and never ship a 100% stake without confirming it.
     (`deal.rollover_pct` / `deal.spv_stake` drive it; the stake cell is linked to the rollover input.)
5. **COMPOSE + BUILD + VERIFY (you, `execute`).** Write the job's `spec.json`; build + verify;
   repair-loop until `mxm.verify` is `status: ok`. **The Sources − Uses check must foot to 0** and every
   key metric (IRR/MoM/EV/Equity/Ticket) must recalculate to a non-zero value — verify enforces this.
6. **QA — run inline and adversarially.** Write `qa/<lens>.json` under `sandbox_workdir` for each lens:
   - **grounding — BLOCKING.** Re-read the sources and confirm every *sourced* number (revenue, EBITDA,
     debt, capex) matches. **A >10% divergence from the source is a HARD STOP** — do not ship; fix the
     extraction or ASK the user. (This is what catches "debt 3× / revenue 55% off the real document".)
   - **plausibility.** Flag out-of-band drivers against the bands in `references/operating-canonical.md`
     — e.g. D&A > ~15% of revenue, cost of debt outside 4–10%, flat growth on a levered deal, rollover
     = 0 on a sponsor deal, NWC > ~10% of revenue, capex wildly off sector. A flag → revisit or ask.
   - **assumption defensibility** and **trap re-check** (margin basis, reported-vs-adjusted, ΔNWC on the
     *change* in revenue not the level). Fix findings; re-run until clean.
7. **CHECKPOINT 3 — final review.** Return the model artifact reference, QA findings, and reasoning report
   for the orchestrator to present to the user.
8. **PERSIST.** Keep `out.xlsx` under `sandbox_artifact_dir` and return the reasoning report.

The reasoning process below applies within each phase, whether you run it yourself or hand it to a child.

**Why execution might not fire (troubleshooting).** The SKILL.md cannot grant tools. AI-Q exposes
`execute` only when the researcher is sandbox-enabled. If `execute` is absent, stop rather than
pretending to build a workbook. Nested delegation and interactive checkpoints are handled outside the
researcher worker; run their analysis inline and return unresolved decisions to the orchestrator.

## Core principle: stable design, flexible content

Two things are separated on purpose:

- **The DESIGN is fixed.** A thin helper (`scripts/mxm/`) owns the entire look — the navy
  header band, the `x`-marked grey section headers, blue inputs, yellow assumption boxes,
  bold totals, number formats, `2025A`/`2026E` year suffixes. **Never restyle cells by
  hand.** You get the house style for free by using the helper.
- **The CONTENT flexes.** Which blocks you include and the line items inside them depend on
  the deal. You express that as a JSON deal spec; the helper renders it consistently.

Do not write a bespoke openpyxl script from scratch and do not edit the template by hand.
Compose the model through the helper.

## How to REASON when building from a source (do this first — every time)

This skill cannot enumerate every company or every data shape — that is impossible, and no rule table
would cover them. **Your job is to reason like an analyst about the specific document in front of you**,
then express that reasoning as the spec. The steps below are a thinking process, not a lookup: at each
one you apply judgment to what THIS source actually gives you. The examples are illustrations of the
reasoning, never "the rule."

1. **Read it as an analyst — what IS this business?** Before any number: what does it do, and what is
   its economic shape — asset-heavy or asset-light, growing or mature, already levered or not, cyclical
   or steady? This single read frames every later choice (a capex-heavy builder depreciates differently
   from a software firm; a mature cash cow carries more leverage than a startup). If you can't tell,
   that itself is a signal to be conservative and flag assumptions.

2. **Inventory onto the skeleton.** Map every disclosed number onto the canonical lines (Revenue,
   EBITDA, D&A, interest, tax, ΔNWC, capex, debt, cash). Note units, currency, and the actual→forecast
   boundary. **Watch definition traps** — they silently break models: is a quoted "margin" on revenue
   or on gross profit? Is a growth figure a recent trend or a headline multi-year CAGR? Is EBITDA
   reported or adjusted/run-rate? Verify the denominator/basis yourself rather than trusting a label.

3. **Classify each line: sourced / derivable / must-assume.** Sourced = disclosed, enter as a blue
   input. Derivable = compute from other disclosed lines (e.g. `EBITDA = EBIT + D&A`, or aggregate an
   itemised opex stack up to EBITDA) — prefer deriving over assuming. Must-assume = genuinely absent.

4. **For each gap, reason from the evidence you DO have — then document it.** Pick the method most
   anchored in what's disclosed; fall back to the business's sector economics; fall back to a flagged
   default only when you have nothing better. Then write the method + basis + your confidence into the
   assumption's rationale (it becomes the cell comment). The point is a *defensible chain of
   reasoning*, not a number. Illustrations (not rules): D&A → if capex is disclosed and the business is
   capex-heavy, tie D&A to capex; if asset-light, tie it to revenue; if a D&A figure exists, source it.
   Tax → disclosed effective rate if present, else the statutory rate for the company's geography.
   Growth → recent realised trend tempered by the business's outlook, not a headline CAGR pasted flat.

5. **Decide scope from the document's intent.** Just financials / an operating ask → operating model
   (no deal layer). A teaser/CIM with deal terms, an entry multiple, or an explicit valuation ask →
   add the `deal` block (Transaction Assumptions → S&U → Net Debt → Dividends → Returns, + a DCF tab). If the
   intent is ambiguous, say what you inferred and why (or ask — see step 7).

6. **Everything the source didn't give is an editable placeholder.** Never bury a judgement as a
   literal inside a formula. Each assumed value is a blue/yellow cell the user can change so the whole
   model re-drives. A model full of documented placeholders the user can adjust beats a model with
   invisible hardcodes.

7. **Ask vs. placeholder — by materiality.** If an unknown *materially* moves the answer (entry
   multiple, deal scope, entry leverage, which EBITDA basis) AND you cannot reason a defensible value,
   ask the user ONCE (a single AskUserQuestion). Otherwise drop a documented placeholder and move on —
   do not stall on immaterial gaps.

8. **Sanity-check the result, then revisit assumptions (not numbers).** After building, eyeball the
   outputs against plausibility: EBITDA margin, effective tax, leverage (Net Debt/EBITDA), capex % of
   revenue, IRR/MoM — are they in a believable range for THIS business? An implausible output means an
   assumption is wrong; fix the assumption, never hardcode the output. The `mxm.verify` recalc gate
   catches broken formulas; plausibility is on you.

Then compose the spec and build. The rest of this document is the mechanics that render your reasoning.

## What the model contains (block catalog)

Top-to-bottom, the blocks are (include the ones the deal needs):

1. **Transaction Assumptions** — LTM EBITDA × entry multiple → EV → less net debt → equity.
2. **Sources & Uses** — net debt + equity fund the purchase; foots to a Check row.
3. **Income Statement** — top-down: Revenue → EBITDA → D&A → EBIT → Interest → EBT → Tax →
   Net Profit, each with % Growth / % Margin sub-rows. Historicals are blue inputs; forecasts
   are driven by growth %, margins and rates.
4. **Cash Flow Statement** — EBITDA → Tax → ΔNWC → CFO → capex → CFI → interest/debt/dividends
   → CFF → cash roll (forecast-only; no revolver — all-equity).
5. **Capex** — maintenance / growth split; historical actuals are blue, forecast is % of revenue.
6. **Debt Schedule** — Term Debt BoP → repayment (editable %) → EoP; interest **calculated here**
   (editable Cost of debt % × average balance); ends with **Gross Debt / EBITDA**.
7. **Net Debt** — cash, debt, net debt, **Net Debt / EBITDA** (presented *before* Dividends).
8. **Dividends** — payout % × cash available (excludes Cash BoP), SPV stake → dividends to SPV.
9. **Returns** — exit EBITDA × multiple (exit links to entry) → equity to SPV; a value-creation
   matrix per exit year → **IRR (XIRR)** and **MoM**.

There is **no Balance Sheet section and no LBO tab** — every deal is all-equity.

See `references/block-catalog.md` for the exact inputs each block reads and the formula it
wires. See `references/returns-math.md` for the entry/exit/IRR/MoM mechanics.

## Workflow

1. **Read the source.** From the CIM / financials / deal sheet, extract:
   - historical **Revenue, EBITDA, D&A, cash, debt** (last N years);
   - **entry multiple**, **SPV stake**, tax rate, interest rate, capex % and maint split,
     NWC %, debt repayment %, dividend payout %, and the **exit multiple** (default = entry);
   - the actual/forecast boundary (how many years are real vs projected).
2. **Write the deal spec** as JSON. Copy `assets/sample_deal.json` and edit the numbers.
   Historical arrays are length `n_hist`; forecast driver arrays are length `n_forecast`.
   Omit a block by leaving it out of an optional `"blocks"` list.
3. **Build:** `python -m mxm.build <deal.json> <out.xlsx>` (run from `scripts/`).
4. **Verify (mandatory):** `python -m mxm.verify <out.xlsx>`. It recalculates with
   LibreOffice and must report `"status": "ok"` — **0 formula errors** and every **Check row
   ≈ 0**. If it fails, read the failing cells/checks, fix the spec or the block, rebuild.
5. **Eyeball it.** Optionally render `soffice --headless --convert-to pdf` and confirm the
   IRR/MoM are sensible and the design matches the house style.

## Rules that keep the model correct

- **Historicals are blue inputs; forecasts are formulas.** A row may mix the two (actuals,
  then a growth/margin-driven projection). Never hardcode a forecast you can drive.
- **Cross-block references go by name**, never by raw row number. Inside a formula callable
  use `S.rref("EBITDA")` / `S.cref("EBITDA", i)`; the registry resolves the row even if the
  referenced block sits lower on the sheet (e.g. P&L interest ← debt schedule).
- **Keep it acyclic.** Dividends read *pre-dividend* cash available; debt paydown does not
  depend on the P&L. If you add a block, do not create a circular reference — `verify` will
  not catch a cycle, but the numbers will be wrong.
- **The SPV invests its stake of the equity** and is paid its stake of the exit — both sides
  must use the same stake, or IRR/MoM will be nonsensical.

## Routing on the input (the operating engine)

The operating engine builds from `"mode": "operating"` (or any spec without a `deal` block) and
**routes on the input**:

- **No forecast in the input** (`n_forecast` absent/0) → the canonical skeleton on **actual years
  only**.
- **Forecast present or wanted** (`n_forecast > 0`) → the same skeleton **projected into the future**.
  When the input contains forecast numbers, **ask the user which forecast to build**:
  - **Management case** — the company's own projected numbers (e.g. a teaser's FY26E/27E/30E),
    entered as **sourced blue values** (`revenue_mgmt`, `ebitda_mgmt`, `da_mgmt`, and forecast
    `cf.*_mgmt` / `capex.total_mgmt` / `debt.debt_mgmt`); %-rows derive.
    **A forecast always spans ≥ 5 years** (`operating.MIN_FORECAST`): if the company discloses fewer,
    the model **extrapolates the tail with editable per-period driver cells** (growth defaults to the
    last disclosed management growth) — it never skips years, and every tail year is a live formula
    (`prev × (1 + growth)`) the user can re-drive in Excel.
  - **Our case** — an **assumption-driven** projection: per-period driver rows (`revenue_growth`,
    `ebitda_margin`, `da_pct`) plus the Assumptions-sheet scalars (`nwc_pct`, `capex_pct`,
    `interest_rate`, `tax_rate`, `repay_pct`).
  - **Both** — supply both, list `"scenarios": ["management","our"]`, and the sheet gets an **in-page
    Scenario selector** (a blue cell); each forecast value line becomes
    `=CHOOSE($G$scenario, <mgmt>, <our>)`, so flipping the cell re-drives the whole projection.
    (Built to grow — base/downside can be added later.) See `assets/sample_forecast_mgmt.json`,
    `assets/sample_forecast_both.json`.

**Returns / valuation / equity / DCF are a separate, later layer** — this engine is a pure operating
projection (no Transaction Assumptions, Sources & Uses, dividends, exit, IRR/MoM).

### Canonical operating model (`"mode": "operating"`)

Produces the **same fixed set of financial indicators every time** (the canonical skeleton, shared
by the worked examples in `assets/`). See `references/operating-canonical.md` for the full contract;
`assets/sample_operating.json` (rich source) and `assets/sample_thin.json` (only Revenue + Debt →
mostly assumed).

Two sheets:
- **`Assumptions`** — every assumption on its own tab: an **editable blue cell** with a **cell
  comment stating why and on what basis** you chose it. Built by `mxm/assumptions.py`.
- **`<Company> - Model X Math`** — the canonical skeleton. A metric present in the source is a
  **blue sourced input**; a missing metric is a **formula referencing the Assumptions sheet**
  (`= Assumptions!$E$7 * Revenue`), computed across all actual years so nothing is blank.

Because drivers are cells and lines are formulas, **editing an assumption (or a sourced actual)
recalculates the whole model.**

Your job: map whatever the source gives (many rows or few) onto the fixed skeleton, and fill
every gap with a documented assumption. Provide actuals under `pnl`/`cf`/`capex`/`debt` where
the source has them; for any metric you must assume, add
`"assumptions": { "<key>": {"value": ..., "rationale": "why + basis"} }`. Missing keys fall back
to built-in defaults (flagged "ASSUMED (default — review)"). Required source: `pnl.revenue`.
Assumption keys: `ebitda_margin, da_pct, da_capex_pct, tax_rate, interest_rate, nwc_pct, capex_pct,
maint_split` (`maint_split` is always used to split capex).

**Provenance for sourced data.** Cite where each historical number came from with a top-level `sources`
dict — `{"revenue": "Teaser p6 chart", "ebitda": "p6 RR-Adj", "capex": "...", "opening": "..."}`. It
renders a visible, editable **Data Sources & Provenance** section (one note per metric) so a reviewer
can trace every blue input to the document. Always fill it for sourced actuals — undocumented historical
data is a review red flag.

**D&A basis (revenue vs capex) — reason from asset intensity.** Missing D&A defaults to
`da_pct × revenue`. But depreciation *follows the asset base*: for a **capex-heavy** business (a
manufacturer building plants, an industrial, infrastructure) D&A trails the capex programme, so
`"pnl": { "da_basis": "capex" }` makes D&A `da_capex_pct × total capex` — usually more faithful. For an
**asset-light** business (software, services, a distributor) keep it on revenue. Choose per business,
not by rote. Interest, when not sourced, is charged on the **average** debt balance (opening/closing).

**Definition traps (reasoning step 2, made concrete).** These silently break models regardless of
sector, so verify the basis yourself: (1) a quoted "margin %" may be on **gross profit, not revenue** —
recompute EBITDA ÷ revenue from the absolute figures (a slide once headlined "34%" where the real
EBITDA/revenue was ~21%). (2) A headline multi-year **CAGR** is not the forward growth driver when
recent years are flat or declining — use a judged, editable growth. (3) Reported vs adjusted/run-rate
EBITDA can differ materially — decide which basis the deal is priced on and be consistent.

**Currency conversion (optional, live).** Enter data in its native currency and display the model
in a reporting currency (usually USD) by adding a `currency` block. An editable **per-period FX
row** sits at the top of the sheet; every money input becomes `=<native>/<that year's FX cell>`, so
changing any rate re-drives that year live, while margins / leverage stay FX-invariant. The rate is
per-period because it is not stable across time (past actuals vs forward years).

```jsonc
"currency": { "source": "INR", "reporting": "USD", "unit": "m",
              "rate": 90.0 /* or per-year */ "rates": [76, 80, 83, 83] }
```

Omit it (or set `reporting == source`) for a single-currency model. Currency **spans the forecast**
too (the FX row has a cell per year, including forecast). See `assets/sample_operating_fx.json`,
`assets/sample_forecast_mgmt.json`, and `references/fx-and-scaling.md`.

### Valuation layer (a `deal` block on the operating model)

Add a `deal` block and the operating+forecast model gains the valuation, in house style. **Every deal is
ALL-EQUITY** — a simplified "teaser" model with no Balance Sheet, no revolver, and no LBO tab.

- **Returns on the model sheet** (the fixed house layout): Entry Balances · Transaction
  Assumptions · Sources & Uses · … · Debt Schedule · Net Debt · Dividends · Returns · Key Ratios (which ends
  with a fixed **house returns-metrics block**: EBITDA · Dividends · Free Cash Flow (House Definition = EBIT) ·
  Cash Flow Conversion % · Cash Yield % · Dividend Yield %). Single term-debt line. The **Sources & Uses** carries the gold-standard equity split — New Debt · Rollover
  Equity · Sponsor SPV Equity on the sources side; Net Debt (refinanced) · Primary · Secondary · Rollover
  on the uses side (foots to a Check row). Set `"rollover_pct"` (share of purchase equity the existing
  holders roll; 0 = clean buyout); the sponsor funds the rest and `spv_stake` defaults to `1 − rollover_pct`.
- **History is P&L + Capex only — nothing is inferred.** The levered forecast is projected from the entry
  balances; every derived cash / debt / interest / tax / net-profit row is **forecast-only** (historical
  columns are blank unless the source actually discloses that metric). Only historical Revenue → EBIT and
  Capex are hardcoded blue actuals.
- **Reported-% referencing (line → % row → assumption cell).** Each scalar rate driver is a **single
  editable cell in the top Assumptions block** (Tax rate · Cost of debt · Capex % · Repayment % · NWC % ·
  Maint split). Each line references a "reported %" row directly below it (Tax → Tax Rate %; Interest → Cost
  of debt %, *calculated in the Debt Schedule*; Capex → Capex as % of Revenue; Repayment → Repayment % of
  opening debt), and that % row **links to its assumption cell** (`=$G$xx`) — one source of truth, never
  hardcoded per column. **NWC is the one exception** — its line references the top `nwc_pct` cell directly
  (no intermediate row), applied to the *change* in revenue.
- **A `DCF` tab** — WACC → FCFF → terminal value → EV → equity, implied multiples, WACC × g sensitivity.

Every driver is an editable blue/yellow cell; unknown inputs → ask once, else a documented placeholder.

**Entry balances (at deal close).** An **Entry Balances** section holds editable `Entry Cash` and `Entry
Term Debt` cells — they default to the **latest reported actuals** ("use latest entry values") and seed the
**first forecast year** (Cash BoP / Term Debt BoP link to them). The Transaction bridge reads entry Net Debt
= `Entry Term Debt − Entry Cash`. Override the defaults with an `"opening": { "cash": …, "debt": … }` block.
A `"primary_injection"` (growth/deleveraging equity cheque) flows through the forecast cash flow as a
`(+) Equity Injection` line.

**Entry timing & returns dates.** The **Deal Close Date** is an editable yellow date cell (default =
mid-year of the first forecast year); the entry leg of the XIRR reads it, so a mid-year close gives a
short, high-IRR first period. Override with `deal.close_date` ("YYYY-MM-DD") — keep it on/before the
first exit year-end or that exit's IRR goes negative (exit-before-entry). `deal.ltm_basis` picks the
entry EBITDA: `"trailing"` (last actual, default) or `"forward"` (first forecast — the analyst's FY+1
run-rate, a higher entry price → lower returns).

**Everything is an editable placeholder.** Any figure the source doesn't give — entry multiple, entry
cash/debt, close date, margins, growth, payout — is written as a **blue/yellow input cell** (never a
hardcoded literal buried in a formula), so the user can change it in Excel and the whole model re-drives.
When a genuinely material unknown has no reasonable default, ask the user once; otherwise drop a documented
placeholder cell and move on.

`deal` fields: `entry_multiple, spv_stake | rollover_pct, primary_injection, payout[], exit_year,
close_date, ltm_basis` (plus optional top-level `"opening": {cash, debt}`). The exit multiple links to the
entry multiple by default (`exit_multiple` is not read). See `references/valuation.md` and
`assets/sample_valuation.json`. (The legacy `"mode":"deal"` path in `blocks.py` still builds
`sample_deal.json`.)

**Verification note:** `mxm.verify` recalculates with LibreOffice and fails on `#REF!`-style errors,
any non-zero Check row (the Sources − Uses check), AND any **key metric (IRR/MoM/EV/Equity/Ticket) that
recalculates to 0 or blank** — so silent wiring bugs are caught, not just hard errors. It also prints the
key outputs for a sanity eyeball.

## Scaling up (optional)

The default is one flat sheet with inline inputs. For live currency conversion (above), a larger
operating model (bottom-up revenue build, scenario switch), or a side-by-side second-currency
mirror, see `references/fx-and-scaling.md`. Do not reach for the heavier extensions unless the deal
genuinely needs them — the single sheet is the deliverable in the overwhelming majority of cases.

## Files

- `scripts/mxm/` — the helper: `style.py` (house-style tokens), `periods.py` (time axis),
  `sheet.py` (named-row registry + layout), `blocks.py` (the block catalog), `build.py`
  (orchestrator), `verify.py` (recalc gate), `office/soffice.py` (sandboxed LibreOffice).
- `references/` — house style, block catalog, returns math, fx & scaling.
- `assets/sample_deal.json` — a complete worked (legacy) deal spec; the self-test fixture.
- `assets/sample_operating_fx.json` — operating model with live INR→USD currency conversion.
- `assets/sample_forecast_mgmt.json` — projected model, **management case** (sourced forecast) + currency.
- `assets/sample_forecast_both.json` — projected model, **management + our** with the Scenario toggle.
