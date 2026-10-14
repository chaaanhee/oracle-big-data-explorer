"""데모 모드용 DuckDB 데이터베이스 생성.

여러 Owner(스키마)에 테이블·뷰를 만들고, Oracle 데이터 딕셔너리 뷰(ALL_TABLES, ALL_CONSTRAINTS,
ALL_TAB_COL_STATISTICS 등)를 같은 컬럼 구조로 채워 실제 Oracle 과 같은 딕셔너리 SQL이 동작하게 한다.
"""

import datetime as dt
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

from .oracle_raw import JULIAN_UNIX_EPOCH, encode_date, encode_number

NOW = dt.datetime.now().replace(microsecond=0)


@dataclass
class Col:
    name: str
    type: str
    comment: str | None = None
    nullable: bool = True
    default: str | None = None


@dataclass
class Obj:
    owner: str
    name: str
    comment: str | None
    columns: list[Col]
    sql: str
    kind: str = "TABLE"
    pk: list[str] = field(default_factory=list)
    fks: list[tuple[list[str], str, str]] = field(default_factory=list)  # (컬럼, 참조 owner, 참조 테이블)
    uniques: list[list[str]] = field(default_factory=list)
    indexes: list[list[str]] = field(default_factory=list)
    analyzed_days_ago: float | None = 2
    stale_ratio: float = 0.0  # 통계 이후 추가된 행 비율 (통계 행 수를 실제보다 작게 기록)
    unusable_index: bool = False


def C(name, type_, comment=None, nullable=True, default=None):
    return Col(name, type_, comment, nullable, default)


def pick(items: list[str], expr: str = "random()") -> str:
    lit = ", ".join("'" + i.replace("'", "''") + "'" for i in items)
    return f"([{lit}])[1 + CAST(floor({expr} * {len(items)}) AS INTEGER)]"


CITIES = ["서울", "인천", "수원", "성남", "대전", "청주", "천안", "광주", "전주", "목포",
          "부산", "대구", "울산", "창원", "포항", "춘천", "강릉", "원주", "제주", "서귀포"]
CITY_REGION = [1, 1, 1, 1, 2, 2, 2, 3, 3, 3, 4, 4, 4, 4, 4, 5, 5, 5, 6, 6]
SURNAMES = ["김", "이", "박", "최", "정", "강", "조", "윤", "장", "임", "한", "오", "서", "신", "권"]
GIVEN = ["민준", "서연", "도윤", "지우", "하준", "서윤", "은우", "지유", "시우", "하은", "지호", "수아", "예준", "지민", "유준"]
DEPTS = ["경영기획", "인사", "재무", "법무", "영업1", "영업2", "온라인영업", "마케팅", "브랜드", "고객지원",
         "물류", "구매", "품질관리", "생산", "연구개발", "데이터분석", "정보보안", "인프라", "플랫폼개발", "앱개발",
         "디자인", "콘텐츠", "제휴", "해외사업", "감사", "총무", "교육"]
TOP_CATEGORIES = ["전자제품", "의류", "식품", "도서", "가구", "뷰티", "스포츠", "완구"]


