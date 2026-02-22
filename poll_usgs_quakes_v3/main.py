import json
from datetime import datetime, timedelta, timezone

def handler_v2(request):
    """
    Cloud Functions Gen2 entrypoint.
    Invoked at path '/' only.
    """

    if request.method not in ("GET", "POST"):
        return ("Method Not Allowed", 405)

    args = request.args or {}
    minutes = int(args.get("minutes", "60"))

    now = datetime.now(timezone.utc)
    since = now - timedelta(minutes=minutes)

    # TODO: replace with real USGS poll logic
    resp = {
        "ok": True,
        "service": "poll_usgs_quakes_v3",
        "since_utc": since.isoformat(),
        "now_utc": now.isoformat(),
        "minutes": minutes,
        "count": 0,
    }

    return (json.dumps(resp), 200, {"Content-Type": "application/json"})
