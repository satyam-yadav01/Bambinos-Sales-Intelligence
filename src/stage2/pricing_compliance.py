import pandas as pd
from .flag_builder import build_flag

CAP_COLS = {"INR": "cap_inr", "AED": "cap_aed", "USD": "cap_usd"}
LIST_COLS = {"INR": "standard_fee_india_inr", "AED": "standard_fee_gcc_aed", "USD": "standard_fee_usa_usd"}

def normalize_id(val):
    if pd.isna(val) or val == "":
        return None
    try:
        return str(int(float(val)))
    except ValueError:
        return str(val).strip()

def evaluate_pricing_compliance(master: pd.DataFrame, orders: pd.DataFrame, policy: pd.DataFrame, as_of_date: str) -> list[dict]:
    flags = []
    
    # Normalize class_id in policy for safe matching
    policy = policy.copy()
    policy["norm_class_id"] = policy["class_id"].apply(normalize_id)
    pol_map = policy.set_index("norm_class_id")
    
    # Normalize order IDs in orders dataset for safe matching
    orders = orders.copy()
    orders["norm_order_id"] = orders["order_id"].apply(normalize_id)
    
    for _, lead in master.iterrows():
        lead_code = lead["lead_code"]
        class_id = normalize_id(lead.get("class_id"))
        
        norm_lead_order_id = normalize_id(lead.get("order_order_id"))
        
        if not norm_lead_order_id:
            if pd.isna(lead.get("policy_found")) or str(lead.get("policy_found")).lower() == "false":
                flags.append(build_flag(lead_code, "Pricing", "UNKNOWN_POLICY", "Medium", "Policy Missing", "Policy Exists", 
                                        f"Class {class_id} missing from policy file.", "PRC-01", "master_leads.csv", "class_id", 
                                        "N/A", "N/A", "Provide policy or confirm out of scope.", "WARN_ONLY", as_of_date))
            continue
            
        matched_orders = orders[orders["norm_order_id"] == norm_lead_order_id]
        if len(matched_orders) == 0:
            flags.append(build_flag(lead_code, "Pricing", "DATA_QUALITY_ERROR", "High", "0 matches", "1 match", 
                                    "Order ID present in master but missing in orders extract.", "PRC-MIS", "master_leads.csv", "order_order_id", 
                                    norm_lead_order_id, "N/A", "Verify order records.", "REQUIRE_HUMAN_REVIEW", as_of_date))
            continue
        elif len(matched_orders) > 1:
            flags.append(build_flag(lead_code, "Pricing", "DATA_QUALITY_ERROR", "High", f"{len(matched_orders)} matches", "1 match", 
                                    "Ambiguous order matching.", "PRC-AMB", "reconciliation_orders.csv", "order_id", 
                                    norm_lead_order_id, "N/A", "Resolve duplicate orders.", "REQUIRE_HUMAN_REVIEW", as_of_date))
            continue
            
        order = matched_orders.iloc[0]
        currency = order["currency"]
        
        if class_id not in pol_map.index:
            flags.append(build_flag(lead_code, "Pricing", "UNKNOWN_POLICY", "Medium", "Policy Missing", "Policy Exists", 
                                    f"Cannot validate transaction; class {class_id} not in policy.", "PRC-02", "reconciliation_orders.csv", 
                                    "class_id", order["order_id"], "N/A", "Review manual pricing.", "WARN_ONLY", as_of_date))
            continue
            
        pol = pol_map.loc[class_id]
        
        if currency not in CAP_COLS or pd.isna(pol.get(LIST_COLS[currency])):
            flags.append(build_flag(lead_code, "Pricing", "NOT_VALIDATABLE", "Medium", currency, "INR, AED, USD", 
                                    f"Policy exists but lacks pricing for {currency}.", "PRC-03", "reconciliation_orders.csv", 
                                    "currency", order["order_id"], str(class_id), "Provide localized price list.", "WARN_ONLY", as_of_date))
            continue

        std_amount = pd.to_numeric(order["standard_amount"], errors="coerce")
        discount = pd.to_numeric(order["discount_applied"], errors="coerce")
        pct_cap = pd.to_numeric(pol["max_discount_pct"], errors="coerce")
        
        if pd.isna(std_amount) or pd.isna(discount) or pd.isna(pct_cap):
            flags.append(build_flag(lead_code, "Pricing", "NOT_VALIDATABLE", "High", "Missing numeric data", "Valid numbers", 
                                    "Required financial fields or policy caps are not numeric.", "PRC-00", "reconciliation_orders.csv", 
                                    "multiple", order["order_id"], str(class_id), "Fix source data.", "REQUIRE_HUMAN_REVIEW", as_of_date))
            continue

        list_price = pd.to_numeric(pol[LIST_COLS[currency]], errors="coerce")
        price_mismatch = False
        
        if std_amount != list_price:
            price_mismatch = True
            flags.append(build_flag(lead_code, "Pricing", "PRICE_MISMATCH_SEVERE", "High", f"{currency} {std_amount}", 
                                    f"{currency} {list_price}", "Recorded standard amount deviates from official policy.", 
                                    "PRC-04", "reconciliation_orders.csv", "standard_amount", order["order_id"], str(class_id), 
                                    "Verify potential entry error; do not auto-correct.", "REQUIRE_HUMAN_REVIEW", as_of_date))
        
        if price_mismatch:
            flags.append(build_flag(lead_code, "Pricing", "NOT_VALIDATABLE", "High", "Base price unreliable", "Base price matched", 
                                    "Discount compliance cannot be unconditionally verified due to standard amount mismatch.", 
                                    "PRC-04B", "reconciliation_orders.csv", "standard_amount", order["order_id"], str(class_id), 
                                    "Resolve base price mismatch first.", "REQUIRE_HUMAN_REVIEW", as_of_date))
        else:
            abs_cap = pd.to_numeric(pol.get(CAP_COLS[currency]), errors="coerce")
            
            if pd.isna(abs_cap):
                flags.append(build_flag(lead_code, "Pricing", "NOT_VALIDATABLE", "High", "Missing absolute cap", "Valid numeric cap", 
                                        "Policy lacks a required absolute currency cap for this class.", "PRC-05A", "policy_clean.csv", 
                                        CAP_COLS[currency], order["order_id"], str(class_id), "Update policy table.", "REQUIRE_HUMAN_REVIEW", as_of_date))
            else:
                effective_cap = min((pct_cap / 100.0) * std_amount, abs_cap)
                if discount > effective_cap:
                    flags.append(build_flag(lead_code, "Pricing", "COMPLIANCE_VIOLATION", "High", discount, effective_cap, 
                                            f"Discount exceeds effective {pct_cap}% / {abs_cap} cap.", "PRC-05", "reconciliation_orders.csv", 
                                            "discount_applied", order["order_id"], str(class_id), "Block sales; require manager approval.", 
                                            "BLOCK_AUTOMATED_SALES", as_of_date))
                
        gateway_err = str(lead.get("order_gateway_error_reason", ""))
        if "%" in gateway_err and str(int(pct_cap)) not in gateway_err:
            flags.append(build_flag(lead_code, "Pricing", "POLICY_CONFLICT", "Info", gateway_err, f"{pct_cap}%", 
                                    "Gateway message cites different cap than official policy.", "PRC-06", "master_leads.csv", 
                                    "order_gateway_error_reason", order["order_id"], str(class_id), "Confirm authoritative cap text.", 
                                    "WARN_ONLY", as_of_date))
            
    return flags