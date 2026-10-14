"""SQL Workbench용 읽기 전용 검사.

애플리케이션 단의 1차 방어선이다. 실제 안전장치는 (1) SELECT 권한만 가진 읽기 전용 계정,
(2) 실행기에서 거는 `SET TRANSACTION READ ONLY`, (3) 실행 시간·반환 행 수 제한이다.
"""

import re

from .config import settings


class SqlRejected(ValueError):
    pass


FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|UPSERT|CREATE|ALTER|DROP|TRUNCATE|RENAME|GRANT|REVOKE|COMMENT|"
    r"LOCK|CALL|EXEC|EXECUTE|BEGIN|DECLARE|COMMIT|ROLLBACK|SAVEPOINT|PURGE|FLASHBACK|ANALYZE|AUDIT|"
    r"ATTACH|DETACH|COPY|EXPORT|IMPORT|INSTALL|LOAD|PRAGMA|SET)\b",
    re.IGNORECASE,
)
FORBIDDEN_PACKAGES = re.compile(r"\b(DBMS_\w+|UTL_\w+|HTTPURITYPE|SYS\.\w+)\b", re.IGNORECASE)
FOR_UPDATE = re.compile(r"\bFOR\s+UPDATE\b", re.IGNORECASE)
INLINE_PLSQL = re.compile(r"^\s*WITH\s+(FUNCTION|PROCEDURE)\b", re.IGNORECASE)
FILE_FUNCS = re.compile(r"\b(read_\w+|glob|parquet_\w+)\s*\(", re.IGNORECASE)


def _strip(sql: str) -> str:
    """주석과 문자열 리터럴을 공백으로 치환해 키워드 검사가 리터럴 내용에 속지 않게 한다."""
    out = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""
        if ch == "-" and nxt == "-":
            j = sql.find("\n", i)
            i = n if j < 0 else j
            continue
        if ch == "/" and nxt == "*":
            j = sql.find("*/", i + 2)
            if j < 0:
                raise SqlRejected("닫히지 않은 주석(/* ... */)이 있습니다.")
            i = j + 2
            out.append(" ")
            continue
        if ch in "qQ" and nxt == "'" and i + 2 < n:
            # Oracle 대체 인용 리터럴 q'[...]'
            opener = sql[i + 2]
            closer = {"[": "]", "(": ")", "{": "}", "<": ">"}.get(opener, opener)
            j = sql.find(closer + "'", i + 3)
            if j < 0:
                raise SqlRejected("닫히지 않은 문자열 리터럴이 있습니다.")
            i = j + 2
            out.append("''")
            continue
        if ch == "'":
            j = i + 1
            while True:
                j = sql.find("'", j)
                if j < 0:
                    raise SqlRejected("닫히지 않은 문자열 리터럴이 있습니다.")
                if j + 1 < n and sql[j + 1] == "'":
                    j += 2
                    continue
                break
            i = j + 1
            out.append("''")
            continue
        if ch == '"':
            j = sql.find('"', i + 1)
            if j < 0:
                raise SqlRejected('닫히지 않은 따옴표 식별자(")가 있습니다.')
            out.append('""')
            i = j + 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def validate_select(sql: str, *, demo: bool = False) -> str:
    """검사를 통과하면 끝의 세미콜론을 제거한 실행용 SQL을 돌려준다."""
    body = sql.strip()
    stripped = _strip(body).strip()
    while stripped.endswith(";") or stripped.endswith("/"):
        stripped = stripped[:-1].rstrip()
        body = body.rstrip().rstrip(";/").rstrip()
    if not stripped:
        raise SqlRejected("실행할 SQL이 없습니다.")
    if ";" in stripped:
        raise SqlRejected("한 번에 하나의 SQL 문만 실행할 수 있습니다.")
    first = re.match(r"\(*\s*(\w+)", stripped)
    if not first or first.group(1).upper() not in ("SELECT", "WITH"):
        raise SqlRejected("읽기 전용 조회(SELECT 또는 WITH ... SELECT)만 실행할 수 있습니다.")
    if INLINE_PLSQL.search(stripped):
        raise SqlRejected("WITH FUNCTION/PROCEDURE(인라인 PL/SQL)는 허용되지 않습니다.")
    if FOR_UPDATE.search(stripped):
        raise SqlRejected("SELECT ... FOR UPDATE(행 잠금)는 허용되지 않습니다.")
    m = FORBIDDEN.search(stripped)
    if m:
        raise SqlRejected(f"허용되지 않는 키워드가 포함되어 있습니다: {m.group(1).upper()}")
    m = FORBIDDEN_PACKAGES.search(stripped)
    if m:
        raise SqlRejected(f"시스템 패키지 호출은 허용되지 않습니다: {m.group(1).upper()}")
    if not settings.allow_db_links and "@" in stripped:
        raise SqlRejected("DB 링크(@) 사용은 허용되지 않습니다. (ALLOW_DB_LINKS=true 로 허용 가능)")
    if demo and FILE_FUNCS.search(stripped):
        raise SqlRejected("파일 읽기 함수는 허용되지 않습니다.")
    return body
