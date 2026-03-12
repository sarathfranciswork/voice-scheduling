"""
CVS Vaccine Scheduling MCP Server

Exposes CVS scheduling API wrappers as MCP tools for AI assistant integration.
Runs as a standalone HTTP service using FastMCP with Streamable HTTP transport.

Usage:
    python -m mcp_server.server
    # or
    fastmcp run mcp_server/server.py --transport http --port 8001
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastmcp import FastMCP

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cvs_api.client import CVSClient
from cvs_api.exceptions import AuthenticationError, CVSAPIError, NoAvailabilityError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def _lifespan(server: FastMCP) -> AsyncIterator[None]:
    """Bootstrap the CVS guest session at server startup (in background)."""
    async def _warmup():
        try:
            await _get_client()
            logger.info("CVS client warmed up at startup")
        except Exception as e:
            logger.warning("Startup warmup failed (will retry on first tool call): %s", e)

    task = asyncio.create_task(_warmup())
    yield
    task.cancel()


mcp = FastMCP(
    name="CVS Vaccine Scheduling",
    lifespan=_lifespan,
    instructions=(
        "You are an assistant that helps users schedule vaccine appointments at CVS pharmacies. "
        "You support both GUEST and AUTHENTICATED flows.\n\n"
        "== GUEST SCHEDULING FLOW (default) ==\n"
        "1. get_eligible_vaccines - Check which vaccines the patient can receive (requires DOB)\n"
        "2. check_vaccine_eligibility - Get NDC codes for selected vaccines (requires DOB + vaccine codes). "
        "   The server automatically caches this response.\n"
        "3. search_stores - Find nearby CVS pharmacies (requires address). "
        "   The server automatically uses the cached eligibility data and caches store results.\n"
        "4. get_available_time_slots - Get appointment times for a specific date (requires ONLY visit_date). "
        "   The server automatically uses cached eligibility + store data.\n"
        "5. soft_reserve_slot - Hold the selected time slot\n"
        "6. submit_patient_details - Provide patient demographics\n"
        "7. get_questionnaire - Retrieve health screening questions\n"
        "8. submit_questionnaire - Submit questionnaire answers\n"
        "9. confirm_appointment - Final confirmation\n\n"
        "== AUTHENTICATED FLOW (when user wants to log in, view or cancel appointments) ==\n"
        "CVS supports two login methods:\n"
        "  A. OTP (default): login_to_cvs(email) → verify_otp(code) → verify_dob(m,d,y)\n"
        "  B. Password: login_to_cvs(email, password) → authenticated directly\n\n"
        "Tools:\n"
        "1. login_to_cvs - Start login with email (+ optional password)\n"
        "2. verify_otp - Submit the 6-digit SMS code (OTP flow only)\n"
        "3. verify_dob - Enter date of birth (OTP flow only, auto-verifies if DOB cached)\n"
        "4. get_patient_profile - View profile details (name, DOB, email, phone)\n"
        "5. get_my_appointments - List upcoming appointments\n"
        "6. cancel_appointment - Cancel a specific appointment by appointmentId\n"
        "7. logout - Sign out the current user\n\n"
        "IMPORTANT: Steps 2-4 of the guest flow automatically chain data between them. "
        "You do NOT need to pass large JSON responses between tool calls.\n\n"
        "After authenticated login, the patient's DOB is auto-cached from their profile, "
        "so you can skip asking for DOB if scheduling after login."
    ),
)

_client: CVSClient | None = None

# Server-side cache for large inter-step payloads so the LLM doesn't have to
# carry tens of KB of JSON as tool parameters between calls.
_session_cache: dict[str, Any] = {
    "date_of_birth": None,
    "vaccine_codes": None,
    "vaccine_eligibility_data": None,
    "store_search_results": None,
    # Authenticated user state
    "authenticated": False,
    "patient_profile": None,
    "appointments": None,
}


async def _get_client() -> CVSClient:
    global _client
    if _client is None:
        logger.info("Initializing CVS client with auto-bootstrap...")
        _client = CVSClient(auto_bootstrap=True)
        await _client.__aenter__()
        logger.info("CVS client initialized and bootstrapped")
    return _client


async def _ensure_session() -> CVSClient:
    """Get client and refresh session if token is expired."""
    client = await _get_client()
    if not client._session.token_valid:
        logger.info("CVS session expired, refreshing...")
        refreshed = await client.refresh_session()
        if not refreshed:
            logger.warning("Session refresh failed -- API calls may fail")
    return client


def _find_clinic(store_data: dict, clinic_id: str) -> dict | None:
    """Find a clinic by ID in the cached store search results."""
    for c in store_data.get("listOfClinics", []):
        if c.get("clinicId") == clinic_id:
            return c
    return None


def _extract_vaccine_info_for_clinic(clinic: dict) -> list[dict]:
    """Extract vaccine NDC/manufacturer info from a clinic's additionalData."""
    vaccine_codes = _session_cache.get("vaccine_codes", [])
    additional = clinic.get("additionalData", [])
    if not additional:
        return [{"code": c, "ndc": [], "type": c, "doseType": "STANDARD",
                 "manufacturers": "", "isInvConstraint": False, "lastDoseDate": None}
                for c in vaccine_codes]

    patient_data = additional[0].get("patients", [])
    if not patient_data:
        return []

    result = []
    for vax in patient_data[0].get("vaccines", []):
        if vax.get("code") in vaccine_codes:
            ndc_list = []
            manufacturers = set()
            for n in vax.get("ndc", []):
                ndc_list.append({
                    "id": n.get("id"),
                    "name": n.get("name"),
                    "reasonId": n.get("reasonId"),
                    "reasonMappingId": n.get("reasonMappingId"),
                    "subCategoryIMS": n.get("subCategoryIMS"),
                    "subCategoryMC": n.get("subCategoryMC"),
                })
                if n.get("manufacturer"):
                    manufacturers.add(n["manufacturer"])
            result.append({
                "code": vax.get("code"),
                "ndc": ndc_list,
                "type": vax.get("type", vax.get("code")),
                "doseType": vax.get("doseType", "STANDARD"),
                "manufacturers": ", ".join(manufacturers),
                "isInvConstraint": vax.get("isInvConstraint", False),
                "lastDoseDate": vax.get("lastDoseDate"),
            })
    return result


