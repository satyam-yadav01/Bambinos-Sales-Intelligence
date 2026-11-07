"""CLI: python run_extraction.py --input-dir ../ --output-dir outputs"""
from __future__ import annotations
import argparse, os
from pathlib import Path
from dotenv import load_dotenv
from s3.llm_client import LLMClient
from s3.extraction_pipeline import process_all_transcripts, save_results


def main():
    parser = argparse.ArgumentParser(description="Extract sales-call intelligence from transcript text files.")
    parser.add_argument("--input-dir", default=".", help="Directory containing call_*.txt files")
    parser.add_argument("--output-dir", default="outputs", help="Directory for per-transcript JSON and run summary")
    parser.add_argument("--file", help="Process one transcript filename or path")
    args = parser.parse_args()
    load_dotenv()
    root = Path(args.input_dir)
    files = [Path(args.file)] if args.file else sorted(root.glob("call_*.txt"))
    if not files:
        parser.error(f"No transcript files found in {args.input_dir!r}")
    transcripts = {}
    for path in files:
        actual = path if path.is_absolute() or path.exists() else root / path
        if not actual.is_file():
            transcripts[str(path)] = ""  # recorded as parser failure, not silently skipped
        else:
            transcripts[actual.name] = actual.read_text(encoding="utf-8")
    client = LLMClient(api_key=os.getenv("OPENAI_API_KEY"), model=os.getenv("OPENAI_MODEL"),
                       timeout=float(os.getenv("OPENAI_TIMEOUT", "60")),
                       max_retries=int(os.getenv("OPENAI_MAX_RETRIES", "2")))
    results = process_all_transcripts(transcripts, client)
    save_results(results, args.output_dir)
    for name, result in results.items():
        print(f"{name}: {result.get('status')} ({result.get('error_type') or 'OK'})")
    print(f"Saved {len(results)} result(s) to {args.output_dir}")
    if any(r.get("status") != "success" for r in results.values()):
        raise SystemExit(2)

if __name__ == "__main__":
    main()
