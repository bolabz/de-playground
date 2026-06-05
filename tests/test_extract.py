"""DB-free unit tests for the Phase 1 extract.

These exercise config/wiring logic that must not require a live SQL Server or SeaweedFS:
table specs and the SQLAlchemy URL builder. The actual data movement is verified by
running `make extract` against the live stack.
"""

from __future__ import annotations

from de_playground.config import settings
from de_playground.extract.tables import WWI_TABLES


def test_table_specs_are_present_and_unique():
    assert WWI_TABLES, "expected at least one table to extract"
    names = [t.resource_name for t in WWI_TABLES]
    assert len(names) == len(set(names)), "resource names must be unique"


def test_resource_name_format():
    sales_orders = next(t for t in WWI_TABLES if t.table == "Orders")
    assert sales_orders.resource_name == "sales_orders"
    assert sales_orders.cursor == "LastEditedWhen"
    assert sales_orders.primary_key == "OrderID"


def test_mssql_url_is_well_formed():
    url = settings.mssql_url
    assert url.startswith("mssql+pyodbc://")
    assert "ODBC+Driver+18+for+SQL+Server" in url
    assert "TrustServerCertificate=yes" in url
    # database name from defaults
    assert "WideWorldImporters" in url
    # the pipeline connects as the least-privilege login, never sa
    assert "de_extract" in url
