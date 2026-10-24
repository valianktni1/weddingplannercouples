/* Explicit photography submission. Never submits on load or on ordinary saves. */
(async()=>{
 const root=document.querySelector('#ivory-planner'),host=root?.querySelector('#couple-booking-tools')||root?.querySelector('.topbar .actions');if(!host||window.ivoryPreview)return;
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 let status;try{status=await ivory.api('/api/wbm-timings')}catch(_){return}if(!status.linked)return;
 const button=document.createElement('button');button.type='button';button.textContent='Send final timings to Mark';button.className='primary';host.append(button);
 const dialog=document.createElement('dialog');dialog.className='wbm-timing-dialog';root.append(dialog);
 const close=()=>{dialog.close();dialog.innerHTML=''};
 const bools=new Set(['reception_same','prep_photos','later_event']),timeKeys=new Set(['ceremony_time','requested_start','group_photo_time','meal_time','speeches_time','evening_time','cake_time','first_dance_time','later_event_time']);
 const essential=new Set(['ceremony_time','ceremony_duration','ceremony_venue','reception_same','prep_photos','start_choice','speeches_position','first_dance_time','later_event','day_contact','day_mobile','group_count']);
 function control(q,value){
  let kind=q.kind,key=q.key,type=kind==='builtin'?'text':kind;
  if(timeKeys.has(key))type='time';if(['ceremony_duration','travel_minutes'].includes(key))type='number';
  if(['prep_notes','second_prep','extra_stops','important_notes'].includes(key))type='textarea';
  let choices=q.options||[];
  if(bools.has(key))choices=[['true','Yes'],['false','No']];
  else if(key==='start_choice')choices=[['normal','Normal coverage start'],['earlier','Request an earlier start']];
  else if(key==='speeches_position')choices=['Before the meal','Between courses','After the meal'];
  else if(key==='group_count')choices=['None','1-5','6-10','More than 10'];
  else if(kind==='yesno')choices=[['yes','Yes'],['no','No']];
  const attrs=`data-answer="${esc(key)}" id="wbm-${esc(key)}" ${essential.has(key)||q.required?'required':''}`;
  let input;
  if(choices.length)input=`<select ${attrs}><option value="">Please choose</option>${choices.map(v=>{const [id,label]=Array.isArray(v)?v:[v,v];return `<option value="${esc(id)}" ${String(value)===String(id)?'selected':''}>${esc(label)}</option>`}).join('')}</select>`;
  else if(type==='textarea')input=`<textarea ${attrs} maxlength="5000" rows="3">${esc(value)}</textarea>`;
  else input=`<input ${attrs} type="${['text','time','date','number'].includes(type)?type:'text'}" value="${esc(value)}" ${type==='number'?'step="any"':''} maxlength="5000">`;
  return `<label class="field" data-question="${esc(key)}"><span>${esc(q.label)}</span>${input}${q.help?`<small>${esc(q.help)}</small>`:''}</label>`;
 }
 function conditionals(){
  const v=k=>dialog.querySelector(`[data-answer="${k}"]`)?.value;
  const rules={reception_venue:[v('reception_same')==='false',true],prep_person:[v('prep_photos')==='true',true],prep_venue:[v('prep_photos')==='true',true],travel_minutes:[v('prep_photos')==='true',true],prep_notes:[v('prep_photos')==='true',false],second_prep:[v('prep_photos')==='true',false],requested_start:[v('start_choice')==='earlier',true],later_event_name:[v('later_event')==='true',true],later_event_time:[v('later_event')==='true',true]};
  for(const [key,[visible,required]]of Object.entries(rules)){const node=dialog.querySelector(`[data-question="${key}"]`);if(!node)continue;node.hidden=!visible;const input=node.querySelector('input,select,textarea');input.disabled=!visible;input.required=visible&&(required||status.template.fields.find(q=>q.key===key)?.required);}
 }
 function edit(){
  dialog.innerHTML=`<div class="actions"><h2>Final timings for Mark</h2><button type="button" data-wbm-close>Close</button></div><p>Your saved planner timings are filled in below. Check them and complete the photography details. This sends only these answers, the photography timeline and your photo-group titles. Your budget, guest list and private notes are not shared.</p>${status.latest?`<p role="status">${esc(status.latest.status==='received'?'Previous version received by Mark':status.latest.status==='needs_attention'?status.latest.message:'Previous version saved for transfer; receipt not confirmed yet.')}</p>`:''}<form>${[0,1,2,3].map((step)=>`<fieldset><legend>${['Ceremony','Preparation photographs','The rest of your day','Contacts and other details'][step]}</legend>${status.template.fields.filter(q=>q.enabled&&q.step===step).map(q=>control(q,status.answers[q.key]??'')).join('')}</fieldset>`).join('')}<p data-wbm-error role="alert"></p><button type="submit" class="primary">Preview timings before sending</button></form>`;
  dialog.querySelector('[data-wbm-close]').onclick=close;dialog.querySelector('form').onchange=conditionals;conditionals();
  dialog.querySelector('form').onsubmit=e=>{e.preventDefault();const answers={_template_revision:status.template.revision};dialog.querySelectorAll('[data-answer]').forEach(input=>{if(input.disabled)return;let value=input.value;if(bools.has(input.dataset.answer))value=value==='true';else if(input.type==='number'&&value!=='')value=Number(value);answers[input.dataset.answer]=value;});review(answers);};
 }
 function review(answers){
  dialog.innerHTML=`<h2>Check what Mark will receive</h2><dl>${status.template.fields.filter(q=>q.enabled&&answers[q.key]!==undefined&&answers[q.key]!=='').map(q=>`<dt>${esc(q.label)}</dt><dd>${esc(typeof answers[q.key]==='boolean'?(answers[q.key]?'Yes':'No'):answers[q.key])}</dd>`).join('')}</dl><h3>Photography timeline</h3>${status.timeline.map(x=>`<p>${Math.floor(x.start/60).toString().padStart(2,'0')}:${(x.start%60).toString().padStart(2,'0')} · ${esc(x.title)}${x.location?' · '+esc(x.location):''}${x.instructions?' · '+esc(x.instructions):''}</p>`).join('')}<h3>Photo groups</h3><p>${status.groups.map(esc).join(' · ')||'No groups listed'}</p><label class="check"><input type="checkbox" data-wbm-confirm><span>I have checked this version and want to send it to my photography booking with Mark.</span></label><p data-wbm-error role="alert"></p><div class="actions"><button type="button" data-wbm-edit>Back to details</button><button type="button" data-wbm-close>Cancel</button><button type="button" class="primary" data-wbm-send disabled>Send final timings to Mark</button></div>`;
  dialog.querySelector('[data-wbm-confirm]').onchange=e=>dialog.querySelector('[data-wbm-send]').disabled=!e.target.checked;
  dialog.querySelector('[data-wbm-close]').onclick=close;
  dialog.querySelector('[data-wbm-edit]').onclick=()=>{status.answers=answers;edit()};
  dialog.querySelector('[data-wbm-send]').onclick=async e=>{e.target.disabled=true;try{
   await window.ivoryPlannerReadyForTimings();
   const result=await ivory.api('/api/wbm-timings',{method:'POST',body:{confirmed:true,answers,revision:status.revision,hub_revision:status.hub_revision}});
   dialog.innerHTML=`<h2>${result.status==='received'?'Received by Mark':'Saved for transfer to Mark'}</h2><p>${result.status==='received'?'Your final timings are in your photography booking.':'Your submitted copy is saved securely. Mark’s booking system will collect and check it automatically. Receipt has not been confirmed yet.'}</p><button type="button" data-wbm-close>Close</button>`;dialog.querySelector('[data-wbm-close]').onclick=close;
  }catch(error){dialog.querySelector('[data-wbm-error]').textContent=error.message;e.target.disabled=false;}};
 }
 button.onclick=async()=>{button.disabled=true;try{
  if(!window.ivoryPlannerReadyForTimings)throw Error('The planner is still loading. Please try again.');
  await window.ivoryPlannerReadyForTimings();status=await ivory.api('/api/wbm-timings');if(!status.linked)throw Error('Your booking link is unavailable. Nothing was sent.');
  edit();dialog.showModal();
 }catch(error){window.alert(error.message)}finally{button.disabled=false}};
})();

