"""
The Assumptions block — rendered inline at the top of the model sheet (same page as the
Income Statement etc.), not a separate tab.

Each used driver is an editable yellow cell in the input column (col G) carrying a **cell
comment** that states WHY the value was chosen and on what basis. The model references these
cells by formula, so editing an assumption on the page recalculates the whole model.

`Assumptions(sheet).build(keys, overrides)` reserves the section via the ModelSheet layout;
`ref(key)` then gives a same-sheet absolute reference like `$G$16` that blocks embed in formulas.
"""

from __future__ import annotations

from . import style

# key -> (label, number format, default value, default rationale)
DEFAULTS: dict[str, tuple[str, str, float, str]] = {
    "ebitda_margin": (
        "EBITDA margin (% revenue)",
        style.PCT,
        0.30,
        "No EBITDA disclosed in source; assumed 30% of revenue as a sector-typical margin. Edit if a margin is known.",
    ),
    "da_pct": (
        "D&A (% revenue)",
        style.PCT,
        0.05,
        "No depreciation & amortisation disclosed; assumed 5% of revenue (typical for an asset-moderate business).",
    ),
    "da_capex_pct": (
        "D&A (% of capex)",
        style.PCT,
        0.35,
        "No D&A disclosed; assumed 35% of total capex — depreciation trails the capex programme (house method for a growth-investing asset base).",
    ),
    "tax_rate": ("Tax rate", style.PCT, 0.25, "No tax expense disclosed; assumed 25% statutory effective rate."),
    "interest_rate": (
        "Cost of debt (interest %)",
        style.PCT,
        0.08,
        "No interest expense disclosed; assumed 8% cost of debt applied to the debt balance.",
    ),
    "nwc_pct": (
        "Change in NWC (% revenue)",
        style.PCT,
        0.03,
        "No working-capital movement disclosed; assumed a NWC outflow of 3% of revenue.",
    ),
    "capex_pct": (
        "Capex (% revenue)",
        style.PCT,
        0.05,
        "No capex disclosed; assumed 5% of revenue (maintenance + growth combined).",
    ),
    "maint_split": (
        "Maintenance capex (% of total)",
        style.PCT,
        0.65,
        "Split of total capex into maintenance vs growth; assumed 65% maintenance.",
    ),
    "repay_pct": (
        "Debt repayment (% opening debt)",
        style.PCT,
        0.0,
        "No mandatory amortisation disclosed; assumed 0% (debt held flat) in the forecast. Edit for a paydown schedule.",
    ),
}

# which section each assumption belongs to (and display order)
SECTIONS = [
    ("Income Statement", ["ebitda_margin", "da_pct", "da_capex_pct", "tax_rate", "interest_rate"]),
    ("Cash Flow", ["nwc_pct"]),
    ("Capex", ["capex_pct", "maint_split"]),
    ("Debt", ["repay_pct"]),
]


class Assumptions:
    """The Assumptions block, rendered INLINE at the top of the model sheet (not a separate tab).

    Each used driver is an editable yellow cell in the input column (col G) with a rationale comment;
    `ref(key)` returns a same-sheet absolute reference `$G$<row>` that the model formulas embed, so
    editing a driver on the page re-drives the whole model. Built via the ModelSheet reserve/render
    flow, so it must be called before `S.render()` and it participates in the two-phase layout.
    """

    def __init__(self, sheet):
        self.S = sheet
        self._row: dict[str, int] = {}
        self.overrides: dict[str, dict] = {}

    def build(self, keys: list[str], overrides: dict[str, dict]) -> None:
        """Reserve the Assumptions section: one editable row per used driver, grouped in SECTIONS
        order under a single header. `overrides` maps key -> {"value", "rationale"} from the JSON."""
        self.overrides = overrides or {}
        used = [k for k in keys if k in DEFAULTS]
        ordered = [k for _, sk in SECTIONS for k in sk if k in used]
        if not ordered:
            return
        self.S.section("Assumptions")
        self.S.spacer()
        for key in ordered:
            label, fmt, dval, drat = DEFAULTS[key]
            ov = overrides.get(key, {}) if overrides else {}
            value = ov.get("value", dval)
            rationale = ov.get("rationale") or drat
            prefix = "ASSUMED (default — review): " if "rationale" not in ov else "ASSUMED: "
            self._row[key] = self.S.line(
                f"asm_{key}", label=label, g=value, g_fmt=fmt, currency=False, comment=prefix + rationale
            )
        self.S.spacer(2)

    def ref(self, key: str) -> str:
        return f"$G${self._row[key]}"

    def has(self, key: str) -> bool:
        return key in self._row

    def seed(self, key: str) -> float:
        """The build-time default VALUE for a driver — the JSON override if given, else the
        catalogue default. Used to seed per-line reported-% driver rows for keys that are no
        longer rendered in the top Assumptions block (tax, interest, capex %, repay %, D&A %)."""
        ov = self.overrides.get(key, {})
        return ov.get("value", DEFAULTS[key][2])

    def rationale(self, key: str) -> str:
        """The rationale note for a driver's seed value (override text if given, else the default)."""
        ov = self.overrides.get(key, {})
        prefix = "ASSUMED: " if "rationale" in ov else "ASSUMED (default — review): "
        return prefix + (ov.get("rationale") or DEFAULTS[key][3])
