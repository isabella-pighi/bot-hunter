from __future__ import annotations

import argparse
import json
from pathlib import Path

from .pipeline import run_pipeline
from .supervised import run_supervised_pilot


def main() -> None:
    parser = argparse.ArgumentParser(prog="bot-hunter")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run classifiers and write artifacts")
    run_parser.add_argument("--input", required=True, help="Path to raw click TSV")
    run_parser.add_argument("--output-dir", default=".", help="Directory for artifacts and submission.tsv")
    run_parser.add_argument(
        "--ml-backend",
        choices=["kmeans", "sklearn", "auto"],
        default="auto",
        help="Anomaly backend to use; default prefers sklearn when available and falls back to k-means",
    )
    pilot_parser = subparsers.add_parser(
        "supervised-pilot",
        help="Run an additive strict-rule-seeded supervised scoring pilot",
    )
    pilot_parser.add_argument("--input", required=True, help="Path to raw click TSV")
    pilot_parser.add_argument("--output-dir", default=".", help="Directory for pilot artifacts")
    pilot_parser.add_argument(
        "--ml-backend",
        choices=["kmeans", "sklearn", "auto"],
        default="auto",
        help="Baseline anomaly backend to compare against; default prefers sklearn when available",
    )

    args = parser.parse_args()
    if args.command == "run":
        summary = run_pipeline(Path(args.input), Path(args.output_dir), ml_backend=args.ml_backend)
        print(json.dumps(summary, indent=2))
    elif args.command == "supervised-pilot":
        summary = run_supervised_pilot(Path(args.input), Path(args.output_dir), ml_backend=args.ml_backend)
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
