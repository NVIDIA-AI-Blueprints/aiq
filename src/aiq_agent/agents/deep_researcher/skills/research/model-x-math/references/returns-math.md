# Returns math

How the Transaction Assumptions, Sources & Uses, and Returns blocks compute entry, exit,
IRR and MoM. Mirrors the house gold-standard deal layout.

## Entry

```
LTM EBITDA            = last historical EBITDA
Enterprise Value (EV) = LTM EBITDA × Entry Multiple
(-) Net Debt          = last historical Net Debt (Debt − Cash)
Pre-money Equity      = EV − Net Debt
```

## Sources & Uses

```
Uses          = EV (the purchase)
Net Debt      = the net debt funding the purchase
Total Equity  = Total Sources − Net Debt        (= EV − Net Debt = Pre-money Equity)
Check         = Total Sources − EV  →  must be 0
```

The **SPV** (the fund) does not buy the whole company — it takes a **stake**. Its equity
**ticket** is therefore `Total Equity × SPV stake`, and it receives `× SPV stake` of every
exit and dividend. Both sides must use the same stake or the return is meaningless.

## Exit (evaluated for each possible exit year)

```
Exit EV            = forecast EBITDA(year) × Exit Multiple   (Exit Multiple defaults to Entry)
Equity Value       = Exit EV − Debt(year) + Cash(year)
Equity Value to SPV = Equity Value × SPV stake
```

## Value-creation matrix → IRR / MoM

One row per candidate exit year `e`. Cash flows to the SPV, by column:

```
entry column (last historical year):  − (Total Equity × SPV stake)     [the ticket, an outflow]
interim forecast years  < e        :  + Dividends to SPV
exit year               = e        :  + Equity Value to SPV + Dividends to SPV
years                   > e        :  (blank)
```

A dates row (`DATE(year,12,31)` per column) accompanies the matrix. Then:

```
IRR(e) = XIRR( value-creation row , dates row )     wrapped in IFERROR(..,0)
MoM(e) = − Σ(inflows) / (entry outflow)             = total distributions ÷ ticket
```

IRR and MoM are shown across the exit-year columns in the light summary band, so the reader
can pick the exit year.

**Sanity-check the shape, don't memorise a number.** MoM should rise monotonically with a later exit
(more years of compounding + dividends); IRR is highest on a short mid-year first period and settles as
the hold lengthens. Reason about what drives the level for THIS deal: entry vs exit multiple (multiple
expansion/compression), leverage and deleveraging, EBITDA growth, and dividends. A flat-multiple,
modestly-levered buyout typically lands in the low-teens-to-twenties IRR with MoM climbing past ~1.5–2×
over a 5-year hold — but a high-growth or multiple-expansion deal runs hotter and a cash-cow dividend
recap looks different. If the number is implausible for the deal you modelled, a driver is wrong (an
entry that's all-equity, a stake mismatch, a phantom cash balance) — fix the driver, not the output.

## Common mistakes

- Using the **full** equity as the entry outflow while paying only the **stake** at exit →
  negative IRR. Both must be stake-adjusted.
- Referencing a row by hardcoded number instead of `S.rref(name)` → breaks when the block
  set changes.
- Introducing a circular reference (e.g. dividends that read post-dividend cash). Dividends
  read **pre-dividend** cash available.