# ---------------------------------------------------------------------------
# Vaccine eligibility tools
# ---------------------------------------------------------------------------


@mcp.tool
async def refresh_session() -> str:
    """
    Refresh the CVS API session by re-bootstrapping the browser session.
    Use this if other tools are returning authentication errors.

    Returns:
        Status message indicating whether the session was refreshed successfully.
    """
    try:
        client = await _get_client()
        success = await client.refresh_session()
        if success:
            return "Session refreshed successfully. You can now retry the previous operation."
        return "Session refresh failed. The CVS API may be temporarily unavailable."
    except Exception as e:
        return f"Error refreshing session: {e}"


@mcp.tool
async def get_eligible_vaccines(date_of_birth: str) -> str:
    """
    Get the list of vaccines a patient is eligible for based on their date of birth.
    This should be the FIRST step in the scheduling flow.

    Args:
        date_of_birth: Patient date of birth in YYYY-MM-DD format (e.g. "1990-05-15").

    Returns:
        JSON with eligible vaccine codes, names, and NDC information.
    """
    try:
        client = await _ensure_session()
        result = await client.get_eligible_vaccines(date_of_birth=date_of_birth)
        return json.dumps(result, indent=2, default=str)
    except CVSAPIError as e:
        return f"Error: {e}"


@mcp.tool
async def check_vaccine_eligibility(date_of_birth: str, vaccine_codes: list[str]) -> str:
    """
    Check detailed vaccine eligibility and get NDC codes needed for store search.
    MUST be called AFTER get_eligible_vaccines and BEFORE search_stores.
    The response is automatically cached for use by subsequent tools.

    Args:
        date_of_birth: Patient date of birth in YYYY-MM-DD format (e.g. "1990-05-15").
        vaccine_codes: List of vaccine codes the patient selected (e.g. ["FLU", "CVD"]).
                       Use codes from the get_eligible_vaccines response.

    Returns:
        JSON with NDC codes, manufacturers, scheduling date range, and eligibility status.
    """
    try:
        client = await _ensure_session()
        eligibility_input = {
            "vaccineDataInput": [{
                "patientReferenceId": "P1",
                "dateOfBirth": date_of_birth,
                "vaccines": [{"code": code} for code in vaccine_codes],
            }]
        }
        result = await client.check_vaccine_eligibility(eligibility_input)

        _session_cache["date_of_birth"] = date_of_birth
        _session_cache["vaccine_codes"] = vaccine_codes
        _session_cache["vaccine_eligibility_data"] = result
        logger.info("Cached vaccine_eligibility_data (%d bytes)", len(json.dumps(result, default=str)))

        return json.dumps(result, indent=2, default=str)
    except CVSAPIError as e:
        return f"Error: {e}"


# ---------------------------------------------------------------------------
# Store search & time slot tools
# ---------------------------------------------------------------------------


