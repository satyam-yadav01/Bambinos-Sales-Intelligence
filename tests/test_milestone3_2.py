from __future__ import annotations
import json, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from pydantic import ValidationError
from stage3.schemas import CallIntelligenceOutput
from stage3.extraction_prompt import SYSTEM_PROMPT, build_user_prompt
from stage3.llm_client import LLMClient, LLMClientError
from stage3.extraction_pipeline import process_transcript, process_all_transcripts, save_results


def valid_payload(lead="LEAD-001", call="123", quote="Hello there"):
    return {
      "lead_code": lead, "transcript_id": call, "call_summary": "A parent discussed the course.",
      "extracted_facts": {
        "child_requirements": {"learning_goals": [], "current_skill_level": [], "challenges_mentioned": [], "schedule_constraints": [], "evidence_quotes": [quote]},
        "stated_objections": [],
        "conversational_commitments": {"callback_requested": False, "original_time_expression": None, "parent_commitments": [], "pending_questions": [], "promised_information": [], "evidence_quotes": []}
      },
      "analytical_interpretations": {
        "purchase_readiness_assessment": {"intent_category": "No explicit intent", "purchase_readiness": "NOT_EXPRESSED", "evidence_quotes": [], "confidence_score_1_to_5": 2},
        "objection_resolution_analysis": [],
        "counsellor_evaluation": {"requirement_understanding_score_1_to_5": 3, "active_listening_score_1_to_5": 3, "clarity_score_1_to_5": 3, "objection_handling_score_1_to_5": 3, "communication_quality_score_1_to_5": 3, "pressure_or_aggression_detected": False, "unsupported_promises": [], "evidence_quotes": [], "rubric_evaluation_notes": "Insufficient evidence for a stronger rating."},
        "compliance_concerns": [],
        "followup_recommendations": {"normalization_status": "NOT_REQUESTED", "normalized_callback_datetime": None, "recommended_conversational_next_step": "No specific follow-up stated."}
      },
      "data_quality": {"transcript_completeness": "UNKNOWN", "missing_information": [], "speaker_attribution_issues": False}
    }

TRANSCRIPT = """CALL METADATA:\nCall ID: 123 | Lead ID: LEAD-001\nCounsellor: Test (ID: 22) | Geo: India (IST)\n--- TRANSCRIPT START ---\n[00:01] REP (Test): Hello there\n[00:03] PARENT (Parent): I would like information.\n--- TRANSCRIPT END ---"""

class FakeCompletions:
    def __init__(self, parsed=None, error=None): self.parsed, self.error, self.calls = parsed, error, []
    def parse(self, **kwargs):
        self.calls.append(kwargs)
        if self.error: raise self.error
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(parsed=self.parsed, refusal=None))])

class FakeProvider:
    def __init__(self, completions): self.beta = SimpleNamespace(chat=SimpleNamespace(completions=completions))

