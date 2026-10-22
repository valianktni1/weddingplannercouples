/* Navigation has its own layout row; it never overlays scrolling form content. */
(()=>{
 const root=document.getElementById('ivory-planner');if(!root?.classList.contains('couple-app'))return;
 const scroll=root.querySelector('.page-content'),menu=root.querySelector('#couple-menu'),dock=root.querySelector('#couple-dock');
 let setup=false,lastPage=null,menuOrigin=null;
 const mobile=()=>matchMedia('(max-width:760px)').matches;
 const editing=()=>!!document.activeElement?.matches('textarea,select,input:not([type="checkbox"]):not([type="radio"]):not([type="range"]):not([type="button"]):not([type="submit"]),[contenteditable="true"]');
 function themeLabel(){const button=root.querySelector('[data-theme-toggle]');if(button){button.title=button.textContent;button.setAttribute('aria-label',button.textContent)}}
 function fit(){
  const height=window.visualViewport?.height||window.innerHeight;
  root.style.setProperty('--couple-viewport-height',height+'px');
  dock.hidden=setup||(mobile()&&editing());
 }
 function setMenu(open,returnFocus=false){
  menu.hidden=!open;root.classList.toggle('couple-more-open',open);
  root.querySelectorAll('[data-couple-menu]').forEach(b=>b.setAttribute('aria-expanded',String(open)));
  if(open){scroll.scrollTo({top:0,behavior:'instant'});menu.querySelector('a')?.focus({preventScroll:true})}
  else if(returnFocus)menuOrigin?.focus({preventScroll:true});
 }
 root.addEventListener('click',e=>{
  if(e.target.closest('[data-theme-toggle]'))requestAnimationFrame(themeLabel);
  const toggle=e.target.closest('[data-couple-menu]');
  if(toggle){menuOrigin=toggle;setMenu(menu.hidden,true);return}
  if(e.target.closest('[data-couple-close]')){setMenu(false,true);return}
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
 window.addEventListener('resize',fit);window.visualViewport?.addEventListener('resize',fit);
 themeLabel();fit();
})();
