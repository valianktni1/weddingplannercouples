const {chromium}=require(process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES+'/playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.WBM_TEST_CHROME,args:['--no-sandbox','--disable-dev-shm-usage']});
 try{
 const page=await browser.newPage({viewport:{width:390,height:844}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 const base=process.env.PLANNER_TEST_URL||'http://127.0.0.1:8765';
 await page.goto(base+'/login');await page.locator('[name=email]').fill('test@example.com');await page.locator('[name=password]').fill('test-only-long-password');await page.locator('button.primary').click();await page.locator('.wedding-intro').waitFor();
 // Installation prompts are a separate tested flow; dismiss if offered.
 if(await page.locator('#planner-install[open]').count())await page.getByRole('button',{name:'Maybe later',exact:true}).click();
 const original=(await page.evaluate(()=>ivory.api('/api/state'))).state;
 const open=async()=>page.locator('.top [data-couple-menu]').click();
 await page.locator('[data-couple-page=tasks]').first().count();
 await page.locator('.page-content').evaluate(el=>el.scrollTop=el.scrollHeight);
 const y=await page.locator('.page-content').evaluate(el=>el.scrollTop);assert(y>0);
 await open();assert.equal(await page.locator('.planner-menu-group h3').count(),6);
 await page.locator('[data-couple-close]').click();assert(Math.abs(await page.locator('.page-content').evaluate(el=>el.scrollTop)-y)<3,'close lost page position');
 for(const width of [320,390,736,1280])for(const dark of [false,true]){
  await page.setViewportSize({width,height:844});await page.locator('#ivory-planner').evaluate((el,d)=>el.classList.toggle('dark',d),dark);await open();
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'menu overflow');
  await page.locator('#couple-menu a').last().scrollIntoViewIfNeeded();
  assert(await page.locator('#couple-menu a').last().evaluate(el=>{const r=el.getBoundingClientRect();return el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))}),'last menu item covered');
  await page.locator('[data-couple-close]').click();
 }
 await page.setViewportSize({width:390,height:844});await open();await page.locator('#couple-menu [data-couple-page=money]').click();await page.locator('[data-action=edit-budget]').click();await page.locator('#f-budget').fill('99999');await page.locator('#ip-main h1').click();await open();page.once('dialog',d=>d.dismiss());await page.locator('#couple-menu [data-couple-page=home]').click();assert.equal(await page.locator('#f-budget').inputValue(),'99999');await page.locator('[data-couple-close]').click();await page.locator('[data-action=cancel]').click();
 await open();await page.locator('#couple-menu [data-couple-route=seating]').click();await page.locator('#hub-room').waitFor();await open();assert.equal(await page.locator('#couple-menu [data-couple-route=seating]').getAttribute('aria-current'),'page');await page.locator('[data-couple-close]').click();
 await page.locator('[data-hub=table-new]').click();await page.locator('#h-tableName').fill('Unfinished table');await open();page.once('dialog',d=>d.dismiss());await page.locator('#couple-menu [data-couple-route=packs]').click();assert.equal(await page.locator('#h-tableName').inputValue(),'Unfinished table');page.once('dialog',d=>d.accept());await page.locator('#couple-menu [data-couple-route=packs]').click();await page.locator('#pack-pdf').waitFor();assert(await page.locator('#couple-menu').isHidden());
 await open();await page.locator('#couple-menu [data-couple-route=invitations]').click();await page.locator('#create-invite').waitFor();assert.equal(new URL(page.url()).hash,'#guest-invitations');assert.equal(await page.locator('.guest-journey a').count(),4);assert(await page.locator('#create-invite').isVisible());
 assert.deepEqual((await page.evaluate(()=>ivory.api('/api/state'))).state,original,'navigation altered plan');assert.deepEqual(errors,[]);
 await page.screenshot({path:'/tmp/planner-v161-website.png'});
 console.log('PASS grouped menu, close position, widths/dark mode, reachable final item, planner and Hub unsaved guards, active tools, direct invitation link, guest sequence and unchanged state.');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
