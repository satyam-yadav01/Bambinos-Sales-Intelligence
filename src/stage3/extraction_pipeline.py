"""End-to-end extraction. Stage 2 decisions are deliberately not accepted or mutated here."""
from __future__ import annotations
import json, time
from pathlib import Path
from typing import Dict, Any, Optional
from pydantic import ValidationError
from .transcript_parser import parse_transcript, TranscriptParserError
from .schemas import validate_evidence_quotes, CallIntelligenceOutput
from .extraction_prompt import SYSTEM_PROMPT, build_user_prompt
from .llm_client import LLMClient


def process_transcript(raw_transcript: str, llm_client: LLMClient,
                       mock_response: Optional[CallIntelligenceOutput] = None) -> Dict[str, Any]:
    started = time.monotonic()
    try:
        parsed = parse_transcript(raw_transcript)
    except TranscriptParserError as exc:
        return {"status": "error", "error_type": "ParserError", "message": str(exc)}

    metadata = {"call_id": parsed.call_id, "lead_code": parsed.lead_code,
                "counsellor_id": parsed.counsellor_id, "timezone": parsed.timezone,
                "call_started_at": parsed.call_started_at}
    user_prompt = build_user_prompt(parsed.dialogue_only, metadata)
    try:
        output = llm_client.extract_intelligence(SYSTEM_PROMPT, user_prompt, mock_response=mock_response)
        if not isinstance(output, CallIntelligenceOutput):
            output = CallIntelligenceOutput.model_validate(output)
    except ValidationError as exc:
        return {"status": "error", "error_type": "SchemaValidationError",
                "message": str(exc), "metadata": metadata,
                "duration_seconds": round(time.monotonic() - started, 3)}
    except Exception as exc:
        return {"status": "error", "error_type": "LLMError",
                "message": f"{type(exc).__name__}: {exc}", "metadata": metadata,
                "duration_seconds": round(time.monotonic() - started, 3)}

    # IDs come from trusted parser metadata, never from the model's guess.
    identity_errors = []
    if output.lead_code != parsed.lead_code:
        identity_errors.append(f"Model lead_code {output.lead_code!r} does not match parser metadata {parsed.lead_code!r}.")
    if parsed.call_id and output.transcript_id != parsed.call_id:
        identity_errors.append(f"Model transcript_id {output.transcript_id!r} does not match parser call_id {parsed.call_id!r}.")

    evidence = validate_evidence_quotes(output.model_dump(), parsed.dialogue_only)
    validation_passed = not evidence.get("errors") and not identity_errors
    result = {
        "status": "success" if validation_passed else "validation_failed",
        "error_type": None if validation_passed else "OutputValidationError",
        "metadata": metadata,
        "structured_output": output.model_dump(mode="json"),
        "identity_validation": {"passed": not identity_errors, "errors": identity_errors},
        "evidence_validation": evidence,
        "validation_passed": validation_passed,
        "duration_seconds": round(time.monotonic() - started, 3),
        "stage2_boundary": "No Stage 2 inputs were accepted or modified; deterministic restrictions remain external and authoritative."
    }
    return result


def process_all_transcripts(transcripts: Dict[str, str], llm_client: LLMClient,
                            mock_responses: Optional[Dict[str, CallIntelligenceOutput]] = None) -> Dict[str, Dict[str, Any]]:
    results = {}
    for filename, raw_text in transcripts.items():
        try:
            results[filename] = process_transcript(raw_text, llm_client,
                mock_response=(mock_responses or {}).get(filename))
        except Exception as exc:  # isolate unexpected per-file failures
            results[filename] = {"status": "error", "error_type": "UnexpectedError",
                                 "message": f"{type(exc).__name__}: {exc}"}
    return results


def save_results(results: Dict[str, Dict[str, Any]], output_dir: str | Path) -> None:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    for name, result in results.items():
        safe_name = Path(name).stem.replace("..", "_")
        (target / f"{safe_name}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {"total": len(results),
               "success": sum(r.get("status") == "success" for r in results.values()),
               "validation_failed": sum(r.get("status") == "validation_failed" for r in results.values()),
               "error": sum(r.get("status") == "error" for r in results.values()),
               "files": {k: {"status": v.get("status"), "error_type": v.get("error_type"),
                             "message": v.get("message")} for k, v in results.items()}}
    (target / "run_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
