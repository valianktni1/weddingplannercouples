const {chromium}=require(process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES+'/playwright');
const assert=require('node:assert/strict');
(async()=>{
 const b=await chromium.launch({headless:true,executablePath:process.env.WBM_TEST_CHROME,args:['--no-sandbox']});
 try{
 const base=process.env.PLANNER_TEST_URL||'http://127.0.0.1:8765';
 const c=await b.newContext({viewport:{width:390,height:844}}),p=await c.newPage();
 await p.goto(base+'/login');await p.locator('[name=email]').fill('test@example.com');await p.locator('[name=password]').fill('test-only-long-password');await p.locator('button.primary').click();await p.locator('.wedding-intro').waitFor();
 if(await p.locator('#planner-install[open]').count())await p.getByRole('button',{name:'Maybe later',exact:true}).click();
 await p.locator('a.brand').click();await p.locator('.wedding-intro').waitFor();assert.equal(new URL(p.url()).pathname,'/app');
 await c.clearCookies({name:'ivory_session'});await p.goto(base+'/');await p.waitForURL('**/login');assert.equal(await p.locator('h1').innerText(),'Welcome back');assert.equal(await p.getByText('Start your trial',{exact:true}).count(),0);
 await p.getByRole('link',{name:'About the planner'}).click();assert.equal(new URL(p.url()).search,'?welcome=1');
 const installed=await b.newContext({viewport:{width:390,height:844}});
 await installed.addInitScript(()=>{const original=window.matchMedia.bind(window);window.matchMedia=query=>query==='(display-mode: standalone)'?{matches:true}:original(query)});
 const launch=await installed.newPage();await launch.goto(base+'/');await launch.waitForURL('**/login');assert.equal(await launch.locator('h1').innerText(),'Welcome back');
 await launch.goto(base+'/?welcome=1');await launch.waitForTimeout(100);assert.equal(new URL(launch.url()).search,'?welcome=1');
 await p.goto(base+'/login');await p.screenshot({path:'/tmp/planner-v162-welcome-back.png'});
 console.log('PASS returning couple root, safe session loss, planner brand link, welcome-back form, explicit public information and legacy standalone root launch.');
 }finally{await b.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