def build_spec() -> list[Obj]:
    locations_values = ", ".join(f"({i + 1}, '{c}', {r})" for i, (c, r) in enumerate(zip(CITIES, CITY_REGION)))
    dept_values = ", ".join(f"({(i + 1) * 10}, '{d}팀', {(i % 20) + 1}, {i + 1 if i % 6 else 'NULL'})" for i, d in enumerate(DEPTS))
    cat_values = ", ".join(
        [f"({i + 1}, '{c}', NULL)" for i, c in enumerate(TOP_CATEGORIES)]
        + [f"({9 + i}, '{TOP_CATEGORIES[i % 8]} {'일반' if i < 8 else '프리미엄'}', {i % 8 + 1})" for i in range(16)]
    )
    return [
        # ------------------------------------------------------------------ HR
        Obj("HR", "REGIONS", "지역 구분 코드", [
            C("REGION_ID", "NUMBER(4)", "지역 ID", False),
            C("REGION_NAME", "VARCHAR2(50)", "지역명", False),
        ], "SELECT * FROM (VALUES (1,'수도권'),(2,'충청권'),(3,'호남권'),(4,'영남권'),(5,'강원권'),(6,'제주권')) v(a,b)",
            pk=["REGION_ID"]),
        Obj("HR", "LOCATIONS", "사업장 위치", [
            C("LOCATION_ID", "NUMBER(6)", "위치 ID", False),
            C("CITY", "VARCHAR2(30)", "도시", False),
            C("REGION_ID", "NUMBER(4)", "지역 ID"),
            C("STREET_ADDRESS", "VARCHAR2(100)", "도로명 주소"),
        ], f"SELECT a, b, c, b || ' 중앙로 ' || (a * 7) FROM (VALUES {locations_values}) v(a,b,c)",
            pk=["LOCATION_ID"], fks=[(["REGION_ID"], "HR", "REGIONS")]),
        Obj("HR", "JOBS", "직무 코드", [
            C("JOB_ID", "VARCHAR2(10)", "직무 코드", False),
            C("JOB_TITLE", "VARCHAR2(50)", "직무명", False),
            C("MIN_SALARY", "NUMBER(10)", "최저 연봉"),
            C("MAX_SALARY", "NUMBER(10)", "최고 연봉"),
        ], """SELECT * FROM (VALUES ('CEO','대표이사',150000000,400000000),('VP','본부장',100000000,200000000),
              ('MGR','팀장',70000000,120000000),('SR','선임',50000000,80000000),('JR','주임',38000000,55000000),
              ('ENG','엔지니어',45000000,90000000),('ANL','분석가',45000000,85000000),('SALES','영업담당',35000000,70000000),
              ('CS','상담원',30000000,45000000),('DSN','디자이너',38000000,70000000),('HRM','인사담당',38000000,70000000),
              ('ACC','회계담당',38000000,72000000)) v(a,b,c,d)""",
            pk=["JOB_ID"]),
        Obj("HR", "DEPARTMENTS", "부서", [
            C("DEPARTMENT_ID", "NUMBER(4)", "부서 ID", False),
            C("DEPARTMENT_NAME", "VARCHAR2(50)", "부서명", False),
            C("LOCATION_ID", "NUMBER(6)", "근무지 위치 ID"),
            C("MANAGER_ID", "NUMBER(6)", "부서장 사원번호"),
        ], f"SELECT * FROM (VALUES {dept_values}) v(a,b,c,d)",
            pk=["DEPARTMENT_ID"], fks=[(["LOCATION_ID"], "HR", "LOCATIONS"), (["MANAGER_ID"], "HR", "EMPLOYEES")]),
        Obj("HR", "EMPLOYEES", "사원 마스터", [
            C("EMPLOYEE_ID", "NUMBER(6)", "사원번호", False),
            C("FIRST_NAME", "VARCHAR2(20)", "이름"),
            C("LAST_NAME", "VARCHAR2(25)", "성", False),
            C("EMAIL", "VARCHAR2(50)", "회사 이메일", False),
            C("PHONE_NUMBER", "VARCHAR2(20)", "휴대전화"),
            C("HIRE_DATE", "DATE", "입사일", False, "SYSDATE"),
            C("JOB_ID", "VARCHAR2(10)", "직무 코드", False),
            C("SALARY", "NUMBER(10)", "연봉(원)"),
            C("COMMISSION_PCT", "NUMBER(3,2)", "성과급 비율"),
            C("MANAGER_ID", "NUMBER(6)", "상사 사원번호"),
            C("DEPARTMENT_ID", "NUMBER(4)", "소속 부서 ID"),
        ], f"""
            SELECT i, {pick(GIVEN)}, {pick(SURNAMES)}, 'emp' || i || '@corp.example',
                   CASE WHEN random() < 0.12 THEN NULL ELSE '010-' || lpad(CAST(CAST(floor(random()*10000) AS INT) AS VARCHAR), 4, '0')
                        || '-' || lpad(CAST(CAST(floor(random()*10000) AS INT) AS VARCHAR), 4, '0') END,
                   TIMESTAMP '2005-01-01' + to_days(CAST(floor(random() * 7300) AS INTEGER)),
                   {pick(['MGR', 'SR', 'JR', 'ENG', 'ANL', 'SALES', 'CS', 'DSN', 'HRM', 'ACC'])},
                   CAST(round(32000000 + pow(random(), 2) * 90000000, -5) AS BIGINT),
                   CASE WHEN random() < 0.82 THEN NULL ELSE round(random() * 0.3, 2) END,
                   CASE WHEN i <= 27 THEN NULL ELSE 1 + CAST(floor(random() * 27) AS INTEGER) END,
                   CASE WHEN random() < 0.01 THEN NULL ELSE (1 + CAST(floor(random() * 27) AS INTEGER)) * 10 END
            FROM range(1, 20001) g(i)""",
            pk=["EMPLOYEE_ID"], uniques=[["EMAIL"]],
            fks=[(["JOB_ID"], "HR", "JOBS"), (["MANAGER_ID"], "HR", "EMPLOYEES"), (["DEPARTMENT_ID"], "HR", "DEPARTMENTS")],
            indexes=[["LAST_NAME", "FIRST_NAME"]]),
        Obj("HR", "JOB_HISTORY", "직무 변경 이력", [
            C("EMPLOYEE_ID", "NUMBER(6)", "사원번호", False),
            C("START_DATE", "DATE", "시작일", False),
            C("END_DATE", "DATE", "종료일", False),
            C("JOB_ID", "VARCHAR2(10)", "직무 코드", False),
            C("DEPARTMENT_ID", "NUMBER(4)", "부서 ID"),
        ], f"""
            SELECT e, s, s + to_days(CAST(200 + floor(random() * 1500) AS INTEGER)),
                   {pick(['JR', 'SR', 'ENG', 'ANL', 'SALES', 'CS'])}, (1 + CAST(floor(random() * 27) AS INTEGER)) * 10
            FROM (SELECT 1 + CAST(floor(random() * 20000) AS INTEGER) AS e,
                         TIMESTAMP '2003-01-01' + to_days(CAST(floor(random() * 6000) AS INTEGER)) AS s
                  FROM range(30000)) x
            QUALIFY row_number() OVER (PARTITION BY e, s) = 1""",
            pk=["EMPLOYEE_ID", "START_DATE"],
            fks=[(["EMPLOYEE_ID"], "HR", "EMPLOYEES"), (["JOB_ID"], "HR", "JOBS"), (["DEPARTMENT_ID"], "HR", "DEPARTMENTS")],
            analyzed_days_ago=120),
        # ------------------------------------------------------------------ INVENTORY
        Obj("INVENTORY", "PRODUCT_CATEGORIES", "상품 분류 (2단계 계층)", [
            C("CATEGORY_ID", "NUMBER(6)", "분류 ID", False),
            C("CATEGORY_NAME", "VARCHAR2(50)", "분류명", False),
            C("PARENT_CATEGORY_ID", "NUMBER(6)", "상위 분류 ID"),
        ], f"SELECT * FROM (VALUES {cat_values}) v(a,b,c)",
            pk=["CATEGORY_ID"], fks=[(["PARENT_CATEGORY_ID"], "INVENTORY", "PRODUCT_CATEGORIES")]),
        Obj("INVENTORY", "PRODUCTS", "상품 마스터", [
            C("PRODUCT_ID", "NUMBER(10)", "상품 ID", False),
            C("PRODUCT_NAME", "VARCHAR2(100)", "상품명", False),
            C("CATEGORY_ID", "NUMBER(6)", "분류 ID", False),
            C("LIST_PRICE", "NUMBER(12,2)", "정가"),
            C("STATUS", "VARCHAR2(10)", "판매 상태", False, "'판매중'"),
            C("CREATED_AT", "TIMESTAMP(6)", "등록 일시", False, "SYSTIMESTAMP"),
            C("DESCRIPTION", "CLOB", "상품 상세 설명"),
        ], f"""
            SELECT i, {pick(TOP_CATEGORIES)} || ' 상품 ' || lpad(CAST(i AS VARCHAR), 5, '0'),
                   9 + CAST(floor(random() * 16) AS INTEGER),
                   CAST(round(1000 + pow(random(), 3) * 2000000, -2) AS DECIMAL(12,2)),
                   CASE WHEN random() < 0.8 THEN '판매중' WHEN random() < 0.6 THEN '품절' ELSE '단종' END,
                   TIMESTAMP '2018-01-01' + to_seconds(CAST(floor(random() * 250000000) AS BIGINT)),
                   CASE WHEN random() < 0.3 THEN NULL ELSE '이 상품은 ' || i || '번 상품입니다. ' || repeat('상세 설명 ', 20) END
            FROM range(1, 20001) g(i)""",
            pk=["PRODUCT_ID"], fks=[(["CATEGORY_ID"], "INVENTORY", "PRODUCT_CATEGORIES")], indexes=[["PRODUCT_NAME"]]),
        Obj("INVENTORY", "WAREHOUSES", "물류 창고", [
            C("WAREHOUSE_ID", "NUMBER(4)", "창고 ID", False),
            C("WAREHOUSE_NAME", "VARCHAR2(50)", "창고명", False),
            C("LOCATION_ID", "NUMBER(6)", "위치 ID (HR.LOCATIONS)"),
        ], "SELECT i, '물류센터 ' || i, 1 + (i * 3) % 20 FROM range(1, 13) g(i)",
            pk=["WAREHOUSE_ID"], fks=[(["LOCATION_ID"], "HR", "LOCATIONS")]),
        Obj("INVENTORY", "STOCK", "창고별 재고", [
            C("WAREHOUSE_ID", "NUMBER(4)", "창고 ID", False),
            C("PRODUCT_ID", "NUMBER(10)", "상품 ID", False),
            C("QUANTITY", "NUMBER(10)", "재고 수량", False, "0"),
            C("UPDATED_AT", "TIMESTAMP(6)", "갱신 일시"),
        ], """
            SELECT w, p, CAST(floor(pow(random(), 2) * 500) AS INTEGER),
                   TIMESTAMP '2025-01-01' + to_seconds(CAST(floor(random() * 25000000) AS BIGINT))
            FROM range(1, 13) a(w), range(1, 20001) b(p) WHERE random() < 0.5""",
            pk=["WAREHOUSE_ID", "PRODUCT_ID"],
            fks=[(["WAREHOUSE_ID"], "INVENTORY", "WAREHOUSES"), (["PRODUCT_ID"], "INVENTORY", "PRODUCTS")]),
        # ------------------------------------------------------------------ SALES
        Obj("SALES", "CUSTOMERS", "고객 마스터", [
            C("CUSTOMER_ID", "NUMBER(10)", "고객 ID", False),
            C("CUSTOMER_NAME", "VARCHAR2(50)", "고객명", False),
            C("EMAIL", "VARCHAR2(100)", "이메일"),
            C("PHONE", "VARCHAR2(20)", "연락처"),
            C("GRADE", "VARCHAR2(10)", "고객 등급", False, "'BRONZE'"),
            C("CITY", "VARCHAR2(30)", "거주 도시"),
            C("JOINED_AT", "DATE", "가입일", False),
            C("MARKETING_YN", "CHAR(1)", "마케팅 수신 동의", False, "'N'"),
        ], f"""
            SELECT i, {pick(SURNAMES)} || {pick(GIVEN)},
                   CASE WHEN random() < 0.1 THEN NULL ELSE 'user' || i || '@mail.example' END,
                   CASE WHEN random() < 0.35 THEN NULL ELSE '010-' || lpad(CAST(CAST(floor(random()*100000000) AS BIGINT) AS VARCHAR), 8, '0') END,
                   CASE WHEN random() < 0.03 THEN 'VIP' WHEN random() < 0.15 THEN 'GOLD' WHEN random() < 0.4 THEN 'SILVER' ELSE 'BRONZE' END,
                   CASE WHEN random() < 0.05 THEN NULL ELSE {pick(CITIES)} END,
                   TIMESTAMP '2015-01-01' + to_days(CAST(floor(random() * 3900) AS INTEGER)),
                   CASE WHEN random() < 0.42 THEN 'Y' ELSE 'N' END
            FROM range(1, 300001) g(i)""",
            pk=["CUSTOMER_ID"], indexes=[["EMAIL"], ["CITY", "GRADE"]]),
        Obj("SALES", "ORDERS", "주문 헤더", [
            C("ORDER_ID", "NUMBER(12)", "주문번호", False),
            C("CUSTOMER_ID", "NUMBER(10)", "고객 ID", False),
            C("EMPLOYEE_ID", "NUMBER(6)", "담당 영업사원 (HR.EMPLOYEES, 온라인 주문은 NULL)"),
            C("ORDER_DATE", "TIMESTAMP(6)", "주문 일시", False),
            C("STATUS", "VARCHAR2(20)", "주문 상태", False),
            C("CHANNEL", "VARCHAR2(10)", "주문 채널", False),
            C("TOTAL_AMOUNT", "NUMBER(14,2)", "주문 총액"),
            C("SHIP_CITY", "VARCHAR2(30)", "배송 도시"),
        ], f"""
            SELECT i, 1 + CAST(floor(pow(random(), 1.5) * 300000) AS INTEGER),
                   CASE WHEN ch = 'STORE' THEN 1 + CAST(floor(random() * 20000) AS INTEGER) END,
                   TIMESTAMP '2023-01-01' + to_seconds(CAST(floor(random() * 94608000) AS BIGINT)),
                   CASE WHEN random() < 0.62 THEN '배송완료' WHEN random() < 0.4 THEN '배송중' WHEN random() < 0.5 THEN '결제완료'
                        WHEN random() < 0.5 THEN '취소' ELSE '반품' END,
                   ch,
                   CAST(round(5000 + pow(random(), 2.5) * 3000000, -2) AS DECIMAL(14,2)),
                   CASE WHEN random() < 0.02 THEN NULL ELSE {pick(CITIES)} END
            FROM (SELECT i, {pick(['WEB', 'APP', 'APP', 'STORE'])} AS ch FROM range(1, 1500001) g(i)) x""",
            pk=["ORDER_ID"],
            fks=[(["CUSTOMER_ID"], "SALES", "CUSTOMERS"), (["EMPLOYEE_ID"], "HR", "EMPLOYEES")],
            indexes=[["ORDER_DATE"], ["STATUS", "ORDER_DATE"]],
            analyzed_days_ago=45, stale_ratio=0.2),
        Obj("SALES", "ORDER_ITEMS", "주문 상세 품목", [
            C("ORDER_ID", "NUMBER(12)", "주문번호", False),
            C("LINE_NO", "NUMBER(4)", "품목 순번", False),
            C("PRODUCT_ID", "NUMBER(10)", "상품 ID (INVENTORY.PRODUCTS)", False),
            C("QUANTITY", "NUMBER(6)", "수량", False),
            C("UNIT_PRICE", "NUMBER(12,2)", "판매 단가", False),
            C("DISCOUNT_RATE", "NUMBER(3,2)", "할인율"),
        ], """
            SELECT o, l, 1 + CAST(floor(pow(random(), 2) * 20000) AS INTEGER), 1 + CAST(floor(pow(random(), 4) * 10) AS INTEGER),
                   CAST(round(1000 + pow(random(), 3) * 1000000, -2) AS DECIMAL(12,2)),
                   CASE WHEN random() < 0.7 THEN NULL ELSE round(random() * 0.4, 2) END
            FROM range(1, 1500001) a(o), range(1, 6) b(l) WHERE l <= 1 + (o * 7919) % 4""",
            pk=["ORDER_ID", "LINE_NO"],
            fks=[(["ORDER_ID"], "SALES", "ORDERS"), (["PRODUCT_ID"], "INVENTORY", "PRODUCTS")],
            indexes=[["PRODUCT_ID"]]),
        Obj("SALES", "PAYMENTS", "결제 내역", [
            C("PAYMENT_ID", "NUMBER(12)", "결제 ID", False),
            C("ORDER_ID", "NUMBER(12)", "주문번호", False),
            C("METHOD", "VARCHAR2(20)", "결제 수단", False),
            C("AMOUNT", "NUMBER(14,2)", "결제 금액", False),
            C("PAID_AT", "TIMESTAMP(6)", "결제 일시"),
            C("APPROVAL_NO", "VARCHAR2(30)", None),
        ], f"""
            SELECT row_number() OVER (), i, {pick(['신용카드', '신용카드', '간편결제', '계좌이체', '휴대폰', '포인트'])},
                   CAST(round(5000 + pow(random(), 2.5) * 3000000, -2) AS DECIMAL(14,2)),
                   TIMESTAMP '2023-01-01' + to_seconds(CAST(floor(random() * 94608000) AS BIGINT)),
                   CASE WHEN random() < 0.05 THEN NULL ELSE 'AP' || lpad(CAST(i AS VARCHAR), 12, '0') END
            FROM range(1, 1500001) g(i) WHERE random() < 0.9""",
            pk=["PAYMENT_ID"], fks=[(["ORDER_ID"], "SALES", "ORDERS")], indexes=[["PAID_AT"]]),
        Obj("SALES", "ORDER_HIST", "주문 상태 변경 이력", [
            C("HIST_ID", "NUMBER(12)", "이력 ID", False),
            C("ORDER_ID", "NUMBER(12)", "주문번호", False),
            C("STATUS", "VARCHAR2(20)", "변경 후 상태", False),
            C("CHANGED_AT", "TIMESTAMP(6)", "변경 일시", False),
            C("CHANGED_BY", "VARCHAR2(30)", "변경자"),
        ], f"""
            SELECT i, 1 + CAST(floor(random() * 1500000) AS INTEGER), {pick(['결제완료', '배송중', '배송완료', '취소', '반품'])},
                   TIMESTAMP '2023-01-01' + to_seconds(CAST(floor(random() * 94608000) AS BIGINT)),
                   CASE WHEN random() < 0.7 THEN 'SYSTEM' ELSE 'emp' || CAST(1 + floor(random()*20000) AS INTEGER) END
            FROM range(1, 200001) g(i)""",
            pk=["HIST_ID"], fks=[(["ORDER_ID"], "SALES", "ORDERS")], indexes=[["ORDER_ID"]], unusable_index=True),
        Obj("SALES", "ORDERS_BACKUP_2024", None, [
            C("ORDER_ID", "NUMBER(12)"), C("CUSTOMER_ID", "NUMBER(10)"), C("EMPLOYEE_ID", "NUMBER(6)"),
            C("ORDER_DATE", "TIMESTAMP(6)"), C("STATUS", "VARCHAR2(20)"), C("CHANNEL", "VARCHAR2(10)"),
            C("TOTAL_AMOUNT", "NUMBER(14,2)"), C("SHIP_CITY", "VARCHAR2(30)"),
        ], 'SELECT * FROM "SALES"."ORDERS" WHERE ORDER_DATE < TIMESTAMP \'2024-01-01\' AND ORDER_ID % 5 = 0',
            analyzed_days_ago=None),
        Obj("SALES", "V_ORDER_SUMMARY", "주문 요약 뷰 (주문 + 고객)", [
            C("ORDER_ID", "NUMBER(12)", "주문번호"), C("ORDER_DATE", "TIMESTAMP(6)", "주문 일시"),
            C("CUSTOMER_NAME", "VARCHAR2(50)", "고객명"), C("GRADE", "VARCHAR2(10)", "고객 등급"),
            C("STATUS", "VARCHAR2(20)", "주문 상태"), C("TOTAL_AMOUNT", "NUMBER(14,2)", "주문 총액"),
        ], """SELECT o.ORDER_ID, o.ORDER_DATE, c.CUSTOMER_NAME, c.GRADE, o.STATUS, o.TOTAL_AMOUNT
              FROM "SALES"."ORDERS" o JOIN "SALES"."CUSTOMERS" c ON c.CUSTOMER_ID = o.CUSTOMER_ID""",
            kind="VIEW"),
        # ------------------------------------------------------------------ ANALYTICS (FK 없음)
        Obj("ANALYTICS", "DAILY_SALES", "일별·분류별 매출 집계 (배치 적재)", [
            C("SALES_DATE", "DATE", "매출 일자", False),
            C("CATEGORY_ID", "NUMBER(6)", "상품 분류 ID", False),
            C("ORDER_CNT", "NUMBER(10)", "주문 건수"),
            C("AMOUNT", "NUMBER(16,2)", "매출액"),
        ], """
            SELECT CAST(d AS TIMESTAMP), c, CAST(floor(50 + random() * 500) AS INTEGER),
                   CAST(round(1000000 + random() * 90000000, -3) AS DECIMAL(16,2))
            FROM range(DATE '2023-01-01', DATE '2026-01-01', INTERVAL 1 DAY) a(d), range(1, 9) b(c)""",
            pk=["SALES_DATE", "CATEGORY_ID"]),
        Obj("ANALYTICS", "CUSTOMER_SEGMENTS", "고객 세그먼트 (모델 산출)", [
            C("CUSTOMER_ID", "NUMBER(10)", "고객 ID", False),
            C("SEGMENT", "VARCHAR2(20)", "세그먼트", False),
            C("SCORE", "NUMBER(5,2)", "충성도 점수"),
            C("UPDATED_AT", "DATE", None),
        ], f"""
            SELECT i, {pick(['충성', '성장', '휴면위험', '이탈', '신규'])}, round(random() * 100, 2),
                   TIMESTAMP '2025-06-01' + to_days(CAST(floor(random() * 120) AS INTEGER))
            FROM range(1, 300001) g(i) WHERE random() < 0.8""",
            pk=["CUSTOMER_ID"], analyzed_days_ago=8),
        Obj("ANALYTICS", "V_TOP_PRODUCTS", "판매 수량 상위 상품", [
            C("PRODUCT_ID", "NUMBER(10)", "상품 ID"), C("PRODUCT_NAME", "VARCHAR2(100)", "상품명"),
            C("TOTAL_QTY", "NUMBER", "판매 수량"),
        ], """SELECT p.PRODUCT_ID, p.PRODUCT_NAME, SUM(i.QUANTITY) AS TOTAL_QTY
              FROM "SALES"."ORDER_ITEMS" i JOIN "INVENTORY"."PRODUCTS" p ON p.PRODUCT_ID = i.PRODUCT_ID
              GROUP BY ALL ORDER BY TOTAL_QTY DESC LIMIT 100""",
            kind="VIEW"),
    ]


