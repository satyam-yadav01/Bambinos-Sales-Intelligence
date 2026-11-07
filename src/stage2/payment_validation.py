import pandas as pd
from .flag_builder import build_flag

def normalize_id(val):
    if pd.isna(val) or val == "":
        return None
    try:
        return str(int(float(val)))
    except ValueError:
        return str(val).strip()

def evaluate_payment_validation(master: pd.DataFrame, orders: pd.DataFrame, as_of_date: str) -> list[dict]:
    flags = []
    orders = orders.copy()
    orders["norm_order_id"] = orders["order_id"].apply(normalize_id)
    
    for _, lead in master.iterrows():
        lead_code = lead["lead_code"]
        norm_lead_order_id = normalize_id(lead.get("order_order_id"))
        
        if not norm_lead_order_id:
            continue
            
        matched_orders = orders[orders["norm_order_id"] == norm_lead_order_id]
        if len(matched_orders) == 0:
            flags.append(build_flag(lead_code, "Payment", "DATA_QUALITY_ERROR", "High", "0 matches", "1 match", 
                                    "Order ID missing in orders extract.", "PAY-MIS", "master_leads.csv", "order_order_id", 
                                    norm_lead_order_id, "N/A", "Verify order records.", "REQUIRE_HUMAN_REVIEW", as_of_date))
            continue
        elif len(matched_orders) > 1:
            flags.append(build_flag(lead_code, "Payment", "DATA_QUALITY_ERROR", "High", f"{len(matched_orders)} matches", "1 match", 
                                    "Ambiguous order matching.", "PAY-AMB", "reconciliation_orders.csv", "order_id", 
                                    norm_lead_order_id, "N/A", "Resolve duplicate orders.", "REQUIRE_HUMAN_REVIEW", as_of_date))
            continue
            
        order = matched_orders.iloc[0]
        
        cat = str(lead.get("order_payment_category", ""))
        crm_stage = str(lead.get("crm_lead_stage", ""))
        if cat == "Paid" and crm_stage not in ["Paid", "Enrolled", "Won"]:
            flags.append(build_flag(lead_code, "Payment", "PAYMENT_RECEIVED_CRM_STALE", "Medium", f"CRM: {crm_stage}", "Order: Paid", 
                                    "Confirmed payment exists but CRM stage reflects earlier state.", "PAY-01", "master_leads.csv", 
                                    "crm_lead_stage", order["order_id"], "N/A", "Verify CRM and confirm enrolment.", "NO_BLOCK", as_of_date))

        std_amt = pd.to_numeric(order["standard_amount"], errors="coerce")
        discount = pd.to_numeric(order["discount_applied"], errors="coerce")
        net_recorded = pd.to_numeric(order["net_payable_amount"], errors="coerce")
        plan_type = str(order["payment_plan_type"])
        
        if pd.isna(std_amt) or pd.isna(discount) or pd.isna(net_recorded):
            flags.append(build_flag(lead_code, "Payment", "NOT_VALIDATABLE", "High", "Missing numeric data", "Valid numbers", 
                                    "Cannot validate arithmetic due to missing values.", "PAY-00", "reconciliation_orders.csv", 
                                    "multiple", order["order_id"], "N/A", "Fix source data.", "REQUIRE_HUMAN_REVIEW", as_of_date))
            continue
            
        expected_course_total = std_amt - discount
        
        if "50% Down" in plan_type:
            expected_net = expected_course_total * 0.5
            semantics = "50% first instalment"
        elif "Installment" in plan_type:
            flags.append(build_flag(lead_code, "Payment", "NOT_VALIDATABLE", "Medium", plan_type, "Recognized semantics", 
                                    "Instalment percentage not explicitly configured for validation.", "PAY-03", "reconciliation_orders.csv", 
                                    "payment_plan_type", order["order_id"], "N/A", "Review manual payment structure.", "REQUIRE_HUMAN_REVIEW", as_of_date))
            continue
        else:
            expected_net = expected_course_total
            semantics = "full course net"
            
        if abs(expected_net - net_recorded) > 0.01:
            flags.append(build_flag(lead_code, "Payment", "ARITHMETIC_INCONSISTENCY", "High", net_recorded, expected_net, 
                                    f"Recorded net does not match expected {semantics} ({std_amt} - {discount}).", "PAY-02", 
                                    "reconciliation_orders.csv", "net_payable_amount", order["order_id"], "N/A", 
                                    "Review source data inconsistency.", "REQUIRE_HUMAN_REVIEW", as_of_date))
        else:
            flags.append(build_flag(lead_code, "Payment", "ARITHMETIC_VALID", "Info", net_recorded, expected_net, 
                                    f"Recorded net accurately matches expected {semantics}.", "PAY-02-PASS", 
                                    "reconciliation_orders.csv", "net_payable_amount", order["order_id"], "N/A", 
                                    "None", "NO_BLOCK", as_of_date))
            
    return flags