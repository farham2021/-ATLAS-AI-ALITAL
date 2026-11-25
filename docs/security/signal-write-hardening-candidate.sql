-- Candidate only: validate backend writer credentials in staging before deployment.
BEGIN;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON TABLE public.atlas_free_alert_events FROM PUBLIC, anon, authenticated;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON TABLE public.atlas_hourly_signal_snapshots FROM PUBLIC, anon, authenticated;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON TABLE public.atlas_signal_lifecycle FROM PUBLIC, anon, authenticated;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON TABLE public.atlas_signal_lifecycle_events FROM PUBLIC, anon, authenticated;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON TABLE public.atlas_signal_notification_state FROM PUBLIC, anon, authenticated;
DO $$
DECLARE t text; r text; p text;
BEGIN
FOREACH t IN ARRAY ARRAY['public.atlas_free_alert_events','public.atlas_hourly_signal_snapshots','public.atlas_signal_lifecycle','public.atlas_signal_lifecycle_events','public.atlas_signal_notification_state'] LOOP
FOREACH r IN ARRAY ARRAY['anon','authenticated'] LOOP
FOREACH p IN ARRAY ARRAY['INSERT','UPDATE','DELETE','TRUNCATE'] LOOP
IF has_table_privilege(r,t,p) THEN RAISE EXCEPTION 'Unexpected write privilege: % % %',r,t,p; END IF;
END LOOP;
END LOOP;
END LOOP;
END $$;
COMMIT;
