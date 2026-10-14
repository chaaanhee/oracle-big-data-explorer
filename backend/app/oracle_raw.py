"""ALL_TAB_COL_STATISTICS.LOW_VALUE / HIGH_VALUE (RAW) 를 사람이 읽을 수 있는 값으로 변환한다."""

import datetime as dt
from decimal import Decimal, getcontext

getcontext().prec = 50

JULIAN_UNIX_EPOCH = 2440588  # 1970-01-01 의 율리우스 일


def decode_number(b: bytes) -> Decimal | None:
    if not b:
        return None
    if b == b"\x80":
        return Decimal(0)
    if b[0] & 0x80:
        exp = (b[0] & 0x7F) - 65
        digits = [x - 1 for x in b[1:]]
        sign = 1
    else:
        exp = ((~b[0]) & 0x7F) - 65
        body = b[1:-1] if b[-1] == 102 else b[1:]
        digits = [101 - x for x in body]
        sign = -1
    value = sum(Decimal(d) * (Decimal(100) ** (exp - i)) for i, d in enumerate(digits))
    return sign * value.normalize()


def encode_number(x) -> bytes:
    d = Decimal(str(x))
    if d == 0:
        return b"\x80"
    neg = d < 0
    d = abs(d)
    exp = 0
    while d >= Decimal(100) ** (exp + 1):
        exp += 1
    while d < Decimal(100) ** exp:
        exp -= 1
    digits, rem = [], d
    for i in range(20):
        p = Decimal(100) ** (exp - i)
        q = int(rem // p)
        digits.append(q)
        rem -= q * p
        if rem == 0:
            break
    while len(digits) > 1 and digits[-1] == 0:
        digits.pop()
    if not neg:
        return bytes([0xC1 + exp] + [x + 1 for x in digits])
    out = [62 - exp] + [101 - x for x in digits]
    if len(out) < 21:
        out.append(102)
    return bytes(out)


def decode_date(b: bytes) -> dt.datetime | None:
    if not b or len(b) < 7:
        return None
    year = (b[0] - 100) * 100 + (b[1] - 100)
    frac = int.from_bytes(b[7:11], "big") // 1000 if len(b) >= 11 else 0
    return dt.datetime(year, b[2], b[3], b[4] - 1, b[5] - 1, b[6] - 1, frac)


def encode_date(v: dt.datetime | dt.date) -> bytes:
    if not isinstance(v, dt.datetime):
        v = dt.datetime(v.year, v.month, v.day)
    return bytes([v.year // 100 + 100, v.year % 100 + 100, v.month, v.day, v.hour + 1, v.minute + 1, v.second + 1])


def decode_raw(raw, data_type: str):
    if raw is None:
        return None
    b = bytes(raw)
    t = (data_type or "").upper()
    try:
        if t in ("NUMBER", "FLOAT", "INTEGER"):
            return decode_number(b)
        if t == "DATE" or t.startswith("TIMESTAMP"):
            return decode_date(b)
        if t in ("NVARCHAR2", "NCHAR"):
            return b.decode("utf-16-be", errors="replace")
        if t in ("VARCHAR2", "CHAR", "VARCHAR"):
            return b.decode("utf-8", errors="replace")
        if t == "BINARY_DOUBLE" or t == "BINARY_FLOAT":
            return None
    except (ValueError, IndexError):
        return None
    return None


def histogram_endpoint(value, data_type: str):
    """ENDPOINT_VALUE(숫자) 를 컬럼 타입에 맞게 변환한다. 문자열은 ENDPOINT_ACTUAL_VALUE 를 써야 한다."""
    if value is None:
        return None
    t = (data_type or "").upper()
    if t == "DATE" or t.startswith("TIMESTAMP"):
        days = float(value) - JULIAN_UNIX_EPOCH
        return dt.datetime(1970, 1, 1) + dt.timedelta(days=days)
    if t in ("NUMBER", "FLOAT", "INTEGER", "BINARY_DOUBLE", "BINARY_FLOAT"):
        return value
    return None
