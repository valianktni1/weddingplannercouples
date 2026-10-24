(()=>{
 const form=document.getElementById('guest-rsvp-form');if(!form)return;
 let dirty=false,busy=false;const feedback=document.getElementById('guest-feedback'),button=document.getElementById('guest-save');
 function attendance(){form.querySelectorAll('[data-guest]').forEach(group=>{const declined=group.querySelector('[data-attending]').value==='Declined',details=group.querySelector('[data-attending-details]');details.hidden=declined;details.querySelectorAll('input,select').forEach(field=>field.disabled=declined)})}
 attendance();form.addEventListener('input',()=>dirty=true);form.addEventListener('change',()=>{dirty=true;attendance()});
 window.addEventListener('beforeunload',e=>{if(dirty||busy){e.preventDefault();e.returnValue=''}});
 form.addEventListener('submit',async e=>{e.preventDefault();if(busy)return;busy=true;button.disabled=true;feedback.classList.add('notice');feedback.setAttribute('role','status');feedback.textContent='Saving your replies…';
  try{
   const session=await fetch('/api/session',{credentials:'same-origin',cache:'no-store'});if(!session.ok)throw Error('We couldn’t reconnect. Your answers are still here. Please try again.');
   const auth=await session.json();form.elements.csrf.value=auth.csrf;
   const response=await fetch(location.pathname,{method:'POST',credentials:'same-origin',headers:{'X-Requested-With':'guest-rsvp','Accept':'application/json'},body:new URLSearchParams(new FormData(form))});
   let result;try{result=await response.json()}catch{throw Error('Your replies could not be confirmed. Your answers are still here. Please try again.')}
   if(!response.ok)throw Error(result.error||'Your replies could not be saved. Please try again.');
   form.elements.reply_version.value=result.reply_version;dirty=false;feedback.textContent=result.message;
  }catch(error){feedback.textContent=error.message;feedback.setAttribute('role','alert')}
  finally{busy=false;button.disabled=false;feedback.focus();feedback.scrollIntoView({block:'nearest',behavior:'smooth'})}
 });
})();
