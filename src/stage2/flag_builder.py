import pandas as pd
from datetime import datetime

def build_flag(lead_code: str, module: str, flag_id: str, severity: str, 
               observed: str, expected: str, explanation: str, 
               rule_id: str, src_file: str, src_field: str, 
               src_record_ref: str, policy_ref: str, 
               action: str, disposition: str, as_of_date: str) -> dict:
    return {
        "lead_code": lead_code,
        "module": module,
        "flag_identifier": flag_id,
        "severity": severity,
        "observed_value": str(observed) if pd.notna(observed) else "NULL",
        "expected_value": str(expected) if pd.notna(expected) else "NULL",
        "explanation": explanation,
        "evidence_rule_id": rule_id,
        "source_file": src_file,
        "source_field": src_field,
        "source_record_ref": str(src_record_ref) if pd.notna(src_record_ref) else "N/A",
        "policy_ref": str(policy_ref) if pd.notna(policy_ref) else "N/A",
        "recommended_action": action,
        "automation_disposition": disposition,
        "evaluated_as_of_date": as_of_date
    }