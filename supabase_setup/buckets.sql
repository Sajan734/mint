-- Storage buckets for the `mint` Supabase project (already created in the dashboard; this file
-- recreates them on a fresh project). Run in the SQL editor. Idempotent.
--
-- Supabase reserves the name `public`, so ARCHITECTURE.md's `public` bucket is `assets` here.
-- No storage policies: only the service-role key (Modal backends) reads/writes; `assets` is
-- publicly readable by URL; the iOS app uploads to `scans` with signed URLs from the backend.

insert into storage.buckets (id, name, public)
values
  ('scans',    'scans',    false),  -- uploaded videos/frames + manifests (signed URLs only)
  ('assets',   'assets',   true),   -- splats, thumbnails, cube views, references, renders (public read)
  ('fixtures', 'fixtures', false)   -- raw eval and test captures
on conflict (id) do nothing;
