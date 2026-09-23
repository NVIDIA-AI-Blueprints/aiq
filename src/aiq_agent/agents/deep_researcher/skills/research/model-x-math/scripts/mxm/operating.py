"""
Canonical operating model — actuals, optionally projected into the future.

Emits the SAME fixed indicator set (P&L → Cash Flow → Capex → Debt → Net Debt → FCF)
whether actuals-only or projected. Every line is a **sourced actual** (blue input), an
**assumption-driven formula**, or — with a forecast — a **scenario choice** between them.

Forecast columns (`n_forecast > 0`, always **≥ MIN_FORECAST years**) come from:
  * **Management case** — the company's own projected values, sourced blue (`*_mgmt` arrays)
    for the years it discloses; **beyond that horizon the model extrapolates with editable
    per-period driver cells** (growth %, margins), so it never skips years and every tail
    year is a live formula the user can re-drive.
  * **Our case** — assumption/driver-driven from the start.
  * **Both** — `=CHOOSE($G$scenario, <mgmt>, <our>)`, switched by the Scenario selector.

No returns / valuation / dividends layer here — that is a separate, later addition.
"""

from __future__ import annotations

from . import style
from .assumptions import Assumptions
from .sheet import ModelSheet

MIN_FORECAST = 5  # a forecast always spans at least this many years (extrapolated if needed)


def needed_keys(pnl: dict, cf: dict, capex: dict, debt: dict, nf: int, valuation: bool = False) -> list[str]:
    # Valuation (teaser) mode: the scalar rate drivers live as single editable cells in the top Assumptions
    # block (the SINGLE source of truth). Each per-line "reported %" row LINKS to its cell (=$G$xx) and each
    # line item references the % row below it — chain: line → reported % row → assumption. NWC is the one
    # exception (the line references the top cell directly).
    if valuation:
        keys = ["maint_split", "nwc_pct", "tax_rate", "interest_rate", "capex_pct", "repay_pct"]
        if not pnl.get("ebitda"):
            keys.append("ebitda_margin")
        if not pnl.get("da"):
            keys.append("da_capex_pct" if pnl.get("da_basis") == "capex" else "da_pct")
        return keys
    keys = ["maint_split"]
    covers = lambda m: bool(m) and len(m) >= nf  # does this management array span the WHOLE forecast?
    # EBITDA / D&A assumptions are needed whenever the metric is absent — projected OR actuals-only.
    # (Registering only when nf==0 crashed any forecast built from a source without D&A/EBITDA.)
    if not pnl.get("ebitda"):
        keys.append("ebitda_margin")
    if not pnl.get("da"):
        keys.append("da_capex_pct" if pnl.get("da_basis") == "capex" else "da_pct")
    if not pnl.get("tax"):
        keys.append("tax_rate")
    if not pnl.get("interest"):
        keys.append("interest_rate")
    # ΔNWC / capex fall back to the % assumption for any year not sourced (history or the tail)
    if not cf.get("nwc") or (nf > 0 and not covers(cf.get("nwc_mgmt"))):
        keys.append("nwc_pct")
    if not capex.get("total") or (nf > 0 and not covers(capex.get("total_mgmt"))):
        keys.append("capex_pct")
    if nf > 0:
        keys.append("repay_pct")  # forecast debt tail rolls on the repayment assumption
    return keys


def _neg(xs):
    return [-abs(x) for x in xs]


def _is_scen(S: ModelSheet) -> bool:
    return "scenario" in S.rows


def _fit(arr, n):
    """List of length n: truncate, or pad by repeating the last value."""
    if not arr:
        return None
    a = list(arr)
    return (a + [a[-1]] * n)[:n]


def _term_growth(arr, prev):
    # Build-time default for a driver cell. Guard every denominator: a 0/blank prior year (a loss
    # year, a gap) must fall back to a sane default, never crash the build.
    if arr and len(arr) >= 2 and arr[-2]:
        return arr[-1] / arr[-2] - 1
    if arr and prev:
        return arr[0] / prev - 1
    return 0.08


def _term_ratio(num, den, hist_num, hist_den):
    if num and den and den[-1]:
        return abs(num[-1]) / den[-1]
    if hist_num and hist_den and hist_den[-1]:
        return abs(hist_num[-1]) / hist_den[-1]
    return 0.0


# ---------------------------------------------------------------------------
def currency_block(S: ModelSheet, cfg: dict) -> None:
    """A top-of-sheet currency section: a **display toggle** + an editable per-period FX row.
    The model is entered/shown in the SOURCE currency by default (toggle = 1); flip the toggle
    to 2 to convert everything to the reporting currency at each year's rate. `set_fx("fx_rate",
    "fx_curr")` then writes every money input as `=<native>/CHOOSE($G$curr, 1, <FX cell>)`."""
    src, rep = cfg.get("source", ""), cfg.get("reporting", "")
    S.section("Currency", years=True)
    S.spacer()
    # currency=False: the toggle and the FX rate are NOT money — they must never be FX-converted
    # themselves (converting the toggle cell would make it reference itself → circular).
    S.line("fx_curr", label=f"Display currency (1 = {src}, 2 = {rep})", g=1.0, g_fmt="0", currency=False)
    S.line(
        "fx_rate",
        label=f"FX rate ({src} per {rep})",
        values=list(cfg["rates"]),
        fmt=style.FX_RATE,
        italic=True,
        currency=False,
    )
    S.spacer(2)


