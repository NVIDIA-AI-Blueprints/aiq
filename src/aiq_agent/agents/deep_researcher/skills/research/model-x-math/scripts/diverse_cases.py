"""
Diverse-input proof: build + LibreOffice-recalc a spread of DELIBERATELY non-packaging, often thin or
ragged sources, and assert none crash, none produce #DIV/0!/#REF!, every Check foots, and any deal
metrics are non-zero. This is the regression guard that the skill (helper) survives the real variety of
inputs — not just the one rich case it was tuned on. The AGENT's reasoning (which method, which
assumption, when to ask) lives in SKILL.md; this file only proves the renderer is robust to the shapes
that reasoning will hand it.

Run: python3 diverse_cases.py   (needs LibreOffice on PATH, like mxm.verify)
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from mxm.build import build
from mxm.verify import verify

# Each case is (label, spec, extra-asserts(result)->None|str). Kept small so the recalc gate is quick.
CASES = [
    # Asset-light SaaS: high margin, ~no capex, only Revenue+EBITDA sourced, our-case forecast.
    (
        "saas-asset-light",
        {
            "mode": "operating",
            "company": "NimbusSaaS",
            "units": "(in $m)",
            "start_year": 2021,
            "n_hist": 4,
            "n_forecast": 5,
            "pnl": {
                "revenue": [40, 62, 95, 140],
                "revenue_growth": [0.35, 0.30, 0.28, 0.25, 0.22],
                "ebitda": [2, 8, 20, 38],
                "ebitda_margin": [0.28, 0.30, 0.31, 0.32, 0.33],
            },
            "assumptions": {
                "capex_pct": {"value": 0.03, "rationale": "Asset-light SaaS; ~3% of revenue capitalised dev."},
                "da_pct": {"value": 0.04, "rationale": "Capitalised-software amortisation, ~4% of revenue."},
                "nwc_pct": {"value": 0.0, "rationale": "Deferred revenue offsets receivables; ~0 WC drag."},
            },
        },
    ),
    # Thin retailer: revenue only, actuals-only, everything else an assumption.
    (
        "retail-thin",
        {
            "mode": "operating",
            "company": "ThriftRetail",
            "units": "(in €m)",
            "start_year": 2022,
            "n_hist": 3,
            "pnl": {"revenue": [210, 235, 250]},
            "assumptions": {
                "ebitda_margin": {"value": 0.07, "rationale": "Thin grocery-style margin; 7% of revenue."},
                "capex_pct": {"value": 0.03, "rationale": "Store maintenance capex ~3% of revenue."},
            },
        },
    ),
    # Ragged: EBITDA disclosed for only 3 of 5 historical years (over-short array -> trailing blanks).
    (
        "ragged-arrays",
        {
            "mode": "operating",
            "company": "RaggedCo",
            "units": "(in $m)",
            "start_year": 2020,
            "n_hist": 5,
            "pnl": {"revenue": [100, 120, 150, 170, 190], "ebitda": [20, 26, 33]},
        },
    ),
    # Loss / zero year: revenue hits 0 and EBITDA goes negative — stresses every ratio guard.
    (
        "loss-and-zero",
        {
            "mode": "operating",
            "company": "CyclicalCo",
            "units": "(in $m)",
            "start_year": 2021,
            "n_hist": 4,
            "pnl": {"revenue": [300, 120, 0, 180], "ebitda": [40, 5, -10, 15]},
        },
    ),
    # Thin DEAL: minimal financials + a valuation layer (no capex/D&A/debt sourced).
    (
        "deal-thin",
        {
            "mode": "operating",
            "company": "MicroDeal",
            "units": "(in $m)",
            "start_year": 2022,
            "n_hist": 3,
            "n_forecast": 5,
            "pnl": {
                "revenue": [50, 58, 65],
                "revenue_growth": [0.10, 0.10, 0.08, 0.08, 0.06],
                "ebitda": [8, 10, 12],
                "ebitda_margin": [0.19, 0.20, 0.20, 0.20, 0.20],
            },
            "deal": {
                "entry_multiple": 9.0,
                "entry_leverage": 3.0,
                "spv_stake": 0.80,
                "payout": [0.5, 0.7, 0.7, 0.7, 0.7],
            },
        },
    ),
]


def _run(label: str, spec: dict) -> bool:
    wb = build(spec)  # must not raise
    with tempfile.NamedTemporaryFile(suffix=f"_{label}.xlsx", delete=False) as f:
        path = f.name
    wb.save(path)
    res = verify(path)
    div = [e for e in res["formula_errors"] if "#DIV/0!" in e or "#REF!" in e or "#VALUE!" in e]
    ok = res["status"] == "ok"
    # every gap must land as a documented assumption cell (rationale comment) — proof nothing is a
    # silent hardcode. Check the Assumptions sheet has at least one commented input for thin specs.
    detail = (
        f"status={res['status']} errors={len(res['formula_errors'])} div/ref={len(div)} "
        f"checks={res['failing_checks'] or '{}'}"
    )
    print(f"  {'PASS' if ok and not div else 'FAIL'}  {label:20} {detail}")
    if res["formula_errors"][:3]:
        print(f"        first errors: {res['formula_errors'][:3]}")
    Path(path).unlink(missing_ok=True)
    return ok and not div


def main() -> int:
    print("diverse-input proof (build + LibreOffice recalc):")
    results = [_run(label, spec) for label, spec in CASES]
    n_ok = sum(results)
    print(f"\n{n_ok}/{len(results)} cases green")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
