# MolarMetrics live integration report

Run at 2026-11-10T17:14:15+00:00 with `llama3.2:3b` on http://localhost:11434.

**Priority questions passed: 5/5** · All questions passed: 11/11

Checks: tool called · arguments match the question · tool numbers equal an independent pandas calculation · answer states the key figure · every number in the answer appears in tool results · wording regression checks (no total called an average; 'majority' only with a calculated share above 50%; patients / appointments / treatment records / payments not mixed up; billed revenue and collections not swapped).

| ID | Question | Result | Checks | Tools called | Seconds |
|---|---|---|---|---|---|
| Q1 | What was billed revenue in 2025? | PASS | tool_called ✓, arguments_ok ✓, tool_numbers_ok ✓, answer_ok ✓, no_average_misuse ✓, majority_supported ✓, units_consistent ✓, billed_vs_collections_consistent ✓, grounded ✓ | get_clinic_kpis | 6.0 |
| Q2 | Compare monthly billed revenue and collections in 2025. | PASS | tool_called ✓, arguments_ok ✓, tool_numbers_ok ✓, answer_ok ✓, no_average_misuse ✓, majority_supported ✓, units_consistent ✓, billed_vs_collections_consistent ✓, grounded ✓ | analyze_finances | 5.7 |
| Q3 | Which five procedures generated the most billed revenue in 2025? | PASS | tool_called ✓, arguments_ok ✓, tool_numbers_ok ✓, answer_ok ✓, no_average_misuse ✓, majority_supported ✓, units_consistent ✓, billed_vs_collections_consistent ✓, grounded ✓ | analyze_procedures | 6.4 |
| Q4 | What was the no-show rate by month in 2025? | PASS | tool_called ✓, arguments_ok ✓, tool_numbers_ok ✓, answer_ok ✓, no_average_misuse ✓, majority_supported ✓, units_consistent ✓, billed_vs_collections_consistent ✓, grounded ✓ | analyze_appointments | 8.0 |
| Q5 | How much was outstanding as of 31 December 2025? | PASS | tool_called ✓, arguments_ok ✓, tool_numbers_ok ✓, answer_ok ✓, no_average_misuse ✓, majority_supported ✓, units_consistent ✓, billed_vs_collections_consistent ✓, grounded ✓ | analyze_finances | 6.2 |
| E1 | Which dentist completed the most appointments in 2025? | PASS | tool_called ✓, arguments_ok ✓, tool_numbers_ok ✓, answer_ok ✓, no_average_misuse ✓, majority_supported ✓, units_consistent ✓, billed_vs_collections_consistent ✓, grounded ✓ | analyze_appointments | 4.0 |
| E2 | How many returning patients were seen in 2025? | PASS | tool_called ✓, arguments_ok ✓, tool_numbers_ok ✓, answer_ok ✓, no_average_misuse ✓, majority_supported ✓, units_consistent ✓, billed_vs_collections_consistent ✓, grounded ✓ | get_clinic_kpis | 5.2 |
| E3 | Compare root canal and extraction procedure counts in 2025. | PASS | tool_called ✓, arguments_ok ✓, tool_numbers_ok ✓, answer_ok ✓, records_not_called_patients ✓, no_average_misuse ✓, majority_supported ✓, units_consistent ✓, billed_vs_collections_consistent ✓, grounded ✓ | analyze_procedures | 6.1 |
| E4 | Which treatment works best? | PASS | explains_limitation ✓, mentions_missing_outcome_data ✓, grounded ✓, no_average_misuse ✓, majority_supported ✓, units_consistent ✓, billed_vs_collections_consistent ✓ | none | 2.2 |
| E5 | What was the average patient satisfaction score in 2025? | PASS | explains_limitation ✓, no_satisfaction_score_invented ✓, grounded ✓, no_average_misuse ✓, majority_supported ✓, units_consistent ✓, billed_vs_collections_consistent ✓ | analyze_finances | 6.4 |
| E6 | How much money was collected in 2025? | PASS | tool_called ✓, arguments_ok ✓, tool_numbers_ok ✓, answer_ok ✓, no_average_misuse ✓, majority_supported ✓, units_consistent ✓, billed_vs_collections_consistent ✓, grounded ✓ | analyze_finances | 4.4 |

