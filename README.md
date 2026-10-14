# Big Data Explorer (Oracle)

여러 Owner·테이블이 있는 Oracle DB 를 웹에서 탐색하는 도구입니다.
프론트엔드는 React(Vite + TypeScript), 백엔드는 Python(FastAPI + python-oracledb) 입니다.

| 기능 | 화면 | 내용 |
| --- | --- | --- |
| ① Owner / Schema Explorer | 스키마 탐색기 | Owner 목록과 테이블·뷰·인덱스 수, Owner·테이블 이름 검색, 즐겨찾기, 최근 조회 |
| ② Table Data Viewer | 테이블 › 데이터 / 구조 | 페이지 단위 조회, 정렬·필터·검색, 컬럼 타입·NULL 여부·PK/FK 표시, CSV 내보내기 |
| ③ SQL Workbench | SQL 워크벤치 | SQL 실행, 실행 시간·행 수, 결과 표·CSV, 실행 이력·즐겨찾기 쿼리 |
| ④ Table Profiler | 테이블 › 프로파일 | 행 수·용량, 컬럼별 NULL 비율·고유값·최소/최대·분포, 통계 수집 시점, 품질 지표 |
| ⑤ Schema Map | 스키마 맵 / 테이블 › 관계 | PK·FK 기반 ERD, 관련 테이블 탐색, Owner 간 참조 |
| ⑥ Global Search | 전체 검색 | 모든 Owner 의 테이블·컬럼·주석 검색, 이름이 비슷한 테이블, 관련 테이블 |

## 실행

### 백엔드

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
copy .env.example .env      # Oracle 접속 정보 입력 (비워 두면 데모 모드)
.\.venv\Scripts\python -m uvicorn app.main:app --port 8000
```

### 프론트엔드

```powershell
cd frontend
npm install
npm run dev                 # http://localhost:5173 (/api 는 8000 포트로 프록시)
```

## Oracle 연결

`backend/.env` 의 `ORACLE_USER`, `ORACLE_PASSWORD`, `ORACLE_DSN`(예: `dbhost:1521/ORCLPDB1`)을 채우면 Oracle 모드로 동작합니다.
python-oracledb **thin 모드**를 쓰므로 Oracle Client 설치가 필요 없습니다 (DB 12.1 이상).

### 읽기 전용 계정 (권장)

앱은 요청마다 `SET TRANSACTION READ ONLY` 를 걸고 끝나면 롤백하지만, 가장 확실한 방어는 **쓰기 권한이 없는 계정**입니다.

```sql
CREATE USER app_reader IDENTIFIED BY "********";
GRANT CREATE SESSION TO app_reader;

-- 탐색할 테이블마다 SELECT 권한
GRANT SELECT ON sales.orders TO app_reader;
-- 23ai 이상이면 스키마 단위로 줄 수 있음
-- GRANT SELECT ANY TABLE ON SCHEMA sales TO app_reader;

