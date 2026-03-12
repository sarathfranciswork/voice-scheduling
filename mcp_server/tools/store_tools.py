"""MCP tools for store search and time slot operations."""

from __future__ import annotations

from typing import Any


TOOL_DEFINITIONS = [
    {
        "name": "search_stores",
        "description": (
            "Search for CVS pharmacy locations that have vaccine availability near a given location. "
            "Returns a list of clinics with addresses, distances, and available dates. "
            "At least one of zip_code or city+state is required."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "zip_code": {
                    "type": "string",
                    "description": "ZIP code to search near.",
                },
                "city": {
                    "type": "string",
                    "description": "City name for location search.",
                },
                "state": {
                    "type": "string",
                    "description": "Two-letter state code (e.g. 'MA').",
                },
                "vaccine_codes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of vaccine codes to filter availability (from get_eligible_vaccines).",
                },
                "radius": {
                    "type": "integer",
                    "description": "Search radius in miles (default 35).",
                    "default": 35,
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of stores to return (default 10).",
                    "default": 10,
                },
                "date_from": {
                    "type": "string",
                    "description": "Earliest date for availability in YYYY-MM-DD format.",
                },
            },
        },
    },
    {
        "name": "get_available_time_slots",
        "description": (
            "Get available appointment time slots at a specific CVS pharmacy for a given date. "
            "Returns morning, afternoon, and evening time slots. "
            "Use after search_stores to get clinic_id and available dates."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "clinic_id": {
                    "type": "string",
                    "description": "Clinic/store identifier (from search_stores results).",
                },
                "visit_date": {
                    "type": "string",
                    "description": "Date for the appointment in YYYY-MM-DD format.",
                },
                "vaccine_codes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Vaccine codes being scheduled.",
                },
            },
            "required": ["clinic_id", "visit_date", "vaccine_codes"],
        },
    },
    {
        "name": "get_store_details",
        "description": (
            "Get detailed information about a specific CVS pharmacy including "
            "full address, phone numbers, operating hours, and services."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "store_id": {
                    "type": "string",
                    "description": "CVS store identifier.",
                },
            },
            "required": ["store_id"],
        },
    },
]


async def handle_search_stores(client: Any, arguments: dict) -> list[dict]:
    result = await client.search_stores(
        zip_code=arguments.get("zip_code"),
        city=arguments.get("city"),
        state=arguments.get("state"),
        vaccine_codes=arguments.get("vaccine_codes"),
        radius=arguments.get("radius", 35),
        max_results=arguments.get("max_results", 10),
        date_from=arguments.get("date_from"),
    )
    return [{"type": "text", "text": _format_json(result)}]


async def handle_get_available_time_slots(client: Any, arguments: dict) -> list[dict]:
    result = await client.get_available_time_slots(
        clinic_id=arguments["clinic_id"],
        visit_date=arguments["visit_date"],
        vaccine_codes=arguments["vaccine_codes"],
    )
    return [{"type": "text", "text": _format_json(result)}]


async def handle_get_store_details(client: Any, arguments: dict) -> list[dict]:
    result = await client.get_store_details(store_id=arguments["store_id"])
    return [{"type": "text", "text": _format_json(result)}]


HANDLERS = {
    "search_stores": handle_search_stores,
    "get_available_time_slots": handle_get_available_time_slots,
    "get_store_details": handle_get_store_details,
}


def _format_json(data: Any) -> str:
    import json
    return json.dumps(data, indent=2, default=str)