@mcp.tool
async def search_stores(
    address: str,
    radius: int = 35,
    max_results: int = 10,
) -> str:
    """
    Search for CVS pharmacy locations that have vaccine availability near a location.
    MUST be called AFTER check_vaccine_eligibility (which caches required data automatically).

    Args:
        address: Location to search near. Can be ZIP code (e.g. "02101"),
                 "ZIP, STATE" (e.g. "37135, TN"), or "City, STATE" (e.g. "Boston, MA").
        radius: Search radius in miles (default 35).
        max_results: Maximum number of stores to return (default 10).

    Returns:
        JSON with list of clinics including addresses, distances, and available dates.
    """
    eligibility_data = _session_cache.get("vaccine_eligibility_data")
    dob = _session_cache.get("date_of_birth")
    vaccine_codes = _session_cache.get("vaccine_codes")

    if not eligibility_data or not dob or not vaccine_codes:
        return "Error: You must call check_vaccine_eligibility first before searching stores."

    try:
        client = await _ensure_session()
        result = await client.search_stores(
            address=address,
            date_of_birth=dob,
            vaccine_eligibility_data=eligibility_data,
            vaccine_codes=vaccine_codes,
            radius=radius,
            max_results=max_results,
        )

        _session_cache["store_search_results"] = result
        logger.info("Cached store_search_results (%d clinics)", len(result.get("listOfClinics", [])))

        clinics = result.get("listOfClinics", [])
        summary = []
        for c in clinics[:max_results]:
            addr = c.get("address", {})
            avail_dates = c.get("availableDates", [])
            summary.append({
                "clinicId": c.get("clinicId"),
                "clinicName": c.get("clinicName", "CVS Pharmacy"),
                "lobType": c.get("lobType"),
                "distance": c.get("distance"),
                "address": f"{addr.get('street', '')}, {addr.get('city', '')}, {addr.get('state', '')} {addr.get('zip', '')}".strip(", "),
                "availableDates": avail_dates[:7],
                "totalAvailableDates": len(avail_dates),
            })
        return json.dumps({"stores": summary, "totalFound": len(clinics)}, indent=2, default=str)
    except NoAvailabilityError as e:
        return f"No stores found: {e}"
    except CVSAPIError as e:
        return f"Error: {e}"


@mcp.tool
async def get_available_time_slots(
    visit_date: str,
    clinic_id: str = "",
) -> str:
    """
    Get available appointment time slots at CVS pharmacies for a given date.
    MUST be called AFTER search_stores (which caches required data automatically).

    Args:
        visit_date: Date for the appointment in YYYY-MM-DD format (e.g. "2026-02-24").
                    Must be one of the dates from the store's availableDates list.
        clinic_id: Optional specific clinic ID to filter results for.
                   If empty, returns slots for all stores from the previous search.

    Returns:
        JSON with available time slots for each clinic with morning/afternoon/evening arrays.
    """
    store_data = _session_cache.get("store_search_results")
    eligibility_data = _session_cache.get("vaccine_eligibility_data")
    dob = _session_cache.get("date_of_birth")
    vaccine_codes = _session_cache.get("vaccine_codes")

    if not store_data or not eligibility_data or not dob:
        return "Error: You must call check_vaccine_eligibility and search_stores first."

    try:
        client = await _ensure_session()
        result = await client.get_available_time_slots(
            visit_date=visit_date,
            date_of_birth=dob,
            vaccine_codes=vaccine_codes,
            store_search_results=store_data,
            vaccine_eligibility_data=eligibility_data,
        )

        # Build a concise summary for the LLM
        all_slots = result.get("availableTimeslotsResponse", [])
        summary = []
        for entry in all_slots:
            cid = entry.get("clinicId", "")
            if clinic_id and cid != clinic_id:
                continue
            details = entry.get("slotDetails", [])
            for slot_day in details:
                morning = slot_day.get("morning", [])
                afternoon = slot_day.get("afternoon", [])
                evening = slot_day.get("evening", [])
                if morning or afternoon or evening:
                    summary.append({
                        "clinicId": cid,
                        "visitDate": slot_day.get("visitDate", visit_date),
                        "morning": morning,
                        "afternoon": afternoon,
                        "evening": evening,
                    })
        if not summary:
            return f"No time slots available for {visit_date}. Try a different date from the store's availableDates list."
        return json.dumps({"timeSlots": summary}, indent=2, default=str)
    except NoAvailabilityError as e:
        return f"No time slots available: {e}"
    except CVSAPIError as e:
        return f"Error: {e}"


@mcp.tool
async def get_store_details(store_id: str) -> str:
    """
    Get detailed information about a specific CVS pharmacy including
    full address, phone numbers, operating hours, and services.

    Args:
        store_id: CVS store identifier.
    """
    try:
        client = await _ensure_session()
        result = await client.get_store_details(store_id)
        return json.dumps(result, indent=2, default=str)
    except CVSAPIError as e:
        return f"Error: {e}"


# ---------------------------------------------------------------------------
# Scheduling workflow tools
# ---------------------------------------------------------------------------


