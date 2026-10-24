(async()=>{
const esc=ivory.escape,status=document.getElementById('web-status'),form=document.getElementById('website-form');let revision=0,dirty=false,busy=false,readOnly=false;
const field=(label,key,value,type='text')=>`<label class="field"><span>${label}</span><input name="${key}" type="${type}" value="${esc(value||'')}" maxlength="5000"></label>`;
async function listInvites(){const result=await ivory.api('/api/invitations');document.getElementById('active-invites').innerHTML='<h3>Invitation links already created</h3>'+result.invitations.map(i=>`<div class="row"><span>${i.names.map(esc).join(', ')} · ${i.active?'Active':'Revoked / expired'}</span>${i.active&&!readOnly?`<button type="button" data-revoke="${i.id}">Revoke link</button>`:''}</div>`).join('')}
try{
 const [web,plan,files]=await Promise.all([ivory.api('/api/website'),ivory.api('/api/state'),ivory.api('/api/files')]);const site=web.site;revision=web.revision;readOnly=plan.readonly;
 const names=plan.state.names.filter(Boolean).join(' & ');
 document.getElementById('website-fields').innerHTML=field('Website address (lowercase letters, numbers and hyphens)','slug',web.slug||names.toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,''))+field('Page title','title',site.title||names)+field('Wedding date','date',site.date||plan.state.date,'date')+
 `<label class="field"><span>Style</span><select name="theme">${['garden','classic','modern'].map(t=>`<option ${site.theme===t?'selected':''}>${t}</option>`).join('')}</select></label>`+
 [['intro','Welcome message'],['ceremony','Ceremony details'],['reception','Reception details'],['travel','Travel, parking and map links'],['accommodation','Accommodation'],['dress','Dress code'],['faq','Questions and answers']].map(([k,t])=>`<label class="field"><span>${t}</span><textarea name="${k}" rows="3" maxlength="5000">${esc(site[k]||'')}</textarea></label>`).join('')+field('Gift-list link (https://)','gift_url',site.gift_url,'url')+
 `<label class="field"><span>Cover photo</span><select name="cover"><option value="">No cover</option>${files.files.filter(f=>f.kind==='cover').map(f=>`<option value="${f.id}" ${site.cover===f.id?'selected':''}>${esc(f.name)}</option>`).join('')}</select></label>`+
 field('Website access code (leave blank to keep existing; use Clear to remove)','access_code','','password')+
 `<label class="check"><input type="checkbox" name="clear_code"><span>Clear the website access code</span></label><label class="check"><input type="checkbox" name="published" ${site.published?'checked':''}><span>Publish this website</span></label><p class="hint" id="protection-status">Access-code protection ${web.has_code?'is enabled':'is not enabled'}. Old invitations remain valid if you change the address. A public page may include ceremony details; use code protection and personal invitations for separate day/evening information.</p>`;
 document.getElementById('invitation-guests').innerHTML=plan.state.guests.map(g=>`<label class="check"><input type="checkbox" value="${g.id}"><span>${esc(g.name)} · ${g.attendance}</span></label>`).join('')||'<p>Add guests in your planner first.</p>';
 if(readOnly){status.textContent='Editing access has ended. You can still preview your saved website and export your planner.';form.querySelectorAll('input,textarea,select,button').forEach(e=>e.disabled=true);document.getElementById('create-invite').disabled=true;}
 await listInvites();
 if(location.hash==='#guest-invitations')document.getElementById('guest-invitations').scrollIntoView({block:'start'});
}catch(e){status.textContent=e.message}
form.addEventListener('input',()=>dirty=true);form.addEventListener('change',()=>dirty=true);
window.addEventListener('beforeunload',e=>{if(dirty||busy){e.preventDefault();e.returnValue=''}});
form.addEventListener('submit',async e=>{
 e.preventDefault();if(busy||readOnly)return;busy=true;const button=form.querySelector('button');button.disabled=true;status.textContent='Saving website…';
 try{const f=new FormData(form),updated={};for(const k of ['title','date','theme','intro','ceremony','reception','travel','accommodation','dress','faq','gift_url','cover'])updated[k]=f.get(k);updated.published=f.has('published');const code=f.has('clear_code')?'':f.get('access_code')||null;
  const result=await ivory.api('/api/website',{method:'PUT',body:{site:updated,slug:f.get('slug'),revision,access_code:code}});revision=result.revision;dirty=false;
  form.elements.access_code.value='';form.elements.clear_code.checked=false;document.getElementById('protection-status').textContent='Access-code protection '+(result.has_code?'is enabled.':'is not enabled.')+' Existing invitation addresses remain valid.';
  status.innerHTML=`Saved ${updated.published?'and published':'as a private draft'}. <a href="/website/preview" target="_blank" rel="noopener">Preview saved website</a>${updated.published?` · <a href="${esc(result.url)}" target="_blank" rel="noopener">Open published website</a>`:''}`;
 }catch(err){status.textContent=err.message+' Your typed changes are still in the form.'}finally{busy=false;button.disabled=readOnly}
});
let inviting=false;document.getElementById('create-invite').addEventListener('click',async()=>{if(inviting||readOnly)return;inviting=true;const button=document.getElementById('create-invite');button.disabled=true;
 try{const ids=[...document.querySelectorAll('#invitation-guests input:checked')].map(n=>n.value);const result=await ivory.api('/api/invitations',{method:'POST',body:{guest_ids:ids,email:document.getElementById('invite-email').value}});
  document.getElementById('invite-result').innerHTML=`<label class="field"><span>${result.queued?'Invitation queued. Copy link:':'Copy this private invitation link:'}</span><input id="invitation-copy" readonly value="${esc(result.url)}"></label><button type="button" id="copy-invitation">Copy link</button>`;
  document.getElementById('copy-invitation').onclick=async()=>{const input=document.getElementById('invitation-copy');input.select();try{await navigator.clipboard.writeText(input.value);status.textContent='Invitation link copied.'}catch(e){status.textContent='The link is selected—copy it using your phone or keyboard.'}};await listInvites();
 }catch(e){status.textContent=e.message}finally{inviting=false;button.disabled=readOnly}});
document.getElementById('active-invites').addEventListener('click',async e=>{const id=e.target.dataset.revoke;if(!id||!confirm('Revoke this invitation link? Saved replies remain in your guest list.'))return;try{await ivory.api('/api/invitations/'+id+'/revoke',{method:'POST',body:{}});await listInvites();status.textContent='Invitation revoked. Saved guest replies are unchanged.'}catch(err){status.textContent=err.message}});
})();

