"""Stage 1 runner: python run_stage1.py [--raw-dir data/raw] [--out-dir outputs]

Reads the five raw CSVs (read-only), writes audit + master outputs to --out-dir.
Prints only counts/ids (no personal data).
"""
from __future__ import annotations

import argparse
import json
import platform
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from s1.audit import build_data_dictionary
from s1.checks import FKS, PKS, run_all
from s1.canonical import build_identity_map
from s1.common import load_all, parse_policy, sha256
from s1.privacy import Redactor
from s1.master import build_coverage, build_master, build_order_recon


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", default="data/raw", type=Path)
    ap.add_argument("--out-dir", default="outputs", type=Path)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    raw, typed, coercion, paths = load_all(args.raw_dir)
    rd = Redactor(typed["crm"])
    audit, canon = run_all(typed, coercion, args.raw_dir, rd)
    issues, checks = audit.issues_df(), audit.checks_df()
    for col in ("observed", "detail"):  # names inside evidence text (e.g. transcript filenames) are redacted
        issues[col] = rd.series(issues[col], phone=False)
    idmap = build_identity_map(typed["crm"], canon)
    master = build_master(typed, idmap, issues, args.raw_dir, rd)
    outputs = {
        "data_dictionary.csv": build_data_dictionary(typed, PKS, FKS, rd),
        "checks_run.csv": checks,
        "data_quality_issues.csv": issues,
        "lead_canonical_map.csv": idmap,
        "reconciliation_lead_coverage.csv": build_coverage(typed, idmap, args.raw_dir),
        "reconciliation_orders.csv": build_order_recon(typed),
        "policy_clean.csv": parse_policy(typed["policy"]),
        "master_leads.csv": master,
    }
    for name, df in outputs.items():
        df.to_csv(args.out_dir / name, index=False)

    manifest = {
        "run_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "python": platform.python_version(), "pandas": pd.__version__,
        "sources": {k: {"file": p.name, "sha256": sha256(p), "rows": len(raw[k]), "columns": len(raw[k].columns)} for k, p in paths.items()},
        "outputs": {n: {"rows": len(d), "columns": len(d.columns), "sha256": sha256(args.out_dir / n)} for n, d in outputs.items()},
    }
    (args.out_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2))

    print("Rows:", {k: len(v) for k, v in raw.items()})
    print("Master leads:", len(master), "| identity relationships:", len(idmap), "| checks:", len(checks), "| findings:", len(issues))
    print(issues["severity"].value_counts().to_dict())


if __name__ == "__main__":
    main()
