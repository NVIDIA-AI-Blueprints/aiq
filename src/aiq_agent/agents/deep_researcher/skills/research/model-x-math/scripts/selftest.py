"""
Fast structural self-test (no LibreOffice needed).

Builds the sample deal and asserts the workbook has the expected sheet, the core
blocks, blue inputs, and a Check row. For the full numeric gate (formula errors +
footing), run `python -m mxm.verify <out.xlsx>` which recalculates with LibreOffice.

    python selftest.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from mxm.build import build

HERE = Path(__file__).resolve().parent
SAMPLE = HERE.parent / "assets" / "sample_deal.json"

EXPECT_LABELS = [
    "Transaction Assumptions",
    "Enterprise Value",
    "Sources & Uses",
    "Total Sources",
    "Income Statement",
    "Revenue",
    "EBITDA",
    "EBIT",
    "Net Profit",
    "Cash Flow Statement",
    "Cash Flow from Operations",
    "Cash EoP",
    "Capex",
    "Debt Schedule",
    "Debt EoP",
    "Dividends",
    "Dividends to SPV",
    "Net Debt",
    "Returns",
    "Equity Value to SPV",
    "IRR",
    "MoM",
]


def main() -> int:
    data = json.loads(SAMPLE.read_text())
    wb = build(data)
    ws = wb.active

    labels = {ws.cell(r, 3).value for r in range(1, ws.max_row + 1)}
    missing = [x for x in EXPECT_LABELS if x not in labels]
    assert not missing, f"missing blocks/rows: {missing}"

    # a blue input exists (Revenue actual)
    blue = False
    for r in range(1, ws.max_row + 1):
        c = ws.cell(r, 9)  # col I
        if c.font and c.font.color and str(c.font.color.rgb).endswith("0000F4"):
            blue = True
            break
    assert blue, "no blue input cell found — styling not applied"

    # a Check row exists
    assert any(isinstance(v, str) and v.lower().startswith("check") for v in labels), "no Check row"

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        wb.save(f.name)
    print(f"OK deal-model — {len(EXPECT_LABELS)} blocks/rows present, styling applied, saved {f.name}")

    # canonical operating mode (no projection): two sheets, full skeleton, assumptions w/ comments
    CANON = [
        "Income Statement",
        "Revenue",
        "EBITDA",
        "D&A",
        "EBIT",
        "Interest expense",
        "EBT",
        "Tax expense",
        "Net Profit",
        "Cash Flow Statement",
        "Cash Flow from Operations",
        "Cash EoP",
        "Capex",
        "Total Capex",
        "Debt Schedule",
        "Debt EoP",
        "Free Cash Flow",
    ]
    for name in ["sample_operating.json", "sample_thin.json"]:
        op = json.loads((HERE.parent / "assets" / name).read_text())
        wb2 = build(op)
        # Assumptions are now INLINE on the model sheet (no separate tab).
        assert "Assumptions" not in wb2.sheetnames, f"{name}: Assumptions should not be a separate tab"
        mws = wb2[[s for s in wb2.sheetnames if "Math" in s][0]]
        olabels = {mws.cell(r, 3).value for r in range(1, mws.max_row + 1)}
        assert "Assumptions" in olabels, f"{name}: no inline Assumptions section on the model sheet"
        miss = [x for x in CANON if x not in olabels]
        assert not miss, f"{name}: canonical skeleton missing {miss}"
        for banned in ["Returns", "IRR", "Transaction Assumptions", "Dividends"]:
            assert banned not in olabels, f"{name}: should not contain {banned}"
        # rationale comments now sit on the col-G (input) cells of the Assumptions rows
        ncom = sum(1 for r in range(1, mws.max_row + 1) if mws.cell(r, 7).comment)
        assert ncom >= 1, f"{name}: assumptions have no rationale comments"
        print(f"OK operating '{name}' — full canonical skeleton (inline assumptions), {ncom} comments")

    # in-place currency conversion: money inputs become `=native/<FX cell>`, units re-label
    fx = json.loads((HERE.parent / "assets" / "sample_operating_fx.json").read_text())
    wb3 = build(fx)
    mws = wb3[[s for s in wb3.sheetnames if "Math" in s][0]]

    def _row(lbl):
        return next(
            (
                r
                for r in range(1, mws.max_row + 1)
                if isinstance(mws.cell(r, 3).value, str) and mws.cell(r, 3).value.startswith(lbl)
            ),
            None,
        )

    fxrow = _row("FX rate")
    currrow = _row("Display currency")
    assert fxrow and currrow, "FX case: missing 'FX rate' / 'Display currency' rows"
    ulabel = mws.cell(12, 3).value  # units label is a formula that follows the toggle
    assert isinstance(ulabel, str) and ulabel.startswith("=IF(") and "USD" in ulabel and "INR" in ulabel, (
        f"FX case: units label should toggle source/reporting: {ulabel!r}"
    )
    revcell = mws.cell(_row("Revenue"), 9).value  # col I
    assert (
        isinstance(revcell, str)
        and revcell.startswith("=")
        and "CHOOSE(" in revcell
        and f"${fxrow}" in revcell
        and f"$G${currrow}" in revcell
    ), f"FX case: Revenue not a currency toggle: {revcell!r}"
    # the FX rates + toggle themselves stay literal inputs (not self-converted)
    assert isinstance(mws.cell(fxrow, 9).value, (int, float)), "FX case: FX rate must stay a literal input"
    assert isinstance(mws.cell(currrow, 7).value, (int, float)), (
        "FX case: currency toggle must be an editable cell (col G)"
    )
    # backward-compat: no currency block => literal inputs, no FX row
    plain = build(json.loads((HERE.parent / "assets" / "sample_operating.json").read_text()))
    pmws = plain[[s for s in plain.sheetnames if "Math" in s][0]]
    assert not any(
        isinstance(pmws.cell(r, 3).value, str) and pmws.cell(r, 3).value.startswith("FX rate")
        for r in range(1, pmws.max_row + 1)
    ), "no-currency build should have no FX row"
    print(
        f"OK operating FX — currency conversion wired (FX row {fxrow}, units '(in USD m)'), "
        "backward-compatible when omitted"
    )

    # forecast — management case: forecast Revenue columns are blue inputs (sourced), no returns
    mgmt = json.loads((HERE.parent / "assets" / "sample_forecast_mgmt.json").read_text())
    wbm = build(mgmt)
    mm = wbm[[s for s in wbm.sheetnames if "Math" in s][0]]
    labels_m = {mm.cell(r, 3).value for r in range(1, mm.max_row + 1)}
    for banned in ["Returns", "IRR", "MoM", "Transaction Assumptions", "Dividends", "Sources & Uses"]:
        assert banned not in labels_m, f"forecast should carry no returns layer, found {banned}"
    assert isinstance(mm.cell(12, 3).value, str) and mm.cell(12, 3).value.startswith("=IF("), (
        "mgmt case: currency label should be a toggle formula"
    )
    # a forecast Revenue cell (col N = 2026, the 6th data col at index 5 → column 14) is a sourced input
    rrow = next(r for r in range(1, mm.max_row + 1) if mm.cell(r, 3).value == "Revenue")
    fc_rev = mm.cell(rrow, 13).value  # 2026 = first forecast column (index 4 → col 13)
    assert isinstance(fc_rev, str) and fc_rev.startswith("=") and "/" in fc_rev and "$" in fc_rev, (
        f"mgmt case: forecast Revenue should be a sourced (FX-converted) input, got {fc_rev!r}"
    )
    # a forecast always spans >= 5 years; management years beyond disclosure extrapolate LIVE
    ycols = sum(1 for c in range(9, 30) if mm.cell(12, c).value is not None)
    assert ycols >= mgmt["n_hist"] + 5, f"forecast must be >= 5 years (got {ycols} year cols)"
    ext = mm.cell(rrow, 15).value  # 2028 — beyond the teaser's 2-year disclosure
    assert isinstance(ext, str) and "*(1+" in ext, f"extrapolated year should be a live growth formula, got {ext!r}"

    # forecast — both/toggle: a Scenario selector + CHOOSE on the forecast value lines
    both = json.loads((HERE.parent / "assets" / "sample_forecast_both.json").read_text())
    wbb = build(both)
    mb = wbb[[s for s in wbb.sheetnames if "Math" in s][0]]
    scen = next(
        (
            r
            for r in range(1, mb.max_row + 1)
            if isinstance(mb.cell(r, 3).value, str) and mb.cell(r, 3).value.startswith("Case (")
        ),
        None,
    )
    assert scen, "both case: no Scenario selector"
    assert isinstance(mb.cell(scen, 7).value, (int, float)), "both case: selector must be an editable input (col G)"
    rrow_b = next(r for r in range(1, mb.max_row + 1) if mb.cell(r, 3).value == "Revenue")
    fc_b = mb.cell(rrow_b, 13).value  # 2026 = first forecast column
    assert isinstance(fc_b, str) and "CHOOSE(" in fc_b and f"$G${scen}" in fc_b, (
        f"both case: forecast Revenue should CHOOSE on the scenario cell, got {fc_b!r}"
    )
    print(f"OK forecast — management (sourced forecast, no returns) + both (Scenario CHOOSE toggle, cell G{scen})")

    # valuation — a `deal` block adds Returns on the model sheet + a DCF tab. All deals are ALL-EQUITY:
    # no Balance Sheet section and no LBO tab.
    valn = build(json.loads((HERE.parent / "assets" / "sample_valuation.json").read_text()))
    assert "DCF" in valn.sheetnames, f"valuation: missing DCF tab: {valn.sheetnames}"
    assert "LBO" not in valn.sheetnames, f"valuation: LBO tab should be removed (all-equity): {valn.sheetnames}"
    vmain = valn[[s for s in valn.sheetnames if "Model X Math" in s][0]]
    vrow = {}  # FIRST occurrence of each label (section headers win over later same-named total rows)
    for r in range(1, vmain.max_row + 1):
        v = vmain.cell(r, 3).value
        if isinstance(v, str) and v not in vrow:
            vrow[v] = r
    for need in [
        "Entry Balances (at Deal Close)",
        "Transaction Assumptions",
        "Sources & Uses",
        "Net Debt",
        "Dividends",
        "Returns",
        "IRR",
        "MoM",
        "Model X - Key Ratios",
    ]:
        assert need in vrow, f"valuation: model sheet missing '{need}'"
    assert "Balance Sheet" not in vrow, "valuation: Balance Sheet should be removed (all-equity)"
    assert "Revolver EoP" not in vrow, "valuation: revolver should be removed"
    # Net Debt is presented BEFORE Dividends; Gross Debt/EBITDA sits in the Debt Schedule (above Net Debt),
    # Net Debt/EBITDA in the Net Debt block (between Net Debt and Dividends).
    assert vrow["Gross Debt / EBITDA"] < vrow["Net Debt"] < vrow["Net Debt / EBITDA"] < vrow["Dividends"], (
        f"valuation: section/ratio order wrong: {[(k, vrow[k]) for k in ('Gross Debt / EBITDA', 'Net Debt', 'Net Debt / EBITDA', 'Dividends')]}"
    )
    assert any(isinstance(v, str) and v.lower().startswith("check") for v in vrow), "valuation: no Check row"
    dcf = valn["DCF"]
    dl = {dcf.cell(r, 3).value for r in range(1, dcf.max_row + 1)}
    assert "WACC" in dl and "Enterprise Value" in dl, "DCF: missing WACC / EV"
    # house returns-metrics block — a FIXED set of rows appended to Key Ratios ("rows are always the same").
    for need in ["Free Cash Flow (House Definition)", "Cash Flow Conversion %", "Cash Yield %", "Dividend Yield %"]:
        assert need in vrow, f"valuation: house-returns block missing '{need}'"
    cy_row = [r for r in range(1, vmain.max_row + 1) if vmain.cell(r, 3).value == "Cash Yield %"][0]
    cy = str(vmain.cell(cy_row, 13).value)  # first forecast col (M): FCF / entry Total Equity ($-absolute)
    assert f"$I${vrow['Total Equity']}" in cy, f"Cash Yield not divided by entry Total Equity: {cy}"
    # Driver % rows LINK to a single top Assumptions cell (=$G$xx) — not hardcoded per forecast column.
    assert "Tax rate" in vrow and "Cost of debt (interest %)" in vrow, "valuation: top Assumptions cells missing"
    for pctlbl in ["Tax Rate %", "Cost of debt %", "Repayment % of opening debt"]:
        prow = [r for r in range(1, vmain.max_row + 1) if vmain.cell(r, 3).value == pctlbl][0]
        f = str(vmain.cell(prow, 13).value)  # first forecast col M
        assert "$G$" in f, f"valuation: '{pctlbl}' not linked to an assumption cell (hardcoded?): {f}"
    # Dividends: Total Dividends is a bold subtotal, then a gap before SPV Stake.
    dtot = [r for r in range(1, vmain.max_row + 1) if vmain.cell(r, 3).value == "Total Dividends"][0]
    spv = [r for r in range(1, vmain.max_row + 1) if vmain.cell(r, 3).value == "SPV Stake"][0]
    assert spv - dtot >= 2, f"valuation: no spacer between Total Dividends (r{dtot}) and SPV Stake (r{spv})"
    print(
        "OK valuation — all-equity: Returns + DCF + house returns metrics; driver %-rows link to Assumptions cells; Div layout"
    )

    # ver9 — assumption realism: a teaser-style spec (no D&A, no balance sheet, projected + deal).
    #  (a) must NOT crash on missing D&A with a forecast (needed_keys regression guard);
    #  (b) D&A drives off capex (da_basis);  (c) entry_leverage seeds a real opening net debt;
    #  (d) primary_injection appears as an Equity Injection cash line.
    v9 = build(
        {
            "mode": "operating",
            "company": "Teaser",
            "units": "(in €m)",
            "start_year": 2021,
            "n_hist": 4,
            "n_forecast": 5,
            "pnl": {
                "revenue": [500, 550, 600, 640],
                "revenue_growth": [0.05] * 5,
                "ebitda": [100, 110, 120, 130],
                "ebitda_margin": [0.2] * 5,
                "da_basis": "capex",
            },
            "capex": {"total": [40, 45, 42, 44]},
            "deal": {
                "entry_multiple": 8.0,
                "entry_leverage": 4.0,
                "spv_stake": 0.6,
                "primary_injection": 50.0,
                "payout": [0.5, 0.8, 0.8, 0.8, 0.8],
            },
        }
    )
    v9m = v9[[s for s in v9.sheetnames if "Model X Math" in s][0]]
    v9row = {v9m.cell(r, 3).value: r for r in range(1, v9m.max_row + 1)}
    assert "(+) Equity Injection" in v9row, "ver9: primary injection not wired into CF"
    nd = v9m.cell(v9row["(-) Net Debt"], 9).value  # entry net debt formula/point value
    assert nd is not None, "ver9: entry net debt not seeded"
    # D&A drives off an editable "% of capex" row shown directly BELOW the line (referenced locally by
    # cell, not the top assumption). capex_total is negative, so a positive % yields a negative D&A.
    assert "D&A (% of capex)" in v9row, "ver9: da_capex_pct driver row missing"
    da_fn = v9m.cell(v9row["D&A"], 15).value  # a forecast D&A cell → must ref the % row below
    pct_row = v9row["D&A (% of capex)"]
    assert (
        isinstance(da_fn, str)
        and str(pct_row) in da_fn
        and "$G$" not in da_fn
        and not da_fn.lstrip("=").startswith("-")
    ), f"ver9: D&A not driven off the % row {pct_row}: {da_fn}"
    print("OK ver9 — no-D&A forecast builds; D&A off capex % row; entry debt seeds net debt; injection in CF")

    # ver10 — gold-standard rollover Sources & Uses split.
    assert {"New Debt", "Sponsor SPV Equity", "Rollover Equity", "Total Sources", "Total Uses"} <= set(v9row), (
        "ver10: rollover Sources & Uses lines missing"
    )
    print("OK ver10 — rollover Sources & Uses split present")

    # ver11 — the deal-close date is an EDITABLE date placeholder (yellow input), so the entry leg of
    # the XIRR is user-changeable and everything recalculates. Default = mid-year of the first forecast.
    import datetime as _dt

    cd_row = v9row.get("Deal Close Date")
    assert cd_row, "ver11: Deal Close Date cell missing"
    cdv = v9m.cell(cd_row, 9).value
    assert isinstance(cdv, _dt.datetime), f"ver11: close date not an editable date value: {cdv!r}"
    ret = v9m.cell(v9row["ret_dates"], 9 + 3).value if "ret_dates" in v9row else None  # entry-col date
    # forward-LTM option: LTM references the first forecast EBITDA when ltm_basis == "forward"
    fwd = build(
        {
            **json.loads((HERE.parent / "assets" / "sample_valuation.json").read_text()),
            "deal": {
                **json.loads((HERE.parent / "assets" / "sample_valuation.json").read_text())["deal"],
                "ltm_basis": "forward",
            },
        }
    )
    fm = fwd[[s for s in fwd.sheetnames if "Model X Math" in s][0]]
    frow = {fm.cell(r, 3).value: r for r in range(1, fm.max_row + 1)}
    assert isinstance(fm.cell(frow["Deal Close Date"], 9).value, _dt.datetime), "ver11: forward build lost close date"
    print("OK ver11 — editable Deal Close Date placeholder (real-date XIRR); forward-LTM option")

    # ver16 — SIMPLIFIED all-equity teaser: NO Balance Sheet and NO revolver; history carries only P&L +
    # Capex (every derived cash/debt/tax row is forecast-only); rate drivers are per-line "reported %" rows
    # referenced locally, not the top Assumptions block (NWC is the one exception, kept on the top cell).
    for gone in [
        "Balance Sheet",
        "Total Assets",
        "Total Liabilities + Equity",
        "Revolver EoP",
        "Opening Balance Sheet (Year 1 BoP)",
    ]:
        assert gone not in v9row, f"ver16: '{gone}' should be removed in the all-equity model"
    for need in ["Entry Balances (at Deal Close)", "Entry Cash (at close)", "Entry Term Debt (at close)"]:
        assert need in v9row, f"ver16: entry-balance row '{need}' missing"
    # history is FORECAST-ONLY for the derived rows: historical (col 9 = first year) interest + CFO are blank
    assert v9m.cell(v9row["Interest expense"], 9).value is None, "ver16: historical interest should be blank"
    assert v9m.cell(v9row["Cash Flow from Operations"], 9).value is None, "ver16: historical CFO should be blank"
    # Interest is CALCULATED in the Debt Schedule and LINKED into the P&L; Tax references the % row below.
    int_fc = v9m.cell(v9row["Interest expense"], 13).value  # first forecast column (2025 = col M)
    assert isinstance(int_fc, str) and str(v9row["Interest Expense"]) in int_fc, (
        f"ver16: IS interest not linked to the Debt Schedule row: {int_fc}"
    )
    tax_fc = v9m.cell(v9row["Tax expense"], 13).value
    assert isinstance(tax_fc, str) and str(v9row["Tax Rate %"]) in tax_fc and "$G$" not in tax_fc, (
        f"ver16: Tax not linked to the % row below: {tax_fc}"
    )
    # ΔNWC is nwc_pct × the CHANGE in revenue (kept on the top assumption cell): `-$G$..*(<cell> - <cell>)`.
    nwc_fn = v9m.cell(v9row["(-) Change in Net Working Capital"], 13).value  # a forecast column
    assert isinstance(nwc_fn, str) and "$G$" in nwc_fn and "*(" in nwc_fn and "-" in nwc_fn.split("*(", 1)[1], (
        f"ver16: NWC not on ΔRevenue: {nwc_fn}"
    )
    # SPV stake linked to the rollover input cell (some cell = 1 - $G$su_rollpct), not a hardcoded constant.
    assert any(isinstance(cell.value, str) and "1-$G$" in cell.value for row in v9m.iter_rows() for cell in row), (
        "ver16: SPV stake not linked to rollover cell"
    )
    print("OK ver16 — all-equity teaser: no BS/revolver; forecast-only history; per-line rate drivers; NWC on ΔRev")

    # ver18 — a `sources` dict renders a visible Data Sources & Provenance section (one editable cite/metric).
    src = build(
        {
            **json.loads((HERE.parent / "assets" / "sample_valuation.json").read_text()),
            "sources": {"revenue": "CIM p12 revenue bridge", "ebitda": "CIM p12 adj. EBITDA"},
        }
    )
    sm = src[[s for s in src.sheetnames if "Model X Math" in s][0]]
    labels = {sm.cell(r, 3).value for r in range(1, sm.max_row + 1)}
    assert "Data Sources & Provenance" in labels, "ver18: provenance section missing"
    assert any(isinstance(cell.value, str) and "CIM p12" in cell.value for row in sm.iter_rows() for cell in row), (
        "ver18: source citation not rendered"
    )
    # backward-compatible: no `sources` → no section
    nolabels = {v9m.cell(r, 3).value for r in range(1, v9m.max_row + 1)}
    assert "Data Sources & Provenance" not in nolabels, "ver18: provenance section should be omitted when no sources"
    print("OK ver18 — Data Sources & Provenance section (editable cites; omitted when no sources)")

    # ver20 — under the currency toggle, MONEY g-cells (opening balances) FX-wrap like the body so INR↔USD
    # is a pure re-denomination and the balance stays tied; toggle/ratio cells stay literal; the workbook
    # recalculates on open (fullCalcOnLoad).
    v20 = build(json.loads((HERE.parent / "assets" / "sample_valuation.json").read_text()))  # has a currency block
    assert v20.calculation.fullCalcOnLoad, "ver20: fullCalcOnLoad not set (files would read back null)"
    v20m = v20[[s for s in v20.sheetnames if "Model X Math" in s][0]]
    ocr = [r for r in range(1, v20m.max_row + 1) if v20m.cell(r, 3).value == "Entry Cash (at close)"][0]
    ocg = v20m.cell(ocr, 7).value
    assert isinstance(ocg, str) and "CHOOSE" in ocg, f"ver20: entry-balance g-cell not FX-wrapped: {ocg}"
    tcr = [
        r
        for r in range(1, v20m.max_row + 1)
        if isinstance(v20m.cell(r, 3).value, str) and v20m.cell(r, 3).value.startswith("Display currency")
    ][0]
    assert not isinstance(v20m.cell(tcr, 7).value, str), "ver20: currency toggle cell wrongly FX-wrapped"
    print("OK ver20 — money g-cells FX-wrap; toggle/ratio cells literal; fullCalcOnLoad set")
    print("Run `python -m mxm.verify <file>` — the Sources − Uses Check MUST foot to 0 every year.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
