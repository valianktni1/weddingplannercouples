/* Deterministic suggestions from the couple's own entries; no plan changes. */
(()=>{
 const daysBetween=(a,b)=>Math.round((Date.parse(a+'T12:00:00Z')-Date.parse(b+'T12:00:00Z'))/86400000);
 function nextStep(state,today){
  const payments=state.payments.filter(p=>p.amount>p.paid&&p.due).sort((a,b)=>a.due.localeCompare(b.due));
  const tasks=state.tasks.filter(t=>!t.done).slice().sort((a,b)=>(a.due||'9999').localeCompare(b.due||'9999'));
  const payment=payments.find(p=>p.due<today);
  if(payment)return {kind:'payment',item:payment,urgency:'overdue'};
  const overdueTask=tasks.find(t=>t.due&&t.due<today);
  if(overdueTask)return {kind:'task',item:overdueTask,urgency:'overdue'};
  const soonPayment=payments.find(p=>daysBetween(p.due,today)<=7);
  if(soonPayment)return {kind:'payment',item:soonPayment,urgency:'soon'};
  const soonTask=tasks.find(t=>t.due&&daysBetween(t.due,today)<=7);
  if(soonTask)return {kind:'task',item:soonTask,urgency:'soon'};
  if(!state.day.venue)return {kind:'venue'};
  const untilWedding=state.date?daysBetween(state.date,today):null;
  if(!state.day.mealConfirmed&&untilWedding!==null&&untilWedding>=0&&untilWedding<=60)return {kind:'timings'};
  if(tasks.length)return {kind:'task',item:tasks[0],urgency:'normal'};
  if(!state.suppliers.length)return {kind:'supplier'};
  if(!state.guests.length)return {kind:'guests'};
  return {kind:'review'};
 }
 function firstSteps(state){return [
  {key:'supplier',title:'Add a venue or supplier',page:'suppliers',done:state.suppliers.some(s=>s.name&&!/— details to add$/.test(s.name))},
  {key:'payment',title:'Record a payment, if you’ve made one',page:'suppliers',done:state.payments.some(p=>p.paid>0)},
  {key:'guests',title:'Add your first guests',page:'guests',done:state.guests.length>0},
  {key:'partner',title:'Invite your partner, if you’d like to',page:'account',done:['Pending','Queued','Sent','Accepted'].includes(state.invite.status)||!!state.invite.email&&!/cancel|not invited/i.test(state.invite.status)}
 ]}
 function filterGuests(guests,query='',rsvp='',attendance=''){
  const text=query.trim().toLocaleLowerCase('en-GB');
  return guests.filter(g=>(!text||[g.name,g.household].some(v=>(v||'').toLocaleLowerCase('en-GB').includes(text)))&&(!rsvp||g.rsvp===rsvp)&&(!attendance||g.attendance===attendance));
 }
 const api={nextStep,firstSteps,filterGuests};globalThis.ivoryJourney=api;
 if(typeof module!=='undefined'&&module.exports)module.exports=api;
})();
