const {chromium}=require(process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES+'/playwright');
const assert=require('node:assert/strict');
const base=process.env.PLANNER_TEST_URL||'http://127.0.0.1:8765';
const android='Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Mobile Safari/537.36';
const iphone='Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1';
(async()=>{
 const args=process.env.PLANNER_TEST_LAMBDA?(await import(process.env.PLANNER_TEST_LAMBDA)).default.args:['--no-sandbox'];
 let browser;
 try{
  async function visit(userAgent=android,init=null,email='test@example.com'){
   if(browser)await browser.close();
   browser=await chromium.launch({headless:true,executablePath:process.env.WBM_TEST_CHROME||undefined,args});
   const context=await browser.newContext({viewport:{width:390,height:844},userAgent});
   if(init)await context.addInitScript(init);
   const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
   await page.goto(base+'/login');await page.locator('[name=email]').fill(email);await page.locator('[name=password]').fill('test-only-long-password');await page.locator('button.primary').click();await page.waitForURL('**/app*');await page.waitForFunction(()=>document.querySelector('#ivory-planner').dataset.plannerPage);
   return {page,context,errors};
  }
  let {page,context,errors}=await visit();
  const original=await page.evaluate(()=>ivory.api('/api/state'));
  await page.locator('#planner-install:modal').waitFor();
  assert.match(await page.locator('#planner-install-title').innerText(),/one tap away/);
  await page.locator('[data-install-later]').click();await page.reload();
  await page.waitForFunction(()=>document.querySelector('#ivory-planner').dataset.plannerPage);
  assert.equal(await page.locator('#planner-install').evaluate(d=>d.open),false,'repeated automatic prompt');
  await page.locator('.top [data-couple-menu]').click();await page.locator('[data-install-open]').click();
  await page.locator('[data-install-now]').click();assert.match(await page.locator('#planner-install-steps').innerText(),/Install app/);
  for(const width of [320,390]){
   await page.setViewportSize({width,height:460});await page.locator('#ivory-planner').evaluate(el=>el.classList.add('dark'));
   await page.locator('#planner-install').evaluate(d=>d.style.fontSize='24px');
   await page.locator('[data-install-later]').scrollIntoViewIfNeeded();
   const clear=await page.locator('[data-install-later]').evaluate(b=>{const r=b.getBoundingClientRect();return r.bottom<=innerHeight&&r.top>=0&&document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)===b});assert(clear,'dialog close obstructed');
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'horizontal overflow');
  }
  await page.setViewportSize({width:390,height:844});await page.locator('#ivory-planner').evaluate(el=>el.classList.remove('dark'));
  await page.screenshot({path:(process.env.PLANNER_DESIGN_QA_DIR||'/tmp')+'/planner-home-screen-android.png'});
  await page.locator('[data-install-later]').click();assert.deepEqual((await page.evaluate(()=>ivory.api('/api/state'))).state,original.state);
  await page.locator('[data-install-open]').click();
  await page.evaluate(()=>{
   const e=new Event('beforeinstallprompt',{cancelable:true});
   e.prompt=async()=>{window.installCalls=(window.installCalls||0)+1};e.userChoice=Promise.resolve({outcome:'accepted'});window.dispatchEvent(e);
  });
  await page.locator('[data-install-now]').click();await page.waitForFunction(()=>!document.querySelector('#planner-install').open);assert.equal(await page.evaluate(()=>window.installCalls),1);
  assert.deepEqual(errors,[]);await context.close();
  ({page,context,errors}=await visit(iphone));await page.locator('#planner-install:modal').waitFor();await page.locator('[data-install-now]').click();assert.match(await page.locator('#planner-install-steps').innerText(),/Share[\s\S]*Add to Home Screen/);
  await page.screenshot({path:(process.env.PLANNER_DESIGN_QA_DIR||'/tmp')+'/planner-home-screen-iphone.png'});
  await page.keyboard.press('Escape');assert.equal(await page.locator('#planner-install').evaluate(d=>d.open),false);assert.deepEqual(errors,[]);await context.close();
  ({page,context,errors}=await visit(iphone,()=>Object.defineProperty(navigator,'standalone',{get:()=>true})));
  assert.equal(await page.locator('#planner-install').evaluate(d=>d.open),false,'standalone should not ask to install');assert.deepEqual(errors,[]);await context.close();
  ({page,context,errors}=await visit(android,()=>{Storage.prototype.getItem=()=>{throw Error('storage blocked')};Storage.prototype.setItem=()=>{throw Error('storage blocked')}}));
  await page.locator('#planner-install:modal').waitFor();await page.locator('[data-install-later]').click();assert.deepEqual(errors,[]);await context.close();
  ({page,context,errors}=await visit(android,null,'new@example.com'));
  await page.locator('#planner-install:modal').waitFor();await page.locator('[data-install-later]').click();assert(['welcome','setup'].includes(await page.locator('#ivory-planner').getAttribute('data-planner-page')));assert.deepEqual(errors,[]);await context.close();
  console.log('PASS: first mobile login, dismissal/reopen, Android instructions, iPhone instructions, simulated native install, standalone suppression, blocked storage, new-couple setup and button clearance.');
 }finally{if(browser)await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
