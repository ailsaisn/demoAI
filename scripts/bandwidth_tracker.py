#!/usr/bin/env python3
"""
Bandwidth Tracker and Comparative Analyzer
Measures network throughput (Download, Upload, Latency) via speedtest-cli
and generates comparative summaries between internal and client environments.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import sys
import time
from typing import Any, Dict, List, Optional


DEFAULT_OUTPUT_FILE = "bandwidth_log.csv"
CSV_COLUMNS = [
    "timestamp",
    "environment",
    "label",
    "download_mbps",
    "upload_mbps",
    "ping_ms",
    "server_name",
    "server_country",
    "server_sponsor",
    "client_ip",
    "client_isp",
]


def run_speedtest(environment: str, label: str = "") -> Dict[str, Any]:
    """Runs a single speedtest benchmark and returns formatted metrics."""
    try:
        # pyrefly: ignore [missing-import]
        import speedtest
    except ImportError:
        print(
            "Error: 'speedtest-cli' package is not installed.\n"
            "Install it via: pip install speedtest-cli",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Finding optimal speedtest server...")
    st = speedtest.Speedtest(secure=True)
    st.get_best_server()

    print("Testing download speed...")
    st.download(threads=None)

    print("Testing upload speed...")
    st.upload(threads=None)

    res = st.results.dict()
    download_mbps = round(res.get("download", 0) / 1_000_000, 2)
    upload_mbps = round(res.get("upload", 0) / 1_000_000, 2)
    ping_ms = round(res.get("ping", 0), 2)
    server = res.get("server", {})
    client = res.get("client", {})

    record: Dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "environment": environment,
        "label": label or environment,
        "download_mbps": download_mbps,
        "upload_mbps": upload_mbps,
        "ping_ms": ping_ms,
        "server_name": server.get("name", "N/A"),
        "server_country": server.get("country", "N/A"),
        "server_sponsor": server.get("sponsor", "N/A"),
        "client_ip": client.get("ip", "N/A"),
        "client_isp": client.get("isp", "N/A"),
    }
    return record


def append_csv(file_path: Path, record: Dict[str, Any]) -> None:
    """Appends a single speedtest record to CSV."""
    file_exists = file_path.exists() and file_path.stat().st_size > 0
    with file_path.open(mode="a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(record)


def load_records(file_path: Path) -> List[Dict[str, Any]]:
    """Loads all records from a CSV log file."""
    if not file_path.exists():
        return []
    records: List[Dict[str, Any]] = []
    with file_path.open(mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            records.append({
                "timestamp": row.get("timestamp", ""),
                "environment": row.get("environment", "default"),
                "label": row.get("label", ""),
                "download_mbps": float(row.get("download_mbps", 0.0)),
                "upload_mbps": float(row.get("upload_mbps", 0.0)),
                "ping_ms": float(row.get("ping_ms", 0.0)),
                "server_name": row.get("server_name", ""),
                "server_country": row.get("server_country", ""),
                "server_sponsor": row.get("server_sponsor", ""),
                "client_ip": row.get("client_ip", ""),
                "client_isp": row.get("client_isp", ""),
            })
    return records


def calculate_stats(values: List[float]) -> Dict[str, float]:
    """Calculates min, max, avg, and median for a metric."""
    if not values:
        return {"min": 0.0, "max": 0.0, "avg": 0.0, "median": 0.0}
    return {
        "min": round(min(values), 2),
        "max": round(max(values), 2),
        "avg": round(statistics.mean(values), 2),
        "median": round(statistics.median(values), 2),
    }


def display_comparison(records: List[Dict[str, Any]]) -> None:
    """Renders a comparative analysis table across environments."""
    if not records:
        print("No bandwidth records found.")
        return

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for r in records:
        env = r.get("environment", "Unknown")
        grouped.setdefault(env, []).append(r)

    print("\n" + "=" * 80)
    print(" BANDWIDTH TRACKER: COMPARATIVE BENCHMARK SUMMARY")
    print("=" * 80)

    header = f"{'Environment':<18} | {'Samples':<7} | {'Download (Mbps)':<22} | {'Upload (Mbps)':<22} | {'Ping (ms)':<15}"
    sub_header = f"{'':<18} | {'':<7} | {'Avg (Min/Max)':<22} | {'Avg (Min/Max)':<22} | {'Avg (Min/Max)':<15}"
    print(header)
    print(sub_header)
    print("-" * 80)

    for env, rows in grouped.items():
        downloads = [r["download_mbps"] for r in rows]
        uploads = [r["upload_mbps"] for r in rows]
        pings = [r["ping_ms"] for r in rows]

        d_stat = calculate_stats(downloads)
        u_stat = calculate_stats(uploads)
        p_stat = calculate_stats(pings)

        d_str = f"{d_stat['avg']} ({d_stat['min']}/{d_stat['max']})"
        u_str = f"{u_stat['avg']} ({u_stat['min']}/{u_stat['max']})"
        p_str = f"{p_stat['avg']} ({p_stat['min']}/{p_stat['max']})"

        print(f"{env:<18} | {len(rows):<7} | {d_str:<22} | {u_str:<22} | {p_str:<15}")

    print("=" * 80 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Speedtest Bandwidth Tracker and Multi-Environment Comparison CLI"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Test / Track Command
    track_parser = subparsers.add_parser("track", help="Run a speedtest and record metrics")
    track_parser.add_argument(
        "--env",
        "-e",
        required=True,
        help="Environment name (e.g. 'internal', 'client', 'our-server')",
    )
    track_parser.add_argument(
        "--label",
        "-l",
        default="",
        help="Optional custom label or host identifier",
    )
    track_parser.add_argument(
        "--out",
        "-o",
        default=DEFAULT_OUTPUT_FILE,
        help=f"Target CSV file path (default: {DEFAULT_OUTPUT_FILE})",
    )
    track_parser.add_argument(
        "--api-url",
        default="",
        help="Optional FastAPI backend base URL to push records to (e.g. 'http://localhost:8000')",
    )
    track_parser.add_argument(
        "--interval",
        "-i",
        type=int,
        default=0,
        help="Run continuously every N seconds (0 for single run)",
    )
    track_parser.add_argument(
        "--count",
        "-c",
        type=int,
        default=1,
        help="Number of iterations to run (default: 1, set 0 for infinite)",
    )

    # Compare Command
    compare_parser = subparsers.add_parser("compare", help="Compare recorded speedtest metrics")
    compare_parser.add_argument(
        "--files",
        "-f",
        nargs="+",
        default=[DEFAULT_OUTPUT_FILE],
        help=f"CSV file(s) to analyze (default: {DEFAULT_OUTPUT_FILE})",
    )

    args = parser.parse_args()

    if args.command == "track":
        out_path = Path(args.out)
        iterations = 0
        while True:
            iterations += 1
            print(f"\n--- Running Speedtest [{args.env}] (Run #{iterations}) ---")
            record = run_speedtest(environment=args.env, label=args.label)
            append_csv(out_path, record)

            dl = record['download_mbps']
            ul = record['upload_mbps']
            ping = record['ping_ms']
            dl_mbs = round(dl / 8.0, 2)
            ul_mbs = round(ul / 8.0, 2)

            print(
                f"\nSpeedtest Result:\n"
                f"  - Download : {dl} Mbps (~{dl_mbs} MB/s)\n"
                f"  - Upload   : {ul} Mbps (~{ul_mbs} MB/s)\n"
                f"  - Latency  : {ping} ms\n"
                f"  - Provider : {record['client_isp']} (IP: {record['client_ip']})\n"
                f"  - Server   : {record['server_name']}, {record['server_country']} ({record['server_sponsor']})\n"
            )
            print(f"Appended to {out_path.resolve()}")

            if args.api_url:
                try:
                    import urllib.request
                    endpoint = args.api_url.rstrip("/") + "/api/bandwidth/records"
                    data = json.dumps(record).encode("utf-8")
                    req = urllib.request.Request(
                        endpoint,
                        data=data,
                        headers={"Content-Type": "application/json", "User-Agent": "BandwidthTracker/1.0"},
                    )
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        if resp.status in (200, 201):
                            print(f"Successfully synced to backend: {endpoint}")
                except Exception as sync_err:
                    print(f"Warning: Failed to sync to API ({args.api_url}): {sync_err}", file=sys.stderr)

            if args.count > 0 and iterations >= args.count:
                break
            if args.interval <= 0:
                break

            print(f"Waiting {args.interval}s until next test...")
            time.sleep(args.interval)

    elif args.command == "compare":
        all_records: List[Dict[str, Any]] = []
        for f in args.files:
            p = Path(f)
            if p.exists():
                all_records.extend(load_records(p))
            else:
                print(f"Warning: File not found: {f}", file=sys.stderr)
        display_comparison(all_records)


if __name__ == "__main__":
    main()
