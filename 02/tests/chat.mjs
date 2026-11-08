// Synthetic diagnostics: set exposeTestEvidence=true in Return Verified Answer,
// publish, run this harness, then restore false and publish again.
import assert from 'node:assert/strict';
import {readFileSync,writeFileSync} from 'node:fs';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../',import.meta.url));
const e=readFileSync(root+'/.env','utf8');
const value=k=>e.match(new RegExp('^'+k+'=(.*)$','m'))?.[1].replace(/^(['"])(.*)\1$/,'$2');
const raw=JSON.parse(readFileSync(process.argv[2]||root+'/workflows/finance-agent.json','utf8'));
const wf=Array.isArray(raw)?raw[0]:raw;
const hook=wf.nodes.find(n=>n.name==='Finance Chat').webhookId;
const url=`http://localhost:${value('N8N_PORT')||5678}/webhook/${hook}/chat`;
const headers={'Content-Type':'application/json'};
assert.equal((await fetch(url)).status,200,'Local demo chat must allow anonymous access');
const oracle=spawnSync('docker',['compose','exec','-T','postgres','sh','-c',
  'psql -At -v ON_ERROR_STOP=1 -U "$FINANCE_DB_USER" -d "$FINANCE_DB_NAME"'],{cwd:root,encoding:'utf8',input:
  `SELECT jsonb_object_agg(category,total::text) FROM (SELECT c.name AS category,sum(-t.amount) AS total
   FROM finance.transactions t JOIN finance.categories c ON c.id=t.category_id
   WHERE transaction_date>='2026-10-01' AND transaction_date<'2026-11-01'
   AND transaction_type IN ('expense','refund') GROUP BY c.name) s;`});
assert.equal(oracle.status,0,oracle.stderr);const categoryTotals=JSON.parse(oracle.stdout.trim());
const session='finance-test-'+Date.now();
const cases=[
 ['Za co jsem v říjnu 2026 utratil nejvíc?','get_spending_summary','14000'],
 ['A kolik z toho bylo za potraviny?',null,'2720.75'],
 ['Kolik jsem měl příjmů v říjnu 2026?',null,'45000'],
 ['Jaké byly měsíční příjmy a výdaje za září až listopad 2026?','get_monthly_summary','45000'],
 ['Jaká byla moje největší jednotlivá výdajová transakce v říjnu 2026?','search_transactions','14000'],
 ['Porovnej celkové výdaje za září 2026 a říjen 2026.','compare_periods','5780'],
];
const records=[];let failures=0;
for(const [question,expectedTool,expectedAmount] of cases){
 const start=Date.now();
 const r=await fetch(url,{method:'POST',headers,body:JSON.stringify({action:'sendMessage',sessionId:records.length<2?session:session+'-'+records.length,chatInput:question}),signal:AbortSignal.timeout(600000)});
 assert.equal(r.status,200);const b=await r.json();
 const steps=(b.intermediateSteps||[]).map(s=>({tool:s.action.tool,input:s.action.toolInput,result:JSON.parse(s.observation)}));
 const record={question,output:b.output,verification:b.verification,steps,seconds:Math.round((Date.now()-start)/1000)};
 records.push(record);writeFileSync(root+'/tests/acceptance-results.json',JSON.stringify({categoryTotals,records},null,2)+'\n');
 console.log(JSON.stringify(record));
 try {
 if(b.verification)assert.equal(b.verification.verified,true,'Evidence guard blocked an unsupported answer');
 assert.ok(steps.length,'The agent must actually call a database tool');
 if(expectedTool)assert.ok(steps.some(s=>s.tool===expectedTool),'Expected tool '+expectedTool);
 const normalized=b.output.replace(/[\s\u00a0\u202f*]/g,'').replace(/,/g,'.');
 assert.ok(normalized.includes(expectedAmount),'Expected verified amount '+expectedAmount);
 if(question.startsWith('Za co')){
   const result=steps.find(s=>s.tool==='get_spending_summary').result[0].result;
   assert.equal(result.start_date,'2026-10-01');assert.equal(result.end_date_exclusive,'2026-11-01');
   assert.deepEqual(Object.fromEntries(result.categories.map(c=>[c.category,c.spending])),categoryTotals);
   assert.equal(result.total_spending,'24518.75');
 }
 if(question.startsWith('A kolik'))assert.ok(steps.some(s=>s.input.start_date==='2026-10-01'&&s.input.end_date==='2026-11-01'),'Follow-up must preserve October');
 } catch(error) { failures++;record.failure=error.message;console.error('FAIL: '+error.message); }
}
writeFileSync(root+'/tests/acceptance-results.json',JSON.stringify({categoryTotals,failures,records},null,2)+'\n');
if(failures)process.exitCode=1;
console.log((failures?'PARTIAL: ':'PASS: ')+'live local model, real tool calls, independent SQL category totals, four tools, Czech answers and multi-turn context.');