-- 선택 사항: 용량(DBA_SEGMENTS)·통계 정확도를 위해
GRANT SELECT ON sys.dba_segments TO app_reader;   -- 없으면 BLOCKS × 8KB 로 추정
GRANT SELECT_CATALOG_ROLE TO app_reader;          -- 정책상 허용될 때만
```

사이드바의 계정 배지가 접속 계정의 권한을 점검해 **읽기 전용 계정 / 쓰기 권한 감지** 를 표시합니다
(`SESSION_PRIVS`, `SESSION_ROLES`, 소유 객체, `ALL_TAB_PRIVS` 의 DML 권한 기준).

## 안전장치

- **대용량 조회**: 데이터 뷰는 `OFFSET … FETCH NEXT n ROWS` 로 한 페이지(기본 100행, 최대 `PAGE_MAX_ROWS`)만 가져옵니다.
  전체 건수는 기본으로 세지 않고 통계의 `NUM_ROWS` 를 보여 주며, "정확한 건수 세기" 를 눌렀을 때만 `COUNT(*)` 를 실행합니다.
  페이지가 흔들리지 않도록 PK(없으면 ROWID)로 보조 정렬합니다.
- **SQL 워크벤치**: `SELECT`/`WITH` 단일 문장만 허용합니다. DML/DDL, `FOR UPDATE`, PL/SQL 블록, `WITH FUNCTION`,
  `DBMS_*`/`UTL_*` 패키지, DB 링크(`@`, `ALLOW_DB_LINKS=true` 로 허용 가능)를 거부합니다.
  실행 시간 제한(`QUERY_TIMEOUT_SEC`, 드라이버 `call_timeout`), 최대 반환 행(`SQL_MAX_ROWS`), 동시 실행 수(`SQL_CONCURRENCY`)가 적용됩니다.
- **CSV 내보내기**: 서버에서 배치로 스트리밍하며 최대 `EXPORT_MAX_ROWS` 행까지 씁니다 (Excel 호환 UTF-8 BOM).
- 사용자 입력 값은 모두 바인드 변수로 전달하고, 테이블·컬럼 이름은 딕셔너리에 존재하는 것만 따옴표로 감싸 사용합니다.

## 프로파일의 출처 구분

비용이 다른 네 가지 출처를 화면에 배지로 구분해 보여 줍니다.

| 출처 | 데이터 | 비용 |
| --- | --- | --- |
| 메타데이터 | `ALL_OBJECTS`, `DBA_SEGMENTS`, `ALL_TAB_MODIFICATIONS` (생성·DDL 시각, 용량, 통계 이후 변경량) | 거의 없음 |
| 기존 통계 | `ALL_TABLES`, `ALL_TAB_COL_STATISTICS`, `ALL_TAB_HISTOGRAMS` (행 수, NULL 수, NDV, LOW/HIGH, 히스토그램) | 거의 없음, 마지막 수집 시점 기준 |
| 샘플링 | `SAMPLE (p) SEED (7)` 로 약 `SAMPLE_TARGET_ROWS` 행, 고유값은 `APPROX_COUNT_DISTINCT` | 낮음, 근사치 |
| 정확 | 전체 스캔, `COUNT(DISTINCT)` (확인 대화상자 후 실행, `EXACT_PROFILE_TIMEOUT_SEC`) | 높음 |

## 데모 모드 (Oracle 없이 실행)

`ORACLE_*` 가 비어 있으면 `backend/data/demo.duckdb` 를 만들어 사용합니다 (첫 실행 시 약 10초).
DuckDB 안에 Oracle 데이터 딕셔너리(`ALL_USERS`, `ALL_TABLES`, `ALL_TAB_COLUMNS`, `ALL_CONSTRAINTS`, `ALL_TAB_COL_STATISTICS`,
`ALL_TAB_HISTOGRAMS` 등)를 같은 컬럼 구성으로 재현하고, HR / INVENTORY / SALES / ANALYTICS 4개 Owner 에 약 700만 행을 넣었습니다.
Owner 간 FK, 오래된 통계, 통계 미수집 테이블, PK 없는 테이블, UNUSABLE 인덱스 같은 품질 이슈도 일부러 포함되어 있습니다.
앱의 딕셔너리 SQL 은 Oracle 문법 그대로이며 데모 모드에서도 같은 SQL 이 실행됩니다.

```powershell
cd backend
.\.venv\Scripts\python smoke_test.py   # 모든 API 를 한 번씩 호출해 보는 점검 스크립트 (데모 모드)
```

### 데모로 검증하지 못한 부분

데모는 DuckDB 이므로 다음 Oracle 전용 동작은 실제 Oracle 에서 처음 실행할 때 확인이 필요합니다.

- `SAMPLE (p) SEED (n)` 샘플링, `DBMS_LOB.SUBSTR` 로 CLOB 미리보기
- `call_timeout` 에 의한 쿼리 중단, `SET TRANSACTION READ ONLY`
- `DBA_SEGMENTS`·`ALL_TAB_MODIFICATIONS` 조회 권한 (없으면 추정치/빈 값으로 대체)
- `ALL_TAB_COL_STATISTICS.LOW_VALUE/HIGH_VALUE` RAW 디코딩 (NUMBER·DATE·문자 지원, 그 외 타입은 표시하지 않음)

## 환경 변수 (`backend/.env`)

| 변수 | 기본값 | 설명 |
| --- | --- | --- |
| `INCLUDE_OWNERS` / `EXCLUDE_OWNERS` | (비움) | 보여 줄 Owner 를 쉼표로 지정 / 숨길 Owner |
| `QUERY_TIMEOUT_SEC` | 30 | 일반 쿼리 시간 제한 |
| `EXPORT_TIMEOUT_SEC` | 300 | CSV 내보내기 시간 제한 |
| `EXACT_PROFILE_TIMEOUT_SEC` | 120 | 정확 프로파일 시간 제한 |
| `SQL_MAX_ROWS` | 10000 | SQL 워크벤치 화면 최대 행 |
| `EXPORT_MAX_ROWS` | 1000000 | CSV 최대 행 |
| `PAGE_MAX_ROWS` | 500 | 데이터 뷰 페이지 최대 크기 |
| `SQL_CONCURRENCY` | 4 | 동시 실행 SQL 수 |
| `SAMPLE_TARGET_ROWS` | 100000 | 샘플 프로파일 목표 행 수 |
| `METADATA_CACHE_SEC` | 300 | 딕셔너리 조회 캐시 (사이드바 ⟳ 로 비움) |
| `ALLOW_DB_LINKS` | false | SQL 워크벤치에서 DB 링크 허용 |

## 구조

```
backend/app/
  main.py          FastAPI 엔드포인트
  executor.py      Oracle / DuckDB(데모) 실행기 — 시간 제한, 읽기 전용 트랜잭션, 스트리밍
  sql_guard.py     SQL 워크벤치 문장 검사
  dictionary.py    Owner·객체·컬럼·키·인덱스 (ALL_* 뷰)
  data.py          페이지 조회·필터·정렬·건수 SQL 생성
  profiler.py      메타데이터·통계·샘플·정확 프로파일, 분포
  relations.py     ERD, 관련 테이블, 전체 검색, 유사 이름, 계정 점검
  oracle_raw.py    통계 LOW/HIGH RAW 값 디코딩
  demo_setup.py    데모 DB 생성
frontend/src/
  App.tsx                     사이드바(연결 상태·즐겨찾기·최근 조회)와 화면 전환
  components/OwnerExplorer    ①   DataViewer·StructurePanel ②   SqlWorkbench ③
  components/Profiler         ④   SchemaMap·RelationsPanel·ErdCanvas ⑤   GlobalSearch ⑥
```

즐겨찾기, 최근 조회, SQL 실행 이력, 즐겨찾기 쿼리는 브라우저 `localStorage` 에 저장됩니다.
