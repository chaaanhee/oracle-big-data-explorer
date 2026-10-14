"""Schema Map(ERD)·관계 탐색·전체 검색·유사 테이블."""

import difflib
import re
from collections import Counter, defaultdict, deque

from .dictionary import (
    all_foreign_keys,
    cached,
    display_type,
    objects,
    q,
    type_kind,
    visible_owner_names,
)

MAX_ERD_NODES = 120
MAX_NODE_COLUMNS = 60
GENERIC_KEY_COLUMNS = {
    "ID", "NO", "SEQ", "SN", "NAME", "NM", "CODE", "CD", "TYPE", "STATUS", "STAT", "USE_YN", "DEL_YN",
    "CREATED_AT", "UPDATED_AT", "REG_DT", "MOD_DT", "REG_ID", "MOD_ID", "DESCRIPTION", "REMARK", "SORT_ORD",
}


def _key(owner: str, table: str) -> str:
    return f"{owner}.{table}"


@cached
def owner_columns(owner: str) -> dict[str, list[dict]]:
    rows = q(
        """
        SELECT c.table_name AS table_name, c.column_name AS column_name, c.data_type AS data_type,
               c.data_length AS data_length, c.data_precision AS data_precision, c.data_scale AS data_scale,
               c.char_length AS char_length, c.nullable AS nullable, c.column_id AS column_id,
               cc.comments AS col_comment
        FROM all_tab_columns c
        LEFT JOIN all_col_comments cc
               ON cc.owner = c.owner AND cc.table_name = c.table_name AND cc.column_name = c.column_name
        WHERE c.owner = :owner
        ORDER BY c.table_name, c.column_id
        """,
        {"owner": owner},
    )
    out: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        out[r["table_name"]].append({
            "name": r["column_name"], "type": display_type(r), "kind": type_kind(r["data_type"]),
            "nullable": r["nullable"] == "Y", "comment": r["col_comment"],
        })
    return dict(out)


@cached
def owner_primary_keys(owner: str) -> dict[str, list[str]]:
    rows = q(
        """
        SELECT c.table_name AS table_name, cc.column_name AS column_name
        FROM all_constraints c
        JOIN all_cons_columns cc
             ON cc.owner = c.owner AND cc.constraint_name = c.constraint_name AND cc.table_name = c.table_name
        WHERE c.owner = :owner AND c.constraint_type = 'P'
        ORDER BY c.table_name, cc.position
        """,
        {"owner": owner},
    )
    out: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        out[r["table_name"]].append(r["column_name"])
    return dict(out)


def _node(owner: str, table: str, fks: list[dict], *, external: bool = False) -> dict:
    meta = next((o for o in objects(owner) if o["name"] == table), None) if owner in visible_owner_names() else None
    cols = owner_columns(owner).get(table, [])
    pk = set(owner_primary_keys(owner).get(table, []))
    fk_cols = {c for f in fks if f["from_owner"] == owner and f["from_table"] == table for c in f["from_columns"]}
    node_cols = [{**c, "pk": c["name"] in pk, "fk": c["name"] in fk_cols} for c in cols]
    return {
        "id": _key(owner, table),
        "owner": owner,
        "name": table,
        "type": meta["type"] if meta else "TABLE",
        "comment": meta["comment"] if meta else None,
        "num_rows": meta["num_rows"] if meta else None,
        "external": external,
        "column_count": len(node_cols),
        "columns": node_cols[:MAX_NODE_COLUMNS],
    }


def _edge(f: dict) -> dict:
    return {
        "id": f"{f['from_owner']}.{f['name']}",
        "name": f["name"],
        "source": _key(f["from_owner"], f["from_table"]),
        "target": _key(f["to_owner"], f["to_table"]),
        "from_columns": f["from_columns"],
        "to_columns": f["to_columns"],
        "cross_owner": f["from_owner"] != f["to_owner"],
    }


