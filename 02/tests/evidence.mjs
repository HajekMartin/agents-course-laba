// Exercise the actual exported evidence node against valid and fabricated output.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const raw=JSON.parse(readFileSync(new URL('../workflows/finance-agent.json',import.meta.url),'utf8'));
const wf=Array.isArray(raw)?raw[0]:raw;
const execute=new Function('$json','$runIndex',wf.nodes.find(n=>n.name==='Verify Database Evidence').parameters.jsCode);
const check=json=>execute(json,0);
const intermediateSteps=[{action:{tool:'get_spending_summary'},observation:JSON.stringify([{result:{total_spending:'24518.75',categories:[{spending:'14000.00'}]}}])}];
assert.equal(check({output:'Bydlení 14 000 Kč. Celkem 24 518,75 Kč.',intermediateSteps})[0].json.verification.verified,true);
assert.equal(check({output:'Celkem 99 999 Kč.',intermediateSteps})[0].json.verification.verified,false);
assert.equal(check({output:'Bydlení 14 000 Kč.',intermediateSteps:[]})[0].json.verification.verified,false);
assert.equal(check({output:'Bydlení 14 000 Kč.',intermediateSteps:[{action:{tool:'get_spending_summary'},observation:'[{"error":"query failed"}]'}]})[0].json.verification.verified,false);
const filtered=check({output:'Bydlení 14 000 Kč. Ostatní byly mezi 125,50 a 14 000 Kč.',intermediateSteps})[0].json;
assert.equal(filtered.verification.verified,true);
assert.equal(check({output:'Celkem 99 999 Kč.',intermediateSteps})[0].json.needsRetry,true);
assert.equal(execute({output:'Celkem 99 999 Kč.',intermediateSteps},2)[0].json.needsRetry,false);
assert.equal(filtered.verification.filteredSentences,1);
assert.ok(!filtered.output.includes('125,50'));
console.log('PASS: real evidence node accepts verified amounts and blocks fabricated, absent or failed tool evidence.');
