from typing import Literal

from pydantic import BaseModel, Field

FilterOp = Literal[
    "eq", "neq", "gt", "gte", "lt", "lte",
    "contains", "not_contains", "starts_with", "ends_with",
    "in", "between", "is_null", "not_null",
]


class Filter(BaseModel):
    column: str
    op: FilterOp
    value: str | None = None
    value2: str | None = None


class Sort(BaseModel):
    column: str
    direction: Literal["asc", "desc"] = "asc"


class RowQuery(BaseModel):
    search: str | None = None
    filters: list[Filter] = Field(default_factory=list)
    sort: Sort | None = None


class RowsRequest(RowQuery):
    page: int = Field(1, ge=1)
    page_size: int = Field(100, ge=1, le=1000)


class SqlRequest(BaseModel):
    sql: str = Field(max_length=200_000)
    max_rows: int = Field(1000, ge=1)
