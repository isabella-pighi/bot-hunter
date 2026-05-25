from __future__ import annotations

import argparse
import json
from pathlib import Path

from .pipeline import run_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(prog="bot-hunter")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run classifiers and write artifacts")
    run_parser.add_argument("--input", required=True, help="Path to raw click TSV")
    run_parser.add_argument("--output-dir", default=".", help="Directory for artifacts and submission.tsv")
    run_parser.add_argument(
        "--ml-backend",
        choices=["kmeans", "sklearn", "auto"],
        default="kmeans",
        help="Anomaly backend to use; default keeps the dependency-light k-means implementation",
    )

    args = parser.parse_args()
    if args.command == "run":
        summary = run_pipeline(Path(args.input), Path(args.output_dir), ml_backend=args.ml_backend)
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