# ---------------------------------------------------------------------------
def _topline_single(S, name, label, ratio_label, hist, mgmt, drv, our_fn, derived_fn, *, bold=True, fmt=style.NUM1):
    """One value line + its %-row (no scenario toggle).

    hist : sourced actuals (len n_hist)
    mgmt : sourced forecast values (len k ≤ n_forecast) or None  → management case for k years
    drv  : per-period driver values (len n_forecast) or None. `drv[j] is None` where year j is
           management-sourced; a number where year j is driver-projected (the extrapolation tail,
           or the whole forecast in the our case). Those numbers render as **editable blue cells**.
    """
    ax = S.axis
    nh, nf = ax.n_hist, ax.n_forecast
    k = len(mgmt) if mgmt else 0
    drvname = name + "_drv"
    mgmt_fc = [(mgmt[j] if (mgmt and j < k) else None) for j in range(nf)]  # sourced forecast, else gap

    S.line(
        name,
        label=label,
        bold=bold,
        fmt=fmt,
        values=list(hist) + mgmt_fc,
        fn=lambda s, i, c: None if i < nh else our_fn(s, i, c, drvname),
    )
    if drv is None:  # actuals only — plain derived %-row
        S.line(
            None,
            label=ratio_label,
            italic=True,
            fmt=style.PCT,
            currency=False,
            fn=lambda s, i, c: derived_fn(s, i, c) if i >= 1 else None,
        )
        return
    # driver row: management years derive (realised); projected years are editable blue inputs
    drv_vals = [None] * nh + [drv[j] for j in range(nf)]
    S.line(
        drvname,
        label=ratio_label,
        italic=True,
        fmt=style.PCT,
        currency=False,
        values=drv_vals,
        fn=lambda s, i, c: derived_fn(s, i, c) if i >= 1 else None,
    )


def _topline_toggle(
    S, name, label, ratio_label, hist, mgmt, our_drv, aux_growth, our_fn, derived_fn, *, bold=True, fmt=style.NUM1
):
    """Value line as an in-page CHOOSE between the management case (sourced + extrapolated) and
    the our case (driver-projected). Emits: main CHOOSE · realised %-row · our-driver row ·
    management aux row (sourced then extrapolated by its own editable growth)."""
    ax = S.axis
    nh, nf = ax.n_hist, ax.n_forecast
    k = len(mgmt) if mgmt else 0
    scen = S.rref("scenario")
    aux, ourd, auxg = name + "_mgmt", name + "_ourdrv", name + "_auxg"
    mgmt_fc = [(mgmt[j] if j < k else None) for j in range(nf)]

    S.line(
        name,
        label=label,
        bold=bold,
        fmt=fmt,
        values=list(hist) + [None] * nf,
        fn=lambda s, i, c: None if i < nh else f"CHOOSE($G${scen},{c}{s.rref(aux)},{our_fn(s, i, c, ourd)})",
    )
    S.line(
        None,
        label=ratio_label,
        italic=True,
        fmt=style.PCT,
        currency=False,
        fn=lambda s, i, c: derived_fn(s, i, c) if i >= 1 else None,
    )
    S.line(
        ourd,
        label=f"  ↳ {ratio_label} (Our)",
        italic=True,
        fmt=style.PCT,
        currency=False,
        values=[None] * nh + list(our_drv),
    )
    # management aux: sourced for k years, then extrapolated by its own growth (editable)
    S.line(
        aux,
        label=f"  ↳ {label} (Mgmt)",
        italic=True,
        fmt=fmt,
        values=[None] * nh + mgmt_fc,
        fn=lambda s, i, c: None if i < nh + k else f"{ax.col(i - 1)}{s.rref(aux)}*(1+{c}{s.rref(auxg)})",
    )
    if nf - k > 0:
        S.line(
            auxg,
            label=f"  ↳ {label} growth (Mgmt tail)",
            italic=True,
            fmt=style.PCT,
            currency=False,
            values=[None] * (nh + k) + list(aux_growth),
        )


