/* Apply only intended edits. Independent partner/RSVP changes are retained;
   conflicting edits to the same field are never silently overwritten. */
(()=>{
const clone=x=>x===undefined?undefined:JSON.parse(JSON.stringify(x));
const equal=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
function merge(base,local,remote,path='plan'){
 if(equal(local,base))return clone(remote);
 if(equal(remote,base)||equal(local,remote))return clone(local);
 if(path==='plan.email'||path==='plan.invite'||path==='plan.demo')return clone(remote);
 if(local===undefined||remote===undefined||base===undefined){const e=Error('Both plans changed '+path+'. Your unsaved copy has been kept.');e.statusCode=409;throw e;}
 if(Array.isArray(base)&&Array.isArray(local)&&Array.isArray(remote)&&[...base,...local,...remote].every(x=>x&&typeof x==='object'&&typeof x.id==='string')){
  const b=new Map(base.map(x=>[x.id,x])),l=new Map(local.map(x=>[x.id,x])),r=new Map(remote.map(x=>[x.id,x]));
  const ids=[...new Set([...remote.map(x=>x.id),...local.map(x=>x.id)])],out=[];
  for(const id of ids){const item=merge(b.get(id),l.get(id),r.get(id),path+'.'+id);if(item!==undefined)out.push(item)}return out;
 }
 if(base&&local&&remote&&typeof base==='object'&&typeof local==='object'&&typeof remote==='object'&&!Array.isArray(base)&&!Array.isArray(local)&&!Array.isArray(remote)){
  const out={};for(const key of new Set([...Object.keys(base),...Object.keys(local),...Object.keys(remote)])){const value=merge(base[key],local[key],remote[key],path+'.'+key);if(value!==undefined)out[key]=value}return out;
 }
 const error=Error('Both partners changed '+path+'. Download your unsaved copy, then reload to review the latest plan.');error.statusCode=409;throw error;
}
globalThis.ivoryMerge={merge,equal,clone};
})();
