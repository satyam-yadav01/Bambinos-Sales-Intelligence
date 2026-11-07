from stage3.transcript_parser import parse_transcript, TranscriptParserError
from stage3.schemas import CallIntelligenceOutput, validate_evidence_quotes
from pydantic import ValidationError

def run_tests():
    print("--- Milestone 3.1 Final Tests Execution ---\n")
    passed = 0
    total = 26

    def assert_test(condition, name):
        nonlocal passed
        if condition:
            passed += 1
            print(f"✅ {name}")
        else:
            print(f"❌ {name}")

    # [PART 1: Parser & Metadata Format Variation Tests]
    valid_text = "Call ID: 123 | Lead ID: LEAD-001 \nGeo: (USA - PST)\nCall took place at 09:45 AM PST\n--- TRANSCRIPT START ---\n[00:10] REP: Hi\n--- TRANSCRIPT END ---"
    res1 = parse_transcript(valid_text)
    assert_test(res1.call_started_at == "09:45 AM PST" and res1.timezone == "PST", "Test 1: Valid transcript metadata extraction")

    try:
        parse_transcript("Call ID: 123 | Lead ID: LEAD-001")
        assert_test(False, "Test 2: Missing transcript markers")
    except TranscriptParserError:
        assert_test(True, "Test 2: Missing transcript markers")

    try:
        parse_transcript("Call ID: 123\n--- TRANSCRIPT START ---\nHi\n--- TRANSCRIPT END ---")
        assert_test(False, "Test 3: Missing lead ID")
    except TranscriptParserError:
        assert_test(True, "Test 3: Missing lead ID")

    res2 = parse_transcript("Call ID: 123 | Lead ID: LEAD-001\n--- TRANSCRIPT START ---\nHi\n--- TRANSCRIPT END ---")
    assert_test(res2.call_started_at is None, "Test 4: Missing call timestamp (gracefully handled)")

    res3 = parse_transcript("Lead ID: LEAD-001\n--- TRANSCRIPT START ---\nHi\n--- TRANSCRIPT END ---")
    assert_test(res3.counsellor_id is None, "Test 5: Missing metadata fields gracefully handled")

    res4 = parse_transcript("Geo: (USA-PST) | Lead ID:LEAD-001\n--- TRANSCRIPT START ---\nHi\n--- TRANSCRIPT END ---")
    assert_test(res4.timezone == "PST" and res4.lead_code == "LEAD-001", "Test 6: Different metadata formatting supported")

    # [PART 2: Strict Pydantic Field & Enum Validations]
    valid_schema = {
        "lead_code": "LEAD-001", "transcript_id": "123", "call_summary": "Sum",
        "extracted_facts": {
            "child_requirements": {},
            "stated_objections": [],
            "conversational_commitments": {"callback_requested": False}
        },
        "analytical_interpretations": {
            "purchase_readiness_assessment": {"intent_category": "Cat", "purchase_readiness": "EXPLORING", "evidence_quotes": [], "confidence_score_1_to_5": 5},
            "counsellor_evaluation": {
                "requirement_understanding_score_1_to_5": 5, "active_listening_score_1_to_5": 5, "clarity_score_1_to_5": 5,
                "objection_handling_score_1_to_5": 5, "communication_quality_score_1_to_5": 5, "pressure_or_aggression_detected": False,
                "rubric_evaluation_notes": "Good"
            },
            "followup_recommendations": {
                "normalization_status": "NOT_REQUESTED", "recommended_conversational_next_step": "N/A"
            }
        },
        "data_quality": {"transcript_completeness": "COMPLETE", "speaker_attribution_issues": False}
    }

    try:
        CallIntelligenceOutput(**{**valid_schema, "fake_field": "bad"})
        assert_test(False, "Test 7: Unexpected Pydantic field rejection (extra='forbid')")
    except ValidationError:
        assert_test(True, "Test 7: Unexpected Pydantic field rejection (extra='forbid')")

    try:
        invalid_intent = {**valid_schema["analytical_interpretations"]["purchase_readiness_assessment"], "purchase_readiness": "INVALID_STATE"}
        invalid_schema = {**valid_schema, "analytical_interpretations": {**valid_schema["analytical_interpretations"], "purchase_readiness_assessment": invalid_intent}}
        CallIntelligenceOutput(**invalid_schema)
        assert_test(False, "Test 8: Invalid Enum rejection")
    except ValidationError:
        assert_test(True, "Test 8: Invalid Enum rejection")

    try:
        invalid_intent = {**valid_schema["analytical_interpretations"]["purchase_readiness_assessment"], "confidence_score_1_to_5": 6}
        invalid_schema = {**valid_schema, "analytical_interpretations": {**valid_schema["analytical_interpretations"], "purchase_readiness_assessment": invalid_intent}}
        CallIntelligenceOutput(**invalid_schema)
        assert_test(False, "Test 9: Scores below 1 and above 5 (Upper bound)")
    except ValidationError:
        assert_test(True, "Test 9: Scores below 1 and above 5")

    try:
        invalid_followup = {**valid_schema["analytical_interpretations"]["followup_recommendations"], "normalized_callback_datetime": "Tomorrow Afternoon"}
        invalid_schema = {**valid_schema, "analytical_interpretations": {**valid_schema["analytical_interpretations"], "followup_recommendations": invalid_followup}}
        CallIntelligenceOutput(**invalid_schema)
        assert_test(False, "Test 10: Malformed callback datetime")
    except ValidationError:
        assert_test(True, "Test 10: Malformed callback datetime")

    try:
        valid_followup = {**valid_schema["analytical_interpretations"]["followup_recommendations"], "normalized_callback_datetime": "2026-11-03T11:00:00Z"}
        valid_schema_iso = {**valid_schema, "analytical_interpretations": {**valid_schema["analytical_interpretations"], "followup_recommendations": valid_followup}}
        CallIntelligenceOutput(**valid_schema_iso)
        assert_test(True, "Test 11: Valid callback normalization metadata (ISO 8601)")
    except ValidationError:
        assert_test(False, "Test 11: Valid callback normalization metadata (ISO 8601)")


    # [PART 3: Quote Anti-Hallucination & Multi-line Attribution Logic]
    mock_transcript = """
    System note before any tags.
    [00:01] REP (Alice): Hello.
    Welcome to the call.
    This sentence spans
    [00:10] PARENT (Bob): across two lines.
    Bob continuation line.
    [00:15] REP (Alice): I understand.
    [00:20] PARENT (Bob): i understand...
    kya haal hai
    """

    def check_quote(quote, expected_status, expected_speaker=None):
        res = validate_evidence_quotes({"evidence_quotes": [quote]}, mock_transcript)
        if res["errors"]: return False
        attr = res["attributions"][0]
        if attr["status"] != expected_status: return False
        if expected_speaker and expected_speaker not in attr["speakers"]: return False
        return True

    val_empty = validate_evidence_quotes({"evidence_quotes": ["  "]}, mock_transcript)
    assert_test(any("Empty quotation" in e for e in val_empty["errors"]), "Test 12: Empty evidence quote rejection")

    val_hall = validate_evidence_quotes({"evidence_quotes": ["Fake hallucination"]}, mock_transcript)
    assert_test(any("Quote hallucinated" in e for e in val_hall["errors"]), "Test 13: Genuinely hallucinated quotation")
    
    assert_test(check_quote("Hello.", "SINGLE", "REP (Alice)"), "Test 14: Quotation entirely on a timestamped line")
    assert_test(check_quote("Welcome to the call.", "SINGLE", "REP (Alice)"), "Test 15: Quotation on a continuation line without a tag")
    assert_test(check_quote("This sentence spans", "SINGLE", "REP (Alice)"), "Test 16: Quotation spanning multiple lines in utterance")
    assert_test(check_quote("Bob continuation line.", "SINGLE", "PARENT (Bob)"), "Test 17: Speaker change followed by another continuation")
    
    assert_test(check_quote("I understand.", "AMBIGUOUS"), "Test 18: Identical sentences spoken by two different speakers")
    assert_test(check_quote("i understand...", "AMBIGUOUS"), "Test 19: Normalization-equivalent sentences by two different speakers")
    
    val_cross = validate_evidence_quotes({"evidence_quotes": ["This sentence spans across two lines."]}, mock_transcript)
    assert_test(not val_cross["errors"] and val_cross["attributions"][0]["status"] == "UNATTRIBUTED", "Test 20: Quotation spanning two different speaker turns")
    
    assert_test(check_quote("System note before any tags.", "UNATTRIBUTED"), "Test 21: Quotation exists in transcript but no identifiable speaker")
    assert_test(check_quote("kya haal hai?", "SINGLE", "PARENT (Bob)"), "Test 22: Hinglish quotation matching with punctuation differences")

    # [PART 4: Metadata Exclusion Test]
    full_text = "CALL METADATA:\nCall ID: 7001 | Lead ID: LEAD-7001\n--- TRANSCRIPT START ---\n[00:10] REP: Hi\n--- TRANSCRIPT END ---"
    parsed_full = parse_transcript(full_text)
    # Validate quote against parsed dialog, NOT raw transcript
    val_meta = validate_evidence_quotes({"evidence_quotes": ["Call ID: 7001"]}, parsed_full.dialogue_only)
    assert_test(any("Quote hallucinated" in e for e in val_meta["errors"]), "Test 23: Metadata string correctly rejected as evidence quote")

    raw_input_guard = validate_evidence_quotes({"evidence_quotes": ["Call ID: 7001"]}, full_text)
    assert_test(bool(raw_input_guard["errors"]) and not raw_input_guard["attributions"], "Test 24: Complete raw transcript rejected by evidence validator")

    # [PART 5: Real Transcripts Test]
    t1 = """CALL METADATA:
Call ID: 7001 | Lead ID: LEAD-801 | Student: Aa***v Na***r (8 yrs, Grade 3)
Parent: Di***a Na***r (Mother) | Geo: India (Bengaluru - IST)
Course Pitched: Young Communicators (Public Speaking - 48 Sessions)
Counsellor: Rohan S*** (ID: 204) | Duration: 14m 20s | Rep Talk Ratio: 46%
--- TRANSCRIPT START ---
[00:24] PARENT (Divya): Yes! Honestly I was sitting right behind the laptop and I was surprised.
--- TRANSCRIPT END ---"""
    parsed_t1 = parse_transcript(t1)
    assert_test(parsed_t1.lead_code == "LEAD-801", "Test 25: Call 1 Metadata Extracted")
    
    # We validate strictly against `parsed.dialogue_only` so the test mimics production usage
    val_t1 = validate_evidence_quotes({"evidence_quotes": ["sitting right behind the laptop"]}, parsed_t1.dialogue_only)
    assert_test(val_t1["attributions"][0]["status"] == "SINGLE" and "PARENT (Divya)" in val_t1["attributions"][0]["speakers"], "Test 26: Call 1 Quote Attributed via dialogue_only validation")

    print(f"\nTotal Pass/Fail: {passed}/{total}")

if __name__ == "__main__":
    run_tests()