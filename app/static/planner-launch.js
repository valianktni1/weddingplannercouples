/* Old home-screen shortcuts may reopen the public root rather than manifest /app. */
(()=>{
 if(new URLSearchParams(location.search).get('welcome')==='1')return;
 if(matchMedia('(display-mode: standalone)').matches||navigator.standalone===true)location.replace('/app');
})();
