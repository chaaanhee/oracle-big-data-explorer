import datetime as dt
import decimal
import math
import uuid

JS_SAFE_INT = 2**53


def to_jsonable(v):
    if v is None or isinstance(v, (bool, str)):
        return v
    if isinstance(v, int):
        return str(v) if abs(v) > JS_SAFE_INT else v
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, decimal.Decimal):
        if v == v.to_integral_value() and abs(v) <= JS_SAFE_INT:
            return int(v)
        f = float(v)
        return f if math.isfinite(f) else None
    if isinstance(v, (dt.datetime, dt.date, dt.time)):
        return v.isoformat(sep=" ") if isinstance(v, dt.datetime) else v.isoformat()
    if isinstance(v, dt.timedelta):
        return str(v)
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, (bytes, bytearray, memoryview)):
        b = bytes(v)
        return b[:32].hex().upper() + ("…" if len(b) > 32 else "")
    if isinstance(v, dict):
        return {str(k): to_jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [to_jsonable(x) for x in v]
    return str(v)


def rows_to_json(rows) -> list[list]:
    return [[to_jsonable(v) for v in row] for row in rows]


def records(columns: list[dict], rows) -> list[dict]:
    """컬럼명을 소문자 키로 하는 dict 목록으로 변환한다 (Oracle은 대문자 컬럼명을 돌려준다)."""
    names = [c["name"].lower() for c in columns]
    return [dict(zip(names, row)) for row in rows]
