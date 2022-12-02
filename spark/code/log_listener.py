from pyspark.sql import SparkSession
from pyspark.sql.functions import *
from pyspark.sql.types import *
from cassandra.cluster import Cluster
import time
import cassandra.amdlm_cassandra_configs as ccfg

# Wait kafka and spark to start
time.sleep(15)

# Attach to cassandra
cluster = Cluster(['my-cassandra'], port=9042)
session = cluster.connect()

# Initialize keyspace abd table
session.execute(f"create ${ccfg.keyspace} IF NOT EXISTS metrics with replication = "
                "{'class' : 'SimpleStrategy', 'replication_factor':1}")
session.execute(f"use ${ccfg.keyspace}")

session.execute("""
CREATE TABLE IF NOT EXISTS logs (
 timestamp timestamp,
 level text,
 microservice_id text,
 operation_type text,
 action_id text
 user_id text,
 value int,
 PRIMARY KEY(action_id)
);""")

scala_version = '2.12'
spark_version = '3.3.1'
packages = [
    f'org.apache.spark:spark-sql-kafka-0-10_{scala_version}:{spark_version}',
    'org.apache.kafka:kafka-clients:3.3.1',
    f'com.datastax.spark:spark-cassandra-connector_{scala_version}:{spark_version}'
]

spark = SparkSession.builder\
    .master("spark://my-spark-master:7077")\
    .appName("kafka-log-spark")\
    .config("spark.jars.packages", ",".join(packages))\
    .getOrCreate()


print(spark)

topic = 'logs'


kafkaDF = spark \
            .readStream \
            .format("kafka") \
            .option("kafka.bootstrap.servers", "my-kafka:9092") \
            .option("subscribe", topic) \
            .option("startingOffsets", "earliest") \
            .option("failOnDataLoss", "false") \
            .load() \
            .selectExpr("CAST(value AS STRING)") 


schema = StructType([
    StructField("timestamp", TimestampType(), True),
    StructField("level", StringType(), True),
    StructField("microservice_id", StringType(), True),
    StructField("operation_type", StringType(), True),
    StructField("action_id", StringType(), True),
    StructField("user_id", StringType(), True)
])

query = kafkaDF.select(from_json(col("value"), schema).alias("t")) \
            .select("t.timestamp", "t.level", "t.microservice_id", "t.operation_type", "t.action_id", "t.user_id")\
            .writeStream\
            .option("checkpointLocation", '/code/checkpoints/')\
            .format("org.apache.spark.sql.cassandra")\
            .option("keyspace", "metrics")\
            .option("table", "data_table")\
            .trigger(processingTime='30 seconds') \
            .start()\
            .awaitTermination()