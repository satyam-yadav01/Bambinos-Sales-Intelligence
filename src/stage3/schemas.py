import re
from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict, field_validator
from datetime import datetime

# --- ENUMS ---
class PurchaseReadiness(str, Enum):
    EXPLORING = "EXPLORING"
    HESITANT = "HESITANT"
    PENDING_PARTNER = "PENDING_PARTNER"
    READY_TO_PURCHASE = "READY_TO_PURCHASE"
    EXPLICITLY_DECLINED = "EXPLICITLY_DECLINED"
    NOT_EXPRESSED = "NOT_EXPRESSED"

class TranscriptCompleteness(str, Enum):
    COMPLETE = "COMPLETE"
    INCOMPLETE_MISSING_START = "INCOMPLETE_MISSING_START"
    CUT_OFF_ABRUPTLY = "CUT_OFF_ABRUPTLY"
    UNKNOWN = "UNKNOWN"

class CallbackNormalizationStatus(str, Enum):
    NOT_REQUESTED = "NOT_REQUESTED"
    PENDING_VALIDATION = "PENDING_VALIDATION"
    RESOLVED = "RESOLVED"
    AMBIGUOUS = "AMBIGUOUS"

class ObjectionCategory(str, Enum):
    PRICING_AFFORDABILITY = "PRICING_AFFORDABILITY"
    COURSE_VALUE = "COURSE_VALUE"
    TIMING_SCHEDULING = "TIMING_SCHEDULING"
    CHILD_HESITATION = "CHILD_HESITATION"
    TEACHING_QUALITY = "TEACHING_QUALITY"
    TRUST_CREDIBILITY = "TRUST_CREDIBILITY"
    COMPETITOR_COMPARISON = "COMPETITOR_COMPARISON"
    SPOUSE_FAMILY_APPROVAL = "SPOUSE_FAMILY_APPROVAL"
    OTHER = "OTHER"

class ResolutionStatus(str, Enum):
    RESOLVED = "RESOLVED"
    PARTIALLY_RESOLVED = "PARTIALLY_RESOLVED"
    UNRESOLVED = "UNRESOLVED"

class ComplianceCategory(str, Enum):
    UNAUTHORIZED_DISCOUNT = "UNAUTHORIZED_DISCOUNT"
    FAKE_GUARANTEE = "FAKE_GUARANTEE"
    HIGH_PRESSURE_THREAT = "HIGH_PRESSURE_THREAT"
    MISREPRESENTATION = "MISREPRESENTATION"
    POLICY_CONFLICT = "POLICY_CONFLICT"
    OTHER_POTENTIAL_CONCERN = "OTHER_POTENTIAL_CONCERN"

