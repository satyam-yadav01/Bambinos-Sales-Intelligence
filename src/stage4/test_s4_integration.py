import pandas as pd
import os
import sys
import json

def run_tests():
    print("--- Stage 4 Integration Tests Execution ---\n")
    passed = 0
    total = 0

    def assert_test(condition, name):
        nonlocal passed, total
        total += 1
        if condition:
            passed += 1
            print(f"✅ {name}")
        else:
            print(f"❌ {name}")

    summary = pd.read_csv("s4/sales_intelligence_summary.csv")
    flags = pd.read_csv("s4/sales_intelligence_flags.csv")
    
    with open("s4/run_manifest.json") as f:
        manifest = json.load(f)

    # 1. 12 unique leads
    assert_test(len(summary) == 12, "Test 1: Exactly 12 leads in the consolidated summary")
    assert_test(summary["lead_code"].nunique() == 12, "Test 2: No duplicate lead codes")
    expected_codes = {f"LEAD-{801+i}" for i in range(12)}
    assert_test(set(summary["lead_code"]) == expected_codes, "Test 3: Expected 12 lead codes are present exactly once")
    
    # 2. LEAD-809 is NOT_VALIDATABLE, not PASS
    l809 = summary[summary["lead_code"] == "LEAD-809"].iloc[0]
    assert_test(l809["discount_compliance_status"] == "NOT_VALIDATABLE", "Test 4: LEAD-809 is NOT_VALIDATABLE, not PASS")

    # 3. All six Stage 3 records are labelled as draft reference annotations
    s3_leads = summary[summary["lead_code"].isin(["LEAD-801", "LEAD-802", "LEAD-803", "LEAD-804", "LEAD-805", "LEAD-806"])]
    assert_test(all(s3_leads["call_intelligence_status"] == "OFFLINE_DRAFT_REFERENCE"), "Test 5: Stage 3 records labelled as draft reference annotations")

    # 4. LEAD-803 has both an automation block and a human-review requirement
    l803 = summary[summary["lead_code"] == "LEAD-803"].iloc[0]
    assert_test(l803["automation_block"] == True and l803["requires_human_review"] == True, "Test 6: LEAD-803 has both automation block and human-review requirement")
    assert_test(l803["automation_disposition"] == "BLOCK_AUTOMATED_SALES", "Test 7: Overall disposition precedence remains correct (LEAD-803)")

    # 5. Execution date is configurable and appears correctly in the manifest
    assert_test(manifest["execution_date"] == "2026-11-07", "Test 8: Execution date appears correctly in manifest")

    # Other existing tests
    l806 = summary[summary["lead_code"] == "LEAD-806"].iloc[0]
    assert_test(l806["requires_academic_review"] == True, "Test 9: LEAD-806 requires academic review natively")
    
    l804 = summary[summary["lead_code"] == "LEAD-804"].iloc[0]
    assert_test(l804["payment_status"] == "PAID (CRM STALE)", "Test 10: LEAD-804 remains Paid despite stale CRM status")
    
    l805 = summary[summary["lead_code"] == "LEAD-805"].iloc[0]
    assert_test(l805["payment_status"] == "FAILED" and l805["s3_purchase_readiness"] == "READY_TO_PURCHASE", "Test 11: LEAD-805 remains Failed despite stated intention to pay")
    
    l801 = summary[summary["lead_code"] == "LEAD-801"].iloc[0]
    l811 = summary[summary["lead_code"] == "LEAD-811"].iloc[0]
    assert_test(l801["requires_identity_review"] == True and l811["requires_identity_review"] == True, "Test 12: LEAD-801/811 natively trigger identity review separately")
    
    no_transcripts = summary[summary["lead_code"].isin(["LEAD-807", "LEAD-808", "LEAD-809", "LEAD-810", "LEAD-811", "LEAD-812"])]
    assert_test(all(no_transcripts["call_intelligence_status"] == "NO_TRANSCRIPT"), "Test 13: LEAD-807–812 have no fabricated transcript intelligence")

    l808 = summary[summary["lead_code"] == "LEAD-808"].iloc[0]
    assert_test(l808["discount_compliance_status"] == "UNKNOWN", "Test 14: Unknown policies handled safely")

    assert_test(l803["next_best_action"] == "HALT OUTREACH - Compliance Violation", "Test 15: Stage 3 cannot override Stage 2 restrictions")
    
    assert_test(len(flags) > 0 and set(flags["lead_code"]).issubset(set(summary["lead_code"])), "Test 16: Granular flags and consolidated summaries remain consistent")
    assert_test(os.path.exists("s4/run_manifest.json") and os.path.exists("s4/FINAL_SALES_INTELLIGENCE_REPORT.md"), "Test 17: Output files are generated successfully")
    
        # 6. Test robust failure if master_leads.csv is missing
    print("Testing failure constraints...")
    import subprocess
    import sys
    from pathlib import Path

    master_path = Path("data/processed/master_leads.csv")
    temp_path = Path("data/processed/master_leads_temp.csv")
    bad_path = Path("data/processed/master_leads_bad.csv")
    integration_script = "src/stage4/s4_integration.py"

    # Test 18: Missing master file
    master_path.rename(temp_path)
    try:
        res = subprocess.run(
            [sys.executable, integration_script, "--as-of-date", "2026-11-07"],
            capture_output=True, text=True
        )
    finally:
        temp_path.rename(master_path)

    assert_test(
        res.returncode == 1 and "not found" in res.stdout.lower(),
        "Test 18: System explicitly halts when master_leads.csv is missing"
    )

    # Test 19: Master file has incorrect row count
    test_df = pd.read_csv(master_path)
    test_df.head(5).to_csv(bad_path, index=False)

    master_path.rename(temp_path)
    bad_path.rename(master_path)

    try:
        res2 = subprocess.run(
            [sys.executable, integration_script, "--as-of-date", "2026-11-07"],
            capture_output=True, text=True
        )
    finally:
        master_path.unlink(missing_ok=True)
        temp_path.rename(master_path)

    assert_test(
        res2.returncode == 1 and "exactly 12" in res2.stdout,
        "Test 19: System explicitly halts when master_leads.csv does not have exactly 12 leads"
    )

    print(f"\nTotal Pass/Fail: {passed}/{total}")
    if passed < total:
        sys.exit(1)

if __name__ == '__main__':
    run_tests()
