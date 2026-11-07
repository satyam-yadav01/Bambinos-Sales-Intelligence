"""Shared paths, loaders, typing and policy parsing for Stage 1.

Raw files are never modified: they are read as strings, then a *separate* cleaned/typed
copy is produced in memory. Nothing here writes to the raw directory.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

NULL_TOKENS = ["NULL", "null", "", "NaN", "nan", "N/A", "None"]

RAW_PATTERNS = {
    "crm": "1_crm_leads*.csv",
    "demo": "2_demo_class_evaluations*.csv",
    "calls": "3_sales_call_logs*.csv",
    "orders": "4_live_orders_and_invoices*.csv",
    "policy": "reference_courses_pricing_and_compliance_policy*.csv",
}

# Columns converted to typed values; anything non-null that fails to parse is recorded.
TYPES = {
    "crm": {"dt": ["last_call_at", "next_followup_at", "created_at", "updated_at", "deleted_at"],
            "num": ["student_age"]},
    "demo": {"dt": ["demo_completed_at"],
             "num": ["demo_batch_size", "child_engagement_score_1_to_5"]},
    "calls": {"dt": ["call_started_at"],
              "num": ["call_duration_sec", "rep_talk_time_pct", "parent_talk_time_pct"]},
    "orders": {"dt": ["paid_at", "updated_at"],
               "num": ["plan_sessions", "standard_amount", "discount_applied", "net_payable_amount"]},
    "policy": {"dt": [],
               "num": ["sessions_included", "standard_fee_india_inr",
                       "standard_fee_gcc_aed", "standard_fee_usa_usd"]},
}

PII_COLUMNS = {"student_name", "parent_name", "mobile", "email", "parent_mobile", "demo_educator_name"}


def lead_code(lead_id) -> str:
    return f"LEAD-{lead_id}"


def find_raw_files(raw_dir: Path) -> dict[str, Path]:
    found = {}
    for key, pattern in RAW_PATTERNS.items():
        matches = sorted(raw_dir.glob(pattern))
        if len(matches) != 1:
            raise FileNotFoundError(f"Expected exactly one file matching {pattern} in {raw_dir}, found {len(matches)}")
        found[key] = matches[0]
    return found


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_raw(path: Path) -> pd.DataFrame:
    """Exact source values as strings (no NA conversion)."""
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def clean(df: pd.DataFrame) -> pd.DataFrame:
    """Trim whitespace and convert NULL-like tokens to <NA>. Returns a new frame."""
    out = df.apply(lambda s: s.str.strip())
    return out.mask(out.isin(NULL_TOKENS), pd.NA)


def to_typed(name: str, df: pd.DataFrame):
    """Return (typed_df, coercion_failures). A failure = non-null value that did not parse."""
    out, failures = df.copy(), []
    spec = TYPES[name]
    for col in spec["dt"]:
        parsed = pd.to_datetime(out[col], errors="coerce")
        for i in out.index[out[col].notna() & parsed.isna()]:
            failures.append((name, f"row {i + 2}", col, out.at[i, col]))
        out[col] = parsed
    for col in spec["num"]:
        parsed = pd.to_numeric(out[col], errors="coerce")
        for i in out.index[out[col].notna() & parsed.isna()]:
            failures.append((name, f"row {i + 2}", col, out.at[i, col]))
        out[col] = parsed
    return out, failures


def load_all(raw_dir: Path):
    """Return (raw, typed, coercion_failures, paths) keyed by dataset name."""
    paths = find_raw_files(raw_dir)
    raw, typed, failures = {}, {}, []
    for key, path in paths.items():
        raw[key] = load_raw(path)
        typed[key], f = to_typed(key, clean(raw[key]))
        failures += f
    return raw, typed, failures, paths


def payment_category(status) -> str:
    """Normalise gateway/payment status text into Paid / Failed / Flagged / Unpaid (descriptive only)."""
    s = str(status)
    if s == "Paid":
        return "Paid"
    if "Failed" in s:
        return "Failed"
    if "Flagged" in s:
        return "Flagged"
    return "Unpaid"


def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series.str.replace(",", "", regex=False), errors="coerce")


def parse_policy(pol: pd.DataFrame) -> pd.DataFrame:
    """Structured view of the policy text columns. Source text columns are kept untouched."""
    p = pol.copy()
    p["max_discount_pct"] = pd.to_numeric(p["max_rep_discount_allowed_pct"].str.extract(r"(\d+(?:\.\d+)?)\s*%")[0])
    p["cap_inr"] = _num(p["max_rep_discount_allowed_pct"].str.extract(r"Rs\.?\s*([\d,]+)")[0])
    p["cap_aed"] = _num(p["max_rep_discount_allowed_pct"].str.extract(r"AED\s*([\d,]+)")[0])
    p["cap_usd"] = _num(p["max_rep_discount_allowed_pct"].str.extract(r"USD\s*([\d,]+)")[0])
    ages = p["target_age_grades"].str.extract(r"Ages\s*(\d+)\s*-\s*(\d+)")
    p["age_min"], p["age_max"] = pd.to_numeric(ages[0]), pd.to_numeric(ages[1])
    p["grade_max"] = pd.to_numeric(p["target_age_grades"].str.extract(r"to Grade (\d+)")[0])
    gmin = pd.to_numeric(p["target_age_grades"].str.extract(r"\(Grade (\d+)")[0])
    p["grade_min"] = gmin.mask(p["target_age_grades"].str.contains("Pre-K"), 0)
    return p
