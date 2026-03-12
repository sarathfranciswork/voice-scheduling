"""Scheduling workflow endpoints: reserve, patient details, questionnaire, confirm."""

from __future__ import annotations

from typing import Any

import httpx

from cvs_api.config import EXPERIENCE_NAMES, EXPERIENCE_PATH, EXPERIENCE_UUIDS
from cvs_api.exceptions import ExperienceAPIError
from cvs_api.session import CVSSession


async def soft_reserve_slot(
    session: CVSSession,
    http: httpx.AsyncClient,
    *,
    scheduling_input: dict,
    id_type: str = "refId",
) -> dict[str, Any]:
    """
    Soft-reserve a time slot so it is held while the patient completes registration.

    Args:
        scheduling_input: The full scheduling input payload (clinic, date, time, vaccines).
        id_type: Identifier type (default "refId").

    Returns:
        Dict with 'reserveSlot' confirmation data.
    """
    await session.ensure_token()

    uuid = EXPERIENCE_UUIDS["soft_reserve"]
    name = EXPERIENCE_NAMES["soft_reserve"]
    headers = session.get_experience_headers(name, uuid)

    body = {
        "data": {
            "idType": id_type,
            "schedulingInput": scheduling_input,
        }
    }

    resp = await http.post(f"{EXPERIENCE_PATH}/{uuid}", json=body, headers=headers)
    resp.raise_for_status()
    result = resp.json()

    if result.get("statusCode") != "0000":
        raise ExperienceAPIError(
            f"Soft reserve failed: {result.get('statusDescription')}",
            response_body=result,
        )

    return result.get("data", {}).get("reserveSlot", {})


async def submit_patient_details(
    session: CVSSession,
    http: httpx.AsyncClient,
    *,
    patient_details_input: dict,
    id_type: str = "refId",
) -> dict[str, Any]:
    """
    Submit patient demographics (name, DOB, contact info, address).

    Returns:
        Dict with 'patientDetails' containing patient reference IDs.
    """
    await session.ensure_token()

    uuid = EXPERIENCE_UUIDS["patient_details"]
    name = EXPERIENCE_NAMES["patient_details"]
    headers = session.get_experience_headers(name, uuid)

    body = {
        "data": {
            "idType": id_type,
            "patientDetailsInput": patient_details_input,
        }
    }

    resp = await http.post(f"{EXPERIENCE_PATH}/{uuid}", json=body, headers=headers)
    resp.raise_for_status()
    result = resp.json()

    if result.get("statusCode") != "0000":
        raise ExperienceAPIError(
            f"Patient details failed: {result.get('statusDescription')}",
            response_body=result,
        )

    return result.get("data", {}).get("patientDetails", {})


async def get_questionnaire(
    session: CVSSession,
    http: httpx.AsyncClient,
    *,
    questionnaire_input: dict,
    id_type: str = "refId",
) -> dict[str, Any]:
    """
    Retrieve the pre-appointment screening questionnaire.

    Returns:
        Dict with 'getSchedulingQuestionnaire' containing questions and answer options.
    """
    await session.ensure_token()

    uuid = EXPERIENCE_UUIDS["get_questionnaire"]
    name = EXPERIENCE_NAMES["get_questionnaire"]
    headers = session.get_experience_headers(name, uuid)

    body = {
        "data": {
            "idType": id_type,
            "questionnaireInput": questionnaire_input,
        }
    }

    resp = await http.post(f"{EXPERIENCE_PATH}/{uuid}", json=body, headers=headers)
    resp.raise_for_status()
    result = resp.json()

    if result.get("statusCode") != "0000":
        raise ExperienceAPIError(
            f"Get questionnaire failed: {result.get('statusDescription')}",
            response_body=result,
        )

    return result.get("data", {}).get("getSchedulingQuestionnaire", {})


