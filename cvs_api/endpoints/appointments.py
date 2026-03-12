"""Authenticated appointment endpoints -- profile, upcoming appointments, cancellation.

These endpoints route through the Playwright browser's fetch() API to preserve
the Akamai session (cookies + TLS fingerprint must match the login browser).
The ``auth_post`` callable is provided by CVSClient.auth_post.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from typing import Any

from cvs_api.config import (
    AUTH_EXPERIENCE_NAMES,
    AUTH_EXPERIENCE_UUIDS,
    EXPERIENCE_PATH,
)
from cvs_api.exceptions import AuthenticationError, ExperienceAPIError
from cvs_api.session import CVSSession

logger = logging.getLogger(__name__)

AuthPostFn = Callable[..., Coroutine[Any, Any, dict[str, Any]]]


async def get_patient_profile(
    session: CVSSession,
    auth_post: AuthPostFn,
) -> dict[str, Any]:
    """Fetch the authenticated user's patient profile."""
    if not session.is_authenticated:
        raise AuthenticationError("Not authenticated. Login required.")

    uuid = AUTH_EXPERIENCE_UUIDS["patient_profile"]
    name = AUTH_EXPERIENCE_NAMES["patient_profile"]
    headers = session.get_auth_experience_headers(
        name, uuid,
        route="PHARMACY-GKE-RKE",
        client_id="imz",
        referer="https://www.cvs.com/scheduling/",
    )
    body = {"data": {"idType": "RETAIL_PROFILE_ID_TYPE"}}

    result = await auth_post(f"{EXPERIENCE_PATH}/{uuid}", headers=headers, body=body)

    if result.get("statusCode") != "0000":
        raise ExperienceAPIError(
            f"Patient profile failed: {result.get('statusDescription')}",
            response_body=result,
        )

    return result.get("data", {}).get("profile", {})


async def get_upcoming_appointments(
    session: CVSSession,
    auth_post: AuthPostFn,
    lob_list: list[str] | None = None,
) -> dict[str, Any]:
    """Fetch the authenticated user's upcoming appointments."""
    if not session.is_authenticated:
        raise AuthenticationError("Not authenticated. Login required.")

    if lob_list is None:
        lob_list = ["CLINIC", "RxIMZ"]

    uuid = AUTH_EXPERIENCE_UUIDS["upcoming_appointments"]
    name = AUTH_EXPERIENCE_NAMES["upcoming_appointments"]
    headers = session.get_auth_experience_headers(name, uuid)

    body = {
        "data": {
            "idType": "RETAIL_PROFILE_ID_TYPE",
            "appointmentsFilterCriteriaInput": {
                "lob": lob_list,
                "isProviderCancelled": True,
            },
        }
    }

    result = await auth_post(f"{EXPERIENCE_PATH}/{uuid}", headers=headers, body=body)

    if result.get("statusCode") != "0000":
        raise ExperienceAPIError(
            f"Upcoming appointments failed: {result.get('statusDescription')}",
            response_body=result,
        )

    return result.get("data", {}).get("getUpcomingAppointments", {})


async def cancel_appointment(
    session: CVSSession,
    auth_post: AuthPostFn,
    *,
    lob: str,
    cancel_reason_code: str = "8",
    vaccine_ids: list[str],
    confirmation_number: str,
) -> dict[str, Any]:
    """Cancel an existing appointment."""
    if not session.is_authenticated:
        raise AuthenticationError("Not authenticated. Login required.")

    uuid = AUTH_EXPERIENCE_UUIDS["cancel_appointment"]
    name = AUTH_EXPERIENCE_NAMES["cancel_appointment"]
    headers = session.get_auth_experience_headers(name, uuid)

    body = {
        "data": {
            "cancelAppointmentInput": {
                "lob": lob,
                "cancelReasonCode": cancel_reason_code,
                "vaccineId": vaccine_ids,
                "confirmationNumber": confirmation_number,
            }
        }
    }

    logger.info("Cancelling appointment: lob=%s, confirmation=%s", lob, confirmation_number)
    result = await auth_post(f"{EXPERIENCE_PATH}/{uuid}", headers=headers, body=body)

    if result.get("statusCode") != "0000":
        raise ExperienceAPIError(
            f"Cancel appointment failed: {result.get('statusDescription')}",
            response_body=result,
        )

    cancel_data = result.get("data", {}).get("cancelAppointment", {})
    if cancel_data.get("statusCode") not in ("SUCCESS", "0000", None):
        raise ExperienceAPIError(
            f"Cancel appointment rejected: {cancel_data.get('statusDescription')}",
            response_body=result,
        )

    return cancel_data
