"""테이블 프로파일링.

결과마다 출처(source)를 붙인다.
- metadata : 데이터 딕셔너리 (객체 정보, 세그먼트 크기, 변경 이력) — 비용 거의 없음
- stats    : 옵티마이저 통계 (ALL_TAB_COL_STATISTICS, 히스토그램) — 마지막 수집 시점 기준
- sample   : SAMPLE 절로 일부 행만 읽어 계산 — 근사치
- exact    : 전체 스캔 — 정확하지만 비용이 크다
"""

import datetime as dt
import time

from .config import settings
from .data import qi, table_ref
from .dictionary import columns, indexes, keys, object_info, q
from .executor import DbError, get_executor
from .oracle_raw import decode_raw, histogram_endpoint
from .serialize import to_jsonable

ASSUMED_BLOCK_SIZE = 8192
GENERIC_COLUMNS_PER_QUERY = 150


def _now() -> dt.datetime:
    return dt.datetime.now()


def _days_since(t) -> float | None:
    if not isinstance(t, dt.datetime):
        return None
    return round((_now() - t).total_seconds() / 86400, 1)


def _table_stats(owner: str, table: str) -> dict | None:
    rows = q(
        """
        SELECT t.num_rows AS num_rows, t.blocks AS blocks, t.empty_blocks AS empty_blocks,
               t.avg_row_len AS avg_row_len, t.sample_size AS sample_size, t.last_analyzed AS last_analyzed,
               t.partitioned AS partitioned, t.compression AS compression, t.tablespace_name AS tablespace_name
        FROM all_tables t WHERE t.owner = :owner AND t.table_name = :name
        """,
        {"owner": owner, "name": table},
    )
    return rows[0] if rows else None


def _segment_size(owner: str, table: str, stats: dict | None) -> dict:
    try:
        rows = q(
            "SELECT SUM(bytes) AS bytes FROM dba_segments WHERE owner = :owner AND segment_name = :name",
            {"owner": owner, "name": table},
        )
        if rows and rows[0]["bytes"] is not None:
            return {"bytes": int(rows[0]["bytes"]), "source": "metadata", "note": "DBA_SEGMENTS 할당 크기"}
    except DbError:
        pass
    if stats and stats.get("blocks"):
        return {
            "bytes": int(stats["blocks"]) * ASSUMED_BLOCK_SIZE,
            "source": "stats",
            "note": "DBA_SEGMENTS 권한이 없어 통계의 BLOCKS × 8KB 로 추정",
        }
    return {"bytes": None, "source": None, "note": "크기 정보를 조회할 권한이나 통계가 없습니다"}


def metadata(owner: str, table: str) -> dict:
    started = time.perf_counter()
    info = object_info(owner, table)
    cols = columns(owner, table)
    stats = _table_stats(owner, table)

    stale = q(
        """
        SELECT stale_stats, stattype_locked FROM all_tab_statistics
        WHERE owner = :owner AND table_name = :name AND object_type = 'TABLE'
        """,
        {"owner": owner, "name": table},
    )
    mods = q(
        """
        SELECT inserts, updates, deletes, truncated, "TIMESTAMP" AS modified_at FROM all_tab_modifications
        WHERE table_owner = :owner AND table_name = :name AND partition_name IS NULL
        """,
        {"owner": owner, "name": table},
    )
    col_stats = {
        r["column_name"]: r
        for r in q(
            """
            SELECT column_name, num_distinct, num_nulls, density, low_value, high_value, histogram,
                   num_buckets, sample_size, last_analyzed, avg_col_len
            FROM all_tab_col_statistics WHERE owner = :owner AND table_name = :name
            """,
            {"owner": owner, "name": table},
        )
    }

    num_rows = stats["num_rows"] if stats else None
    out_cols = []
    for c in cols:
        s = col_stats.get(c["name"])
        entry = {k: c[k] for k in ("name", "type", "data_type", "kind", "nullable", "comment")}
        if s and s["last_analyzed"] is not None:
            nulls = s["num_nulls"]
            entry.update({
                "num_distinct": s["num_distinct"],
                "num_nulls": nulls,
                "null_ratio": (nulls / num_rows) if (num_rows and nulls is not None) else None,
                "low": to_jsonable(decode_raw(s["low_value"], c["data_type"])),
                "high": to_jsonable(decode_raw(s["high_value"], c["data_type"])),
                "density": s["density"],
                "histogram": s["histogram"],
                "num_buckets": s["num_buckets"],
                "sample_size": s["sample_size"],
                "last_analyzed": s["last_analyzed"],
                "avg_col_len": s["avg_col_len"],
            })
        out_cols.append(entry)

    mod = mods[0] if mods else None
    table_part = {
        "type": info["type"],
        "status": info["status"],
        "created": info["created"],
        "last_ddl_time": info["last_ddl_time"],
        "num_rows": num_rows,
        "blocks": stats["blocks"] if stats else None,
        "avg_row_len": stats["avg_row_len"] if stats else None,
        "sample_size": stats["sample_size"] if stats else None,
        "last_analyzed": stats["last_analyzed"] if stats else None,
        "stats_age_days": _days_since(stats["last_analyzed"]) if stats else None,
        "stale_stats": stale[0]["stale_stats"] if stale else None,
        "stats_locked": bool(stale and stale[0]["stattype_locked"]),
        "partitioned": stats["partitioned"] == "YES" if stats else False,
        "compression": stats["compression"] if stats else None,
        "tablespace": stats["tablespace_name"] if stats else None,
        "size": _segment_size(owner, table, stats) if info["type"] == "TABLE" else None,
        "modifications": {
            "inserts": mod["inserts"], "updates": mod["updates"], "deletes": mod["deletes"],
            "truncated": mod["truncated"] == "YES", "timestamp": mod["modified_at"],
        } if mod else None,
    }
    return {
        "table": table_part,
        "columns": out_cols,
        "quality": quality(owner, table, info, table_part, out_cols),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
    }


