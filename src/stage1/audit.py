"""Audit trail: every check is logged (pass or flag) and every finding becomes an issue row."""
from __future__ import annotations

import pandas as pd

SEVERITY_RANK = {"High": 0, "Medium": 1, "Low": 2, "Info": 3}


def F(dataset, record_key, field, observed, detail, severity="Medium", category="", decision=""):
    """Build one finding. `decision` is non-empty when a human must approve/resolve it."""
    return {"dataset": dataset, "record_key": record_key, "field": field, "observed": observed,
            "detail": detail, "severity": severity, "category": category, "decision_required": decision}


class Audit:
    def __init__(self):
        self.checks, self.issues = [], []

    def record(self, check_id: str, description: str, tested: int, failures: list[dict]):
        self.checks.append({"check_id": check_id, "description": description, "records_tested": tested,
                            "findings": len(failures), "result": "PASS" if not failures else "FLAGGED"})
        self.issues += [{"check_id": check_id, **f} for f in failures]

    def checks_df(self) -> pd.DataFrame:
        return pd.DataFrame(self.checks)

    def issues_df(self) -> pd.DataFrame:
        df = pd.DataFrame(self.issues)
        df["_r"] = df["severity"].map(SEVERITY_RANK)
        df = df.sort_values(["_r", "check_id", "record_key"]).drop(columns="_r").reset_index(drop=True)
        df.insert(0, "issue_id", [f"DQ-{i + 1:03d}" for i in range(len(df))])
        df["status"] = "OPEN"
        return df


DESCRIPTIONS = {
    "crm.id": "Numeric CRM lead id. PK. Equals the number in lead_code and is the lead_id used by demo/call/order files.",
    "crm.lead_code": "Display code LEAD-<id>.",
    "crm.user_id": "Parent/account id. Shared by duplicate inquiries.",
    "crm.student_id": "Child id. FK target for demo/orders student_id.",
    "crm.class_id": "Course pitched. FK to policy.class_id.",
    "crm.course_pitched": "Course name as typed in CRM (can differ from policy course_name).",
    "crm.assigned_counsellor_id": "Counsellor id. Matches calls.counsellor_id.",
    "crm.crm_lead_stage": "Pipeline stage. Vocabulary has no paid/enrolled value.",
    "crm.manual_rep_disposition": "Free-form disposition typed by rep.",
    "crm.manual_rep_notes": "Free-text rep note; often very short.",
    "crm.last_call_at": "Time of last call per CRM. NULL = never called.",
    "crm.next_followup_at": "Scheduled follow-up. NULL = none scheduled.",
    "crm.deleted_at": "Soft-delete marker; NULL = active.",
    "demo.demo_id": "PK. Demo evaluation id.",
    "demo.lead_id": "FK to crm.id.",
    "demo.demo_batch_size": "Number of children in the demo batch.",
    "demo.child_engagement_score_1_to_5": "Educator's engagement rating, 1 (low) to 5 (high).",
    "demo.demo_magic_moment_for_parent": "Educator free text. Some rows embed rep-action annotations in this field.",
    "demo.recommended_course_track": "Free-text track recommendation (not an id; may not match a policy course).",
    "demo.recommended_batch_type": "Batch format recommended by the educator.",
    "calls.call_id": "PK. Call log id.",
    "calls.lead_id": "FK to crm.id.",
    "calls.transcript_filename": "Name of transcript file. Files were NOT supplied with the five CSVs.",
    "calls.rep_talk_time_pct": "Share of call time the rep spoke; rep + parent pct should total 100.",
    "calls.rep_logged_disposition": "Disposition the rep recorded after the call.",
    "orders.order_id": "PK. Order id.",
    "orders.invoice_number": "Unique invoice number; suffix equals order_id.",
    "orders.lead_id": "FK to crm.id.",
    "orders.standard_amount": "List price recorded on the order, in `currency`.",
    "orders.discount_applied": "Absolute discount amount in `currency` (not a percentage).",
    "orders.net_payable_amount": "Amount due on this payment. For instalments this is the instalment, not the course net.",
    "orders.payment_plan_type": "Full payment, instalment or custom link.",
    "orders.payment_link_status": "Gateway-side payment status.",
    "orders.gateway_error_reason": "Gateway failure/flag reason text.",
    "orders.paid_at": "Settlement time; NULL unless paid.",
    "policy.class_id": "PK. Course id referenced by crm/demo/orders.",
    "policy.standard_fee_india_inr": "Official list price (INR). Policy has no GBP/UK column.",
    "policy.standard_fee_gcc_aed": "Official list price (AED).",
    "policy.standard_fee_usa_usd": "Official list price (USD).",
    "policy.max_rep_discount_allowed_pct": "Text: max rep discount % plus per-currency caps.",
    "policy.forbidden_compliance_red_flags": "Text of behaviours counsellors must not exhibit.",
}


WITHHELD = {"user_id", "student_id", "assigned_counsellor_name", "counsellor_name", "student_age", "student_grade", "city_timezone"}


def build_data_dictionary(typed: dict, pks: dict, fks: dict, redactor) -> pd.DataFrame:
    from .common import PII_COLUMNS
    rows = []
    for ds, df in typed.items():
        for col in df.columns:
            s = df[col]
            role = "PK" if pks.get(ds) == col else ("FK->" + fks[(ds, col)] if (ds, col) in fks else "")
            if col in PII_COLUMNS or col in WITHHELD:
                role = (role + (" PII" if col in PII_COLUMNS else " personal identifier")).strip()
                example = "(withheld)"
            else:
                vals = [redactor.redact(str(v), phone=False)[0][:40] for v in s.dropna().astype(str).unique()[:2]]
                example = " | ".join(vals)
            rows.append({"dataset": ds, "column": col, "inferred_type": str(s.dtype), "role": role,
                         "non_null": int(s.notna().sum()), "null_count": int(s.isna().sum()),
                         "distinct": int(s.nunique()), "example_values": example,
                         "description": DESCRIPTIONS.get(f"{ds}.{col}", "")})
    return pd.DataFrame(rows)