@mcp.tool
async def soft_reserve_slot(
    clinic_id: str,
    appointment_date: str,
    appointment_time: str,
) -> str:
    """
    Temporarily reserve a time slot while the patient completes registration.
    MUST be called AFTER get_available_time_slots. The server uses cached data
    to construct the full reservation payload automatically.

    Args:
        clinic_id: The clinicId from the store search results (e.g. "CVS_06414" or "761").
        appointment_date: Date in YYYY-MM-DD format (e.g. "2026-02-24").
        appointment_time: Time slot string exactly as returned by get_available_time_slots
                         (e.g. "10:45 AM", "5:00 PM").

    Returns:
        JSON with reservation confirmation including reservationCode and expiryTime.
    """
    store_data = _session_cache.get("store_search_results")
    dob = _session_cache.get("date_of_birth")
    if not store_data or not dob:
        return "Error: You must complete steps 1-4 (eligibility, store search, time slots) before reserving."

    clinic = _find_clinic(store_data, clinic_id)
    if not clinic:
        return f"Error: Clinic '{clinic_id}' not found in the previous store search results."

    addr = clinic.get("address", {})
    vaccine_info = _extract_vaccine_info_for_clinic(clinic)

    scheduling_input = {
        "lob": clinic.get("lobType", "RxIMZ"),
        "source": "1",
        "isStateMgmtFlag": True,
        "groupSize": 1,
        "operationType": "add",
        "softReservationInput": [{
            "patientReferenceId": "P1",
            "dateOfBirth": dob,
            "flow": "VACCINE",
            "clinicId": clinic_id,
            "clinicType": clinic.get("clinicType", "IMZ_STORE"),
            "appointmentDate": appointment_date,
            "timeZone": clinic.get("timeZone", "America/New_York"),
            "line1": addr.get("street", ""),
            "line2": "",
            "city": addr.get("city", ""),
            "state": addr.get("state", ""),
            "zipCode": addr.get("zip", ""),
            "appointmentTime": appointment_time,
            "appointmentDuration": None,
            "isDurationBasedScheduling": None,
            "totalDuration": None,
            "reservationCode": "",
            "expiryTime": "",
            "vaccines": vaccine_info,
            "reasonForVisit": [],
            "oldReservation": {
                "oldconfirmationNumberapptID": "",
                "reason": "",
                "clinicId": "",
                "oldApptDate": "",
                "oldApptScheduleType": "",
            },
        }],
    }

    try:
        client = await _ensure_session()
        result = await client.soft_reserve_slot(scheduling_input)
        _session_cache["reservation"] = result
        _session_cache["selected_clinic"] = clinic
        _session_cache["appointment_date"] = appointment_date
        _session_cache["appointment_time"] = appointment_time
        logger.info("Slot reserved: %s at %s on %s", clinic_id, appointment_time, appointment_date)
        return json.dumps(result, indent=2, default=str)
    except CVSAPIError as e:
        return f"Error reserving slot: {e}"


@mcp.tool
async def submit_patient_details(
    first_name: str,
    last_name: str,
    email: str,
    phone_number: str,
    street_address: str,
    city: str,
    state: str,
    zip_code: str,
    gender: str = "Male",
) -> str:
    """
    Submit patient demographic information. Required AFTER reserving a slot.
    The server uses cached data (DOB, clinic info) to construct the full payload.

    Args:
        first_name: Patient first name.
        last_name: Patient last name.
        email: Patient email address.
        phone_number: Patient phone number (digits only, e.g. "3522140442").
        street_address: Street address line (e.g. "1886 Abbey Wood Dr").
        city: City name.
        state: Two-letter state code (e.g. "TN").
        zip_code: ZIP code (e.g. "37135").
        gender: Patient gender ("Male", "Female", or "Other"). Defaults to "Male".

    Returns:
        JSON with patient details confirmation.
    """
    dob = _session_cache.get("date_of_birth")
    clinic = _session_cache.get("selected_clinic")
    if not dob:
        return "Error: Patient date of birth not found. Complete earlier steps first."

    lob = clinic.get("lobType", "RxIMZ") if clinic else "RxIMZ"

    patient_details_input = {
        "lob": lob,
        "authType": "",
        "source": "instore-clinic",
        "operationType": "upsert",
        "schedulingDataInfo": [{
            "patientInput": {
                "patientReferenceId": "P1",
                "firstName": first_name,
                "middleName": "",
                "lastName": last_name,
                "gender": gender,
                "dateOfBirth": dob,
                "email": email,
                "phoneNumber": phone_number,
                "primaryPhoneNumber": phone_number,
                "isMobileNumber": "true",
                "address": {
                    "city": city,
                    "country": "USA",
                    "county": "",
                    "intersection": "",
                    "line": [street_address, ""],
                    "state": state,
                    "postalCode": zip_code,
                },
                "encRxConnectId": None,
                "encMCPatientId": None,
                "isCareGiver": False,
                "epicPlanId": None,
                "subscriberDetails": None,
            }
        }],
    }

    try:
        client = await _ensure_session()
        result = await client.submit_patient_details(patient_details_input)
        _session_cache["patient_details_submitted"] = True
        logger.info("Patient details submitted for %s %s", first_name, last_name)
        return json.dumps(result, indent=2, default=str)
    except CVSAPIError as e:
        return f"Error submitting patient details: {e}"


