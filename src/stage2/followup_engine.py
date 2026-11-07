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

def evaluate_followups(master: pd.DataFrame, as_of_date: str = None) -> list[dict]:
    flags = []
    
    if not as_of_date:
        run_date = pd.Timestamp.now(tz="Asia/Kolkata").date()
        as_of_date_str = run_date.isoformat()
    else:
        run_date = pd.Timestamp(as_of_date).date()
        as_of_date_str = as_of_date
    
    for _, lead in master.iterrows():
        lead_code = lead["lead_code"]
        
        tz_label = str(lead.get("timezone_label", "")).strip()
        mapped_tz = TZ_MAP.get(tz_label)
        
        # Independent Timezone Validation
        if not mapped_tz:
            flags.append(build_flag(lead_code, "Followup", "TIMEZONE_UNKNOWN", "Medium", 
                                    tz_label if tz_label and tz_label != "nan" else "Missing", 
                                    "Mapped IANA TZ", "Timezone label could not be mapped to IANA database.", 
                                    "FOL-03", "master_leads.csv", "timezone_label", "N/A", "N/A", 
                                    "Fix CRM timezone mapping.", "REQUIRE_HUMAN_REVIEW", as_of_date_str))

        last_call_raw = lead.get("last_call_at")
        next_followup_raw = lead.get("next_followup_at")
        
        missing_last, invalid_last, last_call_at = parse_timestamp(last_call_raw)
        missing_next, invalid_next, next_followup_at = parse_timestamp(next_followup_raw)
        
        # Last Call DQ check
        if invalid_last:
            flags.append(build_flag(lead_code, "Followup", "DATA_QUALITY_ERROR", "High", str(last_call_raw), "Valid Timestamp", 
                                    "Last call timestamp could not be parsed.", "FOL-ERR3", "master_leads.csv", 
                                    "last_call_at", "N/A", "N/A", "Fix source timestamp format.", "REQUIRE_HUMAN_REVIEW", as_of_date_str))

        # Next Follow-up DQ / Missing check
        if missing_next:
            flags.append(build_flag(lead_code, "Followup", "NO_FOLLOWUP_SCHEDULED", "Medium", "NULL", "Valid Date", 
                                    "No follow-up date scheduled for this lead.", "FOL-01", "master_leads.csv", 
                                    "next_followup_at", "N/A", "N/A", "Schedule follow-up date (if unrestricted).", "NO_BLOCK", as_of_date_str))
            continue
            
        if invalid_next:
            flags.append(build_flag(lead_code, "Followup", "DATA_QUALITY_ERROR", "High", str(next_followup_raw), "Valid Timestamp", 
                                    "Follow-up timestamp could not be parsed.", "FOL-ERR", "master_leads.csv", 
                                    "next_followup_at", "N/A", "N/A", "Fix source timestamp format.", "REQUIRE_HUMAN_REVIEW", as_of_date_str))
            continue

        # Safe Stale Follow-up Check
        if not missing_last and not invalid_last:
            if not mapped_tz:
                flags.append(build_flag(lead_code, "Followup", "DATA_QUALITY_ERROR", "High", "Missing TZ", "Valid TZ", 
                                        "Cannot safely compare stale timestamps without a timezone mapping.", "FOL-02-ERR", "master_leads.csv", 
                                        "timezone_label", "N/A", "N/A", "Provide timezone to check stale dates.", "REQUIRE_HUMAN_REVIEW", as_of_date_str))
            else:
                try:
                    next_utc = _safe_utc(next_followup_at, mapped_tz)
                    last_utc = _safe_utc(last_call_at, mapped_tz)
                    if next_utc < last_utc:
                        flags.append(build_flag(lead_code, "Followup", "STALE_FOLLOWUP_DATE", "Medium", next_utc.isoformat(), 
                                                f"> {last_utc.isoformat()}", "Next follow-up date is earlier than the last recorded call.", 
                                                "FOL-02", "master_leads.csv", "next_followup_at", "N/A", "N/A", 
                                                "Reschedule follow-up (if unrestricted).", "WARN_ONLY", as_of_date_str))
                except Exception as e:
                    flags.append(build_flag(lead_code, "Followup", "DATA_QUALITY_ERROR", "High", "Comparison Failed", "Valid Timestamps", 
                                            f"Chronological comparison failed: {str(e)}", "FOL-02-ERR2", "master_leads.csv", 
                                            "multiple", "N/A", "N/A", "Verify timestamp/timezone integrity.", "REQUIRE_HUMAN_REVIEW", as_of_date_str))
            
        # Overdue Calculation
        if not mapped_tz:
            continue
            
        try:
            if next_followup_at.tzinfo is None:
                localized_followup = next_followup_at.tz_localize(mapped_tz)
            else:
                localized_followup = next_followup_at.tz_convert(mapped_tz)
                
            followup_date = localized_followup.date()
            
            if followup_date < run_date:
                flags.append(build_flag(lead_code, "Followup", "OVERDUE", "High", followup_date.isoformat(), 
                                        f">= {run_date.isoformat()}", "Follow-up date is in the past.", "FOL-04", 
                                        "master_leads.csv", "next_followup_at", "N/A", "N/A", 
                                        "Time-due for standard follow-up (subject to restrictions).", "NO_BLOCK", as_of_date_str))
            elif followup_date == run_date:
                flags.append(build_flag(lead_code, "Followup", "DUE_TODAY", "Medium", followup_date.isoformat(), 
                                        f"== {run_date.isoformat()}", "Follow-up is due today in lead's local time.", "FOL-05", 
                                        "master_leads.csv", "next_followup_at", "N/A", "N/A", 
                                        "Time-due for standard follow-up (subject to restrictions).", "NO_BLOCK", as_of_date_str))
            else:
                flags.append(build_flag(lead_code, "Followup", "FUTURE", "Info", followup_date.isoformat(), 
                                        f"> {run_date.isoformat()}", "Follow-up is scheduled in the future.", "FOL-06", 
                                        "master_leads.csv", "next_followup_at", "N/A", "N/A", 
                                        "No immediate date-based action.", "NO_BLOCK", as_of_date_str))
        except Exception as e:
            flags.append(build_flag(lead_code, "Followup", "DATA_QUALITY_ERROR", "High", "Timezone conversion failed", "Valid Timezone", 
                                    f"Failed to localize timestamp: {str(e)}", "FOL-ERR2", "master_leads.csv", 
                                    "next_followup_at", "N/A", "N/A", "Verify timestamp/timezone integrity.", "REQUIRE_HUMAN_REVIEW", as_of_date_str))
            
    return flags