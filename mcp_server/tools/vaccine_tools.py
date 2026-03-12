"""MCP tools for vaccine eligibility operations."""

from __future__ import annotations

from typing import Any


TOOL_DEFINITIONS = [
    {
        "name": "get_eligible_vaccines",
        "description": (
            "Get the list of vaccines a patient is eligible for based on their date of birth. "
            "Returns vaccine names, codes, and NDC information. "
            "This should be the first step in the scheduling flow."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "date_of_birth": {
                    "type": "string",
                    "description": "Patient date of birth in YYYY-MM-DD format.",
                },
            },
            "required": ["date_of_birth"],
        },
    },
    {
        "name": "check_vaccine_eligibility",
        "description": (
            "Check detailed vaccine eligibility with screening questions. "
            "Uses the output from eligibility questionnaire answers."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "vaccine_eligibility_input": {
                    "type": "object",
                    "description": "Eligibility screening payload including vaccine codes and answers.",
                },
            },
            "required": ["vaccine_eligibility_input"],
        },
    },
]


async def handle_get_eligible_vaccines(client: Any, arguments: dict) -> list[dict]:
    result = await client.get_eligible_vaccines(
        date_of_birth=arguments["date_of_birth"],
    )
    return [{"type": "text", "text": _format_json(result)}]


async def handle_check_vaccine_eligibility(client: Any, arguments: dict) -> list[dict]:
    result = await client.check_vaccine_eligibility(
        vaccine_eligibility_input=arguments["vaccine_eligibility_input"],
    )
    return [{"type": "text", "text": _format_json(result)}]


HANDLERS = {
    "get_eligible_vaccines": handle_get_eligible_vaccines,
    "check_vaccine_eligibility": handle_check_vaccine_eligibility,
}


def _format_json(data: Any) -> str:
    import json
    return json.dumps(data, indent=2, default=str)
