import re
from typing import Optional, Dict
from pydantic import BaseModel

class TranscriptParserError(Exception):
    pass

class ParsedTranscript(BaseModel):
    call_id: Optional[str]
    lead_code: str
    counsellor_id: Optional[str]
    timezone: Optional[str]
    call_started_at: Optional[str]
    other_metadata: Dict[str, str]
    dialogue_only: str
    raw_text: str

def parse_transcript(text: str) -> ParsedTranscript:
    """Deterministically extracts metadata and isolates pure conversation, raising strict errors on invalid data."""
    if "--- TRANSCRIPT START ---" not in text or "--- TRANSCRIPT END ---" not in text:
        raise TranscriptParserError("Transcript start/end markers are missing or malformed.")
    
    parts = re.split(r'---\s*TRANSCRIPT START\s*---', text)
    if len(parts) != 2:
        raise TranscriptParserError("Ambiguous or multiple transcript start markers.")
    
    metadata_part = parts[0].strip()
    dialogue_part = re.split(r'---\s*TRANSCRIPT END\s*---', parts[1])[0].strip()
    
    if not dialogue_part:
        raise TranscriptParserError("Parsed dialogue is empty.")
    
    call_id_match = re.search(r'Call ID:\s*(\d+)', metadata_part, re.IGNORECASE)
    lead_code_match = re.search(r'Lead ID:\s*(LEAD-\d+)', metadata_part, re.IGNORECASE)
    if not lead_code_match:
        raise TranscriptParserError("Lead ID mapping is missing or ambiguous.")
        
    counsellor_id_match = re.search(r'Counsellor:.*?\(ID:\s*(\d+)\)', metadata_part, re.IGNORECASE)
    tz_match = re.search(r'Geo:.*?\b([A-Z]{3,4})\)', metadata_part, re.IGNORECASE)
    
    call_started_at = None
    call_started_match = re.search(r'Call took place at\s*([0-9:\sAPM]+[A-Z]{0,4})', metadata_part, re.IGNORECASE)
    if call_started_match:
        call_started_at = call_started_match.group(1).strip()
    
    metadata = {
        "call_id": call_id_match.group(1) if call_id_match else None,
        "lead_code": lead_code_match.group(1),
        "counsellor_id": counsellor_id_match.group(1) if counsellor_id_match else None,
        "timezone": tz_match.group(1) if tz_match else None,
        "call_started_at": call_started_at,
        "other_metadata": {"raw_header": metadata_part},
        "dialogue_only": dialogue_part,
        "raw_text": text
    }
    
    return ParsedTranscript(**metadata)