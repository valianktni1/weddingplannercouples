const {chromium}=require(process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES+'/playwright');
const assert=require('node:assert/strict');
const base=process.env.PLANNER_TEST_URL||'http://127.0.0.1:8765';
(async()=>{
 const args=process.env.PLANNER_TEST_LAMBDA?(await import(process.env.PLANNER_TEST_LAMBDA)).default.args:['--no-sandbox'];
 const browser=await chromium.launch({headless:true,executablePath:process.env.WBM_TEST_CHROME||undefined,args});
 try{
  const page=await browser.newPage({viewport:{width:390,height:844}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'/login');await page.locator('[name=email]').fill('test@example.com');await page.locator('[name=password]').fill('test-only-long-password');await page.locator('button.primary').click();await page.waitForURL('**/app*');await page.locator('.wedding-intro').waitFor();
  assert.equal(await page.locator('#ip-save').innerText(),'All changes saved');
  await page.locator('.first-steps').waitFor();await page.locator('[data-action="hide-first-steps"]').click();assert.equal(await page.locator('.first-steps').count(),0);await page.reload();await page.locator('.wedding-intro').waitFor();assert.equal(await page.locator('.first-steps').count(),0);
  async function go(key){await page.locator('.top [data-couple-menu]').click();await page.locator('#couple-menu [data-couple-page="'+key+'"]').click()}
  await go('account');assert.match(await page.locator('#ip-main').innerText(),/Editing access is available until/);await page.locator('[data-action="show-first-steps"]').click();await page.locator('.first-steps').waitFor();
  await page.evaluate(async()=>{const p=await ivory.api('/api/state');p.state.payments[0].due=new Date(Date.now()-86400000).toISOString().slice(0,10);await ivory.api('/api/state',{method:'PUT',body:{state:p.state,revision:p.revision}})});await page.reload();await page.locator('.next-step').waitFor();assert.match(await page.locator('.next-step').innerText(),/payment needs checking/);await page.locator('.next-step [data-action="record-payment"]').click();await page.locator('#ip-extra:not([hidden])').waitFor();await page.locator('[data-action="cancel"]').click();
  const original=(await page.evaluate(()=>ivory.api('/api/state'))).state;
  await go('guests');assert.equal(await page.locator('a[href="/hub#seating"]').filter({hasText:'Arrange our tables'}).count(),1);
  await page.locator('#f-guestSearch').fill('PAT');assert.match(await page.locator('#guest-results-count').innerText(),/Showing 1 of 2/);assert.match(await page.locator('#guest-results').innerText(),/Pat/);
  await page.locator('#f-guestRsvp').selectOption('Waiting');assert.match(await page.locator('#guest-results').innerText(),/No guests match/);await page.locator('[data-action="clear-guest-filters"]').click();assert.match(await page.locator('#guest-results-count').innerText(),/Showing 2 of 2/);
  await page.locator('#f-guestRsvp').selectOption('Accepted');await page.locator('#f-guestAttendance').selectOption('Day');assert.match(await page.locator('#guest-results-count').innerText(),/Showing 1 of 2/);
  await page.locator('#ivory-planner').evaluate(el=>el.classList.add('dark'));await page.setViewportSize({width:320,height:640});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'guest filters overflow');assert(await page.locator('#couple-dock [data-couple-page=tasks] span').evaluate(el=>el.getBoundingClientRect().height<25),'checklist label split');await page.locator('#ivory-planner').evaluate(el=>el.classList.remove('dark'));
  assert.deepEqual((await page.evaluate(()=>ivory.api('/api/state'))).state,original,'filters changed saved guests');
  await page.screenshot({path:(process.env.PLANNER_DESIGN_QA_DIR||'/tmp')+'/planner-v150-guests.png'});
  await go('day');await page.screenshot({path:(process.env.PLANNER_DESIGN_QA_DIR||'/tmp')+'/planner-v150-timings.png'});assert.equal(await page.locator('.day-journey [aria-current="step"]').innerText(),'1. Build our timings');await page.locator('.day-journey [data-action="test"]').click();assert.equal(await page.locator('.day-journey [aria-current="step"]').innerText(),'2. Check our timings');await page.locator('.day-journey [data-action="final"]').click();assert.equal(await page.locator('.day-journey [aria-current="step"]').innerText(),'3. Review & export');await page.locator('.day-journey a[href="/hub"]').click();await page.locator('#hub-main h1').waitFor();assert.equal(await page.locator('.day-journey [aria-current="step"]').innerText(),'4. Share our day');
  assert.deepEqual(errors,[]);console.log('PASS: overdue payment action, guide hide/reopen, settings access date, guest search/combined filters/no-match/clear, unchanged saved guests, mobile width and four-step journey.');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