@mcp.tool
async def get_questionnaire() -> str:
    """
    Retrieve the pre-appointment health screening questionnaire.
    MUST be called AFTER submit_patient_details.
    Uses cached clinic/vaccine/patient data automatically.

    Returns:
        JSON with screening questions and answer options (Yes/No/I don't know).
        Ask the patient each question and collect their answers.
    """
    clinic = _session_cache.get("selected_clinic")
    dob = _session_cache.get("date_of_birth")
    vaccine_codes = _session_cache.get("vaccine_codes", [])
    if not clinic or not dob:
        return "Error: Complete earlier steps (reserve slot, patient details) first."

    clinic_id = clinic.get("clinicId", "")
    store_id = clinic_id.replace("CVS_", "") if clinic_id.startswith("CVS_") else clinic_id
    lob = clinic.get("lobType", "RxIMZ")

    vaccine_ndc = _extract_vaccine_info_for_clinic(clinic)
    ndc_input = []
    for v in vaccine_ndc:
        ndcs = [{"id": n["id"]} for n in v.get("ndc", [])[:1]]
        ndc_input.append({"code": v["code"], "ndc": ndcs})

    questionnaire_input = {
        "lob": lob,
        "flow": "VACCINE",
        "storeId": store_id,
        "clinicId": clinic_id,
        "source": "instore-clinic",
        "sameDaySchedule": False,
        "questionnaireDataInput": [{
            "patientReferenceId": "P1",
            "dateOfBirth": dob,
            "vaccines": ndc_input,
            "requiredQuestionnaireContext": ["IMZ_SCREENING_QUESTION"],
        }],
    }

    try:
        client = await _ensure_session()
        result = await client.get_questionnaire(questionnaire_input)
        _session_cache["questionnaire_data"] = result
        logger.info("Retrieved questionnaire")

        q_sets = result.get("questionnaireData", [])
        questions_summary = []
        for qs in q_sets:
            for q in qs.get("questions", []):
                options = [{"text": o.get("text"), "value": o.get("value")}
                           for o in q.get("answerOptions", [])]
                questions_summary.append({
                    "id": q.get("id"),
                    "text": q.get("text"),
                    "options": options,
                    "context": qs.get("context"),
                })
        return json.dumps({"questions": questions_summary}, indent=2, default=str)
    except CVSAPIError as e:
        return f"Error: {e}"


@mcp.tool
async def submit_questionnaire(answers: list[dict]) -> str:
    """
    Submit completed health screening questionnaire answers.
    MUST be called AFTER get_questionnaire.

    Args:
        answers: List of answer objects. Each must have:
                 - "id": question ID (string from get_questionnaire)
                 - "answer": the answer value (e.g. "2" for No, "1" for Yes, "3" for I don't know)
                 Example: [{"id": "34", "answer": "2"}, {"id": "35", "answer": "2"}]

    Returns:
        JSON confirming questionnaire submission.
    """
    q_data = _session_cache.get("questionnaire_data")
    clinic = _session_cache.get("selected_clinic")
    if not q_data or not clinic:
        return "Error: Call get_questionnaire first."

    lob = clinic.get("lobType", "RxIMZ")
    answer_map = {str(a["id"]): str(a["answer"]) for a in answers}

    q_sets = q_data.get("questionnaireData", [])
    formatted_questions = []
    for qs in q_sets:
        context = qs.get("context", "IMZ_SCREENING_QUESTION")
        for q in qs.get("questions", []):
            qid = str(q.get("id"))
            answer_value = answer_map.get(qid, "2")
            answer_text = "No"
            for opt in q.get("answerOptions", []):
                if str(opt.get("value")) == answer_value:
                    answer_text = opt.get("text", "No")
                    break
            formatted_questions.append({
                "id": qid,
                "text": q.get("text", ""),
                "vaccines": q.get("vaccines", []),
                "answerOptions": {
                    "text": answer_text,
                    "value": answer_value,
                    "answerFreeText": "",
                },
            })

    scheduling_questionnaire_input = {
        "lob": lob,
        "flow": "VACCINE",
        "operation": "add",
        "schedulingQuestionnaireDataInput": [{
            "patientReferenceId": "P1",
            "context": "IMZ_SCREENING_QUESTION",
            "questions": formatted_questions,
        }],
    }

    try:
        client = await _ensure_session()
        result = await client.submit_questionnaire(scheduling_questionnaire_input)
        _session_cache["questionnaire_submitted"] = True
        logger.info("Questionnaire submitted")
        return json.dumps(result, indent=2, default=str)
    except CVSAPIError as e:
        return f"Error: {e}"


@mcp.tool
async def get_user_schedule() -> str:
    """
    Check if the patient already has an existing appointment (duplicate detection).
    Called automatically before confirming a new appointment.

    Returns:
        JSON with any existing scheduled appointments.
    """
    try:
        client = await _ensure_session()
        result = await client.get_user_schedule(check_duplicate=True)
        return json.dumps(result, indent=2, default=str)
    except CVSAPIError as e:
        return f"Error: {e}"


@mcp.tool
async def confirm_appointment() -> str:
    """
    Final confirmation of the vaccine appointment. This is the LAST step.
    MUST be called AFTER all previous steps (reserve, patient details, questionnaire).
    Uses cached data to build the confirmation payload automatically.

    Returns:
        JSON with confirmation number and appointment summary.
    """
    clinic = _session_cache.get("selected_clinic")
    if not clinic:
        return "Error: Complete all previous steps before confirming."

    lob = clinic.get("lobType", "RxIMZ")
    confirm_input = {
        "lob": lob,
        "source": "instore-clinic",
        "additionalInput": {
            "imzFlow": "store_guest",
            "isImzGapIncluded": False,
        },
    }

    try:
        client = await _ensure_session()
        result = await client.confirm_appointment(confirm_input)
        logger.info("Appointment confirmed!")
        return json.dumps(result, indent=2, default=str)
    except CVSAPIError as e:
        return f"Error confirming appointment: {e}"


