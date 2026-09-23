# FX and scaling up

The default deliverable is **one flat sheet, one currency, inline blue inputs**. Reach for
the extensions below only when a specific deal needs them — do not add complexity by default.

## Currency conversion (in-place, per-period) — implemented

Operating mode supports **live, in-Excel currency conversion**. Source data is entered in its
native currency (the primary / source of truth); the model **displays in a reporting currency**
(usually USD), driven by an **editable per-period FX row**. Because a real FX rate is not stable
across time, the rate is **one editable cell per year**, not a single scalar — historical actuals
and forward years can each carry their own rate. Add a `currency` block to the operating JSON:

```jsonc
"currency": {
  "source":    "INR",           // currency the input arrays are in (primary)
  "reporting": "USD",           // display currency
  "unit":      "m",             // label suffix → "(in USD m)"; default "m"
  "rate":      90.0,            // scalar source-per-reporting, broadcast to every year, OR:
  "rates":     [76, 80, 83, 83] // per-period source-per-reporting (fitted to the axis length)
}
```

How it works (owned by `sheet.py` / `operating.currency_block` / `build.build_operating`):

1. A **`Currency` section with an `FX rate` row** is reserved at the top of the sheet — one blue,
   editable cell per year (source units per 1 reporting unit).
2. Every money input is written as **`=<native>/<that year's FX cell>`** (column-relative,
   row-absolute), so the whole model displays in the reporting currency and **editing any FX cell
   re-drives that year's column live**. Ratios (% margin, % growth, tax %, Net Debt / EBITDA) are
   quotients of two converted cells, so they are **FX-invariant** — correct, a margin or a leverage
   multiple must not move with currency.
3. Provenance is preserved: converted inputs stay **blue** (the native number is visible inside the
   formula); the FX row is `currency=False` so the rates are never self-converted.

Omit the `currency` block (or set `reporting == source`) for a single-currency model — behaviour is
unchanged. Deal/forecast-mode FX is not wired yet; the `currency` flag on `ModelSheet.line()` makes
it a small follow-up. See `assets/sample_operating_fx.json` for a worked INR→USD example.

### Second currency (side-by-side mirror) — alternative, not built

If a deal instead needs **two currencies shown at once** (e.g. a €m exit off a $m model), keep the
model in its primary currency and add a right-hand column group `=<primary cell> * $<fx cell>`. This
mirror is not implemented in the helper — build it only when a reader explicitly needs both columns.

## Scaling to a larger operating model

Some businesses need a **bottom-up revenue build** rather than a single seeded Revenue line
(e.g. product/segment lines × volume × price, or a cohort/conversion build). When that is the
case:

- Add a driver block *above* the P&L that reserves the segment rows and subtotals them into
  `Revenue`, then let the P&L consume `Revenue` exactly as today. Everything downstream is
  unchanged because it references `Revenue` by name.
- If the driver set is large or the client wants an editable assumptions area, move the blue
  inputs to a separate **Assumptions** sheet and reference them across sheets. A **Running
  Case** scenario switch (`CHOOSE(case, mgmt, base, downside)`) can then re-drive the model.

These are deliberately out of scope for v1's helper — the single sheet covers the
house style, which is the target. Build the bottom-up/multi-sheet variant by extending
`blocks.py` with new block functions and a second `ModelSheet`, reusing the same `style.py`
tokens so the look stays identical.

## Multi-period conventions

- The period axis is annual. The first year is treated as the earliest actual; the
  actual/forecast split is `n_hist` / `n_forecast`. CAGR columns (via `RRI`) and an LTM/stub
  first column are present in the gold standard and can be added to `periods.py` if needed —
  they are cosmetic and not required for the model to foot.