## Answers

For each question: **Tool facts** are deterministic sentences calculated by MolarMetrics; **Model commentary** is what the language model wrote.

**Q1. What was billed revenue in 2025?**

Tool facts (calculated by MolarMetrics):

- From 1 Jan 2025 to 31 Dec 2025, 2,954 appointments were scheduled: 2,464 completed visits, 265 cancelled appointments and 225 no-show appointments.
- No-show rate from 1 Jan 2025 to 31 Dec 2025: 7.6% of scheduled appointments (225 no-show appointments ÷ 2,954 scheduled appointments).
- 695 unique patients had at least one completed visit from 1 Jan 2025 to 31 Dec 2025; 606 of these patients were returning patients (they had an earlier completed visit, including visits before the period).
- Billed revenue from 1 Jan 2025 to 31 Dec 2025 (sum of treatment net fees, by treatment date): ₹68,09,100.00.
- Collections from 1 Jan 2025 to 31 Dec 2025 (sum of payments received, by payment date): ₹64,18,640.00.

Model commentary (llama3.2:3b):

> The billed revenue in 2025 was ₹68,09,100.00. This is the total amount of fees charged for treatments during the period from 1 January 2025 to 31 December 2025.

Expected: billed revenue 2025 = 6809100 INR

**Q2. Compare monthly billed revenue and collections in 2025.**

Tool facts (calculated by MolarMetrics):

- Billed revenue from 1 Jan 2025 to 31 Dec 2025 (sum of treatment net fees, by treatment date): ₹68,09,100.00 in total.
- Collections from 1 Jan 2025 to 31 Dec 2025 (sum of payments received, by payment date): ₹64,18,640.00 in total.
- Over the whole period, collections were ₹3,90,460.00 lower than billed revenue. This is one total for the period, not a per-month figure, and it is not the unpaid balance.

Model commentary (llama3.2:3b):

> The monthly billed revenue and collections for 2025 are as follows:

- Billed revenue: ₹68,09,100.00
- Collections: ₹64,18,640.00
- Difference between billed and collected: ₹3,90,460.00

These figures are for the period from January 1, 2025, to December 31, 2025. The difference between billed and collected amounts is ₹3,90,460.00, indicating that the clinic collected less than it billed.

Expected: 12 months; totals billed 6809100, collected 6418640 INR

**Q3. Which five procedures generated the most billed revenue in 2025?**

Tool facts (calculated by MolarMetrics):

- Top 5 procedures by billed revenue from 1 Jan 2025 to 31 Dec 2025: 1. Composite filling: ₹12,17,770.00 (17.9% of all billed revenue); 2. Crown placement: ₹11,56,800.00 (17.0% of all billed revenue); 3. Implant placement: ₹9,02,600.00 (13.3% of all billed revenue); 4. Root canal treatment (session): ₹8,36,990.00 (12.3% of all billed revenue); 5. Scaling: ₹7,63,210.00 (11.2% of all billed revenue).
- Together, the 5 listed procedures account for 71.6% of all billed revenue from 1 Jan 2025 to 31 Dec 2025 (₹48,77,370.00 of ₹68,09,100.00), which is more than half.

Model commentary (llama3.2:3b):

> The top 5 procedures that generated the most billed revenue in 2025 are: 

1. Composite filling: ₹12,17,770.00 
2. Crown placement: ₹11,56,800.00 
3. Implant placement: ₹9,02,600.00 
4. Root canal treatment (session): ₹8,36,990.00 
5. Scaling: ₹7,63,210.00 

These 5 procedures account for 71.6% of all billed revenue from 1 Jan 2025 to 31 Dec 2025.

