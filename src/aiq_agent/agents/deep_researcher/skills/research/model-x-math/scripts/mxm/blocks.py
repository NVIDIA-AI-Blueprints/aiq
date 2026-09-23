"""
Block catalog for a Model X Math sheet.

Each block is a small function that reserves rows on a ModelSheet and wires the
formulas reverse-engineered from the house gold standard. Blocks are composable —
build.py runs the ones a given deal needs, in order. Cross-block references use
semantic names (S.rref / S.cref), so a block never hardcodes another block's row.

The model is INTERACTIVE: historical periods are blue inputs; forecast periods
are formulas driven by assumption rows (growth %, margins, rates), so changing
an assumption re-drives the whole sheet.
"""

from __future__ import annotations

from . import style
from .sheet import ModelSheet


def _pad(hist: list, n_forecast: int) -> list:
    return list(hist) + [None] * n_forecast


# ---------------------------------------------------------------------------
def income_statement(S: ModelSheet, cfg: dict) -> None:
    ax = S.axis
    ff = ax.first_forecast
    fc = range(ff, ax.n)  # forecast periods
    hc = range(0, ax.n_hist)  # historical periods
    p = cfg  # pnl config

    S.section("Income Statement", years=True)
    S.spacer()

    # Revenue: actuals, then prior × (1+growth)
    S.line(
        "Revenue",
        values=_pad(p["revenue"], ax.n_forecast),
        bold=True,
        fn=lambda s, i, c: f"{ax.col(i - 1)}{s.rref('Revenue')}*(1+{c}{s.rref('rev_growth')})",
    )
    S.line(
        "rev_growth",
        label="% Growth",
        italic=True,
        fmt=style.PCT,
        values=[None] * ax.n_hist + list(p.get("revenue_growth", [])),
        fn=lambda s, i, c: f"{c}{s.rref('Revenue')}/{ax.col(i - 1)}{s.rref('Revenue')}-1" if i >= 1 else None,
    )
    S.spacer()

    # EBITDA: actuals, then revenue × margin
    S.line(
        "EBITDA",
        values=_pad(p["ebitda"], ax.n_forecast),
        bold=True,
        fn=lambda s, i, c: f"{c}{s.rref('Revenue')}*{c}{s.rref('ebitda_margin')}",
    )
    S.line(
        "ebitda_margin",
        label="% Margin",
        italic=True,
        fmt=style.PCT,
        values=[None] * ax.n_hist + list(p.get("ebitda_margin", [])),
        fn=lambda s, i, c: f"{c}{s.rref('EBITDA')}/{c}${s.rref('Revenue')}",
    )
    S.spacer()

    # D&A (negative): actuals, then −(% of rev) × rev
    S.line(
        "DA",
        label="D&A",
        values=_pad([-abs(x) for x in p["da"]], ax.n_forecast),
        fn=lambda s, i, c: f"-{c}{s.rref('da_pct')}*{c}{s.rref('Revenue')}",
    )
    S.line(
        "da_pct",
        label="% of Revenues",
        italic=True,
        fmt=style.PCT,
        values=[None] * ax.n_hist + list(p.get("da_pct", [])),
        fn=lambda s, i, c: f"-{c}{s.rref('DA')}/{c}${s.rref('Revenue')}",
    )
    S.spacer()

    S.line("EBIT", total=True, bold=True, fn=lambda s, i, c: f"{c}{s.rref('EBITDA')}+{c}{s.rref('DA')}")
    S.margin("EBIT")
    S.spacer()

    # Interest: actual inputs if given (no-projection mode), else ← debt schedule.
    int_actual = p.get("interest")
    S.line(
        "Interest",
        label="Interest expense",
        values=_pad([-abs(x) for x in int_actual], ax.n_forecast) if int_actual else None,
        fn=lambda s, i, c: f"{c}{s.rref('int_sched')}",
    )
    S.spacer()
    S.line("EBT", total=True, bold=True, fn=lambda s, i, c: f"{c}{s.rref('EBIT')}+{c}{s.rref('Interest')}")
    S.margin("EBT")
    S.spacer()
    # Tax: actual inputs if given (effective rate shown), else −EBT × rate.
    tax_actual = p.get("tax")
    S.line(
        "Tax",
        label="Tax expense",
        g=(None if tax_actual else p.get("tax_rate")),
        g_fmt=style.PCT,
        values=_pad([-abs(x) for x in tax_actual], ax.n_forecast) if tax_actual else None,
        fn=lambda s, i, c: f"-{c}{s.rref('EBT')}*$G${s.rref('Tax')}",
    )
    S.line(
        "tax_rate_pct",
        label="Tax Rate %",
        italic=True,
        fmt=style.PCT,
        fn=(
            (lambda s, i, c: f"-{c}{s.rref('Tax')}/{c}{s.rref('EBT')}")
            if tax_actual
            else (lambda s, i, c: f"$G${s.rref('Tax')}")
        ),
    )
    S.spacer()
    S.line(
        "NetProfit",
        label="Net Profit",
        total=True,
        bold=True,
        fn=lambda s, i, c: f"{c}{s.rref('EBT')}+{c}{s.rref('Tax')}",
    )
    S.margin("NetProfit")
    S.spacer(2)


