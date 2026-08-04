# EVE Evolution Discovery Lab v2.0 — Deployment Guide

This ZIP replaces the **Discovery Lab GitHub repository only**. Do not upload these files to EVE Algo Lab.

## Existing Discovery Lab upgrade

### 1. Update the separate Discovery Supabase database first

1. Open the Supabase project used by EVE Evolution Discovery Lab.
2. Open **SQL Editor**.
3. Paste the entire contents of `SUPABASE_UPDATE_v2.0.sql`.
4. Run it once.
5. Confirm the query completes without an error.

Never run this script in the EVE Algo Lab Supabase project.

### 2. Replace the Discovery GitHub repository

Replace the repository contents with everything inside this folder. Do not copy selected files and do not apply patches.

Commit and push the complete replacement. Railway and Netlify can then redeploy from GitHub.

### 3. Check Railway variables

Required variables:

```text
SOURCE_SUPABASE_URL=<EVE Algo Lab Supabase URL>
DISCOVERY_SUPABASE_URL=<Discovery Lab Supabase URL>
DISCOVERY_SUPABASE_SERVICE_ROLE_KEY=<Discovery Lab service-role key>
ADMIN_TOKEN=<existing long Discovery admin token>
CORS_ORIGINS=https://<your-discovery-netlify-site>
```

Configure one source credential:

```text
SOURCE_SUPABASE_READ_ONLY_KEY=<preferred restricted source key>
```

or, during migration only:

```text
SOURCE_SUPABASE_SERVICE_ROLE_KEY=<legacy EVE Algo Lab service-role key>
```

When `SOURCE_SUPABASE_READ_ONLY_KEY` is present, Discovery Lab uses it and the old service-role variable can be removed. The runtime and Data Health page show which credential mode is active. The application source adapter itself exposes GET operations only; a truly database-restricted key must be created in the source Supabase project by its administrator.

Recommended operating variables:

```text
SOURCE_SYMBOL=XAU/USD
SOURCE_SNAPSHOT_INTERVAL=15min
SOURCE_CANDLE_INTERVAL=5min
RESEARCH_TIMEFRAME=M5
AUTONOMOUS_ENABLED=true
M1_REPLAY_ENABLED=true
MINIMUM_GENERATIONS_BEFORE_FINAL=3
PACKAGE_DOWNLOADS_REQUIRE_ADMIN=true
RESEARCH_API_REQUIRES_ADMIN=true
```

Existing queue, timing and batch variables may remain unchanged.

### 4. Railway deployment check

The Railway root directory remains:

```text
/railway
```

Open:

```text
https://<railway-domain>/health
```

Confirm:

- `ok` is `true`
- version is `2.0.0`
- the runtime reports `eve-research-integrity-v2.0`
- `production_write_surface` is `none`
- the source credential mode is the one you expect

### 5. Netlify

The existing Netlify site can remain connected to the same GitHub repository. The included `netlify.toml` still uses the `frontend` folder.

Required Netlify variable:

```text
DISCOVERY_RAILWAY_URL=https://<railway-domain>
```

Redeploy after Railway is healthy.

### 6. First checks in the application

The browser asks for the existing Railway `ADMIN_TOKEN` before showing private research results. The token is stored only for the browser session.

Open **Data Health** and confirm:

- snapshots are present
- earliest and latest dates are sensible
- completed outcomes are close to 100%
- source interval and snapshot interval are correct
- `SOURCE_CANDLE_INTERVAL=5min` agrees with `RESEARCH_TIMEFRAME=M5`
- the source boundary does not report an error

On **Overview**, confirm the worker has completed a cycle after deployment.

### 7. Package downloads

Package and `.mq5` downloads ask for the same `ADMIN_TOKEN` stored in Railway. The token is held only in the browser session.

Every generated package still requires:

1. MetaEditor compilation.
2. MT5 demo-account forward testing.
3. Attachment to the market and timeframe specified by its Trading Passport.
4. Trading to be explicitly enabled in EA Inputs.

## Fresh Discovery Lab installation

For a completely new separate Discovery Supabase project, run `SUPABASE_SETUP.sql` instead of the update script. Then follow the Railway and Netlify steps above.

## Rollback

The v2 SQL migration adds columns, indexes, a multi-timeframe-safe snapshot key and replacement dashboard functions; it does not delete historical candidates, mutations, lineages, packages or snapshots. Keep the previous GitHub release available if a code rollback is required.
