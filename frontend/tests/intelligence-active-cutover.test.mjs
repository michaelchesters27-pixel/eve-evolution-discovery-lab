import fs from 'node:fs';
import assert from 'node:assert/strict';

const source = fs.readFileSync(new URL('../intelligence.js', import.meta.url), 'utf8');

assert.match(source, /every_m5_fabric/);
assert.match(source, /SCIENTIST V2 ACTIVE ON EVERY-M5 FABRIC/);
assert.match(source, /Scientist dataset authority/);
assert.match(source, /ACTIVE M5/);