@mcp.tool
async def address_typeahead(search_text: str, max_results: int = 5) -> str:
    """
    Address autocomplete for patient address entry.
    Returns address suggestions as the patient types.

    Args:
        search_text: Partial address text to search for.
        max_results: Maximum number of suggestions (default 5).
    """
    try:
        client = await _ensure_session()
        result = await client.address_typeahead(search_text, max_results)
        return json.dumps(result, indent=2, default=str)
    except CVSAPIError as e:
        return f"Error: {e}"


# ---------------------------------------------------------------------------
# Authentication & appointment management tools
# ---------------------------------------------------------------------------


@mcp.tool
async def login_to_cvs(email: str, password: str = "") -> str:
    """
    Start the CVS login process. Supports two modes:

    1. OTP mode (default): If no password is provided, sends an SMS verification code.
       After calling this, ask the user for the code and call verify_otp.
    2. Password mode: If password is provided, logs in directly with password.
       No OTP or DOB verification needed.

    Use this when the user wants to:
    - View their upcoming appointments
    - Cancel an appointment
    - Log in to their CVS account
    - Schedule as an authenticated user (pre-fills their info)

    Args:
        email: The user's CVS account email address.
        password: Optional. The user's CVS account password. If empty, uses OTP flow.

    Returns:
        Status message: "code_sent" (OTP sent), or "authenticated" (password login succeeded).
    """
    try:
        client = await _get_client()

        if password:
            result = await client.login_with_password(email, password)
            status = result.get("status", "unknown")
            if status == "authenticated":
                return await _complete_authentication(client)
            else:
                message = result.get("message", "Unknown error")
                return f"Password login failed: {message}"
        else:
            result = await client.login(email)
            status = result.get("status", "unknown")
            if status == "code_sent":
                mfa_method = result.get("mfa_method", "sms")
                return (
                    f"Login initiated. CVS has sent a 6-digit verification code via {mfa_method}. "
                    "Please ask the user for the code and then call verify_otp."
                )
            elif status == "authenticated":
                return await _complete_authentication(client)
            else:
                message = result.get("message", "Unknown error")
                return f"Login failed: {message}"
    except Exception as e:
        return f"Error during login: {e}"


@mcp.tool
async def verify_otp(code: str) -> str:
    """
    Submit the 6-digit SMS verification code.
    MUST be called AFTER login_to_cvs when the status is "code_sent".

    After OTP verification, CVS requires date of birth verification.
    If DOB is already cached (from the scheduling flow), it is submitted automatically.
    Otherwise, returns "dob_required" and you should ask the user for their DOB
    then call verify_dob.

    Args:
        code: The 6-digit verification code from SMS (e.g. "123456").

    Returns:
        Status: "dob_required" (need to call verify_dob next) or "authenticated".
    """
    try:
        client = await _get_client()
        result = await client.submit_otp(code)
        status = result.get("status", "unknown")

        if status == "dob_required":
            # Try auto-verify with cached DOB
            cached_dob = _session_cache.get("date_of_birth")
            if cached_dob:
                logger.info("Auto-verifying DOB from cache: %s", cached_dob)
                parts = cached_dob.split("-")
                if len(parts) == 3:
                    year, month, day = parts
                    dob_result = await client.verify_dob(month, day, year)
                    if dob_result.get("status") == "authenticated":
                        return await _complete_authentication(client)
                    return f"DOB auto-verification failed: {dob_result.get('message', 'Unknown error')}. Please call verify_dob manually."

            return json.dumps({
                "status": "dob_required",
                "message": (
                    "OTP verified. CVS now requires date of birth verification. "
                    "Ask the user for their date of birth and call verify_dob."
                ),
            }, indent=2)

        elif status == "authenticated":
            return await _complete_authentication(client)
        else:
            message = result.get("message", "Verification failed")
            return f"OTP verification failed: {message}"
    except Exception as e:
        return f"Error during OTP verification: {e}"


@mcp.tool
async def verify_dob(month: str, day: str, year: str) -> str:
    """
    Submit date of birth to complete CVS login authentication.
    MUST be called AFTER verify_otp when the status is "dob_required".

    After successful DOB verification, the user's patient profile is automatically fetched.

    Args:
        month: Birth month as 1-2 digits (e.g. "10" for October, "3" for March).
        day: Birth day as 1-2 digits (e.g. "15", "5").
        year: Birth year as 4 digits (e.g. "1990").

    Returns:
        Authentication status and patient profile summary if successful.
    """
    try:
        client = await _get_client()
        result = await client.verify_dob(month, day, year)
        status = result.get("status", "unknown")

        if status == "authenticated":
            # Cache the DOB for future use
            dob_str = f"{year}-{month.zfill(2)}-{day.zfill(2)}"
            if not _session_cache.get("date_of_birth"):
                _session_cache["date_of_birth"] = dob_str

            return await _complete_authentication(client)
        else:
            message = result.get("message", "DOB verification failed")
            return f"DOB verification failed: {message}"
    except Exception as e:
        return f"Error during DOB verification: {e}"


