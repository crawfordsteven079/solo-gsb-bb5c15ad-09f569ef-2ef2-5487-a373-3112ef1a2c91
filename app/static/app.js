// 回收分拣污染判定 —— 前端逻辑（原生 JS）
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

async function api(path, options = {}) {
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const text = await resp.text();
  const data = text ? JSON.parse(text) : null;
  if (!resp.ok) throw { status: resp.status, data };
  return data;
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ---------- Tab 切换 ----------
$$(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    $$(".tab").forEach((b) => b.classList.remove("active"));
    $$(".panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    $(`#tab-${btn.dataset.tab}`).classList.add("active");
    if (btn.dataset.tab === "rules") loadRules();
    if (btn.dataset.tab === "query") loadDecisions();
    if (btn.dataset.tab === "audit") loadAudit();
  });
});

// ---------- 来料判定 ----------
const MATERIALS = ["PET", "HDPE", "PP", "PAPER", "GLASS", "METAL", "ALU", "ORGANIC"];

function addItemRow(code = "", amount = "", note = "") {
  const tr = document.createElement("tr");
  tr.innerHTML = `
    <td><select class="i-code">
      <option value="">请选择…</option>
      ${MATERIALS.map((m) => `<option ${m === code ? "selected" : ""}>${m}</option>`).join("")}
    </select></td>
    <td><input class="i-amount" type="number" step="0.01" value="${esc(amount)}"></td>
    <td><input class="i-note" value="${esc(note)}"></td>
    <td><button class="secondary" type="button">删除</button></td>`;
  tr.querySelector("button").addEventListener("click", () => tr.remove());
  $("#items-table tbody").appendChild(tr);
}

async function loadRegions() {
  const data = await api("/api/rules/regions");
  const sel = $("#f-region");
  sel.innerHTML = data.items
    .map((r) => `<option value="${esc(r.region)}">${esc(r.region)}（生效：${esc(r.active_version ?? "无")}）</option>`)
    .join("");
  if (!data.items.length) sel.innerHTML = '<option value="">（请先创建规则）</option>';
}

function collectPayload(dryRun) {
  const items = $$("#items-table tbody tr").map((tr) => ({
    material_code: tr.querySelector(".i-code").value,
    contamination_kg: parseFloat(tr.querySelector(".i-amount").value),
    note: tr.querySelector(".i-note").value,
  }));
  const v = $("#f-rulever").value.trim();
  return {
    batch_no: $("#f-batch").value.trim(),
    region: $("#f-region").value,
    weight_kg: parseFloat($("#f-weight").value),
    items,
    ...(v ? { rule_version: v } : {}),
    dry_run: dryRun,
  };
}

function showFieldErrors(box, err) {
  const errs = err.data?.errors || [{ field: "-", message: err.data?.detail || `HTTP ${err.status}` }];
  box.innerHTML = "字段错误：<ul>" +
    errs.map((e) => `<li><b>${esc(e.field)}</b>：${esc(e.message)}</li>`).join("") + "</ul>";
  box.classList.remove("hidden");
}

function renderResult(r) {
  $("#result-card").classList.remove("hidden");
  $("#r-no").textContent = r.persisted ? r.decision_no : "试算结果（未保存）";
  $("#r-summary").innerHTML = `
    <div class="kpi">污染等级<b class="grade-${r.grade}">${r.grade} · ${esc(r.grade_name)}</b></div>
    <div class="kpi">处置结论<b><span class="pill ${r.conclusion_code}">${esc(r.conclusion)}</span></b></div>
    <div class="kpi">污染率<b>${(r.contamination_rate * 100).toFixed(2)}%</b></div>
    <div class="kpi">货值<b>${r.gross_amount.toFixed(2)}</b></div>
    <div class="kpi">扣费合计<b>${r.total_deduction.toFixed(2)}</b></div>
    <div class="kpi">应付(元)<b>${r.net_payable.toFixed(2)}</b></div>`;
  $("#r-deductions").innerHTML =
    `<thead><tr><th>类型</th><th>计算依据</th><th style="text-align:right">金额(${esc(r.currency)})</th></tr></thead>
     <tbody>${r.deductions.map((d) =>
       `<tr><td>${esc(d.name)}</td><td class="muted">${esc(d.basis)}</td>
        <td style="text-align:right">${d.amount.toFixed(2)}</td></tr>`).join("") ||
       '<tr><td colspan="3" class="muted">无扣费</td></tr>'}</tbody>`;
  $("#r-evidence").innerHTML = r.evidence.map((e) => `<li>${esc(e)}</li>`).join("");
  $("#r-meta").textContent = `规则版本：${r.rule_version} ｜ 污染合计：${r.total_contamination_kg}kg`;
}

async function submitJudge(dryRun) {
  const box = $("#judge-errors");
  box.classList.add("hidden");
  try {
    const r = await api("/api/decisions", { method: "POST", body: JSON.stringify(collectPayload(dryRun)) });
    renderResult(r);
    if (!dryRun) {
      $$("#items-table tbody tr").forEach((tr) => tr.remove());
      addItemRow();
    }
  } catch (err) {
    $("#result-card").classList.add("hidden");
    showFieldErrors(box, err);
  }
}

$("#btn-add-item").addEventListener("click", () => addItemRow());
$("#btn-dryrun").addEventListener("click", () => submitJudge(true));
$("#btn-submit").addEventListener("click", () => submitJudge(false));