# ---------------------------------------------------------------------------
def cash_flow(S: ModelSheet, cfg: dict) -> None:
    ax = S.axis
    fc = range(ax.first_forecast, ax.n)
    p = cfg

    S.section("Cash Flow Statement", years=True)
    S.spacer()
    S.line("cf_ebitda", label="EBITDA", fn=lambda s, i, c: f"{c}{s.rref('EBITDA')}")
    S.line("cf_tax", label="(-) Tax", fn=lambda s, i, c: f"{c}{s.rref('Tax')}")
    # ΔNWC: actual inputs if given, else −nwc% × revenue in the forecast.
    nwc_actual = p.get("nwc")
    S.line(
        "cf_nwc",
        label="(-) Change in Net Working Capital",
        g=(None if nwc_actual else p.get("nwc_pct")),
        g_fmt=style.PCT,
        values=_pad([-abs(x) for x in nwc_actual], ax.n_forecast) if nwc_actual else None,
        fn=lambda s, i, c: f"-$G${s.rref('cf_nwc')}*{c}{s.rref('Revenue')}" if i >= ax.first_forecast else None,
    )
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
    has_fc = ax.n_forecast > 0
    S.line("cf_int", label="(-) Interest Expense", fn=lambda s, i, c: f"{c}{s.rref('Interest')}")
    S.line("cf_debt", label="(-) Debt Repayment", fn=lambda s, i, c: f"{c}{s.rref('debt_repay')}")
    cff_end = "cf_debt"
    if has_fc:  # dividends only exist alongside a projection
        S.line("cf_div", label="(-) Dividends", cols=fc, fn=lambda s, i, c: f"-{c}{s.rref('div_total')}")
        cff_end = "cf_div"
    S.line(
        "CFF",
        label="Cash flow from Financing",
        total=True,
        bold=True,
        fn=lambda s, i, c: f"SUM({c}{s.rref('cf_int')}:{c}{s.rref(cff_end)})",
    )
    S.spacer()
    # Cash roll
    S.line("cash_bop", label="Cash BoP", cols=range(1, ax.n), fn=lambda s, i, c: f"{ax.col(i - 1)}{s.rref('cash_eop')}")
    S.line(
        "cash_chg",
        label="(+/-) Change in Cash",
        fn=lambda s, i, c: f"{c}{s.rref('CFO')}+{c}{s.rref('CFI')}+{c}{s.rref('CFF')}",
    )
    S.line(
        "cash_eop",
        label="Cash EoP",
        total=True,
        bold=True,
        values=_pad(p["cash_eop_hist"], ax.n_forecast),
        fn=lambda s, i, c: f"{c}{s.rref('cash_bop')}+{c}{s.rref('cash_chg')}",
    )
    S.spacer()
    if has_fc:
        S.line(
            "div_avail",
            label="Cash flow available for dividends",
            cols=range(ax.first_forecast, ax.n),
            fn=lambda s, i, c: f"{c}{s.rref('CFO')}+{c}{s.rref('CFI')}+{c}{s.rref('cf_int')}+{c}{s.rref('cf_debt')}",
        )
    S.spacer(2)