async def _complete_authentication(client: CVSClient) -> str:
    """After successful authentication, fetch profile and return summary."""
    _session_cache["authenticated"] = True

    try:
        profile = await client.get_patient_profile()
        _session_cache["patient_profile"] = profile

        first_name = profile.get("firstName", "")
        last_name = profile.get("lastName", "")
        email = profile.get("emailAddress", "")
        dob = profile.get("dateOfBirth", "")
        gender = profile.get("gender", "")

        phones = profile.get("phoneNumber", [])
        if isinstance(phones, list):
            phone = phones[0].get("number", "") if phones else ""
        else:
            phone = str(phones) if phones else ""

        address = profile.get("address") or {}
        addr_lines = address.get("line", [])
        addr_street = addr_lines[0] if addr_lines else ""

        if dob and not _session_cache.get("date_of_birth"):
            _session_cache["date_of_birth"] = dob

        profile_summary = {
            "firstName": first_name,
            "lastName": last_name,
            "email": email,
            "dateOfBirth": dob,
            "phone": phone,
            "gender": gender,
            "address": {
                "street": addr_street,
                "city": address.get("city", ""),
                "state": address.get("state", ""),
                "zip": address.get("postalCode", ""),
            } if addr_street else None,
        }

        return json.dumps({
            "status": "authenticated",
            "profile": profile_summary,
            "message": f"Welcome, {first_name}! You are now logged in.",
        }, indent=2)
    except Exception as e:
        logger.warning("Failed to fetch profile after auth: %s", e)
        return json.dumps({
            "status": "authenticated",
            "profile": {
                "firstName": "",
                "lastName": "",
                "email": "",
                "dateOfBirth": "",
            },
            "message": "Login successful, but could not load profile details.",
        }, indent=2)


@mcp.tool
async def get_patient_profile() -> str:
    """
    Get the authenticated user's CVS patient profile.
    Requires the user to be logged in (call login_to_cvs + verify_otp + verify_dob first).

    Returns:
        JSON with patient name, email, date of birth, phone number, and favorite store.
    """
    if not _session_cache.get("authenticated"):
        return "Error: User is not logged in. Use login_to_cvs, verify_otp, and verify_dob first."

    try:
        client = await _get_client()
        profile = await client.get_patient_profile()
        _session_cache["patient_profile"] = profile

        phones = profile.get("phoneNumber", [])
        phone_str = phones[0].get("number", "") if phones else ""

        summary = {
            "firstName": profile.get("firstName"),
            "lastName": profile.get("lastName"),
            "email": profile.get("emailAddress"),
            "dateOfBirth": profile.get("dateOfBirth"),
            "phone": phone_str,
            "rxTied": profile.get("rxTied"),
            "favoriteStore": (profile.get("additionalData") or {}).get("defaultFavStoreId"),
        }
        return json.dumps(summary, indent=2, default=str)
    except AuthenticationError as e:
        _session_cache["authenticated"] = False
        return f"Authentication error: {e}. Please log in again."
    except CVSAPIError as e:
        return f"Error: {e}"


@mcp.tool
async def get_my_appointments() -> str:
    """
    Get the authenticated user's upcoming vaccine appointments.
    Requires the user to be logged in (call login_to_cvs + verify_otp + verify_dob first).

    Returns:
        JSON with a list of upcoming appointments including date, time, store, and vaccines.
    """
    if not _session_cache.get("authenticated"):
        return "Error: User is not logged in. Use login_to_cvs, verify_otp, and verify_dob first."

    try:
        client = await _get_client()
        result = await client.get_upcoming_appointments()

        caregiver = result.get("caregiverAppointments", {})
        raw_appointments = caregiver.get("appointments", [])

        _session_cache["appointments"] = raw_appointments
        logger.info("Fetched %d upcoming appointments", len(raw_appointments))

        if not raw_appointments:
            return json.dumps({"appointments": [], "message": "No upcoming appointments found."}, indent=2)

        summary = []
        for appt in raw_appointments:
            details = appt.get("details", {})
            vaccines_imz = details.get("vaccinesIMZ", [])
            services_mc = details.get("servicesMC", [])

            vaccine_names = [v.get("name", v.get("code", "Unknown")) for v in vaccines_imz]
            service_names = [s.get("name", "Unknown") for s in (services_mc or [])]

            store = appt.get("store", {})
            store_addr = store.get("address", {})
            address_line = store_addr.get("line", [""])[0] if store_addr.get("line") else ""

            vaccine_ids = [v.get("id") for v in vaccines_imz if v.get("id")]

            summary.append({
                "appointmentId": appt.get("appointmentId"),
                "appointmentDate": appt.get("appointmentDate"),
                "lobType": appt.get("lobType"),
                "status": appt.get("status"),
                "vaccines": vaccine_names,
                "services": service_names,
                "vaccineIds": vaccine_ids,
                "store": {
                    "clinicId": store.get("clinicId"),
                    "address": f"{address_line}, {store_addr.get('city', '')}, {store_addr.get('state', '')} {store_addr.get('postalCode', '')}".strip(", "),
                    "timeZone": store.get("timeZone"),
                },
                "checkInId": appt.get("checkInId"),
                "flow": appt.get("flow"),
            })

        return json.dumps({"appointments": summary, "total": len(summary)}, indent=2, default=str)
    except AuthenticationError as e:
        _session_cache["authenticated"] = False
        return f"Authentication error: {e}. Please log in again."
    except CVSAPIError as e:
        return f"Error: {e}"


