import json, subprocess, sys

PROJECT="synexis-project-sentinel"
TOPIC="fusion.hypotheses"

sql = r"""
SELECT TO_JSON_STRING(STRUCT(
  aoi_id,
  type,
  confidence,
  src,
  headline,
  event_sent,
  event_url,
  src_event_id,
  hypo_id,
  details
)) AS msg
FROM `synexis-project-sentinel.sentinel_core.hypotheses_current`
LIMIT 50
"""

out = subprocess.check_output(
    ["bq","query","--use_legacy_sql=false","--format=json",sql],
    text=True, stderr=subprocess.STDOUT
)
rows = json.loads(out) if out.strip() else []

if not rows:
    print("No rows in hypotheses_current to publish.")
    sys.exit(0)

published = 0
for r in rows:
    msg = r["msg"]
    subprocess.check_call([
        "gcloud","pubsub","topics","publish",TOPIC,
        "--message",msg,
        "--project",PROJECT
    ])
    published += 1

print(f"Published {published} messages to {TOPIC}.")
