// Live local-model regression. Insert only synthetic rows, then delete this import.
// Never print or save arbitrary model output: the application can contain private data.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {spawnSync} from 'node:child_process';
import {createHash,randomUUID} from 'node:crypto';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../',import.meta.url));
const wf=JSON.parse(readFileSync(root+'/workflows/finance-agent.json','utf8'));
const env=readFileSync(root+'/.env','utf8');
const port=env.match(/^N8N_PORT=(.*)$/m)?.[1]?.replace(/['"]/g,'')||5678;
const hook=wf.nodes.find(n=>n.name==='Finance Chat').webhookId;
const url=`http://localhost:${port}/webhook/${hook}/chat`;
const marker='SyntheticIntent'+randomUUID().replaceAll('-','');
const hash=createHash('sha256').update(marker).digest('hex');
const quote=s=>"'"+s.replaceAll("'","''")+"'";
function sql(query){
 const r=spawnSync('docker',['compose','exec','-T','postgres','sh','-c','psql -qAt -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$FINANCE_DB_NAME"'],{cwd:root,input:query,encoding:'utf8'});
 assert.equal(r.status,0,'Synthetic regression SQL failed');
 return JSON.parse(r.stdout.trim());
}
const rows=Array.from({length:29},(_,i)=>({date:`2096-02-${String(i+1).padStart(2,'0')}`,amount:i<19?'1234.56':i<26?'-987.65':i===26?'87.65':i===27?'-400.00':'400.00',currency:'CZK',description:marker+' synthetic payment '+String(i+1).padStart(2,'0'),merchant:'',transaction_id:marker+'-'+i,transaction_type:i<19?'income':i<26?'expense':i===26?'refund':'transfer'}));
const money=s=>{const [whole,fraction]=s.split('.');return whole.replace(/\B(?=(\d{3})+(?!\d))/g,' ')+','+fraction;};
try{
 assert.equal(sql("SELECT count(*) FROM finance.transactions WHERE transaction_date>='2096-02-01' AND transaction_date<'2096-03-01'"),0,'Reserved synthetic test period must be empty');
 const imported=sql(`SELECT finance.import_statement('synthetic-intent-regression.csv',${quote(hash)},${quote(JSON.stringify(rows))}::jsonb);`);
 assert.equal(imported.imported_transactions,29);
 const oracle=sql(`SELECT jsonb_agg(jsonb_build_object('date',transaction_date,'amount',amount::text,'description',description)) FROM finance.transactions WHERE import_id=(SELECT id FROM finance.imports WHERE file_hash=${quote(hash)});`);
 assert.equal(oracle.length,29);
 // Execute the actual exported tool under the reader role, with a description-only match.
 const query=wf.nodes.find(n=>n.name==='search_transactions').parameters.query;
 const args=['2096-02-01','2096-03-01','CZK',marker,'','0','','transactions'];
 const found=sql('SET ROLE finance_reader; PREPARE q('+args.map(()=> 'text').join(',')+') AS '+query+'\nEXECUTE q('+args.map(quote).join(',')+');');
 assert.equal(found.match_count,29);
 assert.equal(found.transactions.filter(t=>t.transaction_type==='transfer').length,2);
 assert.equal(found.net_spending,'6825.90');
 assert.equal(found.income,'23456.64');
 console.log('PASS: actual reader SQL, description-only merchant matching, 29 rows including transfers, exact spending/income totals.');
 const sessionId='synthetic-list-'+randomUUID();
 const questions=[
  `Vyhledej a přesně vypiš všechny transakce v CZK od 2096-02-01 do 2096-03-01 (konec nezahrnut) s textem ${marker}, včetně příjmů, výdajů, vratek a vlastních převodů.`,
  'Můžeš mi laskavě přesně vypsat ty transakce?',
  'No ale já jsem ten výpis nedostal, pošli mi ho teď celý znovu.',
 ];
 for(const [index,chatInput] of questions.entries()){
  const start=Date.now();
  const response=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'sendMessage',sessionId,chatInput}),signal:AbortSignal.timeout(1500000)});
  assert.equal(response.status,200);
  const body=await response.json();
  assert.equal(body.verification?.verified,true,'Response must have actual database evidence');
  assert.ok(body.verification.tools.includes('search_transactions'),'The agent must select the search tool');
  assert.equal(body.verification.renderedRows,29,'Must deliver all 29 synthetic rows');
  assert.equal(body.verification.matchCount,29);
  assert.equal(body.verification.truncated,false);
  const lines=body.output.split('\n').filter(l=>l.startsWith('| 2096-'));
  assert.equal(lines.length,29);
  for(const row of oracle)assert.ok(lines.some(l=>l.includes(row.date)&&l.includes(row.description)&&l.includes(money(row.amount))),'Each row must match independent SQL, including exact signed amount');
  console.log(`PASS: live local LLM question ${index+1}, fresh search tool, all 29 exact SQL rows, ${Math.round((Date.now()-start)/1000)}s.`);
 }
}finally{
 const remaining=sql(`BEGIN; DELETE FROM finance.transactions WHERE import_id IN (SELECT id FROM finance.imports WHERE file_hash=${quote(hash)}); DELETE FROM finance.imports WHERE file_hash=${quote(hash)}; COMMIT; SELECT count(*) FROM finance.imports WHERE file_hash=${quote(hash)};`);
 assert.equal(remaining,0);
 console.log('PASS: temporary synthetic import removed; existing transactions preserved.');
}
