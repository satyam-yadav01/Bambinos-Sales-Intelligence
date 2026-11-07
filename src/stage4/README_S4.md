# Stage 4: Sales Intelligence System Integration

## Overview
This builds the final `sales_intelligence_summary.csv` aggregating deterministic payment, policy, and followup logic (Stage 2) with offline conversational intelligence (Stage 3).

## Limitations
The conversational intelligence uses draft offline annotations. It does not measure live LLM precision or extraction accuracy. Stage 2 retains complete authority over automation policies, payment records, and identity overlaps.

## Execution Instructions
From the project root:
1. Ensure `master_leads_2.csv` (the revised 12-row file), `reconciliation_orders.csv`, and `policy_clean.csv` exist in the root directory.
2. Run the integration script (optionally specifying an as-of-date for testing chronological logic):
   `python s4_integration.py --as-of-date 2026-11-06`
3. Verify output structural integrity:
   `python test_s4_integration.py`

*Note: All outputs are securely deposited in the `s4/` directory.*