class Severity(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"

# --- EXTRACTED FACTS ---
class ChildRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid")
    learning_goals: List[str] = Field(default_factory=list)
    current_skill_level: List[str] = Field(default_factory=list)
    challenges_mentioned: List[str] = Field(default_factory=list)
    schedule_constraints: List[str] = Field(default_factory=list)
    evidence_quotes: List[str] = Field(default_factory=list)

class StatedObjection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: ObjectionCategory
    description: str
    evidence_quotes: List[str] = Field(default_factory=list)

class ConversationalCommitments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    callback_requested: bool
    original_time_expression: Optional[str] = Field(None, description="Exact conversational phrase e.g., 'tomorrow at 11 AM'")
    parent_commitments: List[str] = Field(default_factory=list)
    pending_questions: List[str] = Field(default_factory=list)
    promised_information: List[str] = Field(default_factory=list)
    evidence_quotes: List[str] = Field(default_factory=list)

class ExtractedFacts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    child_requirements: ChildRequirements
    stated_objections: List[StatedObjection] = Field(default_factory=list)
    conversational_commitments: ConversationalCommitments

# --- ANALYTICAL INTERPRETATIONS ---
class ParentIntentAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent_category: str = Field(description="General classification of intent.")
    purchase_readiness: PurchaseReadiness = Field(description="Explicit readiness based on interpretation.")
    evidence_quotes: List[str] = Field(default_factory=list)
    confidence_score_1_to_5: int = Field(ge=1, le=5)

class ObjectionResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: ObjectionCategory
    resolution_status: ResolutionStatus
    evidence_quotes: List[str] = Field(default_factory=list)
    confidence_score_1_to_5: int = Field(ge=1, le=5)

class CounsellorAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requirement_understanding_score_1_to_5: int = Field(ge=1, le=5)
    active_listening_score_1_to_5: int = Field(ge=1, le=5)
    clarity_score_1_to_5: int = Field(ge=1, le=5)
    objection_handling_score_1_to_5: int = Field(ge=1, le=5)
    communication_quality_score_1_to_5: int = Field(ge=1, le=5)
    pressure_or_aggression_detected: bool
    unsupported_promises: List[str] = Field(default_factory=list)
    evidence_quotes: List[str] = Field(default_factory=list)
    rubric_evaluation_notes: str = Field(description="Qualitative justification using observable behaviours.")

class ComplianceConcern(BaseModel):
    model_config = ConfigDict(extra="forbid")
    concern_category: ComplianceCategory
    description: str
    severity: Severity
    evidence_quotes: List[str] = Field(default_factory=list)
    requires_human_review: bool

class FollowupRecommendations(BaseModel):
    model_config = ConfigDict(extra="forbid")
    normalization_status: CallbackNormalizationStatus
    normalized_callback_datetime: Optional[str] = Field(None, description="ISO datetime if confidently resolvable. DO NOT INVENT.")
    recommended_conversational_next_step: str

    @field_validator('normalized_callback_datetime')
    @classmethod
    def validate_iso_datetime(cls, v):
        if v is not None:
            try:
                datetime.fromisoformat(v.replace("Z", "+00:00"))
            except ValueError:
                raise ValueError(f"normalized_callback_datetime must be a valid ISO 8601 format, got: {v}")
        return v

class AnalyticalInterpretations(BaseModel):
    model_config = ConfigDict(extra="forbid")
    purchase_readiness_assessment: ParentIntentAssessment
    objection_resolution_analysis: List[ObjectionResolution] = Field(default_factory=list)
    counsellor_evaluation: CounsellorAnalysis
    compliance_concerns: List[ComplianceConcern] = Field(default_factory=list)
    followup_recommendations: FollowupRecommendations

class DataQuality(BaseModel):
    model_config = ConfigDict(extra="forbid")
    transcript_completeness: TranscriptCompleteness
    missing_information: List[str] = Field(default_factory=list)
    speaker_attribution_issues: bool = Field(description="True if there are confusing or mixed up speaker tags.")

# --- ROOT SCHEMA ---
class CallIntelligenceOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lead_code: str
    transcript_id: str
    call_summary: str
    extracted_facts: ExtractedFacts
    analytical_interpretations: AnalyticalInterpretations
    data_quality: DataQuality

# --- VALIDATION ENGINE ---
def normalize_text(text: str) -> str:
    """Removes extra whitespace/punctuation but preserves exact alphanumeric characters (including Hinglish)."""
    text = re.sub(r'[^\w\s]', '', text.lower())
    return re.sub(r'\s+', ' ', text).strip()

def validate_evidence_quotes(schema_obj_dict: dict, dialogue_only_text: str) -> Dict[str, Any]:
    """Validate evidence against parser-isolated dialogue; reject raw transcript headers."""
    errors = []
    attributions = []

    # Fail closed if a caller accidentally passes the complete transcript/header.
    raw_markers = ("--- TRANSCRIPT START ---", "--- TRANSCRIPT END ---", "CALL METADATA:")
    header_patterns = (
        r"(?im)^\s*Call ID\s*:", r"(?im)^\s*Lead ID\s*:",
        r"(?im)^\s*Counsellor\s*:", r"(?im)^\s*Course Pitched\s*:",
        r"(?im)^\s*Geo\s*:", r"(?im)^\s*Parent\s*:",
        r"(?im)^\s*Student\s*:",
    )
    if any(marker in dialogue_only_text for marker in raw_markers) or any(
        re.search(pattern, dialogue_only_text) for pattern in header_patterns
    ):
        return {
            "errors": ["Evidence validation requires parsed dialogue_only text; raw transcript metadata/header was supplied."],
            "attributions": [],
            "warning": "Pass parse_transcript(raw_text).dialogue_only to validate_evidence_quotes().",
        }
    
    speaker_blocks = []
    current_speaker = "UNATTRIBUTED"
    current_text = []
    dialogue_only_lines = []
    
    for line in dialogue_only_text.split('\n'):
        line_stripped = line.strip()
        if not line_stripped:
            continue
            
        m = re.match(r'^\[\d+:\d+\]\s+([A-Z\s]+\(.*?\)):\s*(.*)', line_stripped)
        if m:
            if current_text:
                speaker_blocks.append({
                    "speaker": current_speaker,
                    "norm_text": normalize_text(" ".join(current_text))
                })
            current_speaker = m.group(1).strip()
            current_text = [m.group(2).strip()]
            dialogue_only_lines.append(m.group(2).strip())
        else:
            current_text.append(line_stripped)
            dialogue_only_lines.append(line_stripped)
            
    if current_text:
        speaker_blocks.append({
            "speaker": current_speaker,
            "norm_text": normalize_text(" ".join(current_text))
        })
        
    norm_dialogue_only = normalize_text(" ".join(dialogue_only_lines))
    
    def extract_quotes(obj, path="root"):
        if isinstance(obj, dict):
            for key, value in obj.items():
                current_path = f"{path}.{key}"
                if key == "evidence_quotes" and isinstance(value, list):
                    for idx, q in enumerate(value):
                        q_path = f"{current_path}[{idx}]"
                        q_str = str(q)
                        if not q_str.strip():
                            errors.append(f"Field {q_path}: Empty quotation provided.")
                            continue
                        
                        norm_q = normalize_text(q_str)
                        if not norm_q:
                            errors.append(f"Field {q_path}: Quotation contains no valid text characters.")
                            continue
                            
                        # Quote must exist in Dialogue-Only text first
                        if norm_q not in norm_dialogue_only:
                            errors.append(f"Field {q_path}: Quote hallucinated or heavily modified: '{q_str}'")
                        else:
                            matched_speakers = set()
                            for block in speaker_blocks:
                                if norm_q in block["norm_text"]:
                                    if block["speaker"] != "UNATTRIBUTED":
                                        matched_speakers.add(block["speaker"])
                                    
                            status = ""
                            speakers_list = []
                            if len(matched_speakers) == 1:
                                status = "SINGLE"
                                speakers_list = list(matched_speakers)
                            elif len(matched_speakers) > 1:
                                status = "AMBIGUOUS"
                                speakers_list = sorted(list(matched_speakers))
                            else:
                                status = "UNATTRIBUTED"
                                
                            attributions.append({
                                "field_path": q_path,
                                "quote": q_str,
                                "status": status,
                                "speakers": speakers_list
                            })
                            
                elif isinstance(value, (list, tuple, dict)):
                    extract_quotes(value, current_path)
        elif isinstance(obj, (list, tuple)):
            for idx, item in enumerate(obj):
                extract_quotes(item, f"{path}[{idx}]")
                
    extract_quotes(schema_obj_dict)
    
    return {
        "errors": errors,
        "attributions": attributions,
        "warning": "NOTE: Textual substring matching verifies the quote exists, but does not establish semantic correctness or proper context."
    }