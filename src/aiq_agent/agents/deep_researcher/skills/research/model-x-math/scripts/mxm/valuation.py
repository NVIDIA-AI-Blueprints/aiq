"""
Returns valuation — the house-standard deal layer appended to the operating model
sheet (the fixed house layout):

    Transaction Assumptions · Sources & Uses · Dividends · Returns · Key Ratios

Everything references the operating model's rows by NAME (EBITDA, debt_eop, cash_eop,
nd_netdebt, CFO, CFI, cf_int, cf_debt, div_total) so the whole thing re-drives when a
forecast driver, the scenario toggle, or the currency toggle changes. Single debt line —
every deal is ALL-EQUITY (no leveraged LBO variant).

Enabled only when the spec carries a `deal` block. Formulas ported/adapted from blocks.py
(entry_and_sources / dividends / exit_returns) and the returns-math reference.
"""

from __future__ import annotations

import datetime as _dt

from . import style
from .sheet import ModelSheet


def _only0(ax, fn):
    return lambda s, i, c: fn(s, c) if i == 0 else None


def _close_date(ax, deal: dict) -> _dt.datetime:
    """The deal-close date placeholder. `deal.close_date` ("YYYY-MM-DD") if given, else mid-year of
    the first forecast year (a sensible, editable default). Drives the entry leg of the XIRR."""
    cd = deal.get("close_date")
    if cd:
        y, m, d = (int(x) for x in str(cd).split("-")[:3])
        return _dt.datetime(y, m, d)
    yr = ax.years[ax.first_forecast if ax.n_forecast else ax.last_hist]
    return _dt.datetime(yr, 6, 30)


# ---------------------------------------------------------------------------
def transaction_assumptions(S: ModelSheet, deal: dict) -> None:
    """Entry: LTM EBITDA × Entry Multiple → EV; − Net Debt → Pre-money; + Primary Injection
    → Post-money Equity. Point-in-time values sit in the first data column (col I)."""
    ax = S.axis
    last = ax.last_hist
    # LTM basis: trailing (last actual, default) or forward (first forecast, the analyst's FY+1 run-rate).
    ltm_col = ax.first_forecast if (deal.get("ltm_basis") == "forward" and ax.n_forecast) else last
    S.section("Transaction Assumptions")
    S.spacer()
    # Editable deal-close date (yellow placeholder) — the entry leg of the XIRR uses it, so a mid-year
    # close gives a short, high-IRR first period. Change the cell and the returns re-drive.
    S.line(
        "ent_date",
        label="Deal Close Date",
        fmt=style.DATE,
        currency=False,
        cols=[0],
        assumption=True,
        values=[_close_date(ax, deal)] + [None] * (ax.n - 1),
    )
    S.line("ent_ltm", label="LTM EBITDA", bold=True, fn=_only0(ax, lambda s, c: f"{ax.col(ltm_col)}{s.rref('EBITDA')}"))
    S.line(
        "ent_mult",
        label="(x) Entry Multiple",
        fmt=style.MULT,
        cols=[0],
        currency=False,
        values=[deal.get("entry_multiple", 10.0)] + [None] * (ax.n - 1),
        assumption=True,
    )
    S.line(
        "ent_ev",
        label="Enterprise Value",
        total=True,
        bold=True,
        fn=_only0(ax, lambda s, c: f"{c}{s.rref('ent_ltm')}*{c}{s.rref('ent_mult')}"),
    )
    # Entry net debt links directly to the editable Entry Balances cells (Term Debt − Cash), not a
    # historical net-debt cell (history carries no inferred debt in the all-equity teaser model).
    S.line(
        "ent_nd", label="(-) Net Debt", fn=_only0(ax, lambda s, c: f"-($G${s.rref('ob_debt')}-$G${s.rref('ob_cash')})")
    )
    S.line(
        "ent_eq",
        label="Pre-money Equity Value",
        total=True,
        bold=True,
        fn=_only0(ax, lambda s, c: f"{c}{s.rref('ent_ev')}+{c}{s.rref('ent_nd')}"),
    )
    S.line(
        "ent_pi",
        label="(+) Primary Injection",
        cols=[0],
        assumption=True,
        values=[deal.get("primary_injection", 0.0)] + [None] * (ax.n - 1),
    )
    S.line(
        "ent_posteq",
        label="Post-money Equity Value",
        total=True,
        bold=True,
        fn=_only0(ax, lambda s, c: f"{c}{s.rref('ent_eq')}+{c}{s.rref('ent_pi')}"),
    )
    S.spacer(2)


