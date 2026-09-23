"""
DCF valuation — its own tab (the "purely mine" layer, in house style).

WACC build → unlevered FCFF (off the model sheet's forecast) → Gordon terminal value →
mid-year discounting → EV → Equity, implied EV/EBITDA, and a WACC × g sensitivity grid.
Everything is formula-driven and cross-references the main model sheet, so it re-drives with
the model's scenario / currency toggles. Logic follows SKILL(13); every input is an editable
blue cell (Damodaran fallbacks as defaults).
"""

from __future__ import annotations

from . import style
from .sheet import ModelSheet

DEFAULTS = dict(
    rf=0.04, beta_u=1.0, erp=0.06, size_premium=0.02, cost_of_debt=0.055, de_ratio=0.30, tax_rate=0.25, perp_growth=0.03
)


def build_dcf(wb, main: ModelSheet, data: dict) -> None:
    cfg = {**DEFAULTS, **(data.get("dcf") or {})}
    ax = main.axis
    ff, n = ax.first_forecast, ax.n
    fc = list(range(ff, n))
    val_year = ax.years[ax.last_hist]
    ic, lastc = ax.col(0), ax.col(n - 1)

    ws = wb.create_sheet("DCF")
    D = ModelSheet(ws, ax, data["company"], "(DCF — in model currency)", title=f"{data['company']} - DCF Valuation")

    def M(name, c):  # cross-sheet ref to the model sheet at column c
        return main.xref(name, c)

    def pt(name, label, *, val=None, fn=None, bold=False, total=False, fmt=style.NUM1, assumption=False, cur=True):
        """A point-in-time row living in the first data column (col I)."""
        D.line(
            name,
            label=label,
            cols=[0],
            bold=bold,
            total=total,
            fmt=fmt,
            currency=cur,
            assumption=assumption,
            values=([val] + [None] * (n - 1)) if val is not None else None,
            fn=(lambda s, i, c: fn(s, c)) if fn else None,
        )

    # ---- WACC build (editable blue inputs, Damodaran fallbacks) ----
    D.section("WACC")
    D.spacer()
    pt("rf", "Risk-free rate", val=cfg["rf"], assumption=True, fmt=style.PCT, cur=False)
    pt("beta_u", "Unlevered beta (βu)", val=cfg["beta_u"], assumption=True, fmt=style.MULT, cur=False)
    pt("erp", "Equity risk premium", val=cfg["erp"], assumption=True, fmt=style.PCT, cur=False)
    pt("size", "Size premium", val=cfg["size_premium"], assumption=True, fmt=style.PCT, cur=False)
    pt("rd", "Pre-tax cost of debt", val=cfg["cost_of_debt"], assumption=True, fmt=style.PCT, cur=False)
    pt("de", "D / E", val=cfg["de_ratio"], assumption=True, fmt=style.PCT, cur=False)
    pt("tax", "Tax rate", val=cfg["tax_rate"], assumption=True, fmt=style.PCT, cur=False)
    pt(
        "beta_l",
        "Levered beta (βL)",
        fmt=style.MULT,
        cur=False,
        fn=lambda s, c: f"{c}{s.rref('beta_u')}*(1+(1-{c}{s.rref('tax')})*{c}{s.rref('de')})",
    )
    pt(
        "ke",
        "Cost of equity (Ke)",
        fmt=style.PCT,
        cur=False,
        fn=lambda s, c: f"{c}{s.rref('rf')}+{c}{s.rref('beta_l')}*{c}{s.rref('erp')}+{c}{s.rref('size')}",
    )
    pt(
        "kd",
        "After-tax cost of debt (Kd)",
        fmt=style.PCT,
        cur=False,
        fn=lambda s, c: f"{c}{s.rref('rd')}*(1-{c}{s.rref('tax')})",
    )
    pt(
        "wacc",
        "WACC",
        bold=True,
        total=True,
        fmt=style.PCT,
        cur=False,
        fn=lambda s, c: (
            f"{c}{s.rref('ke')}*(1/(1+{c}{s.rref('de')}))+{c}{s.rref('kd')}*({c}{s.rref('de')}/(1+{c}{s.rref('de')}))"
        ),
    )
    D.spacer(2)

    # ---- Unlevered FCFF off the model sheet's forecast ----
    wacc = f"$I${D.rref('wacc')}"
    tax = f"$I${D.rref('tax')}"
    D.section("Free Cash Flow to Firm", years=True)
    D.spacer()
    D.line("dcf_ebit", label="EBIT", cols=fc, fn=lambda s, i, c: M("EBIT", c))
    D.line("dcf_nopat", label="NOPAT (EBIT × (1−tax))", cols=fc, fn=lambda s, i, c: f"{M('EBIT', c)}*(1-{tax})")
    D.line("dcf_da", label="(+) D&A", cols=fc, fn=lambda s, i, c: f"-{M('DA', c)}")
    D.line("dcf_capex", label="(-) Capex", cols=fc, fn=lambda s, i, c: M("capex_total", c))
    D.line("dcf_nwc", label="(-) Change in NWC", cols=fc, fn=lambda s, i, c: M("cf_nwc", c))
    D.line(
        "dcf_fcff",
        label="Free Cash Flow to Firm",
        total=True,
        bold=True,
        cols=fc,
        fn=lambda s, i, c: (
            f"{c}{s.rref('dcf_nopat')}+{c}{s.rref('dcf_da')}+{c}{s.rref('dcf_capex')}+{c}{s.rref('dcf_nwc')}"
        ),
    )
    # Discount period tied to the editable Deal Close Date on the model sheet (year-end less close, in
    # years) — not a hardcoded mid-year offset; edit the close date and the DCF re-discounts.
    close = main.xref("ent_date", ax.col(0)) if "ent_date" in main.rows else None
    D.line(
        "dcf_t",
        label="Discount period (from close date)",
        fmt="0.0",
        currency=False,
        cols=fc,
        fn=(lambda s, i, c: f"(DATE({ax.years[i]},12,31)-{close})/365")
        if close
        else (lambda s, i, c: f"{ax.years[i]}-{val_year}-0.5"),
    )
    D.line(
        "dcf_df",
        label="Discount factor",
        fmt="0.000",
        currency=False,
        cols=fc,
        fn=lambda s, i, c: f"1/(1+{wacc})^{c}{s.rref('dcf_t')}",
    )
    D.line(
        "dcf_pv",
        label="PV of FCFF",
        total=True,
        cols=fc,
        fn=lambda s, i, c: f"{c}{s.rref('dcf_fcff')}*{c}{s.rref('dcf_df')}",
    )
    D.spacer(2)

    # ---- Valuation summary (point-in-time, col I) ----
    ffc = ax.col(ff)
    D.section("Valuation")
    D.spacer()
    pt("g", "Perpetuity growth (g)", val=cfg["perp_growth"], assumption=True, fmt=style.PCT, cur=False)
    pt(
        "sumpv",
        "Sum of PV of FCFF",
        bold=True,
        fn=lambda s, c: f"SUM({ffc}{s.rref('dcf_pv')}:{lastc}{s.rref('dcf_pv')})",
    )
    pt(
        "tv",
        "Terminal value (Gordon)",
        fn=lambda s, c: f"{lastc}{s.rref('dcf_fcff')}*(1+{c}{s.rref('g')})/({wacc}-{c}{s.rref('g')})",
    )
    pt(
        "pvtv",
        "PV of terminal value",
        bold=True,
        fn=lambda s, c: f"{c}{s.rref('tv')}/(1+{wacc})^{lastc}{s.rref('dcf_t')}",
    )
    pt("ev", "Enterprise Value", bold=True, total=True, fn=lambda s, c: f"{c}{s.rref('sumpv')}+{c}{s.rref('pvtv')}")
    # Net debt at the DEAL CLOSE (first forecast column), not the last actual year.
    pt("nd", "(-) Net Debt (at close)", fn=lambda s, c: f"-{main.xref('nd_netdebt', ax.col(ff))}")
    pt("eq", "Equity Value", bold=True, total=True, fn=lambda s, c: f"{c}{s.rref('ev')}+{c}{s.rref('nd')}")
    pt(
        "evebitda",
        "Implied EV / EBITDA (Y1)",
        fmt=style.MULT,
        cur=False,
        fn=lambda s, c: f"{c}{s.rref('ev')}/{M('EBITDA', ffc)}",
    )
    D.spacer(2)

    _sensitivity(D, ax, wacc)
    D.render()


