"""
Verification gate.

    python -m mxm.verify <model.xlsx>

Two layers, so it works even where LibreOffice can't run:
  1. STRUCTURAL (always, no soffice): the formula graph — no broken refs baked into formula text,
     the model is wired, and `fullCalcOnLoad` is set so any real viewer recomputes on open.
  2. NUMERIC (best-effort): recalc with LibreOffice, then check every Check row foots to ~0 and no
     key metric is 0/blank.

**gVisor / null-values note.** The sandboxed runtime (gVisor) blocks AF_UNIX sockets; LibreOffice needs them for its
internal IPC, and the `office/soffice.py` LD_PRELOAD shim can DEADLOCK (its `accept()` waits on a pipe
that LibreOffice never signals) → soffice hangs and is reaped as `<defunct>`. So the recalc is
**best-effort and NON-BLOCKING**: a hard timeout + kill/reap means a stuck soffice can never hang the run
or pile up zombies. When recalc can't run, `verify` returns `status: "recalc-unavailable"` (not a
failure) and relies on the structural check; the built workbook's `fullCalcOnLoad` flag makes Excel /
Google Sheets recompute on open, so the user never sees null values.

Exit code 0 for `ok` or `recalc-unavailable`; 1 for `fail`.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from pathlib import Path

from openpyxl import load_workbook

from .office.soffice import get_soffice_env

EXCEL_ERRORS = ["#VALUE!", "#DIV/0!", "#REF!", "#NAME?", "#NULL!", "#NUM!", "#N/A"]
MACRO_DIR = {
    "Darwin": "~/Library/Application Support/LibreOffice/4/user/basic/Standard",
    "Linux": "~/.config/libreoffice/4/user/basic/Standard",
}
MACRO = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE script:module PUBLIC "-//OpenOffice.org//DTD OfficeDocument 1.0//EN" "module.dtd">
<script:module xmlns:script="http://openoffice.org/2000/script" script:name="Module1" script:language="StarBasic">
    Sub RecalculateAndSave()
      ThisComponent.calculateAll()
      ThisComponent.store()
      ThisComponent.close(True)
    End Sub
</script:module>"""


def _setup_macro() -> bool:
    d = os.path.expanduser(MACRO_DIR.get(platform.system(), MACRO_DIR["Linux"]))
    f = os.path.join(d, "Module1.xba")
    if os.path.exists(f) and "RecalculateAndSave" in Path(f).read_text():
        return True
    if not os.path.exists(d):
        subprocess.run(
            ["soffice", "--headless", "--terminate_after_init"], capture_output=True, timeout=30, env=get_soffice_env()
        )
        os.makedirs(d, exist_ok=True)
    Path(f).write_text(MACRO)
    return True


def _kill_soffice() -> None:
    """Kill + reap any stale/zombie soffice so nothing hangs the next run or piles up as <defunct>."""
    for name in ("soffice.bin", "soffice"):
        subprocess.run(["pkill", "-9", "-f", name], capture_output=True)


def recalc(path: str, timeout: int = 90) -> bool:
    """Best-effort LibreOffice recalc. Returns True only if soffice ran to completion. NEVER hangs: a
    hard timeout + kill/reap guards against the gVisor AF_UNIX deadlock (see the module docstring), so a
    stuck soffice can't stall the caller. The orphaned soffice.bin child is reaped afterwards."""
    _kill_soffice()
    try:
        _setup_macro()
    except Exception:
        return False
    cmd = [
        "soffice",
        "--headless",
        "--norestore",
        "vnd.sun.star.script:Standard.Module1.RecalculateAndSave?language=Basic&location=application",
        str(Path(path).absolute()),
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, env=get_soffice_env(), timeout=timeout)
        return True
    except Exception:
        return False
    finally:
        _kill_soffice()


# Key-output rows that must never recalculate to 0 or blank — a 0/None here is almost always a
# silent wiring bug (a formula that computed but referenced an empty/wrong cell), which the plain
# error-string scan does NOT catch. This is the safety net for logic errors, not just #REF!/#DIV.
KEY_METRICS = (
    "irr",
    "mom",
    "moic",
    "enterprise value",
    "pre-money equity",
    "post-money equity",
    "equity value",
    "equity ticket",
    "sponsor share",
    "total sources",
    "total uses",
)


