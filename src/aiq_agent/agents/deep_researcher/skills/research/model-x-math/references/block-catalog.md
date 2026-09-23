# Block catalog

> **Scope:** this table documents the **legacy `"mode":"deal"` path** in `scripts/mxm/blocks.py` (the
> `sample_deal.json` self-test fixture). The **live path is `build.py::build_operating`** — the operating
> engine (`operating.py`) plus the all-equity valuation layer (`valuation.py`), documented in
> `references/operating-canonical.md` and `references/valuation.md`. In the live valuation model Net Debt is
> presented **before** Dividends, there is **no Balance Sheet / revolver / LBO**, and rate drivers are
> per-line "reported %" rows (except NWC). Only `net_debt` below is shared with the live path.

Each block is a function in `scripts/mxm/blocks.py`. `build.py` runs them in the order below
(the visual order). Every block reads a sub-dict of the deal JSON. Historical arrays have
length `n_hist`; forecast driver arrays have length `n_forecast`. All blocks register their
rows by semantic name so other blocks reference them via `S.rref(name)` / `S.cref(name, i)`.

| # | Block (fn) | JSON key | Reads | Emits (named rows) |
|---|---|---|---|---|
| 1 | `entry_and_sources` | `deal` | `entry_multiple`; uses `EBITDA`, `nd_netdebt` | `ent_ltm/mult/ev/nd/eq`, `su_debt/equity/total`, Check |
| 2 | `income_statement` | `pnl` | `revenue`, `revenue_growth`, `ebitda`, `ebitda_margin`, `da`, `da_pct`, `tax_rate` | `Revenue`, `EBITDA`, `DA`, `EBIT`, `Interest`, `EBT`, `Tax`, `NetProfit` |
| 3 | `cash_flow` | `cf` | `nwc_pct`, `cash_eop_hist`, (opt `nwc`) | `CFO`, `CFI`, `CFF`, `cash_eop`, `div_avail` |
| 4 | `capex` | `capex` | `capex_pct`, `maint_split` | `capex_maint`, `capex_growth`, `capex_sum` |
| 5 | `debt_schedule` | `debt` | `repay_pct`, `debt_hist`, `interest_rate` | `debt_bop/eop`, `debt_repay`, `int_sched`, `nd_ebitda` |
| 6 | `dividends` | `dividends` | `payout`, `spv_stake` | `div_payout/stake/total/spv` |
| 7 | `net_debt` | — | uses `cash_eop`, `debt_eop` | `nd_cash/debt/netdebt` |
| 8 | `exit_returns` | `deal` | uses `EBITDA`, `ent_mult`, `debt_eop`, `cash_eop`, `div_stake`, `div_spv`, `su_equity` | `ex_*`, `vc_<year>`, `IRR`, `MoM` |

## Key formula patterns (interactive)

- **Revenue**: actuals (blue), then `prev × (1 + growth_input)`. `% Growth` is the inverse in
  history (`cur/prev − 1`) and a blue input in the forecast.
- **EBITDA**: actuals, then `Revenue × margin_input`. `% Margin` inverse in history.
- **D&A** (negative): actuals, then `−(da_pct) × Revenue`.
- **EBIT** = `EBITDA + D&A`. **EBT** = `EBIT + Interest`. **Interest** ← debt schedule
  (`= int_sched`). **Tax** = `−EBT × tax_rate` (scalar in col G). **Net Profit** = `EBT + Tax`.
- **CFO** = `SUM(EBITDA : ΔNWC)`, ΔNWC = `−nwc_pct × Revenue` in the forecast.
- **Debt**: `EoP = BoP + Repayment`; `Repayment = −repay_pct × BoP`; `Interest = −rate × BoP`.
- **Net Debt** = `Debt − Cash`.
- **Cash roll**: `BoP = prior EoP`; `Change = CFO + CFI + CFF`; `EoP = BoP + Change`.

## Adding or dropping a block

- To **drop** a block, add a `"blocks"` list to the JSON naming only the blocks you want (the
  block names are the fn names in the table). Omitted blocks are skipped.
- To **add** a new block, write a function `my_block(S, cfg)` that reserves rows via
  `S.section(...)`, `S.line(...)`, `S.sub(...)`, `S.check(...)`, register it in
  `build.BLOCK_ORDER`, and reference other blocks only by name. Keep it acyclic.
