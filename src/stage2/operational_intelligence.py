import pandas as pd
from .flag_builder import build_flag

TZ_MAP = {
    "IST": "Asia/Kolkata",
    "GST": "Asia/Dubai",
    "PST": "America/Los_Angeles",
    "CST": "America/Chicago",
    "GMT": "Europe/London",
    "AST": "Asia/Qatar"
}

def _safe_utc(ts, mapped_tz):
    if pd.isna(ts): return None
    if ts.tzinfo is None:
        return ts.tz_localize(mapped_tz).tz_convert("UTC")
    return ts.tz_convert("UTC")

def parse_timestamp(raw_val):
    """Returns (is_missing, is_invalid, parsed_datetime)"""
    if pd.isna(raw_val):
        return True, False, None
    val_str = str(raw_val).strip()
    if val_str in ["", "NaT", "NULL", "nan", "None", "<NA>"]:
        return True, False, None
    dt = pd.to_datetime(raw_val, errors="coerce")
    if pd.isna(dt):
        return False, True, None
    return False, False, dt

def evaluate_operations(master: pd.DataFrame, as_of_date: str = "2026-11-06") -> list[dict]:
    flags = []
    
    for _, lead in master.iterrows():
        lead_code = lead["lead_code"]
        
        # 1. Identity Overlap
        if str(lead.get("identity_relationship")) == "SAME_CUSTOMER_PROPOSED":
            related = str(lead.get("identity_related_lead_codes", ""))
            flags.append(build_flag(lead_code, "Operations", "SAME_CUSTOMER_PROPOSED", "High", related, "NONE", 
                                    "Lead shares identity with another record.", "OPS-01", "lead_canonical_map.csv", 
                                    "identity_relationship", "N/A", "N/A", "Review identity overlap; pause duplicate outreach.", 
                                    "REQUIRE_HUMAN_REVIEW", as_of_date))
            
        # 2. Demo Escalation / Academic Review
        demo_score = pd.to_numeric(lead.get("demo_child_engagement_score_1_to_5"), errors="coerce")
        batch_type = str(lead.get("demo_recommended_batch_type", ""))
        
        requires_academic = False
        if pd.notna(demo_score) and demo_score <= 2:
            requires_academic = True
        if "Micro_Batch_3_Kids_Or_1on1_Bridge" in batch_type:
            requires_academic = True
            
        if requires_academic:
            flags.append(build_flag(lead_code, "Operations", "REQUIRES_ACADEMIC_REVIEW", "Medium", f"Score: {demo_score}, Batch: {batch_type}", 
                                    "Score > 2 or standard batch", "Demo engagement low or specific bridging recommended.", 
                                    "OPS-02", "master_leads.csv", "demo_child_engagement_score_1_to_5", lead.get("demo_demo_id"), "N/A", 
                                    "Route to academic review; suppress standard sales push.", "REQUIRE_ACADEMIC_REVIEW", as_of_date))

        # 3. Missing / Invalid Call Evidence
        missing_last, invalid_last, last_call_at = parse_timestamp(lead.get("last_call_at"))
        missing_log, invalid_log, call_log_started_at = parse_timestamp(lead.get("call_call_started_at"))
        missing_demo, invalid_demo, demo_completed_at = parse_timestamp(lead.get("demo_demo_completed_at"))
        
        has_call_log = str(lead.get("has_call_log", "")).lower() == "true"
        has_demo = str(lead.get("has_demo", "")).lower() == "true"
        
        if invalid_last:
            flags.append(build_flag(lead_code, "Operations", "DATA_QUALITY_ERROR", "High", str(lead.get("last_call_at")), "Valid Timestamp", 
                                    "CRM last call timestamp could not be parsed.", "OPS-ERR-LAST", "master_leads.csv", 
                                    "last_call_at", "N/A", "N/A", "Verify timestamp integrity.", "REQUIRE_HUMAN_REVIEW", as_of_date))
        if invalid_log:
            flags.append(build_flag(lead_code, "Operations", "DATA_QUALITY_ERROR", "High", str(lead.get("call_call_started_at")), "Valid Timestamp", 
                                    "Call log timestamp could not be parsed.", "OPS-ERR-LOG", "master_leads.csv", 
                                    "call_call_started_at", "N/A", "N/A", "Verify timestamp integrity.", "REQUIRE_HUMAN_REVIEW", as_of_date))
        
        # Valid or invalid, if it's not genuinely missing, it counts as an indication.
        if not missing_last and not has_call_log:
            flags.append(build_flag(lead_code, "Operations", "CRM_CALL_INDICATED_BUT_NO_LOG", "Medium", "CRM Call Present, No Log", "Call Log Expected", 
                                    "CRM indicates a call occurred, but no log exists.", "OPS-03", "master_leads.csv", 
                                    "last_call_at", "N/A", "N/A", "Verify contact history before automated callback.", "WARN_ONLY", as_of_date))
        elif missing_last and not has_call_log:
            flags.append(build_flag(lead_code, "Operations", "NO_CALL_INDICATION_OR_LOG", "Medium", "No CRM Call, No Log", "Call Record Expected", 
                                    "No evidence of parent contact exists.", "OPS-04", "master_leads.csv", 
                                    "last_call_at", "N/A", "N/A", "Verify contact history before automated callback.", "REQUIRE_HUMAN_REVIEW", as_of_date))
            
        # 4. Safe Post-Demo evidence evaluation
        if has_demo:
            if invalid_demo:
                flags.append(build_flag(lead_code, "Operations", "DATA_QUALITY_ERROR", "High", str(lead.get("demo_demo_completed_at")), "Valid Timestamp", 
                                        "Demo timestamp could not be parsed.", "OPS-ERR-DEMO", "master_leads.csv", 
                                        "demo_demo_completed_at", str(lead.get("demo_demo_id")), "N/A", "Verify demo timestamp.", 
                                        "REQUIRE_HUMAN_REVIEW", as_of_date))
            elif missing_demo:
                flags.append(build_flag(lead_code, "Operations", "DATA_QUALITY_ERROR", "High", "Missing Demo Timestamp", "Valid Timestamp", 
                                        "Demo indicated but timestamp genuinely missing. Cannot validate chronological post-demo call.", "OPS-05-ERR", "master_leads.csv", 
                                        "demo_demo_completed_at", str(lead.get("demo_demo_id")), "N/A", "Verify demo timestamp.", 
                                        "REQUIRE_HUMAN_REVIEW", as_of_date))
            else:
                tz_label = str(lead.get("timezone_label", "")).strip()
                mapped_tz = TZ_MAP.get(tz_label)
                
                if not mapped_tz:
                     flags.append(build_flag(lead_code, "Operations", "DATA_QUALITY_ERROR", "High", "Missing TZ", "Valid TZ", 
                                        "Cannot safely compare demo and call timestamps without a timezone mapping.", "OPS-05-ERR2", "master_leads.csv", 
                                        "timezone_label", "N/A", "N/A", "Provide timezone for demo chronological check.", 
                                        "REQUIRE_HUMAN_REVIEW", as_of_date))
                elif invalid_last or invalid_log:
                    # An invalid timestamp prevents definitive evaluation of 'no post demo call'.
                    # DQ flags are already emitted above. We safely skip the NO_CALL_LOG_AFTER_DEMO check.
                    pass
                else:
                    has_post_demo_call = False
                    try:
                        demo_utc = _safe_utc(demo_completed_at, mapped_tz)
                        
                        if not missing_last:
                            last_utc = _safe_utc(last_call_at, mapped_tz)
                            if last_utc > demo_utc:
                                has_post_demo_call = True
                                
                        if not missing_log:
                            log_utc = _safe_utc(call_log_started_at, mapped_tz)
                            if log_utc > demo_utc:
                                has_post_demo_call = True
                                
                        if not has_post_demo_call:
                            obs_val = "Call(s) pre-date demo" if (not missing_last or not missing_log) else "No Calls"
                            flags.append(build_flag(lead_code, "Operations", "NO_CALL_LOG_AFTER_DEMO", "High", obs_val, "Post-Demo Call Expected", 
                                                    "Demo was completed but no strictly subsequent call evidence exists.", "OPS-05", "master_leads.csv", 
                                                    "demo_demo_completed_at", str(lead.get("demo_demo_id")), "N/A", "Urgent contact history verification required.", 
                                                    "REQUIRE_HUMAN_REVIEW", as_of_date))
                    except Exception as e:
                        flags.append(build_flag(lead_code, "Operations", "DATA_QUALITY_ERROR", "High", "Comparison Failed", "Valid Timestamps", 
                                                f"Chronological comparison failed: {str(e)}", "OPS-ERR3", "master_leads.csv", 
                                                "multiple", "N/A", "N/A", "Verify timestamp integrity.", "REQUIRE_HUMAN_REVIEW", as_of_date))
                
    return flags