# ---------------------------------------------------------------------------
def sources_uses(S: ModelSheet, deal: dict) -> None:
    """Gold-standard Sources & Uses with an equity split (matches the house-standard build):

        Sources: New Debt · Rollover Equity · Sponsor SPV Equity → Total Equity → Total Sources
        Uses:    Net Debt (refinanced) · Primary · Secondary · Rollover → Purchase Equity → Total Uses

    `rollover_pct` = the share of purchase equity the existing shareholders roll (0 = clean buyout).
    The sponsor SPV funds the rest and is paid its share at exit (`spv_stake` = 1 − rollover_pct,
    normalised in build). Everything foots: Total Sources − Total Uses = 0. `su_equity` (Total Equity =
    post-money) is kept as the name the Returns block reads for the entry ticket."""
    ax = S.axis
    stake = deal.get("spv_stake")
    roll = deal.get("rollover_pct")
    if roll is None:
        roll = (1.0 - stake) if stake is not None else 0.0
    S.section("Sources & Uses")
    S.spacer()
    # Rollover % is an editable input cell (col G), not a baked-in constant.
    S.line(
        "su_rollpct",
        label="Rollover % (seller reinvests)",
        g=float(roll),
        g_fmt=style.PCT,
        currency=False,
        comment="ASSUMED: share of purchase equity the existing holders roll into the deal.",
    )
    # Sources
    S.line("su_debt", label="New Debt", fn=_only0(ax, lambda s, c: f"-{c}{s.rref('ent_nd')}"))
    S.line(
        "su_roll",
        label="Rollover Equity",
        fn=_only0(ax, lambda s, c: f"$G${s.rref('su_rollpct')}*{c}{s.rref('ent_posteq')}"),
    )
    S.line(
        "su_spv",
        label="Sponsor SPV Equity",
        fn=_only0(ax, lambda s, c: f"{c}{s.rref('ent_posteq')}-{c}{s.rref('su_roll')}"),
    )
    S.line(
        "su_equity",
        label="Total Equity",
        total=True,
        bold=True,
        fn=_only0(ax, lambda s, c: f"{c}{s.rref('su_roll')}+{c}{s.rref('su_spv')}"),
    )
    S.line(
        "su_total",
        label="Total Sources",
        total=True,
        bold=True,
        fn=_only0(ax, lambda s, c: f"{c}{s.rref('su_debt')}+{c}{s.rref('su_equity')}"),
    )
    S.spacer()
    # Uses
    S.line("su_refi", label="Net Debt (refinanced)", fn=_only0(ax, lambda s, c: f"-{c}{s.rref('ent_nd')}"))
    S.line("su_primary", label="Primary Injection", fn=_only0(ax, lambda s, c: f"{c}{s.rref('ent_pi')}"))
    S.line(
        "su_secondary",
        label="Secondary (cash to sellers)",
        fn=_only0(ax, lambda s, c: f"{c}{s.rref('su_equity')}-{c}{s.rref('su_roll')}-{c}{s.rref('su_primary')}"),
    )
    S.line("su_rolluse", label="Rollover Equity", fn=_only0(ax, lambda s, c: f"{c}{s.rref('su_roll')}"))
    S.line(
        "su_purchase",
        label="Purchase Equity",
        total=True,
        bold=True,
        fn=_only0(ax, lambda s, c: f"{c}{s.rref('su_primary')}+{c}{s.rref('su_secondary')}+{c}{s.rref('su_rolluse')}"),
    )
    S.line(
        "su_uses",
        label="Total Uses",
        total=True,
        bold=True,
        fn=_only0(ax, lambda s, c: f"{c}{s.rref('su_refi')}+{c}{s.rref('su_purchase')}"),
    )
    S.check("Check (Sources - Uses)", "su_total", "su_uses")
    S.spacer(2)


