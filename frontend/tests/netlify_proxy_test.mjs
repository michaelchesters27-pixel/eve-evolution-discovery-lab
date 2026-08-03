import fs from 'node:fs';
import assert from 'node:assert/strict';
const source=fs.readFileSync(new URL('../netlify/functions/api.mjs',import.meta.url),'utf8');
assert.ok(source.includes('DISCOVERY_RAILWAY_URL'));
assert.ok(source.includes('/api'));
console.log('netlify proxy passed');
