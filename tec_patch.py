import re

with open('backfill_tec.py', 'r') as f:
    content = f.read()

old = '''    session = make_session()
    client  = None if args.dry_run else bigquery.Client(project=PROJECT)

    if not args.dry_run:
        ensure_columns(client)

    # Phase 1: download and parse all days
    daily_tec = {}   # date -> float | None
    total_days = (end_date - start_date).days + 1
    success = 0
    fail    = 0

    with tempfile.TemporaryDirectory() as tmpdir:
        d = start_date
        while d <= end_date:
            filepath = download_ionex(session, d, tmpdir)
            if filepath:
                tec = parse_ionex_global_mean(filepath)
                daily_tec[d] = tec
                if tec is not None:
                    success += 1
                    log.info(f"{d} tec_mean={tec:.2f} TECu")
                else:
                    log.warning(f"{d} parse failed")
                    fail += 1
                # Clean up to save disk space
                for f in os.listdir(tmpdir):
                    os.remove(os.path.join(tmpdir, f))
            else:
                daily_tec[d] = None
                fail += 1
                if d.month == 1 and d.day == 1:
                    log.warning(f"{d} download failed (year boundary)")

            d += timedelta(days=1)'''

new = '''    session = make_session()
    client  = None if args.dry_run else bigquery.Client(project=PROJECT)

    if not args.dry_run:
        ensure_columns(client)

    # CSV cache - survives VM restarts
    import csv
    CACHE_FILE = os.path.expanduser("~/project-sentinel/tec_cache.csv")

    # Load any previously parsed results
    daily_tec = {}
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, 'r') as f:
            for row in csv.DictReader(f):
                d = date.fromisoformat(row['day'])
                v = row['tec_global_mean']
                daily_tec[d] = float(v) if v else None
        log.info(f"Loaded {len(daily_tec)} cached days from {CACHE_FILE}")

    # Phase 1: download and parse all days
    total_days = (end_date - start_date).days + 1
    success = sum(1 for v in daily_tec.values() if v is not None)
    fail    = 0

    cache_fh = open(CACHE_FILE, 'a', newline='')
    cache_writer = csv.writer(cache_fh)
    if os.path.getsize(CACHE_FILE) == 0:
        cache_writer.writerow(['day', 'tec_global_mean'])

    with tempfile.TemporaryDirectory() as tmpdir:
        d = start_date
        while d <= end_date:
            if d in daily_tec:
                d += timedelta(days=1)
                continue
            filepath = download_ionex(session, d, tmpdir)
            if filepath:
                tec = parse_ionex_global_mean(filepath)
                daily_tec[d] = tec
                if tec is not None:
                    success += 1
                    log.info(f"{d} tec_mean={tec:.2f} TECu")
                    cache_writer.writerow([d.isoformat(), tec])
                    cache_fh.flush()
                else:
                    log.warning(f"{d} parse failed")
                    fail += 1
                    cache_writer.writerow([d.isoformat(), ''])
                    cache_fh.flush()
                for f in os.listdir(tmpdir):
                    os.remove(os.path.join(tmpdir, f))
            else:
                daily_tec[d] = None
                fail += 1
                if d.month == 1 and d.day == 1:
                    log.warning(f"{d} download failed (year boundary)")

            d += timedelta(days=1)

    cache_fh.close()'''

if old in content:
    content = content.replace(old, new)
    with open('backfill_tec.py', 'w') as f:
        f.write(content)
    print("SUCCESS - patch applied")
else:
    print("FAILED - old text not found")
