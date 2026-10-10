"""Argument parsing for the fixture tool."""

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser."""
    parser = argparse.ArgumentParser(prog="fixture")
    parser.add_argument("-v", "--verbose", action="store_true", help="Talk more.")
    parser.add_argument(
        "--output",
        default=(
            "reports/a-deliberately-long-default-output-path/"
            "that-runs-well-past-the-eighty-character-cell-limit.txt"
        ),
        help="Where to write the report.",
    )
    return parser


def legacy_quiet() -> bool:
    """Accept the old ``-q`` switch."""
    return "-q" in sys.argv
