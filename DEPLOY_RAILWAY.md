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

## Environment Notes

This app does not currently require an AI API key.

No extra application secrets are required for the current deterministic parser flow unless you add them later.

If you later add LLM-assisted parsing, that will likely introduce one or more new environment variables.

## What To Test After Deploy

Use one known file first.

Recommended smoke test:

1. Open `/ui/import.html`
2. Upload `rate_sheet_files/MSC - FAR EAST RATES JAN.xlsx`
3. Confirm an import appears
4. Open the import detail
5. Approve it
6. Open `/ui/`
7. Confirm approved rates appear in the quote flow

Then repeat with:

- `rate_sheet_files/COSCO FAR-EAST RATES.xlsx`
- `rate_sheet_files/MAERSK Q-1, INDIA AND FAR-EAST.xlsx`
- `RE_ Far East Wastepaper for April - Reudan.eml`

## Known Limits Of Railway Deployment Right Now

This deployment is suitable for demo/internal use, but there are limits:

- data is filesystem-backed, not database-backed
- no auth layer yet
- no concurrency protection around local file writes
- no background job system
- no unknown-file fallback workflow yet

So this is fine for showing the product and running internal demos, but it is not the final production architecture.

## Recommended Summary

Railway is a reasonable way to get a shareable live demo quickly.

The minimum correct setup is:

- deploy repo
- attach volume to `/app/data`
- generate Railway public domain

Without the volume, the demo may appear to work but lose state on restart or redeploy.