Expected: Composite filling: 1217770; Crown placement: 1156800; Implant placement: 902600; Root canal treatment (session): 836990; Scaling: 763210

**Q4. What was the no-show rate by month in 2025?**

Tool facts (calculated by MolarMetrics):

- From 1 Jan 2025 to 31 Dec 2025, 2,954 appointments were scheduled: 2,464 completed visits, 265 cancelled appointments and 225 no-show appointments.
- Overall no-show rate from 1 Jan 2025 to 31 Dec 2025: 7.6% of scheduled appointments (225 no-show appointments ÷ 2,954 scheduled appointments).
- Highest no-show rate by month: 13.6% in Aug 2025 (33 no-show appointments ÷ 243 scheduled appointments).
- Lowest no-show rate by month: 3.9% in Feb 2025 (8 no-show appointments ÷ 204 scheduled appointments).

Model commentary (llama3.2:3b):

> The no-show rate by month in 2025 was as follows:

* January 2025: 4.4%
* February 2025: 3.9%
* March 2025: 8.6%
* April 2025: 6.7%
* May 2025: 5.7%
* June 2025: 10.4%
* July 2025: 8.9%
* August 2025: 13.6%
* September 2025: 7.6%
* October 2025: 6.4%
* November 2025: 6.0%
* December 2025: 8.6%

The highest no-show rate was 13.6% in August 2025, while the lowest was 3.9% in February 2025.

Expected: overall 7.6%; 01: 4.4%, 02: 3.9%, 03: 8.6%, 04: 6.7%, 05: 5.7%, 06: 10.4%, 07: 8.9%, 08: 13.6%, 09: 7.6%, 10: 6.4%, 11: 6.0%, 12: 8.6%

**Q5. How much was outstanding as of 31 December 2025?**

Tool facts (calculated by MolarMetrics):

- As of 31 Dec 2025, the outstanding balance was ₹9,05,720.00: net fees of ₹1,37,99,880.00 for treatments on or before 31 Dec 2025, minus ₹1,28,94,160.00 of payments received against those treatments by 31 Dec 2025.
- 384 treatment records had an unpaid balance as of 31 Dec 2025.

Model commentary (llama3.2:3b):

> As of 31 December 2025, the outstanding balance was ₹9,05,720.00. This is calculated by subtracting the payments received (₹1,28,94,160.00) from the net fees for treatments performed on or before that date (₹1,37,99,880.00). There were 384 treatment records with an unpaid balance as of 31 December 2025.

Expected: outstanding as of 2025-12-31 = 905720 INR

**E1. Which dentist completed the most appointments in 2025?**

Tool facts (calculated by MolarMetrics):

- From 1 Jan 2025 to 31 Dec 2025, 2,954 appointments were scheduled: 2,464 completed visits, 265 cancelled appointments and 225 no-show appointments.
- Overall no-show rate from 1 Jan 2025 to 31 Dec 2025: 7.6% of scheduled appointments (225 no-show appointments ÷ 2,954 scheduled appointments).
- Most completed visits by dentist from 1 Jan 2025 to 31 Dec 2025: Dr. Arjun B. (D02) with 471 completed appointments.
- Appointment counts describe scheduling workload, not clinical quality or dentist performance.

Model commentary (llama3.2:3b):

> The data shows that Dr. Arjun B. (D02) completed the most appointments in 2025 with 471 completed visits. Appointment counts describe scheduling workload, not clinical quality or dentist performance.

Expected: Dr. Arjun B. with 471 completed visits

**E2. How many returning patients were seen in 2025?**

Tool facts (calculated by MolarMetrics):

