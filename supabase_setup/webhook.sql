-- Starts the live pipeline when the iOS app's video lands in Storage: an INSERT into storage.objects for
-- scans/{scan_id}/video.mp4 POSTs {bucket_id, name} to the Modal endpoint `on_upload` (gsplat/app.py), which
-- checks the file is really there, then runs splat -> listing/ (Jev) -> assets/listings/ once per scan.
-- session.json (the scan was requested / picked up) and bottom.mp4 (uploaded before video.mp4) also POST: they
-- only warm a GPU container, so the cold start happens while the seller is still scanning. rescan.mp4 (a buyer's
-- verify rescan, uploaded last) starts the comparison with the listing (Splatter.run_verify).
-- Run once in the SQL editor of the `mint` project, and again after moving to another Modal workspace. Idempotent.
-- Uses pg_net (async HTTP, never blocks the upload). Don't paste this file as is: `python gsplat/client.py urls`
-- prints it with the deployed on_upload URL of the workspace in .env filled in (the URL carries no secret).

create extension if not exists pg_net with schema extensions;

create or replace function public.mint_on_scan_upload() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  if new.bucket_id = 'scans' and (new.name like '%/video.mp4' or new.name like '%/session.json'
                                  or new.name like '%/bottom.mp4' or new.name like '%/rescan.mp4') then
    perform net.http_post(
      url := '<on_upload URL: python gsplat/client.py urls>',
      body := jsonb_build_object('bucket_id', new.bucket_id, 'name', new.name),
      timeout_milliseconds := 10000
    );
  end if;
  return new;
end;
$$;

drop trigger if exists mint_on_scan_upload on storage.objects;
create trigger mint_on_scan_upload after insert on storage.objects
  for each row execute function public.mint_on_scan_upload();

-- Check: select id, status_code, content::text, created from net._http_response order by created desc limit 5;
-- Remove: drop trigger mint_on_scan_upload on storage.objects; drop function public.mint_on_scan_upload();
