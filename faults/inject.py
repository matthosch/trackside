"""Inject faults into the local stack to exercise alerting and the triage agent.

    python faults/inject.py list
    python faults/inject.py api-latency --minutes 15
    python faults/inject.py implausible-laps
    python faults/inject.py clear

Run from the repository root with the Compose stack up. Only the standard library
is used. Every fault is undone by `clear`.
"""

import argparse
import json
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

TOXIPROXY = "http://127.0.0.1:8474"
API = "http://127.0.0.1:8000"
PROXY = "api-db"

SCENARIOS = {
    "api-latency": ("Adds latency between the API and Postgres and sends steady traffic",
                    "ApiSlowRequests (after ~10 min)"),
    "api-errors": ("Cuts the API's link to Postgres and sends steady traffic",
                   "ApiHighErrorRatio (after ~5 min)"),
    "api-down": ("Stops the API container", "ApiDown (after ~2 min)"),
    "implausible-laps": ("Writes impossible lap times into the largest race file and reloads it",
                         "DataQualityCheckFailing: implausible_lap_pct"),
    "missing-laps": ("Empties one race's lap file and reloads it", "DataQualityCheckFailing: races_without_laps"),
    "changed-layout": ("Renames a column in one lap file, as if the timing provider changed format",
                       "DataQualityCheckFailing: files_failed_to_load"),
}
PIPELINE_FAULTS = {"implausible-laps", "missing-laps", "changed-layout"}


def compose(*args: str, check: bool = True) -> str:
    result = subprocess.run(["docker", "compose", *args], capture_output=True, text=True)
    if check and result.returncode != 0:
        sys.exit(f"docker compose {' '.join(args)} failed:\n{result.stderr.strip()}")
    return result.stdout.strip()


def toxiproxy(method: str, path: str, body: dict | None = None) -> dict | list:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(f"{TOXIPROXY}{path}", data=data, method=method,
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read()
    except urllib.error.URLError as error:
        sys.exit(f"Toxiproxy is not reachable at {TOXIPROXY} ({error}); is the stack up?")
    return json.loads(raw) if raw else {}


def traffic(minutes: float) -> None:
    """Steady requests across the API's routes, so latency and error rates have samples."""
    events = json.loads(urllib.request.urlopen(f"{API}/api/events", timeout=30).read())
    paths = ["/api/events"] + [f"/api/events/{e['id']}/{p}" for e in events for p in ("stays", "pace", "drivers")]
    deadline = time.monotonic() + minutes * 60
    sent = failed = 0

    def worker():
        nonlocal sent, failed
        i = 0
        while time.monotonic() < deadline:
            try:
                urllib.request.urlopen(f"{API}{paths[i % len(paths)]}", timeout=30).read()
            except (urllib.error.URLError, TimeoutError):
                failed += 1
            sent += 1
            i += 1
            time.sleep(0.5)

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(4)]
    for t in threads:
        t.start()
    while any(t.is_alive() for t in threads):
        time.sleep(30)
        left = max(0, deadline - time.monotonic()) / 60
        print(f"  {sent} requests sent, {failed} failed; {left:.0f} min left", flush=True)


def clear_network() -> None:
    for toxic in toxiproxy("GET", f"/proxies/{PROXY}/toxics"):
        toxiproxy("DELETE", f"/proxies/{PROXY}/toxics/{toxic['name']}")
    toxiproxy("POST", f"/proxies/{PROXY}", {"enabled": True})


def run(scenario: str, minutes: float, latency_ms: int) -> None:
    what, alert = SCENARIOS[scenario]
    print(f"{scenario}: {what}.\nExpect: {alert}.")
    if scenario == "api-latency":
        toxiproxy("POST", f"/proxies/{PROXY}/toxics",
                  {"name": "latency", "type": "latency", "stream": "downstream", "attributes": {"latency": latency_ms}})
        print(f"Added {latency_ms} ms per database response. Sending traffic for {minutes:g} min...")
        try:
            traffic(minutes)
        finally:
            clear_network()
            print("Latency removed; the alert resolves once the 5-minute rate window rolls over.")
    elif scenario == "api-errors":
        toxiproxy("POST", f"/proxies/{PROXY}", {"enabled": False})
        print(f"Postgres link cut. Sending traffic for {minutes:g} min...")
        try:
            traffic(minutes)
        finally:
            clear_network()
            print("Link restored.")
    elif scenario == "api-down":
        compose("stop", "api")
        print("API stopped. Undo with: python faults/inject.py clear")
    else:
        print(compose("exec", "-T", "airflow-scheduler", "python", "-m", "trackside_pipelines.faults", scenario))
        compose("exec", "-T", "airflow-scheduler", "airflow", "dags", "trigger", "timing_archive")
        print("Triggered timing_archive; the check fails when its quality_checks task runs (a few minutes).\n"
              "Undo with: python faults/inject.py clear")


def clear() -> None:
    clear_network()
    compose("start", "api")
    restored = compose("exec", "-T", "airflow-scheduler", "python", "-m", "trackside_pipelines.faults", "restore")
    print(f"Network faults removed, API started, {restored}.")
    if not restored.startswith("restored 0"):
        compose("exec", "-T", "airflow-scheduler", "airflow", "dags", "trigger", "timing_archive")
        print("Triggered timing_archive to reload the restored files.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("scenario", choices=["list", "clear", *SCENARIOS])
    parser.add_argument("--minutes", type=float, default=15, help="traffic duration for api-latency and api-errors")
    parser.add_argument("--latency-ms", type=int, default=400, help="added per database response")
    args = parser.parse_args()
    if args.scenario == "list":
        for name, (what, alert) in SCENARIOS.items():
            print(f"{name:18} {what}.\n{'':18} Expect: {alert}.")
    elif args.scenario == "clear":
        clear()
    else:
        run(args.scenario, args.minutes, args.latency_ms)


if __name__ == "__main__":
    main()
