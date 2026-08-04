# EVE Evolution Discovery Lab v2.1 — Deployment Guide

This ZIP replaces the **Discovery Lab GitHub repository only**. Do not upload it to EVE Algo Lab.

## Existing v2.0 deployment

### 1. Run the Discovery Supabase update first

1. Open the separate **EVE Evolution Discovery Lab** Supabase project.
2. Open **SQL Editor**.
3. Open `SUPABASE_UPDATE_v2.1.sql` from this repository.
4. Copy the complete file into a new query.
5. Press **Run** once.

Do not run it in the EVE Algo Lab Supabase project.

This step adds the package-profile state and download gate. Railway v2.1 expects these columns.

### 2. Replace the complete GitHub repository

Replace the Discovery Lab repository contents with everything inside this folder. Do not copy selected files and do not apply a patch.

Commit and push. Railway and Netlify should redeploy automatically.

### 3. Railway variables

No new variable is required for v2.1. Keep the existing Discovery Lab variables.

The important source settings remain:

```text
SOURCE_SYMBOL=XAU/USD
SOURCE_SNAPSHOT_INTERVAL=15min
SOURCE_CANDLE_INTERVAL=5min
RESEARCH_TIMEFRAME=M5
AUTONOMOUS_ENABLED=true
M1_REPLAY_ENABLED=true
```

A dedicated `SOURCE_SUPABASE_READ_ONLY_KEY` is still preferred. The existing source service-role key remains accepted as a migration fallback.

### 4. Confirm Railway

Open the latest Railway deployment logs and then open:

```text
https://<railway-domain>/health
```

Confirm `ok` is `true` and the API version is `2.1.0`.

### 5. Confirm Netlify

Allow Netlify to redeploy. Refresh the Discovery Lab and enter the existing `ADMIN_TOKEN` when asked.

### 6. What should happen to the old MT5 package

The existing package will initially show **Legacy survivor detected** and its download will be locked.

The autonomous worker will:

- recover its frozen rules
- test it under current final standards
- perform M1 replay
- complete its Trading Passport

The outcome will be one of:

- **Complete** — the package is rebuilt and download becomes available.
- **Failed** — the old survivor stays visible, but EVE blocks download and explains which current checks failed.

This is intentional. EVE does not guess missing Passport information.

## Fresh installation

For a brand-new separate Discovery Supabase project, run `SUPABASE_SETUP.sql` instead of running the versioned update files. Then deploy Railway and Netlify.

## Rollback

The v2.1 migration adds profile columns, indexes and dashboard counts. It does not delete historical strategies, mutations, frozen survivors or packages. Keep the previous GitHub release available for a code rollback.
