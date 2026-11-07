import pandas as pd
from stage2.pricing_compliance import evaluate_pricing_compliance
from stage2.payment_validation import evaluate_payment_validation

def run_tests():
    as_of_date = "2026-11-06"
    master = pd.read_csv("data/processed/master_leads.csv", keep_default_na=False).replace("", pd.NA)
    orders = pd.read_csv("data/processed/reconciliation_orders.csv", keep_default_na=False).replace("", pd.NA)
    policy = pd.read_csv("data/processed/policy_clean.csv", keep_default_na=False).replace("", pd.NA)
    
    pricing_flags = evaluate_pricing_compliance(master, orders, policy, as_of_date)
    payment_flags = evaluate_payment_validation(master, orders, as_of_date)
    all_flags = pd.DataFrame(pricing_flags + payment_flags)
    
    print("--- Milestone 1 Actual Test Results ---\n")
    
    # Matching Validation
    matched_orders_count = master["order_order_id"].replace("", pd.NA).notna().sum()
    assert matched_orders_count == 6, "Expected exactly 6 leads with orders"
    assert "DATA_QUALITY_ERROR" not in all_flags["flag_identifier"].values, "ID Mismatches or Ambiguous Order matches detected!"
    print(f"✅ ID Normalization successful: All {matched_orders_count} leads with orders matched exactly 1 record.")
    
    # LEAD-803
    f803 = all_flags[all_flags["lead_code"] == "LEAD-803"]
    assert f803.loc[f803["flag_identifier"] == "COMPLIANCE_VIOLATION", "automation_disposition"].iloc[0] == "BLOCK_AUTOMATED_SALES"
    assert f803.loc[f803["flag_identifier"] == "POLICY_CONFLICT", "automation_disposition"].iloc[0] == "WARN_ONLY"
    assert float(f803.loc[f803["flag_identifier"] == "COMPLIANCE_VIOLATION", "expected_value"].iloc[0]) == 950.0
    print("✅ LEAD-803: Block applied, warning separated, effective cap verified at exactly INR 950.")
    
    # LEAD-805
    f805 = all_flags[all_flags["lead_code"] == "LEAD-805"]
    assert "ARITHMETIC_INCONSISTENCY" not in f805["flag_identifier"].values
    assert float(f805.loc[f805["flag_identifier"] == "ARITHMETIC_VALID", "expected_value"].iloc[0]) == 5400.0
    print("✅ LEAD-805: 50% instalment arithmetic validated explicitly; expected value is exactly INR 5,400.")
    
    # LEAD-802
    f802 = all_flags[all_flags["lead_code"] == "LEAD-802"]
    assert "AED 12000.0" in str(f802.loc[f802["flag_identifier"] == "PRICE_MISMATCH_SEVERE", "observed_value"].iloc[0])
    assert "NOT_VALIDATABLE" in f802["flag_identifier"].values
    assert "ARITHMETIC_INCONSISTENCY" in f802["flag_identifier"].values
    print("✅ LEAD-802: AED 12,000 preserved, triggering PRICE_MISMATCH_SEVERE, NOT_VALIDATABLE, and ARITHMETIC_INCONSISTENCY.")
    
    # LEAD-809
    f809 = all_flags[all_flags["lead_code"] == "LEAD-809"]
    assert "NOT_VALIDATABLE" in f809["flag_identifier"].values
    print("✅ LEAD-809: Missing GBP safely returns NOT_VALIDATABLE.")
    
    # LEAD-804
    f804 = all_flags[all_flags["lead_code"] == "LEAD-804"]
    assert "PAYMENT_RECEIVED_CRM_STALE" in f804["flag_identifier"].values
    print("✅ LEAD-804: PAYMENT_RECEIVED_CRM_STALE flagged correctly.")
    
    all_flags.to_csv("s2_milestone1_flags.csv", index=False)
    print("\nFile 's2_milestone1_flags.csv' generated for reviewer inspection.")

if __name__ == "__main__":
    run_tests()