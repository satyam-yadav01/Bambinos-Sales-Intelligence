"""Customer-identity grouping (proposal only).

The CRM export has NO canonical/duplicate-of column. Leads that share ALL of user_id, student_id,
mobile and email are PROPOSED to be the same customer (SAME_CUSTOMER_PROPOSED); the earlier
created_at is labelled EARLIER. This grouping never merges, drops or overwrites a lead: the
operational master keeps one row per CRM lead and only references the relationship.
"""
from __future__ import annotations

import pandas as pd

IDENTITY_COLS = ["user_id", "student_id", "mobile", "email"]


def build_canonical_map(crm: pd.DataFrame) -> pd.DataFrame:
    keyed = crm.assign(_key=crm[IDENTITY_COLS].astype(str).agg("|".join, axis=1))
    ordered = keyed.sort_values(["created_at", "id"], na_position="last")
    canon_of_key = ordered.groupby("_key")["id"].first()
    out = pd.DataFrame({
        "lead_id": keyed["id"],
        "lead_code": keyed["lead_code"],
        "canonical_lead_id": keyed["_key"].map(canon_of_key),
        "crm_marks_duplicate": keyed["crm_lead_stage"].eq("New_Duplicate_Lead"),
    })
    out["canonical_lead_code"] = "LEAD-" + out["canonical_lead_id"]
    out["is_canonical"] = out["lead_id"].eq(out["canonical_lead_id"])
    out["mapping_basis"] = out["is_canonical"].map({True: "self (no identity match)", False: "identical user_id, student_id, mobile, email; earlier created_at"})
    out["mapping_status"] = out["is_canonical"].map({True: "NOT_APPLICABLE", False: "PROPOSED_PENDING_APPROVAL"})
    return out.sort_values("lead_id").reset_index(drop=True)


def partial_identity_overlaps(crm: pd.DataFrame, canon: pd.DataFrame) -> list[tuple[str, str, list[str]]]:
    """Leads sharing a single identity field but NOT mapped to the same canonical lead."""
    group_of = dict(zip(canon["lead_id"], canon["canonical_lead_id"]))
    found = []
    for col in IDENTITY_COLS:
        for value, grp in crm.groupby(col):
            ids = list(grp["id"])
            if len(ids) > 1 and len({group_of[i] for i in ids}) > 1:
                found.append((col, "<value withheld>", ["LEAD-" + i for i in ids]))
    return found


def build_identity_map(crm: pd.DataFrame, canon: pd.DataFrame) -> pd.DataFrame:
    """Reversible, auditable customer-identity relationships (one row per lead in a group)."""
    c = crm.set_index("id")
    size = canon.groupby("canonical_lead_id")["lead_id"].transform("count")
    rows = []
    for n, (_, g) in enumerate(canon[size > 1].groupby("canonical_lead_id"), 1):
        for r in g.sort_values("is_canonical", ascending=False).itertuples():
            rows.append({
                "customer_group_id": f"CG-{n:03d}", "lead_code": r.lead_code,
                "related_lead_codes": ", ".join(x for x in g["lead_code"] if x != r.lead_code),
                "relationship": "SAME_CUSTOMER_PROPOSED",
                "inquiry_order": "EARLIER" if r.is_canonical else "LATER",
                "lead_created_at": c.at[r.lead_id, "created_at"],
                "assigned_counsellor_id": c.at[r.lead_id, "assigned_counsellor_id"],
                "lead_source": c.at[r.lead_id, "lead_source"],
                "crm_lead_stage": c.at[r.lead_id, "crm_lead_stage"],
                "matched_fields": "user_id, student_id, mobile, email (values withheld)",
                "status": "PROPOSED_PENDING_APPROVAL",
                "action_on_lead_records": "none; both leads preserved unchanged",
                "reversible": True,
            })
    return pd.DataFrame(rows)
