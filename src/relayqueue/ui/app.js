"use strict";
const $ = id => document.getElementById(id);
let token = "", selected = null, cursor = null, generation = 0;
const message = text => { $("message").textContent = text; };
async function api(path, options = {}) {
  const response = await fetch(path, {...options, headers: {"X-API-Key": token, "Content-Type": "application/json", ...options.headers}});
  if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(data.message || `Request failed (${response.status})`); }
  return response.json();
}
function clear() {
  generation++; token = ""; selected = null; cursor = null;
  $("key").value = ""; $("connection").textContent = "Not connected";
  $("rows").replaceChildren(); $("detail").hidden = true; $("more").hidden = true;
  $("result").textContent = ""; $("history").replaceChildren(); $("queue").disabled = false;
}
async function load(append = false) {
  if (!token) return;
  const current = generation;
  const page = await api(`/v1/jobs?limit=12${append && cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`);
  if (current !== generation) return;
  if (!append) $("rows").replaceChildren();
  cursor = page.next_cursor; $("more").hidden = !cursor;
  for (const job of page.items) {
    const row = document.createElement("tr");
    const name = document.createElement("td"), button = document.createElement("button"), id = document.createElement("small");
    button.className = "job-link"; button.textContent = job.task; button.onclick = () => show(job.id).catch(e => message(e.message));
    id.textContent = job.id.slice(0, 8); name.append(button, id); row.append(name);
    const status = document.createElement("td"), badge = document.createElement("span");
    badge.className = `badge ${job.status}`; badge.textContent = job.status.replaceAll("_", " "); status.append(badge); row.append(status);
    for (const text of [`${job.attempts} / ${job.max_attempts}`, new Date(job.created_at).toLocaleString()]) {const cell = document.createElement("td"); cell.textContent = text; row.append(cell);}
    $("rows").append(row);
  }
  if (!$("rows").children.length) {const row = document.createElement("tr"), cell = document.createElement("td"); cell.colSpan = 4; cell.textContent = "No jobs yet. Upload the sample CSV to get started."; row.append(cell); $("rows").append(row);}
}
async function show(id) {
  const current = generation;
  const job = await api(`/v1/jobs/${id}`);
  if (current !== generation) return;
  selected = id; $("detail").hidden = false; $("job-id").textContent = id;
  $("job-title").textContent = job.task; $("job-summary").textContent = `${job.status.replaceAll("_", " ")} · ${job.attempts} attempts${job.last_error ? ` · ${job.last_error}` : ""}`;
  $("history").replaceChildren();
  for (const attempt of job.history) {const item = document.createElement("li"); item.textContent = `Attempt ${attempt.attempt_no}: ${attempt.outcome || "running"}${attempt.duration_ms !== null ? ` (${attempt.duration_ms} ms)` : ""}`; $("history").append(item);}
  $("result").textContent = job.result ? JSON.stringify(job.result, null, 2) : "Result appears after completion.";
  $("retry").hidden = job.status !== "dead";
  $("cancel").hidden = ["succeeded", "dead", "cancelled"].includes(job.status);
}
$("connect").onsubmit = async event => {
  event.preventDefault(); const candidate = $("key").value; clear(); token = candidate;
  try {const session = await api("/v1/session"); $("queue").value = session.queue || "default"; $("queue").disabled = !!session.queue; $("connection").textContent = session.queue ? `Workspace: ${session.queue}` : "Local operator"; await load(); message("Connected. Select a job to see its result and attempt history.");} catch (error) {clear(); message(error.message);}
};
$("disconnect").onclick = () => {clear(); message("Disconnected. Your key and job details have been cleared.");};
$("refresh").onclick = () => load().catch(e => message(e.message));
$("more").onclick = () => load(true).catch(e => message(e.message));
$("submit").onsubmit = async event => {
  event.preventDefault(); if (!token) {message("Connect with an access key first."); return;}
  const button = event.submitter; button.disabled = true;
  try {const file = $("file").files[0]; if (!file || file.size > 48000) throw new Error("Choose a CSV file no larger than 48,000 bytes.");
    const content = new TextDecoder("utf-8", {fatal:true}).decode(await file.arrayBuffer());
    const bytes = new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(content)));
    const hash = [...bytes].map(x => x.toString(16).padStart(2, "0")).join("");
    const job = await api("/v1/jobs", {method:"POST", body:JSON.stringify({task:"sales_report", payload:{content}, queue:$("queue").value, idempotency_key:`sales-report:v1:${hash}`,max_attempts:2})});
    await load(); await show(job.id); message("Report accepted. Status updates every three seconds.");
  } catch (error) {message(error.message);} finally {button.disabled = false;}
};
for (const action of ["retry", "cancel"]) $(action).onclick = async () => {if (!selected) return; try {await api(`/v1/jobs/${selected}/${action}`, {method:"POST"}); await show(selected); await load(); message(`${action === "retry" ? "Retry" : "Cancellation"} requested.`);} catch(error) {message(error.message);}};
setInterval(async () => {if (token && !document.hidden) try {if (selected) await show(selected); await load();} catch(e) {message(e.message);}}, 3000);
