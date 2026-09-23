# House style — the "Model X Math" look

Every token below is enforced centrally by `scripts/mxm/style.py`, extracted verbatim from
the firm's gold-standard reference models. You get this look automatically by using
the helper — this doc exists so you can recognise and preserve it, not re-implement it.

## Palette (explicit RGB — theme tints pre-resolved)

| Token | RGB | Where |
|---|---|---|
| Header band | `17375E` (navy) | units line `(in $m)` + the year row; white bold text |
| Section band | `D9D8D6` (grey) | section-header label, e.g. "Income Statement" |
| Summary band | `F2F2F2` (light grey) | IRR / MoM rows |
| Input font | `0000F4` (blue) | every hardcoded input |
| Input fill | `FFFFCC` (light yellow) | box behind *assumption* inputs (multiples, rates) |
| Body text | `323E48` (near-black) | default |

## Typography & grammar

- **Calibri 11** everywhere. **Gridlines off.**
- **Title** (row 2): bold, thin bottom border, `"<Company> - Model X Math"`.
- **Header labels** ("Start date", "End date", "Days per year"): italic.
- **Section header**: bold title on the grey band, with a literal **`x` in column B**.
- **Year row**: white bold on the navy band. Actual years use number format `#"A"` (→ `2025A`),
  forecast years `#"E"` (→ `2026E`). This is how actual vs forecast is signalled.
- **Totals / subtotals** (EV, EBITDA, EBIT, Net Profit, CFO…): **bold + thin top border** on
  both the label and the data cells.
- **Inputs**: blue. A seeded P&L actual (Revenue/EBITDA) is blue **bold**, no fill. An
  *assumption* (entry multiple, tax %, interest %, capex split) is blue **italic** + yellow
  fill + a hair-line box, placed in **column G** for scalars.
- **% sub-rows** (% Growth, % Margin, % of Revenue): italic label, percent format.

## Number formats (exact)

| Kind | Format string |
|---|---|
| value, 1 dp | `#,##0.0;\(#,##0.0\);\-\-` |
| value, 0 dp | `#,##0;\(#,##0\);\-\-` |
| multiple | `#,##0.0\x_);\(#,##0.0\x\);\-\-_)` |
| percent | `0.0%_);\(0.0%\);0.0%_);@_)` |
| IRR | `0.0%` |

Negatives render in parentheses; zeros render as `--`. Multiples carry a trailing `x` (`10.0x`).

## Geometry

Column A ≈ 4.5 (left margin), B narrow (the `x`), C ≈ 32 (labels), G ≈ 9 (scalar inputs),
data columns ≈ 12.5, starting at column **I**. Do not move these — cross-block formulas and
the point-in-time blocks (Entry, Sources) assume column I is the first data column.
