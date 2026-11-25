// Exact QML pure navigation helpers. Synthetic data only, no network.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const ctx = vm.createContext({});
vm.runInContext(fs.readFileSync(path.join(__dirname, '../client/BiliUx.js'), 'utf8').replace(/^\.pragma library\s*/, ''), ctx);
let checks = 0;
const rows = Array.from({length:120}, (_,i) => ({kind:'video',bvid:'BV'+String(i).padStart(10,'0')}));
for (let at=0;at<rows.length;at++) {
  const result = ctx.playlist(rows,rows[at],[{...rows[at],cid:'1'}],0);
  assert(result.rows.length<=24);assert.equal(result.rows[result.index].bvid,rows[at].bvid);checks+=2;
}
const parts=Array.from({length:2000},(_,i)=>({...rows[0],cid:String(i),part_title:'P'+i}));
for(let at=0;at<parts.length;at++) {
  const result=ctx.playlist(rows,rows[0],parts,at);
  assert(result.rows.length<=24);assert.equal(result.rows[result.index].cid,String(at));checks+=2;
}
assert.equal(ctx.identity({kind:'season',season:'2'}),'ss:2');
assert.equal(ctx.identity({kind:'episode',ep:'3'}),'ep:3');
assert.equal(ctx.stamp(125.8),'2:05');
console.log(JSON.stringify({passed:true,checks:checks+3,device_tested:false}));
for(const [file,name,next] of [['BiliAutomation.qml','run','runOnce'],['ToolboxAutomation.qml','tick','stepOnce']]) {
  const text=fs.readFileSync(path.join(__dirname,'../client',file),'utf8');
  const start=text.indexOf('    function '+name+'('),end=text.indexOf('    function '+next+'(',start);
  assert(start>=0&&end>start);
  let called=0;const scope=vm.createContext({stepping:false});
  scope[next]=()=>{called++;scope[name]();};vm.runInContext(text.slice(start,end),scope);
  scope[name]();assert.equal(called,1);assert.equal(scope.stepping,false);
  scope[next]=()=>{throw new Error('fixture');};assert.throws(()=>scope[name]());assert.equal(scope.stepping,false);
}
