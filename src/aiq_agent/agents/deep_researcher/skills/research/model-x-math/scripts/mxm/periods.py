"""
Period axis for a Model X Math sheet.

Owns the time dimension: which columns hold which years, which are actual vs
forecast, and the letters used to build formulas. Deliberately tiny — the axis
is just column bookkeeping; ModelSheet does the writing.
"""

from __future__ import annotations

import calendar
import datetime as _dt

from openpyxl.utils import get_column_letter

from . import style


class PeriodAxis:
    def __init__(self, start_year: int, n_hist: int, n_forecast: int):
        assert n_hist >= 1 and n_forecast >= 0
        self.start_year = start_year
        self.n_hist = n_hist
        self.n_forecast = n_forecast
        self.n = n_hist + n_forecast
        self.years = [start_year + i for i in range(self.n)]
        self._col0 = style.COL_DATA0

    # ---- column mapping -----------------------------------------------------
    def col_idx(self, i: int) -> int:
        return self._col0 + i

    def col(self, i: int) -> str:
        return get_column_letter(self.col_idx(i))

    @property
    def cols(self) -> list[str]:
        return [self.col(i) for i in range(self.n)]

    @property
    def first_col_idx(self) -> int:
        return self._col0

    @property
    def last_col_idx(self) -> int:
        return self.col_idx(self.n - 1)

    def is_forecast(self, i: int) -> bool:
        return i >= self.n_hist

    @property
    def last_hist(self) -> int:
        return self.n_hist - 1

    @property
    def first_forecast(self) -> int:
        return self.n_hist

    def year_fmt(self, i: int) -> str:
        return style.YEAR_E if self.is_forecast(i) else style.YEAR_A

    def start_date(self, i: int) -> _dt.datetime:
        return _dt.datetime(self.years[i], 1, 1)

    def end_date(self, i: int) -> _dt.datetime:
        return _dt.datetime(self.years[i], 12, 31)

    def days(self, i: int) -> int:
        return 366 if calendar.isleap(self.years[i]) else 365
