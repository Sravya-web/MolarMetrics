"""What MolarMetrics can import: five record types and their fields.

Beginner note
-------------
Every clinic exports data differently, so an upload is MAPPED onto these
fixed record types. Each field says whether it is required, what kind of value
it holds, and which column headers usually mean it (used only to SUGGEST a
mapping; the user confirms or corrects every suggestion).

Only these fields are ever stored. Any other column in an uploaded file
(patient names, phone numbers, notes…) is ignored and never saved.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

FieldKind = Literal["id", "ref", "date", "time", "money", "text", "status"]
RecordType = Literal["appointments", "treatments", "payments", "patients", "dentists"]


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    kind: FieldKind
    required: bool
    description: str
    synonyms: tuple[str, ...] = ()
    references: str | None = None  # record type an ID refers to (for kind "ref")


@dataclass(frozen=True)
class RecordSpec:
    key: RecordType
    label: str
    one_row: str  # what ONE row of this file represents
    purpose: str  # what this file adds to the analysis
    id_field: str
    fields: tuple[FieldSpec, ...]
    filename_hints: tuple[str, ...]
    depends_on: RecordType | None = None
    has_money: bool = False
    # Example rows for the downloadable template (canonical formats).
    template_rows: tuple[tuple[str, ...], ...] = ()

    def field(self, key: str) -> FieldSpec:
        return next(f for f in self.fields if f.key == key)

    @property
    def required_fields(self) -> list[FieldSpec]:
        return [f for f in self.fields if f.required]


APPOINTMENTS = RecordSpec(
    key="appointments",
    label="Appointments",
    one_row="One booked appointment: a visit slot that was completed, cancelled or missed (no-show).",
    purpose="Needed for every import. Gives completed visits, no-show rates and patient counts.",
    id_field="appointment_id",
    filename_hints=("appointment", "appointments", "appt", "visit", "visits", "booking", "bookings", "schedule"),
    fields=(
        FieldSpec("appointment_id", "Appointment ID", "id", True, "A unique code for each appointment.",
                  ("appointment id", "appointment no", "appointment number", "appt id", "appt no", "booking id",
                   "visit id", "appointment code", "appointment ref", "booking ref", "booking reference",
                   "appointment reference")),
        FieldSpec("patient_id", "Patient ID", "ref", True, "The patient's code (not their name).",
                  ("patient id", "patient code", "patient no", "patient number", "patient ref", "uhid", "mrn",
                   "pid", "patient"), references="patients"),
        FieldSpec("appointment_date", "Appointment date", "date", True,
                  "The appointment's date (a time can be included).",
                  ("appointment date", "visit date", "date", "appointment datetime", "appointment date time",
                   "date of visit", "appt date", "scheduled date", "booking date", "date time", "datetime",
                   "scheduled on", "slot date")),
        FieldSpec("status", "Appointment status", "status", True,
                  "Whether the visit was completed, cancelled or a no-show.",
                  ("status", "appointment status", "visit status", "outcome", "attendance", "appt status")),
        FieldSpec("appointment_time", "Appointment time", "time", False, "The start time, if it is in a separate "
                  "column.", ("appointment time", "time", "visit time", "slot time", "start time", "slot")),
        FieldSpec("dentist_id", "Dentist ID", "ref", False, "The dentist's code. Enables results by dentist.",
                  ("dentist id", "doctor id", "dentist code", "doctor code", "provider id", "clinician id",
                   "dentist", "doctor", "provider"), references="dentists"),
    ),
    template_rows=(
        ("A1001", "P501", "2025-01-06", "completed", "10:30", "D1"),
        ("A1002", "P502", "2025-01-06", "no-show", "11:00", "D2"),
    ),
)

TREATMENTS = RecordSpec(
    key="treatments",
    label="Treatments",
    one_row="One procedure billed at one appointment (a line item). A visit with two procedures has two rows.",
    purpose="Adds billed revenue and top procedures. Needs an appointments file.",
    id_field="treatment_id",
    depends_on="appointments",
    has_money=True,
    filename_hints=("treatment", "treatments", "procedure", "procedures", "billing", "invoice", "invoices",
                    "charges", "services"),
    fields=(
        FieldSpec("treatment_id", "Treatment ID", "id", True, "A unique code for each procedure line.",
                  ("treatment id", "treatment no", "line id", "item id", "procedure id", "invoice line id",
                   "treatment code", "line no", "bill item id")),
        FieldSpec("appointment_id", "Appointment ID", "ref", True, "The appointment this procedure was done at.",
                  ("appointment id", "appointment no", "appt id", "visit id", "booking id", "appointment"),
                  references="appointments"),
        FieldSpec("procedure", "Procedure", "text", True, "The procedure's name, e.g. Scaling.",
                  ("procedure", "procedure name", "treatment", "treatment name", "service", "service name",
                   "item", "description", "treatment type")),
        FieldSpec("net_fee", "Net fee", "money", False,
                  "The amount charged after any discount. Map this or the listed fee.",
                  ("net fee", "net amount", "net", "amount billed", "billed amount", "final fee", "payable",
                   "net fee inr", "net fee paise", "total", "amount", "fee after discount", "billed")),
        FieldSpec("listed_fee", "Listed fee", "money", False, "The fee before any discount.",
                  ("listed fee", "fee", "gross fee", "price", "charge", "list price", "rate", "gross amount",
                   "listed fee inr", "listed fee paise", "standard fee")),
        FieldSpec("discount", "Discount", "money", False, "The discount given, if any (0 for none).",
                  ("discount", "discount amount", "concession", "waiver", "discount inr", "discount paise")),
    ),
    template_rows=(
        ("T5001", "A1001", "Scaling", "1500.00", "1500.00", "0.00"),
        ("T5002", "A1001", "Composite filling", "2000.00", "2200.00", "200.00"),
    ),
)

PAYMENTS = RecordSpec(
    key="payments",
    label="Payments",
    one_row="One payment received against one treatment. A treatment paid in instalments has several rows.",
    purpose="Adds collections and outstanding balances. Needs a treatments file.",
    id_field="payment_id",
    depends_on="treatments",
    has_money=True,
    filename_hints=("payment", "payments", "receipt", "receipts", "collection", "collections", "transactions"),
    fields=(
        FieldSpec("payment_id", "Payment ID", "id", True, "A unique code for each payment.",
                  ("payment id", "receipt id", "receipt no", "receipt number", "transaction id", "payment no",
                   "payment ref", "txn id")),
        FieldSpec("treatment_id", "Treatment ID", "ref", True, "The treatment this payment is for.",
                  ("treatment id", "treatment no", "line id", "item id", "treatment"), references="treatments"),
        FieldSpec("payment_date", "Payment date", "date", True, "The date the money was received.",
                  ("payment date", "date", "paid on", "receipt date", "transaction date", "date paid",
                   "payment datetime")),
        FieldSpec("amount", "Amount paid", "money", True, "The amount received.",
                  ("amount", "amount paid", "paid amount", "payment amount", "received", "amount received",
                   "amount inr", "amount paise", "paid")),
        FieldSpec("payment_method", "Payment method", "text", False, "e.g. UPI, cash or card.",
                  ("payment method", "method", "mode", "payment mode", "payment type", "tender")),
    ),
    template_rows=(
        ("PM9001", "T5001", "2025-01-06", "1500.00", "UPI"),
        ("PM9002", "T5002", "2025-01-20", "1000.00", "Cash"),
    ),
)

PATIENTS = RecordSpec(
    key="patients",
    label="Patients",
    one_row="One registered patient, identified by a code. Do not include names or contact details.",
    purpose="Optional. Lets MolarMetrics check that every appointment's patient code exists.",
    id_field="patient_id",
    filename_hints=("patient", "patients", "registrations", "register"),
    fields=(
        FieldSpec("patient_id", "Patient ID", "id", True, "The patient's code (not their name).",
                  ("patient id", "patient code", "patient no", "patient number", "uhid", "mrn", "pid", "id")),
        FieldSpec("registration_date", "Registration date", "date", False, "When the patient registered.",
                  ("registration date", "registered on", "date registered", "reg date", "created on",
                   "registration")),
    ),
    template_rows=(("P501", "2024-11-02"), ("P502", "2025-01-03")),
)

DENTISTS = RecordSpec(
    key="dentists",
    label="Dentists",
    one_row="One dentist at the clinic.",
    purpose="Optional. Shows dentist names instead of codes and checks every appointment's dentist code.",
    id_field="dentist_id",
    filename_hints=("dentist", "dentists", "doctor", "doctors", "provider", "providers", "staff", "clinicians"),
    fields=(
        FieldSpec("dentist_id", "Dentist ID", "id", True, "The dentist's code.",
                  ("dentist id", "doctor id", "dentist code", "doctor code", "provider id", "id")),
        FieldSpec("dentist_name", "Dentist name", "text", False, "The name to show in results.",
                  ("dentist name", "doctor name", "name", "display name", "dentist", "doctor", "provider name")),
        FieldSpec("specialty", "Specialty", "text", False, "e.g. General dentistry.",
                  ("specialty", "speciality", "specialization", "specialisation", "department")),
    ),
    template_rows=(("D1", "Dr. A. Rao", "General dentistry"), ("D2", "Dr. M. Iyer", "Endodontics")),
)

RECORD_SPECS: dict[str, RecordSpec] = {s.key: s for s in (APPOINTMENTS, TREATMENTS, PAYMENTS, PATIENTS, DENTISTS)}
RECORD_ORDER = ("appointments", "treatments", "payments", "patients", "dentists")

# Appointment statuses MolarMetrics understands, and labels that usually mean them.
STATUS_VALUES = ("completed", "cancelled", "no_show")
STATUS_LABELS = {"completed": "Completed", "cancelled": "Cancelled", "no_show": "No-show"}
STATUS_SYNONYMS: dict[str, tuple[str, ...]] = {
    "completed": ("completed", "complete", "done", "attended", "seen", "visited", "checked out", "checkedout",
                  "arrived", "fulfilled", "finished", "treated", "closed"),
    "cancelled": ("cancelled", "canceled", "cancel", "cancellation", "cancelled by patient", "canceled by patient",
                  "cancelled by clinic", "canceled by clinic", "patient cancelled", "clinic cancelled",
                  "patient canceled", "clinic canceled"),
    "no_show": ("no show", "noshow", "no shows", "dna", "did not attend", "did not arrive", "missed", "absent",
                "failed to attend", "not attended", "no showed", "didnt attend", "didn t attend"),
}
