(()=>{
 const host=document.getElementById('stationery-app'),status=document.getElementById('stationery-status'),esc=ivory.escape;
 let model,step=1,collection=null,kind='day',data=null,dirty=false,busy=false,previewed=false,serial=0,cropImage=null,cropSerial=0;
 function lockForm(on){host.querySelectorAll('#stationery-form input,#stationery-form textarea,#stationery-form select,#stationery-form button').forEach(el=>el.disabled=on||model.readonly)}
 const hints={day:'Your ceremony and reception invitation.',evening:'Separate wording and arrival details for evening guests.',save_date:'Share your date before the formal invitation.',welcome:'A welcome for the venue entrance.',menu:'Use your own confirmed menu wording.',place:'One guest, or a PDF containing a card for each selected guest.',table:'One table, or a PDF of all assigned table names.',seating:'A guest-facing chart using your current table assignments.',thanks:'A personal thank-you after your day.'};
 const label=(s)=>s.charAt(0).toUpperCase()+s.slice(1);
 const field=(key,title,type='text')=>`<label class="field"><span>${title}</span><input name="${key}" type="${type}" value="${esc(data[key])}" maxlength="${({names:220,venue:180,intro:160,arrival:160,recipient:160,table_name:100})[key]||240}"></label>`;
 const textarea=(key,title)=>`<label class="field"><span>${title}</span><textarea name="${key}" rows="${key==='menu'?10:3}" maxlength="${key==='menu'?1800:500}">${esc(data[key])}</textarea></label>`;
 const options=(name,title,values,value)=>`<label class="field"><span>${title}</span><select name="${name}">${values.map(([k,l])=>`<option value="${esc(k)}" ${value===k?'selected':''}>${esc(l)}</option>`).join('')}</select></label>`;
 function feedback(message,error=false){document.getElementById('stationery-recovery').hidden=!(error&&data);status.textContent=message;status.setAttribute('role',error?'alert':'status');if(error)status.scrollIntoView({block:'nearest'})}
 function guard(){return !dirty||confirm('Leave this unfinished design? Save it first to keep your changes.')}
 function nav(){return `<nav class="stationery-steps" aria-label="Stationery steps">${['Collection','Item','Personalise','Preview & download'].map((name,i)=>`<button type="button" data-stage="${i+1}" ${step===i+1?'aria-current="step"':''} ${i>0&&!collection||i>1&&!data?'disabled':''}>${i+1}. ${name}</button>`).join('')}</nav>`}
 function render(){
  const offer=document.getElementById('stationery-bespoke-offer');if(offer)offer.hidden=step!==1;
  let html=nav();
  if(step===1){
   html+=`<div class="stationery-collections">${Object.entries(model.collections).map(([key,c])=>`<button type="button" class="collection-card" data-collection="${key}"><img src="/api/stationery/collections/${key}.png" alt="${esc(c.name)} invitation example" loading="lazy"><strong>${esc(c.name)}</strong><small>${esc(c.description)}</small></button>`).join('')}</div>`;
   const drafts=Object.entries(model.drafts).filter(([,d])=>d.revision);
   if(drafts.length)html+=`<section class="stationery-draft-list"><h2>Your saved designs</h2>${drafts.map(([key,d])=>`<button type="button" class="planning-link" data-draft="${key}"><span><strong>${esc(model.kinds[key].name)}</strong><small>${esc(model.collections[d.data.collection].name)} · ${d.review_needed?'Wedding details changed — review needed':d.download_outdated?'Saved design changed — download a new copy':d.exported_at?'Downloaded '+new Date(d.exported_at*1000).toLocaleDateString('en-GB'):'Saved draft'}</small></span><span aria-hidden="true">›</span></button>`).join('')}</section>`;
  }else if(step===2){html+=`<h2>${esc(model.collections[collection].name)}</h2><p>What would you like to make?</p><div class="stationery-items">${Object.entries(model.kinds).map(([key,item])=>`<button type="button" data-item="${key}"><strong>${esc(item.name)}</strong><br><span>${esc(hints[key])}</span></button>`).join('')}</div>`}
  else if(step===3){
   const fields=[];fields.push(options('palette','Colour palette',Object.keys(model.collections[data.collection].palettes).map(k=>[k,label(k)]),data.palette));fields.push(options('size','Paper size',model.kinds[kind].sizes.map(k=>[k,model.sizes[k].name]),data.size));
   if(!['place','table','menu'].includes(kind)){fields.push(field('names','Your names'));if(kind!=='thanks')fields.push(field('date','Wedding date','date'));}
   if(['day','evening','save_date'].includes(kind)){fields.push(field('intro','Opening line'),textarea('message','Invitation wording'),field('venue',kind==='evening'?'Evening venue':'Venue'));if(kind!=='save_date')fields.push(field('arrival','Arrival details · e.g. Arrive at 12.30pm'));fields.push(field('closing','Closing line'),field('recipient','Guest names on this invitation (optional)'));}
   if(kind==='menu')fields.push(textarea('menu','Your menu · leave a blank line between courses'));
   if(kind==='thanks')fields.push(textarea('message','Your thank-you message'));
   if(['place','table','seating'].includes(kind))fields.push(options('guest_scope','Guests to include',[['accepted','Confirmed guests'],['invited','Everyone except declined']],data.guest_scope));
   if(kind==='place'){const guests=model.guests.filter(g=>g.rsvp==='Accepted'||data.guest_scope==='invited'&&g.rsvp!=='Declined');fields.push(options('guest_id','Preview / download one guest', [['','Use a name entered below'],...guests.map(g=>[g.id,g.name])],data.guest_id),field('recipient','Name (when no guest is selected)'));}
   if(kind==='table'){fields.push(field('table_name','Table name / number'));}
   if(data.collection==='photo'&&['day','evening','save_date','welcome','thanks'].includes(kind)){
    fields.push(options('photo','Your photograph',[['','Choose a photograph'],...model.photos.map(p=>[p.id,p.name])],data.photo));
    fields.push('<label class="field"><span>Upload a photograph</span><input id="stationery-photo-upload" type="file" accept="image/jpeg,image/png,image/webp"><small>JPEG, PNG or WebP · up to 10 MB and 20 megapixels. Your photo stays private unless you share or publish it.</small></label>');
    fields.push(options('photo_mode','Photo finish',[['colour','Colour'],['mono','Black & white']],data.photo_mode),options('photo_focus','Starting position',[['centre','Centre'],['top','Keep the top of the photo'],['bottom','Keep the bottom of the photo']],data.photo_focus));
    fields.push(`<section class="stationery-crop" aria-label="Photograph framing"><h3>Position your photograph</h3><p>Drag the photo or use the sliders. This frame shows the area used on your chosen paper size.</p><canvas id="stationery-crop-canvas" aria-label="Live photograph crop preview"></canvas><p id="stationery-crop-status" role="status"></p>${[['photo_x','Horizontal position',0,100,1],['photo_y','Vertical position',0,100,1],['photo_zoom','Zoom',1,3,.01]].map(([key,title,min,max,step])=>`<label class="field"><span>${title} <output data-crop-value="${key}">${key==='photo_zoom'?Number(data[key]).toFixed(2)+'×':Math.round(Number(data[key]))+'%'}</output></span><input type="range" name="${key}" min="${min}" max="${max}" step="${step}" value="${esc(data[key])}"></label>`).join('')}<button type="button" data-reset-crop>Reset photo position</button></section>`);
   }
   html+=`<h2>${esc(model.kinds[kind].name)}</h2><p>${esc(model.collections[data.collection].name)} · ${esc(hints[kind])}</p>${model.drafts[kind].review_needed?'<p class="stationery-stale">Your wedding details or guest list changed. Check this design before downloading again.</p>':''}<div class="stationery-edit"><form id="stationery-form">${fields.join('')}<div class="stationery-actions"><button type="button" data-use-current>Use current wedding details</button><button class="primary" type="submit">Save & preview</button></div></form><section class="stationery-preview"><h3>Your preview</h3><p>Update the preview to see your changes.</p><button type="button" data-preview>Update preview</button><div id="stationery-preview-image"></div><p id="stationery-issues" role="status"></p></section></div>`;
  }else{
   html+=`<h2>Check your ${esc(model.kinds[kind].name.toLowerCase())}</h2><p>${esc(model.collections[data.collection].name)} · ${esc(model.sizes[data.size].name)}</p><section class="stationery-preview"><div id="stationery-preview-image"></div><p id="stationery-issues" role="status"></p><div class="stationery-actions"><button type="button" data-back-edit>Edit wording or design</button></div><label class="check"><input id="stationery-confirm" type="checkbox"><span>I have checked the names, wording, date and details in this preview.</span></label><label class="check"><input id="stationery-bleed" type="checkbox"><span>Add 3 mm bleed for a professional printer (PDF only)</span></label><div class="stationery-actions"><button type="button" class="primary" data-download="pdf" disabled>Download print PDF</button><button type="button" data-download="png" disabled>Download sharing image</button>${['place','table'].includes(kind)?`<button type="button" data-download="pdf" data-batch="true" disabled>Download all ${kind==='place'?'guests on A4 sheets':'assigned tables'} (PDF)</button>`:''}</div><p class="stationery-print-note">PDFs use the chosen paper size and embedded fonts. Print at actual size / 100%. Sharing images are for screens. All-guest place cards come on A4 cutting sheets, without bleed. Check a test print before ordering a batch.${data.size==='folded'?' The fine centre line marks the fold.':''}</p>${['day','evening','save_date'].includes(kind)?'<p>Send the image with their <a href="/website#guest-invitations">personal RSVP link</a>. Downloading sends nothing.</p>':''}</section>`;
  }
  host.innerHTML=html;loadCrop();if(model.readonly){host.querySelectorAll('#stationery-form input,#stationery-form textarea,#stationery-form select,#stationery-form button').forEach(e=>e.disabled=true);feedback('View only. You can download saved designs; editing access has ended.')}
 }
 async function load(){model=await ivory.api('/api/stationery');feedback(model.readonly?'View only. You can download saved designs.':'Choose a collection, or continue a saved design.');render()}
 function readForm(){const form=document.getElementById('stationery-form');if(form)for(const [k,v] of new FormData(form))if(typeof v==='string')data[k]=v;}
 function cropValues(){
  for(const key of ['photo_x','photo_y','photo_zoom']){const input=host.querySelector(`[name="${key}"]`),out=host.querySelector(`[data-crop-value="${key}"]`);if(input)input.value=data[key];if(out)out.textContent=key==='photo_zoom'?Number(data[key]).toFixed(2)+'×':Math.round(Number(data[key]))+'%';}
 }
 function drawCrop(){
  const canvas=document.getElementById('stationery-crop-canvas');if(!canvas)return;
  const [w,h]=model.sizes[data.size].mm,ratio=w/(h*(kind==='welcome'?.58:.47));
  canvas.width=900;canvas.height=Math.round(900/ratio);
  const ctx=canvas.getContext('2d');ctx.fillStyle='#e8e4dd';ctx.fillRect(0,0,canvas.width,canvas.height);
  if(cropImage){const cw=Math.min(cropImage.naturalWidth,cropImage.naturalHeight*ratio)/Number(data.photo_zoom),ch=cw/ratio,left=(cropImage.naturalWidth-cw)*Number(data.photo_x)/100,top=(cropImage.naturalHeight-ch)*Number(data.photo_y)/100;ctx.drawImage(cropImage,left,top,cw,ch,0,0,canvas.width,canvas.height);if(data.photo_mode==='mono'){const pixels=ctx.getImageData(0,0,canvas.width,canvas.height);for(let i=0;i<pixels.data.length;i+=4){const grey=Math.round(.299*pixels.data[i]+.587*pixels.data[i+1]+.114*pixels.data[i+2]);pixels.data[i]=pixels.data[i+1]=pixels.data[i+2]=grey;}ctx.putImageData(pixels,0,0);}}
  cropValues();
 }
 function loadCrop(){
  const canvas=document.getElementById('stationery-crop-canvas'),my=++cropSerial;cropImage=null;if(!canvas)return;drawCrop();
  const note=document.getElementById('stationery-crop-status');note.textContent=data.photo?'Loading your photograph…':'Choose or upload a photograph to position it.';
  if(!data.photo)return;
  const img=new Image();img.onload=()=>{if(my!==cropSerial)return;cropImage=img;note.textContent='';drawCrop();};img.onerror=()=>{if(my===cropSerial)note.textContent='Your photograph could not be loaded. Choose it again or upload another.';};img.src='/api/files/'+encodeURIComponent(data.photo);
 }
 async function uploadPhoto(input){
  const file=input.files[0];if(!file||busy)return;readForm();
  try{
   if(!['image/jpeg','image/png','image/webp'].includes(file.type))throw Error('Choose a JPEG, PNG or WebP photograph.');
   if(file.size>10*1024*1024)throw Error('Choose a photograph smaller than 10 MB.');
   busy=true;lockForm(true);feedback('Uploading your photograph…');
   const body=new FormData();body.append('kind','cover');body.append('file',file);
   const result=await ivory.api('/api/files',{method:'POST',body});
   model.photos.push({id:result.id,name:file.name});data.photo=result.id;Object.assign(data,{photo_x:'50',photo_y:'50',photo_zoom:'1',photo_focus:'centre'});dirty=true;previewed=false;render();feedback('Photograph uploaded. Position it below, then save & preview.');
  }catch(err){feedback(err.message+' Your wording and previous photo are still here.',true)}finally{busy=false;lockForm(false);input.value='';enableDownloads();}
 }
 let drag=null;
 host.addEventListener('pointerdown',e=>{const c=e.target;if(c.id!=='stationery-crop-canvas'||!cropImage||busy||model.readonly)return;const r=c.getBoundingClientRect(),ratio=c.width/c.height,cw=Math.min(cropImage.naturalWidth,cropImage.naturalHeight*ratio)/Number(data.photo_zoom),ch=cw/ratio;drag={id:e.pointerId,x:e.clientX,y:e.clientY,px:Number(data.photo_x),py:Number(data.photo_y),dx:cropImage.naturalWidth-cw,dy:cropImage.naturalHeight-ch,cw,ch,w:r.width,h:r.height};c.setPointerCapture(e.pointerId);});
 host.addEventListener('pointermove',e=>{if(!drag||e.pointerId!==drag.id)return;const d=drag;data.photo_x=String(Math.round(Math.max(0,Math.min(100,d.px-(d.dx?(e.clientX-d.x)*d.cw/d.w/d.dx*100:0)))));data.photo_y=String(Math.round(Math.max(0,Math.min(100,d.py-(d.dy?(e.clientY-d.y)*d.ch/d.h/d.dy*100:0)))));dirty=true;previewed=false;drawCrop();});
 for(const event of ['pointerup','pointercancel','lostpointercapture'])host.addEventListener(event,()=>{drag=null;});
 async function preview(){readForm();const my=++serial;const result=await ivory.api('/api/stationery/'+kind+'/preview',{method:'POST',body:{data}});if(my!==serial)return;const container=document.getElementById('stationery-preview-image');if(container){container.innerHTML=`<img class="stationery-picture" alt="Your ${esc(model.kinds[kind].name.toLowerCase())} preview">`;container.querySelector('img').src=result.image;}const issues=document.getElementById('stationery-issues');if(issues)issues.textContent=result.issues.join(' ');previewed=result.issues.length===0;enableDownloads();}
 function enableDownloads(){host.querySelectorAll('[data-download]').forEach(b=>b.disabled=busy||!previewed||!document.getElementById('stationery-confirm')?.checked)}
 async function save(){readForm();lockForm(true);const draft=model.drafts[kind];const r=await ivory.api('/api/stationery/'+kind,{method:'PUT',body:{data,revision:draft.revision,source:draft.source}});model.drafts[kind]={...draft,data:structuredClone(data),revision:r.revision,source:r.source,review_needed:false};dirty=false;feedback('Design saved. Check your preview before downloading.');}
 async function doDownload(button){
  const draft=model.drafts[kind],response=await fetch('/api/stationery/'+kind+'/download',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':document.querySelector('meta[name=csrf-token]').content},body:JSON.stringify({revision:draft.revision,source:draft.source,format:button.dataset.download,batch:button.dataset.batch==='true',bleed:document.getElementById('stationery-bleed').checked?3:0})});
  if(!response.ok){const error=await response.json();throw Error(error.error||'The download could not be prepared.');}
  const blob=await response.blob(),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='our-'+kind+'-r'+draft.revision+'.'+button.dataset.download;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),10000);feedback('Download prepared. Saved files are snapshots—download again after changing the details.');
 }
 host.addEventListener('input',e=>{if(e.target.closest('#stationery-form')){dirty=true;previewed=false;if(e.target.name?.startsWith('photo_')){readForm();drawCrop();}}if(e.target.id==='stationery-confirm')enableDownloads()});
 host.addEventListener('change',e=>{if(e.target.id==='stationery-photo-upload'){uploadPhoto(e.target);return;}if(e.target.closest('#stationery-form')){dirty=true;previewed=false;readForm();if(e.target.name==='photo'){loadCrop();}else if(e.target.name==='photo_focus'){data.photo_x='50';data.photo_y=({top:'0',centre:'50',bottom:'100'})[data.photo_focus];data.photo_zoom='1';drawCrop();}else if(['size','photo_mode'].includes(e.target.name)){drawCrop();}if(e.target.name==='guest_scope'){readForm();data.guest_id='';render();}}if(e.target.id==='stationery-confirm')enableDownloads()});
 host.addEventListener('submit',async e=>{if(e.target.id!=='stationery-form')return;e.preventDefault();if(busy)return;busy=true;try{await save();step=4;render();await preview();}catch(err){feedback(err.message+' Your wording is still here. Save a copy before reloading.',true)}finally{busy=false;lockForm(false);enableDownloads()}});
 host.addEventListener('click',async e=>{
  const b=e.target.closest('button');if(!b||busy||b.type==='submit')return;
  try{
   readForm();
   if(b.dataset.collection){if(!guard())return;dirty=false;collection=b.dataset.collection;data=null;step=2;render();}
   else if(b.dataset.item||b.dataset.draft){if(!guard())return;dirty=false;kind=b.dataset.item||b.dataset.draft;const d=model.drafts[kind];collection=b.dataset.draft?d.data.collection:collection;data=structuredClone(d.data);if(data.collection!==collection){data.collection=collection;data.palette=Object.keys(model.collections[collection].palettes)[0];dirty=true;}step=model.readonly&&d.revision?4:3;previewed=false;render();if(step===4)await preview();}
   else if(b.dataset.stage){const next=Number(b.dataset.stage);if(next===4){if(step===4)return;busy=true;if(model.readonly){if(!model.drafts[kind].revision)throw Error('There is no saved design to download yet.');step=4;render();await preview();}else{await save();step=4;render();await preview();}}else if(next<3){if(!guard())return;dirty=false;step=next;render();}else{step=3;render();}}
   else if(b.hasAttribute('data-use-current')){readForm();if(confirm('Replace the names, date and venue with your current wedding details? Your other wording stays.')){for(const k of ['names','date','venue'])data[k]=model.defaults[kind][k];dirty=true;render();}}
   else if(b.hasAttribute('data-reset-crop')){Object.assign(data,{photo_x:'50',photo_y:'50',photo_zoom:'1',photo_focus:'centre'});host.querySelector('[name=photo_focus]').value='centre';dirty=true;previewed=false;drawCrop();}
   else if(b.hasAttribute('data-preview')){busy=true;readForm();lockForm(true);await preview();}
   else if(b.hasAttribute('data-back-edit')){step=3;render();}
   else if(b.dataset.download){busy=true;enableDownloads();await doDownload(b);}
  }catch(err){feedback(err.message,true)}finally{busy=false;lockForm(false);enableDownloads()}
 });
 document.getElementById('stationery-recovery').addEventListener('click',()=>{readForm();const blob=new Blob([JSON.stringify({item:kind,details:data},null,2)],{type:'text/plain'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='our-stationery-wording.txt';a.click();setTimeout(()=>URL.revokeObjectURL(url),10000)});
 window.addEventListener('beforeunload',e=>{if(dirty||busy){e.preventDefault();e.returnValue=''}});
 load().catch(e=>feedback(e.message,true));
})();