# ---------------------------------------------------------------------------
def income_statement(S: ModelSheet, p: dict, A: Assumptions, valuation: bool = False) -> None:
    ax = S.axis
    nf = ax.n_forecast
    # The integrated model fills the levered P&L across ALL years (history included) off a full debt
    # schedule seeded at opening balances, so the statements tie and the balance sheet balances.
    int_cols = None
    rev, ebd, da = list(p["revenue"]), p.get("ebitda"), p.get("da")
    rev_m, ebd_m, da_m = p.get("revenue_mgmt"), p.get("ebitda_mgmt"), p.get("da_mgmt")
    toggle = _is_scen(S)

    def drv_for(mgmt, explicit, default, nh_last=None):
        """Driver array (len nf): None where management-sourced, else editable numbers.
        Tail = explicit override fitted to the gap, else the flat `default`."""
        if nf == 0:
            return None
        k = len(mgmt) if mgmt else 0
        if mgmt is None:  # our case — whole forecast is driver
            return _fit(explicit, nf) or [default] * nf
        tail = nf - k
        if tail <= 0:
            return [None] * k
        tvals = _fit(explicit, nf)
        tvals = tvals[k:] if tvals else [default] * tail
        return [None] * k + tvals

    S.section("Income Statement", years=True)
    S.spacer()

    rev_g_def = (
        _term_growth(rev_m, rev[-1]) if rev_m else (rev[-1] / rev[-2] - 1 if len(rev) >= 2 and rev[-2] else 0.08)
    )
    rev_drv = drv_for(rev_m, p.get("revenue_growth"), rev_g_def)
    rev_ourdrv = _fit(p.get("revenue_growth"), nf) or [rev_g_def] * nf
    rev_ourfn = lambda s, i, c, d: f"{ax.col(i - 1)}{s.rref('Revenue')}*(1+{c}{s.rref(d)})"
    rev_derived = lambda s, i, c: f"{c}{s.rref('Revenue')}/{ax.col(i - 1)}{s.rref('Revenue')}-1"
    if toggle and rev_m:
        _topline_toggle(
            S,
            "Revenue",
            "Revenue",
            "% Growth",
            rev,
            rev_m,
            rev_ourdrv,
            [rev_g_def] * max(0, nf - len(rev_m)),
            rev_ourfn,
            rev_derived,
        )
    else:
        _topline_single(S, "Revenue", "Revenue", "% Growth", rev, rev_m, rev_drv, rev_ourfn, rev_derived)
    S.spacer()

    if ebd:
        m_def = _term_ratio(ebd_m, rev_m, ebd, rev)
        ebd_drv = drv_for(ebd_m, p.get("ebitda_margin"), m_def)
        ebd_ourdrv = _fit(p.get("ebitda_margin"), nf) or [m_def] * nf
        ebd_ourfn = lambda s, i, c, d: f"{c}{s.rref('Revenue')}*{c}{s.rref(d)}"
        ebd_derived = lambda s, i, c: f"{c}{s.rref('EBITDA')}/{c}${s.rref('Revenue')}"
        if toggle and ebd_m:
            _topline_toggle(
                S,
                "EBITDA",
                "EBITDA",
                "% Margin",
                ebd,
                ebd_m,
                ebd_ourdrv,
                [_term_growth(ebd_m, ebd[-1])] * max(0, nf - len(ebd_m)),
                ebd_ourfn,
                ebd_derived,
            )
        else:
            _topline_single(S, "EBITDA", "EBITDA", "% Margin", ebd, ebd_m, ebd_drv, ebd_ourfn, ebd_derived)
    else:
        S.line("EBITDA", bold=True, fn=lambda s, i, c: f"{c}{s.rref('Revenue')}*{A.ref('ebitda_margin')}")
        S.margin("EBITDA")
    S.spacer()

    if da:
        d_def = _term_ratio(da, rev_m, da, rev)
        da_hist = _neg(da)
        da_mgmt = _neg(da_m) if da_m else None
        da_drv = drv_for(da_mgmt, p.get("da_pct"), d_def)
        da_ourdrv = _fit(p.get("da_pct"), nf) or [d_def] * nf
        da_ourfn = lambda s, i, c, dd: f"-{c}{s.rref(dd)}*{c}{s.rref('Revenue')}"
        da_derived = lambda s, i, c: f"-{c}{s.rref('DA')}/{c}${s.rref('Revenue')}"
        if toggle and da_mgmt:
            _topline_toggle(
                S,
                "DA",
                "D&A",
                "% of Revenues",
                da_hist,
                da_mgmt,
                da_ourdrv,
                [_term_growth(da_mgmt, da_hist[-1])] * max(0, nf - len(da_mgmt)),
                da_ourfn,
                da_derived,
            )
        else:
            _topline_single(S, "DA", "D&A", "% of Revenues", da_hist, da_mgmt, da_drv, da_ourfn, da_derived)
    elif valuation and p.get("da_basis") == "capex":
        # Valuation: D&A driven off a "% of capex" row shown directly below — which LINKS to the top
        # assumption cell (single source of truth). The line references the % row. Forecast only.
        fc = range(ax.first_forecast, ax.n)
        S.line("DA", label="D&A", cols=fc, fn=lambda s, i, c: f"{c}{s.rref('da_pct_capex')}*{c}{s.rref('capex_total')}")
        S.line(
            "da_pct_capex",
            label="D&A (% of capex)",
            italic=True,
            fmt=style.PCT,
            currency=False,
            cols=fc,
            fn=lambda s, i, c: A.ref("da_capex_pct"),
        )
    elif valuation:
        fc = range(ax.first_forecast, ax.n)
        S.line("DA", label="D&A", cols=fc, fn=lambda s, i, c: f"-{c}{s.rref('da_pct_rev')}*{c}{s.rref('Revenue')}")
        S.line(
            "da_pct_rev",
            label="D&A (% of Revenue)",
            italic=True,
            fmt=style.PCT,
            currency=False,
            cols=fc,
            fn=lambda s, i, c: A.ref("da_pct"),
        )
    elif p.get("da_basis") == "capex":
        # D&A as a % of total capex (analyst house method: depreciation trails the capex programme,
        # more faithful than %-of-revenue for a growth-investing asset base). capex_total is negative,
        # so a positive da_capex_pct yields a negative D&A. Resolves by name (capex block renders below).
        S.line("DA", label="D&A", fn=lambda s, i, c: f"{A.ref('da_capex_pct')}*{c}{s.rref('capex_total')}")
        S.sub(None, lambda s, i, c: f"-{c}{s.rref('DA')}/{c}${s.rref('Revenue')}", label="% of Revenues")
    else:
        S.line("DA", label="D&A", fn=lambda s, i, c: f"-{A.ref('da_pct')}*{c}{s.rref('Revenue')}")
        S.sub(None, lambda s, i, c: f"-{c}{s.rref('DA')}/{c}${s.rref('Revenue')}", label="% of Revenues")
    S.spacer()

    S.line("EBIT", total=True, bold=True, fn=lambda s, i, c: f"{c}{s.rref('EBITDA')}+{c}{s.rref('DA')}")
    S.margin("EBIT")
    S.spacer()

    fcols = range(ax.first_forecast, ax.n)
    if p.get("interest"):
        S.line("Interest", label="Interest expense", values=_neg(p["interest"]))
    elif valuation:
        # Interest is CALCULATED in the Debt Schedule (on the average term-debt balance, at the editable
        # Cost-of-debt % shown there) and LINKED up here — forecast only (no inferred historical interest).
        S.line("Interest", label="Interest expense", cols=fcols, fn=lambda s, i, c: f"{c}{s.rref('dbt_int')}")
    else:
        # Operating mode: interest on the AVERAGE term-debt balance at the assumption rate.
        S.line(
            "Interest",
            label="Interest expense",
            cols=int_cols,
            fn=lambda s, i, c: f"-{A.ref('interest_rate')}*AVERAGE({c}{s.rref('debt_bop')},{c}{s.rref('debt_eop')})",
        )
    S.spacer()
    S.line(
        "EBT",
        total=True,
        bold=True,
        cols=(fcols if valuation else None),
        fn=lambda s, i, c: f"{c}{s.rref('EBIT')}+{c}{s.rref('Interest')}",
    )
    S.margin("EBT", cols=(fcols if valuation else None))
    S.spacer()

    if p.get("tax"):
        S.line("Tax", label="Tax expense", values=_neg(p["tax"]))
        S.line(
            "tax_rate_pct",
            label="Tax Rate %",
            italic=True,
            fmt=style.PCT,
            fn=lambda s, i, c: f"-{c}{s.rref('Tax')}/{c}{s.rref('EBT')}",
        )
    elif valuation:
        # Tax references the reported "Tax Rate %" row directly BELOW it, which in turn LINKS to the single
        # editable "Tax rate" assumption cell at the top (=$G$xx). Forecast only — no inferred historical tax.
        S.line(
            "Tax",
            label="Tax expense",
            cols=fcols,
            fn=lambda s, i, c: f"-{c}{s.rref('tax_rate_pct')}*{c}{s.rref('EBT')}",
        )
        S.line(
            "tax_rate_pct",
            label="Tax Rate %",
            italic=True,
            fmt=style.PCT,
            currency=False,
            cols=fcols,
            fn=lambda s, i, c: A.ref("tax_rate"),
        )
    else:
        S.line("Tax", label="Tax expense", fn=lambda s, i, c: f"-{A.ref('tax_rate')}*{c}{s.rref('EBT')}")
        S.line(
            "tax_rate_pct", label="Tax Rate %", italic=True, fmt=style.PCT, fn=lambda s, i, c: f"{A.ref('tax_rate')}"
        )
    S.spacer()
    S.line(
        "NetProfit",
        label="Net Profit",
        total=True,
        bold=True,
        cols=(fcols if valuation else None),
        fn=lambda s, i, c: f"{c}{s.rref('EBT')}+{c}{s.rref('Tax')}",
    )
    S.margin("NetProfit", cols=(fcols if valuation else None))
    S.spacer(2)


