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
    r.add_argument("--report", action="append", dest="reports", help="limit to a report (repeatable)")
    r.add_argument("--metric", action="append", dest="metrics", help="limit to a metric (repeatable)")
    e = sub.add_parser("extract", help="extract configured PDF/CSV sources and write review evidence")
    e.add_argument("config")
    e.add_argument("--out", default="reconloop_out/extraction")
    v = sub.add_parser("revisions", help="compare two declared data vintages with the definition held fixed")
    v.add_argument("config")
    v.add_argument("--metric", required=True)
    v.add_argument("--parameter", required=True)
    v.add_argument("--before", required=True)
    v.add_argument("--after", required=True)
    v.add_argument("--report", action="append", dest="reports")
    v.add_argument("--records", help="reuse final choices from a reconciliation output directory")
    v.add_argument("--out", default="reconloop_out/revisions")
    j = sub.add_parser("job", help="run an isolated batch with a manifest and scheduler exit status")
    j.add_argument("config")
    j.add_argument("--out", default="reconloop_jobs")
    j.add_argument("--judge", choices=["search", "stated_rule"], default="stated_rule")
    s = sub.add_parser("score", help="compare final definitions with known answers (demo / eval sets)")
    s.add_argument("out_dir"); s.add_argument("answers")
    d = sub.add_parser("doctor", help="check PDF/OCR dependencies and optionally probe storage")
    d.add_argument("--ocr", action="store_true")
    d.add_argument("--path")
    d.add_argument("--write-probe", action="store_true")
    p = sub.add_parser("publish-targets", help="publish a complete extraction directory as an immutable verified bundle")
    p.add_argument("extraction_dir")
    p.add_argument("store_root")
    p.add_argument("--id", dest="bundle_id")
    a = ap.parse_args(argv)

    if a.cmd == "doctor":
        from .doctor import diagnose
        result = diagnose(ocr=a.ocr, path=a.path, write_probe=a.write_probe)
        print(json.dumps(result, indent=2))
        if not result["ok"]:
            raise SystemExit(1)
    elif a.cmd == "publish-targets":
        from .storage import publish_targets
        print(publish_targets(a.extraction_dir, a.store_root, bundle_id=a.bundle_id))
    elif a.cmd == "run":
        from .config import run_config
        from .judge import SearchJudge, StatedRuleJudge
        judge = SearchJudge() if a.judge == "search" else StatedRuleJudge()
        recs = run_config(a.config, judge=judge, out_dir=a.out, reports=a.reports, metrics=a.metrics)
        print(f"\nwrote {Path(a.out) / 'report.md'}  ({len(recs)} records)")
    elif a.cmd == "job":
        from .jobs import run_job
        from .judge import SearchJudge, StatedRuleJudge
        judge = SearchJudge() if a.judge == "search" else StatedRuleJudge()
        result = run_job(a.config, a.out, judge=judge)
        print(json.dumps(result, indent=2))
        if result["status"] != "complete":
            raise SystemExit(3 if result["status"] == "needs_review" else 1)
    elif a.cmd == "revisions":
        from .revisions import revisions_config
        evidence = revisions_config(a.config, metric=a.metric, parameter=a.parameter, before=a.before,
                                    after=a.after, reports=a.reports, records_dir=a.records, out_dir=a.out)
        print(f"wrote {len(evidence)} vintage comparisons to {a.out}")
    elif a.cmd == "score":
        from .scoring import score_dir
        res = score_dir(a.out_dir, a.answers)
        print(json.dumps(res, indent=2))
    elif a.cmd == "extract":
        import tomllib
        from .extract.sources import load_sources
        from .storage import local_path
        path = local_path(a.config)
        config = tomllib.loads(path.read_text(encoding="utf-8"))
        result = load_sources(config["targets"], path.parent, evidence_dir=local_path(a.out) / "crops")
        result.write(a.out)
        print(f"wrote {len(result.targets)} targets and {len(result.issues)} review issues to {a.out}")
        if result.issues:
            raise SystemExit(2)


if __name__ == "__main__":
    main()
