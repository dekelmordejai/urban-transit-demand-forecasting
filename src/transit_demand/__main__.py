"""Command-line entry point for data contracts, delivery controls and synthetic demo."""

import argparse
import json

from transit_demand.data.contracts import validate_csv


def main() -> None:
    parser = argparse.ArgumentParser(description="Transit demand data controls and synthetic demo")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="Validate aggregate CSV structure")
    validate.add_argument("path")
    quality = commands.add_parser(
        "quality", help="Validate a delivery against its manifest and catalog"
    )
    quality.add_argument("path")
    quality.add_argument("--manifest", required=True)
    quality.add_argument("--catalog", required=True)
    demo = commands.add_parser(
        "demo", help="Run offline synthetic quality and baseline demonstration"
    )
    demo.add_argument("--output", required=True, help="New or empty output directory")
    args = parser.parse_args()
    try:
        if args.command == "validate":
            records = validate_csv(args.path)
            print(
                f"Validated {len(records)} records; observed entries={sum(r['y_observed'] for r in records)}"
            )
        elif args.command == "quality":
            from pathlib import Path

            from transit_demand.data.quality import validate_delivery

            manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
            catalog = json.loads(Path(args.catalog).read_text(encoding="utf-8"))
            result = validate_delivery(args.path, manifest, catalog)
            result.pop("grid")
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            from transit_demand.demo import run_demo

            result = run_demo(args.output)
            print(f"SYNTHETIC ONLY: {len(result['scores'])} score groups; report in {args.output}")
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f"Validation failed: {error}\n")


if __name__ == "__main__":
    main()