@mcp.tool
async def cancel_appointment(appointment_id: str) -> str:
    """
    Cancel an upcoming vaccine appointment.
    Requires the user to be logged in and to have fetched appointments first
    (call get_my_appointments before this).

    The server automatically resolves the confirmation number, vaccine IDs, and LOB
    from the cached appointment data.

    Args:
        appointment_id: The appointmentId from get_my_appointments
                        (e.g. "rTnJP/J96MGcv/zkKgmkNQ==").

    Returns:
        JSON confirming the cancellation.
    """
    if not _session_cache.get("authenticated"):
        return "Error: User is not logged in. Use login_to_cvs, verify_otp, and verify_dob first."

    cached_appointments = _session_cache.get("appointments")
    if not cached_appointments:
        return "Error: No appointment data cached. Call get_my_appointments first."

    # Find the appointment by ID
    target = None
    for appt in cached_appointments:
        if appt.get("appointmentId") == appointment_id:
            target = appt
            break

    if not target:
        return (
            f"Error: Appointment '{appointment_id}' not found in cached data. "
            "Call get_my_appointments to refresh the list."
        )

    lob = target.get("lobType", "RxIMZ")
    details = target.get("details", {})
    vaccines_imz = details.get("vaccinesIMZ", [])
    vaccine_ids = [v.get("id") for v in vaccines_imz if v.get("id")]

    if not vaccine_ids:
        return "Error: Could not extract vaccine IDs from this appointment."

    confirmation_number = appointment_id

    try:
        client = await _get_client()
        result = await client.cancel_appointment(
            lob=lob,
            cancel_reason_code="8",
            vaccine_ids=vaccine_ids,
            confirmation_number=confirmation_number,
        )

        # Remove from cache
        _session_cache["appointments"] = [
            a for a in cached_appointments if a.get("appointmentId") != appointment_id
        ]

        logger.info("Appointment cancelled: %s", appointment_id)
        return json.dumps({
            "status": "cancelled",
            "confirmationNumber": result.get("confirmationNumber", confirmation_number),
            "lob": lob,
            "message": "Appointment has been successfully cancelled.",
        }, indent=2, default=str)
    except AuthenticationError as e:
        _session_cache["authenticated"] = False
        return f"Authentication error: {e}. Please log in again."
    except CVSAPIError as e:
        return f"Error cancelling appointment: {e}"


# ---------------------------------------------------------------------------
# Manual (redirect) login + logout tools (used by REST API, not typically by LLM)
# ---------------------------------------------------------------------------


@mcp.tool
async def start_manual_login() -> str:
    """
    Open the CVS login page in a visible browser window for the user to log in manually.
    The user can complete login using either OTP or password -- both are supported.

    After calling this, poll check_login_status every few seconds to detect
    when the user finishes logging in.

    Returns:
        Status message confirming the browser was opened.
    """
    try:
        client = await _get_client()
        result = await client.start_manual_login()
        if result.get("status") == "browser_opened":
            return json.dumps({
                "status": "browser_opened",
                "message": "CVS login page opened in browser. Complete login there.",
            })
        return f"Error: {result.get('message', 'Unknown error')}"
    except Exception as e:
        return f"Error opening login browser: {e}"


@mcp.tool
async def check_login_status() -> str:
    """
    Check if the user has completed manual login in the browser.
    Call this periodically after start_manual_login.

    Returns:
        JSON with status "pending", "authenticated" (with profile), or "error".
    """
    try:
        client = await _get_client()
        result = await client.check_login_status()
        status = result.get("status", "unknown")

        if status == "authenticated":
            auth_result = await _complete_authentication(client)
            # Keep the browser alive -- authenticated API calls are routed
            # through it (Akamai ties cookies to the browser's TLS fingerprint).
            logger.info("Auth confirmed; browser kept alive for authenticated API calls")
            return auth_result
        elif status == "error":
            return json.dumps({
                "status": "error",
                "message": result.get("message", "Browser session lost"),
            })
        else:
            return json.dumps({"status": "pending"})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


@mcp.tool
async def logout() -> str:
    """
    Log out the current authenticated user. Clears session cookies and closes the browser.

    Returns:
        Confirmation that the user has been logged out.
    """
    try:
        client = await _get_client()
        await client.logout()
        _session_cache["authenticated"] = False
        _session_cache["patient_profile"] = None
        _session_cache["appointments"] = None
        return json.dumps({"status": "logged_out", "message": "You have been signed out."})
    except Exception as e:
        return f"Error during logout: {e}"


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    port = int(os.environ.get("MCP_SERVER_PORT", "8001"))
    host = os.environ.get("MCP_SERVER_HOST", "0.0.0.0")

    logger.info(f"Starting CVS Scheduling MCP Server on {host}:{port}")
    logger.info(f"MCP endpoint: http://{host}:{port}/mcp")

    mcp.run(transport="http", host=host, port=port)
