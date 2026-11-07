"""Stage 1 validation checks. Descriptive only: no business-rule verdicts (that is Stage 2).

Each check logs how many records it tested and returns findings; passes are logged too so the
reviewer can see what was examined. Nothing is corrected here.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from .audit import Audit, F
from .canonical import build_canonical_map, partial_identity_overlaps
from .common import lead_code, parse_policy, payment_category

CURRENCY_COL = {"INR": "standard_fee_india_inr", "AED": "standard_fee_gcc_aed", "USD": "standard_fee_usa_usd"}
COUNTRY_CCY = {"India": "INR", "UAE (GCC)": "AED", "USA": "USD", "UK": "GBP"}
COUNTRY_PREFIX = {"India": "+91", "UAE (GCC)": "+971", "Qatar (GCC)": "+974", "USA": "+1", "UK": "+44"}
FOLLOWUP_SEVERITY = {"Demo_Completed_Uncalled": "High", "Follow_Up_Hot": "High", "Follow_Up_Warm": "Medium",
                     "Payment_Link_Sent": "Medium", "Follow_Up_Cold": "Low", "New_Duplicate_Lead": "Low"}

PKS = {"crm": "id", "demo": "demo_id", "calls": "call_id", "orders": "order_id", "policy": "class_id"}
FKS = {("demo", "lead_id"): "crm.id", ("calls", "lead_id"): "crm.id", ("orders", "lead_id"): "crm.id",
       ("crm", "class_id"): "policy.class_id", ("demo", "class_id"): "policy.class_id",
       ("orders", "class_id"): "policy.class_id", ("demo", "student_id"): "crm.student_id",
       ("orders", "student_id"): "crm.student_id", ("calls", "counsellor_id"): "crm.assigned_counsellor_id"}


def _fmt(ts) -> str:
    return "NULL" if pd.isna(ts) else pd.Timestamp(ts).strftime("%Y-%m-%d %H:%M")


def _g(x) -> str:
    return f"{x:g}"


def run_all(D: dict, coercion_failures: list, raw_dir: Path, redactor) -> tuple[Audit, pd.DataFrame]:
    A = Audit()
    crm, demo, calls, orders, pol = (D[k] for k in ("crm", "demo", "calls", "orders", "policy"))
    canon = build_canonical_map(crm)
    polp = parse_policy(pol).set_index("class_id")
    crm_i = crm.set_index("id")
    stage = crm_i["crm_lead_stage"]

    # ---- parsing -------------------------------------------------------------------------
    A.record("PARSE", "Non-null values that failed date/number parsing",
             sum(len(D[k]) for k in D),
             [F(ds, key, col, val, "Value could not be parsed", "High", "FORMAT") for ds, key, col, val in coercion_failures])

    # ---- keys ----------------------------------------------------------------------------
    for ds, col in [("crm", "id"), ("crm", "lead_code"), ("demo", "demo_id"), ("calls", "call_id"),
                    ("orders", "order_id"), ("orders", "invoice_number"), ("policy", "class_id")]:
        df = D[ds]
        bad = df[df[col].duplicated(keep=False) | df[col].isna()]
        A.record(f"PK_{ds}_{col}", f"{ds}.{col} is unique and non-null", len(df),
                 [F(ds, f"row {i + 2}", col, r[col], "Duplicate or missing key", "High", "KEY") for i, r in bad.iterrows()])

    bad = crm[crm["lead_code"] != "LEAD-" + crm["id"]]
    A.record("KEY_lead_code", "crm.lead_code equals LEAD-<id>", len(crm),
             [F("crm", r.lead_code, "lead_code", r.lead_code, f"id is {r.id}", "Medium", "KEY") for r in bad.itertuples()])

    crm_ids = set(crm["id"])
    for ds in ("demo", "calls", "orders"):
        df = D[ds]
        bad = df[~df["lead_id"].isin(crm_ids)]
        A.record(f"FK_{ds}_lead", f"{ds}.lead_id exists in crm.id", len(df),
                 [F(ds, f"row {i + 2}", "lead_id", r.lead_id, "No matching CRM lead", "High", "FK") for i, r in bad.iterrows()])

    for ds in ("crm", "demo", "orders"):
        df = D[ds]
        bad = df[~df["class_id"].isin(set(pol["class_id"]))]
        A.record(f"FK_{ds}_class", f"{ds}.class_id exists in policy.class_id", len(df),
                 [F(ds, lead_code(r.id if ds == "crm" else r.lead_id), "class_id", r.class_id,
                    "class_id not in policy file: price, discount cap and compliance rules cannot be looked up",
                    "Medium", "POLICY_GAP", "Provide policy entry for this class_id or confirm it is out of scope")
                  for _, r in bad.iterrows()])

    for ds in ("demo", "orders"):
        for col in ("student_id", "class_id"):
            j = D[ds].join(crm_i[[col]], on="lead_id", rsuffix="_crm")
            bad = j[j[f"{col}_crm"].notna() & (j[col] != j[f"{col}_crm"])]
            A.record(f"CONS_{ds}_{col}", f"{ds}.{col} equals CRM {col} for the same lead", len(j),
                     [F(ds, lead_code(r.lead_id), col, r[col], f"CRM has {r[f'{col}_crm']}", "High", "CONSISTENCY")
                      for _, r in bad.iterrows()])

    # ---- duplicates / canonical ----------------------------------------------------------
    dups = canon[~canon["is_canonical"]]
    A.record("DUP_identity", "Leads sharing user_id+student_id+mobile+email (proposed duplicates)", len(crm),
             [F("crm", r.lead_code, "identity", f"matches {r.canonical_lead_code} on user_id, student_id, mobile, email",
                "Same person re-inquired; mapping is inferred, not in source", "Medium", "DUPLICATE",
                f"Approve proposed SAME_CUSTOMER_PROPOSED relationship {r.lead_code} <-> {r.canonical_lead_code} (no records merged)") for r in dups.itertuples()])
    A.record("DUP_partial", "Leads sharing only some identity fields (possible duplicates not auto-merged)", len(crm),
             [F("crm", ", ".join(ids), col, "shared value withheld", "Shares one identity field but not all; not merged",
                "Medium", "DUPLICATE", "Confirm whether these are the same person") for col, _, ids in partial_identity_overlaps(crm, canon)])
    has_canon_col = any(("canonical" in c) or ("duplicate_of" in c) for c in crm.columns)
    marked = crm[crm["crm_lead_stage"] == "New_Duplicate_Lead"]
    A.record("DUP_canonical_field", "Leads marked New_Duplicate_Lead carry a canonical lead id", len(marked),
             [] if has_canon_col else
             [F("crm", r.lead_code, "canonical_lead_id", "column does not exist in CRM export",
                "Marked duplicate but the export has no field naming the original lead", "High", "MISSING_FIELD",
                "Confirm canonical lead (proposed from identity match) or supply the field") for r in marked.itertuples()])

    # ---- CRM completeness & timeline ------------------------------------------------------
    nf = crm[crm["next_followup_at"].isna()]
    A.record("CRM_followup_null", "CRM leads have next_followup_at", len(crm),
             [F("crm", r.lead_code, "next_followup_at", "NULL", f"No follow-up scheduled; stage {r.crm_lead_stage}",
                FOLLOWUP_SEVERITY.get(r.crm_lead_stage, "Medium"), "MISSING_FOLLOWUP") for r in nf.itertuples()])
    st = crm[crm["next_followup_at"].notna() & crm["last_call_at"].notna() & (crm["next_followup_at"] < crm["last_call_at"])]
    A.record("CRM_followup_before_call", "next_followup_at is not earlier than last_call_at", int(crm["next_followup_at"].notna().sum()),
             [F("crm", r.lead_code, "next_followup_at", _fmt(r.next_followup_at),
                f"Follow-up is before last call ({_fmt(r.last_call_at)}); date not refreshed after the call", "Medium", "STALE_FOLLOWUP") for r in st.itertuples()])
    cn = crm[crm["created_at"].isna()]
    A.record("CRM_created_null", "CRM leads have created_at", len(crm),
             [F("crm", r.lead_code, "created_at", "NULL", f"Stage {r.crm_lead_stage}", "Medium", "MISSING_VALUE") for r in cn.itertuples()])
    A.record("CRM_soft_deleted", "No CRM lead is soft-deleted (deleted_at NULL)", len(crm),
             [F("crm", r.lead_code, "deleted_at", _fmt(r.deleted_at), "Lead is soft-deleted", "Medium", "DELETED") for r in crm[crm["deleted_at"].notna()].itertuples()])
    short = crm[crm["manual_rep_notes"].notna() & (crm["manual_rep_notes"].str.len() < 5)]
    A.record("CRM_note_quality", "Rep notes are longer than 4 characters when present", int(crm["manual_rep_notes"].notna().sum()),
             [F("crm", r.lead_code, "manual_rep_notes", f"'{r.manual_rep_notes}'", f"Uninformative note; disposition '{r.manual_rep_disposition}'", "Low", "NOTE_QUALITY") for r in short.itertuples()])
    A.record("CRM_stage_vocab", "CRM stage vocabulary can represent a paid/enrolled lead", 1,
             [] if crm["crm_lead_stage"].str.contains("paid|enrol|won", case=False).any() else
             [F("crm", "crm.crm_lead_stage", "crm_lead_stage", ", ".join(sorted(crm["crm_lead_stage"].unique())),
                "No stage value represents payment received/enrolled; paid leads stay in an earlier stage", "Medium", "SCHEMA",
                "Decide how paid status should be represented downstream (derive from orders)")])

    # ---- demo / call coverage -------------------------------------------------------------
    demo_leads, call_leads = set(demo["lead_id"]), set(calls["lead_id"])
    no_call_never = [i for i in sorted(demo_leads - call_leads) if pd.isna(crm_i.at[i, "last_call_at"])]
    no_log_but_crm = [i for i in sorted(demo_leads - call_leads) if pd.notna(crm_i.at[i, "last_call_at"])]
    A.record("COV_demo_no_call", "Demo-completed leads have a call (CRM last_call_at or call log)", len(demo_leads),
             [F("crm", lead_code(i), "last_call_at", "NULL", f"Demo done ({_fmt(demo.set_index('lead_id').at[i, 'demo_completed_at'])}), never called; stage {stage[i]}",
                "High", "UNCALLED_DEMO") for i in no_call_never])
    A.record("COV_crm_call_no_log", "Leads whose CRM shows a call also have a call-log record", int(crm["last_call_at"].notna().sum()),
             [F("calls", lead_code(i), "call_id", "no record", f"CRM last_call_at {_fmt(crm_i.at[i, 'last_call_at'])}, disposition '{crm_i.at[i, 'manual_rep_disposition']}', but no call log or transcript",
                "Medium", "MISSING_CALL_LOG", "Supply call log/transcript or confirm call did not occur") for i in no_log_but_crm])

    j = calls.join(crm_i, on="lead_id", rsuffix="_crm")
    mism = []
    for r in j.itertuples():
        for a, b, f in [(r.call_started_at, r.last_call_at, "last_call_at"), (r.rep_logged_disposition, r.manual_rep_disposition, "disposition"),
                        (r.counsellor_id, r.assigned_counsellor_id, "counsellor_id"), (r.rep_logged_crm_note, r.manual_rep_notes, "note")]:
            if a != b:
                mism.append(F("calls", lead_code(r.lead_id), f, str(a), f"CRM has {b}", "Medium", "CONSISTENCY"))
    A.record("CONS_call_vs_crm", "Call log agrees with CRM (call time, disposition, counsellor, note)", len(j), mism)

    names = pd.concat([crm[["assigned_counsellor_id", "assigned_counsellor_name"]].set_axis(["cid", "cname"], axis=1),
                       calls[["counsellor_id", "counsellor_name"]].set_axis(["cid", "cname"], axis=1)]).drop_duplicates()
    amb = names[names["cid"].duplicated(keep=False)]
    A.record("CONS_counsellor_id_name", "Each counsellor id maps to one name across CRM and call logs", names["cid"].nunique(),
             [F("calls", f"counsellor {r.cid}", "counsellor_name", r.cname, "Multiple names for one id", "Medium", "CONSISTENCY") for r in amb.itertuples()])

    bad = calls[(calls["rep_talk_time_pct"] + calls["parent_talk_time_pct"] != 100) | (calls["call_duration_sec"] <= 0)]
    A.record("CALL_talk_pct", "Talk-time percentages sum to 100 and duration > 0", len(calls),
             [F("calls", lead_code(r.lead_id), "talk_time", f"{_g(r.rep_talk_time_pct)}+{_g(r.parent_talk_time_pct)}", "Percentages do not sum to 100 or bad duration", "Medium", "RANGE") for r in bad.itertuples()])

    available = {p.name for p in raw_dir.glob("**/*.txt")}
    A.record("CALL_transcript_files", "Transcript file named in call log was supplied", len(calls),
             [F("calls", lead_code(r.lead_id), "transcript_filename", r.transcript_filename, "Transcript file not supplied with the datasets; Stage 3 cannot analyse this call",
                "High", "MISSING_FILE", "Supply transcript files before Stage 3") for r in calls.itertuples() if r.transcript_filename not in available])
    bad = calls[[(re.search(r"LEAD(\d+)", f) or [None, None])[1] != l for f, l in zip(calls["transcript_filename"], calls["lead_id"])]]
    A.record("CALL_transcript_name_lead", "Lead number inside transcript filename equals lead_id", len(calls),
             [F("calls", lead_code(r.lead_id), "transcript_filename", r.transcript_filename, "Lead number in filename differs", "High", "CONSISTENCY") for r in bad.itertuples()])

    tl = []
    dj = demo.join(crm_i[["created_at", "updated_at"]], on="lead_id")
    for r in dj.itertuples():
        if pd.notna(r.created_at) and r.demo_completed_at < r.created_at:
            tl.append(F("demo", lead_code(r.lead_id), "demo_completed_at", _fmt(r.demo_completed_at), f"Before CRM created_at {_fmt(r.created_at)}", "Medium", "TIMELINE"))
        if r.demo_completed_at > r.updated_at:
            tl.append(F("demo", lead_code(r.lead_id), "demo_completed_at", _fmt(r.demo_completed_at), f"After CRM updated_at {_fmt(r.updated_at)}", "Medium", "TIMELINE"))
    for r in j.itertuples():
        d = demo[demo["lead_id"] == r.lead_id]
        if len(d) and (d["demo_completed_at"] > r.call_started_at).any():
            tl.append(F("calls", lead_code(r.lead_id), "call_started_at", _fmt(r.call_started_at), "Call precedes demo completion", "Low", "TIMELINE"))
        if r.call_started_at > r.updated_at:
            tl.append(F("calls", lead_code(r.lead_id), "call_started_at", _fmt(r.call_started_at), "Call after CRM updated_at", "Medium", "TIMELINE"))
    bad = crm[crm["created_at"].notna() & (crm["created_at"] > crm["updated_at"])]
    tl += [F("crm", r.lead_code, "created_at", _fmt(r.created_at), "created_at after updated_at", "Medium", "TIMELINE") for r in bad.itertuples()]
    A.record("TIMELINE", "Created <= demo <= call <= CRM updated", len(crm) + len(demo) + len(calls), tl)

    # ---- demo quality ---------------------------------------------------------------------
    bad = demo[~demo["child_engagement_score_1_to_5"].between(1, 5) | (demo["demo_batch_size"] < 1) | (demo["attended_demo"] != "Yes")]
    A.record("DEMO_ranges", "Engagement 1-5, batch size >= 1, attended_demo = Yes", len(demo),
             [F("demo", lead_code(r.lead_id), "demo_row", f"engagement {r.child_engagement_score_1_to_5}, batch {r.demo_batch_size}, attended {r.attended_demo}", "Outside expected range", "Medium", "RANGE") for r in bad.itertuples()])
    ann = demo[demo["demo_magic_moment_for_parent"].str.contains(r"UNCALLED|HIGH INTENT", regex=True, na=False)]
    A.record("DEMO_embedded_annotation", "Educator observation fields contain only observations", len(demo),
             [F("demo", lead_code(r.lead_id), "demo_magic_moment_for_parent", "contains '(HIGH INTENT ... UNCALLED BY REP)'",
                "Sales-status annotation inside an educator text field; treat as unverified free text, not a source of truth", "Low", "FREE_TEXT_ANNOTATION") for r in ann.itertuples()])

    # ---- age / grade vs policy target ------------------------------------------------------
    j = crm.join(polp[["age_min", "age_max", "grade_min", "grade_max"]], on="class_id")
    j = j[j["age_min"].notna()]
    grade = pd.to_numeric(j["student_grade"].str.extract(r"(\d+)")[0])
    bad = j[(j["student_age"] < j["age_min"]) | (j["student_age"] > j["age_max"]) | (grade < j["grade_min"]) | (grade > j["grade_max"])]
    A.record("POLICY_age_grade", "Student age/grade within policy target band for pitched course", len(j),
             [F("crm", r.lead_code, "student_age/grade", f"{_g(r.student_age)} / {r.student_grade}", "Outside policy target band", "Low", "ELIGIBILITY") for r in bad.itertuples()])

    # ---- contact validity (values withheld) ------------------------------------------------
    cbad = []
    for r in crm.itertuples():
        m = re.sub(r"[\s\-]", "", str(r.mobile))
        if not m.startswith(COUNTRY_PREFIX.get(r.country, "?")):
            cbad.append(F("crm", r.lead_code, "mobile", "value withheld", f"Country code does not match country {r.country}", "Low", "CONTACT"))
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", str(r.email)):
            cbad.append(F("crm", r.lead_code, "email", "value withheld", "Invalid email format", "Low", "CONTACT"))
        if pd.isna(r.student_name) or pd.isna(r.parent_name):
            cbad.append(F("crm", r.lead_code, "name", "NULL", "Missing student or parent name", "Low", "MISSING_VALUE"))
    A.record("CRM_contact", "Mobile country code, email format, names present", len(crm), cbad)

    # ---- id gaps -------------------------------------------------------------------------
    gaps = []
    for ds, col in [("crm", "id"), ("demo", "demo_id"), ("calls", "call_id"), ("orders", "order_id")]:
        ids = sorted(pd.to_numeric(D[ds][col]))
        missing = sorted(set(range(int(ids[0]), int(ids[-1]) + 1)) - set(ids))
        if missing:
            gaps.append(F(ds, f"{col} {missing[0]}..{missing[-1]}" if len(missing) > 1 else f"{col} {missing[0]}", col,
                          ", ".join(map(str, missing)), "Gap in id sequence; records may be missing from the extract", "Low", "ID_GAP",
                          "Confirm whether these records exist elsewhere"))
    A.record("ID_gaps", "Id sequences are contiguous", 4, gaps)

    # ---- orders ---------------------------------------------------------------------------
    arith, price, ident, pay_crm = [], [], [], []
    for r in orders.itertuples():
        key = lead_code(r.lead_id)
        exp = r.standard_amount - r.discount_applied
        if abs(exp - r.net_payable_amount) > 0.01:
            if "50% Down" in str(r.payment_plan_type) and abs(0.5 * exp - r.net_payable_amount) <= 0.01:
                arith.append(F("orders", key, "net_payable_amount", _g(r.net_payable_amount),
                               f"Equals 50% of (standard {_g(r.standard_amount)} - discount {_g(r.discount_applied)}) = first instalment, not course net",
                               "Info", "SEMANTICS"))
            else:
                arith.append(F("orders", key, "net_payable_amount", _g(r.net_payable_amount),
                               f"standard {_g(r.standard_amount)} - discount {_g(r.discount_applied)} = {_g(exp)}, but net recorded is {_g(r.net_payable_amount)}",
                               "High", "ARITHMETIC", "Confirm correct standard_amount"))
        col = CURRENCY_COL.get(r.currency)
        if r.class_id in polp.index:
            if col is None:
                price.append(F("orders", key, "currency", r.currency, f"Policy has no price column for {r.currency}; list price cannot be verified",
                               "High", "POLICY_GAP", "Provide UK/GBP price list or confirm treatment"))
            elif r.standard_amount != polp.at[r.class_id, col]:
                lp = polp.at[r.class_id, col]
                price.append(F("orders", key, "standard_amount", f"{r.currency} {_g(r.standard_amount)}",
                               f"Policy list price is {_g(lp)} ({_g(r.standard_amount / lp)}x)", "High", "PRICE_MISMATCH",
                               "Confirm correct list price (possible 10x entry error)"))
        if r.invoice_number.split("-")[-1] != r.order_id:
            ident.append(F("orders", key, "invoice_number", r.invoice_number, "Suffix differs from order_id", "Medium", "CONSISTENCY"))
        if r.class_id in polp.index and r.plan_sessions != polp.at[r.class_id, "sessions_included"]:
            ident.append(F("orders", key, "plan_sessions", _g(r.plan_sessions), "Differs from policy sessions_included", "Medium", "CONSISTENCY"))
        if (r.payment_link_status == "Paid") != pd.notna(r.paid_at):
            ident.append(F("orders", key, "paid_at", _fmt(r.paid_at), f"paid_at presence does not match status {r.payment_link_status}", "High", "CONSISTENCY"))
        c = crm_i.loc[r.lead_id] if r.lead_id in crm_i.index else None
        if c is not None:
            if re.sub(r"[\s\-]", "", str(r.parent_mobile)) != re.sub(r"[\s\-]", "", str(c["mobile"])):
                ident.append(F("orders", key, "parent_mobile", "value withheld", "Differs from CRM mobile", "Medium", "CONSISTENCY"))
            if COUNTRY_CCY.get(c["country"], r.currency) != r.currency:
                ident.append(F("orders", key, "currency", r.currency, f"CRM country {c['country']} implies {COUNTRY_CCY[c['country']]}", "Medium", "CONSISTENCY"))
            cat, s = payment_category(r.payment_link_status), c["crm_lead_stage"]
            if cat == "Paid" and s != "Paid":
                pay_crm.append(F("orders", key, "payment_link_status", f"Paid ({_fmt(r.paid_at)})",
                                 f"CRM stage is {s} (CRM updated {_fmt(c['updated_at'])}, before payment); CRM does not reflect the payment",
                                 "High", "PAYMENT_CRM_MISMATCH", "Confirm CRM should be treated as stale; payment record is the evidence"))
            elif cat != "Paid" and s != "Payment_Link_Sent":
                later = "; order updated after CRM" if r.updated_at > c["updated_at"] else ""
                pay_crm.append(F("orders", key, "payment_link_status", f"{r.payment_link_status}",
                                 f"Order exists ({cat}) but CRM stage is {s}{later}", "Medium", "PAYMENT_CRM_MISMATCH"))
    A.record("ORD_arithmetic", "net_payable = standard - discount (instalment-aware)", len(orders), arith)
    A.record("ORD_list_price", "Order standard_amount matches policy list price for its currency", len(orders), price)
    A.record("ORD_consistency", "Invoice suffix, sessions, paid_at, mobile, currency-vs-country consistent", len(orders), ident)
    A.record("ORD_vs_CRM_stage", "CRM stage reflects the order's payment status", len(orders), pay_crm)

    cap = []
    for r in orders.itertuples():
        m = re.search(r">\s*(\d+)\s*%", str(r.gateway_error_reason))
        if m and r.class_id in polp.index and float(m.group(1)) != polp.at[r.class_id, "max_discount_pct"]:
            cap.append(F("orders", lead_code(r.lead_id), "gateway_error_reason", f"cap {m.group(1)}%",
                         f"Gateway message cites {m.group(1)}% cap; policy max is {_g(polp.at[r.class_id, 'max_discount_pct'])}%", "Medium", "POLICY_CONFLICT",
                         "Confirm which cap is authoritative"))
    A.record("ORD_gateway_cap_vs_policy", "Discount cap quoted in gateway message equals policy cap", int(orders["gateway_error_reason"].str.contains("%", na=False).sum()), cap)

    # ---- policy table internal consistency -------------------------------------------------
    pbad = []
    for cid, r in polp.iterrows():
        for ccy, capcol, feecol in [("INR", "cap_inr", "standard_fee_india_inr"), ("AED", "cap_aed", "standard_fee_gcc_aed"), ("USD", "cap_usd", "standard_fee_usa_usd")]:
            if pd.notna(r[capcol]):
                exp = r["max_discount_pct"] / 100 * r[feecol]
                if abs(exp - r[capcol]) > 1:
                    pbad.append(F("policy", f"class {cid}", capcol, f"{ccy} {_g(r[capcol])}", f"{_g(r['max_discount_pct'])}% of {_g(r[feecol])} = {_g(exp)}", "Low", "POLICY_INTERNAL",
                                  "Confirm which cap (percentage or absolute) governs"))
    A.record("POLICY_cap_consistency", "Absolute discount caps equal the stated percentage of list price", len(polp), pbad)
    A.record("POLICY_currency_coverage", "Policy has list prices for every currency present in orders and CRM countries", 1,
             [F("policy", "policy columns", "standard_fee_*", "INR, AED, USD only", "No GBP/UK column; Qatar assumed covered by the AED GCC price (unconfirmed)", "Medium", "POLICY_GAP",
                "Provide UK price list; confirm Qatar uses AED GCC pricing")])
    name_bad = []
    for r in crm.itertuples():
        if r.class_id in polp.index and r.course_pitched.strip().lower() != polp.at[r.class_id, "course_name"].strip().lower():
            name_bad.append(F("crm", r.lead_code, "course_pitched", r.course_pitched, f"Policy name is '{polp.at[r.class_id, 'course_name']}'", "Low", "NAMING"))
    A.record("CRM_course_name", "CRM course name equals policy course name for the class_id", len(crm), name_bad)

    # ---- name character set (values withheld) ---------------------------------------------------
    ns = [F("crm", r.lead_code, col, "non-ASCII character in name (value withheld)",
            "Mixed-script/lookalike characters can break name matching and de-duplication", "Low", "FORMAT")
          for r in crm.itertuples() for col in ("student_name", "parent_name")
          if pd.notna(getattr(r, col)) and re.search(r"[^\x00-\x7F]", getattr(r, col))]
    A.record("CRM_name_charset", "Name fields use ASCII characters only", len(crm) * 2, ns)

    # ---- privacy: personal data inside free text ----------------------------------------------
    priv, scanned = [], 0
    for ds, df, cols, keyf in [
            ("crm", crm, ["manual_rep_disposition", "manual_rep_notes"], lambda r: r.lead_code),
            ("demo", demo, ["current_skill_level_assessed", "skill_strengths_observed", "learning_gaps_observed",
                            "demo_magic_moment_for_parent", "recommended_course_track", "recommended_batch_type"], lambda r: lead_code(r.lead_id)),
            ("calls", calls, ["transcript_filename", "rep_logged_disposition", "rep_logged_crm_note"], lambda r: lead_code(r.lead_id))]:
        for r in df.itertuples():
            for col in cols:
                val = getattr(r, col)
                if pd.isna(val):
                    continue
                scanned += 1
                _, labels = redactor.redact(val)
                if labels:
                    priv.append(F(ds, keyf(r), col, f"contains {', '.join(labels)} (text withheld)",
                                  "Personal data inside a free-text field; redacted in all generated outputs, raw file unchanged",
                                  "Medium", "PRIVACY", "Approve redaction approach; consider cleaning the source field"))
    A.record("PRIV_free_text", "Free-text fields contain no student/parent names, phone numbers or e-mail", scanned, priv)

    return A, canon