# --------------------------------------------------------------------------- 딕셔너리 DDL

DICTIONARY_DDL = """
CREATE TABLE ALL_USERS (USERNAME VARCHAR, USER_ID INTEGER, CREATED TIMESTAMP, ORACLE_MAINTAINED VARCHAR);
CREATE TABLE ALL_OBJECTS (OWNER VARCHAR, OBJECT_NAME VARCHAR, OBJECT_TYPE VARCHAR, CREATED TIMESTAMP,
    LAST_DDL_TIME TIMESTAMP, STATUS VARCHAR);
CREATE TABLE ALL_TABLES (OWNER VARCHAR, TABLE_NAME VARCHAR, TABLESPACE_NAME VARCHAR, NUM_ROWS BIGINT, BLOCKS BIGINT,
    EMPTY_BLOCKS BIGINT, AVG_ROW_LEN BIGINT, SAMPLE_SIZE BIGINT, LAST_ANALYZED TIMESTAMP, PARTITIONED VARCHAR,
    COMPRESSION VARCHAR);
CREATE TABLE ALL_VIEWS (OWNER VARCHAR, VIEW_NAME VARCHAR, TEXT VARCHAR);
CREATE TABLE ALL_TAB_COLUMNS (OWNER VARCHAR, TABLE_NAME VARCHAR, COLUMN_NAME VARCHAR, DATA_TYPE VARCHAR,
    DATA_LENGTH INTEGER, DATA_PRECISION INTEGER, DATA_SCALE INTEGER, CHAR_LENGTH INTEGER, NULLABLE VARCHAR,
    COLUMN_ID INTEGER, DATA_DEFAULT VARCHAR);
CREATE TABLE ALL_TAB_COMMENTS (OWNER VARCHAR, TABLE_NAME VARCHAR, TABLE_TYPE VARCHAR, COMMENTS VARCHAR);
CREATE TABLE ALL_COL_COMMENTS (OWNER VARCHAR, TABLE_NAME VARCHAR, COLUMN_NAME VARCHAR, COMMENTS VARCHAR);
CREATE TABLE ALL_CONSTRAINTS (OWNER VARCHAR, CONSTRAINT_NAME VARCHAR, CONSTRAINT_TYPE VARCHAR, TABLE_NAME VARCHAR,
    R_OWNER VARCHAR, R_CONSTRAINT_NAME VARCHAR, DELETE_RULE VARCHAR, STATUS VARCHAR);
CREATE TABLE ALL_CONS_COLUMNS (OWNER VARCHAR, CONSTRAINT_NAME VARCHAR, TABLE_NAME VARCHAR, COLUMN_NAME VARCHAR,
    POSITION INTEGER);
CREATE TABLE ALL_INDEXES (OWNER VARCHAR, INDEX_NAME VARCHAR, INDEX_TYPE VARCHAR, TABLE_OWNER VARCHAR,
    TABLE_NAME VARCHAR, UNIQUENESS VARCHAR, STATUS VARCHAR);
CREATE TABLE ALL_IND_COLUMNS (INDEX_OWNER VARCHAR, INDEX_NAME VARCHAR, TABLE_OWNER VARCHAR, TABLE_NAME VARCHAR,
    COLUMN_NAME VARCHAR, COLUMN_POSITION INTEGER, DESCEND VARCHAR);
CREATE TABLE ALL_TAB_STATISTICS (OWNER VARCHAR, TABLE_NAME VARCHAR, OBJECT_TYPE VARCHAR, STALE_STATS VARCHAR,
    STATTYPE_LOCKED VARCHAR);
CREATE TABLE ALL_TAB_COL_STATISTICS (OWNER VARCHAR, TABLE_NAME VARCHAR, COLUMN_NAME VARCHAR, NUM_DISTINCT BIGINT,
    LOW_VALUE BLOB, HIGH_VALUE BLOB, DENSITY DOUBLE, NUM_NULLS BIGINT, NUM_BUCKETS INTEGER, LAST_ANALYZED TIMESTAMP,
    SAMPLE_SIZE BIGINT, AVG_COL_LEN INTEGER, HISTOGRAM VARCHAR);
CREATE TABLE ALL_TAB_HISTOGRAMS (OWNER VARCHAR, TABLE_NAME VARCHAR, COLUMN_NAME VARCHAR, ENDPOINT_NUMBER BIGINT,
    ENDPOINT_VALUE DOUBLE, ENDPOINT_ACTUAL_VALUE VARCHAR);
CREATE TABLE ALL_TAB_MODIFICATIONS (TABLE_OWNER VARCHAR, TABLE_NAME VARCHAR, PARTITION_NAME VARCHAR, INSERTS BIGINT,
    UPDATES BIGINT, DELETES BIGINT, "TIMESTAMP" TIMESTAMP, TRUNCATED VARCHAR);
CREATE TABLE DBA_SEGMENTS (OWNER VARCHAR, SEGMENT_NAME VARCHAR, SEGMENT_TYPE VARCHAR, BYTES BIGINT);
CREATE TABLE SESSION_PRIVS (PRIVILEGE VARCHAR);
CREATE TABLE SESSION_ROLES (ROLE VARCHAR);
CREATE TABLE ALL_TAB_PRIVS (GRANTOR VARCHAR, GRANTEE VARCHAR, TABLE_SCHEMA VARCHAR, TABLE_NAME VARCHAR, PRIVILEGE VARCHAR);
CREATE TABLE DUAL (DUMMY VARCHAR);
INSERT INTO DUAL VALUES ('X');
INSERT INTO SESSION_PRIVS VALUES ('CREATE SESSION');
INSERT INTO SESSION_ROLES VALUES ('CONNECT');
"""


