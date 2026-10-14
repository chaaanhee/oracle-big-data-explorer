"""DB 실행 계층. Oracle(python-oracledb thin)과 데모용 DuckDB를 같은 인터페이스로 감싼다.

모든 내부 SQL은 Oracle 문법과 `:name` 바인드 변수로 작성하고, 데모(DuckDB)에서는 바인드 표기만 `$name`으로 바꿔 실행한다.
"""

import re
import threading
import time
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

import duckdb
import oracledb

from .config import settings

oracledb.defaults.fetch_lobs = False


class QueryTimeout(Exception):
    pass


class DbError(Exception):
    pass


@dataclass
class Result:
    columns: list[dict]
    rows: list[tuple]
    truncated: bool = False
    elapsed_ms: float = 0.0


class Executor(ABC):
    mode: str
    user: str

    @abstractmethod
    def query(self, sql: str, params: dict | None = None, *, max_rows: int | None = None,
              timeout: int | None = None) -> Result: ...

    @abstractmethod
    def stream(self, sql: str, params: dict | None = None, *, timeout: int | None = None,
               batch: int = 5000) -> Iterator[Any]:
        """첫 번째로 컬럼 목록을, 이후 행 배치를 yield 한다."""

    @abstractmethod
    def sample_from(self, table_ref: str, pct: float) -> str: ...

    @abstractmethod
    def days_between(self, col: str, lo_param: str) -> str:
        """날짜 컬럼과 기준 시각(바인드) 사이의 일수 표현식."""

    @abstractmethod
    def clob_preview(self, col: str, length: int) -> str: ...

    @abstractmethod
    def server_info(self) -> dict: ...

    def close(self) -> None:
        pass


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


# --------------------------------------------------------------------------- Oracle


def _oracle_columns(description) -> list[dict]:
    cols = []
    for d in description or []:
        type_name = getattr(d.type_code, "name", str(d.type_code)).replace("DB_TYPE_", "")
        cols.append({"name": d.name, "type": type_name})
    return cols


class OracleExecutor(Executor):
    mode = "oracle"

    def __init__(self):
        self.user = settings.oracle_user.upper()
        self.pool = oracledb.create_pool(
            user=settings.oracle_user,
            password=settings.oracle_password,
            dsn=settings.oracle_dsn,
            min=1,
            max=settings.pool_max,
            increment=1,
            getmode=oracledb.POOLGETMODE_TIMEDWAIT,
            wait_timeout=10_000,
        )

    @contextmanager
    def _cursor(self, timeout: int | None):
        conn = self.pool.acquire()
        try:
            conn.call_timeout = int((timeout or settings.query_timeout_sec) * 1000)
            cur = conn.cursor()
            # 계정이 쓰기 권한을 갖고 있더라도 이 트랜잭션 안에서는 DML이 거부된다.
            cur.execute("SET TRANSACTION READ ONLY")
            yield cur
        except oracledb.DatabaseError as e:
            msg = str(e)
            if "DPI-1067" in msg or "ORA-03156" in msg:
                raise QueryTimeout(f"실행 시간 제한({timeout or settings.query_timeout_sec}초)을 초과했습니다.") from e
            raise DbError(msg) from e
        finally:
            try:
                conn.rollback()
            except oracledb.Error:
                pass
            self.pool.release(conn)

    def query(self, sql, params=None, *, max_rows=None, timeout=None) -> Result:
        started = time.perf_counter()
        with self._cursor(timeout) as cur:
            if max_rows:
                cur.arraysize = min(max_rows + 1, 2000)
                cur.prefetchrows = cur.arraysize + 1
            cur.execute(sql, params or {})
            columns = _oracle_columns(cur.description)
            if max_rows:
                rows = cur.fetchmany(max_rows + 1)
                truncated = len(rows) > max_rows
                rows = rows[:max_rows]
            else:
                rows, truncated = cur.fetchall(), False
        return Result(columns, rows, truncated, _ms(started))

    def stream(self, sql, params=None, *, timeout=None, batch=5000):
        with self._cursor(timeout or settings.export_timeout_sec) as cur:
            cur.arraysize = batch
            cur.execute(sql, params or {})
            yield _oracle_columns(cur.description)
            while rows := cur.fetchmany(batch):
                yield rows

    def sample_from(self, table_ref, pct):
        return f"{table_ref} SAMPLE ({pct:.6f}) SEED (7)"

    def days_between(self, col, lo_param):
        return f"(CAST({col} AS DATE) - CAST({lo_param} AS DATE))"

    def clob_preview(self, col, length):
        return f"DBMS_LOB.SUBSTR({col}, {int(length)}, 1)"

    def server_info(self):
        with self.pool.acquire() as conn:
            return {"version": conn.version, "dsn": settings.oracle_dsn}

    def close(self):
        self.pool.close(force=True)


