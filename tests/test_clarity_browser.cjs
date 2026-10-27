/* Isolated sample accounts only. No live mail, payments or couple records. */
const {chromium}=require(process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES+'/playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.WBM_TEST_CHROME,args:['--no-sandbox']});
 try{
  const page=await browser.newPage({viewport:{width:390,height:844}}),errors=[],base=process.env.PLANNER_TEST_URL||'http://127.0.0.1:8765';page.on('pageerror',e=>errors.push(e.message));const state=async()=>(await (await page.request.get(base+'/api/state')).json()).state;
  await page.goto(base+'/login');await page.locator('[name=email]').fill('new@example.com');await page.locator('[name=password]').fill('test-only-long-password');await page.locator('button.primary').click();
  await page.locator('[data-action=setup-next]').waitFor();assert.match(await page.locator('#ip-main').innerText(),/Each Continue saves that step/);
  await page.locator('#f-nameA').fill('Alex');await page.locator('#f-nameB').fill('Sam');await page.locator('[data-action=setup-next]').click();await page.getByRole('heading',{name:'What have you booked?'}).waitFor();assert.match(await page.locator('#ip-main').innerText(),/Nothing booked yet/);
  await page.locator('[data-action=setup-next]').click();await page.getByRole('heading',{name:'Make it yours'}).waitFor();assert.match(await page.locator('#ip-main').innerText(),/send an invitation when you choose Open our planner/);
  await page.locator('[data-action=setup-next]').click();await page.locator('.wedding-intro').waitFor();if(await page.locator('#planner-install[open]').count())await page.locator('[data-install-later]').click();
  await page.locator('#ip-save').filter({hasText:'All changes saved'}).waitFor();const before=await state();
  assert.match(await page.locator('.next-step').innerText(),/Start with a booking/);await page.locator('.next-step [data-action=add-supplier]').click();await page.locator('#f-supplierName').fill('Keep this unfinished booking');
  page.once('dialog',d=>d.dismiss());await page.locator('.next-step [data-action=add-supplier]').click();assert.equal(await page.locator('#f-supplierName').inputValue(),'Keep this unfinished booking');
  page.once('dialog',d=>d.accept());await page.locator('[data-action=cancel]').click();
  const guide=page.locator('.planner-guide');assert.equal(await guide.getAttribute('open'),null);await guide.locator('summary').click();assert.equal(await guide.locator('.planning-link').count(),6);
  for(const width of [320,390,736,1280])for(const dark of [false,true]){await page.setViewportSize({width,height:844});await page.locator('#ivory-planner').evaluate((el,d)=>el.classList.toggle('dark',d),dark);assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'open guide overflow '+width);}
  await page.setViewportSize({width:390,height:844});await page.locator('#ivory-planner').evaluate(el=>el.classList.remove('dark'));await guide.scrollIntoViewIfNeeded();await page.screenshot({path:'/tmp/planner-v193-guide.png'});
  // Same-page guide links must retain the unfinished-form navigation guard.
  await page.locator('.quick-add [data-action=add-guest]').click();await page.locator('#f-guestName').fill('Unfinished guest');
  page.once('dialog',d=>d.dismiss());await guide.locator('[data-action=suppliers]').click();assert.equal(await page.locator('#f-guestName').inputValue(),'Unfinished guest');page.once('dialog',d=>d.accept());await page.locator('[data-action=cancel]').click();
  await guide.locator('[data-action=suppliers]').click();await page.getByRole('heading',{name:'Our wedding team'}).waitFor();
  await page.locator('#couple-dock [data-couple-page=money]').click();await page.locator('[data-action=edit-budget]').waitFor();assert.match(await page.locator('#ip-main').innerText(),/save the booking and total, add its instalments/);await page.locator('[data-action=suppliers]').click();await page.getByRole('heading',{name:'Our wedding team'}).waitFor();
  assert.deepEqual(await state(),before,'guidance changed the saved plan');
  await page.goto(base+'/stationery');assert.match(await page.locator('#stationery-main').innerText(),/Downloading stationery does not send invitations/);await page.locator('#stationery-main a[href="/website#guest-invitations"]').click();await page.locator('#create-invite').waitFor();assert.match(await page.locator('.website-editor').innerText(),/leave it blank to copy and share it yourself/);await page.locator('.website-editor a[href="/stationery"]').click();await page.locator('#stationery-main').waitFor();assert.deepEqual(await state(),before);
  // The active-access flag should lead to the existing summary, not an upgrade error.
  await page.route('**/api/billing',route=>route.fulfill({json:{already_active:true}}));await page.goto(base+'/app');await page.locator('.wedding-intro').waitFor();await page.locator('.top [data-couple-menu]').click();await page.locator('#buy-access').click();await page.waitForURL('**/upgrade');await page.getByRole('heading',{name:'Your access is active'}).waitFor();assert.deepEqual(errors,[]);
  console.log('PASS setup clarity, first-booking action, unfinished-form protection, guide routes, mobile/dark layouts, budget path, stationery/RSVP cross-links, unchanged saved plan and active-access summary.');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
