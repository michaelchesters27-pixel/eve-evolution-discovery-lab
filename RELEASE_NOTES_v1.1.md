# EVE Evolution Discovery Lab v1.1

## What changed

- New independent `composed_signal` strategies assemble two to four executable market conditions instead of relying mainly on named templates.
- Legacy strategy families remain as lower-priority benchmark controls.
- Mutation now explores schedule, month, regime, alignment sign, direction and recipe structure, including adding, removing, replacing and tuning conditions.
- Mutation memory biases proven genes while retaining a 30% exploration path.
- Candidate decisions now store explicit promotion-gate diagnostics.
- Activity messages show locked PF, expectancy, trade count and failed gates.
- Repeated source-sync events are compacted into one meaningful progress entry in the dashboard.
- Evolution displays exact parent-to-child changes and measured validation deltas.
- MT5 generation supports the new composed recipes.

## Deployment

No Supabase SQL or environment-variable changes are required. Replace only the files listed in `UPDATE_MANIFEST_v1.1.txt`, or deploy the full repository ZIP.
