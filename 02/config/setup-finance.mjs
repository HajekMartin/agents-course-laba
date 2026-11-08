// Administrative setup only. The application itself runs in n8n and PostgreSQL.
import { readFileSync, writeFileSync } from 'node:fs';
import { randomBytes } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
let dotenv = readFileSync(`${root}/.env`, 'utf8');
const config = Object.fromEntries(dotenv.split(/\r?\n/).filter(l => /^[A-Z_]+=/.test(l)).map(l => {
  const i = l.indexOf('=');
  return [l.slice(0,i), l.slice(i+1).replace(/^(['"])(.*)\1$/, '$2')];
}));
for (const key of ['FINANCE_READER_PASSWORD']) {
  if (!config[key]) {
    config[key] = randomBytes(32).toString('hex');
    const pattern = new RegExp(`^${key}=.*$`,'m');
    dotenv = pattern.test(dotenv) ? dotenv.replace(pattern,()=>`${key}=${config[key]}`) : dotenv+`\n${key}=${config[key]}\n`;
    writeFileSync(`${root}/.env`, dotenv, {mode:0o600});
  }
}
function docker(args, input) {
  const r = spawnSync('docker', ['compose', ...args], {
    cwd:root, env:{...process.env, FINANCE_READER_PASSWORD:config.FINANCE_READER_PASSWORD},
    input, encoding:'utf8', maxBuffer:4*1024*1024,
  });
  if (r.status !== 0) throw new Error(r.stderr || r.stdout || r.error?.message || 'Docker operation failed');
  return r.stdout;
}
if (!process.argv.includes('--credentials-only')) {
  docker(['exec','-T','postgres','sh','-c',
    'psql -v ON_ERROR_STOP=1 -U "$FINANCE_DB_USER" -d "$FINANCE_DB_NAME"'],
    readFileSync(`${root}/database/001-finance.sql`,'utf8'));
  docker(['exec','-T','-e','FINANCE_READER_PASSWORD','postgres','sh','-c',
    'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres'],
    readFileSync(`${root}/database/002-reader.sql`,'utf8'));
  console.log('Finance migration and read-only role applied.');
}
const pg = {host:'postgres',port:5432,database:config.FINANCE_DB_NAME||'finance',ssl:'disable',maxConnections:5};
const credentials = [
  {id:'FinancePgImport02',name:'Finance - Import Database',type:'postgres',data:{...pg,user:config.FINANCE_DB_USER||'finance_app',password:config.FINANCE_DB_PASSWORD}},
  {id:'FinancePgRead02',name:'Finance - Read Only Database',type:'postgres',data:{...pg,user:'finance_reader',password:config.FINANCE_READER_PASSWORD}},
];
const base = new URL(config.UNSLOTH_BASE_URL);
if (!['host.docker.internal','localhost','127.0.0.1','::1','[::1]'].includes(base.hostname)) {
  throw new Error('Unsloth must use a local host endpoint');
}
if (config.UNSLOTH_API_KEY) credentials.push({id:'FinanceUnsloth02',name:'Finance - Local Unsloth',type:'openAiApi',
  data:{apiKey:config.UNSLOTH_API_KEY,url:config.UNSLOTH_BASE_URL,organizationId:''}});
// Pass secrets through stdin, never shell arguments or source-controlled JSON.
docker(['exec','-T','n8n','node','-e',
  "const fs=require('fs');fs.writeFileSync('/tmp/finance-credentials.json',fs.readFileSync(0),{mode:0o600});"], JSON.stringify(credentials));
try {
  docker(['exec','-T','n8n','n8n','import:credentials','--input=/tmp/finance-credentials.json']);
} finally {
  docker(['exec','-T','n8n','rm','-f','/tmp/finance-credentials.json']);
}
console.log(`Imported ${credentials.length} encrypted n8n credentials; no secrets exported.`);
