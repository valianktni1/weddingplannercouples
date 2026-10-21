/* Mocked UI only. Generate /tmp/wbm-timing-template.json from the booking schema. */
const {chromium}=require(process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES+'/playwright');
const fs=require('fs'),assert=require('assert/strict'),path=require('path');
(async()=>{
 const b=await chromium.launch({headless:true,executablePath:process.env.WBM_TEST_CHROME||'/tmp/wbm-browser/chrome-linux/headless_shell',args:['--no-sandbox']});
 try{
 const page=await b.newPage({viewport:{width:390,height:844}});const errors=[];page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.dismiss());
 await page.route('**/*',r=>r.abort());
 const schema=JSON.parse(fs.readFileSync('/tmp/wbm-timing-template.json'));
 const status={linked:true,revision:2,hub_revision:0,template:schema,answers:{_template_revision:schema.revision,ceremony_time:'13:00',ceremony_duration:30,ceremony_venue:'Example Hall',reception_same:true,first_dance_time:'19:30',meal_time:'16:00',start_choice:'normal',speeches_position:'After the meal',later_event:false,group_count:'1-5',travel_minutes:0},groups:['Family photo'],timeline:[{start:780,title:'Ceremony',location:'Example Hall',instructions:''}],latest:null};
 const css=fs.readFileSync(path.resolve(__dirname,'../app/static/style.css'),'utf8'),source=fs.readFileSync(path.resolve(__dirname,'../app/static/wbm-timings.js'),'utf8');
 async function boot(linked=true){await page.setContent('<style>'+css+'</style><div id="ivory-planner"><div class="topbar"><div class="actions"></div></div></div>');await page.evaluate(s=>{window.testStatus=s;window.writes=[];window.unsaved=false;window.ivory={api:async(path,opts)=>{if(opts?.method==='POST'){writes.push({path,body:opts.body});return {id:'example',status:'queued'}}return testStatus}};window.ivoryPlannerReadyForTimings=async()=>{if(unsaved)throw Error('Save the planner first')};},{...status,linked});await page.addScriptTag({content:source});}
 await boot(false);assert.equal(await page.locator('.topbar button').count(),0);
 await boot();await page.locator('.topbar button').waitFor();assert.equal(await page.evaluate(()=>writes.length),0);
 await page.evaluate(()=>unsaved=true);await page.locator('.topbar button').click();assert.equal(await page.locator('dialog[open]').count(),0);assert.equal(await page.evaluate(()=>writes.length),0);
 await page.evaluate(()=>unsaved=false);await page.locator('.topbar button').click();await page.locator('dialog[open]').waitFor();
 assert.equal(await page.locator('#wbm-ceremony_time').inputValue(),'13:00');
 await page.locator('#wbm-prep_photos').selectOption('false');await page.locator('#wbm-day_contact').fill('Example contact');await page.locator('#wbm-day_mobile').fill('07700900111');
 for(const dark of [false,true])for(const width of [320,390,768,1280]){
  await page.setViewportSize({width,height:900});await page.locator('#ivory-planner').evaluate((el,dark)=>el.classList.toggle('dark',dark),dark);
  assert.equal(await page.locator('dialog').evaluate(el=>el.scrollWidth>el.clientWidth),false,'Dialog overflow '+width);
  assert((await page.locator('dialog').boundingBox()).width<=width);
 }
 await page.setViewportSize({width:390,height:844});await page.screenshot({path:'/tmp/wbm-planner-timings-mobile.png'});
 await page.locator('dialog button[type=submit]').click();assert.equal(await page.evaluate(()=>writes.length),0);
 assert.equal(await page.locator('[data-wbm-send]').isDisabled(),true);
 assert((await page.locator('dialog').innerText()).includes('Family photo'));
 await page.locator('[data-wbm-confirm]').check();await page.locator('[data-wbm-send]').click();await page.waitForFunction(()=>writes.length===1);
 const sent=await page.evaluate(()=>writes[0]);assert.equal(sent.path,'/api/wbm-timings');assert.equal(sent.body.confirmed,true);assert.equal(sent.body.answers.prep_photos,false);assert.equal(sent.body.answers.ceremony_time,'13:00');assert.equal(sent.body.revision,2);
 assert.deepEqual(errors,[]);console.log('PASS: linked-only button, unsaved guard, prefill, conditional fields, 320/390/768/1280 widths, light/dark, preview and explicit confirmation before one mocked submission.');
 }finally{await b.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
