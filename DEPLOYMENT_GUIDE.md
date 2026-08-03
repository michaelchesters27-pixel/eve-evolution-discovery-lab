# EVE Evolution Discovery Lab — Deployment Guide

This is a **new second project**. Do not replace or edit the existing `eve-algo-lab` repository.

## 1. Create the new Supabase project

1. Create a separate Supabase project.
2. Open SQL Editor.
3. Paste the entire contents of `SUPABASE_SETUP.sql`.
4. Run it once.
5. Copy the new project's URL and service-role key.

## 2. Create a new GitHub repository

Suggested repository name:

`eve-evolution-discovery-lab`

Upload the contents of the inner `eve-evolution-discovery-lab` folder. This project contains fewer than 100 files and can be uploaded through the GitHub web uploader.

## 3. Deploy a new Railway service

Use the repository's `/railway` folder as the Railway root directory.

Add these Railway variables:

```text
SOURCE_SUPABASE_URL=<existing EVE Supabase URL>
SOURCE_SUPABASE_SERVICE_ROLE_KEY=<existing EVE service-role key>
DISCOVERY_SUPABASE_URL=<new Discovery Supabase URL>
DISCOVERY_SUPABASE_SERVICE_ROLE_KEY=<new Discovery service-role key>
ADMIN_TOKEN=<long random secret>
CORS_ORIGINS=https://<new-netlify-site>.netlify.app
SOURCE_SYMBOL=XAU/USD
SOURCE_SNAPSHOT_INTERVAL=15min
AUTONOMOUS_ENABLED=true
```

No Twelve Data key is required. The current EVE project continues collecting historical and live market-state data.

After deployment, open Railway's public URL and verify:

`/health`

returns `"ok": true`.

## 4. Deploy a new Netlify site

Connect the new GitHub repository.

The included `netlify.toml` uses:

- Base directory: `frontend`
- Publish directory: `.`
- Functions directory: `netlify/functions`

Add this Netlify variable:

```text
DISCOVERY_RAILWAY_URL=https://<your-new-railway-service>.up.railway.app
```

Redeploy Netlify.

## 5. What happens after deployment

The worker will:

1. Import the six-year completed snapshot history from existing EVE.
2. Keep syncing new live snapshots as existing EVE creates them.
3. Compose candidates.
4. Test and reject candidates.
5. Start lineages for survivors.
6. Mutate those lineages continuously.
7. Freeze qualifying champions.
8. Produce downloadable MT5 packages.

The first complete source sync may take several worker cycles. Progress is visible under **Data & Setup**.

## 6. Downloading an MT5 bot

When a strategy survives all promotion gates:

1. Open **MT5 Packages**.
2. Click **Download package** or **Download .mq5**.
3. Copy the `.mq5` into MT5 `MQL5/Experts`.
4. Compile it in MetaEditor.
5. Attach it to XAUUSD M5 on a demo account.
6. Set `InpEnableTrading=true` only for demo testing.

## Existing EVE safety boundary

Do not run `SUPABASE_SETUP.sql` in the existing EVE Supabase project. The new Discovery Lab must have its own database, Railway service, Netlify site and GitHub repository.