def quality(owner: str, table: str, info: dict, t: dict, cols: list[dict]) -> list[dict]:
    out: list[dict] = []

    def add(level, title, detail, source):
        out.append({"level": level, "title": title, "detail": detail, "source": source})

    if info["status"] != "VALID":
        add("bad", "객체 상태", f"객체 상태가 {info['status']} 입니다.", "metadata")

    if info["type"] == "TABLE":
        if t["last_analyzed"] is None:
            add("bad", "옵티마이저 통계", "통계가 수집된 적이 없습니다. 행 수·분포 정보가 없어 실행 계획 품질도 떨어질 수 있습니다.", "stats")
        else:
            age = t["stats_age_days"] or 0
            level = "warn" if age > 30 or t["stale_stats"] == "YES" else "ok"
            stale = " · Oracle이 STALE 로 표시" if t["stale_stats"] == "YES" else ""
            add(level, "통계 신선도", f"마지막 수집 {age:.0f}일 전{stale}", "stats")
        m = t["modifications"]
        if m and t["num_rows"]:
            changed = (m["inserts"] or 0) + (m["updates"] or 0) + (m["deletes"] or 0)
            ratio = changed / t["num_rows"]
            add("warn" if ratio > 0.1 else "ok", "통계 이후 변경량",
                f"수집 이후 {changed:,}건 변경 (통계 행 수 대비 {ratio:.1%})", "metadata")

        pk = keys(owner, table)["primary_key"]
        if not pk:
            add("warn", "기본키", "기본키가 없습니다. 중복 행 식별과 관계 추적이 어렵습니다.", "metadata")
        elif pk["status"] != "ENABLED":
            add("warn", "기본키", f"기본키 제약이 {pk['status']} 상태입니다.", "metadata")

        unusable = [i["name"] for i in indexes(owner, table) if i["status"] not in ("VALID", "N/A")]
        if unusable:
            add("bad", "인덱스 상태", "사용 불가(UNUSABLE) 인덱스: " + ", ".join(unusable), "metadata")

    if not info["comment"]:
        add("warn", "테이블 설명", "테이블 주석(COMMENT)이 없습니다.", "metadata")
    commented = sum(1 for c in cols if c.get("comment"))
    ratio = commented / len(cols) if cols else 1
    add("ok" if ratio >= 0.9 else "warn" if ratio >= 0.5 else "bad", "컬럼 설명",
        f"{commented}/{len(cols)}개 컬럼에 주석이 있습니다 ({ratio:.0%})", "metadata")

    with_stats = [c for c in cols if c.get("null_ratio") is not None]
    if with_stats:
        all_null = [c["name"] for c in with_stats if c["null_ratio"] >= 0.999]
        high_null = [c["name"] for c in with_stats if 0.5 <= c["null_ratio"] < 0.999]
        constant = [c["name"] for c in with_stats if c.get("num_distinct") == 1]
        if all_null:
            add("bad", "값이 없는 컬럼", ", ".join(all_null), "stats")
        if high_null:
            add("warn", "NULL 50% 이상 컬럼", ", ".join(high_null), "stats")
        if constant:
            add("info", "단일 값 컬럼", ", ".join(constant), "stats")
        if not (all_null or high_null):
            add("ok", "NULL 비율", "NULL 이 50% 이상인 컬럼이 없습니다.", "stats")
    return out


