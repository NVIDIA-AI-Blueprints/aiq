# Canonical operating model (optionally projected)

The **default** ask. Build from source data (rich or thin) the *same fixed set of financial
indicators every time* — the canonical skeleton any PE operating model needs (the worked examples in
`assets/` all share it). `"mode": "operating"` in the JSON.
With `n_forecast > 0` the same skeleton is **projected into the future** (see "Forecast" below); with
no forecast it is actual years only. No entry/exit/returns, no dividends — that valuation layer is
separate and added later.

## Forecast (management / our / both)

When `n_forecast > 0`, each forecast column comes from one of three sources, chosen by the input:

- **Management case** — the company's own numbers, sourced blue. Provide `*_mgmt` forecast arrays:
  `revenue_mgmt`, `ebitda_mgmt`, `da_mgmt` (P&L) and `cf.nwc_mgmt` / `cf.cash_mgmt` /
  `capex.total_mgmt` / `debt.debt_mgmt`. %-rows (Growth/Margin) then **derive** (`cur/prev−1`, etc.).
  A forecast **always spans ≥ 5 years** (`MIN_FORECAST`): years the company doesn't disclose are
  **extrapolated live** — the value line becomes `prev × (1 + growth)` off an **editable driver cell**
  (default = last disclosed management growth; EBITDA/D&A hold the last margin / %-of-revenue). Beyond
  the disclosed horizon, ΔNWC/capex fall to the `nwc_pct`/`capex_pct` assumptions and debt to
  `repay_pct` — all editable, so the whole tail re-drives from cells.
- **Our case** — assumption-driven. Provide per-period driver arrays `revenue_growth`,
  `ebitda_margin`, `da_pct` (blue rows on the sheet), plus the Assumptions-sheet scalars
  (`nwc_pct`, `capex_pct`, `interest_rate`, `tax_rate`, `repay_pct`). Forecast values become formulas
  (`prev×(1+growth)`, `rev×margin`, `−pct×rev`, `BoP−repay%×BoP`, cash roll).
- **Both** — supply management arrays *and* our drivers, and list `"scenarios": ["management","our"]`.
  A **Scenario selector** (blue cell, col G) is emitted and each forecast value line becomes
  `=CHOOSE($G$scenario, <mgmt cell>, <our formula>)`. Flip the cell to re-drive the whole projection.
  The realised %-rows stay derived; the mgmt value and the our driver appear as `↳` sub-rows.

The mechanism is uniform: historical columns are always sourced blue; the mgmt/our/toggle choice only
governs the forecast columns. Currency (the FX row) and the Assumptions sheet apply throughout.

## The canonical skeleton (always produced)

| Block | Lines |
|---|---|
| **Income Statement** | Revenue · % Growth · EBITDA · % Margin · D&A · % of Rev · EBIT · % Margin · Interest expense · EBT · % Margin · Tax expense · Tax Rate % · Net Profit · % Margin |
| **Cash Flow Statement** | EBITDA · (−) Tax · (−) ΔNWC · Cash Flow from Operations · Change in NWC as % Rev · (−) Maint Capex · (−) Growth Capex · Cash flow from Investing · (−) Interest · (−) Debt Repayment · Cash flow from Financing · Cash BoP · Change in Cash · Cash EoP |
| **Capex** | Maintenance · Growth · Total |
| **Debt Schedule** | Debt BoP · (−) Repayment · Debt EoP · Interest Expense · Net Debt / EBITDA |
| **Net Debt** | Cash · Debt · Net Debt |
| **Free Cash Flow** | EBITDA · (−) Tax · (−) ΔNWC · (−) Capex · (−) Interest · **Free Cash Flow** · FCF Conversion |

## Sourced vs assumed (the fill-or-assume rule)

Every line is computed across **all** actual years as either a sourced actual or an
assumption-driven formula:

