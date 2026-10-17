-- Mint scanner storage: run once in Supabase → SQL Editor.
-- A private bucket for raw scans. Nobody can read or write it directly with the public (anon) key:
-- the phone uploads through one-time URLs signed by the `scan-upload` Edge Function, and
-- reconstruction downloads with the service-role key (server side only, never in an app).
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('scans', 'scans', false, 209715200,  -- 200 MB per file; a 20 s scan is ~20 MB
        array['video/mp4', 'application/json', 'application/x-ndjson', 'image/jpeg'])
on conflict (id) do update
  set file_size_limit = excluded.file_size_limit,
      allowed_mime_types = excluded.allowed_mime_types;
