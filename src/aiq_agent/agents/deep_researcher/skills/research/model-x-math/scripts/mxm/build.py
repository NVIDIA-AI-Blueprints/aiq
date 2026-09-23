"""
Build a Model X Math workbook from a JSON deal spec.

Usage:
    python -m mxm.build <deal.json> <out.xlsx>

The JSON drives WHICH blocks run and their inputs; the helper enforces the look.
See assets/sample_deal.json for the schema and references/block-catalog.md for the
per-block keys. Blocks are reserved top-to-bottom (visual order), then rendered
in one pass so cross-block formulas resolve regardless of order.
"""

from __future__ import annotations

import json
import sys

from openpyxl import Workbook

from . import blocks
from . import dcf
from . import operating
from . import valuation
from .assumptions import Assumptions
from .periods import PeriodAxis
from .sheet import ModelSheet

# visual order of the sheet; each maps to a config sub-key (None = no config)
BLOCK_ORDER = [
    ("entry_and_sources", "deal"),
    ("income_statement", "pnl"),
    ("cash_flow", "cf"),
    ("capex", "capex"),
    ("debt_schedule", "debt"),
    ("dividends", "dividends"),
    ("net_debt", None),
    ("exit_returns", "deal"),
]


def _finalize(wb: Workbook) -> Workbook:
    # Force a full recalculation when the file is opened in any real spreadsheet app. openpyxl writes
    # formulas but never computes them, and in the gVisor sandbox LibreOffice can't recalc either
    # (AF_UNIX sockets are blocked), so without this the file would read back as all-null. With it, Excel
    # / Google Sheets / any viewer recomputes on first open — no null values.
    wb.calculation.fullCalcOnLoad = True
    return wb


def build(data: dict) -> Workbook:
    # Operating engine (actuals, optionally projected) unless a deal/returns layer is asked for.
    if data.get("mode") == "operating" or ("deal" not in data and data.get("mode") != "deal"):
        return _finalize(build_operating(data))
    wb = Workbook()
    ws = wb.active
    ws.title = f"{data['company']} - Model X Math"[:31]

    axis = PeriodAxis(data["start_year"], data["n_hist"], data.get("n_forecast", 0))
    S = ModelSheet(ws, axis, data["company"], data.get("units", "(in $m)"))

    enabled = set(data.get("blocks", [name for name, _ in BLOCK_ORDER]))
    for fn_name, cfg_key in BLOCK_ORDER:
        if fn_name not in enabled:
            continue
        getattr(blocks, fn_name)(S, data.get(cfg_key, {}) if cfg_key else {})

    S.render()
    return _finalize(wb)


def _resolve_currency(cur: dict | None, n: int) -> dict | None:
    """Normalise a `currency` block into `{source, reporting, unit, rates(len n)}`, or
    None when no live conversion is needed (absent, or reporting == source)."""
    if not cur:
        return None
    source = cur.get("source", "")
    reporting = cur.get("reporting")
    if not reporting or reporting == source:
        return None
    rates = cur.get("rates")
    if not rates:
        rate = cur.get("rate")
        if rate is None:
            raise ValueError("currency block needs 'rate' or 'rates'")
        rates = [rate] * n
    rates = list(rates)[:n] + [rates[-1]] * max(0, n - len(rates))  # fit to axis length
    return {"source": source, "reporting": reporting, "unit": cur.get("unit", "m"), "rates": rates}


# Historical-actual arrays per block — the ones that must line up with n_hist (driver/forecast
# arrays like *_mgmt / revenue_growth / ebitda_margin are length n_forecast and are left alone).
_HIST_KEYS = {
    "pnl": ("revenue", "ebitda", "da", "interest", "tax"),
    "cf": ("nwc", "cash_eop"),
    "capex": ("total",),
    "debt": ("debt",),
}


def _normalize_hist(blocks_: dict, n_hist: int) -> None:
    """Truncate over-long historical arrays to n_hist (so they can't spill into forecast columns)
    and warn on any length mismatch. Mutates the block dicts in place."""
    for block, keys in _HIST_KEYS.items():
        d = blocks_.get(block) or {}
        for k in keys:
            arr = d.get(k)
            if not isinstance(arr, list) or len(arr) == n_hist:
                continue
            print(
                f"[mxm] warning: {block}.{k} has {len(arr)} values but n_hist={n_hist} "
                f"({'truncated' if len(arr) > n_hist else 'short — trailing years blank'})",
                file=sys.stderr,
            )
            if len(arr) > n_hist:
                d[k] = arr[:n_hist]


