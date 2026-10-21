/* Isolated admin UI: all API calls mocked, no live data or network. */
const {chromium}=require(process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES+'/playwright');
const fs=require('fs'),path=require('path'),assert=require('assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.WBM_TEST_CHROME,args:['--no-sandbox']});
 try{
 const page=await browser.newPage();await page.route('**/*',r=>r.abort());const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.setContent('<style>body{margin:0}</style><div id="ivory-planner"><button class="mobile-menu"></button><div id="sa-feedback"></div><div class="shell"><nav id="sa-nav"></nav><main id="sa-main"></main></div></div>');
 await page.addStyleTag({content:fs.readFileSync(path.join(__dirname,'../app/static/style.css'),'utf8')});
 await page.evaluate(()=>{
 window.posts=0;window.job={};window.items=[{name:'planner-20261021-120000-123456.tar.gz',bytes:2048,created:1792584000}];
 const system={settings:{backup_time:'03:00',backup_retention_days:14},couples:[],status:{worker_heartbeat:Date.now()/1000,backups:[],paid_sales_pence:0,disk_free:1024**3,disk_total:2*1024**3}};
 window.ivory={escape:v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),api:async(url,options)=>{if(url==='/api/admin')return system;if(url==='/api/admin/backups'){if(options?.method==='POST'){window.posts++;window.job={status:'queued',message:'Queued for backup worker.'};return {job:window.job}}return {job:window.job,archives:window.items,worker_running:true}}throw Error('Unexpected mock request '+url)}};
 });
 await page.addScriptTag({content:fs.readFileSync(path.join(__dirname,'../app/static/admin.js'),'utf8')});
 await page.locator('[data-page="backups"]').click();await page.locator('#backup-archives a').waitFor();
 assert.equal(await page.evaluate(()=>window.posts),0);
 assert.equal(await page.locator('#backup-archives a').getAttribute('href'),'/api/admin/backups/planner-20261021-120000-123456.tar.gz');
 for(const width of [320,390,768,1280])for(const dark of [false,true]){
  await page.setViewportSize({width,height:900});await page.evaluate(d=>document.querySelector('#ivory-planner').classList.toggle('dark',d),dark);
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),`overflow ${width}/${dark}`);
  const bounds=await page.locator('[data-action="backup-now"]').boundingBox();assert(bounds.height>=44);
 }
 await page.locator('[data-action="backup-now"]').click();await page.waitForFunction(()=>window.posts===1);assert(await page.locator('[data-action="backup-now"]').isDisabled());
 await page.evaluate(()=>window.job={status:'completed',message:'Backup completed.'});await page.locator('[data-action="backup-refresh"]').click();await page.waitForFunction(()=>!document.querySelector('[data-action="backup-now"]').disabled);
 await page.locator('[data-action="backup-help"]').first().click();assert(await page.locator('#a-extra').innerText().then(t=>t.includes('weddingplannercouples.env')));
 await page.setViewportSize({width:320,height:900});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
 assert.deepEqual(errors,[]);console.log('PASS: no automatic backup creation, download links, queued/completed states, recovery help and 320/390/768/1280px light/dark layouts.');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