# ---------------------------------------------------------------------------
def cash_flow(S: ModelSheet, cf: dict, A: Assumptions, valuation: bool = False, deal: dict | None = None) -> None:
    ax = S.axis
    nh, nf = ax.n_hist, ax.n_forecast
    ff = ax.first_forecast
    fcols = range(ff, ax.n)
    S.section("Cash Flow Statement", years=True)
    S.spacer()
    # ΔNWC is nwc_pct × the CHANGE in revenue (working capital only grows when the business grows) — NOT
    # % of the whole revenue level (which overstates the outflow ~30× and drains cash). NWC is the ONE
    # driver kept on the top Assumptions cell (`A.ref('nwc_pct')`); every other rate is a per-line % row.
    # First forecast year references the last ACTUAL revenue (real P&L), so ΔNWC is a live step from entry.
    dnwc = lambda s, i, c: f"-{A.ref('nwc_pct')}*({c}{s.rref('Revenue')}-{ax.col(i - 1)}{s.rref('Revenue')})"
    if valuation:
        # Forecast-only cash flow — no inferred history. The levered cash flow is projected from the
        # entry balances; history carries only P&L + Capex, so the statement starts at the first forecast.
        S.line("cf_ebitda", label="EBITDA", cols=fcols, fn=lambda s, i, c: f"{c}{s.rref('EBITDA')}")
        S.line("cf_tax", label="(-) Tax", cols=fcols, fn=lambda s, i, c: f"{c}{s.rref('Tax')}")
        S.line("cf_nwc", label="(-) Change in Net Working Capital", cols=fcols, fn=dnwc)
        S.line(
            "CFO",
            label="Cash Flow from Operations",
            total=True,
            bold=True,
            cols=fcols,
            fn=lambda s, i, c: f"SUM({c}{s.rref('cf_ebitda')}:{c}{s.rref('cf_nwc')})",
        )
        S.sub(
            None,
            lambda s, i, c: f"-{c}{s.rref('cf_nwc')}/{c}{s.rref('Revenue')}",
            label="Change in NWC as % Rev",
            cols=fcols,
        )
        S.spacer()
        S.line("cf_maint", label="(-) Maintenance Capex", cols=fcols, fn=lambda s, i, c: f"{c}{s.rref('capex_maint')}")
        S.line("cf_growth", label="(-) Growth Capex", cols=fcols, fn=lambda s, i, c: f"{c}{s.rref('capex_growth')}")
        S.line(
            "CFI",
            label="Cash flow from Investing",
            total=True,
            bold=True,
            cols=fcols,
            fn=lambda s, i, c: f"SUM({c}{s.rref('cf_maint')}:{c}{s.rref('cf_growth')})",
        )
        S.spacer()
        S.line("cf_int", label="(-) Interest Expense", cols=fcols, fn=lambda s, i, c: f"{c}{s.rref('Interest')}")
        if deal and deal.get("primary_injection"):
            S.line(
                "cf_inject", label="(+) Equity Injection", cols=[ff], fn=lambda s, i, c: f"{deal['primary_injection']}"
            )
        S.line("cf_debt", label="(-) Term Debt Repayment", cols=fcols, fn=lambda s, i, c: f"{c}{s.rref('debt_repay')}")
        S.line("cf_div", label="(-) Dividends", cols=fcols, fn=lambda s, i, c: f"-{c}{s.rref('div_total')}")
        S.line(
            "CFF",
            label="Cash flow from Financing",
            total=True,
            bold=True,
            cols=fcols,
            fn=lambda s, i, c: f"SUM({c}{s.rref('cf_int')}:{c}{s.rref('cf_div')})",
        )
        S.spacer()
        # All-equity cash roll (no revolver): Cash EoP = Cash BoP + CFO + CFI + CFF. Cash BoP seeds the
        # editable Entry Cash cell at the FIRST forecast year, then rolls prior EoP.
        S.line(
            "cash_bop",
            label="Cash BoP",
            cols=fcols,
            fn=lambda s, i, c: f"$G${s.rref('ob_cash')}" if i == ff else f"{ax.col(i - 1)}{s.rref('cash_eop')}",
        )
        S.line(
            "cash_chg",
            label="(+/-) Change in Cash",
            cols=fcols,
            fn=lambda s, i, c: f"{c}{s.rref('CFO')}+{c}{s.rref('CFI')}+{c}{s.rref('CFF')}",
        )
        S.line(
            "cash_eop",
            label="Cash EoP",
            total=True,
            bold=True,
            cols=fcols,
            fn=lambda s, i, c: f"{c}{s.rref('cash_bop')}+{c}{s.rref('cash_chg')}",
        )
        # Pre-dividend cash available — EXCLUDES Cash BoP (and dividends): the year's own cash generation
        # only. `= CFO + CFI + Interest + Term-debt repayment`. Kept acyclic.
        S.line(
            "div_avail",
            label="Cash flow available for dividends",
            cols=fcols,
            fn=lambda s, i, c: f"{c}{s.rref('CFO')}+{c}{s.rref('CFI')}+{c}{s.rref('cf_int')}+{c}{s.rref('cf_debt')}",
        )
        S.spacer(2)
        return
    # operating (no deal) — no revolver; cash rolls from opening_cash
    S.line("cf_ebitda", label="EBITDA", fn=lambda s, i, c: f"{c}{s.rref('EBITDA')}")
    S.line("cf_tax", label="(-) Tax", fn=lambda s, i, c: f"{c}{s.rref('Tax')}")
    nwc_hist = _neg(cf["nwc"]) if cf.get("nwc") else [None] * nh
    nwc_fc = _neg(cf["nwc_mgmt"]) if cf.get("nwc_mgmt") else []
    dnwc_op = lambda s, i, c: (
        "0" if i == 0 else f"-{A.ref('nwc_pct')}*({c}{s.rref('Revenue')}-{ax.col(i - 1)}{s.rref('Revenue')})"
    )
    S.line("cf_nwc", label="(-) Change in Net Working Capital", values=nwc_hist + nwc_fc, fn=dnwc_op)
    S.line(
        "CFO",
        label="Cash Flow from Operations",
        total=True,
        bold=True,
        fn=lambda s, i, c: f"SUM({c}{s.rref('cf_ebitda')}:{c}{s.rref('cf_nwc')})",
    )
    S.sub(None, lambda s, i, c: f"-{c}{s.rref('cf_nwc')}/{c}{s.rref('Revenue')}", label="Change in NWC as % Rev")
    S.spacer()
    S.line("cf_maint", label="(-) Maintenance Capex", fn=lambda s, i, c: f"{c}{s.rref('capex_maint')}")
    S.line("cf_growth", label="(-) Growth Capex", fn=lambda s, i, c: f"{c}{s.rref('capex_growth')}")
    S.line(
        "CFI",
        label="Cash flow from Investing",
        total=True,
        bold=True,
        fn=lambda s, i, c: f"SUM({c}{s.rref('cf_maint')}:{c}{s.rref('cf_growth')})",
    )
    S.spacer()
    S.line("cf_int", label="(-) Interest Expense", fn=lambda s, i, c: f"{c}{s.rref('Interest')}")
    S.line("cf_debt", label="(-) Term Debt Repayment", fn=lambda s, i, c: f"{c}{s.rref('debt_repay')}")
    S.line(
        "CFF_core",
        label="Cash flow from Financing (pre-revolver)",
        total=True,
        bold=True,
        fn=lambda s, i, c: f"SUM({c}{s.rref('cf_int')}:{c}{s.rref('cf_debt')})",
    )
    S.spacer()
    S.line(
        "CFF", label="Cash flow from Financing", total=True, bold=True, fn=lambda s, i, c: f"{c}{s.rref('CFF_core')}"
    )
    S.line("cash_bop", label="Cash BoP", cols=range(1, ax.n), fn=lambda s, i, c: f"{ax.col(i - 1)}{s.rref('cash_eop')}")
    S.line(
        "cash_chg",
        label="(+/-) Change in Cash",
        fn=lambda s, i, c: f"{c}{s.rref('CFO')}+{c}{s.rref('CFI')}+{c}{s.rref('CFF')}",
    )
    cash_hist = list(cf["cash_eop"]) if cf.get("cash_eop") else [cf.get("opening_cash", 0.0)] + [None] * (nh - 1)
    cash_fc = list(cf["cash_mgmt"]) if cf.get("cash_mgmt") else []
    S.line(
        "cash_eop",
        label="Cash EoP",
        total=True,
        bold=True,
        values=cash_hist + cash_fc,
        fn=lambda s, i, c: f"{c}{s.rref('cash_bop')}+{c}{s.rref('cash_chg')}",
    )
    S.spacer(2)


