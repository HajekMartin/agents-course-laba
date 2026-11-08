// Compile and execute the actual exported fixed tool queries under the reader role.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../',import.meta.url));
const raw=JSON.parse(readFileSync(process.argv[2]||root+'/workflows/finance-agent.json','utf8'));
const wf=Array.isArray(raw)?raw[0]:raw;
const cases=[
 ['get_spending_summary',['2026-10-01','2026-11-01','CZK'],r=>{assert.equal(r.total_spending,'24518.75');assert.equal(r.food_spending,'3730.75');assert.equal(r.transaction_count,15)}],
 ['search_transactions',['2026-10-01','2026-11-01','CZK','Alza','','0',''],r=>{assert.equal(r.net_spending,'5000.00');assert.equal(r.refunds,'1000.00');assert.equal(r.match_count,2)}],
 ['get_monthly_summary',['2026-09-01','2026-12-01','CZK',''],r=>{assert.equal(r.total_income,'135000.00');assert.equal(r.total_net_balance,'72828.75');assert.equal(r.total_spending,'62171.25');assert.equal(r.average_monthly_spending,'20723.75')}],
 ['compare_periods',['2026-09-01','2026-10-01','2026-10-01','2026-11-01','CZK'],r=>{assert.equal(r.spending_change,'5780.00');assert.equal(r.spending_change_percent,'30.85')}],
];
for(const [name,values,verify] of cases){
 const query=wf.nodes.find(n=>n.name===name).parameters.query;
 const sql='SET ROLE finance_reader; PREPARE finance_query('+values.map(()=> 'text').join(',')+') AS '+query+
 '\nEXECUTE finance_query('+values.map(v=>"'"+v.replaceAll("'","''")+"'").join(',')+');';
 const r=spawnSync('docker',['compose','exec','-T','postgres','sh','-c','psql -qAt -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$FINANCE_DB_NAME"'],{cwd:root,input:sql,encoding:'utf8'});
 assert.equal(r.status,0,r.stderr);const result=JSON.parse(r.stdout.trim());verify(result);
 console.log('PASS: '+name+' actual exported SQL under finance_reader');
}
