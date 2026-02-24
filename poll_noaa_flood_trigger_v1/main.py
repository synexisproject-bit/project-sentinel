import os, json
from datetime import datetime, timezone
from flask import Flask, request
import google.auth
import google.auth.transport.requests
import requests as http_requests

PROJECT = os.environ.get("PROJECT", "synexis-project-sentinel")
JOB_NAME = os.environ.get("JOB_NAME", "job-noaa-flood-v1")
REGION = os.environ.get("REGION", "us-east1")

app = Flask(__name__)

@app.route("/", methods=["GET", "POST"])
@app.route("/run", methods=["GET", "POST"])
def run():
    now = datetime.now(timezone.utc).isoformat()
    try:
        creds, project = google.auth.default()
        auth_req = google.auth.transport.requests.Request()
        creds.refresh(auth_req)
        token = creds.token

        url = f"https://run.googleapis.com/v2/projects/{PROJECT}/locations/{REGION}/jobs/{JOB_NAME}:run"
        resp = http_requests.post(
            url,
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"},
            json={},
            timeout=30
        )

        if resp.status_code in (200, 202):
            return json.dumps({
                "ok": True,
                "status": "job_launched",
                "job": JOB_NAME,
                "launched_at": now
            }), 200, {"Content-Type": "application/json"}
        else:
            return json.dumps({
                "ok": False,
                "error": resp.text
            }), 200, {"Content-Type": "application/json"}

    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}), 200, \
               {"Content-Type": "application/json"}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
