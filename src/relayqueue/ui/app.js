"use strict";
const $ = id => document.getElementById(id);
const state = {token:"", epoch:0, jobs:[], cursor:null, older:false, selected:null, selection:0, loading:false, loadPromise:null, sample:null, signature:"", controllers:new Set(), sampleVersion:0, sampleController:null};
const labels = {succeeded:"Succeeded", running:"Running", queued:"Queued", failed_retrying:"Retrying", dead:"Failed", cancelled:"Cancelled", scheduled:"Scheduled"};
function message(text, kind="info") {$("message").textContent=text; $("message").className=`notice ${kind}`;}
function navigate() {
  const view = ["jobs","upload","guide"].includes(location.hash.slice(1)) ? location.hash.slice(1) : "jobs";
  document.querySelectorAll(".view").forEach(el=>{el.hidden=el.id!==view;});
  document.querySelectorAll("nav a").forEach(el=>{if(el.dataset.view===view) el.setAttribute("aria-current","page"); else el.removeAttribute("aria-current");});
  $("breadcrumb").textContent=`Workspace / ${{jobs:"Jobs",upload:"Create report",guide:"API guide"}[view]}`;
  document.title=`RelayQueue — ${{jobs:"Jobs",upload:"Create report",guide:"API guide"}[view]}`;
}
window.addEventListener("hashchange",navigate); navigate();
const localDemo=["localhost","127.0.0.1"].includes(location.hostname)&&location.port==="8000";
$("demo-connect").hidden=!localDemo; $("full-docs").hidden=!localDemo;
async function api(path, options={}) {
  const controller=new AbortController(); state.controllers.add(controller);
  const timer=setTimeout(()=>controller.abort(),15000);
  try {
    const response=await fetch(path,{...options,signal:controller.signal,headers:{"X-API-Key":state.token,"Content-Type":"application/json",...options.headers}});
    if(!response.ok) {
      const data=await response.json().catch(()=>({}));
      const text=response.status===401 ? "Access key not accepted. Check your key and reconnect." : response.status===429 ? "Too many requests. Wait a moment and try again." : data.message||`Request failed (${response.status}). Try again.`;
      throw new Error(text);
    }
    return await response.json();
  } catch(error) {
    if(error.name==="AbortError") throw new Error("Request timed out or was cancelled. Try again.");
    if(error instanceof TypeError) throw new Error("Cannot reach RelayQueue. Check that the local services are running, then retry.");
    throw error;
  } finally {clearTimeout(timer);state.controllers.delete(controller);}
}
function connectionUI(connected, queue=null) {
  $("connect").hidden=connected; $("demo-connect").hidden=connected||!localDemo; $("disconnect").hidden=!connected;
  $("connection").textContent=connected?(queue?`Workspace: ${queue}`:"Local workspace"):"Not connected";
  $("connection").classList.toggle("connected",connected);
  $("connection-title").textContent=connected?"Workspace connected":"Connect your workspace";
  $("connection-help").textContent=connected?"Your key stays in memory and is cleared on reload.":"Use an access key to view jobs and create reports.";
  for(const id of ["refresh","search","filter","submit-button"]) $(id).disabled=!connected;
  $("queue").value=queue||"default"; $("queue").disabled=!!queue;
  $("upload-help").textContent=connected?"Your report will run in the background. You can follow it immediately.":"Connect your workspace before creating a report.";
}
function invalidateSample() {
  state.sampleVersion++; state.sampleController?.abort(); state.sampleController=null;
  state.sample=null; $("use-sample").disabled=false;
}
function reset() {
  invalidateSample(); $("file").value=""; $("file-name").textContent="Choose your sales CSV"; $("file-info").textContent="UTF-8 CSV � up to 48 KB";
  state.epoch++; state.controllers.forEach(c=>c.abort()); state.controllers.clear(); state.token=""; state.jobs=[];state.cursor=null;state.older=false;state.selected=null;state.selection++;state.loading=false;state.loadPromise=null;state.signature="";
  if($("detail").open) $("detail").close();
  $("key").value=""; $("search").value="";$("filter").value="";$("more").hidden=true;$("updated").textContent="Waiting for connection";$("poll-status").textContent="Updates appear here while connected.";
  $("result").textContent="";$("history").replaceChildren();$("result-summary").replaceChildren();
  connectionUI(false);renderJobs();
}
function renderJobs() {
  const query=$("search").value.trim().toLowerCase(), filter=$("filter").value;
  const jobs=state.jobs.filter(job=>(!filter||job.status===filter)&&(!query||`${job.task} ${job.id}`.toLowerCase().includes(query)));
  const signature=JSON.stringify(jobs)+query+filter+!!state.token;
  $("job-count").textContent=`${state.jobs.length} loaded`;
  if(signature===state.signature)return; state.signature=signature;
  const fragment=document.createDocumentFragment();
  for(const job of jobs) {
    const row=document.createElement("tr"), name=document.createElement("td"), button=document.createElement("button"), id=document.createElement("small");
    button.className="job-link";button.textContent=job.task==="sales_report"?"Sales report":job.task;button.onclick=()=>openJob(job.id);
    button.setAttribute("aria-label",`View ${job.task} ${job.id.slice(0,8)}`);
    id.textContent=job.id.slice(0,8);name.append(button,id);row.append(name);
    const status=document.createElement("td"),badge=document.createElement("span");badge.className=`badge ${job.status}`;badge.textContent=labels[job.status]||job.status;status.append(badge);row.append(status);
    for(const value of [job.queue,`${job.attempts} / ${job.max_attempts}`,new Date(job.created_at).toLocaleString(undefined,{month:"short",day:"numeric",hour:"2-digit",minute:"2-digit"})]){const cell=document.createElement("td");cell.textContent=value;row.append(cell);}
    const cell=document.createElement("td"),view=document.createElement("button");view.className="view-button";view.textContent="›";view.setAttribute("aria-label",`Open job ${job.id.slice(0,8)}`);view.onclick=()=>openJob(job.id);cell.append(view);row.append(cell);fragment.append(row);
  }
  // Polling never replaces a focused control; explicit filter/refresh actions render immediately.
  $("rows").replaceChildren(fragment);$("empty").hidden=jobs.length>0;
  $("empty-title").textContent=!state.token?"Your work starts here":state.jobs.length?"No matching jobs":"Ready for your first job";
  $("empty-description").textContent=!state.token?"Connect your workspace to see jobs and their progress.":state.jobs.length?"Try another search or status. Search covers the jobs loaded on this page.":"Create a report using your own CSV or try the sample data.";
}
async function load(options={}) {
  const epoch=state.epoch;
  if(!state.token)return false;
  if(state.loadPromise){
    if(options.background)return false;
    // An explicit action waits, then makes its own request (including its cursor).
    try{await state.loadPromise;}catch{/* The explicit request retries a failed poll. */}
    if(epoch!==state.epoch||!state.token)return false;
    return load(options);
  }
  const pending=performLoad(options); state.loadPromise=pending;
  try{return await pending;}
  finally{if(state.loadPromise===pending)state.loadPromise=null;}
}
async function performLoad({append=false,background=false}={}) {
  if(!state.token)return false;
  if(background&&(state.older||$("rows").contains(document.activeElement)))return false;
  const epoch=state.epoch;state.loading=true;
  if(!background){$("refresh").disabled=true;$("more").disabled=true;$("refresh").textContent="Refreshing…";}
  try {
    const page=await api(`/v1/jobs?limit=12${append&&state.cursor?`&cursor=${encodeURIComponent(state.cursor)}`:""}`);
    if(epoch!==state.epoch)return false;
    state.jobs=append?[...new Map([...state.jobs,...page.items].map(job=>[job.id,job])).values()]:page.items;
    state.cursor=page.next_cursor;state.older=append;$("more").hidden=!state.cursor;renderJobs();
    $("updated").textContent=`Updated ${new Date().toLocaleTimeString(undefined,{hour:"2-digit",minute:"2-digit"})}`;
    $("poll-status").textContent=state.older?"Older jobs loaded. Refresh to return to the latest jobs.":"Live updates every 5 seconds.";
    return true;
  } finally {if(epoch===state.epoch){state.loading=false;$("refresh").disabled=false;$("more").disabled=false;$("refresh").textContent="Refresh";}}
}
async function connect(candidate) {
  reset();state.token=candidate;const epoch=state.epoch;
  $("connect-button").disabled=true;$("demo-connect").disabled=true;$("connect-button").textContent="Connecting…";
  message("Connecting to your workspace…");
  try {const session=await api("/v1/session");if(epoch!==state.epoch)return;connectionUI(true,session.queue);await load();if(epoch===state.epoch)message("Connected. Open a job to see its progress, or create a sales report.","success");}
  catch(error){if(epoch===state.epoch){reset();message(error.message,"error");}}
  finally {$("connect-button").disabled=false;$("demo-connect").disabled=false;$("connect-button").textContent="Connect";}
}
$("connect").onsubmit=event=>{event.preventDefault();connect($("key").value.trim());};
$("demo-connect").onclick=()=>connect("dev-key-1");
$("disconnect").onclick=()=>{reset();message("Disconnected. Your access key and job details have been cleared.");};
$("refresh").onclick=async()=>{const epoch=state.epoch;try{if(await load())message("Job list refreshed.","success");}catch(e){if(epoch===state.epoch)message(e.message,"error");}};
$("more").onclick=()=>load({append:true}).catch(e=>message(e.message,"error"));
$("search").oninput=renderJobs;$("filter").onchange=renderJobs;
function renderDetails(job) {
  $("job-title").textContent=job.task==="sales_report"?"Sales report":job.task;
  $("job-id").textContent=job.id;$("job-summary").textContent=`${labels[job.status]||job.status} · ${job.attempts} of ${job.max_attempts} attempts${job.cancel_requested?" · Cancellation requested":""}${job.last_error?` · ${job.last_error}`:""}`;
  $("history").replaceChildren();
  for(const attempt of job.history){const item=document.createElement("li");item.textContent=`Attempt ${attempt.attempt_no} — ${attempt.outcome||"Running"}`;const detail=document.createElement("small");detail.textContent=attempt.error||`${attempt.duration_ms??"…"} ms`;item.append(detail);$("history").append(item);}
  if(!job.history.length){const item=document.createElement("li");item.textContent="Waiting for a worker to start.";$("history").append(item);}
  $("result").textContent=job.result?JSON.stringify(job.result,null,2):"The result will appear when this job completes.";
  $("result-summary").replaceChildren();$("result-summary").hidden=!(job.result&&"revenue" in job.result);
  if(!$("result-summary").hidden)for(const [label,value] of [["Revenue",job.result.revenue],["Units",job.result.units],["Rows processed",job.result.rows]]){const group=document.createElement("div"),number=document.createElement("strong"),caption=document.createElement("span");number.textContent=value;caption.textContent=label;group.append(number,caption);$("result-summary").append(group);}
  $("retry").hidden=job.status!=="dead";$("cancel").hidden=["succeeded","dead","cancelled"].includes(job.status)||job.cancel_requested;
}
async function updateJob() {
  if(!state.selected)return;
  const id=state.selected,selection=state.selection,epoch=state.epoch;
  const job=await api(`/v1/jobs/${id}`);
  if(epoch===state.epoch&&selection===state.selection&&$("detail").open)renderDetails(job);
}
async function openJob(id) {
  state.selected=id;state.selection++;$("job-title").textContent="Loading job…";$("job-id").textContent=id;$("job-summary").textContent="Fetching status and attempt history…";
  $("history").replaceChildren();$("result-summary").hidden=true;$("result").textContent="Loading…";$("detail-message").textContent="";$("raw-result").open=false;$("retry").hidden=true;$("cancel").hidden=true;
  if(!$("detail").open)$("detail").showModal();
  try{await updateJob();}catch(e){$("detail-message").textContent=e.message;}
}
for(const id of ["close-detail","done"])$(id).onclick=()=>$("detail").close();
$("detail").addEventListener("close",()=>{state.selected=null;state.selection++;});
$("detail").addEventListener("click",event=>{if(event.target===$("detail")){const r=$("detail").getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)$("detail").close();}});
for(const action of ["retry","cancel"])$(action).onclick=async()=>{
  const id=state.selected,epoch=state.epoch,button=$(action),text=button.textContent;if(!id)return;
  button.disabled=true;button.textContent=action==="retry"?"Retrying…":"Cancelling…";
  try{await api(`/v1/jobs/${id}/${action}`,{method:"POST"});if(epoch!==state.epoch)return;await updateJob();await load({background:true});if(id===state.selected)$("detail-message").textContent=action==="retry"?"Retry requested. Status will update automatically.":"Cancellation requested. Completed external effects cannot be undone.";}
  catch(e){if(epoch===state.epoch&&id===state.selected)$("detail-message").textContent=e.message;}finally{button.disabled=false;button.textContent=text;}
};
$("file").onchange=()=>{invalidateSample();const file=$("file").files[0];$("file-name").textContent=file?file.name:"Choose your sales CSV";$("file-info").textContent=file?`${file.size.toLocaleString()} bytes selected`:"UTF-8 CSV · up to 48 KB";};
$("use-sample").onclick=async()=>{
  invalidateSample();
  const version=state.sampleVersion, controller=new AbortController();
  state.sampleController=controller; $("use-sample").disabled=true;
  const timer=setTimeout(()=>controller.abort(),15000);
  try {
    const response=await fetch("./sample.csv",{signal:controller.signal});
    if(!response.ok)throw new Error("Sample could not be loaded. Try downloading it instead.");
    const content=await response.text();
    if(version!==state.sampleVersion)return;
    state.sample=content; $("file").value="";
    $("file-name").textContent="Sample sales.csv selected";
    $("file-info").textContent="3 rows � expected revenue 50.10";
    message("Sample data selected. Create the report when you�re ready.","success");
  } catch(e) {
    if(version===state.sampleVersion)message(e.name==="AbortError"?"Sample request timed out. Try again.":e.message,"error");
  } finally {
    clearTimeout(timer);
    if(version===state.sampleVersion){state.sampleController=null;$("use-sample").disabled=false;}
  }
};
$("submit").onsubmit=async event=>{
  event.preventDefault();if(!state.token){message("Connect your workspace first.","error");return;}
  const epoch=state.epoch,button=$("submit-button"),queue=$("queue").value;button.disabled=true;button.textContent="Creating report…";
  try{
    const file=$("file").files[0];if(!state.sample&&!file)throw new Error("Choose a CSV file or click Use sample data first.");
    if(file&&file.size>48000)throw new Error("This file is too large. Choose a CSV under 48,000 bytes.");
    const content=state.sample??new TextDecoder("utf-8",{fatal:true}).decode(await file.arrayBuffer());
    const digest=new Uint8Array(await crypto.subtle.digest("SHA-256",new TextEncoder().encode(content)));
    if(epoch!==state.epoch)return;
    const hash=[...digest].map(x=>x.toString(16).padStart(2,"0")).join("");
    const job=await api("/v1/jobs",{method:"POST",body:JSON.stringify({task:"sales_report",queue,payload:{content},idempotency_key:`sales-report:v1:${hash}`,max_attempts:2})});
    if(epoch!==state.epoch)return;
    message("Report accepted. The job details show its current progress and result.","success");await openJob(job.id);await load();
  }catch(e){if(epoch===state.epoch)message(e.message,"error");}finally{button.disabled=!state.token;button.textContent="Create report";}
};
async function poll(){
  const epoch=state.epoch;
  if(state.token&&!document.hidden)try{if(state.selected)await updateJob();await load({background:true});}catch(e){if(epoch===state.epoch){$("poll-status").textContent="Live updates interrupted. Use Refresh to retry.";message(e.message,"error");}}
  setTimeout(poll,5000);
}
renderJobs();setTimeout(poll,5000);
if(location.protocol==="file:"){
  document.querySelectorAll("input,button,select").forEach(el=>{el.disabled=true;});
  message("This is a file preview. Open the running dashboard to use RelayQueue: ");
  const link=document.createElement("a");link.href="http://localhost:8000/";link.textContent="Open local dashboard";$("message").append(link);
}
