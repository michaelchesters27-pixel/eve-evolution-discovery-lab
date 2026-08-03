import fs from 'node:fs';
import assert from 'node:assert/strict';
const html=fs.readFileSync(new URL('../index.html',import.meta.url),'utf8');
const js=fs.readFileSync(new URL('../app.js',import.meta.url),'utf8');
for (const label of ['Overview','New Strategies','Evolution','MT5 Packages','Data & Setup']) assert.ok(html.includes(label));
for (const id of ['view-overview','view-candidates','view-evolution','view-mt5','view-data']) assert.equal((html.match(new RegExp(`id="${id}"`,'g'))||[]).length,1);
assert.ok(js.includes("api('/dashboard')"));
assert.ok(js.includes('/download'));
console.log('frontend structure passed');