def _sensitivity(D: ModelSheet, ax, wacc: str) -> None:
    """A WACC × g grid of Enterprise Value: rows = WACC (base ±2%, 1% steps), cols = g
    (base ±1%, 0.5% steps). Each cell re-discounts the FCFF row + Gordon TV at that (WACC, g)."""
    n = ax.n
    ff = ax.first_forecast
    ffc, lastc = ax.col(ff), ax.col(n - 1)
    fcff_r, t_r = D.rref("dcf_fcff"), D.rref("dcf_t")
    g0 = f"$I${D.rref('g')}"
    D.section("Sensitivity — Enterprise Value (WACC × g)")
    D.spacer()
    top = D.r  # row for the g header
    left = style.COL_INPUT  # column G holds the WACC axis; g axis spans to the right
    fcff_rng = f"{ffc}{fcff_r}:{lastc}{fcff_r}"
    t_rng = f"{ffc}{t_r}:{lastc}{t_r}"
    # write header (g offsets) and body via direct cell access after reserving rows
    D._sens = dict(top=top, fcff_rng=fcff_rng, t_rng=t_rng, lastc=lastc, wacc=wacc, g0=g0)
    for _ in range(7):  # reserve corner + 5 WACC rows (+1 spacer)
        D.spacer()

    # hook the direct-write into render via a post-spec (simple: write now to ws using reserved rows)
    ws = D.ws
    g_off = [-0.01, -0.005, 0.0, 0.005, 0.01]
    w_off = [-0.02, -0.01, 0.0, 0.01, 0.02]
    r0, c0 = top, left
    style.section(ws.cell(row=r0, column=c0))
    ws.cell(row=r0, column=c0).value = "WACC \\ g"
    for j, go in enumerate(g_off):
        cc = ws.cell(row=r0, column=c0 + 1 + j)
        cc.value = f"={g0}+{go}"
        style.value(cc, style.PCT)
        style.label(cc, bold=True)
    for iw, wo in enumerate(w_off):
        rr = r0 + 1 + iw
        wc = ws.cell(row=rr, column=c0)
        wc.value = f"={wacc}+{wo}"
        style.value(wc, style.PCT)
        style.label(wc, bold=True)
        wcell = f"${get_col(c0)}${rr}"
        for j in range(5):
            gcell = f"{get_col(c0 + 1 + j)}${r0}"
            ev = (
                f"=SUMPRODUCT({fcff_rng},(1+{wcell})^(-{t_rng}))"
                f"+({lastc}{fcff_r}*(1+{gcell})/({wcell}-{gcell}))/(1+{wcell})^{lastc}{t_r}"
            )
            cell = ws.cell(row=rr, column=c0 + 1 + j)
            cell.value = ev
            style.value(cell, style.NUM0)


def get_col(idx: int) -> str:
    from openpyxl.utils import get_column_letter

    return get_column_letter(idx)
