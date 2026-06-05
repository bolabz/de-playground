"""Silver -> Gold: curated sales marts (ordered demand + billed revenue).

Delta tables:
  * fact_sales       — ORDERED: order-line grain, orders joined onto lines, revenue measures,
                       partitioned by order year/month.
  * agg_sales_daily  — daily ordered roll-up.
  * fact_invoices    — BILLED: invoice-line grain, invoices joined onto invoice lines, the same
                       revenue measures plus line_profit (invoices carry cost, orders don't) and
                       an is_credit_note flag, partitioned by invoice year/month.
  * agg_billed_daily — daily billed roll-up (incl. profit).

Ordered (demand) vs billed (actuals) is the classic sales-mart pair. Gold is rebuilt in full
from Silver (overwrite), so it's safe to re-run. The group-bys are shuffles — watch :4040.
"""

from __future__ import annotations

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from ..common.lake import ensure_bucket, s3a
from ..common.logging import get_logger
from ..config import settings

log = get_logger(__name__)


def build_fact_sales(orders: DataFrame, lines: DataFrame) -> DataFrame:
    """Order-line grain fact with revenue measures. Pure (unit-testable)."""
    o = orders.select("order_id", "customer_id", "salesperson_person_id", "order_date")
    line = lines.select(
        "order_line_id",
        "order_id",
        "stock_item_id",
        "description",
        "quantity",
        "unit_price",
        "tax_rate",
        "picked_quantity",
    )
    return (
        line.join(o, on="order_id", how="inner")
        .withColumn("extended_price", F.col("quantity") * F.col("unit_price"))
        .withColumn("tax_amount", F.col("extended_price") * F.col("tax_rate") / F.lit(100))
        .withColumn("line_total", F.col("extended_price") + F.col("tax_amount"))
        .withColumn("order_year", F.year("order_date"))
        .withColumn("order_month", F.month("order_date"))
    )


def build_daily_agg(fact: DataFrame) -> DataFrame:
    """Daily sales roll-up. Pure (unit-testable)."""
    return (
        fact.groupBy("order_date")
        .agg(
            F.countDistinct("order_id").alias("num_orders"),
            F.count(F.lit(1)).alias("num_lines"),
            F.sum("quantity").alias("total_quantity"),
            F.round(F.sum("line_total"), 2).alias("total_revenue"),
        )
        .orderBy("order_date")
    )


def build_fact_invoices(invoices: DataFrame, invoice_lines: DataFrame) -> DataFrame:
    """Invoice-line grain billed-revenue fact. Pure (unit-testable).

    Measures are computed the same way as fact_sales so ordered vs billed compare apples to
    apples; line_profit comes straight from the source (orders have no cost, so no profit).
    """
    inv = invoices.select(
        "invoice_id",
        "customer_id",
        "salesperson_person_id",
        "invoice_date",
        "is_credit_note",
    )
    line = invoice_lines.select(
        "invoice_line_id",
        "invoice_id",
        "stock_item_id",
        "description",
        "quantity",
        "unit_price",
        "tax_rate",
        "line_profit",
    )
    return (
        line.join(inv, on="invoice_id", how="inner")
        .withColumn("extended_price", F.col("quantity") * F.col("unit_price"))
        .withColumn("tax_amount", F.col("extended_price") * F.col("tax_rate") / F.lit(100))
        .withColumn("line_total", F.col("extended_price") + F.col("tax_amount"))
        .withColumn("invoice_year", F.year("invoice_date"))
        .withColumn("invoice_month", F.month("invoice_date"))
    )


def build_billed_daily_agg(fact: DataFrame) -> DataFrame:
    """Daily billed roll-up (incl. profit). Pure (unit-testable)."""
    return (
        fact.groupBy("invoice_date")
        .agg(
            F.countDistinct("invoice_id").alias("num_invoices"),
            F.count(F.lit(1)).alias("num_lines"),
            F.sum("quantity").alias("total_quantity"),
            F.round(F.sum("line_total"), 2).alias("total_revenue"),
            F.round(F.sum("line_profit"), 2).alias("total_profit"),
        )
        .orderBy("invoice_date")
    )


def build_gold(spark: SparkSession) -> None:
    ensure_bucket(settings.gold_bucket)

    # ---- ORDERED: fact_sales + daily agg ----
    orders = spark.read.format("delta").load(s3a(settings.silver_bucket, "wwi", "sales_orders"))
    lines = spark.read.format("delta").load(s3a(settings.silver_bucket, "wwi", "sales_orderlines"))
    fact = build_fact_sales(orders, lines).cache()  # reused by both writes

    fact_dst = s3a(settings.gold_bucket, "wwi", "fact_sales")
    fact.write.format("delta").mode("overwrite").partitionBy("order_year", "order_month").save(
        fact_dst
    )
    log.info(
        "gold table written",
        extra={"table": "fact_sales", "rows": fact.count(), "destination": fact_dst},
    )

    agg = build_daily_agg(fact)
    agg_dst = s3a(settings.gold_bucket, "wwi", "agg_sales_daily")
    agg.write.format("delta").mode("overwrite").save(agg_dst)
    log.info(
        "gold table written",
        extra={"table": "agg_sales_daily", "rows": agg.count(), "destination": agg_dst},
    )
    fact.unpersist()

    # ---- BILLED: fact_invoices + daily agg ----
    invoices = spark.read.format("delta").load(s3a(settings.silver_bucket, "wwi", "sales_invoices"))
    invoice_lines = spark.read.format("delta").load(
        s3a(settings.silver_bucket, "wwi", "sales_invoicelines")
    )
    fact_inv = build_fact_invoices(invoices, invoice_lines).cache()

    inv_dst = s3a(settings.gold_bucket, "wwi", "fact_invoices")
    fact_inv.write.format("delta").mode("overwrite").partitionBy(
        "invoice_year", "invoice_month"
    ).save(inv_dst)
    log.info(
        "gold table written",
        extra={"table": "fact_invoices", "rows": fact_inv.count(), "destination": inv_dst},
    )

    billed = build_billed_daily_agg(fact_inv)
    billed_dst = s3a(settings.gold_bucket, "wwi", "agg_billed_daily")
    billed.write.format("delta").mode("overwrite").save(billed_dst)
    log.info(
        "gold table written",
        extra={"table": "agg_billed_daily", "rows": billed.count(), "destination": billed_dst},
    )
    fact_inv.unpersist()
