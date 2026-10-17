# buyer_agent

Buyer-side comparison service (FastAPI). Tests: `.venv\Scripts\python -m pytest -q`.

## Run

```
python -m uvicorn --factory buyer_agent.api:app_factory --host 127.0.0.1 --port 8765 --no-proxy-headers
```

- Always pass `--no-proxy-headers`. Rate limits and the auth-failure lockout use the socket peer
  address. With proxy headers on, a client behind a local proxy could rotate `X-Forwarded-For`
  to dodge them. Put any proxy in front only if it also sits on the loopback and is the sole caller.
- `BUYER_AGENT_TOKEN` must be at least 32 characters (for example `python -c "import secrets; print(secrets.token_urlsafe(32))"`).

## Paths are derived by the website, never by the user

The API opens files under `DATA_ROOT` for whatever paths the caller sends, and it does not bind a
`listing_id` to those paths. Any holder of the token can compare any file under `DATA_ROOT`.
The website server must therefore build `listing_splat`, `buyer_splat`, `view_pairs.manifest_path`
and the `listing_id` itself from its own records. Never forward a path or id that came from a browser.