def owner_erd(owner: str, related_only: bool = True, limit: int = MAX_ERD_NODES) -> dict:
    fks = [f for f in all_foreign_keys() if f["from_owner"] == owner or f["to_owner"] == owner]
    tables = [o for o in objects(owner) if o["type"] == "TABLE"]
    degree = Counter()
    for f in fks:
        degree[_key(f["from_owner"], f["from_table"])] += 1
        degree[_key(f["to_owner"], f["to_table"])] += 1

    own = [t["name"] for t in tables if not related_only or degree[_key(owner, t["name"])]]
    own.sort(key=lambda n: (-degree[_key(owner, n)], n))
    truncated = len(own) > limit
    own = own[:limit]
    included = {_key(owner, n) for n in own}

    edges, external = [], set()
    for f in fks:
        s, t = _key(f["from_owner"], f["from_table"]), _key(f["to_owner"], f["to_table"])
        if s not in included and t not in included:
            continue
        for k, o, n in ((s, f["from_owner"], f["from_table"]), (t, f["to_owner"], f["to_table"])):
            if k not in included:
                if o == owner:
                    break
                external.add((o, n))
        else:
            edges.append(_edge(f))

    nodes = [_node(owner, n, fks) for n in own] + [_node(o, n, fks, external=True) for o, n in sorted(external)]
    return {
        "owner": owner,
        "nodes": nodes,
        "edges": edges,
        "total_tables": len(tables),
        "unrelated_tables": sum(1 for t in tables if not degree[_key(owner, t["name"])]),
        "truncated": truncated,
    }


def neighborhood(owner: str, table: str, depth: int = 1, limit: int = 40) -> dict:
    fks = all_foreign_keys()
    adj: dict[str, list[dict]] = defaultdict(list)
    for f in fks:
        adj[_key(f["from_owner"], f["from_table"])].append(f)
        adj[_key(f["to_owner"], f["to_table"])].append(f)

    start = _key(owner, table)
    seen = {start: 0}
    queue = deque([start])
    edges: dict[str, dict] = {}
    truncated = False
    while queue:
        cur = queue.popleft()
        if seen[cur] >= depth:
            continue
        for f in adj[cur]:
            s, t = _key(f["from_owner"], f["from_table"]), _key(f["to_owner"], f["to_table"])
            other = t if s == cur else s
            if other not in seen:
                if len(seen) >= limit:
                    truncated = True
                    continue
                seen[other] = seen[cur] + 1
                queue.append(other)
            edges[f"{f['from_owner']}.{f['name']}"] = f

    nodes = []
    for k, d in seen.items():
        o, n = k.split(".", 1)
        node = _node(o, n, fks, external=o != owner)
        node["depth"] = d
        nodes.append(node)
    return {
        "center": start,
        "depth": depth,
        "nodes": nodes,
        "edges": [_edge(f) for f in edges.values() if _key(f["from_owner"], f["from_table"]) in seen
                  and _key(f["to_owner"], f["to_table"]) in seen],
        "truncated": truncated,
    }


def owner_references() -> list[dict]:
    agg: dict[tuple, dict] = {}
    for f in all_foreign_keys():
        if f["from_owner"] == f["to_owner"]:
            continue
        a = agg.setdefault((f["from_owner"], f["to_owner"]), {
            "from_owner": f["from_owner"], "to_owner": f["to_owner"], "fk_count": 0, "examples": [],
        })
        a["fk_count"] += 1
        if len(a["examples"]) < 5:
            a["examples"].append(f"{f['from_table']} → {f['to_owner']}.{f['to_table']}")
    return sorted(agg.values(), key=lambda a: -a["fk_count"])


# --------------------------------------------------------------------------- search


def _pattern(text: str) -> str:
    esc = text.upper().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{esc}%"


SYSTEM_FILTER = "NOT IN (SELECT username FROM all_users WHERE oracle_maintained = 'Y')"


@cached
def all_table_names() -> list[tuple[str, str, str]]:
    visible = visible_owner_names()
    rows = q(
        f"""
        SELECT owner, object_name, object_type FROM all_objects
        WHERE object_type IN ('TABLE', 'VIEW') AND object_name NOT LIKE 'BIN$%' AND owner {SYSTEM_FILTER}
        """
    )
    return [(r["owner"], r["object_name"], r["object_type"]) for r in rows if r["owner"] in visible]