# ---------------------------------------------------------------------------
def capex(S: ModelSheet, cfg: dict) -> None:
    ax = S.axis
    p = cfg
    # No-projection mode: actual total capex given → split it by maint_split as inputs.
    if p.get("total"):
        split = p.get("maint_split", 0.65)
        tot = [-abs(x) for x in p["total"]]
        S.section("Capex", years=True)
        S.spacer()
        S.line("capex_maint", label="Maintenance Capex", values=_pad([x * split for x in tot], ax.n_forecast))
        S.line("capex_growth", label="Growth Capex", values=_pad([x * (1 - split) for x in tot], ax.n_forecast))
        S.line(
            "capex_sum",
            label="Total Capex",
            total=True,
            bold=True,
            fn=lambda s, i, c: f"{c}{s.rref('capex_maint')}+{c}{s.rref('capex_growth')}",
        )
        S.spacer(2)
        return
    S.section("Capex", years=True)
    S.spacer()
    S.line(
        "capex_total",
        label="Total Capex (% Revenue)",
        g=p["capex_pct"],
        g_fmt=style.PCT,
        italic=True,
        fmt=style.PCT,
        fn=lambda s, i, c: f"$G${s.rref('capex_total')}",
    )
    S.line(
        "capex_maint",
        label="Maintenance Capex",
        g=p["maint_split"],
        g_fmt=style.PCT,
        fn=lambda s, i, c: f"-$G${s.rref('capex_maint')}*$G${s.rref('capex_total')}*{c}{s.rref('Revenue')}",
    )
    S.line(
        "capex_growth",
        label="Growth Capex",
        fn=lambda s, i, c: f"-(1-$G${s.rref('capex_maint')})*$G${s.rref('capex_total')}*{c}{s.rref('Revenue')}",
    )
    S.line(
        "capex_sum",
        label="Total Capex",
        total=True,
        bold=True,
        fn=lambda s, i, c: f"{c}{s.rref('capex_maint')}+{c}{s.rref('capex_growth')}",
    )
    S.spacer(2)


# ---------------------------------------------------------------------------
def debt_schedule(S: ModelSheet, cfg: dict) -> None:
    ax = S.axis
    ff = ax.first_forecast
    p = cfg
    S.section("Debt Schedule", years=True)
    S.spacer()
    has_fc = ax.n_forecast > 0
    S.line("debt_bop", label="Debt BoP", cols=range(1, ax.n), fn=lambda s, i, c: f"{ax.col(i - 1)}{s.rref('debt_eop')}")
    if has_fc:  # forecast: repayment drives EoP
        S.line(
            "debt_repay",
            label="(-) Debt Repayment",
            g=p.get("repay_pct"),
            g_fmt=style.PCT,
            cols=range(ff, ax.n),
            fn=lambda s, i, c: f"-$G${s.rref('debt_repay')}*{c}{s.rref('debt_bop')}",
        )
        S.line(
            "debt_eop",
            label="Debt EoP",
            total=True,
            bold=True,
            values=_pad(p["debt_hist"], ax.n_forecast),
            fn=lambda s, i, c: f"{c}{s.rref('debt_bop')}+{c}{s.rref('debt_repay')}",
        )
    else:  # actuals: EoP are inputs, repayment is the observed movement
        S.line(
            "debt_repay",
            label="(-) Debt Repayment",
            cols=range(1, ax.n),
            fn=lambda s, i, c: f"{c}{s.rref('debt_eop')}-{c}{s.rref('debt_bop')}",
        )
        S.line("debt_eop", label="Debt EoP", total=True, bold=True, values=list(p["debt_hist"]))
    S.spacer()
    S.line(
        "int_sched",
        label="Interest Expense",
        g=p["interest_rate"],
        g_fmt=style.PCT,
        fn=lambda s, i, c: (
            f"-$G${s.rref('int_sched')}*{c}{s.rref('debt_eop')}"
            if i == 0
            else f"-$G${s.rref('int_sched')}*{c}{s.rref('debt_bop')}"
        ),
    )
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
def net_debt(S: ModelSheet, cfg: dict, valuation: bool = False) -> None:
    # All-equity valuation: a single term-debt line (no revolver / total-debt line). Net Debt / EBITDA lives
    # HERE (moved out of the Debt Schedule). Forecast-only in valuation — no inferred historical net debt.
    ax = S.axis
    fcols = range(ax.first_forecast, ax.n) if valuation else None
    S.section("Net Debt", years=True)
    S.spacer()
    S.line("nd_cash", label="Cash", cols=fcols, fn=lambda s, i, c: f"{c}{s.rref('cash_eop')}")
    S.line("nd_debt", label="Debt", cols=fcols, fn=lambda s, i, c: f"{c}{s.rref('debt_eop')}")
    S.line(
        "nd_netdebt",
        label="Net Debt",
        total=True,
        bold=True,
        cols=fcols,
        fn=lambda s, i, c: f"{c}{s.rref('nd_debt')}-{c}{s.rref('nd_cash')}",
    )
    if valuation:
        S.line(
            "nd_ebitda",
            label="Net Debt / EBITDA",
            italic=True,
            fmt=style.MULT,
            cols=fcols,
            fn=lambda s, i, c: f"{c}{s.rref('nd_netdebt')}/{c}{s.rref('EBITDA')}",
        )
    S.spacer(2)