# --------------------------------------------------------------------------- DuckDB (demo)

_BIND = re.compile(r"(?<![:\w$]):([A-Za-z_]\w*)")


class DuckExecutor(Executor):
    mode = "demo"

    def __init__(self, path: str):
        self.user = "APP_READER"
        self._con = duckdb.connect(path, read_only=True)
        self._lock = threading.Lock()

    @contextmanager
    def _cursor(self, timeout: int | None):
        cur = self._con.cursor()
        limit = timeout or settings.query_timeout_sec
        timer = threading.Timer(limit, cur.interrupt)
        timer.start()
        try:
            yield cur
        except duckdb.InterruptException as e:
            raise QueryTimeout(f"실행 시간 제한({limit}초)을 초과했습니다.") from e
        except duckdb.Error as e:
            raise DbError(str(e)) from e
        finally:
            timer.cancel()
            cur.close()

    @staticmethod
    def _sql(sql: str, params: dict | None) -> str:
        return _BIND.sub(r"$\1", sql) if params else sql

    def query(self, sql, params=None, *, max_rows=None, timeout=None) -> Result:
        started = time.perf_counter()
        with self._cursor(timeout) as cur:
            cur.execute(self._sql(sql, params), params or None)
            columns = [{"name": d[0], "type": str(d[1])} for d in cur.description or []]
            if max_rows:
                rows = cur.fetchmany(max_rows + 1)
                truncated = len(rows) > max_rows
                rows = rows[:max_rows]
            else:
                rows, truncated = cur.fetchall(), False
        return Result(columns, rows, truncated, _ms(started))

    def stream(self, sql, params=None, *, timeout=None, batch=5000):
        with self._cursor(timeout or settings.export_timeout_sec) as cur:
            cur.execute(self._sql(sql, params), params or None)
            yield [{"name": d[0], "type": str(d[1])} for d in cur.description or []]
            while rows := cur.fetchmany(batch):
                yield rows

    def sample_from(self, table_ref, pct):
        return f"{table_ref} TABLESAMPLE {pct:.6f} PERCENT (bernoulli, 7)"

    def days_between(self, col, lo_param):
        return f"(date_diff('second', CAST({lo_param} AS TIMESTAMP), CAST({col} AS TIMESTAMP)) / 86400.0)"

    def clob_preview(self, col, length):
        return f"substr({col}, 1, {int(length)})"

    def server_info(self):
        return {"version": f"DuckDB {duckdb.__version__} (Oracle 딕셔너리 에뮬레이션)", "dsn": str(settings.demo_db)}

    def close(self):
        self._con.close()


_executor: Executor | None = None


def get_executor() -> Executor:
    global _executor
    if _executor is None:
        if settings.oracle_enabled:
            _executor = OracleExecutor()
        else:
            from .demo_setup import ensure_demo_db

            ensure_demo_db(settings.demo_db)
            _executor = DuckExecutor(str(settings.demo_db))
    return _executor


def close_executor() -> None:
    global _executor
    if _executor is not None:
        _executor.close()
        _executor = None
