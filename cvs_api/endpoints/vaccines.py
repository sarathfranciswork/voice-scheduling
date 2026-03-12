"""Vaccine eligibility endpoints."""

from __future__ import annotations

from typing import Any

import httpx

from cvs_api.config import EXPERIENCE_NAMES, EXPERIENCE_PATH, EXPERIENCE_UUIDS
from cvs_api.exceptions import ExperienceAPIError
from cvs_api.session import CVSSession


async def get_eligible_vaccines(
    session: CVSSession,
    http: httpx.AsyncClient,
    date_of_birth: str,
    flow: str = "VACCINE",
) -> dict[str, Any]:
    """
    Get vaccines the patient is eligible for based on DOB.

    Args:
        date_of_birth: Patient DOB in YYYY-MM-DD format.
        flow: Scheduling flow type (default "VACCINE").

    Returns:
        Dict with 'eligibleVaccineData' containing vaccine codes, names, NDCs.
    """
    await session.ensure_token()

    uuid = EXPERIENCE_UUIDS["eligible_vaccines"]
    name = EXPERIENCE_NAMES["eligible_vaccines"]
    headers = session.get_experience_headers(name, uuid)

    body = {"data": {"dob": [date_of_birth], "flow": flow}}

    resp = await http.post(f"{EXPERIENCE_PATH}/{uuid}", json=body, headers=headers)
    resp.raise_for_status()
    result = resp.json()

    if result.get("statusCode") != "0000":
        raise ExperienceAPIError(
            f"Eligible vaccines failed: {result.get('statusDescription')}",
            response_body=result,
        )

    return result.get("data", {}).get("getEligibleVaccines", {})


async def check_vaccine_eligibility(
    session: CVSSession,
    http: httpx.AsyncClient,
    vaccine_eligibility_input: dict,
) -> dict[str, Any]:
    """Check detailed vaccine eligibility with screening criteria."""
    await session.ensure_token()

    uuid = EXPERIENCE_UUIDS["vaccine_eligibility_check"]
    name = EXPERIENCE_NAMES["vaccine_eligibility_check"]
    headers = session.get_experience_headers(name, uuid)

    body = {"data": {"vaccineEligibilityInput": vaccine_eligibility_input}}

    resp = await http.post(f"{EXPERIENCE_PATH}/{uuid}", json=body, headers=headers)
    resp.raise_for_status()
    result = resp.json()

    if result.get("statusCode") != "0000":
        raise ExperienceAPIError(
            f"Vaccine eligibility check failed: {result.get('statusDescription')}",
            response_body=result,
        )

    return result.get("data", {}).get("getVaccineEligibility", {})
