import csv
import io
import json
import threading
import time
from contextlib import asynccontextmanager
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError

from . import data, dictionary, profiler, relations
from .config import settings
from .executor import DbError, QueryTimeout, close_executor, get_executor
from .schemas import RowQuery, RowsRequest, SqlRequest
from .serialize import rows_to_json, to_jsonable
from .sql_guard import SqlRejected, validate_select


@asynccontextmanager
async def lifespan(_: FastAPI):
    get_executor()
    yield
    close_executor()


app = FastAPI(title="Oracle Big Data Explorer API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_sql_slots = threading.BoundedSemaphore(settings.sql_concurrency)


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": message})


@app.exception_handler(dictionary.NotFound)
async def _not_found(_: Request, e: Exception):
    return _error(404, str(e))


@app.exception_handler(data.QueryError)
@app.exception_handler(SqlRejected)
async def _bad_request(_: Request, e: Exception):
    return _error(400, str(e))


@app.exception_handler(QueryTimeout)
async def _timeout(_: Request, e: Exception):
    return _error(408, str(e))


@app.exception_handler(DbError)
async def _db_error(_: Request, e: Exception):
    return _error(400, str(e))


def J(value):
    return JSONResponse(to_jsonable(value))


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


def _csv_response(chunks, filename: str, max_rows: int) -> StreamingResponse:
    """stream() 의 (컬럼, 배치...) 를 CSV 로 흘려보낸다. Excel 호환을 위해 UTF-8 BOM 을 붙인다."""
    header = next(chunks)

    def body():
        yield "\ufeff".encode()
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow([c["name"] for c in header])
        written = 0
        try:
            for batch in chunks:
                rows = batch[: max_rows - written]
                w.writerows([["" if v is None else to_jsonable(v) for v in r] for r in rows])
                written += len(rows)
                yield buf.getvalue().encode()
                buf.seek(0)
                buf.truncate()
                if written >= max_rows:
                    break
            yield buf.getvalue().encode()
        finally:
            chunks.close()

    return StreamingResponse(
        body(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=\"export.csv\"; filename*=UTF-8''{quote(filename)}"},
    )


# ------------------------------------------------------------------ 연결 정보


@app.get("/api/info")
def info():
    ex = get_executor()
    return J({
        "mode": ex.mode,
        "user": ex.user,
        **ex.server_info(),
        "limits": {
            "query_timeout_sec": settings.query_timeout_sec,
            "sql_max_rows": settings.sql_max_rows,
            "export_max_rows": settings.export_max_rows,
            "page_max_rows": settings.page_max_rows,
            "sql_concurrency": settings.sql_concurrency,
            "sample_target_rows": settings.sample_target_rows,
            "exact_profile_timeout_sec": settings.exact_profile_timeout_sec,
        },
        "account": relations.account_check(ex.user),
    })


@app.post("/api/cache/clear")
def clear_cache():
    dictionary.clear_cache()
    return {"ok": True}


# ------------------------------------------------------------------ ① Owner / Schema Explorer


@app.get("/api/owners")
def owners(include_system: bool = False):
    return J(dictionary.owners(include_system))


@app.get("/api/owners/{owner}/objects")
def owner_objects(owner: str):
    return J(dictionary.objects(owner))


@app.get("/api/owner-references")
def owner_references():
    return J(relations.owner_references())


# ------------------------------------------------------------------ ② Table Data Viewer


@app.get("/api/tables/{owner}/{table}")
def table_detail(owner: str, table: str):
    return J(dictionary.table_detail(owner, table))


@app.post("/api/tables/{owner}/{table}/rows")
def table_rows(owner: str, table: str, req: RowsRequest):
    if req.page_size > settings.page_max_rows:
        raise HTTPException(400, f"페이지 크기는 최대 {settings.page_max_rows}행입니다.")
    cols = dictionary.columns(owner, table)
    rows, has_more, elapsed = data.page(owner, table, cols, req, req.page, req.page_size)
    return J({
        "columns": cols,
        "rows": rows_to_json(rows),
        "page": req.page,
        "page_size": req.page_size,
        "has_more": has_more,
        "elapsed_ms": elapsed,
    })


@app.post("/api/tables/{owner}/{table}/count")
def table_count(owner: str, table: str, req: RowQuery):
    cols = dictionary.columns(owner, table)
    total, elapsed = data.count(owner, table, cols, req, settings.query_timeout_sec)
    return {"count": total, "elapsed_ms": elapsed}


@app.get("/api/tables/{owner}/{table}/export")
def table_export(owner: str, table: str, q: str = "{}"):
    try:
        query = RowQuery.model_validate(json.loads(q))
    except (json.JSONDecodeError, ValidationError) as e:
        raise HTTPException(400, f"잘못된 내보내기 조건: {e}")
    cols = dictionary.columns(owner, table)
    sql, params = data.build(owner, table, cols, query)
    chunks = get_executor().stream(sql, params)
    return _csv_response(chunks, f"{owner}.{table}.csv", settings.export_max_rows)


# ------------------------------------------------------------------ ③ SQL Workbench


@app.post("/api/sql")
def run_sql(req: SqlRequest):
    ex = get_executor()
    sql = validate_select(req.sql, demo=ex.mode == "demo")
    if not _sql_slots.acquire(timeout=5):
        raise HTTPException(429, f"동시 실행 가능한 쿼리 수({settings.sql_concurrency})를 초과했습니다. 잠시 후 다시 시도하세요.")
    try:
        r = ex.query(sql, max_rows=min(req.max_rows, settings.sql_max_rows))
    finally:
        _sql_slots.release()
    return J({
        "columns": r.columns,
        "rows": rows_to_json(r.rows),
        "row_count": len(r.rows),
        "truncated": r.truncated,
        "elapsed_ms": r.elapsed_ms,
    })


@app.get("/api/sql/export")
def export_sql(sql: str):
    ex = get_executor()
    checked = validate_select(sql, demo=ex.mode == "demo")
    return _csv_response(ex.stream(checked), "query_result.csv", settings.export_max_rows)


# ------------------------------------------------------------------ ④ Table Profiler


@app.get("/api/tables/{owner}/{table}/profile/metadata")
def profile_metadata(owner: str, table: str):
    return J(profiler.metadata(owner, table))


@app.post("/api/tables/{owner}/{table}/profile/{mode}")
def profile_scan(owner: str, table: str, mode: str):
    if mode not in ("sample", "exact"):
        raise HTTPException(404)
    return J(profiler.scan_profile(owner, table, mode))


@app.get("/api/tables/{owner}/{table}/distribution")
def distribution(owner: str, table: str, column: str, source: str = Query("sample", pattern="^(stats|sample)$")):
    try:
        return J(profiler.distribution(owner, table, column, source))
    except KeyError:
        raise HTTPException(404, f"컬럼 '{column}' 을(를) 찾을 수 없습니다.")


# ------------------------------------------------------------------ ⑤ Schema Map


@app.get("/api/owners/{owner}/erd")
def owner_erd(owner: str, related_only: bool = True, limit: int = Query(80, ge=1, le=300)):
    return J(relations.owner_erd(owner, related_only, limit))


@app.get("/api/tables/{owner}/{table}/neighborhood")
def neighborhood(owner: str, table: str, depth: int = Query(1, ge=1, le=3)):
    dictionary.object_info(owner, table)
    return J(relations.neighborhood(owner, table, depth))


# ------------------------------------------------------------------ ⑥ Global Search


@app.get("/api/search")
def search(q: str = Query(min_length=1), kinds: str = "table,column,comment,similar", owner: str | None = None,
           limit: int = Query(50, ge=1, le=200)):
    started = time.perf_counter()
    result = relations.search(q, set(kinds.split(",")), owner, limit)
    return J({**result, "elapsed_ms": _ms(started)})


@app.get("/api/tables/{owner}/{table}/related")
def related(owner: str, table: str):
    dictionary.object_info(owner, table)
    return J(relations.related(owner, table))


@app.get("/api/health")
def health():
    return {"ok": True}
