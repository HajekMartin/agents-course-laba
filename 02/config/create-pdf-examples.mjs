// Minimal reproducible text PDF fixtures. No additional runtime package is needed.
import {writeFileSync} from 'node:fs';
const root=new URL('../examples/',import.meta.url);
function pdf(lines){
 const escape=s=>s.replace(/[\\()]/g,'\\$&');
 const stream='BT /F1 10 Tf 45 790 Td 15 TL\n'+lines.map((s,i)=>(i?'T* ':'')+'('+escape(s)+') Tj').join('\n')+'\nET';
 const objects=[
  '<< /Type /Catalog /Pages 2 0 R >>',
  '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
  '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
  '<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>',
  '<< /Length '+Buffer.byteLength(stream)+' >>\nstream\n'+stream+'\nendstream',
 ];
 let output='%PDF-1.4\n';const offsets=[0];
 objects.forEach((object,i)=>{offsets.push(Buffer.byteLength(output));output+=(i+1)+' 0 obj\n'+object+'\nendobj\n';});
 const xref=Buffer.byteLength(output);output+='xref\n0 '+(objects.length+1)+'\n0000000000 65535 f \n';
 output+=offsets.slice(1).map(n=>String(n).padStart(10,'0')+' 00000 n \n').join('');
 output+='trailer\n<< /Size '+(objects.length+1)+' /Root 1 0 R >>\nstartxref\n'+xref+'\n%%EOF\n';
 return output;
}
const header=['SYNTHETIC BANK - ACCOUNT STATEMENT','Currency: CZK','Period: October-November 2026',
 'Opening balance: 10000.00 CZK (not a transaction)',''];
const rows=[
 ['02.10.2026','-14000.00','Synthetic purchase','Synthetic Rent','DEMO-014','expense'],
 ['03.10.2026','-1250.50','Synthetic purchase','Lidl','DEMO-015','expense'],
 ['22.10.2026','1000.00','Synthetic refund','Alza','DEMO-038','refund'],
 ['07.11.2026','-75.00','Synthetic PDF purchase','Lidl','DEMO-PDF-001','expense'],
];
const lines=[...header];
for(const [date,amount,description,merchant,id,type] of rows)lines.push(
 'Booking date: '+date,'Amount: '+amount+' CZK','Description: '+description,
 'Merchant: '+merchant,'Transaction ID: '+id,'Transaction type: '+type,'');
writeFileSync(new URL('bank-statement.pdf',root),pdf(lines));
writeFileSync(new URL('no-text.pdf',root),pdf([]));
console.log('Created synthetic text statement and empty-text PDF fixtures.');
