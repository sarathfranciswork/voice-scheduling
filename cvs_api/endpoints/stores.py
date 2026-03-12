"""Store / location search and time slot endpoints."""

from __future__ import annotations

import datetime
from typing import Any

import httpx

from cvs_api.config import (
    CONTENT_API_KEY,
    EXPERIENCE_NAMES,
    EXPERIENCE_PATH,
    EXPERIENCE_UUIDS,
    STORE_LOCATOR_PATH,
)
from cvs_api.exceptions import ExperienceAPIError, NoAvailabilityError
from cvs_api.session import CVSSession


def _to_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _to_int(val: Any, default: int = 0) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


async def search_stores(
    session: CVSSession,
    http: httpx.AsyncClient,
    *,
    address: str,
    date_of_birth: str,
    vaccine_eligibility_data: dict[str, Any],
    vaccine_codes: list[str],
    radius: int = 35,
    max_results: int = 25,
) -> dict[str, Any]:
    """
    Search for CVS pharmacy locations with vaccine availability.

    Args:
        address: Location string, e.g. "02101" or "37135, TN" or "Boston, MA".
        date_of_birth: Patient DOB in YYYY-MM-DD format.
        vaccine_eligibility_data: Full response from check_vaccine_eligibility containing
            NDC codes, manufacturers, scheduling dates, and patient eligibility data.
        vaccine_codes: List of vaccine codes to search for (e.g. ["FLU", "CVD"]).
        radius: Search radius in miles (default 35).
        max_results: Maximum number of stores (default 25).

    Returns:
        Dict with 'listOfClinics' containing matched stores and their available dates.
    """
    await session.ensure_token()

    uuid = EXPERIENCE_UUIDS["locator_time_slots"]
    name = EXPERIENCE_NAMES["locator_time_slots"]
    headers = session.get_experience_headers(name, uuid)

    # Extract scheduling date range from eligibility data
    min_date = vaccine_eligibility_data.get(
        "minScheduleDateIMZ",
        datetime.date.today().isoformat(),
    )
    max_date = vaccine_eligibility_data.get(
        "maxScheduleDateIMZ",
        (datetime.date.today() + datetime.timedelta(days=42)).isoformat(),
    )

    # Build per-vaccine LOB entries from eligibility data
    vax_data = vaccine_eligibility_data.get("vaccineData", [])
    patient_data = vax_data[0] if vax_data else {}

    pharmacy_vaccines = []  # RxIMZ
    clinic_vaccines = []     # CLINIC
    clinic_reason_ids = []

    imz_pharmacy = patient_data.get("immunizationsPharmacy", {})
    imz_clinic = patient_data.get("immunizationsMC", {})

    for code in vaccine_codes:
        # RxIMZ entry
        pharm_vax = _find_vaccine(imz_pharmacy.get("vaccines", []), code)
        if pharm_vax:
            ndc_list = [{"id": n["id"]} for n in pharm_vax.get("ndc", [])]
            manufacturers = pharm_vax.get("manufacturer", []) or []
            pharmacy_vaccines.append({
                "ndc": ndc_list,
                "code": code,
                "manufacturers": manufacturers,
            })

        # CLINIC entry
        clinic_vax = _find_vaccine(imz_clinic.get("vaccines", []), code)
        if clinic_vax:
            ndc_list = []
            for n in clinic_vax.get("ndc", []):
                ndc_entry: dict[str, Any] = {"id": n["id"]}
                if n.get("reasonId") is not None:
                    ndc_entry["reasonId"] = n["reasonId"]
                    clinic_reason_ids.append(n["reasonId"])
                if n.get("reasonMappingId") is not None:
                    ndc_entry["reasonMappingId"] = n["reasonMappingId"]
                if n.get("subCategoryIMS") is not None:
                    ndc_entry["subCategoryIMS"] = n["subCategoryIMS"]
                if n.get("subCategoryMC") is not None:
                    ndc_entry["subCategoryMC"] = n["subCategoryMC"]
                ndc_list.append(ndc_entry)
            clinic_vaccines.append({
                "ndc": ndc_list,
                "code": code,
            })

    lob_entries = []

    if pharmacy_vaccines:
        lob_entries.append({
            "lobType": "RxIMZ",
            "lobParameters": {
                "minSchedulingDate": min_date,
                "maxSchedulingDate": max_date,
                "patients": [{
                    "patientReferenceId": "P1",
                    "dateOfBirth": date_of_birth,
                    "vaccines": pharmacy_vaccines,
                }],
            },
        })

    if clinic_vaccines:
        lob_entries.append({
            "lobType": "CLINIC",
            "lobParameters": {
                "reasonId": clinic_reason_ids if clinic_reason_ids else [1],
                "patients": [{
                    "patientReferenceId": "P1",
                    "dateOfBirth": date_of_birth,
                    "vaccines": clinic_vaccines,
                }],
            },
        })

    body: dict[str, Any] = {
        "data": {
            "preferredStore": {
                "lastVistedClinic": None,
                "lastVistedStore": None,
                "favoriteStore": "",
            },
            "searchCriteriaInput": {
                "address": address,
                "groupSize": "1",
                "lob": lob_entries,
                "flow": "VACCINE",
                "entryFlow": "IMZ",
            },
            "sortCriteriaInput": {
                "sortBy": "distance",
            },
            "filterCriteriaInput": {
                "isIncludeDates": True,
                "isIncludeClinicConfig": True,
                "searchRadius": radius,
                "limitResults": max_results,
                "isShowAllClinics": True,
            },
        }
    }

    resp = await http.post(f"{EXPERIENCE_PATH}/{uuid}", json=body, headers=headers)
    resp.raise_for_status()
    result = resp.json()

    if result.get("statusCode") != "0000":
        raise ExperienceAPIError(
            f"Store search failed: {result.get('statusDescription')}",
            response_body=result,
        )

    locations = result.get("data", {}).get("getLocations", {})
    if not locations.get("listOfClinics"):
        raise NoAvailabilityError("No stores found matching the search criteria.")

    return locations