# --------------------------------------------------------------------------- sample / exact


def _source(owner: str, table: str, mode: str) -> tuple[str, dict]:
    """프로파일 대상 FROM 절과 그 방식을 설명하는 메타 정보를 만든다."""
    ex = get_executor()
    ref = table_ref(owner, table)
    info = object_info(owner, table)
    stats = _table_stats(owner, table)
    num_rows = stats["num_rows"] if stats else None
    target = settings.sample_target_rows

    if mode == "exact":
        return ref, {"mode": "exact", "label": "전체 스캔", "estimated_rows": num_rows}
    if info["type"] == "TABLE" and num_rows and num_rows > target:
        pct = min(max(target / num_rows * 100, 0.000001), 99.999999)
        return f"(SELECT * FROM {ex.sample_from(ref, pct)})", {
            "mode": "sample", "label": f"무작위 행 샘플 약 {pct:.4g}% (목표 {target:,}행, SEED 고정)",
            "percent": pct, "estimated_rows": num_rows,
        }
    if info["type"] == "TABLE" and num_rows is not None:
        return ref, {"mode": "sample", "label": f"통계상 {num_rows:,}행으로 작아 전체를 읽음", "estimated_rows": num_rows}
    return f"(SELECT * FROM {ref} FETCH FIRST {target} ROWS ONLY)", {
        "mode": "sample",
        "label": f"앞부분 {target:,}행 (통계가 없거나 뷰라서 무작위 샘플이 아님)",
        "estimated_rows": num_rows,
    }


def scan_profile(owner: str, table: str, mode: str) -> dict:
    started = time.perf_counter()
    cols = [c for c in columns(owner, table) if c["kind"] != "opaque"]
    src, source = _source(owner, table, mode)
    timeout = settings.exact_profile_timeout_sec if mode == "exact" else settings.query_timeout_sec
    ex = get_executor()

    results: dict[str, dict] = {}
    scanned = None
    for start in range(0, max(len(cols), 1), GENERIC_COLUMNS_PER_QUERY):
        chunk = cols[start:start + GENERIC_COLUMNS_PER_QUERY]
        exprs = ["COUNT(*) AS n"]
        for i, c in enumerate(chunk):
            col = qi(c["name"])
            exprs.append(f"COUNT({col}) AS nn{i}")
            if c["kind"] == "lob":
                continue
            distinct = f"COUNT(DISTINCT {col})" if mode == "exact" else f"APPROX_COUNT_DISTINCT({col})"
            exprs += [f"{distinct} AS d{i}", f"MIN({col}) AS mn{i}", f"MAX({col}) AS mx{i}"]
        r = ex.query(f"SELECT {', '.join(exprs)} FROM {src} s", timeout=timeout)
        row = dict(zip([c["name"].lower() for c in r.columns], r.rows[0]))
        scanned = int(row["n"])
        for i, c in enumerate(chunk):
            nn = int(row[f"nn{i}"])
            entry = {"non_null": nn, "nulls": scanned - nn, "null_ratio": (scanned - nn) / scanned if scanned else None}
            if c["kind"] != "lob":
                d = row.get(f"d{i}")
                entry.update({
                    "distinct": int(d) if d is not None else None,
                    "distinct_ratio": (int(d) / nn) if (d is not None and nn) else None,
                    "min": to_jsonable(row.get(f"mn{i}")),
                    "max": to_jsonable(row.get(f"mx{i}")),
                })
            results[c["name"]] = entry

    return {
        "source": source,
        "rows_scanned": scanned,
        "columns": results,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
    }


# --------------------------------------------------------------------------- distribution


def distribution(owner: str, table: str, column: str, source: str, bins: int = 20, top: int = 20) -> dict:
    col = next((c for c in columns(owner, table) if c["name"] == column), None)
    if not col:
        raise KeyError(column)
    if source == "stats":
        return _stats_histogram(owner, table, col)
    return _sample_distribution(owner, table, col, bins, top)


