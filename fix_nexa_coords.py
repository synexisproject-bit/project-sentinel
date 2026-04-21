#!/usr/bin/env python3
"""Fix incorrect geocoding in NEXA corpus hac_normalized coordinates."""

from google.cloud import bigquery

PROJECT = "synexis-project-sentinel"
TABLE   = f"{PROJECT}.hac_intake.hac_normalized"
bq      = bigquery.Client(project=PROJECT)

# (ref_lat, ref_lon, exp_lat, exp_lon, note)
corrections = {
    'cbf61709-1c7f-4fa2-bdc6-b44bd3183269': (35.689,  139.692, 35.689,  139.692, 'Tokyo'),
    '9489bf30-e1e9-479f-b24e-5e71a9d7754c': (33.749,  -84.388, 38.0,    -97.0,   'Atlanta'),
    '3edf21a3-2ffe-4334-83ce-4b8c684e8cd1': (39.916,  116.383, 38.0,    -97.0,   'Beijing'),
    '823dcd42-5f59-4aa4-bc08-f94a80456d59': (42.360,  -71.059, 38.0,    -97.0,   'Boston'),
    '39dbd0e9-5f19-4f12-a816-09967dd56db4': (34.052, -118.244, 38.0,    -97.0,   'Los Angeles'),
    'c0701d5a-1f53-4fdd-9a38-213fdba6c396': (48.857,    2.352, 38.0,    -97.0,   'Paris'),
    '57870f4f-673d-4529-b39a-3ba4a5786e42': (37.775, -122.418, 37.775, -122.418, 'San Francisco'),
    'eaedbe81-e26e-49e9-a4e7-06ff08534948': (37.775, -122.418, 38.0,    -97.0,   'San Francisco'),
    'cf0b2a97-a97f-4e9c-b117-8992063cdb16': (37.775, -122.418, 38.0,    -97.0,   'San Francisco'),
    '01d5f493-ed72-4dff-b21d-3d06a9454d6c': (37.775, -122.418, 38.0,    -97.0,   'San Francisco'),
    '1ac17eff-fe8b-4e80-bd26-37278fd797ee': (37.775, -122.418, 38.0,    -97.0,   'San Francisco'),
    '68be034e-65da-4f6c-b089-27af8bb86605': (-33.868, 151.209, -41.0,   174.0,   'Sydney'),
    '8ac00a75-a8e9-43fd-aa45-832c2d75d0a9': (26.820,   30.802, 38.0,    -97.0,   'Egypt centroid'),
    '851369a5-7e89-4bd6-bf3b-9a5475d06450': (40.713,  -74.006, 42.0,     12.0,   'New York'),
    '0d1033b0-9c1f-4327-a9a9-5f8c7cccab7a': (40.713,  -74.006, 42.0,     12.0,   'New York'),
    'd8da7804-a6fb-4260-8740-5f3c3ff11664': (38.0,    -97.0,   38.0,    -97.0,   'US re-centroid'),
    '4e99b1f3-045f-4b48-88ce-fb605a952557': (38.0,    -97.0,   38.0,    -97.0,   'US re-centroid'),
    '93d96db9-2fc0-44b3-8dbb-e563201d65bf': (38.0,    -97.0,   38.0,    -97.0,   'US re-centroid'),
    '763d2d94-e481-490b-83b9-78fdf0e90462': (38.0,    -97.0,   38.0,    -97.0,   'US re-centroid'),
}

print(f"Applying {len(corrections)} coordinate corrections...")
updated = 0
errors  = 0

for sid, (ref_lat, ref_lon, exp_lat, exp_lon, note) in corrections.items():
    query = """
        UPDATE `synexis-project-sentinel.hac_intake.hac_normalized`
        SET referred_lat_approx    = @ref_lat,
            referred_lon_approx    = @ref_lon,
            experiencer_lat_approx = @exp_lat,
            experiencer_lon_approx = @exp_lon
        WHERE submission_id = @sid
    """
    cfg = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("ref_lat", "FLOAT64", ref_lat),
        bigquery.ScalarQueryParameter("ref_lon", "FLOAT64", ref_lon),
        bigquery.ScalarQueryParameter("exp_lat", "FLOAT64", exp_lat),
        bigquery.ScalarQueryParameter("exp_lon", "FLOAT64", exp_lon),
        bigquery.ScalarQueryParameter("sid",     "STRING",  sid),
    ])
    try:
        bq.query(query, job_config=cfg).result()
        print(f"  Fixed {sid[:8]}: {note} -> ({ref_lat}, {ref_lon})")
        updated += 1
    except Exception as e:
        print(f"  ERROR {sid[:8]}: {e}")
        errors += 1

print(f"\nDone — updated {updated}, errors {errors}")

# Verify results
print("\nPost-fix coordinate distribution:")
for row in bq.query("""
    SELECT referred_location_text,
           ROUND(referred_lat_approx,1) AS lat,
           ROUND(referred_lon_approx,1) AS lon,
           COUNT(*) AS cnt
    FROM `synexis-project-sentinel.hac_intake.hac_normalized`
    WHERE source_type = 'archive_nexa'
      AND referred_lat_approx IS NOT NULL
    GROUP BY 1,2,3
    ORDER BY referred_location_text
""").result():
    print(f"  {row.referred_location_text:<20} ({row.lat:7.1f}, {row.lon:8.1f})  n={row.cnt}")