# ---------------------------------------------------------------------------
def capex(S: ModelSheet, cap: dict, A: Assumptions, valuation: bool = False) -> None:
    ax = S.axis
    nh, nf = ax.n_hist, ax.n_forecast
    S.section("Capex", years=True)
    S.spacer()
    S.line(
        "capex_maint",
        label="Maintenance Capex",
        fn=lambda s, i, c: f"{A.ref('maint_split')}*{c}{s.rref('capex_total')}",
    )
    S.line(
        "capex_growth",
        label="Growth Capex",
        fn=lambda s, i, c: f"(1-{A.ref('maint_split')})*{c}{s.rref('capex_total')}",
    )
    if valuation:
        ff = ax.first_forecast
        # Historical capex = sourced blue actuals (hardcoded, like the P&L); forecast = the "Capex as % of
        # Revenue" row directly below × Revenue. That % row shows the ACTUAL intensity in history (derived)
        # and LINKS to the single "Capex (% revenue)" assumption cell in the forecast (=$G$xx).
        # Sourced management capex (total_mgmt) wins as blue inputs for the years it covers; the %
        # assumption drives only the remaining tail years (its % row stays derived under mgmt years).
        total_hist = _neg(cap["total"]) if cap.get("total") else [None] * nh
        mgmt = _neg(cap["total_mgmt"]) if cap.get("total_mgmt") else []
        n_m = min(len(mgmt), nf)
        S.line(
            "capex_total",
            label="Total Capex",
            total=True,
            bold=True,
            values=total_hist + mgmt[:n_m] + [None] * (nf - n_m),
            fn=lambda s, i, c: None if i < ff + n_m else f"-{c}{s.rref('capex_pct_rev')}*{c}{s.rref('Revenue')}",
        )
        S.line(
            "capex_pct_rev",
            label="Capex as % of Revenue",
            italic=True,
            fmt=style.PCT,
            currency=False,
            fn=lambda s, i, c: (
                f"-{c}{s.rref('capex_total')}/{c}{s.rref('Revenue')}" if i < ff + n_m else A.ref("capex_pct")
            ),
        )
    else:
        total_hist = _neg(cap["total"]) if cap.get("total") else [None] * nh
        total_fc = _neg(cap["total_mgmt"]) if cap.get("total_mgmt") else []
        S.line(
            "capex_total",
            label="Total Capex",
            total=True,
            bold=True,
            values=total_hist + total_fc,
            fn=lambda s, i, c: f"-{A.ref('capex_pct')}*{c}{s.rref('Revenue')}",
        )
        S.line(
            "capex_pct_rev",
            label="Capex as % of Revenue",
            italic=True,
            fmt=style.PCT,
            fn=lambda s, i, c: f"-{c}{s.rref('capex_total')}/{c}{s.rref('Revenue')}",
        )
    S.spacer(2)


