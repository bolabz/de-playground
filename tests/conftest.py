"""Shared pytest fixtures."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

# Local-mode SparkSession fixture — opt-in via the `pyspark` marker. Spark 3.5 supports
# Java 8/11/17 ONLY (newer JVMs crash on JavaSparkContext init with Py4JJavaError); the
# fixture detects + pins JDK 17 itself so `uv run pytest -m pyspark` Just Works on a host
# with `brew install openjdk@17` regardless of what the system default `java` is. Mirrors
# the Makefile's JAVA17 macro so the make targets and the pytest invocation agree.


def _detect_java17_home() -> str | None:
    """Find a JDK 17 install on the host. Returns its JAVA_HOME, or None.

    Order — same as the Makefile's JAVA17:
      1. macOS's `/usr/libexec/java_home -v 17` (the canonical Apple registry).
      2. Homebrew's keg-only `openjdk@17` (which java_home doesn't see).
    """
    if shutil.which("/usr/libexec/java_home"):
        try:
            out = subprocess.run(
                ["/usr/libexec/java_home", "-v", "17"],
                capture_output=True,
                text=True,
                check=True,
            )
            home = out.stdout.strip()
            if home and Path(home, "bin", "java").exists():
                return home
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

    brew = shutil.which("brew")
    if brew:
        try:
            # `brew` resolved to its full path via shutil.which above; S607 (partial
            # exec path) would fire on a bare "brew" arg but this is the resolved one.
            prefix = subprocess.run(  # noqa: S603
                [brew, "--prefix", "openjdk@17"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            if prefix:
                home = f"{prefix}/libexec/openjdk.jdk/Contents/Home"
                if Path(home, "bin", "java").exists():
                    return home
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

    return None


@pytest.fixture(scope="session")
def spark():
    pytest.importorskip("pyspark")

    # Pin JDK 17 BEFORE pyspark.sql imports SparkSession — getOrCreate() reads JAVA_HOME
    # to find the JVM. If detection finds JDK 17, override (matches Makefile behavior:
    # the shell `java` could be 21+ and Spark 3.5 doesn't support it). If detection
    # finds nothing AND JAVA_HOME is already set (e.g. CI's actions/setup-java exported
    # it, or a Linux dev set it by hand), trust that and let it fly.
    java_home = _detect_java17_home()
    if java_home:
        os.environ["JAVA_HOME"] = java_home
    elif not os.environ.get("JAVA_HOME"):
        pytest.fail(
            "JDK 17 not found on host. Spark 3.5 supports Java 8/11/17 only; install "
            "JDK 17 (Apple Silicon: `brew install openjdk@17`; Linux: install your "
            "distro's openjdk-17 package) or set JAVA_HOME to an existing JDK 17 "
            "install before running `pytest -m pyspark`."
        )

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
