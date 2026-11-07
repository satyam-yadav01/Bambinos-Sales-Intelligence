"""Post-run validation: python validate_stage1.py [--raw-dir data/raw] [--out-dir outputs] [--baseline path/to/old_manifest.json]

Exit code 1 if any check fails. Prints only pass/fail lines (no personal data).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import pandas as pd

from s1.common import find_raw_files, sha256
from s1.master import TEXT_COLS
from s1.privacy import Redactor

FREE_TEXT = {"master_leads.csv": TEXT_COLS, "data_quality_issues.csv": ["observed", "detail"], "data_dictionary.csv": ["example_values"]}

PROHIBITED_EXACT = {"user_id", "student_id", "assigned_counsellor_name", "counsellor_name", "student_name", "parent_name",
                    "mobile", "email", "parent_mobile", "student_age", "student_grade", "city_timezone", "demo_educator_name"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", default="data/raw", type=Path)
    ap.add_argument("--out-dir", default="outputs", type=Path)
    ap.add_argument("--baseline", type=Path, help="earlier run_manifest.json whose source checksums must still match")
    a = ap.parse_args()
    results = []

    def check(name, ok):
        results.append((name, bool(ok)))

    paths = find_raw_files(a.raw_dir)
    raw_crm = pd.read_csv(paths["crm"], dtype=str, keep_default_na=False)
    master = pd.read_csv(a.out_dir / "master_leads.csv", dtype=str, keep_default_na=False)
    idmap = pd.read_csv(a.out_dir / "lead_canonical_map.csv", dtype=str, keep_default_na=False)
    manifest = json.loads((a.out_dir / "run_manifest.json").read_text())

    check("master has 12 rows", len(master) == 12)
    check("every CRM lead_code appears exactly once", sorted(master["lead_code"]) == sorted(raw_crm["lead_code"]) and master["lead_code"].is_unique)
    m = master.set_index("lead_code")
    check("LEAD-801 and LEAD-811 are separate rows", {"LEAD-801", "LEAD-811"} <= set(m.index))
    raw = raw_crm.set_index("lead_code")
    for code in ("LEAD-801", "LEAD-811"):
        check(f"{code} keeps its own counsellor id, created_at, stage",
              m.at[code, "assigned_counsellor_id"] == raw.at[code, "assigned_counsellor_id"]
              and m.at[code, "created_at"] == raw.at[code, "created_at"]
              and m.at[code, "crm_lead_stage"] == raw.at[code, "crm_lead_stage"])
    check("801/811 counsellors and creation dates differ (both preserved)",
          m.at["LEAD-801", "assigned_counsellor_id"] != m.at["LEAD-811", "assigned_counsellor_id"] and m.at["LEAD-801", "created_at"] != m.at["LEAD-811", "created_at"])
    check("identity map has both leads as SAME_CUSTOMER_PROPOSED",
          set(idmap["lead_code"]) == {"LEAD-801", "LEAD-811"} and (idmap["relationship"] == "SAME_CUSTOMER_PROPOSED").all())
    check("master references the relationship on both leads",
          all(m.at[c, "identity_relationship"] == "SAME_CUSTOMER_PROPOSED" for c in ("LEAD-801", "LEAD-811")) and (m["identity_relationship"] == "NONE").sum() == 10)
    check("no other leads in identity map", len(idmap) == 2)
    check("prohibited identifying columns absent from master", not (set(master.columns) & PROHIBITED_EXACT))
    check("no column name hints at contact/identity data", not [c for c in master.columns if re.search(r"mobile|email|phone|user_id|student_id|(student|parent|counsellor)_name", c)])

    rd = Redactor(raw_crm)
    values = set(raw_crm["mobile"]) | set(raw_crm["email"])
    leaks = []
    for f in sorted(a.out_dir.glob("*.csv")):
        text = f.read_text()
        df = pd.read_csv(f, dtype=str, keep_default_na=False)
        scan_cols = [c for c in FREE_TEXT.get(f.name, []) if c in df.columns]
        cells = df[scan_cols].stack() if scan_cols else []
        hit = any(v and v in text for v in values) or any(rd.redact(c, phone=False)[1] for c in cells if isinstance(c, str))
        if hit:
            leaks.append(f.name)
    check(f"no student/parent names (incl. masked-shape matches), mobile or email in any output CSV ({leaks or 'none'})", not leaks)

    for k, p in paths.items():
        check(f"raw {k} checksum matches manifest", manifest["sources"][k]["sha256"] == sha256(p))
    if a.baseline:
        base = json.loads(a.baseline.read_text())["sources"]
        for k, p in paths.items():
            check(f"raw {k} checksum equals baseline run", base[k]["sha256"] == sha256(p))

    for name, ok in results:
        print(("PASS  " if ok else "FAIL  ") + name)
    print(f"\n{sum(ok for _, ok in results)}/{len(results)} validation checks passed")
    return 0 if all(ok for _, ok in results) else 1


if __name__ == "__main__":
    sys.exit(main())
