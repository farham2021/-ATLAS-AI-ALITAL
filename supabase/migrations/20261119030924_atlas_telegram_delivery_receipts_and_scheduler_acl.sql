CREATE TABLE IF NOT EXISTS public.atlas_telegram_delivery_receipts (
    receipt_id text PRIMARY KEY CHECK (receipt_id ~ '^[0-9a-f]{64}$'),
    workflow_run_id text NOT NULL,
    run_key text,
    cycle text NOT NULL,
    destination_kind text NOT NULL CHECK (destination_kind IN ('private', 'group', 'other')),
    destination_hash text NOT NULL CHECK (destination_hash ~ '^[0-9a-f]{64}$'),
    method text NOT NULL CHECK (method IN ('sendMessage', 'sendPhoto', 'sendDocument', 'sendAudio')),
    message_id bigint NOT NULL CHECK (message_id > 0),
    telegram_date timestamptz,
    recorded_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.atlas_telegram_delivery_receipts ENABLE ROW LEVEL SECURITY;
REVOKE ALL PRIVILEGES ON TABLE public.atlas_telegram_delivery_receipts FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT ON TABLE public.atlas_telegram_delivery_receipts TO service_role;

-- Scheduler REST calls use the service role and lease RPCs; client roles need no table access.
REVOKE ALL PRIVILEGES ON TABLE public.atlas_scheduler_runs FROM PUBLIC, anon, authenticated;