def _find_vaccine(vaccines: list[dict], code: str) -> dict | None:
    """Find a vaccine entry by code in a list of vaccine dicts."""
    for v in vaccines:
        if v.get("code") == code:
            return v
    return None


async def get_available_time_slots(
    session: CVSSession,
    http: httpx.AsyncClient,
    *,
    visit_date: str,
    date_of_birth: str,
    vaccine_codes: list[str],
    store_search_results: dict[str, Any],
    vaccine_eligibility_data: dict[str, Any],
) -> dict[str, Any]:
    """
    Get available appointment time slots for stores on a specific date.

    Args:
        visit_date: Requested date in YYYY-MM-DD format.
        date_of_birth: Patient DOB in YYYY-MM-DD format.
        vaccine_codes: List of vaccine codes to schedule (e.g. ["FLU"]).
        store_search_results: The full response from search_stores containing
            clinic IDs, distances, and lobType groupings.
        vaccine_eligibility_data: The full response from check_vaccine_eligibility
            containing NDC codes, reasonIds, and scheduling date ranges.

    Returns:
        Dict with time slot availability per clinic.
    """
    await session.ensure_token()

    uuid = EXPERIENCE_UUIDS["available_time_slots"]
    name = EXPERIENCE_NAMES["available_time_slots"]
    headers = session.get_experience_headers(name, uuid)

    # Calculate patient age from DOB
    dob = datetime.date.fromisoformat(date_of_birth)
    today = datetime.date.today()
    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

    # Extract eligibility data
    vax_data = vaccine_eligibility_data.get("vaccineData", [])
    patient_data = vax_data[0] if vax_data else {}
    imz_clinic = patient_data.get("immunizationsMC", {})
    min_date = vaccine_eligibility_data.get("minScheduleDateIMZ", today.isoformat())
    max_date = vaccine_eligibility_data.get("maxScheduleDateIMZ",
                                            (today + datetime.timedelta(days=42)).isoformat())

    # Build CLINIC NDC data and reasonIds
    clinic_vaccines: list[dict[str, Any]] = []
    clinic_reason_ids: list[int] = []
    for code in vaccine_codes:
        clinic_vax = _find_vaccine(imz_clinic.get("vaccines", []), code)
        if clinic_vax:
            ndc_list = []
            for n in clinic_vax.get("ndc", []):
                reason_id = _to_int(n.get("reasonId"), 1)
                ndc_list.append({
                    "name": None, "manufacturer": None, "id": str(n["id"]),
                    "reasonId": reason_id,
                    "reasonMappingId": str(n.get("reasonMappingId", "")),
                    "subCategoryIMS": str(n.get("subCategoryIMS", "")),
                    "subCategoryMC": str(n.get("subCategoryMC", "")),
                })
                clinic_reason_ids.append(reason_id)
            clinic_vaccines.append({"ndc": ndc_list, "code": code})

    # Group clinics from search results by lobType
    clinics = store_search_results.get("listOfClinics", [])
    rximz_clinics = [c for c in clinics if c.get("lobType") == "RxIMZ"]
    clinic_type_clinics = [c for c in clinics if c.get("lobType") == "CLINIC"]

    lob_entries = []

    # CLINIC LOB entry
    if clinic_type_clinics and clinic_vaccines:
        clinic_ids = [str(c["clinicId"]) for c in clinic_type_clinics if c.get("clinicId")]
        dist_mappings = [
            {"clinicId": str(c["clinicId"]), "distance": _to_float(c.get("distance"), 0.0)}
            for c in clinic_type_clinics if c.get("clinicId")
        ]
        lob_entries.append({
            "lobType": "CLINIC",
            "clinicInfo": {
                "clinicIds": clinic_ids,
                "distanceMappings": dist_mappings,
                "age": str(age),
                "reasonIds": clinic_reason_ids if clinic_reason_ids else [1],
            },
            "patients": [{
                "patientReferenceId": "P1",
                "dateOfBirth": date_of_birth,
                "vaccines": clinic_vaccines,
            }],
        })

    # RxIMZ LOB entry
    if rximz_clinics:
        clinic_ids = [str(c["clinicId"]) for c in rximz_clinics if c.get("clinicId")]
        dist_mappings = [
            {"clinicId": str(c["clinicId"]), "distance": _to_float(c.get("distance"), 0.0)}
            for c in rximz_clinics if c.get("clinicId")
        ]
        lob_entries.append({
            "lobType": "RxIMZ",
            "clinicInfo": {
                "clinicIds": clinic_ids,
                "groupSize": "1",
                "distanceMappings": dist_mappings,
            },
            "minSchedulingDate": min_date,
            "maxSchedulingDate": max_date,
        })

    body = {
        "data": {
            "availableTimeSlotsInput": {
                "startDate": visit_date,
                "endDate": visit_date,
                "lob": lob_entries,
                "flow": "VACCINE",
                "sortBy": "distance",
            }
        }
    }

    resp = await http.post(f"{EXPERIENCE_PATH}/{uuid}", json=body, headers=headers)
    resp.raise_for_status()
    result = resp.json()

    if result.get("statusCode") != "0000":
        raise ExperienceAPIError(
            f"Time slots failed: {result.get('statusDescription')}",
            response_body=result,
        )

    return result.get("data", {}).get("getAvailableTimeSlots", {})


async def get_store_details(
    session: CVSSession,
    http: httpx.AsyncClient,
    store_id: str,
) -> dict[str, Any]:
    """Retrieve store details (address, hours, services) from the locator API."""
    await session.ensure_token()

    headers = {
        "accept": "application/json",
        "x-api-key": CONTENT_API_KEY,
        "x-channel": "WEB",
        "authorization": f"Bearer {session._token}",
    }

    resp = await http.get(f"{STORE_LOCATOR_PATH}/{store_id}", headers=headers)
    resp.raise_for_status()
    return resp.json()
