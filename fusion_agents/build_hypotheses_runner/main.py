import os
from google.cloud import bigquery
from flask import Flask, jsonify

PROJECT = os.getenv("PROJECT", "synexis-project-sentinel")
DATASET = os.getenv("DATASET", "sentinel_core")
PROC    = f"`{PROJECT}.{DATASET}.sp_build_hypotheses`()"

app = Flask(__name__)
bq = bigquery.Client(project=PROJECT)

@app.get("/")
def handler():
    job = bq.query(f"CALL {PROC};")
    job.result()
    return jsonify(ok=True, ran="sp_build_hypotheses")

# GCF entrypoint
def run(request):
    return handler()
