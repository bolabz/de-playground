"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

# Local-mode SparkSession fixture — opt-in via the `pyspark` marker. JDK 17 must be on the
# host (`brew install openjdk@17`); CI's opt-in `pyspark` job installs it. Default CI stays
# Java-free, so this fixture (and any test that uses it) is skipped by addopts.


@pytest.fixture(scope="session")
def spark():
    pyspark = pytest.importorskip("pyspark")
    from pyspark.sql import SparkSession

    s = (
        SparkSession.builder.master("local[2]")  # type: ignore[attr-defined]
        .appName("de-playground-tests")
        .config("spark.ui.enabled", "false")
        .config("spark.sql.shuffle.partitions", "2")
        .getOrCreate()
    )
    yield s
    s.stop()
    del pyspark
