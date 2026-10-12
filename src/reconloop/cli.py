"""Command line:  reconloop run CONFIG [--out DIR]   |   reconloop score OUT_DIR ANSWERS.json"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main(argv=None):
    ap = argparse.ArgumentParser(prog="reconloop")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="reconcile every report x metric automatically")
    r.add_argument("config"); r.add_argument("--out", default="reconloop_out")
    r.add_argument("--judge", choices=["search", "stated_rule"], default="stated_rule")
    s = sub.add_parser("score", help="compare final definitions with known answers (demo / eval sets)")
    s.add_argument("out_dir"); s.add_argument("answers")
    a = ap.parse_args(argv)

    if a.cmd == "run":
        from .config import run_config
        from .judge import SearchJudge, StatedRuleJudge
        judge = SearchJudge() if a.judge == "search" else StatedRuleJudge()
        recs = run_config(a.config, judge=judge, out_dir=a.out)
        print(f"\nwrote {Path(a.out) / 'report.md'}  ({len(recs)} records)")
    elif a.cmd == "score":
        from .scoring import score_dir
        res = score_dir(a.out_dir, a.answers)
        print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