# ---------------------------------------------------------------------------
def debt_schedule(S: ModelSheet, debt: dict, A: Assumptions, valuation: bool = False) -> None:
    ax = S.axis
    nh, nf = ax.n_hist, ax.n_forecast
    ff, entry = ax.first_forecast, ax.last_hist
    S.section("Debt Schedule", years=True)
    S.spacer()
    if valuation:
        # All-equity term-debt schedule (no revolver, no balance-sheet plug). Term debt is seeded at the
        # editable Entry Term Debt cell at the FIRST forecast year and amortises on the editable "Repayment %"
        # row directly below. Forecast only — no inferred historical debt. Interest is CALCULATED here (on
        # the average balance, at the editable Cost-of-debt %) and linked up into the P&L Interest line.
        ff = ax.first_forecast
        fcols = range(ff, ax.n)
        S.line(
            "debt_bop",
            label="Term Debt BoP",
            cols=fcols,
            fn=lambda s, i, c: f"$G${s.rref('ob_debt')}" if i == ff else f"{ax.col(i - 1)}{s.rref('debt_eop')}",
        )
        S.line(
            "debt_repay",
            label="(-) Term Debt Repayment",
            cols=fcols,
            fn=lambda s, i, c: f"-{c}{s.rref('debt_repay_pct')}*{c}{s.rref('debt_bop')}",
        )
        S.line(
            "debt_repay_pct",
            label="Repayment % of opening debt",
            italic=True,
            fmt=style.PCT,
            currency=False,
            cols=fcols,
            fn=lambda s, i, c: A.ref("repay_pct"),
        )
        S.line(
            "debt_eop",
            label="Term Debt EoP",
            total=True,
            bold=True,
            cols=fcols,
            fn=lambda s, i, c: f"{c}{s.rref('debt_bop')}+{c}{s.rref('debt_repay')}",
        )
        S.spacer()
        S.line(
            "dbt_int",
            label="Interest Expense",
            cols=fcols,
            fn=lambda s, i, c: (
                f"-{c}{s.rref('cost_debt_pct')}*AVERAGE({c}{s.rref('debt_bop')},{c}{s.rref('debt_eop')})"
            ),
        )
        S.line(
            "cost_debt_pct",
            label="Cost of debt %",
            italic=True,
            fmt=style.PCT,
            currency=False,
            cols=fcols,
            fn=lambda s, i, c: A.ref("interest_rate"),
        )
        S.spacer()
        S.line(
            "dbt_gde",
            label="Gross Debt / EBITDA",
            italic=True,
            fmt=style.MULT,
            cols=fcols,
            fn=lambda s, i, c: f"{c}{s.rref('debt_eop')}/{c}{s.rref('EBITDA')}",
        )
        S.spacer(2)
        return
    S.line("debt_bop", label="Debt BoP", cols=range(1, ax.n), fn=lambda s, i, c: f"{ax.col(i - 1)}{s.rref('debt_eop')}")
    debt_hist = list(debt["debt"]) if debt.get("debt") else [0.0] * nh
    debt_mgmt = list(debt["debt_mgmt"]) if debt.get("debt_mgmt") else []
    ksrc = nh + len(debt_mgmt)  # last column index (exclusive) that is a sourced EoP balance
    # sourced-EoP years show the observed movement; projected tail rolls on the repayment assumption
    S.line(
        "debt_repay",
        label="(-) Debt Repayment",
        cols=range(1, ax.n),
        fn=lambda s, i, c: (
            f"-{A.ref('repay_pct')}*{c}{s.rref('debt_bop')}"
            if i >= ksrc
            else f"{c}{s.rref('debt_eop')}-{c}{s.rref('debt_bop')}"
        ),
    )
    S.line(
        "debt_eop",
        label="Debt EoP",
        total=True,
        bold=True,
        values=debt_hist + debt_mgmt,
        fn=lambda s, i, c: f"{c}{s.rref('debt_bop')}+{c}{s.rref('debt_repay')}" if i >= ksrc else None,
    )
    S.spacer()
    S.line("dbt_int", label="Interest Expense", fn=lambda s, i, c: f"{c}{s.rref('Interest')}")
    S.spacer()
    S.line(
        "nd_ebitda",
        label="Net Debt / EBITDA",
        italic=True,
        fmt=style.MULT,
        fn=lambda s, i, c: f"{c}{s.rref('nd_netdebt')}/{c}{s.rref('EBITDA')}",
    )
    S.spacer(2)