class Milestone32Tests(unittest.TestCase):
    def setUp(self):
        self.client = LLMClient(api_key="test", client=FakeProvider(FakeCompletions()), max_retries=0)
        self.output = CallIntelligenceOutput.model_validate(valid_payload())

    def test_prompt_contains_key_safeguards(self):
        for phrase in ("NOT_EXPRESSED", "DO NOT calculate", "Stage 2", "RESOLVED", "Hinglish"):
            self.assertIn(phrase, SYSTEM_PROMPT)

    def test_prompt_separates_metadata_and_dialogue(self):
        prompt = build_user_prompt("[00:01] REP: Hello", {"lead_code":"LEAD-001", "raw_header":"SECRET"})
        self.assertIn("PARSER METADATA", prompt); self.assertIn("DIALOGUE ONLY", prompt)
        self.assertNotIn("SECRET", prompt)

    def test_pipeline_success_when_valid(self):
        r = process_transcript(TRANSCRIPT, self.client, self.output)
        self.assertEqual(r["status"], "success"); self.assertTrue(r["validation_passed"])

    def test_llm_does_not_receive_raw_metadata_header(self):
        capture = {}
        class Capturing:
            def extract_intelligence(self, system_prompt, user_prompt, mock_response=None):
                capture["prompt"] = user_prompt; return self.output
        # Bind output without relying on provider.
        cap = Capturing(); cap.output = self.output
        process_transcript(TRANSCRIPT, cap)
        self.assertNotIn("CALL METADATA:", capture["prompt"])
        self.assertIn("DIALOGUE ONLY", capture["prompt"])

    def test_metadata_is_separate(self):
        r = process_transcript(TRANSCRIPT, self.client, self.output)
        self.assertEqual(r["metadata"]["lead_code"], "LEAD-001")
        self.assertEqual(r["metadata"]["call_id"], "123")

    def test_metadata_quote_fails_validation(self):
        payload = valid_payload(quote="Call ID: 123")
        r = process_transcript(TRANSCRIPT, self.client, CallIntelligenceOutput.model_validate(payload))
        self.assertEqual(r["status"], "validation_failed")
        self.assertTrue(r["evidence_validation"]["errors"])

    def test_hallucinated_quote_fails_validation(self):
        payload = valid_payload(quote="This never happened")
        r = process_transcript(TRANSCRIPT, self.client, CallIntelligenceOutput.model_validate(payload))
        self.assertEqual(r["status"], "validation_failed")

    def test_wrong_lead_id_fails_closed(self):
        output = CallIntelligenceOutput.model_validate(valid_payload(lead="LEAD-999"))
        r = process_transcript(TRANSCRIPT, self.client, output)
        self.assertEqual(r["status"], "validation_failed")
        self.assertFalse(r["identity_validation"]["passed"])

    def test_wrong_call_id_fails_closed(self):
        output = CallIntelligenceOutput.model_validate(valid_payload(call="999"))
        r = process_transcript(TRANSCRIPT, self.client, output)
        self.assertEqual(r["status"], "validation_failed")

    def test_invalid_schema_rejected(self):
        p = valid_payload(); p["unexpected"] = "no"
        with self.assertRaises(ValidationError): CallIntelligenceOutput.model_validate(p)

    def test_invalid_enum_rejected(self):
        p = valid_payload(); p["analytical_interpretations"]["purchase_readiness_assessment"]["purchase_readiness"] = "BUY_NOW"
        with self.assertRaises(ValidationError): CallIntelligenceOutput.model_validate(p)

    def test_bad_json_not_silently_repaired(self):
        class BadJSON:
            def extract_intelligence(self, *args, **kwargs): raise ValueError("invalid JSON")
        r = process_transcript(TRANSCRIPT, BadJSON())
        self.assertEqual(r["status"], "error"); self.assertEqual(r["error_type"], "LLMError")

    def test_parser_error_recorded(self):
        r = process_transcript("not a transcript", self.client)
        self.assertEqual(r["status"], "error"); self.assertEqual(r["error_type"], "ParserError")

    def test_callback_is_not_inferred_by_pipeline(self):
        # Schema permits the model to express NOT_REQUESTED; pipeline does not derive intent.
        self.assertFalse(self.output.extracted_facts.conversational_commitments.callback_requested)
        self.assertEqual(self.output.analytical_interpretations.purchase_readiness_assessment.purchase_readiness.value, "NOT_EXPRESSED")

    def test_financial_and_stage2_boundary_is_explicit(self):
        self.assertIn("DO NOT calculate", SYSTEM_PROMPT)
        r = process_transcript(TRANSCRIPT, self.client, self.output)
        self.assertIn("Stage 2", r["stage2_boundary"])
        self.assertNotIn("stage2_decision", r)

    def test_provider_structured_parse_called(self):
        comp = FakeCompletions(parsed=self.output)
        client = LLMClient(api_key="x", client=FakeProvider(comp), max_retries=0)
        got = client.extract_intelligence("sys", "user")
        self.assertIsInstance(got, CallIntelligenceOutput)
        self.assertEqual(comp.calls[0]["response_format"], CallIntelligenceOutput)

    def test_provider_timeout_retry_then_success(self):
        class TimeoutErrorFake(Exception): pass
        comp = FakeCompletions(parsed=self.output)
        calls = {"n":0}
        def flaky(**kwargs):
            calls["n"] += 1
            if calls["n"] == 1: raise TimeoutErrorFake("timeout")
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(parsed=self.output, refusal=None))])
        comp.parse = flaky
        client = LLMClient(api_key="x", client=FakeProvider(comp), max_retries=1, sleep=lambda _:None)
        self.assertIsInstance(client.extract_intelligence("s", "u"), CallIntelligenceOutput)
        self.assertEqual(calls["n"], 2)

    def test_provider_nonretryable_failure_not_retried(self):
        class BadRequestErrorFake(Exception): status_code=400
        comp = FakeCompletions(error=BadRequestErrorFake("bad request"))
        client = LLMClient(api_key="x", client=FakeProvider(comp), max_retries=3, sleep=lambda _:None)
        with self.assertRaises(LLMClientError): client.extract_intelligence("s", "u")
        self.assertEqual(len(comp.calls), 1)

    def test_provider_missing_parsed_response_rejected(self):
        comp = FakeCompletions(parsed=None)
        client = LLMClient(api_key="x", client=FakeProvider(comp), max_retries=0)
        with self.assertRaises(LLMClientError): client.extract_intelligence("s", "u")

    def test_batch_isolates_errors(self):
        results = process_all_transcripts({"good.txt": TRANSCRIPT, "bad.txt": "bad"}, self.client,
                                          {"good.txt": self.output})
        self.assertEqual(results["good.txt"]["status"], "success")
        self.assertEqual(results["bad.txt"]["status"], "error")

    def test_save_results_creates_json_and_summary(self):
        results = {"call.txt": {"status":"success", "structured_output":{"x":1}}}
        with tempfile.TemporaryDirectory() as d:
            save_results(results, d)
            self.assertTrue((Path(d)/"call.json").exists())
            summary = json.loads((Path(d)/"run_summary.json").read_text())
            self.assertEqual(summary["success"], 1)

    def test_real_six_transcripts_parse_and_map(self):
        root = Path(__file__).resolve().parent.parent
        files = sorted((root / "data" / "raw" / "transcripts").glob("call_*.txt"))
        self.assertEqual(len(files), 6, "Expected the six supplied source transcripts alongside the project folder")
        from stage3.transcript_parser import parse_transcript
        expected = {"LEAD-801", "LEAD-802", "LEAD-803", "LEAD-804", "LEAD-805", "LEAD-806"}
        parsed = {parse_transcript(p.read_text(encoding="utf-8")).lead_code for p in files}
        self.assertEqual(parsed, expected)

if __name__ == "__main__": unittest.main(verbosity=2)
