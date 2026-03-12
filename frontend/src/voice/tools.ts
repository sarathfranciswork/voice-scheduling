import { tool } from '@openai/agents/realtime';
import { z } from 'zod';

async function callTool(name: string, args: Record<string, unknown>): Promise<string> {
  const res = await fetch('/api/realtime/tool-call', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, arguments: args }),
  });
  if (!res.ok) {
    const err = await res.text();
    return `Error: ${err}`;
  }
  const data = await res.json();
  return data.result;
}

export const getEligibleVaccines = tool({
  name: 'get_eligible_vaccines',
  description: 'Get the list of vaccines a patient is eligible for based on their date of birth.',
  parameters: z.object({
    date_of_birth: z.string().describe('Patient date of birth in MM/DD/YYYY format'),
  }),
  execute: async (args) => callTool('get_eligible_vaccines', args),
});

export const checkVaccineEligibility = tool({
  name: 'check_vaccine_eligibility',
  description: 'Check detailed vaccine eligibility and get NDC codes needed for store search.',
  parameters: z.object({
    date_of_birth: z.string().describe('Patient DOB in MM/DD/YYYY format'),
    vaccine_codes: z.array(z.string()).describe('List of vaccine codes to check'),
  }),
  execute: async (args) => callTool('check_vaccine_eligibility', args),
});

export const searchStores = tool({
  name: 'search_stores',
  description: 'Search for CVS pharmacy locations that have vaccine availability near a location.',
  parameters: z.object({
    address: z.string().describe('ZIP code, city/state, or street address'),
    radius: z.number().optional().describe('Search radius in miles, default 35'),
    max_results: z.number().optional().describe('Maximum stores to return, default 10'),
  }),
  execute: async (args) => callTool('search_stores', args),
});

export const getAvailableTimeSlots = tool({
  name: 'get_available_time_slots',
  description: 'Get available appointment time slots at CVS pharmacies for a given date.',
  parameters: z.object({
    visit_date: z.string().describe('Date in YYYY-MM-DD format'),
    clinic_id: z.string().optional().describe('Specific clinic ID to filter by'),
  }),
  execute: async (args) => callTool('get_available_time_slots', args),
});

export const getStoreDetails = tool({
  name: 'get_store_details',
  description: 'Get detailed information about a specific CVS pharmacy including address, phone, and hours.',
  parameters: z.object({
    store_id: z.string().describe('The CVS store ID'),
  }),
  execute: async (args) => callTool('get_store_details', args),
});

export const softReserveSlot = tool({
  name: 'soft_reserve_slot',
  description: 'Temporarily reserve a time slot while the patient completes registration.',
  parameters: z.object({
    clinic_id: z.string().describe('The clinic ID'),
    appointment_date: z.string().describe('Date in YYYY-MM-DD format'),
    appointment_time: z.string().describe('Time in HH:MM format'),
  }),
  execute: async (args) => callTool('soft_reserve_slot', args),
});

export const submitPatientDetails = tool({
  name: 'submit_patient_details',
  description: 'Submit patient demographic information for the appointment.',
  parameters: z.object({
    first_name: z.string().describe('Patient first name'),
    last_name: z.string().describe('Patient last name'),
    email: z.string().describe('Patient email address'),
    phone_number: z.string().describe('Patient phone number'),
    street_address: z.string().describe('Street address'),
    city: z.string().describe('City'),
    state: z.string().describe('State abbreviation'),
    zip_code: z.string().describe('ZIP code'),
    gender: z.string().optional().describe('Gender, default Male'),
  }),
  execute: async (args) => callTool('submit_patient_details', args),
});

export const getQuestionnaire = tool({
  name: 'get_questionnaire',
  description: 'Retrieve the pre-appointment health screening questionnaire.',
  parameters: z.object({}),
  execute: async () => callTool('get_questionnaire', {}),
});

export const submitQuestionnaire = tool({
  name: 'submit_questionnaire',
  description: 'Submit completed health screening questionnaire answers.',
  parameters: z.object({
    answers: z.array(z.record(z.string(), z.unknown())).describe('Array of answer objects'),
  }),
  execute: async (args) => callTool('submit_questionnaire', args),
});

export const getUserSchedule = tool({
  name: 'get_user_schedule',
  description: 'Check if the patient already has an existing appointment.',
  parameters: z.object({}),
  execute: async () => callTool('get_user_schedule', {}),
});

export const confirmAppointment = tool({
  name: 'confirm_appointment',
  description: 'Final confirmation of the vaccine appointment.',
  parameters: z.object({}),
  execute: async () => callTool('confirm_appointment', {}),
});

export const addressTypeahead = tool({
  name: 'address_typeahead',
  description: 'Address autocomplete for patient address entry.',
  parameters: z.object({
    search_text: z.string().describe('Partial address to search'),
    max_results: z.number().optional().describe('Max results, default 5'),
  }),
  execute: async (args) => callTool('address_typeahead', args),
});

export const getPatientProfile = tool({
  name: 'get_patient_profile',
  description: "Get the authenticated user's CVS patient profile.",
  parameters: z.object({}),
  execute: async () => callTool('get_patient_profile', {}),
});

export const getMyAppointments = tool({
  name: 'get_my_appointments',
  description: "Get the authenticated user's upcoming vaccine appointments.",
  parameters: z.object({}),
  execute: async () => callTool('get_my_appointments', {}),
});

export const cancelAppointment = tool({
  name: 'cancel_appointment',
  description: 'Cancel an upcoming vaccine appointment.',
  parameters: z.object({
    appointment_id: z.string().describe('The appointment ID to cancel'),
  }),
  execute: async (args) => callTool('cancel_appointment', args),
});

export const allVoiceTools = [
  getEligibleVaccines,
  checkVaccineEligibility,
  searchStores,
  getAvailableTimeSlots,
  getStoreDetails,
  softReserveSlot,
  submitPatientDetails,
  getQuestionnaire,
  submitQuestionnaire,
  getUserSchedule,
  confirmAppointment,
  addressTypeahead,
  getPatientProfile,
  getMyAppointments,
  cancelAppointment,
];
