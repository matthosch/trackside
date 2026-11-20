# Runbook: a data-quality check is failing

Covers `DataQualityCheckFailing`.

## What it means

After every `timing_archive` run, the `quality_checks` task runs the checks in
`pipelines/trackside_pipelines/quality.py`, stores each result in
`ops.dq_results`, and pushes `trackside_dq_check_status` (0 pass, 1 warn,
2 fail). A failing check does not fail the pipeline run: the run succeeds and
this alert fires instead, so data problems and pipeline outages are told apart.

Checks look at all loaded data, so the alert keeps firing until the cause is fixed.

## Find the failing check

```sql
SELECT DISTINCT ON (check_name) check_name, status, value, warn_above, fail_above, detail, checked_at
FROM ops.dq_results
WHERE pipeline = 'timing_archive'
ORDER BY check_name, checked_at DESC;
```

## By check

**files_not_fetched.** Files listed on the archive that could not be downloaded.
```sql
SELECT url, discovered_at FROM raw.timing_files WHERE fetched_at IS NULL;
```
A 404 usually means the archive replaced a provisional file with a final one;
the next `discover` picks up the new file. Persistent 403s mean we are being refused.

**files_failed_to_load.** A file downloaded but would not parse, almost always
because its columns changed.
```sql
SELECT url, load_error FROM raw.timing_files WHERE load_error IS NOT NULL;
```
Compare the file's header with `LAP_COLUMNS` / `RESULTS_COLUMNS` in `timing.py`.
Fix the parser, add a test with the new layout, and bump `PARSER_VERSION` in
`timing.py`. The next run retries the failed files and reprocesses everything
loaded by the older version; no SQL by hand.

The same applies to any parser fix that changes what lands in staging, even when
nothing failed: bumping the version is what backfills the corrected data.

**races_without_laps.** A race session exists but has no lap data. Either the
archive has not published the lap file yet (wait a day), or the lap file's name
no longer matches the patterns in `alkamel.py`.

**implausible_lap_pct.** Too many laps are faster than 85% of their session's
median, which means bad timing data or a parsing error (for example, a lap time
read from the wrong column). Implausible laps are already excluded from pace.

**laps_without_entry_pct.** Laps whose car number has no row in the results
file, so the car model is unknown. Usually a car-number format change (the
loader strips leading zeros); check `car_number()` in `timing.py`.

**unmapped_vehicles** (warn only). A new vehicle name needs a pattern in
`staging.car_model_patterns`; until then it shows under its raw name.

**upcoming_circuits_without_pace** (warn only). An upcoming race is at a
circuit with no archive data in the loaded seasons.
