# Bambinos Sales Intelligence: Stage 1 Report (revision 2, after review)

Scope: data understanding, validation, operational lead table. No Stage 2–4 logic. Raw files are untouched (SHA-256 in `outputs/run_manifest.json`, identical to the first run). Leads are referenced by `LEAD-xxx`.

## 0. Revision after review

**Customer identity vs lead opportunity.** The master table now holds one row per CRM lead (opportunity): **12 rows**. The earlier version collapsed LEAD-811 into LEAD-801, which hid a second opportunity (own counsellor, own creation date, own stage). Now:
- LEAD-801 (counsellor 204, created 2026-10-30) and LEAD-811 (counsellor 215, created 2026-11-03) are separate rows with their own values; nothing is merged, deleted or overwritten.
- The inferred link lives in `lead_canonical_map.csv` as `SAME_CUSTOMER_PROPOSED` (group CG-001, 801 = EARLIER, 811 = LATER, status `PROPOSED_PENDING_APPROVAL`). It is derived from identical user ID, student ID, mobile and email (values withheld) and is reversible: deleting the file leaves every lead record intact.
- The master only references the relationship (`customer_group_id`, `identity_relationship`, `identity_related_lead_codes`, `identity_inquiry_order`); the other 10 leads show `NONE`.
- Demo, call and order records stay attached to the lead id they carry. LEAD-811 has none of its own, so it is not given 801's demo.

**Data minimization.** Master columns removed: `user_id`, `student_id`, `assigned_counsellor_name`, names, mobile, email, `student_age`, `student_grade`, `city_timezone` (replaced by a `timezone_label` such as IST), and the demo educator name. Counsellor ids and lead codes stay. Age and grade are available via `lead_id` in the raw CRM; Stage 1 already checked them against the policy bands.

**Free-text redaction.** Source names are partly masked (e.g. `Aa***v`), but free text contains full first names (notes, demo observations, transcript filenames). The redactor matches the masked shape (start letters + end letter), so it over-redacts by design, and replaces hits with `[STUDENT]`, `[PARENT]`, `[NAME]`, `[EMAIL]`, `[PHONE]`. The first version of this redactor built no name patterns (a defect, fixed). Limits: names of people not in the CRM name columns are not detected, and some common words can be over-redacted (DQ-039 is such a false positive: `High_Aptitude_…`). Raw files are not edited.

## 1. Dataset verification

| Dataset | Rows | Cols | Preliminary figure | PK |
|---|---|---|---|---|
| CRM leads | 12 | 25 | 12 ✔ | `id` (= number in `lead_code`) |
| Demo evaluations | 11 | 17 | 11 ✔ | `demo_id` |
| Call logs | 6 | 12 | 6 ✔ | `call_id` |
| Orders/invoices | 6 | 17 | 6 ✔ | `order_id` |
| Policy | 6 | 12 | 6 ✔ | `class_id` |

Join keys: `lead_id` (demo/calls/orders → `crm.id`), `class_id` (crm/demo/orders → policy), `student_id`, `counsellor_id`. All FKs resolve except `class_id 108` (§3). 51 checks run: 29 passed, 22 flagged (54 findings: 15 High, 24 Medium, 14 Low, 1 Info). Full log: `checks_run.csv`.

Change from the previous 49 checks / 44 findings: the original 49 checks are unchanged and all 44 original findings remain (same check, record, field; severity unchanged). Two checks were added: `PRIV_free_text` (9 findings: names in 6 transcript filenames and in demo text for 801, 806, 809 — 8 genuine, DQ-039 a likely false positive) and `CRM_name_charset` (1 finding: LEAD-812 student name contains a non-ASCII lookalike character). The wording of the 6 `CALL_transcript_files` findings now has the child's name redacted. Issue ids were renumbered (DQ-001…054).

## 2. Preliminary findings, verified against raw records

