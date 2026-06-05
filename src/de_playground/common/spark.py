"""SparkSession factories wired for Delta Lake + SeaweedFS (S3A).

Two ways to run the same transform code:

* get_spark()         — LOCAL mode (pip-installed Spark). `configure_spark_with_delta_pip`
                        Ivy-fetches the Delta jar matching the installed delta-spark, plus we
                        add the S3A jars. Simplest to run solo.
* get_cluster_spark() — CLUSTER mode: submit to the standalone Spark cluster. The Delta + S3A
                        jars are baked into the Spark image (see spark/Dockerfile), so there's
                        no Ivy download and no --packages — the executors already have them.

The S3A + Delta config is identical either way; only jar provisioning and the master differ.
The `from delta import ...` is imported lazily inside get_spark so that importing this module
(e.g. on the cluster driver, which has no delta-spark Python package) doesn't require it.
"""

from __future__ import annotations

from pyspark.sql import SparkSession

from ..config import settings

# Hadoop 3.3.4 ships with Spark 3.5; the S3A jars must match it.
_S3A_PACKAGES = [
    "org.apache.hadoop:hadoop-aws:3.3.4",
    "com.amazonaws:aws-java-sdk-bundle:1.12.262",
]


def _base_builder(app_name: str, master: str) -> SparkSession.Builder:
    """Shared config: Delta SQL extensions + S3A pointed at SeaweedFS."""
    return (
        SparkSession.builder.appName(app_name)
        .master(master)
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config(
            "spark.sql.catalog.spark_catalog",
            "org.apache.spark.sql.delta.catalog.DeltaCatalog",
        )
        .config("spark.hadoop.fs.s3a.endpoint", settings.s3_endpoint_url)
        .config("spark.hadoop.fs.s3a.access.key", settings.s3_access_key)
        .config("spark.hadoop.fs.s3a.secret.key", settings.s3_secret_key)
        .config("spark.hadoop.fs.s3a.path.style.access", "true")
        .config("spark.hadoop.fs.s3a.connection.ssl.enabled", "false")
        .config(
            "spark.hadoop.fs.s3a.aws.credentials.provider",
            "org.apache.hadoop.fs.s3a.SimpleAWSCredentialsProvider",
        )
        .config("spark.sql.session.timeZone", "UTC")
    )


def get_spark(app_name: str = "de-playground", master: str = "local[*]") -> SparkSession:
    """Local mode: jars resolved via Ivy from the pip-installed delta-spark."""
    from delta import configure_spark_with_delta_pip  # lazy: only needed locally

    builder = _base_builder(app_name, master)
    spark = configure_spark_with_delta_pip(builder, extra_packages=_S3A_PACKAGES).getOrCreate()
    spark.sparkContext.setLogLevel("WARN")
    return spark


def get_cluster_spark(app_name: str = "de-playground") -> SparkSession:
    """Cluster mode: master from SPARK_MASTER_URL; jars are baked into the Spark image."""
    spark = _base_builder(app_name, settings.spark_master_url).getOrCreate()
    spark.sparkContext.setLogLevel("WARN")
    return spark