# ---------------------------------------------------------------------------
def dividends(S: ModelSheet, cfg: dict) -> None:
    ax = S.axis
    fc = range(ax.first_forecast, ax.n)
    p = cfg
    S.section("Dividends", years=True)
    S.spacer()
    S.line("div_payout", label="Dividend Payout", fmt=style.PCT, cols=fc, values=[None] * ax.n_hist + list(p["payout"]))
    S.line(
        "div_stake",
        label="SPV Stake",
        fmt=style.PCT,
        cols=fc,
        fn=lambda s, i, c: f"{p['spv_stake']}" if i == ax.first_forecast else f"{ax.col(i - 1)}{s.rref('div_stake')}",
    )
    S.line(
        "div_avail2", label="Cash flow available for dividends", cols=fc, fn=lambda s, i, c: f"{c}{s.rref('div_avail')}"
    )
    S.line(
        "div_total",
        label="Total Dividends",
        cols=fc,
        fn=lambda s, i, c: f"{c}{s.rref('div_avail2')}*{c}{s.rref('div_payout')}",
    )
    S.line(
        "div_spv",
        label="Dividends to SPV",
        total=True,
        bold=True,
        cols=fc,
        fn=lambda s, i, c: f"{c}{s.rref('div_total')}*{c}{s.rref('div_stake')}",
    )
    S.spacer(2)


# ---------------------------------------------------------------------------
def entry_and_sources(S: ModelSheet, cfg: dict) -> None:
    """Point-in-time blocks — values sit in the first data column (col I)."""
    ax = S.axis
    last = ax.last_hist
    p = cfg
    ic = ax.col(0)  # first data column letter (I)

    def only0(fn):
        return lambda s, i, c: fn(s, c) if i == 0 else None

    S.section("Transaction Assumptions")
    S.spacer()
    S.line("ent_ltm", label="LTM EBITDA", bold=True, fn=only0(lambda s, c: f"{ax.col(last)}{s.rref('EBITDA')}"))
    S.line(
        "ent_mult",
        label="(x) Entry Multiple",
        fmt=style.MULT,
        cols=[0],
        values=[p["entry_multiple"]] + [None] * (ax.n - 1),
        assumption=True,
    )
    S.line(
        "ent_ev",
        label="Enterprise Value",
        total=True,
        bold=True,
        fn=only0(lambda s, c: f"{c}{s.rref('ent_ltm')}*{c}{s.rref('ent_mult')}"),
    )
    S.line("ent_nd", label="(-) Net Debt", fn=only0(lambda s, c: f"-{ax.col(last)}{s.rref('nd_netdebt')}"))
    S.line(
        "ent_eq",
        label="Pre-money Equity Value",
        total=True,
        bold=True,
        fn=only0(lambda s, c: f"{c}{s.rref('ent_ev')}+{c}{s.rref('ent_nd')}"),
    )
    S.spacer(2)

    S.section("Sources & Uses")
    S.spacer()
    S.line("su_debt", label="Net Debt", fn=only0(lambda s, c: f"-{c}{s.rref('ent_nd')}"))
    S.line(
        "su_equity",
        label="Total Equity",
        total=True,
        bold=True,
        fn=only0(lambda s, c: f"{c}{s.rref('su_total')}-{c}{s.rref('su_debt')}"),
    )
    S.line("su_total", label="Total Sources", total=True, bold=True, fn=only0(lambda s, c: f"{c}{s.rref('ent_ev')}"))
    S.check("Check (Sources - Uses)", "su_total", "ent_ev")
    S.spacer(2)


