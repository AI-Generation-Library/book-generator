"use strict";
const $ = (id) => document.getElementById(id);
const form = $("book-form");
let token = "";
let jobs = [];
let resumeId = "";
let previewJob = null;
let noticeTimer;
let lastJobs = "";
const labels = {ready: "준비", running: "집필 중", paused: "중단", failed: "확인 필요", completed: "완료"};
const docs = {openai: "https://developers.openai.com/api/docs/models", claude: "https://platform.claude.com/docs/en/about-claude/models/overview", gemini: "https://ai.google.dev/gemini-api/docs/models"};

function notice(message) {
  $("notice").textContent = message;
  $("notice").hidden = false;
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => { $("notice").hidden = true; }, 8500);
}
async function api(path, method = "GET", body) {
  const options = {method, headers: {"X-Generator-Token": token}};
  if (body !== undefined) { options.headers["Content-Type"] = "application/json"; options.body = JSON.stringify(body); }
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "요청을 처리하지 못했습니다.");
  return data;
}
function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}
function action(text, handler, className = "") {
  const button = node("button", "action " + className, text);
  button.type = "button";
  button.addEventListener("click", handler);
  return button;
}
function renderJobs() {
  const serialized = JSON.stringify(jobs);
  if (serialized === lastJobs) return;
  lastJobs = serialized;
  $("jobs").replaceChildren();
  $("empty-state").hidden = jobs.length > 0;
  $("job-count").textContent = `${jobs.length}개 작업`;
  for (const job of jobs) {
    const card = node("article", "job");
    const top = node("div", "job-top");
    const heading = node("div");
    heading.append(node("p", "eyebrow", job.config.demo ? "OFFLINE DEMO" : job.config.provider.toUpperCase()));
    heading.append(node("h3", "", job.config.title));
    heading.append(node("p", "job-meta", `${job.config.id} · ${job.config.chapter_count}장 · ${job.config.demo ? "데모 원고" : job.config.model}`));
    top.append(heading, node("span", `status ${job.status}`, labels[job.status] || job.status));
    card.append(top, node("p", "job-stage", job.message));
    const track = node("div", "progress-track");
    const bar = node("div", "progress-bar");
    const count = job.completed_chapters.length;
    const percent = Math.round(count / job.config.chapter_count * 100);
    bar.style.width = `${percent}%`;
    track.setAttribute("role", "progressbar"); track.setAttribute("aria-label", "장별 작성 진행률");
    track.setAttribute("aria-valuenow", String(count)); track.setAttribute("aria-valuemin", "0");
    track.setAttribute("aria-valuemax", String(job.config.chapter_count));
    track.append(bar); card.append(track);
    const usage = node("div", "usage");
    usage.append(node("span", "", `${count} / ${job.config.chapter_count}장 저장`));
    usage.append(node("span", "", `출력 ${job.output_tokens.toLocaleString()} / ${job.config.output_budget.toLocaleString()}`));
    usage.append(node("span", "", `입력 ${job.input_tokens.toLocaleString()}`));
    if (job.reserved_tokens) usage.append(node("span", "", `예약 ${job.reserved_tokens.toLocaleString()}`));
    card.append(usage);
    const actions = node("div", "job-actions");
    if (job.status === "completed") {
      const link = node("a", "action download", "원고 ZIP ↓");
      link.href = `/api/runs/${job.run_id}/download`; link.setAttribute("download", ""); actions.append(link);
    }
    if (count) actions.append(action("원고 보기 ↗", () => preview(job)));
    if (job.active) actions.append(action("중단", async () => {
      try { const data = await api(`/api/runs/${job.run_id}/cancel`, "POST"); notice(data.message); await refresh(); }
      catch (error) { notice(error.message); }
    }));
    else if (job.status !== "completed") actions.append(action("이어서 집필 →", () => openResume(job)));
    card.append(actions, node("p", "job-path", `generated/${job.run_id}/book/${job.config.id}`));
    $("jobs").append(card);
  }
}
async function refresh() { jobs = await api("/api/runs"); renderJobs(); }
function readConfig(demo) {
  const data = new FormData(form);
  const text = (name) => String(data.get(name) || "").trim();
  return {id: text("id"), title: text("title"), subject: text("subject"), audience: text("audience"),
    language: text("language"), tags: text("tags").split(",").map((item) => item.trim()).filter(Boolean),
    chapter_count: Number(data.get("chapter_count")), outline: text("outline"), references: text("references"),
    provider: text("provider"), model: text("model"), workspace_id: text("provider") === "claude" ? text("workspace_id") : "",
    max_output_tokens: Number(data.get("max_output_tokens")), output_budget: Number(data.get("output_budget")), demo};
}
async function start(demo = false) {
  if (!form.reportValidity()) return;
  const config = readConfig(demo);
  let key = demo ? "" : $("api-key").value.trim();
  if (!demo && (!key || !config.model)) { notice("제공자의 모델 ID와 API 키를 입력해 주세요."); return; }
  $("generate-button").disabled = true; $("demo-button").disabled = true;
  $("api-key").value = "";
  try {
    await api("/api/runs", "POST", {config, api_key: key});
    key = "";
    notice(demo ? "API 호출 없이 데모 원고를 만듭니다." : "집필을 시작했습니다. 진행 상황을 작업실에서 확인하세요.");
    await refresh();
    if (matchMedia("(max-width: 680px)").matches) $("studio-heading").scrollIntoView({behavior: "smooth"});
  } catch (error) { notice(error.message); }
  finally { key = ""; $("generate-button").disabled = false; $("demo-button").disabled = false; }
}
function fillDemo() {
  if (!$("title").value) $("title").value = "나의 첫 번째 학습 안내서";
  if (!$("book-id").value) $("book-id").value = "my-learning-guide";
  if (!$("subject").value) $("subject").value = "학습 목표를 정하고 예제와 검증 계획을 만드는 방법";
  $("chapter-count").value = "3";
  return start(true);
}
function openResume(job) {
  resumeId = job.run_id;
  $("resume-description").textContent = `${job.config.title} · ${job.config.demo ? "데모" : job.config.provider + " / " + job.config.model}`;
  $("resume-key").value = ""; $("resume-key").disabled = job.config.demo;
  $("resume-key").placeholder = job.config.demo ? "데모는 키가 필요하지 않습니다" : "실행에 사용할 키를 다시 입력하세요";
  $("resume-max").value = job.config.max_output_tokens;
  $("resume-budget").value = job.config.output_budget;
  $("resume-dialog").showModal();
}
async function preview(job) {
  previewJob = job;
  $("preview-chapter").replaceChildren();
  for (const number of job.completed_chapters) {
    const option = node("option", "", `${number}장`);
    option.value = number;
    $("preview-chapter").append(option);
  }
  const chapter = job.completed_chapters[job.completed_chapters.length - 1];
  $("preview-chapter").value = chapter;
  await loadPreview(chapter);
}
async function loadPreview(chapter) {
  try {
    const job = previewJob;
    const data = await api(`/api/runs/${job.run_id}/preview?chapter=${chapter}`);
    $("preview-title").textContent = `${job.config.title} · ${chapter}장`;
    $("preview-content").textContent = data.markdown;
    if (!$("preview-dialog").open) $("preview-dialog").showModal();
  } catch (error) { notice(error.message); }
}
form.addEventListener("submit", (event) => { event.preventDefault(); start(false); });
$("demo-button").addEventListener("click", fillDemo);
$("try-demo").addEventListener("click", fillDemo);
$("provider").addEventListener("change", () => {
  $("provider-docs").href = docs[$("provider").value];
  $("workspace-field").hidden = $("provider").value !== "claude";
  $("api-key").value = "";
});
$("close-resume").addEventListener("click", () => { $("resume-key").value = ""; $("resume-dialog").close(); });
$("resume-dialog").addEventListener("close", () => { $("resume-key").value = ""; });
$("close-preview").addEventListener("click", () => $("preview-dialog").close());
$("preview-chapter").addEventListener("change", () => loadPreview($("preview-chapter").value));
$("resume-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  let key = $("resume-key").value.trim();
  $("resume-key").value = "";
  try {
    await api(`/api/runs/${resumeId}/resume`, "POST", {api_key: key,
      output_budget: Number($("resume-budget").value), max_output_tokens: Number($("resume-max").value)});
    key = ""; $("resume-dialog").close(); notice("저장한 지점부터 이어서 집필합니다."); await refresh();
  } catch (error) { notice(error.message); }
  finally { key = ""; }
});
async function poll() {
  try { await refresh(); } catch (error) { notice("로컬 생성기에 연결할 수 없습니다. 서버 실행 상태를 확인해 주세요."); }
  setTimeout(poll, jobs.some((job) => job.active) ? 1200 : 5000);
}
async function init() {
  try { const session = await api("/api/session"); token = session.token; await poll(); }
  catch (error) { notice("로컬 서버 연결을 확인하고 화면을 새로 열어 주세요."); }
}
init();