def _stats_histogram(owner: str, table: str, col: dict) -> dict:
    meta = q(
        """
        SELECT histogram, num_buckets, sample_size, last_analyzed FROM all_tab_col_statistics
        WHERE owner = :owner AND table_name = :name AND column_name = :col
        """,
        {"owner": owner, "name": table, "col": col["name"]},
    )
    kind = meta[0]["histogram"] if meta else None
    base = {"source": "stats", "column": col["name"], "histogram": kind}
    if not kind or kind == "NONE":
        return {**base, "kind": "none", "reason": "이 컬럼에는 수집된 히스토그램이 없습니다. 샘플 분포를 확인하세요."}
    rows = q(
        """
        SELECT endpoint_number, endpoint_value, endpoint_actual_value FROM all_tab_histograms
        WHERE owner = :owner AND table_name = :name AND column_name = :col
        ORDER BY endpoint_number
        """,
        {"owner": owner, "name": table, "col": col["name"]},
    )
    out, prev = [], 0
    for r in rows:
        n = int(r["endpoint_number"])
        label = r["endpoint_actual_value"]
        if label is None:
            v = histogram_endpoint(r["endpoint_value"], col["data_type"])
            label = to_jsonable(v) if v is not None else "(인코딩된 값)"
        out.append({"label": str(label), "count": n - prev})
        prev = n
    total = prev or 1
    for o in out:
        o["ratio"] = o["count"] / total
    frequency = kind in ("FREQUENCY", "TOP-FREQUENCY")
    return {
        **base,
        "kind": "categorical" if frequency else "buckets",
        "values": out,
        "note": ("값별 빈도 (통계 수집 시 샘플 기준)" if frequency
                 else f"{kind} 히스토그램: 각 막대는 버킷 경계값까지의 행 비중입니다"),
        "last_analyzed": meta[0]["last_analyzed"],
    }


def _sample_distribution(owner: str, table: str, col: dict, bins: int, top: int) -> dict:
    ex = get_executor()
    src, source = _source(owner, table, "sample")
    c = qi(col["name"])
    base = {"source": "sample", "sample": source, "column": col["name"]}

    if col["kind"] in ("number", "date"):
        r = ex.query(f"SELECT MIN({c}) AS lo, MAX({c}) AS hi, COUNT(*) AS n, COUNT({c}) AS nn FROM {src} s")
        lo, hi, n, nn = r.rows[0]
        base.update({"rows": int(n), "nulls": int(n) - int(nn)})
        if lo is None:
            return {**base, "kind": "histogram", "bins": []}
        if col["kind"] == "date":
            span = (hi - lo).total_seconds() / 86400
            expr = ex.days_between(c, ":lo")
        else:
            span = float(hi) - float(lo)
            expr = f"({c} - :lo)"
        nb = bins if span > 0 else 1
        width = span / nb if span > 0 else 1
        rows = ex.query(
            f"""
            SELECT b, COUNT(*) AS cnt FROM (
                SELECT LEAST(FLOOR({expr} / :w), :nb1) AS b FROM {src} s WHERE {c} IS NOT NULL
            ) x GROUP BY b ORDER BY b
            """,
            {"lo": lo, "w": width, "nb1": nb - 1},
        ).rows
        counts = {int(b): int(cnt) for b, cnt in rows if b is not None}
        out = []
        for i in range(nb):
            if col["kind"] == "date":
                start = lo + dt.timedelta(days=width * i)
                label = start.strftime("%Y-%m-%d %H:%M" if span < 3 else "%Y-%m-%d")
            else:
                start = float(lo) + width * i
                label = _fmt_num(start) + "~" + _fmt_num(start + width)
            out.append({"label": label, "count": counts.get(i, 0)})
        return {**base, "kind": "histogram", "bins": out, "min": to_jsonable(lo), "max": to_jsonable(hi)}

    if col["kind"] != "text":
        return {**base, "kind": "none", "reason": f"{col['type']} 컬럼은 분포를 계산하지 않습니다."}
    r = ex.query(f"SELECT COUNT(*) AS n, COUNT({c}) AS nn FROM {src} s")
    n, nn = (int(x) for x in r.rows[0])
    rows = ex.query(
        f"""
        SELECT v, cnt FROM (
            SELECT {c} AS v, COUNT(*) AS cnt FROM {src} s WHERE {c} IS NOT NULL GROUP BY {c}
        ) x ORDER BY cnt DESC FETCH FIRST {int(top)} ROWS ONLY
        """
    ).rows
    shown = sum(int(cnt) for _, cnt in rows)
    values = [{"label": str(v), "count": int(cnt)} for v, cnt in rows]
    return {**base, "kind": "categorical", "rows": n, "nulls": n - nn, "values": values, "others": nn - shown}


def _fmt_num(x: float) -> str:
    for unit, scale in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(x) >= scale:
            return f"{x / scale:.3g}{unit}"
    return f"{x:.3g}"