def search(text: str, kinds: set[str], owner: str | None, limit: int) -> dict:
    p = _pattern(text.strip())
    visible = visible_owner_names()
    owner_sql = " AND {col} = :owner" if owner else ""
    params = {"p": p, "lim": limit * 2, **({"owner": owner} if owner else {})}
    out: dict[str, list] = {}

    if "table" in kinds:
        rows = q(
            f"""
            SELECT o.owner AS owner, o.object_name AS name, o.object_type AS object_type, c.comments AS table_comment
            FROM all_objects o
            LEFT JOIN all_tab_comments c ON c.owner = o.owner AND c.table_name = o.object_name
            WHERE o.object_type IN ('TABLE', 'VIEW') AND o.object_name LIKE :p ESCAPE '\\'
              AND o.owner {SYSTEM_FILTER}{owner_sql.format(col='o.owner')}
            ORDER BY o.object_name
            FETCH FIRST :lim ROWS ONLY
            """,
            params,
        )
        out["tables"] = [
            {"owner": r["owner"], "name": r["name"], "type": r["object_type"], "comment": r["table_comment"]}
            for r in rows if r["owner"] in visible
        ][:limit]

    if "column" in kinds:
        rows = q(
            f"""
            SELECT c.owner AS owner, c.table_name AS table_name, c.column_name AS column_name,
                   c.data_type AS data_type, cc.comments AS col_comment
            FROM all_tab_columns c
            LEFT JOIN all_col_comments cc
                   ON cc.owner = c.owner AND cc.table_name = c.table_name AND cc.column_name = c.column_name
            WHERE c.column_name LIKE :p ESCAPE '\\' AND c.owner {SYSTEM_FILTER}{owner_sql.format(col='c.owner')}
            ORDER BY c.column_name, c.owner, c.table_name
            FETCH FIRST :lim ROWS ONLY
            """,
            params,
        )
        out["columns"] = [
            {"owner": r["owner"], "table": r["table_name"], "column": r["column_name"],
             "type": r["data_type"], "comment": r["col_comment"]}
            for r in rows if r["owner"] in visible
        ][:limit]

    if "comment" in kinds:
        t_rows = q(
            f"""
            SELECT owner, table_name, comments FROM all_tab_comments
            WHERE UPPER(comments) LIKE :p ESCAPE '\\' AND owner {SYSTEM_FILTER}{owner_sql.format(col='owner')}
            FETCH FIRST :lim ROWS ONLY
            """,
            params,
        )
        c_rows = q(
            f"""
            SELECT owner, table_name, column_name, comments FROM all_col_comments
            WHERE UPPER(comments) LIKE :p ESCAPE '\\' AND owner {SYSTEM_FILTER}{owner_sql.format(col='owner')}
            FETCH FIRST :lim ROWS ONLY
            """,
            params,
        )
        out["comments"] = (
            [{"owner": r["owner"], "table": r["table_name"], "column": None, "comment": r["comments"]}
             for r in t_rows if r["owner"] in visible]
            + [{"owner": r["owner"], "table": r["table_name"], "column": r["column_name"], "comment": r["comments"]}
               for r in c_rows if r["owner"] in visible]
        )[:limit]

    if "similar" in kinds:
        out["similar"] = similar_names(text.upper(), exclude=None, limit=15)
    return out


# --------------------------------------------------------------------------- similar / related

_TOKEN_NOISE = {"TB", "T", "TBL", "MST", "M", "INFO", "DATA", "BAK", "BACKUP", "OLD", "NEW", "TMP", "TEMP", "HIST", "V"}


def _tokens(name: str) -> set[str]:
    return {t for t in re.split(r"[_$#0-9]+", name.upper()) if t and t not in _TOKEN_NOISE}


def _score(a: str, b: str) -> float:
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    ta, tb = _tokens(a), _tokens(b)
    jac = len(ta & tb) / len(ta | tb) if ta and tb else 0
    contains = 0.15 if (a in b or b in a) and min(len(a), len(b)) >= 4 else 0
    return min(1.0, 0.55 * ratio + 0.45 * jac + contains)


def similar_names(name: str, exclude: tuple[str, str] | None, limit: int = 15) -> list[dict]:
    scored = []
    for owner, table, typ in all_table_names():
        if exclude and (owner, table) == exclude:
            continue
        s = _score(name, table)
        if s >= 0.45:
            scored.append({"owner": owner, "name": table, "type": typ, "score": round(s, 3)})
    scored.sort(key=lambda r: (-r["score"], r["name"]))
    return scored[:limit]


