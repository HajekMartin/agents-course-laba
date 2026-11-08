// End-to-end tests against the anonymous local demo Form Trigger. Synthetic data only.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
const root = new URL('../',import.meta.url);
const env = readFileSync(new URL('.env',root),'utf8');
const value = key => env.match(new RegExp(`^${key}=(.*)$`,'m'))?.[1].replace(/^(['"])(.*)\1$/,'$2');
const base = `http://localhost:${value('N8N_PORT')||5678}`;
const headers = {};
const url = base+'/form/finance-import';
assert.equal((await fetch(url)).status,200,'Local demo upload must allow anonymous access');
export async function upload(name,bytes) {
  const formPage=await fetch(url,{headers});assert.equal(formPage.status,200);
  const token=(await formPage.text()).match(/const authToken = '([^']*)'/)?.[1];
  const body=new FormData();body.append('field-0',new Blob([bytes]),name);
  const r=await fetch(url,{method:'POST',headers:{...headers,...(token?{'x-auth-token':token}:{})},body,signal:AbortSignal.timeout(120000)});
  assert.equal(r.status,200);
  const payload=await r.json();
  assert.ok(payload.formSubmittedText,'Expected direct summary without a waiting execution');
  return JSON.parse(payload.formSubmittedText);
}
for (const name of ['canonical-statement.csv','canonical-statement.csv','canonical-statement.xlsx','canonical-statement.xlsx','invalid-rows.csv','missing-columns.csv']) {
  const s=await upload(name,readFileSync(new URL('examples/'+name,root)));
  console.log(JSON.stringify({test:name,...s}));
  if (name.startsWith('canonical')) {
    assert.ok(['completed','duplicate_file'].includes(s.status));assert.equal(s.invalid_rows,0);
    assert.equal(s.processed_rows,name.endsWith('xlsx')?44:43);
    assert.equal(s.imported_transactions+s.skipped_duplicates,s.processed_rows);
  } else {
    assert.ok(['rejected','duplicate_file'].includes(s.status));
    assert.equal(s.invalid_rows,name==='invalid-rows.csv'?2:1);assert.equal(s.imported_transactions,0);
    assert.ok(s.errors.length);
  }
}
const unsupported=await upload('unsupported.pdf',Buffer.from('synthetic unsupported file'));
assert.equal(unsupported.status,'rejected');
console.log('PASS: anonymous CSV/XLSX uploads, repeats, invalid amounts/dates, missing columns and unsupported extension.');
