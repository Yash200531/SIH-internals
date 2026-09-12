-- Export and retain protected alert history before an explicitly approved rollback.
DROP TABLE triage_outbox;
DROP TABLE triage_flag_history;
DROP TABLE triage_flag;
DROP FUNCTION reject_triage_history_mutation();
