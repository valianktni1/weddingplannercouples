/* Home-screen invitation. No service worker, private-page cache or saved credentials. */
(()=>{
 const root=document.getElementById('ivory-planner'),dialog=document.getElementById('planner-install');
 if(!root||!dialog||window.ivoryPreview)return;
 const install=dialog.querySelector('[data-install-now]'),later=dialog.querySelector('[data-install-later]');
 const help=dialog.querySelector('#planner-install-help'),steps=dialog.querySelector('#planner-install-steps'),status=dialog.querySelector('#planner-install-status');
 const key='ivory:home-screen:v1:'+dialog.dataset.installKey;
 const ua=navigator.userAgent,ios=/iPad|iPhone|iPod/.test(ua)||(navigator.platform==='MacIntel'&&navigator.maxTouchPoints>1);
 const samsung=/SamsungBrowser/i.test(ua)&&!ios;
 const phone=ios||/Android/i.test(ua)||navigator.userAgentData?.mobile;
 const standalone=()=>navigator.standalone===true||matchMedia('(display-mode: standalone)').matches||matchMedia('(display-mode: fullscreen)').matches;
 const chrome=dialog.querySelector('[data-install-chrome]');
 const plannerURL=location.origin+'/app';
 chrome.href='intent://'+location.host+'/app#Intent;scheme='+location.protocol.slice(0,-1)+';package=com.android.chrome;S.browser_fallback_url='+encodeURIComponent(plannerURL)+';end';
 let deferred=null,ready=false,shown=false,origin=null;
 const seen=()=>{try{return localStorage.getItem(key)==='seen'}catch{return false}};
 const remember=()=>{try{localStorage.setItem(key,'seen')}catch{/* Private browsing still works. */}};
 const editing=()=>document.activeElement?.matches('input,select,textarea,[contenteditable="true"]');
 function label(){install.textContent=deferred?'Install Ivory Planner':'Add to home screen'}
 function instructions(){
  const embedded=/FBAN|FBAV|Instagram|\bwv\b|; wv\)/i.test(ua);
  let lines;
  if(embedded)lines=['Open this planner in '+(ios?'Safari':'Chrome')+' using this browser’s menu, or copy the planner address into that browser.','Sign in if asked, then open Menu → Add to home screen.'];
  else if(ios)lines=['Open this planner in Safari if you’re using another browser.','Tap Share (the square with the upward arrow). You may find Share inside the browser menu.','Choose Add to Home Screen. If shown, turn on Open as Web App, then tap Add.'];
  else if(samsung)lines=['Tap Open in Chrome below. If it does not open, open Chrome yourself and visit '+plannerURL+'.','Sign in if asked, then choose Menu → Add to home screen in your planner.','Choose Install when Chrome offers it. You can keep using the planner in Samsung Internet too.'];
  else if(/Android/i.test(ua))lines=['Open your browser’s menu (⋮).','Choose Add to Home screen or Install app.','Confirm Add or Install. If the option is missing, open this planner in Chrome.'];
  else lines=['Open this planner on your phone and choose Menu → Add to home screen.','On this computer, check your browser’s address bar or menu for Install app.'];
  steps.replaceChildren(...lines.map(text=>{const li=document.createElement('li');li.textContent=text;return li}));
  help.hidden=false;install.hidden=true;chrome.hidden=!samsung;later.textContent='Got it';help.focus();
 }
 function open(manual=false){
  if(standalone()||dialog.open||(!manual&&(!ready||!phone||shown||seen()||editing()||document.querySelector('dialog[open]'))))return;
  origin=document.activeElement;help.hidden=true;chrome.hidden=true;install.hidden=false;install.disabled=false;later.textContent='Maybe later';status.textContent='';label();
  dialog.showModal();if(samsung){instructions();later.textContent='Maybe later'}shown=true;remember();
 }
 function close(){dialog.close();if(origin?.isConnected)origin.focus({preventScroll:true})}
 root.addEventListener('ivory:page',e=>{ready=!e.detail.setup;if(ready)open()});
 document.addEventListener('DOMContentLoaded',async()=>{if(!document.getElementById('ip-main')){try{const plan=await ivory.api('/api/state');ready=!!plan.state.ready;if(ready)open()}catch{/* Keep normal planning available if this optional check fails. */}}});
 root.addEventListener('click',e=>{if(e.target.closest('[data-install-open]'))open(true)});
 later.addEventListener('click',close);
 dialog.addEventListener('cancel',remember);
 window.addEventListener('beforeinstallprompt',e=>{e.preventDefault();if(samsung)return;deferred=e;label();});
 window.addEventListener('appinstalled',()=>{deferred=null;remember();if(dialog.open)close()});
 install.addEventListener('click',async()=>{
  if(samsung||!deferred){instructions();return}
  const prompt=deferred;deferred=null;install.disabled=true;
  try{
   await prompt.prompt();const choice=await prompt.userChoice;
   if(choice.outcome==='accepted'){close();return}
   status.textContent='No problem. You can add it later from Menu.';
  }catch{status.textContent='Use your browser’s menu to add the planner instead.';instructions()}
  finally{install.disabled=false;label()}
 });
})();
