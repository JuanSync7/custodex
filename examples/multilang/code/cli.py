"""Command-line front end for the greeter (the subject: argparse options)."""

from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    """Build the ``greet`` argument parser."""
    parser = argparse.ArgumentParser(prog="greet")
    parser.add_argument("--name", default="world", help="who to greet")
    parser.add_argument("--shout", action="store_true", help="upper-case the greeting")
    parser.add_argument("--repeat", default=1, help="how many times to greet")
    return parser