def related(owner: str, table: str) -> dict:
    fks = all_foreign_keys()
    direct = []
    for f in fks:
        if f["from_owner"] == owner and f["from_table"] == table:
            direct.append({"owner": f["to_owner"], "name": f["to_table"], "direction": "references",
                           "via": f"{', '.join(f['from_columns'])} → {', '.join(f['to_columns'])}", "constraint": f["name"]})
        elif f["to_owner"] == owner and f["to_table"] == table:
            direct.append({"owner": f["from_owner"], "name": f["from_table"], "direction": "referenced_by",
                           "via": f"{', '.join(f['from_columns'])} → {', '.join(f['to_columns'])}", "constraint": f["name"]})
    linked = {(d["owner"], d["name"]) for d in direct}

    cols = [c["name"] for c in owner_columns(owner).get(table, [])]
    pk = owner_primary_keys(owner).get(table, [])
    implicit = []
    visible = visible_owner_names()

    key_cols = [c for c in pk if c not in GENERIC_KEY_COLUMNS and len(c) > 3]
    if key_cols:
        binds = {f"c{i}": c for i, c in enumerate(key_cols)}
        rows = q(
            f"""
            SELECT owner, table_name, column_name FROM all_tab_columns
            WHERE column_name IN ({', '.join(':' + k for k in binds)}) AND owner {SYSTEM_FILTER}
            """,
            binds,
        )
        for r in rows:
            k = (r["owner"], r["table_name"])
            if k == (owner, table) or k in linked or r["owner"] not in visible:
                continue
            implicit.append({"owner": r["owner"], "name": r["table_name"], "direction": "maybe_referenced_by",
                             "via": f"{r['column_name']} 컬럼 공유 (FK 없음)"})

    candidates = [c for c in cols if c not in pk and c not in GENERIC_KEY_COLUMNS
                  and re.search(r"_(ID|CD|CODE|NO|KEY|SEQ)$", c)]
    if candidates:
        binds = {f"c{i}": c for i, c in enumerate(candidates[:200])}
        rows = q(
            f"""
            SELECT c.owner AS owner, c.table_name AS table_name, cc.column_name AS column_name
            FROM all_constraints c
            JOIN all_cons_columns cc
                 ON cc.owner = c.owner AND cc.constraint_name = c.constraint_name AND cc.table_name = c.table_name
            WHERE c.constraint_type = 'P' AND cc.column_name IN ({', '.join(':' + k for k in binds)})
              AND c.owner {SYSTEM_FILTER}
            """,
            binds,
        )
        for r in rows:
            k = (r["owner"], r["table_name"])
            if k == (owner, table) or k in linked or r["owner"] not in visible:
                continue
            implicit.append({"owner": r["owner"], "name": r["table_name"], "direction": "maybe_references",
                             "via": f"{r['column_name']} 가 상대 테이블의 기본키 컬럼명과 같음 (FK 없음)"})

    uniq, seen = [], set()
    for i in implicit:
        k = (i["owner"], i["name"], i["direction"])
        if k not in seen:
            seen.add(k)
            uniq.append(i)
    return {
        "foreign_keys": direct,
        "implicit": uniq[:50],
        "similar": similar_names(table, exclude=(owner, table)),
    }


# --------------------------------------------------------------------------- account


RISKY_PRIV = re.compile(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|EXECUTE|GRANT)\b.*\bANY\b|^(DBA|SYSDBA|SYSOPER)$")


def account_check(user: str) -> dict:
    findings = []
    try:
        privs = [r["privilege"] for r in q("SELECT privilege FROM session_privs")]
        risky = [p for p in privs if RISKY_PRIV.search(p)]
        if risky:
            findings.append({"level": "bad", "text": "시스템 쓰기 권한 보유: " + ", ".join(risky[:8])})
        roles = [r["role"] for r in q("SELECT role FROM session_roles")]
        if any(r in ("DBA", "RESOURCE", "IMP_FULL_DATABASE") for r in roles):
            findings.append({"level": "bad", "text": "강력한 롤 보유: " + ", ".join(roles)})
    except Exception:  # noqa: BLE001 - 권한 뷰 조회 실패는 점검 불가로만 표시한다
        findings.append({"level": "warn", "text": "SESSION_PRIVS 를 조회할 수 없어 권한 점검을 건너뜀"})
    owned = q("SELECT COUNT(*) AS cnt FROM all_objects WHERE owner = :u", {"u": user})[0]["cnt"]
    if owned:
        findings.append({"level": "warn", "text": f"접속 계정이 객체 {owned}개를 소유 (소유 객체는 수정 가능)"})
    dml = q(
        """
        SELECT COUNT(*) AS cnt FROM all_tab_privs
        WHERE grantee = :u AND privilege IN ('INSERT', 'UPDATE', 'DELETE', 'ALTER')
        """,
        {"u": user},
    )[0]["cnt"]
    if dml:
        findings.append({"level": "warn", "text": f"테이블 쓰기 권한 {dml}건 보유"})
    return {"read_only": not any(f["level"] == "bad" for f in findings) and not owned and not dml,
            "findings": findings}
