-- ATLAS operational health audit (read-only, no mutations)
-- Run against the ATLAS Supabase project using a privileged SQL editor.
-- All timestamps are UTC; do not infer Telegram receipt from a SENT status.
select cycle,status,count(*) as runs,max(completed_at) as latest_completion
from public.atlas_scheduler_runs
group by cycle,status order by cycle,status;

select run_key,cycle,lease_until
from public.atlas_scheduler_runs
where status='RUNNING' and lease_until < now()
order by lease_until;

select telegram_status,count(*) as events,max("timestamp") as latest_event,
       count(*) filter (where sent is true) as marked_sent
from public.atlas_free_alert_events
group by telegram_status order by count(*) desc;

select date_trunc('day',"timestamp") as day_utc,
       count(*) as alerts,
       count(*) filter (where telegram_status='SENT') as sent,
       count(*) filter (where telegram_status='STORAGE_ONLY') as storage_only
from public.atlas_free_alert_events
where "timestamp" >= now() - interval '7 days'
group by 1 order by 1 desc;

select max(sent_at) as latest_desk_delivery,count(*) as total_desk_deliveries
from public.atlas_desk_deliveries;