| Lead | Verdict | Evidence |
|---|---|---|
| 803 | **Confirmed** | Phonics (101) list INR 9,500, policy max 10% (Rs 950). Recorded discount 4,000 = **42.1%** of list. Net 5,500 = 9,500 − 4,000. Gateway flag text cites a **15%** cap, which conflicts with policy's 10% (DQ-025). Verdict is a Stage 2 rule. |
| 804 | **Confirmed** | Order 99404 Paid USD 265 at 2026-11-03 11:40; matches policy USD price for class 302. CRM stage still `Payment_Link_Sent`, last CRM update 10:00 (before payment), follow-up still scheduled 20:00. CRM has no paid/enrolled stage at all (DQ-021). |
| 802 | **Confirmed, with nuance** | Recorded standard AED 12,000 vs policy 1,200 (10×). Net 1,100 = 1,200 − 100, but 12,000 − 100 ≠ 1,100, so the row is internally inconsistent. Discount 100 = 8.3% of the policy price, under the 10% cap. Entry error is likely, not proven. |
| 805 | **Confirmed** | List 12,000 matches policy. Discount 1,200 = exactly 10%. 50% of 10,800 = 5,400 = recorded net, so the net is the first instalment, not the course fee. Failed: `Bank_OTP_Timeout_On_UPI_Mandate`. CRM stage `Follow_Up_Warm` doesn't reflect it. |
| 809 | **Confirmed** | GBP 210, Payment_Failed (`3DS_Authentication_Declined_By_Issuer`). Policy has INR/AED/USD columns only. CRM `Payment_Link_Sent` + "Card error" is consistent with the failure. |
| 808 | **Confirmed** | `class_id 108` is absent from policy; both CRM and demo reference it. Also no call log despite CRM showing a call (20:10, "Busy", note "ok"), no order, no follow-up. |
| 811 | **Corrected** | Not a missing value: the CRM export has **no canonical-ID column**. Identity evidence points to LEAD-801 (same `user_id`, `student_id`, mobile, email, course): proposed `SAME_CUSTOMER_PROPOSED`. Different counsellor (215 vs 204), created 11-03 vs 10-30. Both leads kept as separate opportunities. |
| Demo, no call | **Confirmed, 5 leads** | 807, 812: never called (CRM `last_call_at` NULL). 808, 809, 810: CRM shows a call, but no call log exists. |
| Callbacks | **Partly confirmed** | 6 of 12 rows have no `next_followup_at` (802, 806, 807, 808, 811, 812). LEAD-810's follow-up (11-01 10:00) is *before* its last call (11-02 12:30), so it is stale. "Overdue" needs an as-of date: decision D5. |
| Intimidated child | **Confirmed: LEAD-806** | Demo 9006: engagement 2, placed with four older kids, camera off after 15 min, asked for her mother. Educator recommends micro-batch or 1-on-1 bridge. CRM says "Child not interested", cold, no follow-up date. |

## 3. Other data-quality problems found

- **No transcripts supplied.** All 6 call-log rows name a `.txt` file; none were uploaded. Blocks Stage 3 only.
- **CRM vs orders disagree** for 801, 802, 803, 805: an order exists but CRM stage isn't payment-related. For 801, 804, 805 the order was updated after the CRM record.
- **ID gaps:** `demo_id 9011`, `order_id 99406–99408` missing from the extracts.
- **Policy internal:** class 302 USD cap "25" vs 10% × 265 = 26.5. No UK pricing. Qatar treatment unstated.
- **Naming:** CRM course names differ from policy for classes 302 (804, 812) and 105 (807). Demo `recommended_course_track` is free text, not an id.
- **Privacy:** child first names appear in free text (transcript filenames, demo observations); redacted in outputs (DQ-031…039).
- **Name format:** LEAD-812 student name has a non-ASCII lookalike character (DQ-046), which can break name matching.
- **Missing values:** `created_at` NULL for 807, 812.
- **Free-text contamination:** 807, 812 demo fields embed "HIGH INTENT … UNCALLED BY REP". Treated as unverified text.
- **Weak notes:** "ok" (808), "cb" (810).
- **Passed:** keys unique, FKs, student/class consistency across files, call log ↔ CRM agreement, talk-time sums, timeline order, age/grade bands, contact formats, no soft-deletes.

