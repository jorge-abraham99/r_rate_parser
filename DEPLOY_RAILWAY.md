# Deploying To Railway

## Short Answer

Yes. Railway can give this app a public domain you can share.

The important detail is that Railway does **not** give every service a public domain automatically. After the service is deployed, you need to go to the service's Networking settings and click `Generate Domain`. That gives you a Railway-provided domain in the `*.up.railway.app` format. You can also attach a custom domain later.

## Why This App Needs Special Handling

This app is not just a stateless API.

It writes real application data to disk:

- imported source files
- run artifacts
- review packs
- approval records
- approved warehouse tables

Those live under:

- `./data`

On Railway, container filesystems are ephemeral across deploys and restarts unless you attach a persistent volume.

For this app, that means:

- without a volume, imports and approved data can disappear
- with a volume mounted to `/app/data`, the current local filesystem model will persist properly

## Files Added For Railway

This repo includes:

- `railway.json`

That config sets:

- the start command
- the healthcheck path
- restart policy

The app healthcheck endpoint is:

- `/api/health`

## Recommended Railway Setup

### 1. Create The Service

Deploy this repo from GitHub into Railway as a single web service.

Railway should build it with its normal Python flow and start it with:

```bash
uvicorn rate_ingest.api:app --host 0.0.0.0 --port $PORT
```

### 2. Attach A Persistent Volume

Create a volume and mount it to:

```text
/app/data
```

That mount path matters because the app writes to `./data`, and Railway documents that relative writes from an app in `/app` should use a volume mounted at `/app/data`.

### 3. Generate A Public Domain

After deployment:

1. Open the service in Railway
2. Go to `Settings` -> `Networking`
3. Find `Public Networking`
4. Click `Generate Domain`

That will give you a Railway-managed domain like:

```text
your-service.up.railway.app
```

### 4. Confirm The App Is Healthy

Check:

- `https://<your-domain>/api/health`
- `https://<your-domain>/ui/`
- `https://<your-domain>/ui/import.html`

## Deploy Steps

### Option A: GitHub Deploy

1. Push the repo to GitHub
2. In Railway, create a new project
3. Choose `Deploy from GitHub repo`
4. Select this repository
5. Let Railway build and deploy it
6. Attach a volume to `/app/data`
7. Generate the public domain

### Option B: Railway CLI

If you use the Railway CLI:

```bash
railway login
railway link
railway up
```

Then attach the volume in Railway and generate the public domain from the dashboard.

## Stage 7 trial cutover

The application is ready to run its authenticated Postgres trial, but Railway must be switched deliberately. Set these variables in the Railway service, never in browser code:

```text
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_PUBLISHABLE_KEY=<publishable-key>
SUPABASE_DB_URL=<server-only SSL PostgreSQL connection string>
AUTH_REQUIRED=true
RATE_STORAGE_BACKEND=postgres
SOURCE_STORAGE_BACKEND=supabase
SUPABASE_STORAGE_BUCKET=rate-sources
```

`SUPABASE_DB_URL` is a server secret. `/api/public-config` exposes only the URL and publishable key needed by the browser; it must never expose the database URL, a JWT secret, or a service-role key.

Stage 8 source uploads use the publishable key and the signed-in operator's access token. Do not add a Storage secret or service-role key to Railway.

This trial intentionally starts with an empty Postgres rate library. Do not run a CSV backfill before changing `RATE_STORAGE_BACKEND`; the existing CSV rates will not appear in Postgres. Keep the CSV configuration available as the short-term rollback path.

The optional backfill command is retained only for a later recovery/migration decision:

```bash
python -m rate_ingest backfill-postgres <organization-uuid>
python -m rate_ingest backfill-postgres <organization-uuid> --apply
```

The first command is read-only. The second copies every recoverable CSV import and its parsed entities into that organization. It fails before writing if any import lacks its source file or structured run bundle, and it is safe to retry.

The optional backfill requires `SOURCE_STORAGE_BACKEND=filesystem`. Do not combine it with the Stage 8 Storage setting because the CLI has no signed-in user token.

In Supabase Auth → URL Configuration, keep public sign-up disabled and use the password page as the Site URL. Dashboard-sent invitations do not supply a custom `redirectTo`, so they use the Site URL:

```text
Site URL:
https://rrateparser-production.up.railway.app/ui/set-password.html

Allowed Redirect URLs:
https://rrateparser-production.up.railway.app/
https://rrateparser-production.up.railway.app/ui/set-password.html
```

Add that same URL to Supabase's allowed redirect URLs. Invited users follow it to choose a password, then the app checks `/api/me`; an account without an `organization_members` row is denied Rate Desk access. Create the organization membership and deliberate `viewer`, `operator`, or `admin` role before sending the invitation.

## What To Test After Deploy

Use one known file first.

Recommended Stage 7 smoke test:

1. While logged out, confirm `/ui/` redirects to login and `/api/rate-desk` and `/api/imports` return `401`.
2. Accept a fresh invitation at `/ui/set-password.html`; verify a mismatched password is rejected and an expired/reused link gives the safe generic message.
3. Sign in as a viewer: Rate Desk and imports work, while upload and approval return `403`.
4. Sign in as an operator: upload the MSC sample, review it, approve it, and search it from Rate Desk.
5. Approve a replacement for the same carrier and verify the previous import becomes archived only when the new import is approved.
6. Confirm the Rate Desk starts empty, then verify only the newly approved Postgres import appears before inviting the wider trial group.

Then repeat with:

- `rate_sheet_files/COSCO FAR-EAST RATES.xlsx`
- `rate_sheet_files/MAERSK Q-1, INDIA AND FAR-EAST.xlsx`
- `RE_ Far East Wastepaper for April - Reudan.eml`

## Known Limits Of Railway Deployment Right Now

This trial deployment has limits:

- review artifacts and CSV rollback data still depend on the `/app/data` volume
- original uploads use private Supabase Storage when `SOURCE_STORAGE_BACKEND=supabase`
- rollback to `RATE_STORAGE_BACKEND=csv` does not include imports created only in Postgres after cutover
- no background job system
- no unknown-file fallback workflow yet

Postgres owns import/rate data during the trial; filesystem artifacts remain for review/debugging.

## Recommended Summary

Railway is a reasonable way to get a shareable live demo quickly.

The minimum correct Stage 7 setup is:

- deploy repo
- attach volume to `/app/data`
- generate Railway public domain
- configure Supabase Auth and the exact invitation redirect
- accept that the Postgres trial begins without the old CSV rates
- set Railway to `RATE_STORAGE_BACKEND=postgres`

Without the volume, review artifacts and original uploaded files may disappear on restart or redeploy.