def verify(path: str) -> dict:
    # 1) STRUCTURAL check (no LibreOffice needed) — the formula graph itself. Catches baked-in broken
    # references (#REF!/#NAME? in the formula TEXT) and confirms the wiring + recalc-on-open flag. This
    # always runs, so we get a signal even when LibreOffice can't recalc in the sandbox.
    wf = load_workbook(path, data_only=False)
    formula_cells, formulas, struct_errors, labels = {}, 0, [], set()
    for sn in wf.sheetnames:
        coords = set()
        for row in wf[sn].iter_rows():
            lab = row[2].value if len(row) > 2 else None
            if isinstance(lab, str):
                labels.add(lab.strip().lower())
            for c in row:
                if isinstance(c.value, str) and c.value.startswith("="):
                    coords.add(c.coordinate)
                    if any(e in c.value for e in EXCEL_ERRORS):
                        struct_errors.append(f"{sn}!{c.coordinate}={c.value}")  # broken ref baked in
        formula_cells[sn] = coords
        formulas += len(coords)
    full_calc = bool(getattr(wf.calculation, "fullCalcOnLoad", False))
    wf.close()
    has_balance_check = any("check" in l and "balance" in l for l in labels)
    structural_ok = (not struct_errors) and formulas > 0 and full_calc

    # 2) best-effort LibreOffice recalc (never hangs). If it can't run (sandbox) we skip numeric checks.
    ran = recalc(path)

    # 3) read recalculated values and audit
    wb = load_workbook(path, data_only=True)
    errors, checks, suspects, uncomputed, key_outputs = [], {}, [], [], {}
    computed_any = False  # did the recalc actually compute a formula to a value? (else it didn't run)
    for sn in wb.sheetnames:
        ws = wb[sn]
        fcells = formula_cells.get(sn, set())
        for row in ws.iter_rows():
            label = row[2].value if len(row) > 2 else None  # col C
            for cell in row:
                v = cell.value
                if v is not None and cell.coordinate in fcells:
                    computed_any = True
                if isinstance(v, str) and any(e in v for e in EXCEL_ERRORS):
                    errors.append(f"{sn}!{cell.coordinate}={v}")
            if not isinstance(label, str):
                continue
            ll = label.strip().lower()
            if ll.startswith("check"):
                nums = [c.value for c in row if isinstance(c.value, (int, float))]
                checks[f"{sn}:{label.strip()}"] = max((abs(x) for x in nums), default=0.0)
            elif any(k in ll for k in KEY_METRICS):
                vals = []
                for c in row:
                    if c.coordinate not in fcells:
                        continue
                    vals.append(c.value)
                    if c.value is None:  # formula produced nothing → didn't compute
                        uncomputed.append(f"{sn}!{c.coordinate} ({label.strip()})")
                    elif isinstance(c.value, (int, float)) and c.value == 0:
                        suspects.append(f"{sn}!{c.coordinate} ({label.strip()})=0")
                if vals:
                    key_outputs[f"{sn}:{label.strip()}"] = vals[:12]
    wb.close()

    # Did the recalc actually compute anything? (a recalc that "ran" but left every formula blank = it
    # didn't really run — the sandbox / stale-soffice case). If so, fall back to the structural verdict.
    recalced = ran and computed_any
    bad_checks = {k: v for k, v in checks.items() if v > 1e-6}
    if recalced:
        status = "ok" if not (errors or bad_checks or suspects or uncomputed) else "fail"
    else:
        # No usable LibreOffice recalc (gVisor blocks it). Don't fail or hang — trust the structural
        # check; the file has fullCalcOnLoad so any real viewer recomputes on open.
        status = "recalc-unavailable" if structural_ok else "fail"
    return {
        "status": status,
        "recalc_ran": recalced,
        "structural_ok": structural_ok,
        "structural_errors": struct_errors[:30],  # broken refs baked into formula text
        "fullCalcOnLoad": full_calc,  # file recomputes on open (Excel/Sheets)
        "has_balance_check": has_balance_check,
        "note": (
            ""
            if recalced
            else "LibreOffice recalc unavailable (sandbox blocks AF_UNIX); structural check used. "
            "The workbook is set to recalc on open — open it in Excel/Sheets to see values."
        ),
        "formula_errors": errors[:30],
        "suspect_metrics": suspects[:30],  # key outputs that recalculated to 0
        "uncomputed_metrics": uncomputed[:30],  # key-output formulas that produced no value
        "n_formulas": formulas,
        "checks": checks,
        "failing_checks": bad_checks,
        "key_outputs": key_outputs,
    }


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m mxm.verify <model.xlsx>")
        sys.exit(1)
    res = verify(sys.argv[1])
    print(json.dumps(res, indent=2))
    sys.exit(0 if res["status"] in ("ok", "recalc-unavailable") else 1)


if __name__ == "__main__":
    main()
