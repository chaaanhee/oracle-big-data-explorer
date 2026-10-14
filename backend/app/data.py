"""테이블 데이터 조회: 검색·필터·정렬을 바인드 변수 SQL로 만들고, 필요한 페이지만 가져온다."""

import datetime as dt
from decimal import Decimal, InvalidOperation

from .dictionary import keys, object_info
from .executor import get_executor
from .schemas import Filter, RowQuery

COMPARE = {"eq": "=", "neq": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
LOB_PREVIEW_CHARS = 500


class QueryError(ValueError):
    pass


def qi(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def table_ref(owner: str, table: str) -> str:
    return f"{qi(owner)}.{qi(table)}"


def _like_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def convert(value: str, kind: str, column: str):
    v = value.strip()
    if kind == "number":
        try:
            return Decimal(v.replace(",", ""))
        except InvalidOperation:
            raise QueryError(f"'{column}' 은(는) 숫자 컬럼입니다: '{value}'")
    if kind == "date":
        try:
            return dt.datetime.fromisoformat(v.replace("/", "-"))
        except ValueError:
            raise QueryError(f"'{column}' 은(는) 날짜 컬럼입니다. 예: 2024-01-31 또는 2024-01-31 13:00:00")
    return v


def select_list(cols: list[dict]) -> str:
    ex = get_executor()
    parts = []
    for c in cols:
        col = qi(c["name"])
        if c["kind"] == "lob":
            parts.append(f"{ex.clob_preview(col, LOB_PREVIEW_CHARS)} AS {col}")
        elif c["data_type"] in ("LONG", "LONG RAW", "BFILE", "BLOB"):
            parts.append(f"NULL AS {col}")
        else:
            parts.append(col)
    return ", ".join(parts)


class Builder:
    def __init__(self):
        self.params: dict = {}
        self._n = 0

    def bind(self, value) -> str:
        name = f"p{self._n}"
        self._n += 1
        self.params[name] = value
        return f":{name}"


def _filter_sql(b: Builder, f: Filter, col: dict) -> str:
    c = qi(col["name"])
    kind = col["kind"]
    if f.op == "is_null":
        return f"{c} IS NULL"
    if f.op == "not_null":
        return f"{c} IS NOT NULL"
    if kind in ("lob", "opaque"):
        raise QueryError(f"'{col['name']}' ({col['type']}) 컬럼은 NULL 여부로만 필터할 수 있습니다.")
    if f.value is None or f.value.strip() == "":
        raise QueryError(f"'{col['name']}' 필터에 값을 입력하세요.")
    if f.op in COMPARE:
        return f"{c} {COMPARE[f.op]} {b.bind(convert(f.value, kind, col['name']))}"
    if f.op == "between":
        if not f.value2:
            raise QueryError(f"'{col['name']}' 범위 필터의 끝 값을 입력하세요.")
        lo = b.bind(convert(f.value, kind, col["name"]))
        hi = b.bind(convert(f.value2, kind, col["name"]))
        return f"{c} BETWEEN {lo} AND {hi}"
    if f.op == "in":
        values = [v for v in f.value.split(",") if v.strip()]
        if len(values) > 500:
            raise QueryError("IN 목록은 500개까지 입력할 수 있습니다.")
        return f"{c} IN ({', '.join(b.bind(convert(v, kind, col['name'])) for v in values)})"
    if kind != "text":
        raise QueryError(f"'{col['name']}' 은(는) 문자 컬럼이 아니라서 '{f.op}' 필터를 쓸 수 없습니다.")
    v = f.value.strip().lower()
    if f.op == "contains":
        return f"INSTR(LOWER({c}), {b.bind(v)}) > 0"
    if f.op == "not_contains":
        return f"({c} IS NULL OR INSTR(LOWER({c}), {b.bind(v)}) = 0)"
    if f.op == "starts_with":
        return f"LOWER({c}) LIKE {b.bind(_like_escape(v) + '%')} ESCAPE '\\'"
    if f.op == "ends_with":
        return f"LOWER({c}) LIKE {b.bind('%' + _like_escape(v))} ESCAPE '\\'"
    raise QueryError(f"지원하지 않는 연산자: {f.op}")


def build(owner: str, table: str, cols: list[dict], query: RowQuery, *, order: bool = True) -> tuple[str, dict]:
    by_name = {c["name"]: c for c in cols}
    b = Builder()
    where: list[str] = []

    search = (query.search or "").strip()
    if search:
        parts = [f"INSTR(LOWER({qi(c['name'])}), {b.bind(search.lower())}) > 0" for c in cols if c["kind"] == "text"]
        try:
            num = Decimal(search.replace(",", ""))
            parts += [f"{qi(c['name'])} = {b.bind(num)}" for c in cols if c["kind"] == "number"]
        except InvalidOperation:
            pass
        if not parts:
            raise QueryError("검색할 수 있는 문자/숫자 컬럼이 없습니다.")
        where.append("(" + " OR ".join(parts) + ")")

    for f in query.filters:
        if f.column not in by_name:
            raise QueryError(f"알 수 없는 컬럼: {f.column}")
        where.append(_filter_sql(b, f, by_name[f.column]))

    sql = f"SELECT {select_list(cols)} FROM {table_ref(owner, table)}"
    if where:
        sql += " WHERE " + " AND ".join(where)

    if order:
        order_by = []
        if query.sort:
            col = by_name.get(query.sort.column)
            if not col:
                raise QueryError(f"알 수 없는 정렬 컬럼: {query.sort.column}")
            if col["kind"] in ("lob", "opaque"):
                raise QueryError(f"'{col['name']}' ({col['type']}) 컬럼으로는 정렬할 수 없습니다.")
            direction = "DESC" if query.sort.direction == "desc" else "ASC"
            order_by.append(f"{qi(col['name'])} {direction} NULLS LAST")
        # 페이지 간 순서가 흔들리지 않도록 PK(없으면 ROWID)를 보조 정렬키로 쓴다.
        pk = keys(owner, table)["primary_key"]
        if pk:
            order_by += [qi(c) for c in pk["columns"] if not (query.sort and query.sort.column == c)]
        elif object_info(owner, table)["type"] == "TABLE":
            order_by.append("ROWID")
        if order_by:
            sql += " ORDER BY " + ", ".join(order_by)
    return sql, b.params


def page(owner: str, table: str, cols: list[dict], query: RowQuery, page_no: int, page_size: int):
    sql, params = build(owner, table, cols, query)
    params["off"] = (page_no - 1) * page_size
    params["lim"] = page_size + 1
    r = get_executor().query(sql + " OFFSET :off ROWS FETCH NEXT :lim ROWS ONLY", params)
    has_more = len(r.rows) > page_size
    return r.rows[:page_size], has_more, r.elapsed_ms


def count(owner: str, table: str, cols: list[dict], query: RowQuery, timeout: int):
    sql, params = build(owner, table, cols, query, order=False)
    r = get_executor().query(f"SELECT COUNT(*) AS cnt FROM ({sql}) t", params, timeout=timeout)
    return int(r.rows[0][0]), r.elapsed_ms
