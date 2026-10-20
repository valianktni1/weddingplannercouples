// The real couple UI reads a sample state. No request from this page can write.
const previewState=JSON.parse(document.getElementById('preview-state').textContent);
window.ivoryPreview=true;
ivory.api=async(path,options={})=>{
  if(path==='/api/state'&&(!options.method||options.method==='GET'))return structuredClone(previewState);
  throw Error('This preview is read only. No changes or emails were sent.');
};
