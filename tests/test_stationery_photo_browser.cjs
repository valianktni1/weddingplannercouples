const {chromium}=require(process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES+'/playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.WBM_TEST_CHROME,args:['--no-sandbox']});
 try{
 const page=await browser.newPage({viewport:{width:390,height:844}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 const base=process.env.PLANNER_TEST_URL||'http://127.0.0.1:8765';
 await page.goto(base+'/login');await page.locator('[name=email]').fill('test@example.com');await page.locator('[name=password]').fill('test-only-long-password');await page.locator('button.primary').click();await page.locator('.wedding-intro').waitFor();
 if(await page.locator('#planner-install[open]').count())await page.getByRole('button',{name:'Maybe later',exact:true}).click();
 const original=(await page.evaluate(()=>ivory.api('/api/state'))).state;
 await page.goto(base+'/stationery');await page.locator('[data-collection=photo]').click();await page.locator('[data-item=day]').click();
 await page.locator('[name=arrival]').fill('Please arrive at 12.30pm');await page.locator('[name=message]').fill('Our wording survives photo upload');
 // Upload a real asymmetric image directly inside the stationery editor.
 const photo=await page.evaluate(()=>{const c=document.createElement('canvas');c.width=600;c.height=800;const x=c.getContext('2d');for(let y=0;y<800;y+=40)for(let z=0;z<600;z+=40){x.fillStyle=`rgb(${z%256},${y%256},${(y+z)%256})`;x.fillRect(z,y,40,40);}return c.toDataURL('image/png').split(',')[1];});
 await page.locator('#stationery-photo-upload').setInputFiles({name:'our-own-photo.png',mimeType:'image/png',buffer:Buffer.from(photo,'base64')});
 await page.waitForFunction(()=>document.querySelector('#stationery-status').textContent.includes('Photograph uploaded'));
 await page.waitForFunction(()=>document.querySelector('#stationery-crop-status').textContent==='');
 assert.equal(await page.locator('[name=message]').inputValue(),'Our wording survives photo upload');
 assert(await page.locator('[name=photo]').inputValue());
 const frame=()=>page.locator('#stationery-crop-canvas').evaluate(c=>c.toDataURL());
 const before=await frame();
 for(const [name,value] of [['photo_zoom','1.75'],['photo_x','83'],['photo_y','24']])await page.locator(`[name=${name}]`).fill(value);
 assert.notEqual(await frame(),before,'sliders must change actual visible crop');
 await page.locator('[name=photo_focus]').selectOption('bottom');assert.equal(await page.locator('[name=photo_y]').inputValue(),'100');assert.equal(await page.locator('[name=photo_zoom]').inputValue(),'1');
 await page.locator('[data-reset-crop]').click();assert.equal(await page.locator('[name=photo_y]').inputValue(),'50');
 await page.locator('[name=photo_zoom]').fill('2');await page.locator('#stationery-crop-canvas').scrollIntoViewIfNeeded();
 const box=await page.locator('#stationery-crop-canvas').boundingBox();await page.mouse.move(box.x+box.width/2,box.y+box.height/2);await page.mouse.down();await page.mouse.move(box.x+box.width/2-30,box.y+box.height/2-20,{steps:4});await page.mouse.up();
 assert(Number(await page.locator('[name=photo_x]').inputValue())>50,'drag horizontal');assert(Number(await page.locator('[name=photo_y]').inputValue())>50,'drag vertical');
 for(const width of [320,390,736,1280])for(const dark of [false,true]){await page.setViewportSize({width,height:844});await page.locator('#ivory-planner').evaluate((el,d)=>el.classList.toggle('dark',d),dark);assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'photo editor overflow '+width);}
 await page.setViewportSize({width:390,height:844});await page.locator('#ivory-planner').evaluate(el=>el.classList.remove('dark'));
 // Failed uploads preserve the selected photo, crop and unsaved wording.
 const selected=await page.locator('[name=photo]').inputValue(),position=await page.locator('[name=photo_x]').inputValue();
 await page.locator('#stationery-photo-upload').setInputFiles({name:'broken.jpg',mimeType:'image/jpeg',buffer:Buffer.from('invalid image')});
 await page.waitForFunction(()=>document.querySelector('#stationery-status').textContent.includes('previous photo are still here'));
 assert.equal(await page.locator('[name=photo]').inputValue(),selected);assert.equal(await page.locator('[name=photo_x]').inputValue(),position);assert.equal(await page.locator('[name=message]').inputValue(),'Our wording survives photo upload');
 await page.locator('[name=photo_mode]').selectOption('mono');
 await page.locator('[data-preview]').click();await page.locator('.stationery-picture').waitFor();assert.equal(await page.locator('#stationery-issues').innerText(),'');
 await page.locator('#stationery-crop-canvas').scrollIntoViewIfNeeded();await page.screenshot({path:'/tmp/planner-photo-editor-mobile.png'});
 await page.locator('#stationery-form button[type=submit]').click();await page.locator('#stationery-confirm').waitFor();await page.waitForFunction(()=>document.querySelector('.stationery-picture')&&document.querySelector('#stationery-issues').textContent==='');await page.locator('#stationery-confirm').check();
 for(const fmt of ['pdf','png']){const download=page.waitForEvent('download');await page.locator(`[data-download=${fmt}]`).first().click();await (await download).saveAs('/tmp/planner-photo-invitation.'+fmt);}
 const saved=await page.evaluate(()=>ivory.api('/api/stationery'));assert.equal(saved.drafts.day.data.photo,selected);assert.equal(Number(saved.drafts.day.data.photo_x),Number(position));assert.equal(saved.drafts.day.data.photo_zoom,'2.0');
 await page.reload();await page.locator('[data-draft=day]').click();assert.equal(await page.locator('[name=photo_x]').inputValue(),position);assert.equal(await page.locator('[name=photo_zoom]').inputValue(),'2');
 assert.deepEqual((await page.evaluate(()=>ivory.api('/api/state'))).state,original,'photo workflow must not change wedding plans or website');
 assert.deepEqual(errors,[]);console.log('PASS in-editor upload, wording preservation, live sliders, drag, presets/reset, failed upload recovery, narrow/dark layouts, real PDF/PNG, saved crop reload and unchanged wedding plans.');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