## 4. Decisions needed

| # | Decision | Default I used |
|---|---|---|
| D1 | Approve the proposed SAME_CUSTOMER_PROPOSED relationship 801 ↔ 811 | Nothing merged; both leads kept; relationship in `lead_canonical_map.csv`. |
| D2 | Supply the 6 transcript files before Stage 3 | n/a |
| D3 | LEAD-802 amount: treat AED 12,000 as entry error? | Source left unchanged; flagged. |
| D4 | Provide policy for class 108 and a UK/GBP price list; confirm Qatar uses AED | Not validated; flagged. |
| D5 | As-of date and timezone for Stage 2 overdue logic. Data ends 2026-11-03 20:45; timestamps have no timezone. | Not applied. |
| D6 | Authoritative discount cap: policy 10% vs gateway 15%; USD 25 vs 26.5 | Policy text used as reference. |
| D7 | Are 9011 and 99406–99408 real missing records? | Flagged only. |
| D8 | Approve redaction approach for free text (and whether to clean the source fields/filenames) | Redacted in outputs only; raw unchanged. |

## 5. Files

| File | Purpose |
|---|---|
| `run_stage1.py`, `s1/*.py` | Pipeline: `common`, `audit`, `canonical` (identity proposal), `privacy` (redaction), `checks`, `master` |
| `validate_stage1.py` | Post-run validation (22 checks: 12 leads once, 801/811 separate, relationship kept, no prohibited columns or personal values, raw checksums) |
| `outputs/master_leads.csv` | 12 operational leads × 64 cols: CRM + demo + call + order + policy match + identity reference + DQ issue ids. No identifiers; free text redacted |
| `outputs/data_quality_issues.csv` | 54 findings with severity, evidence, `decision_required` |
| `outputs/checks_run.csv` | All 51 checks with pass/flag |
| `outputs/data_dictionary.csv` | 83 columns: type, role, nulls, distinct, examples. Descriptions only for key/ambiguous columns |
| `outputs/lead_canonical_map.csv` | Proposed customer-identity relationships (2 rows: 801, 811), counsellor ids and creation dates retained |
| `outputs/reconciliation_lead_coverage.csv` | Per lead: demo/call/order/transcript presence |
| `outputs/reconciliation_orders.csv` | Per order: price vs policy, discount %, arithmetic, CRM stage. Descriptive, no verdicts |
| `outputs/policy_clean.csv` | Policy with parsed caps and age/grade bands |
| `outputs/run_manifest.json` | Checksums, row counts, versions |

## 6. Run

```
pip install pandas        # only dependency; tested on Python 3.12, pandas 3.0.6
python run_stage1.py      # reads data/raw, writes outputs/ (raw never modified)
python validate_stage1.py # exit code 1 on any failure
```
Options: `--raw-dir`, `--out-dir`. Output is deterministic apart from the timestamp in the manifest.

## 7. Reviewer handoff

Revision 2 complete. Master = 12 operational leads (each CRM lead exactly once); LEAD-801 and LEAD-811 remain separate with their own counsellor, creation date and stage; their `SAME_CUSTOMER_PROPOSED` relationship is kept separately and reversibly (pending approval). Prohibited identifiers are absent from the master; free text is redacted. Raw checksums are identical to the first run; policy values, payment statuses and the LEAD-802 amount are untouched. 51 checks / 54 findings (was 49 / 44): all 44 original findings retained, plus 2 new checks (privacy, name charset) and 10 new findings. One implementation defect was found and fixed (redactor ignored masked names). Validation: 22/22 pass, fresh-copy run reproduces the outputs. No Stage 2+ logic. Awaiting approval on D1–D8.
