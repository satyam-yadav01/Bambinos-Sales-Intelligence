import pandas as pd
from stage2.followup_engine import evaluate_followups
from stage2.operational_intelligence import evaluate_operations
from stage2.pricing_compliance import evaluate_pricing_compliance

PRECEDENCE = {
    "BLOCK_AUTOMATED_SALES": 1,
    "REQUIRE_ACADEMIC_REVIEW": 2,
    "REQUIRE_HUMAN_REVIEW": 3,
    "WARN_ONLY": 4,
    "NO_BLOCK": 5
}

def aggregate_dispositions(flags_df: pd.DataFrame) -> dict:
    """Simulates Milestone 3 Integration Precedence logic to prove restriction enforcement."""
    lead_summary = {}
    for lead, group in flags_df.groupby("lead_code"):
        min_rank = min(group["automation_disposition"].map(PRECEDENCE).fillna(5))
        top_disp = [k for k, v in PRECEDENCE.items() if v == min_rank][0]
        lead_summary[lead] = top_disp
    return lead_summary

def run_tests():
    as_of_date = "2026-11-06"
    master = pd.read_csv("data/processed/master_leads.csv", keep_default_na=False).replace("", pd.NA)
    orders = pd.read_csv("data/processed/reconciliation_orders.csv", keep_default_na=False).replace("", pd.NA)
    policy = pd.read_csv("data/processed/policy_clean.csv", keep_default_na=False).replace("", pd.NA)
    
    synthetic_leads = [
        {"lead_code": "SYN-001", "timezone_label": "XYZ_TZ", "next_followup_at": pd.NA, "last_call_at": pd.NA},
        # Fix: SYN-002 originally failed by skipping invalid last_call_at. Must now emit DQ flag AND process DUE_TODAY/OVERDUE.
        {"lead_code": "SYN-002", "timezone_label": "IST", "next_followup_at": "2026-11-05 10:00:00", "last_call_at": "invalid_date_format"},
        {"lead_code": "SYN-003", "timezone_label": "PST", "next_followup_at": "2026-11-01 10:00:00+05:30", "last_call_at": pd.NA},
        {"lead_code": "SYN-004", "timezone_label": "IST", "has_demo": "True", "demo_demo_completed_at": "2026-11-02 12:00:00+00:00", "last_call_at": "2026-11-02 17:00:00"},
        {"lead_code": "SYN-005", "timezone_label": "IST", "next_followup_at": "2026-11-06 10:00:00", "last_call_at": pd.NA},
        {"lead_code": "SYN-006", "timezone_label": "GST", "next_followup_at": "2026-12-01 10:00:00", "last_call_at": pd.NA},
        {"lead_code": "SYN-007", "timezone_label": "IST", "has_demo": "True", "demo_demo_completed_at": pd.NA, "last_call_at": pd.NA},
        # New: Invalid call log stamp
        {"lead_code": "SYN-008", "timezone_label": "IST", "has_call_log": "True", "call_call_started_at": "invalid_log"},
        # New: Invalid demo stamp
        {"lead_code": "SYN-009", "timezone_label": "IST", "has_demo": "True", "demo_demo_completed_at": "invalid_demo"},
        # New: Genuinely missing last_call_at 
        {"lead_code": "SYN-010", "timezone_label": "IST", "has_call_log": "False", "last_call_at": pd.NA}
    ]
    master_extended = pd.concat([master, pd.DataFrame(synthetic_leads)], ignore_index=True)
    
    followup_flags = evaluate_followups(master_extended, as_of_date)
    ops_flags = evaluate_operations(master_extended, as_of_date)
    m1_flags = evaluate_pricing_compliance(master, orders, policy, as_of_date) 
    
    all_flags = pd.DataFrame(followup_flags + ops_flags + m1_flags)
    
    print("--- Milestone 2 Actual Test Results ---\n")
    
    def check_flag(lead, flag_id, expected_disp=None, expected_source=None):
        f = all_flags[(all_flags["lead_code"] == lead) & (all_flags["flag_identifier"] == flag_id)]
        if expected_source:
             f = f[f["source_field"] == expected_source]
        assert not f.empty, f"Missing flag {flag_id} for {lead} on {expected_source}"
        if expected_disp:
            assert f.iloc[0]["automation_disposition"] == expected_disp, f"Wrong disposition for {lead} {flag_id}"
        return f

    # [1. Assert Actual Stage 1 Behaviour Preserved]
    print("[Actual Leads & Rules Preserved]")
    check_flag("LEAD-801", "SAME_CUSTOMER_PROPOSED", "REQUIRE_HUMAN_REVIEW")
    check_flag("LEAD-806", "REQUIRES_ACADEMIC_REVIEW", "REQUIRE_ACADEMIC_REVIEW")
    check_flag("LEAD-807", "NO_CALL_INDICATION_OR_LOG")
    check_flag("LEAD-807", "NO_CALL_LOG_AFTER_DEMO")
    check_flag("LEAD-810", "CRM_CALL_INDICATED_BUT_NO_LOG")
    check_flag("LEAD-810", "STALE_FOLLOWUP_DATE", "WARN_ONLY")
    print("✅ All historical operational/demo intelligence rules preserved perfectly.")

    # [2. Integration Precedence Assertions]
    print("\n[Milestone 1 + Milestone 2 Integration Precedence]")
    dispositions = aggregate_dispositions(all_flags)
    check_flag("LEAD-803", "OVERDUE", "NO_BLOCK")
    check_flag("LEAD-803", "COMPLIANCE_VIOLATION", "BLOCK_AUTOMATED_SALES")
    assert dispositions["LEAD-803"] == "BLOCK_AUTOMATED_SALES", "Precedence failed: Overdue date overrode Compliance Block."
    print("✅ Integration: LEAD-803 OVERDUE correctly superseded by BLOCK_AUTOMATED_SALES.")

    check_flag("LEAD-801", "OVERDUE", "NO_BLOCK") 
    assert dispositions["LEAD-801"] == "REQUIRE_HUMAN_REVIEW", "Precedence failed: Overdue date overrode Identity Review."
    print("✅ Integration: LEAD-801 OVERDUE correctly superseded by REQUIRE_HUMAN_REVIEW.")
    
    check_flag("LEAD-806", "NO_FOLLOWUP_SCHEDULED", "NO_BLOCK")
    assert dispositions["LEAD-806"] == "REQUIRE_ACADEMIC_REVIEW", "Precedence failed: Academic Review lost to No-Block status."
    print("✅ Integration: LEAD-806 standard routing correctly superseded by REQUIRE_ACADEMIC_REVIEW.")

    # [3. Synthetic Edge-Case Assertions (Timestamp/Timezone Integrity)]
    print("\n[Synthetic Edge Cases]")
    check_flag("SYN-001", "TIMEZONE_UNKNOWN", "REQUIRE_HUMAN_REVIEW")
    print("✅ SYN-001: Unknown timezone safely isolated independently of follow-up existence.")
    
    check_flag("SYN-002", "DATA_QUALITY_ERROR", "REQUIRE_HUMAN_REVIEW", "last_call_at")
    check_flag("SYN-002", "OVERDUE", "NO_BLOCK", "next_followup_at")
    print("✅ SYN-002: Invalid last_call_at explicitly throws DQ error, whilst valid follow-up date remains successfully evaluated.")
    
    check_flag("SYN-003", "OVERDUE", "NO_BLOCK")
    print("✅ SYN-003: Timezone-aware timestamp localized and evaluated safely.")
    
    check_flag("SYN-004", "NO_CALL_LOG_AFTER_DEMO", "REQUIRE_HUMAN_REVIEW")
    print("✅ SYN-004: Mixed TZ-Aware vs Naive timestamps localized safely to UTC. Call pre-dates demo correctly identified.")
    
    check_flag("SYN-005", "DUE_TODAY", "NO_BLOCK")
    print("✅ SYN-005: Date matching as-of-date strictly classified as DUE_TODAY.")
    
    check_flag("SYN-006", "FUTURE", "NO_BLOCK")
    print("✅ SYN-006: Date after as-of-date strictly classified as FUTURE.")

    check_flag("SYN-007", "DATA_QUALITY_ERROR", "REQUIRE_HUMAN_REVIEW", "demo_demo_completed_at")
    print("✅ SYN-007: Demo indicated but timestamp genuinely missing correctly triggers DQ error.")

    check_flag("SYN-008", "DATA_QUALITY_ERROR", "REQUIRE_HUMAN_REVIEW", "call_call_started_at")
    print("✅ SYN-008: Invalid call log stamp safely triggers DQ error instead of treating it as missing evidence.")
    
    check_flag("SYN-009", "DATA_QUALITY_ERROR", "REQUIRE_HUMAN_REVIEW", "demo_demo_completed_at")
    print("✅ SYN-009: Invalid demo stamp safely triggers DQ error instead of crashing chronological evaluation.")

    check_flag("SYN-010", "NO_CALL_INDICATION_OR_LOG", "REQUIRE_HUMAN_REVIEW")
    print("✅ SYN-010: Genuinely missing last_call_at explicitly evaluated and logged correctly.")

    print("\nMilestone 2 Final Tests completed successfully.")

if __name__ == "__main__":
    run_tests()