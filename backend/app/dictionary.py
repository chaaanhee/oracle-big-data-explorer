"""Oracle 데이터 딕셔너리(ALL_* 뷰) 조회.

ALL_* 뷰는 접속 계정이 접근 가능한 객체만 보여 주므로, 읽기 전용 계정에 SELECT 권한을 준 범위가 곧 탐색 범위가 된다.
대형 DB에서는 딕셔너리 조회도 느릴 수 있어 결과를 METADATA_CACHE_SEC 동안 캐시한다.
"""

import threading
import time
from collections import defaultdict
from functools import wraps

from .config import settings
from .executor import get_executor
from .serialize import records

CHAR_TYPES = {"VARCHAR2", "CHAR", "NVARCHAR2", "NCHAR", "VARCHAR"}
NUMBER_TYPES = {"NUMBER", "FLOAT", "INTEGER", "BINARY_DOUBLE", "BINARY_FLOAT"}
LOB_TYPES = {"CLOB", "NCLOB"}
OPAQUE_TYPES = {"BLOB", "BFILE", "RAW", "LONG RAW", "LONG", "XMLTYPE", "SDO_GEOMETRY", "ROWID", "UROWID"}


class NotFound(Exception):
    pass


def type_kind(data_type: str) -> str:
    t = (data_type or "").upper()
    if t in NUMBER_TYPES:
        return "number"
    if t == "DATE" or t.startswith("TIMESTAMP"):
        return "date"
    if t in CHAR_TYPES:
        return "text"
    if t in LOB_TYPES:
        return "lob"
    return "opaque"


def display_type(c: dict) -> str:
    t = c["data_type"]
    if t == "NUMBER" and c.get("data_precision") is not None:
        scale = c.get("data_scale") or 0
        return f"NUMBER({c['data_precision']}{',' + str(scale) if scale else ''})"
    if t in ("VARCHAR2", "NVARCHAR2", "CHAR", "NCHAR", "VARCHAR"):
        return f"{t}({c.get('char_length') or c.get('data_length')})"
    return t


# --------------------------------------------------------------------------- cache

_cache: dict = {}
_cache_lock = threading.Lock()


def cached(fn):
    @wraps(fn)
    def wrapper(*args):
        key = (fn.__name__, args)
        now = time.monotonic()
        with _cache_lock:
            hit = _cache.get(key)
            if hit and now - hit[0] < settings.metadata_cache_sec:
                return hit[1]
        value = fn(*args)
        with _cache_lock:
            _cache[key] = (now, value)
        return value

    return wrapper


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def q(sql: str, params: dict | None = None, timeout: int | None = None) -> list[dict]:
    r = get_executor().query(sql, params, timeout=timeout)
    return records(r.columns, r.rows)


# --------------------------------------------------------------------------- owners


def _owner_visible(owner: str, maintained: str | None) -> bool:
    if settings.include_owners:
        return owner in settings.include_owners
    if owner in settings.exclude_owners:
        return False
    return maintained != "Y"


@cached
def owners(include_system: bool = False) -> list[dict]:
    rows = q(
        """
        SELECT u.username AS owner, u.created AS created, u.oracle_maintained AS oracle_maintained,
               COALESCE(o.table_cnt, 0) AS table_cnt,
               COALESCE(o.view_cnt, 0) AS view_cnt,
               COALESCE(o.index_cnt, 0) AS index_cnt
        FROM all_users u
        LEFT JOIN (
            SELECT owner,
                   SUM(CASE WHEN object_type = 'TABLE' THEN 1 ELSE 0 END) AS table_cnt,
                   SUM(CASE WHEN object_type = 'VIEW' THEN 1 ELSE 0 END) AS view_cnt,
                   SUM(CASE WHEN object_type = 'INDEX' THEN 1 ELSE 0 END) AS index_cnt
            FROM all_objects
            WHERE object_type IN ('TABLE', 'VIEW', 'INDEX') AND object_name NOT LIKE 'BIN$%'
            GROUP BY owner
        ) o ON o.owner = u.username
        ORDER BY u.username
        """
    )
    out = []
    for r in rows:
        system = r["oracle_maintained"] == "Y"
        if not include_system and not _owner_visible(r["owner"], r["oracle_maintained"]):
            continue
        out.append({
            "owner": r["owner"],
            "created": r["created"],
            "system": system,
            "tables": int(r["table_cnt"]),
            "views": int(r["view_cnt"]),
            "indexes": int(r["index_cnt"]),
        })
    return out


def visible_owner_names() -> set[str]:
    return {o["owner"] for o in owners(False)}