// ---------- 查询 ----------
function queryParams(prefix) {
  return new URLSearchParams(Object.entries({
    batch_no: $(`#${prefix}-batch`)?.value.trim(),
    region: $(`#${prefix}-region`)?.value.trim(),
    grade: $(`#${prefix}-grade`)?.value,
  }).reduce((acc, [k, v]) => (v ? (acc[k] = v, acc) : acc), {}));
}

async function loadDecisions() {
  const qs = queryParams("q").toString();
  const data = await api(`/api/decisions${qs ? "?" + qs : ""}`);
  $("#query-table tbody").innerHTML = data.items.map((d) => `
    <tr>
      <td><a href="/api/decisions/${encodeURIComponent(d.decision_no)}" target="_blank">${esc(d.decision_no)}</a></td>
      <td>${esc(d.batch_no)}</td><td>${esc(d.region)}</td>
      <td>${d.weight_kg}</td><td>${(d.contamination_rate * 100).toFixed(2)}%</td>
      <td class="grade-${d.grade}">${d.grade}</td>
      <td><span class="pill ${d.conclusion_code}">${esc(d.conclusion)}</span></td>
      <td>${d.result.net_payable.toFixed(2)}</td>
      <td>${esc(d.rule_version)}</td><td class="muted">${esc(d.created_at)}</td>
    </tr>`).join("") || '<tr><td colspan="10" class="muted">暂无数据</td></tr>';

  const exportQs = queryParams("q").toString();
  $("#btn-export").href = `/api/decisions/export/csv${exportQs ? "?" + exportQs : ""}`;
}
$("#btn-query").addEventListener("click", loadDecisions);

// ---------- 规则 ----------
async function loadRules() {
  const [regions, rules] = await Promise.all([
    api("/api/rules/regions"), api("/api/rules"),
  ]);
  $("#regions-table tbody").innerHTML = regions.items.map((r) =>
    `<tr><td>${esc(r.region)}</td><td><b>${esc(r.active_version ?? "—")}</b></td><td>${r.rule_set_id ?? "—"}</td></tr>`
  ).join("") || '<tr><td colspan="3" class="muted">暂无区域</td></tr>';

  $("#rules-table tbody").innerHTML = rules.items.map((r) => `
    <tr>
      <td>${r.id}</td><td>${esc(r.version)}</td><td>${esc(r.region)}</td>
      <td><span class="pill ${r.is_active ? "active" : "draft"}">${r.is_active ? "生效中" : "未激活"}</span></td>
      <td>${esc(r.note)}</td><td class="muted">${esc(r.created_at)}</td>
      <td>${r.is_active ? "" : `<button class="secondary" onclick="activateRule(${r.id})">激活</button>`}
          <button class="secondary" onclick='viewRule(${r.id})'>查看</button></td>
    </tr>`).join("");
  window.__rules = rules.items;
}

window.activateRule = async (id) => {
  await api(`/api/rules/${id}/activate`, { method: "POST" });
  await loadRules();
  await loadRegions();
};

window.viewRule = (id) => {
  const r = window.__rules.find((x) => x.id === id);
  $("#n-version").value = r.version + "-copy";
  $("#n-region").value = r.region;
  $("#n-content").value = JSON.stringify(r.content, null, 2);
  window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
};

$("#btn-create-rule").addEventListener("click", async () => {
  const box = $("#rule-errors");
  box.classList.add("hidden");
  let content;
  try {
    content = JSON.parse($("#n-content").value);
  } catch (e) {
    box.innerHTML = "规则内容不是合法 JSON：" + esc(e.message);
    box.classList.remove("hidden");
    return;
  }
  try {
    await api("/api/rules", {
      method: "POST",
      body: JSON.stringify({
        version: $("#n-version").value.trim(),
        region: $("#n-region").value.trim(),
        note: $("#n-note").value,
        content,
        activate: $("#n-activate").checked,
      }),
    });
    await loadRules();
    await loadRegions();
    box.textContent = "创建成功";
    box.className = "errors";
    box.style.background = "#e2f3e6";
    box.style.color = "#1e7d3c";
    box.classList.remove("hidden");
  } catch (err) {
    box.style.background = "";
    box.style.color = "";
    showFieldErrors(box, err);
  }
});

// ---------- 审计 ----------
async function loadAudit() {
  const params = new URLSearchParams();
  ["action", "entity", "ref"].forEach((k, i) => {
    const el = ["a-action", "a-entity", "a-ref"][i];
    if ($(el).value.trim()) params.set(k === "entity" ? "entity_type" : k, $(el).value.trim());
  });
  const data = await api(`/api/audit-logs?${params}`);
  $("#audit-table tbody").innerHTML = data.items.map((r) => `
    <tr>
      <td class="muted">${esc(r.created_at)}</td>
      <td><b>${esc(r.action)}</b></td>
      <td>${esc(r.entity_type)}</td><td>${esc(r.entity_ref)}</td>
      <td>${esc(r.operator)}</td>
      <td class="muted"><code>${esc(JSON.stringify(r.detail))}</code></td>
    </tr>`).join("") || '<tr><td colspan="6" class="muted">暂无记录</td></tr>';
}
$("#btn-audit").addEventListener("click", loadAudit);

// ---------- 初始化 ----------
addItemRow();
loadRegions();