# ---------------------------------------------------------------------------
_SRC_LABELS = {
    "revenue": "Revenue",
    "ebitda": "EBITDA",
    "da": "D&A",
    "interest": "Interest",
    "tax": "Tax",
    "nwc": "Change in NWC",
    "cash": "Cash",
    "capex": "Total Capex",
    "debt": "Debt",
    "opening": "Opening balance sheet",
}


def data_sources(S: ModelSheet, sources: dict) -> None:
    """Provenance for the sourced historical inputs — a visible, editable note per metric stating WHERE
    the number came from (page/section of the CIM/teaser). Driven by the spec's `sources` dict
    {metric: "citation"}; omit it to skip the section."""
    S.section("Data Sources & Provenance")
    S.spacer()
    for key, cite in sources.items():
        label = _SRC_LABELS.get(key, key)
        # metric in the label column, the citation as an editable italic note beside it (col G onward).
        S.line(
            f"src_{key}",
            label=label,
            values=[str(cite)] + [None] * (S.axis.n - 1),
            italic=True,
            currency=False,
            fmt="@",
        )
    S.spacer(2)


# ---------------------------------------------------------------------------
def opening_block(S: ModelSheet, ob: dict) -> None:
    """Entry balances at deal close (editable yellow cells in col G) that seed the forecast. The first
    forecast year's Cash BoP and Term Debt BoP link to these cells. `ref` names: ob_cash, ob_debt."""
    S.section("Entry Balances (at Deal Close)")
    S.spacer()
    rows = [
        (
            "ob_cash",
            "Entry Cash (at close)",
            ob["cash"],
            "Cash at deal close (latest reported actual). The first forecast year's Cash BoP links here.",
        ),
        (
            "ob_debt",
            "Entry Term Debt (at close)",
            ob["debt"],
            "Interest-bearing term debt at deal close (latest reported actual). Seeds the debt schedule.",
        ),
    ]
    fx_col = S.axis.first_forecast if S.axis.n_forecast else 0  # entry balances are at deal close
    for name, label, val, why in rows:
        S.line(name, label=label, g=float(val), g_fmt=style.NUM1, g_fx_col=fx_col, comment="ASSUMED: " + why)
    S.spacer(2)


# ---------------------------------------------------------------------------
def fcf_summary(S: ModelSheet, A: Assumptions) -> None:
    S.section("Free Cash Flow", years=True)
    S.spacer()
    S.line("fcf_ebitda", label="EBITDA", fn=lambda s, i, c: f"{c}{s.rref('EBITDA')}")
    S.line("fcf_tax", label="(-) Tax", fn=lambda s, i, c: f"{c}{s.rref('Tax')}")
    S.line("fcf_nwc", label="(-) Change in NWC", fn=lambda s, i, c: f"{c}{s.rref('cf_nwc')}")
    S.line("fcf_capex", label="(-) Capex", fn=lambda s, i, c: f"{c}{s.rref('capex_total')}")
    S.line("fcf_int", label="(-) Interest", fn=lambda s, i, c: f"{c}{s.rref('Interest')}")
    S.line(
        "FCF",
        label="Free Cash Flow",
        total=True,
        bold=True,
        fn=lambda s, i, c: f"SUM({c}{s.rref('fcf_ebitda')}:{c}{s.rref('fcf_int')})",
    )
    S.sub(None, lambda s, i, c: f"{c}{s.rref('FCF')}/{c}{s.rref('EBITDA')}", label="FCF Conversion")
    S.spacer(2)
