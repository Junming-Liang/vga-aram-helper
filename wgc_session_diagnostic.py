"""Test-only explicit launcher. Never starts the application or accepts a HWND."""
from __future__ import annotations
import argparse
from pathlib import Path


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--report',type=Path)
    group.add_argument('--job-owner-report',type=Path,help=argparse.SUPPRESS)
    args=parser.parse_args(argv)
    from wgc_session_smoke import run,job_owner
    return job_owner(args.job_owner_report) if args.job_owner_report else run(args.report)


if __name__=='__main__':
    raise SystemExit(main())
