"""Which WideWorldImporters tables we extract, and how to load them incrementally.

Scope for Phase 1: the four Sales transactional tables that form the sales fact core.
All four carry `LastEditedWhen datetime2(7) NOT NULL DEFAULT sysdatetime()`, which we use
as the incremental high-watermark cursor.

To add a table later: append a TableSpec. Note that WWI's *temporal* dimension tables
(e.g. Sales.Customers, Warehouse.StockItems) don't have LastEditedWhen — their system
period column `ValidFrom` is the right cursor, so set cursor="ValidFrom" for those.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TableSpec:
    schema: str
    table: str
    primary_key: str
    cursor: str = "LastEditedWhen"

    @property
    def resource_name(self) -> str:
        # dlt resource + bronze folder name, e.g. "sales_orders"
        return f"{self.schema}_{self.table}".lower()


WWI_TABLES: list[TableSpec] = [
    TableSpec("Sales", "Orders", primary_key="OrderID"),
    TableSpec("Sales", "OrderLines", primary_key="OrderLineID"),
    TableSpec("Sales", "Invoices", primary_key="InvoiceID"),
    TableSpec("Sales", "InvoiceLines", primary_key="InvoiceLineID"),
]
