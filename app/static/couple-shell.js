/* Navigation has its own layout row; it never overlays scrolling form content. */
(()=>{
 const root=document.getElementById('ivory-planner');if(!root?.classList.contains('couple-app'))return;
 const scroll=root.querySelector('.page-content'),menu=root.querySelector('#couple-menu'),dock=root.querySelector('#couple-dock');
 let setup=false,lastPage=null,menuOrigin=null,menuScroll=0,menuWindowScroll=0,pointerActive=false;
 const mobile=()=>matchMedia('(max-width:760px)').matches;
 const editing=()=>!!document.activeElement?.matches('textarea,select,input:not([type="checkbox"]):not([type="radio"]):not([type="range"]):not([type="button"]):not([type="submit"]),[contenteditable="true"]');
 function themeLabel(){const button=root.querySelector('[data-theme-toggle]');if(button){button.title=button.textContent;button.setAttribute('aria-label',button.textContent)}}
 function fit(){
  const height=window.visualViewport?.height||window.innerHeight;
  root.style.setProperty('--couple-viewport-height',height+'px');
  // A blur during a tap must not insert the dock between pointer-down and click.
  // Otherwise a control near the bottom can move away before its tap completes.
  if(!pointerActive||editing()||!dock.hidden)dock.hidden=setup||(mobile()&&editing());
 }
 function setMenu(open,returnFocus=false){
  const wasOpen=!menu.hidden;
  if(open&&!wasOpen){menuScroll=scroll.scrollTop;menuWindowScroll=window.scrollY;}
  menu.hidden=!open;root.classList.toggle('couple-more-open',open);
  root.querySelectorAll('[data-couple-menu]').forEach(b=>b.setAttribute('aria-expanded',String(open)));
  if(open){scroll.scrollTo({top:0,behavior:'instant'});if(!mobile())window.scrollTo({top:0,behavior:'instant'});menu.querySelector('a')?.focus({preventScroll:true})}
  else if(returnFocus){scroll.scrollTo({top:menuScroll,behavior:'instant'});if(!mobile())window.scrollTo({top:menuWindowScroll,behavior:'instant'});menuOrigin?.focus({preventScroll:true})}
 }
 root.addEventListener('click',e=>{
  if(e.target.closest('[data-theme-toggle]'))requestAnimationFrame(themeLabel);
  const toggle=e.target.closest('[data-couple-menu]');
  if(toggle){menuOrigin=toggle;setMenu(menu.hidden,true);return}
  if(e.target.closest('[data-couple-close]')){setMenu(false,true);return}
  const route=e.target.closest('[data-couple-route]');
  // Hub tab navigation uses its own dirty-form guard, without a page reload.
  if(route&&location.pathname==='/hub'&&new URL(route.href).pathname==='/hub'&&typeof window.ivoryHubNavigate==='function'&&!e.ctrlKey&&!e.metaKey&&!e.shiftKey&&!e.altKey&&e.button===0){
   e.preventDefault();if(window.ivoryHubNavigate(new URL(route.href).hash.slice(1)||'overview')){setMenu(false);scroll.scrollTo({top:0,behavior:'instant'});}return;
  }
  if(route&&location.pathname==='/website'&&new URL(route.href).pathname==='/website'&&!e.ctrlKey&&!e.metaKey&&!e.shiftKey&&!e.altKey&&e.button===0){setMenu(false);}
  const link=e.target.closest('[data-couple-page]');if(!link)return;
  // Modified clicks keep normal link/new-tab behaviour, except in admin preview.
  if(!window.ivoryPreview&&(e.ctrlKey||e.metaKey||e.shiftKey||e.altKey||e.button!==0))return;
  if(typeof window.ivoryCoupleNavigate==='function'){
   e.preventDefault();window.ivoryCoupleNavigate(link.dataset.couplePage);
  }
 });
 root.addEventListener('keydown',e=>{if(e.key==='Escape'&&!menu.hidden){setMenu(false,true);e.preventDefault()}});
 root.addEventListener('ivory:page',e=>{
  const {page,setup:inSetup}=e.detail;setup=inSetup;root.querySelectorAll('[data-couple-menu]').forEach(b=>b.hidden=setup);
  root.dataset.plannerPage=page;
  root.querySelectorAll('[data-couple-page]').forEach(a=>{if(a.dataset.couplePage===page)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current')});
  setMenu(false);
  if(lastPage!==page){scroll.scrollTo({top:0,behavior:'instant'});lastPage=page}
  fit();
 });
 root.addEventListener('focusin',fit);root.addEventListener('focusout',()=>requestAnimationFrame(fit));
 root.addEventListener('pointerdown',()=>pointerActive=true,{capture:true});
 for(const event of ['pointerup','pointercancel'])window.addEventListener(event,()=>{pointerActive=false;requestAnimationFrame(fit)});
 window.addEventListener('resize',fit);window.visualViewport?.addEventListener('resize',fit);
 function markTool(){
  const key=location.pathname==='/bespoke'?'bespoke':location.pathname==='/stationery'?'stationery':location.pathname==='/website'?(location.hash==='#guest-invitations'?'invitations':'website'):location.pathname==='/files'?'files':location.pathname==='/upgrade'?'access':location.pathname==='/hub'?(['seating','packs'].includes(location.hash.slice(1))?location.hash.slice(1):'hub'):null;
  root.querySelectorAll('[data-couple-route]').forEach(a=>{if(a.dataset.coupleRoute===key)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current')});
 }
 window.addEventListener('hashchange',markTool);root.addEventListener('ivory:hub-page',markTool);markTool();
 themeLabel();fit();
})();

