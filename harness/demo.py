#!/usr/bin/env python3
"""SNIFF live-demo entry point for the trick-test harness.

Runs system/run as a black box against mutated copies of the official data.
Writes JSON + HTML reports with metrics computed from the run (never hardcoded).

Examples:
  # Fast showcase (3 hits × all mutations) — good for live demo
  python3 harness/demo.py --data /path/to/screening/dev --quick

  # Full practice SAME_ENTITY matrix
  python3 harness/demo.py --data /path/to/screening/dev
"""
from __future__ import annotations

import argparse
import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
import mutate as harness  # noqa: E402

# Showcase seeds: individual DOB path, ambiguity-prone, company NAME_LOCATION
SHOWCASE_HITS = ("H-582410", "H-4D76E3", "H-02115F")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="SNIFF trick-test demo runner")
    p.add_argument("--data", required=True, help="Official screening/dev folder (outside the repo)")
    p.add_argument(
        "--out-dir",
        default="/tmp/sniff-harness/demo",
        help="Directory for JSON + HTML reports",
    )
    p.add_argument(
        "--quick",
        action="store_true",
        help=f"Demo subset only: {', '.join(SHOWCASE_HITS)}",
    )
    p.add_argument(
        "--mutations",
        default="all",
        help="Comma-separated mutations or 'all' (default all)",
    )
    args = p.parse_args(argv)

    os.makedirs(args.out_dir, exist_ok=True)
    json_path = os.path.join(args.out_dir, "demo_report.json")
    html_path = os.path.join(args.out_dir, "demo_report.html")

    cmd = [
        "--data", args.data,
        "--out", json_path,
        "--html", html_path,
        "--seeds", "practice",
        "--mutations", args.mutations,
    ]
    if args.quick:
        cmd.extend(["--hit-ids", ",".join(SHOWCASE_HITS)])

    print("SNIFF trick-test demo")
    print(f"  data:  {args.data}")
    print(f"  json:  {json_path}")
    print(f"  html:  {html_path}")
    print(f"  mode:  {'quick showcase' if args.quick else 'full practice SAME seeds'}")
    print()
    return harness.main(cmd)


if __name__ == "__main__":
    sys.exit(main())