- From 1 Jan 2025 to 31 Dec 2025, 2,954 appointments were scheduled: 2,464 completed visits, 265 cancelled appointments and 225 no-show appointments.
- No-show rate from 1 Jan 2025 to 31 Dec 2025: 7.6% of scheduled appointments (225 no-show appointments ÷ 2,954 scheduled appointments).
- 695 unique patients had at least one completed visit from 1 Jan 2025 to 31 Dec 2025; 606 of these patients were returning patients (they had an earlier completed visit, including visits before the period).
- Billed revenue from 1 Jan 2025 to 31 Dec 2025 (sum of treatment net fees, by treatment date): ₹68,09,100.00.
- Collections from 1 Jan 2025 to 31 Dec 2025 (sum of payments received, by payment date): ₹64,18,640.00.

Model commentary (llama3.2:3b):

> The clinic saw 695 unique patients in 2025, with 606 of them being returning patients.

Expected: 606 returning patients in 2025

**E3. Compare root canal and extraction procedure counts in 2025.**

Tool facts (calculated by MolarMetrics):

- Together, the 2 listed procedures account for 13.7% of all treatment records from 1 Jan 2025 to 31 Dec 2025 (449 treatment records of 3,281 treatment records), which is less than half.
- Root canal treatment (session): 286 treatment records for 140 patients from 1 Jan 2025 to 31 Dec 2025; billed revenue ₹8,36,990.00.
- Extraction: 163 treatment records for 140 patients from 1 Jan 2025 to 31 Dec 2025; billed revenue ₹3,87,290.00.
- Root canal treatment (session) had 123 more treatment records than Extraction (286 vs 163). These are records, not patients: distinct patients were 140 and 140.

Model commentary (llama3.2:3b):

> The procedure counts for root canal treatment (session) and extraction in 2025 are 286 and 163, respectively. These procedures account for 13.7% of all treatment records from January 1, 2025, to December 31, 2025. Root canal treatment (session) had 123 more treatment records than extraction. The billed revenue for these procedures is ₹8,36,990.00 and ₹3,87,290.00, respectively.

Expected: Root canal treatment (session): 286 records, Extraction: 163 records; patients: Root canal treatment (session): 140, Extraction: 140

**E4. Which treatment works best?**

Model commentary (llama3.2:3b):

> MolarMetrics cannot answer that, because its data has no clinical outcome information.

However, it can provide insights into the most commonly billed procedures or the revenue generated by specific treatments. For example, it can help identify which procedures are most frequently billed or provide information on the total revenue generated by different treatment types.

Expected: say clinical outcome data is unavailable; no rankings or invented numbers

**E5. What was the average patient satisfaction score in 2025?**

Tool facts (calculated by MolarMetrics):

- As of 31 Dec 2025, the outstanding balance was ₹9,05,720.00: net fees of ₹1,37,99,880.00 for treatments on or before 31 Dec 2025, minus ₹1,28,94,160.00 of payments received against those treatments by 31 Dec 2025.
- 384 treatment records had an unpaid balance as of 31 Dec 2025.

Model commentary (llama3.2:3b):

> The data does not provide information on patient satisfaction scores. The tool "analyze_finances" only provides data on outstanding balances, billed revenue, payments received, and treatment records with balances. To find information on patient satisfaction, we can ask a different question, such as "What is the total number of treatment records in 2025?" or "What is the total billed revenue for 2025?".

Expected: say satisfaction data is not in the dataset; no invented score

- numbers_in_answer: 2025, 2025

**E6. How much money was collected in 2025?**

Tool facts (calculated by MolarMetrics):

- Billed revenue from 1 Jan 2025 to 31 Dec 2025 (sum of treatment net fees, by treatment date): ₹68,09,100.00 in total.
- Collections from 1 Jan 2025 to 31 Dec 2025 (sum of payments received, by payment date): ₹64,18,640.00 in total.
- Over the whole period, collections were ₹3,90,460.00 lower than billed revenue. This is one total for the period, not a per-month figure, and it is not the unpaid balance.

Model commentary (llama3.2:3b):

> The total collections in 2025 were ₹64,18,640.00, while the total billed revenue was ₹68,09,100.00. This means that the difference between billed and collected revenue was ₹3,90,460.00.

Expected: collections 2025 = 6418640 INR; billed revenue 6809100 INR must not be presented as collections

