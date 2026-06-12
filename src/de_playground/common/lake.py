"""Lake helpers: bucket management + s3a path construction.

Spark talks to SeaweedFS via the s3a:// scheme (the Hadoop S3 client). These helpers keep
bucket names and path layout in one place so Silver/Gold code reads cleanly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError, EndpointConnectionError

from de_playground.common.logging import get_logger
from de_playground.common.retry import retry_until
from de_playground.config import settings

if TYPE_CHECKING:
    import pyarrow.fs as pafs
    from mypy_boto3_s3 import S3Client

log = get_logger(__name__)


def s3_client(admin: bool = False) -> S3Client:
    """boto3 S3 client for SeaweedFS (path-style).

    `admin=True` uses admin creds (bucket creation / management); the default uses the
    least-privilege app identity (Read/Write/List) the pipeline runs as.

    Return type is `mypy_boto3_s3.S3Client` (provided by the `boto3-stubs` dep, WS1) so
    callers get full method/parameter completion at the typed boundary.
    """
    if admin:
        import os

        key = os.environ.get("S3_ADMIN_ACCESS_KEY", "adminaccesskey")
        secret = os.environ.get("S3_ADMIN_SECRET_KEY", "adminsecretkey")
    else:
        key, secret = settings.s3_access_key, settings.s3_secret_key
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=key,
        aws_secret_access_key=secret,
        config=Config(s3={"addressing_style": "path"}),  # SeaweedFS needs path-style
        region_name="us-east-1",
    )


def bucket_exists(name: str) -> bool:
    """True if the bucket exists and is reachable.

    Uses head_bucket (a per-bucket check) rather than list_buckets, so it works under the
    least-privilege app identity without global/admin list rights. Retries on connection
    refusal to wait out SeaweedFS's startup race.
    """
    s3 = s3_client()
    try:
        retry_until(
            lambda: s3.head_bucket(Bucket=name),
            exceptions=(EndpointConnectionError,),
        )
        return True
    except ClientError as err:
        if err.response.get("Error", {}).get("Code") in ("404", "NoSuchBucket", "NotFound"):
            return False
        raise


def ensure_bucket(name: str) -> None:
    """Assert a bucket exists. The pipeline runs as the least-privilege app identity (no
    bucket-management rights), so creation is a separate admin step (`make create-buckets`)."""
    if not bucket_exists(name):
        raise RuntimeError(
            f"bucket '{name}' does not exist — run `make create-buckets` first "
            "(the pipeline's app identity can't create buckets, by design)"
        )


def create_buckets() -> None:
    """One-time setup (admin identity): create the medallion buckets if missing."""
    admin = s3_client(admin=True)
    for bucket in (settings.bronze_bucket, settings.silver_bucket, settings.gold_bucket):
        if bucket_exists(bucket):
            log.info("bucket already exists", extra={"bucket": bucket})
        else:
            admin.create_bucket(Bucket=bucket)
            log.info("bucket created", extra={"bucket": bucket})


if __name__ == "__main__":  # `python -m de_playground.common.lake` -> create buckets
    create_buckets()


def s3a(bucket: str, *parts: str) -> str:
    """Build an s3a:// URI, e.g. s3a('silver', 'wwi', 'sales_orders')."""
    suffix = "/".join(p.strip("/") for p in parts)
    return f"s3a://{bucket}/{suffix}" if suffix else f"s3a://{bucket}"


def pyarrow_s3() -> pafs.S3FileSystem:
    """A pyarrow S3 filesystem pointed at SeaweedFS (for reading Bronze Parquet)."""
    import pyarrow.fs as pafs  # lazy: pyarrow only needed by readers

    host = settings.s3_endpoint_url.split("://", 1)[-1]  # strip scheme -> host:port
    scheme = "https" if settings.s3_endpoint_url.startswith("https") else "http"
    return pafs.S3FileSystem(
        access_key=settings.s3_access_key,
        secret_key=settings.s3_secret_key,
        endpoint_override=host,
        scheme=scheme,
    )


def bronze_cdc_prefix_exists(table: str) -> bool:
    """True if `bronze/wwi_cdc/<table>/` contains any objects.

    Used by `silver_cdc` to skip tables that had no CDC changes captured yet — replaces
    the previous string-match-on-exception-message check in silver_cdc.py (WS4 6b).
    """
    s3 = s3_client()
    resp = s3.list_objects_v2(
        Bucket=settings.bronze_bucket,
        Prefix=f"wwi_cdc/{table}/",
        MaxKeys=1,
    )
    return "Contents" in resp and bool(resp["Contents"])


def delta_storage_options() -> dict[str, str]:
    """storage_options for delta-rs reads/writes against SeaweedFS (path-style, http)."""
    return {
        "AWS_ACCESS_KEY_ID": settings.s3_access_key,
        "AWS_SECRET_ACCESS_KEY": settings.s3_secret_key,
        "AWS_ENDPOINT_URL": settings.s3_endpoint_url,
        "AWS_REGION": "us-east-1",
        "AWS_ALLOW_HTTP": "true",
    }
