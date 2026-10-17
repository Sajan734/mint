# Supabase for the scanner

The app uploads each scan to Storage, bucket **`scans`**, as `scans/{scan_id}/video.mp4` (+ `poses.jsonl`, `capture.json`, `thumb.jpg`). The app holds **no keys**: it asks the `scan-upload` Edge Function for one-time signed upload URLs, then PUTs the files.

## One-time setup (~5 minutes)

1. **Project:** create one at [supabase.com](https://supabase.com) (free tier is fine). Note the project URL: `https://<ref>.supabase.co`.
2. **Bucket:** Dashboard → SQL Editor → paste [`setup.sql`](setup.sql) → Run.
3. **Edge Function:** either
   - Dashboard → Edge Functions → *Deploy a new function* → *Via editor* → name it **`scan-upload`** → paste [`functions/scan-upload/index.ts`](functions/scan-upload/index.ts) → Deploy → in its settings, **turn off "Enforce JWT verification"**; or
   - CLI: `brew install supabase/tap/supabase && supabase login && supabase functions deploy scan-upload --no-verify-jwt --project-ref <ref>` (run from `scanner/`).
4. **Check it:**
   ```bash
   curl -s -X POST https://<ref>.supabase.co/functions/v1/scan-upload \
     -H 'Content-Type: application/json' \
     -d '{"scan_id":"00000000-0000-4000-8000-000000000000","files":["capture.json"]}'
   # → {"uploads":[{"file":"capture.json","path":"scans/…","signed_url":"https://…"}]}
   ```
5. **App:** in `scanner/ios/project.yml` set `MINT_UPLOAD_URL: https://<ref>.supabase.co/functions/v1/scan-upload`, then `cd scanner/ios && xcodegen` and ⌘R. After each scan the card shows *Sending to Mint …%* → *Sent to Mint*.

## Getting scans (reconstruction)

```bash
export SUPABASE_URL=https://<ref>.supabase.co SUPABASE_SERVICE_ROLE_KEY=...   # Settings → API; server side only
python3 scanner/tools/fetch_scan.py latest ./scans
```

## Notes

- The function only signs `video.mp4`, `poses.jsonl`, `capture.json`, `thumb.jpg` under a UUID folder, and the bucket only accepts those types up to 200 MB. It's open to anyone with its URL (fine for a hackathon; delete or add auth afterwards).
- Per CLAUDE.md, D owns the team's Supabase schema; at merge this bucket + function fold into the team project (or the API's `POST /scans`).
