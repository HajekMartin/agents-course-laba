// Export only the two actual application workflows; never export credentials.
import {readFileSync,writeFileSync,mkdirSync,rmSync} from 'node:fs';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../',import.meta.url));
function docker(args){
 const r=spawnSync('docker',['compose',...args],{cwd:root,encoding:'utf8'});
 if(r.status!==0)throw new Error(r.stderr||r.stdout||r.error?.message);
}
mkdirSync(root+'/exports',{recursive:true});mkdirSync(root+'/workflows',{recursive:true});
for(const [id,file] of [['ObNXCw6o4NlnPtMm','finance-import.json'],['u4woXC4KYKne0clG','finance-agent.json']]){
 const container='/tmp/'+file;
 const temporary=root+'/exports/'+file;
 docker(['exec','-T','n8n','n8n','export:workflow','--id='+id,'--output='+container]);
 docker(['cp','n8n:'+container,temporary]);
 const raw=JSON.parse(readFileSync(temporary,'utf8'));const wf=Array.isArray(raw)?raw[0]:raw;
 wf.active=false;wf.pinData={};wf.staticData=null;
 // Anonymous demo triggers do not need their former Basic Auth references.
 for(const n of wf.nodes){
  if(n.parameters?.authentication==='none' && n.credentials?.httpBasicAuth){
   delete n.credentials.httpBasicAuth;
   if(Object.keys(n.credentials).length===0)delete n.credentials;
  }
 }
 for(const key of ['activeVersion','activeVersionId','shared','scopes'])delete wf[key];
 writeFileSync(root+'/workflows/'+file,JSON.stringify(wf,null,2)+'\n');
 rmSync(temporary);docker(['exec','-T','n8n','rm','-f',container]);
 console.log('Exported actual sanitized workflow: workflows/'+file);
}