| Line | If in source | Else (assumption on the Assumptions sheet) |
|---|---|---|
| Revenue | input (**required**) | — |
| EBITDA | input | `Revenue × ebitda_margin` |
| D&A | input | `−da_pct × Revenue` |
| EBIT | — | `= EBITDA + D&A` (always derived) |
| Interest | input | `−interest_rate × Debt EoP` |
| Tax | input (Tax Rate% = effective `−Tax/EBT`) | `−tax_rate × EBT` |
| ΔNWC | input | `−nwc_pct × Revenue` |
| Total Capex | input | `−capex_pct × Revenue` |
| Maint / Growth Capex | — | `maint_split` × Total / `(1−maint_split)` × Total |
| Debt EoP | input | `0` if absent |
| Cash EoP | input | `Cash BoP + Change in Cash` (seed with `cf.opening_cash`) |

## The Assumptions sheet

Built by `mxm/assumptions.py`. Only the assumptions actually used are shown (plus `maint_split`,
always). Each is an **editable blue cell** in column E with a **cell comment** giving the
rationale — *why this value and on what basis* — prefixed `ASSUMED:` (or
`ASSUMED (default — review):` when it fell back to a built-in default because you gave no
rationale). The model references these cells absolutely (`Assumptions!$E$<row>`), so **editing an
assumption recalculates the whole model**.

Built-in defaults (override via the JSON `assumptions` block): ebitda_margin 30%, da_pct 5%,
tax_rate 25%, interest_rate 8%, nwc_pct 3%, capex_pct 5%, maint_split 65%. These are last-resort
fall-backs, not target values — a value driven off the source's own evidence almost always beats a
default, and a default that survives should still carry a rationale for *why it fits this business*.

## Plausibility guardrails (a second look, not hard limits)

After building, glance at each driver/output and ask "is this believable for THIS business?" Rough
bands that should prompt a re-check (not enforce a value) — reason about the exceptions, they are real:

- **EBITDA margin** ~5–40% for most operating businesses (software/IP can run 40%+; distribution/retail
  low single digits). A 60% margin on a distributor, or 3% on a software firm, means check the basis.
- **Effective tax** ~10–35% (statutory band across geographies); &lt;10% or &gt;40% wants an explanation
  (losses/shields, withholding, one-offs).
- **Net Debt / EBITDA** ~0–6× for a going concern; negative = net cash (a startup or a de-levered
  cash cow), &gt;6× = aggressive/distressed — intended, or a seeding error?
- **Capex % of revenue** ~1–3% asset-light, ~5–15% asset-heavy; **D&A** usually 2–10% of revenue and,
  over time, in the neighbourhood of maintenance capex.
- **Revenue growth**: does the forward driver match the business's stage and the recent trend?

An out-of-band value is not automatically wrong — but it must be *reasoned and documented*, not
accidental. If it's accidental, fix the assumption.

## Mapping arbitrary source → the skeleton

- **Rich source** (full P&L with many OpEx lines): aggregate them into the skeleton — sum all
  operating costs so EBITDA ties, take D&A, interest, tax as reported. Few or no assumptions.
- **Thin source** (only revenue, or revenue + a couple of lines): source what exists, assume the
  rest with a clear rationale (peer margins, sector norms, disclosed leverage). The model still
  emits the full skeleton — see `assets/sample_thin.json` (only Revenue + Debt sourced).
- **Provenance is visible:** sourced numbers are **blue** on the model sheet; assumed drivers are
  the **yellow editable cells** on the Assumptions sheet with rationale comments; everything else
  is a black formula.

## JSON shape

```jsonc
{
  "mode": "operating",
  "company": "...", "units": "(in $m)", "start_year": 2022, "n_hist": 4,
  "pnl":  { "revenue": [...],           // required; others optional → assumed if absent
            "ebitda": [...], "da": [...], "interest": [...], "tax": [...] },
  "cf":   { "nwc": [...], "cash_eop": [...], "opening_cash": 0 },
  "capex":{ "total": [...] },
  "debt": { "debt": [...] },
  "assumptions": { "maint_split": {"value": 0.65, "rationale": "why + basis"}, ... }
}
```
All actual arrays have length `n_hist`. Any metric you omit is filled from an assumption.
