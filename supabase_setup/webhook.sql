-- Starts the live pipeline when the iOS app's video lands in Storage: an INSERT into storage.objects for
-- scans/{scan_id}/video.mp4 POSTs {bucket_id, name} to the Modal endpoint `on_upload` (gsplat/app.py), which
-- checks the file is really there, then runs splat -> listing/ (Jev) -> assets/listings/ once per scan.
-- Run once in the SQL editor of the `mint` project. Idempotent. Uses pg_net (async HTTP, never blocks the upload).
-- The URL is the deployed endpoint (`modal deploy gsplat/app.py` prints it); it carries no secret.

create extension if not exists pg_net with schema extensions;

create or replace function public.mint_on_scan_upload() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  if new.bucket_id = 'scans' and new.name like '%/video.mp4' then
    perform net.http_post(
      url := 'https://doalnikhil--mint-gsplat-on-upload.us-east.modal.run',
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