def _parse_type(t: str) -> dict:
    m = re.match(r"^(\w+(?: \w+)?)(?:\((\d+)(?:,(\d+))?\))?$", t)
    base, a, b = m.group(1), m.group(2), m.group(3)
    if base == "NUMBER":
        return {"data_type": "NUMBER", "data_length": 22, "data_precision": int(a) if a else None,
                "data_scale": int(b or 0) if a else None, "char_length": 0}
    if base in ("VARCHAR2", "CHAR", "NVARCHAR2", "NCHAR"):
        return {"data_type": base, "data_length": int(a), "data_precision": None, "data_scale": None, "char_length": int(a)}
    if base == "TIMESTAMP":
        return {"data_type": f"TIMESTAMP({a or 6})", "data_length": 11, "data_precision": None, "data_scale": int(a or 6), "char_length": 0}
    if base == "DATE":
        return {"data_type": "DATE", "data_length": 7, "data_precision": None, "data_scale": None, "char_length": 0}
    return {"data_type": base, "data_length": 4000, "data_precision": None, "data_scale": None, "char_length": 0}


def _encode(value, data_type: str):
    if value is None:
        return None
    if data_type == "NUMBER":
        return encode_number(value)
    if data_type == "DATE" or data_type.startswith("TIMESTAMP"):
        return encode_date(value)
    if isinstance(value, str):
        out = b""
        for ch in value:
            nb = ch.encode("utf-8")
            if len(out) + len(nb) > 32:
                break
            out += nb
        return out
    return None


