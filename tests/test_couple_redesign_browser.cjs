/* Served, isolated sample installation. No external mail or production data. */
const {chromium}=require(process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES+'/playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const base=process.env.PLANNER_TEST_URL||'http://127.0.0.1:8765';
(async()=>{
 const args=process.env.PLANNER_TEST_LAMBDA?(await import(process.env.PLANNER_TEST_LAMBDA)).default.args:['--no-sandbox'];
 const browser=await chromium.launch({headless:true,executablePath:process.env.WBM_TEST_CHROME||undefined,args});
 try{
 const page=await browser.newPage({viewport:{width:390,height:844}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(base+'/login');await page.locator('[name=email]').fill('test@example.com');await page.locator('[name=password]').fill('test-only-long-password');await page.locator('button.primary').click();await page.waitForURL('**/app*');await page.locator('.wedding-intro').waitFor();
 await page.locator('[data-theme-toggle]').click();assert(await page.locator('#ivory-planner').evaluate(el=>el.classList.contains('dark')));await page.locator('[data-theme-toggle]').click();
 const original=await page.evaluate(()=>ivory.api('/api/state'));
 async function clearAtBottom(selector){
  const target=page.locator(selector).first();await target.scrollIntoViewIfNeeded();
  const result=await target.evaluate(el=>{const scroll=document.querySelector('.page-content').getBoundingClientRect(),dock=document.querySelector('#couple-dock'),d=dock.getBoundingClientRect(),r=el.getBoundingClientRect();return {top:r.top,bottom:r.bottom,scrollTop:scroll.top,scrollBottom:scroll.bottom,dockTop:d.top,dockHidden:dock.hidden,dockDisplay:getComputedStyle(dock).display,dockPosition:getComputedStyle(dock).position,width:document.documentElement.scrollWidth,viewport:innerWidth}});
  assert(result.bottom<=result.scrollBottom+2&&result.top>=result.scrollTop-2,'control clipped: '+selector+' '+JSON.stringify(result));
  if(!result.dockHidden&&result.dockDisplay!=='none')assert(result.scrollBottom<=result.dockTop+2,'dock overlays content '+JSON.stringify(result));
  assert(result.dockPosition!=='fixed'&&result.dockPosition!=='absolute','dock must occupy its own row');
  assert(result.width<=result.viewport+1,'horizontal page overflow');
 }
 const screens={home:'.wedding-intro',day:'[data-action="edit-day"]',test:'#s-a',calendar:'.cal-grid',money:'[data-action="edit-budget"]',suppliers:'[data-action="add-supplier"]',guests:'[data-action="add-guest"]',tasks:'[data-action="add-task"]',final:'[data-action="full-export"]',account:'[data-action="edit-details"]'};
 for(const [key,selector] of Object.entries(screens)){
  await page.locator('.top [data-couple-menu]').click();await page.locator('#couple-menu [data-couple-page="'+key+'"]').click();await page.locator(selector).first().waitFor();assert.equal(await page.locator('#couple-menu').getAttribute('hidden'),'');
 }
 assert.deepEqual((await page.evaluate(()=>ivory.api('/api/state'))).state,original.state,'navigation changed saved plan');
 await page.locator('#couple-dock [data-couple-page="home"]').click();await page.locator('.wedding-intro').waitFor();
 for(const width of [320,390,736,768,1280])for(const dark of [false,true]){
  await page.setViewportSize({width,height:844});await page.locator('#ivory-planner').evaluate((el,d)=>el.classList.toggle('dark',d),dark);
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'dashboard overflow '+width);
 }
 const output=process.env.PLANNER_DESIGN_QA_DIR||'/tmp';
 await page.setViewportSize({width:390,height:844});await page.locator('#ivory-planner').evaluate(el=>el.classList.remove('dark'));await page.screenshot({path:path.join(output,'planner-redesign-home-mobile.png')});await page.locator('[data-theme-toggle]').click();await page.screenshot({path:path.join(output,'planner-redesign-home-dark.png')});await page.locator('[data-theme-toggle]').click();await page.setViewportSize({width:1280,height:900});await page.screenshot({path:path.join(output,'planner-redesign-home-desktop.png')});await page.setViewportSize({width:390,height:844});
 await page.locator('#couple-dock [data-couple-page="money"]').click();await page.locator('[data-action="edit-budget"]').click();await page.locator('#f-budget').fill('19000');await page.locator('#ip-main h1').click();await page.waitForFunction(()=>!document.querySelector('#couple-dock').hidden);
 page.once('dialog',d=>d.dismiss());await page.locator('#couple-dock [data-couple-page="home"]').click();assert.equal(await page.locator('#f-budget').inputValue(),'19000');assert.equal(await page.locator('#ivory-planner').getAttribute('data-planner-page'),'money');
 // Editing hides the dock and an actual viewport reduction must retain Save.
 await page.locator('#f-budget').focus();await page.setViewportSize({width:390,height:460});await page.waitForFunction(()=>document.querySelector('#couple-dock').hidden);await clearAtBottom('[data-action="save-budget"]');
 await page.locator('[data-action="save-budget"]').click();await page.waitForFunction(()=>document.querySelector('#ip-save').textContent.startsWith('Saved'));
 assert.equal((await page.evaluate(()=>ivory.api('/api/state'))).state.budget,19000);
 await page.setViewportSize({width:390,height:844});
 // A long timings form keeps its LAST submit button above the dock.
 await page.locator('.top [data-couple-menu]').click();await page.locator('#couple-menu [data-couple-page="day"]').click();await page.locator('[data-action="edit-day"]').click();
 for(const [width,height] of [[320,844],[390,844],[736,390]]){await page.setViewportSize({width,height});await clearAtBottom('[data-action="save-day"]')}
 await page.addStyleTag({content:'#ivory-planner.couple-app{font-size:24px!important}#ivory-planner.couple-app button,#ivory-planner.couple-app input,#ivory-planner.couple-app select,#ivory-planner.couple-app textarea{font-size:24px!important}'});
 await page.setViewportSize({width:320,height:844});await clearAtBottom('[data-action="save-day"]');await page.locator('[data-action="save-day"]').click();await page.waitForFunction(()=>document.querySelector('#ip-save').textContent.startsWith('Saved'));
 // Linked WBM controls remain reachable from Menu and the dialog stays above navigation.
 await page.setViewportSize({width:390,height:844});await page.locator('.top [data-couple-menu]').click();await page.getByRole('button',{name:'Send final timings to Mark',exact:true}).click();await page.locator('dialog[open]').waitFor();
 await page.locator('dialog button[type=submit]').scrollIntoViewIfNeeded();assert(await page.locator('dialog button[type=submit]').evaluate(el=>{const r=el.getBoundingClientRect();return el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))}));await page.locator('[data-wbm-close]').click();
 // Website manual-share control and its generated result are reachable at the bottom.
 await page.goto(base+'/website');await page.locator('#website-fields input').first().waitFor();
 for(const width of [320,390,736,1280])for(const dark of [false,true]){await page.setViewportSize({width,height:844});await page.locator('#ivory-planner').evaluate((el,d)=>el.classList.toggle('dark',d),dark);await clearAtBottom('#create-invite')}
 await page.locator('[name=published]').check();await page.locator('#website-form button.primary').click();await page.waitForFunction(()=>document.querySelector('#web-status').textContent.startsWith('Saved'));await page.locator('#invitation-guests input[type=checkbox]').first().check();await page.locator('#create-invite').click();await page.locator('#invitation-copy').waitFor();assert.match(await page.locator('#invitation-copy').inputValue(),/weddings.*invite/);
 await clearAtBottom('#invite-result');
 await page.goto(base+'/files');await page.locator('#file-list').waitFor();await page.setViewportSize({width:390,height:844});await clearAtBottom('#upload-form button');
 await page.goto(base+'/hub#sharing');await page.locator('#hub-main h1').waitFor();
 for(const width of [320,390,736,1280]){await page.setViewportSize({width,height:844});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Hub page overflow '+width)}
 // Guided setup and the relocated sign-out control remain usable.
 await page.setViewportSize({width:390,height:844});await page.locator('.top [data-couple-menu]').click();await page.locator('#couple-menu form button').click();await page.waitForURL(base+'/');
 await page.goto(base+'/login');await page.locator('[name=email]').fill('new@example.com');await page.locator('[name=password]').fill('test-only-long-password');await page.locator('button.primary').click();await page.locator('#f-nameA').waitFor();assert(await page.locator('#couple-dock').isHidden());
 await page.locator('#f-nameA').fill('Sam');await page.locator('#f-nameB').fill('Alex');await page.locator('[data-action=setup-next]').click();await page.getByRole('heading',{name:'What have you booked?'}).waitFor();await page.locator('[data-action=setup-next]').click();await page.getByRole('heading',{name:'What matters most to you?'}).waitFor();await page.locator('[data-action=setup-next]').click();await page.locator('.wedding-intro').waitFor();assert(await page.locator('#couple-dock').isVisible());
 assert((await page.evaluate(()=>ivory.api('/api/state'))).state.ready);
 assert.deepEqual(errors,[]);console.log('PASS: all ten planner pages, state-preserving navigation, bottom action clearance, keyboard-height viewport, enlarged text, guarded unfinished work, real budget/timing saves, manual website share link, documents, Hub, linked WBM modal, sign-out and guided setup; widths 320/390/736/768/1280 and light/dark.');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
