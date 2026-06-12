"""Typed, 12-factor configuration loaded from environment (.env).

Every connection string and credential the pipeline needs lives here, read from the
environment via pydantic-settings. On Azure these same values come from Key Vault /
managed identity instead of a .env file — the code that *reads* Settings stays identical.

Least privilege: the pipeline connects to SQL Server as a dedicated, SELECT-only login
(`mssql_app_*`), NOT as `sa`. The `sa` password is here only so the *admin* shell scripts
(restore, enable-cdc, create-app-login) can read it from one place; no Python path uses it.
All defaults below are LOCAL-ONLY placeholders — real values come from a gitignored .env.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ---- Source: SQL Server / WideWorldImporters (OLTP) ----
    mssql_host: str = "localhost"
    mssql_port: int = 1433
    mssql_db: str = "WideWorldImporters"
    # Least-privilege login the PIPELINE uses (created by sql/create_app_login.sql).
    mssql_app_user: str = "de_extract"
    mssql_app_password: str = "Change_me_app_passw0rd"  # noqa: S105 - LOCAL-ONLY placeholder
    # Admin password — used by the admin shell scripts only, never by Python.
    mssql_sa_password: str = "Change_me_strong_passw0rd"  # noqa: S105 - LOCAL-ONLY placeholder

    # ---- Lake: SeaweedFS (S3-compatible) ----
    # The pipeline uses the least-privilege "app" identity (Read/Write/List, no Admin).
    s3_endpoint_url: str = "http://localhost:8333"
    s3_access_key: str = "appaccesskey"  # LOCAL-ONLY placeholder
    s3_secret_key: str = "appsecretkey"  # noqa: S105 - LOCAL-ONLY placeholder
    bronze_bucket: str = "bronze"
    silver_bucket: str = "silver"
    gold_bucket: str = "gold"

    # ---- Processing: Spark ----
    spark_master_url: str = "spark://localhost:7077"

    # ---- Serving: Elasticsearch ----
    es_url: str = "http://localhost:9200"

    @property
    def mssql_url(self) -> str:
        """SQLAlchemy URL for the pipeline's least-privilege login (ODBC Driver 18)."""
        from sqlalchemy.engine import URL  # lazy: keeps config import light

        return URL.create(
            "mssql+pyodbc",
            username=self.mssql_app_user,
            password=self.mssql_app_password,
            host=self.mssql_host,
            port=self.mssql_port,
            database=self.mssql_db,
            query={
                "driver": "ODBC Driver 18 for SQL Server",
                "TrustServerCertificate": "yes",
            },
        ).render_as_string(hide_password=False)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached factory — same semantics as the previous module-level singleton, but
    tests can override via `get_settings.cache_clear()` (then monkeypatch the env or
    `Settings`). Nothing runs at import time; the first call materializes the instance.
    WS4 (DI seam) — full constructor injection is P2 (WS9)."""
    return Settings()


def __getattr__(name: str) -> Settings:
    """Module-level `__getattr__` (PEP 562) preserves `from de_playground.config import
    settings` for ad-hoc consumers (scripts, REPL) that haven't migrated to the factory.
    The first lookup triggers `get_settings()` lazily — so even this fallback doesn't
    run at import time. In-tree consumers all call `get_settings()` explicitly so they
    pick up test overrides.
    """
    if name == "settings":
        return get_settings()
    raise AttributeError(f"module 'de_playground.config' has no attribute {name!r}")
