"""MCP tools for the scheduling workflow (reserve, patient, questionnaire, confirm)."""

from __future__ import annotations

from typing import Any


TOOL_DEFINITIONS = [
    {
        "name": "soft_reserve_slot",
        "description": (
            "Temporarily reserve a time slot so it is held while the patient completes "
            "their registration. Must be called after the user selects a time slot."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "scheduling_input": {
                    "type": "object",
                    "description": (
                        "Full scheduling input including clinicId, visitDate, "
                        "time slot details, and immunization codes."
                    ),
                },
            },
            "required": ["scheduling_input"],
        },
    },
    {
        "name": "submit_patient_details",
        "description": (
            "Submit patient demographic information: first name, last name, date of birth, "
            "gender, email, phone number, and address. Required after reserving a slot."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "patient_details_input": {
                    "type": "object",
                    "description": (
                        "Patient details payload including personal info and address. "
                        "Fields: firstName, lastName, dateOfBirth (YYYY-MM-DD), gender, "
                        "email, phoneNumber, address (street, city, state, zip)."
                    ),
                },
            },
            "required": ["patient_details_input"],
        },
    },
    {
        "name": "get_questionnaire",
        "description": (
            "Retrieve the pre-appointment health screening questionnaire that the patient "
            "must complete before the vaccination. Returns questions with answer options."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "questionnaire_input": {
                    "type": "object",
                    "description": "Questionnaire request payload with immunization codes and patient info.",
                },
            },
            "required": ["questionnaire_input"],
        },
    },
    {
        "name": "submit_questionnaire",
        "description": (
            "Submit the completed health screening questionnaire answers. "
            "Must be completed before confirming the appointment."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "scheduling_questionnaire_input": {
                    "type": "object",
                    "description": "Questionnaire answers payload with question IDs and selected answers.",
                },
            },
            "required": ["scheduling_questionnaire_input"],
        },
    },
    {
        "name": "get_user_schedule",
        "description": (
            "Check if the patient already has an existing appointment scheduled. "
            "Used for duplicate detection before confirming a new appointment."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "check_duplicate": {
                    "type": "boolean",
                    "description": "Whether to check for duplicate appointments (default true).",
                    "default": True,
                },
            },
        },
    },
    {
        "name": "confirm_appointment",
        "description": (
            "Final confirmation of the vaccine appointment. This is the last step in the "
            "scheduling flow. Returns a confirmation number and appointment summary. "
            "IMPORTANT: Only call this after all previous steps are complete."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "confirm_appointment_input": {
                    "type": "object",
                    "description": "Confirmation payload with all appointment details.",
                },
            },
            "required": ["confirm_appointment_input"],
        },
    },
    {
        "name": "address_typeahead",
        "description": (
            "Address autocomplete/typeahead for patient address entry. "
            "Returns address suggestions as the patient types their address."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "search_text": {
                    "type": "string",
                    "description": "Partial address text to search for.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of address suggestions (default 5).",
                    "default": 5,
                },
            },
            "required": ["search_text"],
        },
    },
]


async def handle_soft_reserve_slot(client: Any, arguments: dict) -> list[dict]:
    result = await client.soft_reserve_slot(
        scheduling_input=arguments["scheduling_input"],
    )
    return [{"type": "text", "text": _format_json(result)}]


async def handle_submit_patient_details(client: Any, arguments: dict) -> list[dict]:
    result = await client.submit_patient_details(
        patient_details_input=arguments["patient_details_input"],
    )
    return [{"type": "text", "text": _format_json(result)}]


async def handle_get_questionnaire(client: Any, arguments: dict) -> list[dict]:
    result = await client.get_questionnaire(
        questionnaire_input=arguments["questionnaire_input"],
    )
    return [{"type": "text", "text": _format_json(result)}]


async def handle_submit_questionnaire(client: Any, arguments: dict) -> list[dict]:
    result = await client.submit_questionnaire(
        scheduling_questionnaire_input=arguments["scheduling_questionnaire_input"],
    )
    return [{"type": "text", "text": _format_json(result)}]


async def handle_get_user_schedule(client: Any, arguments: dict) -> list[dict]:
    result = await client.get_user_schedule(
        check_duplicate=arguments.get("check_duplicate", True),
    )
    return [{"type": "text", "text": _format_json(result)}]


async def handle_confirm_appointment(client: Any, arguments: dict) -> list[dict]:
    result = await client.confirm_appointment(
        confirm_appointment_input=arguments["confirm_appointment_input"],
    )
    return [{"type": "text", "text": _format_json(result)}]


async def handle_address_typeahead(client: Any, arguments: dict) -> list[dict]:
    result = await client.address_typeahead(
        search_text=arguments["search_text"],
        max_results=arguments.get("max_results", 5),
    )
    return [{"type": "text", "text": _format_json(result)}]


HANDLERS = {
    "soft_reserve_slot": handle_soft_reserve_slot,
    "submit_patient_details": handle_submit_patient_details,
    "get_questionnaire": handle_get_questionnaire,
    "submit_questionnaire": handle_submit_questionnaire,
    "get_user_schedule": handle_get_user_schedule,
    "confirm_appointment": handle_confirm_appointment,
    "address_typeahead": handle_address_typeahead,
}


def _format_json(data: Any) -> str:
    import json
    return json.dumps(data, indent=2, default=str)