@cached
def objects(owner: str) -> list[dict]:
    rows = q(
        """
        SELECT o.object_name AS name, o.object_type AS object_type, o.status AS status,
               o.created AS created, o.last_ddl_time AS last_ddl_time,
               t.num_rows AS num_rows, t.last_analyzed AS last_analyzed, c.comments AS table_comment
        FROM all_objects o
        LEFT JOIN all_tables t ON t.owner = o.owner AND t.table_name = o.object_name
        LEFT JOIN all_tab_comments c ON c.owner = o.owner AND c.table_name = o.object_name
        WHERE o.owner = :owner AND o.object_type IN ('TABLE', 'VIEW') AND o.object_name NOT LIKE 'BIN$%'
        ORDER BY o.object_name
        """,
        {"owner": owner},
    )
    idx = q(
        "SELECT table_name, COUNT(*) AS cnt FROM all_indexes WHERE table_owner = :owner GROUP BY table_name",
        {"owner": owner},
    )
    idx_count = {r["table_name"]: int(r["cnt"]) for r in idx}
    cols = q(
        "SELECT table_name, COUNT(*) AS cnt FROM all_tab_columns WHERE owner = :owner GROUP BY table_name",
        {"owner": owner},
    )
    col_count = {r["table_name"]: int(r["cnt"]) for r in cols}
    return [
        {
            "owner": owner,
            "name": r["name"],
            "type": r["object_type"],
            "status": r["status"],
            "created": r["created"],
            "last_ddl_time": r["last_ddl_time"],
            "num_rows": r["num_rows"],
            "last_analyzed": r["last_analyzed"],
            "comment": r["table_comment"],
            "indexes": idx_count.get(r["name"], 0),
            "columns": col_count.get(r["name"], 0),
        }
        for r in rows
    ]


# --------------------------------------------------------------------------- table detail


@cached
def columns(owner: str, table: str) -> list[dict]:
    rows = q(
        """
        SELECT c.column_id AS column_id, c.column_name AS column_name, c.data_type AS data_type,
               c.data_length AS data_length, c.data_precision AS data_precision, c.data_scale AS data_scale,
               c.char_length AS char_length, c.nullable AS nullable, c.data_default AS data_default,
               cc.comments AS col_comment
        FROM all_tab_columns c
        LEFT JOIN all_col_comments cc
               ON cc.owner = c.owner AND cc.table_name = c.table_name AND cc.column_name = c.column_name
        WHERE c.owner = :owner AND c.table_name = :name
        ORDER BY c.column_id
        """,
        {"owner": owner, "name": table},
    )
    if not rows:
        raise NotFound(f"{owner}.{table} 을(를) 찾을 수 없거나 조회 권한이 없습니다.")
    return [
        {
            "id": r["column_id"],
            "name": r["column_name"],
            "data_type": r["data_type"],
            "type": display_type(r),
            "kind": type_kind(r["data_type"]),
            "nullable": r["nullable"] == "Y",
            "default": (r["data_default"] or "").strip() or None,
            "comment": r["col_comment"],
        }
        for r in rows
    ]


FK_SQL = """
    SELECT fk.owner AS fk_owner, fk.table_name AS fk_table, fk.constraint_name AS fk_name,
           fkc.column_name AS fk_column, fkc.position AS position,
           pk.owner AS pk_owner, pk.table_name AS pk_table, pkc.column_name AS pk_column,
           fk.delete_rule AS delete_rule, fk.status AS status
    FROM all_constraints fk
    JOIN all_cons_columns fkc
         ON fkc.owner = fk.owner AND fkc.constraint_name = fk.constraint_name AND fkc.table_name = fk.table_name
    JOIN all_constraints pk ON pk.owner = fk.r_owner AND pk.constraint_name = fk.r_constraint_name
    JOIN all_cons_columns pkc
         ON pkc.owner = pk.owner AND pkc.constraint_name = pk.constraint_name
        AND pkc.table_name = pk.table_name AND pkc.position = fkc.position
    WHERE fk.constraint_type = 'R'
"""


def _group_fks(rows: list[dict]) -> list[dict]:
    grouped: dict[tuple, dict] = {}
    for r in sorted(rows, key=lambda r: (r["fk_owner"], r["fk_table"], r["fk_name"], r["position"])):
        key = (r["fk_owner"], r["fk_name"])
        e = grouped.setdefault(key, {
            "name": r["fk_name"],
            "from_owner": r["fk_owner"], "from_table": r["fk_table"], "from_columns": [],
            "to_owner": r["pk_owner"], "to_table": r["pk_table"], "to_columns": [],
            "delete_rule": r["delete_rule"], "status": r["status"],
        })
        e["from_columns"].append(r["fk_column"])
        e["to_columns"].append(r["pk_column"])
    return list(grouped.values())