def _endpoint_value(value, data_type: str):
    if data_type == "NUMBER":
        return float(value)
    if data_type == "DATE" or data_type.startswith("TIMESTAMP"):
        return (value - dt.datetime(1970, 1, 1)).total_seconds() / 86400 + JULIAN_UNIX_EPOCH
    return 0.0


def _build(con: duckdb.DuckDBPyConnection) -> None:
    spec = build_spec()
    con.execute("SELECT setseed(0.42)")
    for owner in sorted({o.owner for o in spec}):
        con.execute(f'CREATE SCHEMA "{owner}"')
    for o in spec:
        names = ", ".join(f'"{c.name}"' for c in o.columns)
        body = f"SELECT * FROM ({o.sql}) src({names})"
        con.execute(f'CREATE {o.kind} "{o.owner}"."{o.name}" AS {body}')
    con.execute(DICTIONARY_DDL)

    pk_name = {(o.owner, o.name): f"PK_{o.name}" for o in spec if o.pk}
    created_base = NOW - dt.timedelta(days=900)

    users = [("SYS", 0, "Y"), ("SYSTEM", 5, "Y"), ("APP_READER", 120, "N")]
    users += [(u, 100 + i, "N") for i, u in enumerate(sorted({o.owner for o in spec}))]
    for name, uid, maintained in users:
        con.execute("INSERT INTO ALL_USERS VALUES (?, ?, ?, ?)", [name, uid, created_base - dt.timedelta(days=uid), maintained])
    con.execute("INSERT INTO ALL_OBJECTS VALUES ('SYS', 'DUAL', 'TABLE', ?, ?, 'VALID')", [created_base, created_base])

    for idx, o in enumerate(spec):
        key = (o.owner, o.name)
        created = created_base + dt.timedelta(days=idx * 11)
        last_ddl = NOW - dt.timedelta(days=(idx * 37) % 200 + 1)
        con.execute("INSERT INTO ALL_OBJECTS VALUES (?, ?, ?, ?, ?, 'VALID')", [o.owner, o.name, o.kind, created, last_ddl])
        con.execute("INSERT INTO ALL_TAB_COMMENTS VALUES (?, ?, ?, ?)", [o.owner, o.name, o.kind, o.comment])
        con.execute("INSERT INTO ALL_TAB_PRIVS VALUES (?, 'APP_READER', ?, ?, 'SELECT')", [o.owner, o.owner, o.name])
        if o.kind == "VIEW":
            con.execute("INSERT INTO ALL_VIEWS VALUES (?, ?, ?)", [o.owner, o.name, " ".join(o.sql.split())])

        types = {}
        for i, c in enumerate(o.columns, start=1):
            t = _parse_type(c.type)
            types[c.name] = t["data_type"]
            con.execute(
                "INSERT INTO ALL_TAB_COLUMNS VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [o.owner, o.name, c.name, t["data_type"], t["data_length"], t["data_precision"], t["data_scale"],
                 t["char_length"], "Y" if c.nullable else "N", i, (c.default + " ") if c.default else None],
            )
            con.execute("INSERT INTO ALL_COL_COMMENTS VALUES (?, ?, ?, ?)", [o.owner, o.name, c.name, c.comment])

        if o.kind != "TABLE":
            continue

        def add_index(name, cols, unique, status="VALID"):
            con.execute("INSERT INTO ALL_INDEXES VALUES (?, ?, 'NORMAL', ?, ?, ?, ?)",
                        [o.owner, name, o.owner, o.name, "UNIQUE" if unique else "NONUNIQUE", status])
            con.execute("INSERT INTO ALL_OBJECTS VALUES (?, ?, 'INDEX', ?, ?, 'VALID')", [o.owner, name, created, created])
            for p, col in enumerate(cols, start=1):
                con.execute("INSERT INTO ALL_IND_COLUMNS VALUES (?, ?, ?, ?, ?, ?, 'ASC')", [o.owner, name, o.owner, o.name, col, p])

        def add_constraint(name, ctype, cols, r_owner=None, r_name=None):
            con.execute("INSERT INTO ALL_CONSTRAINTS VALUES (?, ?, ?, ?, ?, ?, ?, 'ENABLED')",
                        [o.owner, name, ctype, o.name, r_owner, r_name, "NO ACTION" if ctype == "R" else None])
            for p, col in enumerate(cols, start=1):
                con.execute("INSERT INTO ALL_CONS_COLUMNS VALUES (?, ?, ?, ?, ?)", [o.owner, name, o.name, col, p])

        if o.pk:
            add_constraint(pk_name[key], "P", o.pk)
            add_index(pk_name[key], o.pk, True)
        for n, u in enumerate(o.uniques, start=1):
            add_constraint(f"UK_{o.name}_{n}", "U", u)
            add_index(f"UK_{o.name}_{n}", u, True)
        for n, (cols, r_owner, r_table) in enumerate(o.fks, start=1):
            add_constraint(f"FK_{o.name}_{n}", "R", cols, r_owner, pk_name[(r_owner, r_table)])
        for n, cols in enumerate(o.indexes, start=1):
            status = "UNUSABLE" if (o.unusable_index and n == 1) else "VALID"
            add_index(f"IX_{o.name}_{n}", cols, False, status)

        # ---- 통계 (DBMS_STATS.GATHER_TABLE_STATS 를 흉내 낸다)
        ref = f'"{o.owner}"."{o.name}"'
        exprs = ["COUNT(*)"]
        for c in o.columns:
            q = f'"{c.name}"'
            exprs += [f"COUNT({q})", f"approx_count_distinct({q})",
                      f"MIN({q})" if types[c.name] != "CLOB" else "NULL",
                      f"MAX({q})" if types[c.name] != "CLOB" else "NULL",
                      f"AVG(strlen(CAST({q} AS VARCHAR)))"]
        stats = con.execute(f"SELECT {', '.join(exprs)} FROM {ref}").fetchone()
        actual = stats[0]
        avg_row_len = 0
        col_stats = []
        for i, c in enumerate(o.columns):
            nn, ndv, lo, hi, avg_len = stats[1 + i * 5: 6 + i * 5]
            avg_len = int(math.ceil(avg_len or 0)) + 1
            avg_row_len += avg_len
            col_stats.append((c, nn, ndv, lo, hi, avg_len))
        blocks = max(1, math.ceil(actual * avg_row_len / 7000))
        con.execute("INSERT INTO DBA_SEGMENTS VALUES (?, ?, 'TABLE', ?)", [o.owner, o.name, int(blocks * 8192 * 1.12)])

        if o.analyzed_days_ago is None:
            con.execute("INSERT INTO ALL_TABLES VALUES (?, ?, 'USERS', NULL, NULL, NULL, NULL, NULL, NULL, 'NO', 'DISABLED')",
                        [o.owner, o.name])
            con.execute("INSERT INTO ALL_TAB_STATISTICS VALUES (?, ?, 'TABLE', NULL, NULL)", [o.owner, o.name])
            continue

        analyzed = NOW - dt.timedelta(days=o.analyzed_days_ago, hours=3)
        stat_rows = int(actual * (1 - o.stale_ratio))
        con.execute("INSERT INTO ALL_TABLES VALUES (?, ?, 'USERS', ?, ?, 0, ?, ?, ?, 'NO', 'DISABLED')",
                    [o.owner, o.name, stat_rows, int(blocks * (1 - o.stale_ratio)), avg_row_len, stat_rows, analyzed])
        stale = "YES" if o.stale_ratio > 0.1 or o.analyzed_days_ago > 90 else "NO"
        con.execute("INSERT INTO ALL_TAB_STATISTICS VALUES (?, ?, 'TABLE', ?, NULL)", [o.owner, o.name, stale])
        if o.stale_ratio:
            inserted = actual - stat_rows
            con.execute("INSERT INTO ALL_TAB_MODIFICATIONS VALUES (?, ?, NULL, ?, ?, ?, ?, 'NO')",
                        [o.owner, o.name, inserted, int(inserted * 0.6), int(inserted * 0.01), NOW - dt.timedelta(hours=5)])
        elif o.analyzed_days_ago > 30:
            con.execute("INSERT INTO ALL_TAB_MODIFICATIONS VALUES (?, ?, NULL, ?, ?, 0, ?, 'NO')",
                        [o.owner, o.name, int(actual * 0.03), int(actual * 0.05), NOW - dt.timedelta(days=3)])

        for c, nn, ndv, lo, hi, avg_len in col_stats:
            data_type = types[c.name]
            nulls = int((actual - nn) * (1 - o.stale_ratio))
            if data_type == "CLOB":
                con.execute("INSERT INTO ALL_TAB_COL_STATISTICS VALUES (?, ?, ?, NULL, NULL, NULL, NULL, ?, 0, ?, ?, ?, 'NONE')",
                            [o.owner, o.name, c.name, nulls, analyzed, stat_rows, avg_len])
                continue
            ndv = min(int(ndv or 0), nn)
            histogram, buckets = "NONE", 1
            if 0 < ndv <= 32:
                histogram, buckets = "FREQUENCY", ndv
                rows = con.execute(
                    f'SELECT "{c.name}", COUNT(*) FROM {ref} WHERE "{c.name}" IS NOT NULL GROUP BY 1 ORDER BY 1'
                ).fetchall()
                cumulative = 0
                for value, cnt in rows:
                    cumulative += cnt
                    actual_value = value if isinstance(value, str) else None
                    con.execute("INSERT INTO ALL_TAB_HISTOGRAMS VALUES (?, ?, ?, ?, ?, ?)",
                                [o.owner, o.name, c.name, cumulative, _endpoint_value(value, data_type), actual_value])
            con.execute(
                "INSERT INTO ALL_TAB_COL_STATISTICS VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [o.owner, o.name, c.name, ndv, _encode(lo, data_type), _encode(hi, data_type),
                 (1 / ndv) if ndv else 0, nulls, buckets, analyzed, stat_rows, avg_len, histogram],
            )


def ensure_demo_db(path: Path) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".building")
    tmp.unlink(missing_ok=True)
    con = duckdb.connect(str(tmp))
    try:
        _build(con)
        con.execute("CHECKPOINT")
    finally:
        con.close()
    os.replace(tmp, path)