# ---------------------------------------------------------------------------
def dividends(S: ModelSheet, deal: dict) -> None:
    """Cash available (pre-dividend) × Payout% → Total Dividends; × SPV stake → to SPV.
    Payout is an editable per-forecast-year blue row; `div_avail` comes from cash_flow."""
    ax = S.axis
    fc = range(ax.first_forecast, ax.n)
    payout = list(deal.get("payout", [0.5] + [0.8] * (ax.n_forecast - 1)))
    payout = (payout + [payout[-1]] * ax.n_forecast)[: ax.n_forecast] if payout else [0.0] * ax.n_forecast
    S.section("Dividends", years=True)
    S.spacer()
    # Presentation order: Payout → Cash available → Total Dividends → SPV Stake → Dividends to SPV.
    S.line(
        "div_payout",
        label="Dividend Payout",
        fmt=style.PCT,
        currency=False,
        cols=fc,
        values=[None] * ax.n_hist + payout,
    )
    S.line(
        "div_avail2", label="Cash flow available for dividends", cols=fc, fn=lambda s, i, c: f"{c}{s.rref('div_avail')}"
    )
    S.line(
        "div_total",
        label="Total Dividends",
        total=True,
        bold=True,
        cols=fc,
        fn=lambda s, i, c: f"MAX(0,{c}{s.rref('div_avail2')})*{c}{s.rref('div_payout')}",
    )
    S.spacer()
    # SPV stake is LINKED to the Sources & Uses rollover cell (sponsor owns whatever the sellers don't
    # roll): 1 − rollover%. Not a hardcoded 100%/30%; edit the rollover input and the stake re-drives.
    S.line(
        "div_stake",
        label="SPV Stake",
        fmt=style.PCT,
        currency=False,
        cols=fc,
        fn=lambda s, i, c: (
            f"1-$G${s.rref('su_rollpct')}" if i == ax.first_forecast else f"{ax.col(i - 1)}{s.rref('div_stake')}"
        ),
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
def returns(S: ModelSheet, deal: dict) -> None:
    """Per candidate exit year: Exit EV = EBITDA × Exit Multiple; Equity = EV − Debt + Cash;
    × SPV stake → Equity to SPV. Value-creation matrix → XIRR / MoM across exit years."""
    ax = S.axis
    ff = ax.first_forecast
    fc = list(range(ff, ax.n))
    entry_i = ax.last_hist

    S.section("Returns", years=True)
    S.spacer()
    S.line("ex_ebitda", label="EBITDA", cols=fc, fn=lambda s, i, c: f"{c}{s.rref('EBITDA')}")
    # Exit multiple LINKS to the entry multiple cell by default (exit = entry), then carries flat.
    # Editable in Excel — override any year's cell for a different exit multiple.
    S.line(
        "ex_mult",
        label="Exit Multiple",
        fmt=style.MULT,
        currency=False,
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
    S.line(
        "ex_stake",
        label="SPV Stake",
        fmt=style.PCT,
        currency=False,
        cols=fc,
        fn=lambda s, i, c: f"{c}{s.rref('div_stake')}",
    )
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

    def date_fn(s, i, c):
        # Entry leg uses the editable Deal Close Date cell; exits are year-ends.
        if i == entry_i:
            return f"={ax.col(0)}{s.rref('ent_date')}"
        return f"=DATE({ax.years[i]},12,31)" if i >= ff else None

    S.line("ret_dates", label="", fmt=style.DATE, currency=False, cols=[entry_i] + fc, fn=date_fn)

    for e in fc:
        name = f"vc_{ax.years[e]}"

        def make(e):
            def f(s, i, c):
                if i == entry_i:
                    return f"-{ax.col(0)}{s.rref('su_equity')}*{ax.col(ff)}{s.rref('div_stake')}"
                if ff <= i < e:
                    return f"{c}{s.rref('ex_div_spv')}"
                if i == e:
                    return f"{c}{s.rref('ex_eq_spv')}+{c}{s.rref('ex_div_spv')}"
                return None

            return f

        S.line(name, label=f"{ax.years[e]} Value Creation", cols=[entry_i] + fc, fn=make(e))
    S.spacer()

    first_c, last_c = ax.col(entry_i), ax.col(ax.n - 1)

    def irr_fn(s, i, c):
        if i < ff:
            return None
        r, dr = s.rref(f"vc_{ax.years[i]}"), s.rref("ret_dates")
        return f"IFERROR(XIRR({first_c}{r}:{last_c}{r},{first_c}{dr}:{last_c}{dr}),0)"

    def mom_fn(s, i, c):
        if i < ff:
            return None
        r = s.rref(f"vc_{ax.years[i]}")
        return f"-SUM({ax.col(ff)}{r}:{last_c}{r})/{first_c}{r}"

    S.line("IRR", label="IRR", fmt=style.IRR_PCT, summary=True, cols=fc, fn=irr_fn)
    S.line("MoM", label="MoM", fmt=style.MULT, summary=True, cols=fc, fn=mom_fn)
    S.spacer(2)


# ---------------------------------------------------------------------------
def key_ratios(S: ModelSheet, deal: dict) -> None:
    """A summary band (the house-standard 'Model X - Key Ratios'): leverage + top-line links."""
    ax = S.axis
    fcols = range(ax.first_forecast, ax.n)  # leverage ratios follow the forecast term debt / cash
    S.section("Model X - Key Ratios", years=True)
    S.spacer()
    S.line("kr_gd", label="Gross Debt", cols=fcols, fn=lambda s, i, c: f"{c}{s.rref('debt_eop')}")
    S.line("kr_cash", label="Cash", cols=fcols, fn=lambda s, i, c: f"{c}{s.rref('cash_eop')}")
    S.line(
        "kr_nd", label="Net Debt", total=True, bold=True, cols=fcols, fn=lambda s, i, c: f"{c}{s.rref('nd_netdebt')}"
    )
    S.spacer()
    S.line(
        "kr_gde",
        label="Gross Debt / EBITDA",
        italic=True,
        fmt=style.MULT,
        cols=fcols,
        fn=lambda s, i, c: f"{c}{s.rref('debt_eop')}/{c}{s.rref('EBITDA')}",
    )
    S.line(
        "kr_nde",
        label="Net Debt / EBITDA",
        italic=True,
        fmt=style.MULT,
        cols=fcols,
        fn=lambda s, i, c: f"{c}{s.rref('nd_netdebt')}/{c}{s.rref('EBITDA')}",
    )
    S.spacer()

    # house returns metrics — a FIXED block appended to Key Ratios (matches the reviewer's gold standard):
    # EBITDA · Dividends · Free Cash Flow (House Definition = EBIT) · Cash Flow Conversion % (FCF/EBITDA) ·
    # Cash Yield % (FCF / entry Total Equity) · Dividend Yield % (Dividends / entry Total Equity). Entry
    # equity = the point-in-time `su_equity` (Total Equity) in the first data column, referenced absolutely.
    eq = lambda s: f"${ax.col(0)}${s.rref('su_equity')}"
    S.line("hr_ebitda", label="EBITDA", bold=True, fn=lambda s, i, c: f"{c}{s.rref('EBITDA')}")
    S.line("hr_div", label="Dividends", bold=True, cols=fcols, fn=lambda s, i, c: f"{c}{s.rref('div_total')}")
    S.line(
        "hr_fcf",
        label="Free Cash Flow (House Definition)",
        bold=True,
        cols=fcols,
        fn=lambda s, i, c: f"{c}{s.rref('EBIT')}",
    )
    S.line(
        "hr_conv",
        label="Cash Flow Conversion %",
        fmt=style.PCT,
        currency=False,
        cols=fcols,
        fn=lambda s, i, c: f"{c}{s.rref('hr_fcf')}/{c}{s.rref('hr_ebitda')}",
    )
    S.line(
        "hr_cashyield",
        label="Cash Yield %",
        fmt=style.PCT,
        currency=False,
        cols=fcols,
        fn=lambda s, i, c: f"{c}{s.rref('hr_fcf')}/{eq(s)}",
    )
    S.line(
        "hr_divyield",
        label="Dividend Yield %",
        fmt=style.PCT,
        currency=False,
        cols=fcols,
        fn=lambda s, i, c: f"{c}{s.rref('hr_div')}/{eq(s)}",
    )
    S.spacer(2)
