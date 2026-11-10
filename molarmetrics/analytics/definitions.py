"""Metric definitions: the single source of truth.

The same text is shown on the dashboard, returned inside every tool result
(so the model can quote it), and printed in the About tab and README.
"""

DEFINITIONS: dict[str, str] = {
    "scheduled_appointments": (
        "All appointment records (completed, cancelled and no-show) whose appointment date "
        "falls within the selected date range."
    ),
    "completed_visits": "Appointments with status 'completed' within the selected date range.",
    "cancelled_appointments": "Appointments with status 'cancelled' within the selected date range.",
    "no_show_appointments": "Appointments with status 'no_show' within the selected date range.",
    "no_show_rate": (
        "No-show appointments divided by ALL scheduled appointments (completed + cancelled + "
        "no-show) in the same period. The denominator is always reported with the rate."
    ),
    "unique_patients_seen": "Distinct patients with at least one completed visit in the selected date range.",
    "returning_patients": (
        "Distinct patients seen in the period who had an earlier completed visit at any time before that "
        "visit, including visits before the period. A first-ever visit does not count as returning."
    ),
    "billed_revenue": (
        "Sum of treatment net fees (listed fee minus discount), filtered or grouped by the appointment "
        "(treatment) date. This is money charged, not money received."
    ),
    "collections": (
        "Sum of payments received, filtered or grouped by the payment date. This is money received, "
        "which may relate to treatments from earlier periods."
    ),
    "outstanding_balance": (
        "Net fees for treatments performed on or before the as-of date, minus payments received against "
        "those treatments on or before that date."
    ),
    "treatment_count": (
        "Number of treatment records (procedure line items). One root canal record is one SESSION, so "
        "counts are not numbers of patients, teeth or completed treatment courses."
    ),
    "patients_treated": "Distinct patients with at least one record of that procedure in the range.",
}


LABELS: dict[str, str] = {
    "scheduled_appointments": "Scheduled appointments",
    "completed_visits": "Completed visits",
    "cancelled_appointments": "Cancelled appointments",
    "no_show_appointments": "No-show appointments",
    "no_show_rate": "No-show rate",
    "unique_patients_seen": "Unique patients seen",
    "returning_patients": "Returning patients",
    "billed_revenue": "Billed revenue",
    "collections": "Collections",
    "outstanding_balance": "Outstanding balance",
    "treatment_count": "Treatment count (records)",
    "patients_treated": "Patients treated",
}


def pick(*keys: str) -> dict[str, str]:
    """Return just the definitions a result needs (keeps tool output short)."""
    return {k: DEFINITIONS[k] for k in keys}
