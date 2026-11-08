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
  const r=await fetch(url,{method:'POST',headers:{...headers,...(token?{'x-auth-token':token}:{})},body,signal:AbortSignal.timeout(600000)});
  assert.equal(r.status,200);
  const html=await r.text();
  const summary=html.match(/<pre id="import-summary">([\s\S]*?)<\/pre>/)?.[1];
  assert.ok(summary,'Expected a direct result page without a waiting execution');
  const next=html.match(/id="upload-another" href="([^"]+)"/)?.[1];
  assert.equal(next,'/form/finance-import','Result must link back to the permanent production form');
  assert.equal((await fetch(new URL(next,url))).status,200,'Another upload must work without running the editor');
  const decode=s=>s.replace(/&quot;/g,'"').replace(/&#39;/g,"'").replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&amp;/g,'&');
  return JSON.parse(decode(summary));
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
assert.equal((await upload('unsupported.txt',Buffer.from('synthetic unsupported file'))).status,'rejected');
for(const name of ['bank-statement.pdf','bank-statement.pdf']){
 const s=await upload(name,readFileSync(new URL('examples/'+name,root)));
 console.log(JSON.stringify({test:name,...s}));
 assert.ok(['completed','partial','duplicate_file'].includes(s.status));
 assert.equal(s.processed_rows,4);assert.equal(s.invalid_rows,0);
 assert.equal(s.imported_transactions+s.skipped_duplicates,4);
}
const empty=await upload('no-text.pdf',readFileSync(new URL('examples/no-text.pdf',root)));
assert.equal(empty.status,'rejected');assert.match(empty.errors[0].message,/OCR|readable text/);
console.log('PASS: anonymous CSV/XLSX/PDF uploads, repeats, source checks, empty-text PDFs, validation errors and continuous production uploads.');