def build_operating(data: dict) -> Workbook:
    """Canonical operating model — actuals, optionally projected. Two sheets: an editable
    `Assumptions` tab (rationale comments) feeding the model. `n_forecast > 0` projects the
    future from management-case values (sourced) and/or our-case drivers, toggled by a
    Scenario selector when `scenarios` lists both. No returns/valuation layer."""
    units = data.get("units", "(in $m)")
    pnl = data.get("pnl", {})
    cf = data.get("cf", {})
    capex_cfg = data.get("capex", {})
    debt = data.get("debt", {})
    n_hist = data["n_hist"]
    scenarios = data.get("scenarios") or []

    # Robustness: a ragged source (an actual array not exactly n_hist long) must not silently
    # misalign or overflow into the forecast columns. Truncate over-long historical arrays and warn;
    # short arrays are safe (trailing years render blank, ratios are IFERROR-guarded).
    _normalize_hist({"pnl": pnl, "cf": cf, "capex": capex_cfg, "debt": debt}, n_hist)

    # A forecast always spans at least operating.MIN_FORECAST years: management arrays that stop
    # short are extrapolated with editable driver cells (never skip years). n_forecast=0 (and no
    # forecast inputs) stays an actuals-only model.
    def _len(d, *keys):
        return max([len(d.get(k) or []) for k in keys] + [0])

    disclosed = max(
        _len(pnl, "revenue_mgmt", "ebitda_mgmt", "da_mgmt"),
        _len(pnl, "revenue_growth", "ebitda_margin", "da_pct"),
        _len(cf, "nwc_mgmt", "cash_mgmt"),
        _len(capex_cfg, "total_mgmt"),
        _len(debt, "debt_mgmt"),
        data.get("n_forecast", 0),
    )
    n_forecast = max(disclosed, operating.MIN_FORECAST) if disclosed > 0 else 0

    wb = Workbook()
    mws = wb.active
    mws.title = f"{data['company']} - Model X Math"[:31]

    axis = PeriodAxis(data["start_year"], n_hist, n_forecast)

    # Currency conversion as an in-Excel toggle: the model is shown in its SOURCE currency by
    # default (the original numbers), and a toggle cell flips the whole sheet to the reporting
    # currency at each year's editable rate. Source data always stays entered natively.
    cur = _resolve_currency(data.get("currency"), axis.n)
    S = ModelSheet(mws, axis, data["company"], units)
    if cur:
        operating.currency_block(S, cur)  # reserve the toggle + FX row at the top…
        S.set_fx("fx_rate", "fx_curr")  # …then wrap every money input in the toggle
        curr_row = S.rref("fx_curr")
        src_label = data.get("units") or f"(in {cur['source']} {cur['unit']})"
        rep_label = f"(in {cur['reporting']} {cur['unit']})"
        S.units = f'=IF($G${curr_row}=1,"{src_label}","{rep_label}")'  # header label follows the toggle
    if len(scenarios) >= 2:  # both cases → an in-page CHOOSE toggle
        S.scenario_cell(scenarios, default=data.get("scenario_default", 1))

    # Assumptions block — rendered INLINE at the top of the model sheet (same page as the P&L etc.,
    # not a separate tab): editable yellow cells with rationale comments, referenced same-sheet as
    # $G$<row>, so editing a driver on the page re-drives the whole model.
    A = Assumptions(S)
    A.build(
        operating.needed_keys(pnl, cf, capex_cfg, debt, n_forecast, valuation=bool(data.get("deal"))),
        data.get("assumptions", {}),
    )

    # Provenance for sourced historical inputs (visible, editable notes) — only when the spec cites sources.
    if data.get("sources"):
        operating.data_sources(S, data["sources"])

    # Valuation (returns) layer — appended to the model sheet when a `deal` block is present,
    # in the gold-standard order. In valuation mode the balance sheet is MODELLED forward (cash
    # rolls, debt amortises via repay_pct) so dividends and paydown drive Net Debt into Returns.
    deal = data.get("deal")
    if deal and deal.get("spv_stake") is None and deal.get("rollover_pct") is not None:
        deal = {**deal, "spv_stake": 1.0 - deal["rollover_pct"]}  # sponsor keeps the non-rolled equity
    if deal:
        # Entry Balances at deal close — editable cells that seed the FIRST forecast year (Cash BoP,
        # Term Debt BoP). Default to the LATEST reported actuals ("use latest entry values"); fall back to a
        # documented placeholder when the source is silent. All-equity: no NWC / PP&E / min-cash / revolver.
        rev0 = (pnl.get("revenue") or [0.0])[0]
        ebd0 = (pnl.get("ebitda") or [0.0])[0]
        opb = data.get("opening", {})
        cash_hist = cf.get("cash_eop") or []
        debt_hist = debt.get("debt") or []
        ob_cash = opb.get("cash", cash_hist[-1] if cash_hist else round(0.05 * rev0, 1))
        odebt = opb.get("debt")
        if odebt is None:
            odebt = debt_hist[-1] if debt_hist else deal.get("entry_net_debt")
        if odebt is None and deal.get("entry_leverage") is not None:
            odebt = deal["entry_leverage"] * ebd0
        ob = {"cash": round(ob_cash or 0.0, 1), "debt": round(odebt or 0.0, 1)}
        operating.opening_block(S, ob)
        valuation.transaction_assumptions(S, deal)
        valuation.sources_uses(S, deal)

    operating.income_statement(S, pnl, A, valuation=bool(deal))
    operating.cash_flow(S, cf, A, valuation=bool(deal), deal=deal)
    operating.capex(S, capex_cfg, A, valuation=bool(deal))
    operating.debt_schedule(S, debt, A, valuation=bool(deal))
    blocks.net_debt(S, {}, valuation=bool(deal))  # Net Debt BEFORE Dividends (all-equity presentation)
    if deal:
        valuation.dividends(S, deal)
        valuation.returns(S, deal)
        valuation.key_ratios(S, deal)
    else:
        operating.fcf_summary(S, A)
    S.render()
    if deal:  # DCF on its own tab (LBO removed — all deals are all-equity)
        dcf.build_dcf(wb, S, data)
    return wb


def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: python -m mxm.build <deal.json> <out.xlsx>")
        sys.exit(1)
    with open(sys.argv[1]) as f:
        data = json.load(f)
    wb = build(data)
    wb.save(sys.argv[2])
    print(f"wrote {sys.argv[2]}")


if __name__ == "__main__":
    main()