# ---------------------------------------------------------------------------
def exit_returns(S: ModelSheet, cfg: dict) -> None:
    ax = S.axis
    ff = ax.first_forecast
    fc = list(range(ff, ax.n))
    entry_i = ax.last_hist  # entry sits at end of last historical year
    p = cfg

    S.section("Returns", years=True)
    S.spacer()
    S.line("ex_ebitda", label="EBITDA", cols=fc, fn=lambda s, i, c: f"{c}{s.rref('EBITDA')}")
    S.line(
        "ex_mult",
        label="Exit Multiple",
        fmt=style.MULT,
        cols=fc,
        fn=lambda s, i, c: f"{ax.col(0)}{s.rref('ent_mult')}" if i == ff else f"{ax.col(i - 1)}{s.rref('ex_mult')}",
    )
    S.line(
        "ex_ev",
        label="Enterprise Value",
        cols=fc,
        total=True,
        fn=lambda s, i, c: f"{c}{s.rref('ex_ebitda')}*{c}{s.rref('ex_mult')}",
    )
    S.line("ex_debt", label="(-) Debt", cols=fc, fn=lambda s, i, c: f"-{c}{s.rref('debt_eop')}")
    S.line("ex_cash", label="(+) Cash", cols=fc, fn=lambda s, i, c: f"{c}{s.rref('cash_eop')}")
    S.line(
        "ex_eq",
        label="Equity Value",
        cols=fc,
        total=True,
        bold=True,
        fn=lambda s, i, c: f"{c}{s.rref('ex_ev')}+{c}{s.rref('ex_debt')}+{c}{s.rref('ex_cash')}",
    )
    S.line("ex_stake", label="SPV Stake", fmt=style.PCT, cols=fc, fn=lambda s, i, c: f"{c}{s.rref('div_stake')}")
    S.line(
        "ex_eq_spv",
        label="Equity Value to SPV",
        cols=fc,
        total=True,
        bold=True,
        fn=lambda s, i, c: f"{c}{s.rref('ex_eq')}*{c}{s.rref('ex_stake')}",
    )
    S.line("ex_div_spv", label="Dividends to SPV", cols=fc, fn=lambda s, i, c: f"{c}{s.rref('div_spv')}")
    S.spacer()

    # dates row for XIRR: entry col (last hist) + forecast cols
    def date_fn(s, i, c):
        if i == entry_i:
            return f"=DATE({ax.years[i]},12,31)"
        if i >= ff:
            return f"=DATE({ax.years[i]},12,31)"
        return None

    S.line("ret_dates", label="", fmt=style.DATE, cols=[entry_i] + fc, fn=date_fn)

    # value-creation matrix: one row per exit year e
    S._vc_rows = []
    for e in fc:
        name = f"vc_{ax.years[e]}"
        S._vc_rows.append((name, e))

        def make(e):
            def f(s, i, c):
                if i == entry_i:
                    # SPV invests only its stake of the total equity (its ticket),
                    # matched by the stake-adjusted exit proceeds below.
                    return f"-{ax.col(0)}{s.rref('su_equity')}*{ax.col(ff)}{s.rref('div_stake')}"
                if ff <= i < e:
                    return f"{c}{s.rref('ex_div_spv')}"
                if i == e:
                    return f"{c}{s.rref('ex_eq_spv')}+{c}{s.rref('ex_div_spv')}"
                return None

            return f

        S.line(name, label=f"{ax.years[e]} Value Creation", cols=[entry_i] + fc, fn=make(e))
    S.spacer()

    # IRR / MoM across exit years (summary band)
    first_c = ax.col(entry_i)
    last_c = ax.col(ax.n - 1)

    def irr_fn(s, i, c):
        if i < ff:
            return None
        r = s.rref(f"vc_{ax.years[i]}")
        dr = s.rref("ret_dates")
        return f"IFERROR(XIRR({first_c}{r}:{last_c}{r},{first_c}{dr}:{last_c}{dr}),0)"

    def mom_fn(s, i, c):
        if i < ff:
            return None
        r = s.rref(f"vc_{ax.years[i]}")
        return f"-SUM({ax.col(ff)}{r}:{last_c}{r})/{first_c}{r}"

    S.line("IRR", label="IRR", fmt=style.IRR_PCT, summary=True, cols=fc, fn=irr_fn)
    S.line("MoM", label="MoM", fmt=style.MULT, summary=True, cols=fc, fn=mom_fn)
