"""Operational master lead table (one row per CRM lead) and reconciliation views.

Personal identifiers are excluded and free text is redacted; join to the raw CRM via lead_id if needed.
Descriptive facts only: no policy verdicts (Stage 2).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .common import PII_COLUMNS, parse_policy, payment_category

SEV = {"High": 3, "Medium": 2, "Low": 1, "Info": 0}


PROHIBITED = PII_COLUMNS | {"user_id", "student_id", "assigned_counsellor_name", "student_age", "student_grade", "city_timezone"}
TEXT_COLS = ["manual_rep_disposition", "manual_rep_notes", "call_rep_logged_disposition",
             "call_rep_logged_crm_note", "call_transcript_filename", "demo_current_skill_level_assessed",
             "demo_skill_strengths_observed", "demo_learning_gaps_observed", "demo_demo_magic_moment_for_parent",
             "demo_recommended_course_track", "demo_recommended_batch_type"]


def _attach(base: pd.DataFrame, table: pd.DataFrame, prefix: str, drop: list[str], name: str) -> pd.DataFrame:
    if table["lead_id"].duplicated().any():
        raise ValueError(f"{name}: more than one record per lead; collapsing rule needs a decision")
    keep = [c for c in table.columns if c not in drop + ["lead_id"]]
    t = table[["lead_id"] + keep].rename(columns={c: f"{prefix}{c}" for c in keep})
    return base.merge(t, on="lead_id", how="left")


def build_master(D: dict, idmap: pd.DataFrame, issues: pd.DataFrame, raw_dir: Path, redactor) -> pd.DataFrame:
    """One row per CRM lead (opportunity). Customer-identity relationships are referenced, never merged."""
    crm, demo, calls, orders, pol = (D[k] for k in ("crm", "demo", "calls", "orders", "policy"))

    base = crm.copy()
    base["timezone_label"] = base["city_timezone"].str.extract(r"\(([^)]+)\)")[0]
    base = base.drop(columns=[c for c in PROHIBITED if c in base.columns]).rename(columns={"id": "lead_id"})

    im = idmap[["lead_code", "customer_group_id", "relationship", "related_lead_codes", "inquiry_order"]].rename(columns={
        "relationship": "identity_relationship", "related_lead_codes": "identity_related_lead_codes", "inquiry_order": "identity_inquiry_order"})
    base = base.merge(im, on="lead_code", how="left")
    base["identity_relationship"] = base["identity_relationship"].fillna("NONE")

    base = _attach(base, demo, "demo_", ["student_id", "class_id", "demo_educator_name", "category_name"], "demo")
    base = _attach(base, calls, "call_", ["counsellor_name", "counsellor_id"], "calls")
    base = _attach(base, orders, "order_", ["student_id", "class_id", "parent_mobile", "plan_sessions"], "orders")

    pcols = parse_policy(pol)[["class_id", "course_name", "max_discount_pct"]].rename(columns={"course_name": "policy_course_name", "max_discount_pct": "policy_max_discount_pct"})
    base = base.merge(pcols, on="class_id", how="left")
    base["policy_found"] = base["policy_course_name"].notna()

    available = {p.name for p in raw_dir.glob("**/*.txt")}
    base["has_demo"] = base["demo_demo_id"].notna()
    base["has_call_log"] = base["call_call_id"].notna()
    base["has_order"] = base["order_order_id"].notna()
    base["transcript_available"] = base["call_transcript_filename"].isin(available)  # evaluated on the raw filename
    base["order_payment_category"] = base["order_payment_link_status"].map(lambda s: payment_category(s) if pd.notna(s) else pd.NA)

    per_lead = {}
    for r in issues.itertuples():
        per_lead.setdefault(r.record_key, []).append((r.issue_id, r.severity))
    ids, cnt, mx = [], [], []
    for code in base["lead_code"]:
        found = sorted(per_lead.get(code, []))
        ids.append(";".join(i for i, _ in found)); cnt.append(len(found))
        mx.append(max((s for _, s in found), key=lambda s: SEV[s], default="None"))
    base["dq_issue_ids"], base["dq_issue_count"], base["dq_max_severity"] = ids, cnt, mx

    for col in TEXT_COLS:  # redact personal data in free text (raw files untouched)
        if col in base.columns:
            base[col] = redactor.series(base[col])
    return base.sort_values("lead_id").reset_index(drop=True)


def build_coverage(D: dict, idmap: pd.DataFrame, raw_dir: Path) -> pd.DataFrame:
    crm, demo, calls, orders = D["crm"], D["demo"], D["calls"], D["orders"]
    available = {p.name for p in raw_dir.glob("**/*.txt")}
    out = crm[["lead_code"]].copy()
    out = out.merge(idmap[["lead_code", "relationship", "related_lead_codes"]].rename(columns={"relationship": "identity_relationship", "related_lead_codes": "identity_related_lead_codes"}), on="lead_code", how="left")
    out["identity_relationship"] = out["identity_relationship"].fillna("NONE")
    ids = crm["id"]
    out["has_demo_record"] = ids.isin(demo["lead_id"]).values
    out["has_call_log"] = ids.isin(calls["lead_id"]).values
    out["has_order"] = ids.isin(orders["lead_id"]).values
    out["crm_last_call_present"] = crm["last_call_at"].notna().values
    out["transcript_file_supplied"] = ids.map(lambda i: bool(calls.loc[calls["lead_id"] == i, "transcript_filename"].isin(available).any())).values
    return out


def build_order_recon(D: dict) -> pd.DataFrame:
    crm_i = D["crm"].set_index("id")
    polp = parse_policy(D["policy"]).set_index("class_id")
    col = {"INR": "standard_fee_india_inr", "AED": "standard_fee_gcc_aed", "USD": "standard_fee_usa_usd"}
    rows = []
    for r in D["orders"].itertuples():
        c = crm_i.loc[r.lead_id]
        lp = polp.at[r.class_id, col[r.currency]] if r.class_id in polp.index and r.currency in col else pd.NA
        rows.append({
            "lead_code": f"LEAD-{r.lead_id}", "order_id": r.order_id, "currency": r.currency,
            "standard_amount": r.standard_amount, "discount_applied": r.discount_applied, "net_payable_amount": r.net_payable_amount,
            "payment_plan_type": r.payment_plan_type, "payment_link_status": r.payment_link_status,
            "payment_category": payment_category(r.payment_link_status),
            "policy_list_price": lp,
            "recorded_standard_equals_list": (r.standard_amount == lp) if pd.notna(lp) else pd.NA,
            "policy_max_discount_pct": polp.at[r.class_id, "max_discount_pct"] if r.class_id in polp.index else pd.NA,
            "discount_pct_of_recorded_standard": round(100 * r.discount_applied / r.standard_amount, 2),
            "discount_pct_of_policy_list": round(100 * r.discount_applied / lp, 2) if pd.notna(lp) else pd.NA,
            "standard_minus_discount": r.standard_amount - r.discount_applied,
            "crm_stage": c["crm_lead_stage"], "crm_updated_at": c["updated_at"], "order_updated_at": r.updated_at,
            "order_updated_after_crm": r.updated_at > c["updated_at"],
        })
    return pd.DataFrame(rows)
