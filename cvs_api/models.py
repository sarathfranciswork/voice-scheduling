"""
Pydantic models for CVS scheduling API requests and responses.

Derived from captured API traffic during Phase 1.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Token
# ---------------------------------------------------------------------------

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: str = "899"
    status_code: str = Field(alias="statusCode", default="0000")


# ---------------------------------------------------------------------------
# Eligible Vaccines
# ---------------------------------------------------------------------------

class Vaccine(BaseModel):
    code: str
    name: str | None = None
    type: str | None = None
    ndc: list[dict] | None = None
    manufacturers: list[dict] | None = None
    age_restriction: dict | None = Field(alias="ageRestriction", default=None)
    dosage_info: dict | None = Field(alias="dosageInfo", default=None)
    series: str | None = None
    lob: str | None = None

    model_config = {"populate_by_name": True}


class EligibleVaccinesResponse(BaseModel):
    eligible_vaccine_data: list[dict] = Field(alias="eligibleVaccineData", default_factory=list)

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Store / Location Search
# ---------------------------------------------------------------------------

class StoreAddress(BaseModel):
    street: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = Field(alias="zip", default=None)
    country: str | None = None

    model_config = {"populate_by_name": True}


class Clinic(BaseModel):
    clinic_id: str | None = Field(alias="clinicId", default=None)
    store_id: str | None = Field(alias="storeId", default=None)
    store_number: str | None = Field(alias="storeNumber", default=None)
    address: dict | None = None
    distance: float | None = None
    available_dates: list[str] | None = Field(alias="availableDates", default=None)
    scheduling_dates: list[str] | None = Field(alias="schedulingDates", default=None)

    model_config = {"populate_by_name": True}


class LocationSearchResponse(BaseModel):
    list_of_clinics: list[dict] = Field(alias="listOfClinics", default_factory=list)

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Time Slots
# ---------------------------------------------------------------------------

class TimeSlotDetail(BaseModel):
    visit_date: str | None = Field(alias="visitDate", default=None)
    morning: list[dict] | None = None
    afternoon: list[dict] | None = None
    evening: list[dict] | None = None
    earliest: list[dict] | None = None

    model_config = {"populate_by_name": True}


class TimeSlotsForClinic(BaseModel):
    clinic_id: str | None = Field(alias="clinicId", default=None)
    time_zone: str | None = Field(alias="timeZone", default=None)
    slot_details: list[TimeSlotDetail] = Field(alias="slotDetails", default_factory=list)

    model_config = {"populate_by_name": True}


class TimeSlotsResponse(BaseModel):
    available_timeslots: list[dict] = Field(alias="availableTimeslotsResponse", default_factory=list)

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Patient Details
# ---------------------------------------------------------------------------

class PatientInput(BaseModel):
    patient_reference_id: str = Field(alias="patientReferenceId", default="P1")
    first_name: str = Field(alias="firstName")
    middle_name: str = Field(alias="middleName", default="")
    last_name: str = Field(alias="lastName")
    gender: str = "Male"
    date_of_birth: str = Field(alias="dateOfBirth")
    email: str = ""
    phone_number: str = Field(alias="phoneNumber", default="")
    address: dict | None = None

    model_config = {"populate_by_name": True}


class PatientDetailsResponse(BaseModel):
    patient_data: list[dict] = Field(alias="patientData", default_factory=list)
    status_code: str = Field(alias="statusCode", default="")
    status_description: str = Field(alias="statusDescription", default="")

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Questionnaire
# ---------------------------------------------------------------------------

class QuestionAnswer(BaseModel):
    id: str
    text: str = ""
    vaccines: list[dict] | None = None
    answer_options: dict | None = Field(alias="answerOptions", default=None)

    model_config = {"populate_by_name": True}


class QuestionnaireResponse(BaseModel):
    scheduling_questionnaire_data: list[dict] = Field(
        alias="schedulingQuestionnaireData", default_factory=list
    )

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Appointment Confirmation
# ---------------------------------------------------------------------------

class ConfirmationResponse(BaseModel):
    status_code: str = Field(alias="statusCode", default="")
    status_description: str = Field(alias="statusDescription", default="")
    response_details: dict | None = Field(alias="responseDetails", default=None)

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Store Details (locator API)
# ---------------------------------------------------------------------------

class StoreInfo(BaseModel):
    store_id: str | None = Field(alias="storeId", default=None)
    address: dict | None = None
    phone_numbers: list[dict] | None = Field(alias="phoneNumbers", default=None)
    hours: dict | None = None
    latitude: float | None = None
    longitude: float | None = None

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Wrapper for the standard CVS API response envelope
# ---------------------------------------------------------------------------

class CVSAPIResponse(BaseModel):
    """Standard envelope: {"statusCode": "0000", "statusDescription": "Success", "data": {...}}"""
    status_code: str = Field(alias="statusCode", default="")
    status_description: str = Field(alias="statusDescription", default="")
    data: dict = Field(default_factory=dict)

    model_config = {"populate_by_name": True}

    @property
    def is_success(self) -> bool:
        return self.status_code == "0000" or "success" in self.status_description.lower()
