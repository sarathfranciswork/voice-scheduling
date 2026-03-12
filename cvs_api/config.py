"""
CVS API configuration -- base URLs, API keys, experience UUIDs, and default headers.

These values were extracted from the captured API traffic during Phase 1 (guest)
and authenticated capture sessions.
"""

BASE_URL = "https://www.cvs.com"

# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------
TOKEN_API_KEY = "6TiidoRjpQG3uSjKU33lgq97MAuVBtpz"
EXPERIENCE_API_KEY = "HGNLXaQhG8CtglhHBvA7XD2TFnso1Scx"
CONTENT_API_KEY = "5fmbGDY003CAfvb3nPPxI9qyjuGfugG2"
INTROSPECT_API_KEY = "cnkL3GygZ8GgwivKfflt4q9R9UuROI4M"
AUTH_API_KEY = "2fIIfA47pLR0ZBAca94e0FO7ionmxg4v"

# ---------------------------------------------------------------------------
# Guest experience UUIDs -- scheduling steps
# ---------------------------------------------------------------------------
EXPERIENCE_UUIDS = {
    "eligible_vaccines": "9e69c442-990b-4811-9027-8a82e0821291",
    "eligibility_questions": "039ef9a3-c229-4f42-90c4-b0200115c36e",
    "vaccine_eligibility_check": "bef0bbbd-8500-4ef5-8da3-680b744988a2",
    "msft_oauth_token": "502014d6-a7e7-4840-b5e4-25b0ccfe035e",
    "locator_time_slots": "7b584f90-9ddb-49f2-bc4e-724ba766ed0e",
    "available_time_slots": "6692e0f6-323a-4d1b-a40a-7a85bd87d468",
    "soft_reserve": "59f7ec75-4eb3-49a6-b230-9dd89a58e470",
    "get_questionnaire": "a0521318-471f-47bb-a31d-8d79803f4749",
    "address_typeahead": "263a57ad-9f65-47e0-b3f8-a4d2341f0ffd",
    "patient_details": "d9e2b69b-8f12-4e3c-b770-19be6c9504e9",
    "submit_questionnaire": "20b2a414-79cb-4317-b3a7-2cf77608bd4a",
    "get_user_schedule": "717d9390-f185-4c36-8e6d-48dd58426eaf",
    "confirm_appointment": "ba6fe0cb-d389-4071-a1c3-956e7b950640",
}

# Guest experience name headers (x-experience-name)
EXPERIENCE_NAMES = {
    "eligible_vaccines": "getEligibleVaccinesForGuest",
    "eligibility_questions": "eligibilityQuestions",
    "vaccine_eligibility_check": "vaccineEligibilityCheck",
    "msft_oauth_token": "msftOauthTokenPublicAuth",
    "locator_time_slots": "locatorTimeSlots",
    "available_time_slots": "getAvailableTimeSlots",
    "soft_reserve": "softReserveForPublic",
    "get_questionnaire": "getQuestionnaireForPublicAuth",
    "address_typeahead": "preciselyServicePublicAuth",
    "patient_details": "patientDetailsGuest",
    "submit_questionnaire": "questionnaireMutationPublicAuth",
    "get_user_schedule": "getUserSchedulePublicAuth",
    "confirm_appointment": "confirmationForPublicAuth",
}

# ---------------------------------------------------------------------------
# Authenticated experience UUIDs -- login, profile, appointments, cancellation
# ---------------------------------------------------------------------------
AUTH_EXPERIENCE_UUIDS = {
    "kmsi_auto_login": "21201d73-8dfd-48ae-8b51-08805b8db802",
    "mfa_login": "0406807d-b6b3-465d-b02d-a8afe67834c7",
    "password_login": "56c226b9-6934-4c9e-86cc-f72e4a344280",
    "patient_profile": "ae59e1c7-0fc5-455b-82f1-f95bc6701163",
    "upcoming_appointments": "c9e58296-9af4-4c7f-89a6-8c2160af16a8",
    "cancel_appointment": "e9086e0c-b741-4b2c-96aa-142fd2377307",
    "verify_xid": "802708ae-f861-4fd2-99a2-9dc19e282930",
    "upcoming_appointments_xid": "1a2fd345-f573-48d4-9588-c4b7fcd052ac",
}

AUTH_EXPERIENCE_NAMES = {
    "patient_profile": "patientProfile",
    "upcoming_appointments": "upcomingAppointments",
    "cancel_appointment": "cancelAppointment",
    "verify_xid": "verifyXid",
    "upcoming_appointments_xid": "upcomingAppointmentsSingleAppt",
}

# ---------------------------------------------------------------------------
# Endpoint paths
# ---------------------------------------------------------------------------
TOKEN_PATH = "/api/guest/v1/token"
INTROSPECT_PATH = "/api/retail/token/v1/introspect"
EXPERIENCE_PATH = "/scheduling/client/experience/v2/load"
STORE_LOCATOR_PATH = "/api/locator/v2/stores"
CONTENT_PATH = "/api/unified/scheduling/v2/content"

CVS_LOGIN_URL = "https://www.cvs.com/account-login/look-up?icid=cvsheader%3Asignin&screenname=%2F"
AUTH_EXPERIENCE_PATH = "/api/auth/experience/v2/load"
AUTH_LOGOUT_PATH = "/api/auth/experience/v1/load"

# ---------------------------------------------------------------------------
# Default headers shared across guest experience API calls
# ---------------------------------------------------------------------------
DEFAULT_EXPERIENCE_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "content-type": "application/json",
    "x-route": "I90health",
    "api-key": "experienceUrl",
    "access-control-expose-headers": "grid",
    "cat": "NGS_IMZ",
    "category": "NGS_IMZ",
    "x-cat": "NGS_WEB",
    "adrum": "isAjax:true",
    "x-channel": "WEB",
}

# Authenticated flows use NGS_CANCEL_RESCH category
AUTH_EXPERIENCE_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "content-type": "application/json",
    "x-route": "I90health",
    "api-key": "experienceUrl",
    "access-control-expose-headers": "grid",
    "cat": "NGS_CANCEL_RESCH",
    "category": "NGS_CANCEL_RESCH",
    "x-cat": "NGS_WEB",
    "adrum": "isAjax:true",
    "x-channel": "WEB",
}

# ---------------------------------------------------------------------------
# Token / session settings
# ---------------------------------------------------------------------------
TOKEN_REFRESH_BUFFER_SECONDS = 60
DEFAULT_TOKEN_TTL_SECONDS = 899
REQUEST_TIMEOUT_SECONDS = 30
