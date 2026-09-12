DROP TRIGGER IF EXISTS clinical_summary_signed_immutable ON clinical_summary_workflow;
DROP FUNCTION IF EXISTS prevent_signed_clinical_summary_mutation();
DROP TRIGGER IF EXISTS clinical_summary_action_append_only ON clinical_summary_action;
DROP FUNCTION IF EXISTS prevent_clinical_summary_action_mutation();
DROP TABLE IF EXISTS clinical_summary_outbox;
DROP TABLE IF EXISTS clinical_summary_action;
DROP TABLE IF EXISTS clinical_summary_workflow;
DROP TABLE IF EXISTS confirmed_encounter_summary_context;