@cached
def all_foreign_keys() -> list[dict]:
    """접근 가능한 전체 FK 목록. 관계 탐색(BFS)·ERD·Owner 간 참조 집계의 기반이 된다."""
    visible = visible_owner_names()
    return [
        fk for fk in _group_fks(q(FK_SQL, timeout=max(settings.query_timeout_sec, 120)))
        if fk["from_owner"] in visible or fk["to_owner"] in visible
    ]


@cached
def keys(owner: str, table: str) -> dict:
    rows = q(
        """
        SELECT c.constraint_name AS constraint_name, c.constraint_type AS constraint_type,
               c.status AS status, cc.column_name AS column_name, cc.position AS position
        FROM all_constraints c
        JOIN all_cons_columns cc
             ON cc.owner = c.owner AND cc.constraint_name = c.constraint_name AND cc.table_name = c.table_name
        WHERE c.owner = :owner AND c.table_name = :name AND c.constraint_type IN ('P', 'U')
        ORDER BY c.constraint_name, cc.position
        """,
        {"owner": owner, "name": table},
    )
    pk, uniques = None, {}
    for r in rows:
        if r["constraint_type"] == "P":
            pk = pk or {"name": r["constraint_name"], "columns": [], "status": r["status"]}
            pk["columns"].append(r["column_name"])
        else:
            u = uniques.setdefault(r["constraint_name"], {"name": r["constraint_name"], "columns": [], "status": r["status"]})
            u["columns"].append(r["column_name"])
    return {"primary_key": pk, "unique_keys": list(uniques.values())}


@cached
def indexes(owner: str, table: str) -> list[dict]:
    rows = q(
        """
        SELECT i.owner AS index_owner, i.index_name AS index_name, i.index_type AS index_type,
               i.uniqueness AS uniqueness, i.status AS status,
               ic.column_name AS column_name, ic.column_position AS column_position, ic.descend AS descend
        FROM all_indexes i
        JOIN all_ind_columns ic ON ic.index_owner = i.owner AND ic.index_name = i.index_name
        WHERE i.table_owner = :owner AND i.table_name = :name
        ORDER BY i.index_name, ic.column_position
        """,
        {"owner": owner, "name": table},
    )
    out: dict[str, dict] = {}
    for r in rows:
        ix = out.setdefault(r["index_name"], {
            "owner": r["index_owner"], "name": r["index_name"], "type": r["index_type"],
            "unique": r["uniqueness"] == "UNIQUE", "status": r["status"], "columns": [],
        })
        ix["columns"].append(r["column_name"] + (" DESC" if r["descend"] == "DESC" else ""))
    return list(out.values())


@cached
def object_info(owner: str, table: str) -> dict:
    rows = q(
        """
        SELECT o.object_type AS object_type, o.status AS status, o.created AS created,
               o.last_ddl_time AS last_ddl_time, c.comments AS table_comment
        FROM all_objects o
        LEFT JOIN all_tab_comments c ON c.owner = o.owner AND c.table_name = o.object_name
        WHERE o.owner = :owner AND o.object_name = :name AND o.object_type IN ('TABLE', 'VIEW')
        """,
        {"owner": owner, "name": table},
    )
    if not rows:
        raise NotFound(f"{owner}.{table} 을(를) 찾을 수 없거나 조회 권한이 없습니다.")
    r = rows[0]
    info = {
        "owner": owner, "name": table, "type": r["object_type"], "status": r["status"],
        "created": r["created"], "last_ddl_time": r["last_ddl_time"], "comment": r["table_comment"],
        "view_text": None,
    }
    if r["object_type"] == "VIEW":
        v = q("SELECT text FROM all_views WHERE owner = :owner AND view_name = :name", {"owner": owner, "name": table})
        info["view_text"] = v[0]["text"] if v else None
    return info


def table_detail(owner: str, table: str) -> dict:
    info = object_info(owner, table)
    cols = [dict(c) for c in columns(owner, table)]
    k = keys(owner, table)
    fks = all_foreign_keys()
    outgoing = [f for f in fks if f["from_owner"] == owner and f["from_table"] == table]
    incoming = [f for f in fks if f["to_owner"] == owner and f["to_table"] == table]
    pk_cols = set(k["primary_key"]["columns"]) if k["primary_key"] else set()
    fk_cols = defaultdict(list)
    for f in outgoing:
        for c, tc in zip(f["from_columns"], f["to_columns"]):
            fk_cols[c].append(f"{f['to_owner']}.{f['to_table']}.{tc}")
    for c in cols:
        c["pk"] = c["name"] in pk_cols
        c["fk"] = fk_cols.get(c["name"], [])
    return {
        **info,
        "columns": cols,
        **k,
        "foreign_keys": outgoing,
        "referenced_by": incoming,
        "indexes": indexes(owner, table),
    }
