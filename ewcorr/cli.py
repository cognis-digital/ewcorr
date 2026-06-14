"""Command-line interface for EWCORR.

Subcommands:
    correlate FILE   Cluster an EW/ELINT observation log into emitters.

Global:
    --version        Print tool name and version.
    --format {table,json}

Exit codes:
    0  success
    1  no emitters could be formed (empty/degenerate result)
    2  bad input / usage error
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from . import TOOL_NAME, TOOL_VERSION
from .core import (
    CorrelationConfig,
    EWCorrError,
    correlate,
    parse_observations,
    summarize,
)


def _read_input(path: str) -> str:
    if path == "-":
        try:
            return sys.stdin.read()
        except UnicodeDecodeError as exc:
            raise OSError(f"stdin contains non-UTF-8 data: {exc}") from exc
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _render_table(report: dict) -> str:
    lines: list[str] = []
    lines.append(
        f"EWCORR: {report['emitters']} emitter(s) from "
        f"{report['observations']} observation(s) "
        f"({report['multi_obs_emitters']} multi-hit, {report['singletons']} singleton)"
    )
    lines.append("")
    hdr = (
        f"{'EMITTER':<8} {'HITS':>4} {'FREQ_MHz':>10} {'BRG':>6} "
        f"{'SPREAD':>6} {'CONF':>5}  {'FIRST_SEEN':<22} SENSORS"
    )
    lines.append(hdr)
    lines.append("-" * len(hdr))
    for c in report["clusters"]:
        lines.append(
            f"{c['emitter_id']:<8} {c['count']:>4} {c['freq_center_mhz']:>10.4f} "
            f"{c['bearing_mean_deg']:>6.1f} {c['bearing_spread_deg']:>6.1f} "
            f"{c['confidence']:>5.2f}  {c['first_seen']:<22} "
            f"{','.join(c['sensors']) or '-'}"
        )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=TOOL_NAME,
        description=(
            "Correlate passive EW/ELINT event logs into candidate emitter clusters "
            "(defensive analysis / monitoring only)."
        ),
    )
    p.add_argument("--version", action="version", version=f"{TOOL_NAME} {TOOL_VERSION}")
    p.add_argument(
        "--format",
        choices=("table", "json"),
        default="table",
        help="output format (default: table)",
    )
    sub = p.add_subparsers(dest="command", required=True)

    c = sub.add_parser("correlate", help="cluster an observation log into emitters")
    c.add_argument("file", help="CSV log path, or '-' for stdin")
    c.add_argument("--time-window", type=float, default=30.0,
                   help="max seconds between linked detections (default: 30)")
    c.add_argument("--freq-tol", type=float, default=0.5,
                   help="frequency tolerance in MHz (default: 0.5)")
    c.add_argument("--bearing-tol", type=float, default=5.0,
                   help="bearing tolerance in degrees (default: 5)")
    c.add_argument(
        "--min-hits", type=int, default=1, metavar="N",
        help="drop emitters with fewer than N observations (default: 1; min: 1)",
    )
    return p


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "correlate":
        if args.min_hits < 1:
            print("error: --min-hits must be at least 1", file=sys.stderr)
            return 2
        try:
            text = _read_input(args.file)
            observations = parse_observations(text)
            cfg = CorrelationConfig(
                time_window_s=args.time_window,
                freq_tol_mhz=args.freq_tol,
                bearing_tol_deg=args.bearing_tol,
            )
            clusters = correlate(observations, cfg)
            if args.min_hits > 1:
                clusters = [c for c in clusters if c.count >= args.min_hits]
            report = summarize(clusters)
        except FileNotFoundError:
            print(f"error: file not found: {args.file}", file=sys.stderr)
            return 2
        except IsADirectoryError:
            print(
                f"error: path is a directory, not a file: {args.file}",
                file=sys.stderr,
            )
            return 2
        except PermissionError:
            print(f"error: permission denied: {args.file}", file=sys.stderr)
            return 2
        except UnicodeDecodeError as exc:
            print(
                f"error: file is not valid UTF-8: {args.file}: {exc}",
                file=sys.stderr,
            )
            return 2
        except OSError as exc:
            print(f"error: cannot read input: {exc}", file=sys.stderr)
            return 2
        except EWCorrError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

        if args.format == "json":
            print(json.dumps(report, indent=2))
        else:
            print(_render_table(report))

        # The tool's notion of failure: no emitters survived correlation.
        return 0 if report["emitters"] > 0 else 1

    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