async def submit_questionnaire(
    session: CVSSession,
    http: httpx.AsyncClient,
    *,
    scheduling_questionnaire_input: dict,
    id_type: str = "refId",
) -> dict[str, Any]:
    """
    Submit completed questionnaire answers.

    Returns:
        Dict with 'schedulingQuestionnaire' confirmation.
    """
    await session.ensure_token()

    uuid = EXPERIENCE_UUIDS["submit_questionnaire"]
    name = EXPERIENCE_NAMES["submit_questionnaire"]
    headers = session.get_experience_headers(name, uuid)

    body = {
        "data": {
            "idType": id_type,
            "schedulingQuestionnaireInput": scheduling_questionnaire_input,
        }
    }

    resp = await http.post(f"{EXPERIENCE_PATH}/{uuid}", json=body, headers=headers)
    resp.raise_for_status()
    result = resp.json()

    if result.get("statusCode") != "0000":
        raise ExperienceAPIError(
            f"Submit questionnaire failed: {result.get('statusDescription')}",
            response_body=result,
        )

    return result.get("data", {}).get("schedulingQuestionnaire", {})


async def get_user_schedule(
    session: CVSSession,
    http: httpx.AsyncClient,
    *,
    check_duplicate: bool = True,
    id_type: str = "refId",
) -> dict[str, Any]:
    """Check for duplicate/existing scheduled appointments."""
    await session.ensure_token()

    uuid = EXPERIENCE_UUIDS["get_user_schedule"]
    name = EXPERIENCE_NAMES["get_user_schedule"]
    headers = session.get_experience_headers(name, uuid)

    body = {
        "data": {
            "idType": id_type,
            "checkDuplicate": check_duplicate,
        }
    }

    resp = await http.post(f"{EXPERIENCE_PATH}/{uuid}", json=body, headers=headers)
    resp.raise_for_status()
    result = resp.json()

    if result.get("statusCode") != "0000":
        raise ExperienceAPIError(
            f"Get user schedule failed: {result.get('statusDescription')}",
            response_body=result,
        )

    return result.get("data", {}).get("getUserSchedule", {})


async def confirm_appointment(
    session: CVSSession,
    http: httpx.AsyncClient,
    *,
    confirm_appointment_input: dict,
) -> dict[str, Any]:
    """
    Final confirmation of the appointment.

    Returns:
        Dict with 'confirmAppointment' containing confirmation number and details.
    """
    await session.ensure_token()

    uuid = EXPERIENCE_UUIDS["confirm_appointment"]
    name = EXPERIENCE_NAMES["confirm_appointment"]
    headers = session.get_experience_headers(name, uuid)

    body = {"data": {"confirmAppointmentInput": confirm_appointment_input}}

    resp = await http.post(f"{EXPERIENCE_PATH}/{uuid}", json=body, headers=headers)
    resp.raise_for_status()
    result = resp.json()

    if result.get("statusCode") != "0000":
        raise ExperienceAPIError(
            f"Confirm appointment failed: {result.get('statusDescription')}",
            response_body=result,
        )

    return result.get("data", {}).get("confirmAppointment", {})


async def address_typeahead(
    session: CVSSession,
    http: httpx.AsyncClient,
    *,
    search_text: str,
    max_results: int = 5,
) -> dict[str, Any]:
    """
    Address autocomplete / typeahead for patient address entry.

    Returns:
        Dict with 'typeAheadAddressPredictions' containing address suggestions.
    """
    await session.ensure_token()

    uuid = EXPERIENCE_UUIDS["address_typeahead"]
    name = EXPERIENCE_NAMES["address_typeahead"]
    headers = session.get_experience_headers(name, uuid)

    body = {
        "data": {
            "request": {
                "searchText": search_text,
                "maxResults": max_results,
                "country": "US",
            }
        }
    }

    resp = await http.post(f"{EXPERIENCE_PATH}/{uuid}", json=body, headers=headers)
    resp.raise_for_status()
    result = resp.json()

    if result.get("statusCode") != "0000":
        raise ExperienceAPIError(
            f"Address typeahead failed: {result.get('statusDescription')}",
            response_body=result,
        )

    return result.get("data", {}).get("typeAheadAddressPredictions", {})
