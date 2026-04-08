import json, subprocess, sys

PROJECT="synexis-project-sentinel"
VIEW="synexis-project-sentinel.sentinel_mart.fusion_hypotheses_aoi_view_v2"
TOPIC="fusion.hypotheses"

sql=f"""
SELECT TO_JSON_STRING(t) AS msg
FROM (
  SELECT AS STRUCT *
  FROM `{VIEW}`
  ORDER BY 1
  LIMIT 50
) t
"""

cmd=["bq","query","--use_legacy_sql=false","--format=json",sql]

try:
    out = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)
except subprocess.CalledProcessError as e:
    print("BQ QUERY FAILED. Output below:\n")
    print(e.output)
    sys.exit(1)

rows=json.loads(out) if out.strip() else []
if not rows:
    print("No rows from view; nothing to publish.")
    sys.exit(0)

published=0
for r in rows:
    msg=r["msg"]
    subprocess.check_call([
        "gcloud","pubsub","topics","publish",TOPIC,
        "--message",msg,
        "--project",PROJECT
    ])
    published += 1

print(f"Published {published} messages to {TOPIC}.")
