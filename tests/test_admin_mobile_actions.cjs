/* Render production admin JS/CSS with fake account metadata; no messages or mutations. */
const {chromium}=require(process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES+'/playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const args=process.env.PLANNER_TEST_LAMBDA?(await import(process.env.PLANNER_TEST_LAMBDA)).default.args:['--no-sandbox'];
 const browser=await chromium.launch({headless:true,executablePath:process.env.WBM_TEST_CHROME||undefined,args});
 try{
  const page=await browser.newPage({viewport:{width:390,height:844}}),errors=[];page.on('pageerror',e=>errors.push(e.message));await page.route('**/*',r=>r.abort());
  await page.setContent('<body class="admin-page"><div id="ivory-planner" class="admin-app"><header class="top"><span class="brand">Ivory Digital</span><div class="actions"><button>Dark mode</button><button>Sign out</button></div></header><button class="mobile-menu" data-action="menu" aria-controls="sa-nav"></button><div id="sa-feedback"></div><div class="shell"><nav id="sa-nav"></nav><main id="sa-main"></main></div></div></body>');
  for(const name of ['style.css','admin.css'])await page.addStyleTag({content:fs.readFileSync(path.join(__dirname,'../app/static',name),'utf8')});
  await page.evaluate(()=>{
   const system={settings:{price_pence:2500},couples:[{id:'example',names:'Example couple with a longer name',email:'example-couple@example.com',wedding:'2028-10-09',access:'Complimentary',until:'2028-11-08',invitation_pending:true,journey:{stage:'Invited',last_active:null,expires_soon:false}}],status:{backups:[],paid_sales_pence:0,disk_free:1024**3},support:[],history:[],cancelled_invitations:[],manual_payments:[]};window.mutations=0;
   window.ivory={escape:v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),api:async(url,options)=>{if(options?.method&&options.method!=='GET')window.mutations++;if(url==='/api/admin')return system;if(url==='/api/admin/backups')return {archives:[],job:{},worker_running:true};throw Error('Unexpected test request '+url)}};
  });
  await page.addScriptTag({content:fs.readFileSync(path.join(__dirname,'../app/static/admin.js'),'utf8')});await page.locator('#sa-main h1').waitFor();
  async function checkActions(){
   const rows=await page.locator('#sa-main .row>.actions').evaluateAll(groups=>groups.map(group=>{
    const g=group.getBoundingClientRect();
    const buttons=[...group.querySelectorAll('button,a.button')].map(b=>{
     const r=b.getBoundingClientRect(),style=getComputedStyle(b);
     return {width:r.width,height:r.height,wordBreak:style.wordBreak,overflowWrap:style.overflowWrap,inside:r.left>=g.left-1&&r.right<=g.right+1};
    });
    return {width:g.width,buttons};
   }));
   assert(rows.length);for(const row of rows)for(const b of row.buttons){assert(b.width>0&&b.height>=48);assert(b.inside);assert.equal(b.wordBreak,'normal');assert.equal(b.overflowWrap,'normal');if(await page.evaluate(()=>innerWidth<=760))assert(b.width>=row.width-1,'phone controls must fill their own row');}
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'page overflows');
  }
  async function go(section){const target=page.locator('#sa-nav [data-page="'+section+'"]');if(!await target.isVisible())await page.locator('.mobile-menu').click();await target.click()}
  for(const section of ['journey','couples','backups','support']){
   await go(section);
   for(const width of [320,360,390,480,600,760,768,1280])for(const dark of [false,true]){
    await page.setViewportSize({width,height:844});await page.locator('#ivory-planner').evaluate((el,d)=>el.classList.toggle('dark',d),dark);
    if(['journey','couples'].includes(section))await checkActions();
    else assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),section+' overflow');
   }
  }
  await page.setViewportSize({width:390,height:844});await go('journey');
  await page.locator('#ivory-planner').evaluate(el=>el.classList.remove('dark'));
  await page.locator('#journey-couples').scrollIntoViewIfNeeded();await page.screenshot({path:(process.env.PLANNER_DESIGN_QA_DIR||'/tmp')+'/planner-admin-buttons-fixed.png'});
  await page.locator('[data-action="access"]').click();await page.locator('#a-access').waitFor();assert.equal(await page.locator('#a-until').inputValue(),'2028-11-08');
  await page.locator('[data-action="request-payment"]').click();await page.locator('#a-requestMethod').waitFor();
  await page.locator('[data-action="cancel-invitation"]').click();await page.locator('#a-cancelConfirmed').waitFor();await page.locator('[data-action="dismiss-invitation-action"]').click();
  await page.addStyleTag({content:'#ivory-planner.admin-app{font-size:24px!important}'});await page.setViewportSize({width:320,height:844});await checkActions();
  assert.equal(await page.evaluate(()=>window.mutations),0);assert.deepEqual(errors,[]);
  console.log('PASS: admin journey/account action widths, natural word wrapping, phone full-width buttons, light/dark, widths 320–1280, 24px text, backup/support layouts and unchanged access/payment/cancel controls; zero mutations.');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
