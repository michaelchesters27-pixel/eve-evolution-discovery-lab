# EVE Evolution Discovery Lab v2.1

## Phase 1 — Strategy Profiling Gate

### Legacy survivor recovery

- Existing packages are marked for current-standard profiling.
- EVE reads the package's linked frozen strategy rather than guessing from its name.
- Legacy rules are re-tested using the current final research engine.
- M1 execution replay is mandatory.
- Passing survivors are rebuilt as v2.1 packages.
- Failed survivors remain visible but cannot be downloaded.

### Complete Trading Passports

- Added explicit profile version, status, origin and completion report.
- Added strongest/weakest session, regime, weekday and UTC hour where sample size permits.
- Added explicit text when no reliable session or regime advantage can be established.
- Added evidence segment, dataset version, M1 status and risk profile.
- Package generation raises an error if the Passport is incomplete.

### Mandatory download gate

- Package and MQ5 endpoints return HTTP 409 when profiling is incomplete or failed.
- Download requires `profile_status=complete`, `download_eligible=true`, package status `ready` and a complete Passport.
- The frontend does not render download controls for locked packages.

### Operator experience

- Removed raw credential-mode text from the sidebar.
- Runtime status now describes the market research source rather than internal variable names.
- Package cards explain legacy profiling, failed current standards and download state.
- Research components and common failed gates are translated into operator language.
- The research pipeline now includes a distinct Profile stage before Package.

### Evidence profiling

- Backtest metrics now retain expectancy and trade counts by UTC hour.
- Existing session, weekday and regime evidence is used by the Passport.
- No bucket is promoted as best or worst unless it reaches the profile's minimum sample requirement.

### Database

Run `SUPABASE_UPDATE_v2.1.sql` in the separate Discovery Lab Supabase project before deploying this code.
