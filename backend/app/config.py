import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def _list(name: str) -> list[str]:
    return [v.strip().upper() for v in os.environ.get(name, "").split(",") if v.strip()]


@dataclass(frozen=True)
class Settings:
    oracle_user: str = os.environ.get("ORACLE_USER", "")
    oracle_password: str = os.environ.get("ORACLE_PASSWORD", "")
    oracle_dsn: str = os.environ.get("ORACLE_DSN", "")
    pool_max: int = _int("ORACLE_POOL_MAX", 8)

    demo_db: Path = Path(os.environ.get("DEMO_DB", BASE_DIR / "data" / "demo.duckdb"))

    query_timeout_sec: int = _int("QUERY_TIMEOUT_SEC", 30)
    export_timeout_sec: int = _int("EXPORT_TIMEOUT_SEC", 300)
    exact_profile_timeout_sec: int = _int("EXACT_PROFILE_TIMEOUT_SEC", 120)
    sql_max_rows: int = _int("SQL_MAX_ROWS", 10_000)
    export_max_rows: int = _int("EXPORT_MAX_ROWS", 1_000_000)
    page_max_rows: int = _int("PAGE_MAX_ROWS", 500)
    sql_concurrency: int = _int("SQL_CONCURRENCY", 4)
    sample_target_rows: int = _int("SAMPLE_TARGET_ROWS", 100_000)
    metadata_cache_sec: int = _int("METADATA_CACHE_SEC", 300)
    allow_db_links: bool = os.environ.get("ALLOW_DB_LINKS", "false").lower() == "true"
    include_owners: list[str] = field(default_factory=lambda: _list("INCLUDE_OWNERS"))
    exclude_owners: list[str] = field(default_factory=lambda: _list("EXCLUDE_OWNERS"))

    @property
    def oracle_enabled(self) -> bool:
        return bool(self.oracle_user and self.oracle_dsn)


settings = Settings()
