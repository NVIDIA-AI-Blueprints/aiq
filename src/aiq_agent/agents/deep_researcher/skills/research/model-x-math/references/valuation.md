# Valuation layer

Added when the spec carries a `deal` block. Two parts, all formula-driven and editable, in the house
style: **Returns on the model sheet** and a **DCF tab**. The model self-checks (the Sources − Uses Check
row) and the recalc gate flags any 0/blank key metric. **Every deal is ALL-EQUITY** — there is no
Balance Sheet section, no revolver, and no LBO tab.

## 1. Returns — on the model sheet (the fixed house layout)

Appended in this order: **Entry Balances · Transaction Assumptions · Sources & Uses · … Debt Schedule ·
Net Debt · Dividends · Returns · Model X - Key Ratios** (Net Debt is presented **before** Dividends). The
forecast is projected from the entry balances; **history carries only P&L + Capex** — every derived cash /
debt / tax row is forecast-only (no inferred historical data).

- **Entry Balances (at Deal Close):** editable `Entry Cash` / `Entry Term Debt` cells — default to the
  latest reported actuals ("use latest entry values"). The first forecast year's Cash BoP and Term Debt BoP
  link to these cells, and the Transaction bridge reads entry Net Debt = `Entry Term Debt − Entry Cash`.
- **Transaction Assumptions:** `LTM EBITDA × Entry Multiple → EV`; `− Net Debt → Pre-money`; `+ Primary
  Injection → Post-money Equity`.
- **Sources & Uses:** Net Debt + Total Equity fund EV+PI; a Check row foots to 0. SPV takes `spv_stake` of
  the equity (its ticket).
- **Debt Schedule:** Term Debt BoP → Repayment (editable `Repayment %` row) → EoP; Interest is **calculated
  here** (editable `Cost of debt %` row × average balance) and linked up into the P&L Interest line; ends
  with **Gross Debt / EBITDA**.
- **Net Debt:** Cash · Debt · Net Debt · **Net Debt / EBITDA**.
- **Dividends** (order: Payout → Cash available → Total Dividends → SPV Stake → Dividends to SPV):
  `Cash available = CFO + CFI + Interest + Debt Repayment` — the year's own cash generation, **excluding
  Cash BoP** and dividends; `Total Dividends = Payout% × max(0, available)`; `to SPV = × stake`.
- **Returns:** per exit year — `Exit EV = EBITDA × Exit Multiple` (Exit Multiple **links to the entry
  multiple** by default); `Equity = EV − Debt + Cash`; `× stake`; a value-creation matrix (`−ticket`,
  interim SPV dividends, exit proceeds) → `XIRR` / `MoM`.
- **Key Ratios:** Gross/Net Debt, leverage, historical Revenue/EBITDA CAGR, then a **fixed house
  returns-metrics block** (always the same rows): EBITDA · Dividends · Free Cash Flow (House Definition = EBIT)
  · Cash Flow Conversion % (FCF/EBITDA) · Cash Yield % (FCF / entry Total Equity) · Dividend Yield %
  (Dividends / entry Total Equity).

**Reported-% referencing (line → % row → assumption cell).** Each rate driver is a single editable cell in
the top **Assumptions block** (Tax rate · Cost of debt · Capex % · Repayment % · NWC % · Maint split). Each
line item references a "reported %" row directly **below** it (Tax → Tax Rate %; Interest → Cost of debt %;
Capex → Capex as % of Revenue; Repayment → Repayment % of opening debt), and that % row in turn **links to
its assumption cell** (`=$G$xx`) — one source of truth, never a value hardcoded across the forecast columns.
(The Capex % row shows the actual historical intensity as a *derived* value, and links to the assumption in
the forecast.) The **one exception is NWC**, whose line references the top `nwc_pct` cell **directly** (no
intermediate row), applied to the *change* in revenue.

```jsonc
"deal": { "entry_multiple": 10.0, "spv_stake": 0.70,
          "primary_injection": 0.0, "payout": [0.5, 0.8, 0.8, 0.8, 0.8] }
```

Entry Net Debt defaults to the latest reported cash/debt; override with an `"opening": { "cash": …,
"debt": … }` block. `exit_multiple` is no longer read — the exit multiple links to the entry multiple (edit
the cell in Excel for a different exit).

## 2. DCF — its own `DCF` tab (logic from SKILL(13))

`WACC = Ke·1/(1+D/E) + Kd·(D/E)/(1+D/E)`, `βL = βu[1+(1−tax)D/E]`, `Ke = Rf + βL·ERP + size`,
`Kd = Rd(1−tax)`. Unlevered `FCFF = NOPAT + D&A + Capex + ΔNWC` off the model forecast; mid-year discounting;
Gordon `TV = FCFF_T(1+g)/(WACC−g)`; `EV = ΣPV(FCFF) + PV(TV)`; `Equity = EV − Net Debt`; implied EV/EBITDA;
a **WACC × g** sensitivity grid. Inputs are editable blue cells (Damodaran fallbacks); the DCF values the
scenario the model toggle currently selects.

```jsonc
"dcf": { "rf": 0.04, "beta_u": 1.0, "erp": 0.06, "size_premium": 0.02,
         "cost_of_debt": 0.055, "de_ratio": 0.30, "tax_rate": 0.25, "perp_growth": 0.03 }
```

> **No LBO tab.** All deals are all-equity, so the leveraged LBO variant does not exist (the `lbo.py` module
> was removed). Sponsor leverage is out of scope for this model.

## Editability & the "ask if unknown" rule

Every driver is a blue cell the user can overwrite by hand (multiples, stake, payout, WACC build, leverage,
rates). When the source doesn't give a needed input, the agent asks once, else falls back to a documented
placeholder that is trivially editable in Excel. The recalc gate (`mxm.verify`) now fails on any key metric
(IRR/MoM/EV/Equity/Ticket/Sources/Uses) that recalculates to **0 or blank** — catching silent wiring bugs,
not just `#REF!`.
