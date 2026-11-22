# Databricks notebook source
# MAGIC %md
# MAGIC # 02 · Transform: Volume JSON → bronze → silver
# MAGIC - `bronze.documents_raw`: one row per CAP case file, raw JSON as text
# MAGIC - `silver.documents`: one clean row per case (metadata + full text)
# MAGIC - `silver.chunks`: ~3,000-character overlapping chunks for Vector Search (Change Data Feed on)

# COMMAND ----------

dbutils.widgets.text("catalog", "legal_demo")
dbutils.widgets.text("code_path", "/Volumes/legal_demo/raw/code/dev")
catalog = dbutils.widgets.get("catalog")

import json
import sys

# Shared code is copied to a Volume by scripts/push_code.sh. (Bundle workspace files often fail
# to read with "[Errno 5] Input/output error" right after a deploy on Free Edition.)
sys.path.insert(0, dbutils.widgets.get("code_path"))

from pyspark.sql import functions as F
from pyspark.sql import types as T

from legal_demo.text import case_to_document, document_to_chunks

raw_path = f"/Volumes/{catalog}/raw/cap"

# COMMAND ----------

# MAGIC %md ## Bronze

# COMMAND ----------

bronze = (
    # One row per file. (Pass wholetext as the keyword: on Spark Connect, .option("wholetext", True)
    # arrives as "True", which Spark ignores, and files get split into lines.)
    spark.read.text(f"{raw_path}/ne3d/*/*.json", wholetext=True).select(
        F.col("_metadata.file_path").alias("source_file"),
        F.col("value").alias("raw_json"),
        F.current_timestamp().alias("ingested_at"),
    )
)
bronze.write.mode("overwrite").option("overwriteSchema", True).saveAsTable(
    f"{catalog}.bronze.documents_raw"
)
print("bronze rows:", spark.table(f"{catalog}.bronze.documents_raw").count())

# COMMAND ----------

# MAGIC %md ## Silver documents

# COMMAND ----------

doc_schema = T.StructType(
    [
        T.StructField("doc_id", T.StringType(), False),
        T.StructField("case_name", T.StringType()),
        T.StructField("case_name_short", T.StringType()),
        T.StructField("decision_date", T.DateType()),
        T.StructField("docket_number", T.StringType()),
        T.StructField("citation", T.StringType()),
        T.StructField("court", T.StringType()),
        T.StructField("reporter", T.StringType()),
        T.StructField("volume", T.StringType()),
        T.StructField("parties", T.ArrayType(T.StringType())),
        T.StructField("judges", T.ArrayType(T.StringType())),
        T.StructField("attorneys", T.ArrayType(T.StringType())),
        T.StructField("opinion_types", T.ArrayType(T.StringType())),
        T.StructField("opinion_authors", T.ArrayType(T.StringType())),
        T.StructField("head_matter", T.StringType()),
        T.StructField("full_text", T.StringType()),
        T.StructField("char_count", T.IntegerType()),
        T.StructField("source_url", T.StringType()),
        T.StructField("source_file", T.StringType()),
    ]
)

docs = []
for row in spark.table(f"{catalog}.bronze.documents_raw").collect():
    # .../raw/cap/{reporter}/{volume}/{file_name}.json
    reporter, volume = row.source_file.split("/")[-3:-1]
    docs.append(case_to_document(json.loads(row.raw_json), reporter, volume, row.source_file))

documents = spark.createDataFrame(docs, doc_schema)
documents.write.mode("overwrite").option("overwriteSchema", True).saveAsTable(
    f"{catalog}.silver.documents"
)
spark.sql(
    f"COMMENT ON TABLE {catalog}.silver.documents IS "
    "'Indiana Supreme Court opinions (CAP, N.E.3d): one row per case'"
)
print("documents:", len(docs))

# COMMAND ----------

# MAGIC %md ## Silver chunks
# MAGIC Merged (not overwritten) so the Vector Search index only re-embeds chunks that changed.

# COMMAND ----------

chunk_schema = T.StructType(
    [
        T.StructField("chunk_id", T.StringType(), False),
        T.StructField("doc_id", T.StringType(), False),
        T.StructField("chunk_index", T.IntegerType()),
        T.StructField("case_name_short", T.StringType()),
        T.StructField("decision_date", T.DateType()),
        T.StructField("text", T.StringType()),
    ]
)
chunks = [c for d in docs for c in document_to_chunks(d)]
spark.createDataFrame(chunks, chunk_schema).createOrReplaceTempView("new_chunks")

spark.sql(
    f"""
    CREATE TABLE IF NOT EXISTS {catalog}.silver.chunks (
      chunk_id STRING NOT NULL, doc_id STRING NOT NULL, chunk_index INT,
      case_name_short STRING, decision_date DATE, text STRING
    )
    TBLPROPERTIES (delta.enableChangeDataFeed = true)
    COMMENT 'Overlapping text chunks of silver.documents, source for Vector Search'
    """
)
spark.sql(
    f"""
    MERGE INTO {catalog}.silver.chunks AS t
    USING new_chunks AS s ON t.chunk_id = s.chunk_id
    WHEN MATCHED AND t.text <> s.text THEN UPDATE SET *
    WHEN NOT MATCHED THEN INSERT *
    WHEN NOT MATCHED BY SOURCE THEN DELETE
    """
)
print("chunks:", len(chunks))
