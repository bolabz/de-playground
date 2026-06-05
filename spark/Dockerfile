# Custom Spark image for the standalone cluster: official Apache Spark with the Delta Lake
# and S3A jars baked into /opt/spark/jars. Executors need these jars on their classpath to
# read/write Delta on SeaweedFS; baking them in avoids a runtime Ivy download on every worker
# and removes the need for --packages at submit time.
#
# Versions matched to Spark 3.5 (Scala 2.12) + the Hadoop 3.3.4 it bundles:
#   delta-spark_2.12 3.2.1 (+ delta-storage 3.2.1), hadoop-aws 3.3.4, aws-java-sdk-bundle 1.12.262
FROM apache/spark:3.5.8-scala2.12-java17-python3-ubuntu

USER root

# Delta + S3A jars (ADD fetches from Maven Central; no curl/wget needed in the image).
ADD https://repo1.maven.org/maven2/io/delta/delta-spark_2.12/3.2.1/delta-spark_2.12-3.2.1.jar /opt/spark/jars/
ADD https://repo1.maven.org/maven2/io/delta/delta-storage/3.2.1/delta-storage-3.2.1.jar /opt/spark/jars/
ADD https://repo1.maven.org/maven2/org/apache/hadoop/hadoop-aws/3.3.4/hadoop-aws-3.3.4.jar /opt/spark/jars/
ADD https://repo1.maven.org/maven2/com/amazonaws/aws-java-sdk-bundle/1.12.262/aws-java-sdk-bundle-1.12.262.jar /opt/spark/jars/

# Python deps the DRIVER imports (de_playground.config -> pydantic-settings;
# de_playground.common.lake -> boto3). Executors run pure DataFrame ops, so they don't
# import de_playground at all — but the driver (client mode) does. Jars made world-readable
# so the non-root `spark` user can load them.
RUN python3 -m pip install --no-cache-dir boto3 pydantic-settings \
    && chmod -R a+r /opt/spark/jars

# Prometheus metrics sink (scraped by the observability profile at /metrics/prometheus).
COPY metrics.properties /opt/spark/conf/metrics.properties

USER spark
