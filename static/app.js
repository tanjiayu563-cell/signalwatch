const app = {
  state: null,
  tab: "events",
  busy: false,
  eventMap: new Map(),
  runMap: new Map(),
  itemMap: new Map(),
  previousWatchTerms: "",
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));
const SOURCE_LABELS = {manual_article: "手动导入文章"};

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function safeUrl(value) {
  try {
    const url = new URL(String(value || ""), window.location.origin);
    return ["http:", "https:"].includes(url.protocol) ? url.href : "#";
  } catch {
    return "#";
  }
}

function formatTime(value, withDate = true) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    ...(withDate ? { month: "2-digit", day: "2-digit" } : {}),
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function formatHotValue(value) {
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) return "--";
  if (number >= 100000000) return `${(number / 100000000).toFixed(1)}亿`;
  if (number >= 10000) return `${(number / 10000).toFixed(1)}万`;
  return number.toLocaleString("zh-CN");
}

function sourceName(sourceId) {
  const source = app.state?.sources?.find((entry) => entry.id === sourceId);
  return source?.name || SOURCE_LABELS[sourceId] || sourceId;
}

function riskLabel(risk) {
  return { high: "高风险", medium: "中风险", low: "低风险" }[risk] || "低风险";
}

function sentimentLabel(sentiment) {
  return { negative: "负向", positive: "正向", neutral: "中性" }[sentiment] || "中性";
}

function reviewLabel(status) {
  return {
    new: "待研判",
    reviewing: "研判中",
    closed: "已处置",
    false_positive: "误报",
  }[status] || "待研判";
}

function truncate(value, length = 150) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  return text.length > length ? `${text.slice(0, length)}…` : text;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.error || `请求失败：HTTP ${response.status}`);
  }
  return payload;
}

async function loadState({ quiet = false } = {}) {
  try {
    const state = await api("/api/state");
    app.state = state;
    render(state);
    if (!quiet) setLiveState(true);
    return state;
  } catch (error) {
    setLiveState(false, "服务异常");
    if (!quiet) toast(error.message, true);
    throw error;
  }
}

function setLiveState(ok, customText = "") {
  const dot = $("#liveDot");
  const text = $("#liveText");
  dot.classList.remove("ok", "warn");
  if (ok) {
    dot.classList.add("ok");
    text.textContent = "公开源在线";
  } else {
    dot.classList.add("warn");
    text.textContent = customText || "连接异常";
  }
}

function render(state) {
  const stats = state.stats || {};
  $("#statItems").textContent = stats.items ?? 0;
  $("#statEvents").textContent = stats.events ?? 0;
  $("#statAlerts").textContent = stats.alert_items ?? 0;
  $("#statSources").textContent = stats.sources_ok ?? 0;
  $("#statSourcesTotal").textContent = `/${stats.sources_total ?? 0}`;
  $("#tabEventCount").textContent = stats.events ?? 0;
  $("#tabItemCount").textContent = stats.items ?? 0;
  $("#tabRunCount").textContent = state.agent_runs?.length ?? 0;
  $("#authCount").textContent = stats.auth_pending ?? 0;
  $("#coverageNote").textContent = state.coverage_note || "当前只展示公开来源覆盖范围。";
  $("#lastScan").textContent = `最近扫描：${formatTime(state.scanner?.last_finished_at)}`;
  renderAI(state.ai || {});

  const watchInput = $("#watchInput");
  const watchSignature = (state.watch_terms || []).join("\u0000");
  if (watchSignature !== app.previousWatchTerms) {
    $("#matchedOnly").checked = Boolean(state.watch_terms?.length);
    app.previousWatchTerms = watchSignature;
  }
  if (document.activeElement !== watchInput) {
    const terms = (state.watch_terms || []).join("，");
    if (watchInput.value !== terms) watchInput.value = terms;
  }

  const running = Boolean(state.scanner?.running || app.busy);
  const scanBadge = $("#scanBadge");
  scanBadge.classList.toggle("running", running);
  scanBadge.textContent = running
    ? "正在扫描公开来源…"
    : state.scanner?.last_error
      ? "部分来源异常"
      : stats.items
        ? `监测词 ${state.watch_terms?.length || 0} 个`
        : "等待首次扫描";

  const scanButton = $("#scanButton");
  scanButton.disabled = running;
  scanButton.querySelector("span:last-child").textContent = running ? "扫描中" : "立即扫描";

  renderSources(state.public_sources || []);
  renderAuthSources(state.auth_sources || []);
  renderSourceFilter(state.sources || []);
  renderFeed();
}

function renderAI(ai) {
  const enabled = Boolean(ai.enabled);
  const status = $("#aiStatus");
  status.textContent = enabled ? "已启用" : "未配置";
  status.classList.toggle("warn", !enabled);
  $("#aiModelName").textContent = enabled ? ai.model : "规则引擎";
  $("#aiCopy").textContent = enabled
    ? "模型只接收命中监测词的候选证据，输出结构化研判；规则风险仍作为兜底，不直接执行任何外部动作。"
    : "当前使用本地规则引擎；配置模型后只分析命中的候选内容，规则结果保留为兜底。";
  const error = $("#aiError");
  error.hidden = !ai.last_error;
  error.textContent = ai.last_error || "";
  $("#footerMode").textContent = ai.mode_label || "规则引擎 · 单机模式";
  renderNotifications(app.state?.notifications || {});
}

function renderNotifications(notifications) {
  const element = $("#notificationChannels");
  if (!element) return;
  const channels = notifications.channels || [];
  element.textContent = channels.length
    ? channels.map((channel) => channel === "webhook" ? "Webhook" : "邮件").join(" / ")
    : "未配置";
}

function renderSources(sources) {
  const list = $("#sourceList");
  const okCount = sources.filter((source) => source.runtime_status === "ok").length;
  const mini = $("#sourceHealthMini");
  mini.textContent = `${okCount}/${sources.length}`;
  mini.classList.toggle("warn", okCount < sources.length);

  list.innerHTML = sources.map((source) => {
    const status = source.runtime_status;
    const dotClass = status === "ok" ? "dot-ok" : status === "error" ? "dot-bad" : "dot-warn";
    const statusText = status === "ok"
      ? `${source.item_count || 0} 条`
      : status === "running"
        ? "扫描中"
        : status === "error"
          ? "异常"
          : "待扫描";
    return `
      <div class="source-item">
        <div class="source-head">
          <span class="source-name"><i class="dot ${dotClass}"></i>${esc(source.name)}</span>
          <span class="source-time">${esc(statusText)}</span>
        </div>
        <div class="source-meta">${esc(source.coverage)} · ${formatTime(source.last_run_at)}</div>
        ${source.error ? `<div class="source-error">${esc(truncate(source.error, 120))}</div>` : ""}
      </div>
    `;
  }).join("");
}

function renderAuthSources(sources) {
  const list = $("#authList");
  if (!sources.length) {
    list.innerHTML = `<div class="side-copy">暂无待授权来源。</div>`;
    return;
  }
  list.innerHTML = sources.map((source) => {
    const configured = Boolean(source.credential?.configured);
    const label = configured ? "已保存待验证" : source.coverage;
    return `
      <div class="auth-item">
        <div class="auth-item-head">
          <strong>${esc(source.name)}</strong>
          <button class="auth-button ${configured ? "configured" : ""}" type="button"
            data-auth-source="${esc(source.id)}">${configured ? "管理" : "授权"}</button>
        </div>
        <div class="auth-meta">${esc(source.kind)} · ${esc(label)}</div>
      </div>
    `;
  }).join("");
}

function renderSourceFilter(sources) {
  const select = $("#sourceFilter");
  const current = select.value || "all";
  const knownIds = new Set(sources.map((source) => source.id));
  const dynamicSources = (app.state?.items || [])
    .map((item) => item.source)
    .filter((sourceId, index, all) => sourceId && !knownIds.has(sourceId) && all.indexOf(sourceId) === index)
    .map((sourceId) => ({id: sourceId, name: SOURCE_LABELS[sourceId] || sourceId}));
  select.innerHTML = `<option value="all">全部来源</option>` + [...sources, ...dynamicSources]
    .filter((source) => !source.auth_required || source.credential?.configured)
    .map((source) => `<option value="${esc(source.id)}">${esc(source.name)}</option>`)
    .join("");
  select.value = Array.from(select.options).some((option) => option.value === current)
    ? current
    : "all";
}

function filteredEvents() {
  if (!app.state) return [];
  const query = $("#searchFilter").value.trim().toLowerCase();
  const risk = $("#riskFilter").value;
  const source = $("#sourceFilter").value;
  const matchedOnly = $("#matchedOnly").checked;

  return app.state.events.filter((event) => {
    if (risk !== "all" && event.risk_level !== risk) return false;
    if (source !== "all" && !event.sources.includes(source)) return false;
    if (matchedOnly && !(event.alert || event.matched_terms.length)) return false;
    if (!query) return true;
    const haystack = [
      event.title,
      event.summary,
      ...(event.matched_terms || []),
      ...(event.risk_reasons || []),
    ].join(" ").toLowerCase();
    return haystack.includes(query);
  });
}

function filteredItems() {
  if (!app.state) return [];
  const query = $("#searchFilter").value.trim().toLowerCase();
  const risk = $("#riskFilter").value;
  const source = $("#sourceFilter").value;
  const matchedOnly = $("#matchedOnly").checked;

  return app.state.items.filter((item) => {
    if (risk !== "all" && item.risk_level !== risk) return false;
    if (source !== "all" && item.source !== source) return false;
    if (matchedOnly && !(item.alert || item.matched_terms.length)) return false;
    if (!query) return true;
    const haystack = [
      item.title,
      item.summary,
      ...(item.matched_terms || []),
      ...(item.risk_reasons || []),
    ].join(" ").toLowerCase();
    return haystack.includes(query);
  });
}

function renderFeed() {
  if (!app.state) return;
  const list = $("#feedList");
  app.eventMap = new Map(app.state.events.map((event) => [event.id, event]));
  app.runMap = new Map((app.state.agent_runs || []).map((run) => [run.id, run]));
  app.itemMap = new Map(
    app.state.events.flatMap((event) => event.items || []).map((item) => [item.id, item])
  );
  if (app.tab === "events") {
    renderEvents(list);
  } else if (app.tab === "items") {
    renderItems(list);
  } else {
    renderRuns(list);
  }
}

function renderEvents(list) {
  const events = filteredEvents();
  const visible = events.slice(0, 100);
  $("#resultNote").textContent = events.length
    ? `显示 ${visible.length} / ${events.length} 个事件 · 命中监测词的事件优先排序`
    : "当前筛选条件下没有事件";

  if (!visible.length) {
    list.innerHTML = emptyMarkup(
      app.state.stats.items ? "没有符合筛选条件的事件" : "正在建立监测基线",
      app.state.stats.items
        ? "尝试清除筛选条件，或加入新的监测关键词后重新扫描。"
        : "公开来源首次扫描完成后，事件会显示在这里。"
    );
    return;
  }

  list.innerHTML = visible.map((event) => {
    const lead = event.items[0] || {};
    const reasons = (event.risk_reasons || []).slice(0, 3);
    const aiUsed = event.items.some((item) => item.ai && item.ai.risk_level);
    return `
      <article class="event-card risk-${esc(event.risk_level)}" data-event-id="${esc(event.id)}">
        <div class="event-top">
          <div class="badge-row">
            <span class="badge ${esc(event.risk_level)}">${esc(riskLabel(event.risk_level))}</span>
            ${event.alert ? `<span class="badge alert">监测命中</span>` : ""}
            ${event.matched_terms.length ? `<span class="badge match">${esc(event.matched_terms.join(" / "))}</span>` : ""}
            ${aiUsed ? `<span class="badge ai-badge">AI研判</span>` : ""}
            <span class="badge neutral">${esc(sentimentLabel(event.sentiment))}</span>
          </div>
          <time class="event-time">${formatTime(event.last_seen)}</time>
        </div>
        <h3>${esc(event.title)}</h3>
        <p class="event-summary">${esc(event.summary || "该信号暂无摘要，请打开证据链查看原始来源。")}</p>
        ${reasons.length ? `<div class="reason-strip">${reasons.map((reason) => `<span>${esc(reason)}</span>`).join("")}</div>` : ""}
        <div class="event-meta">
          <span><strong>${event.item_count}</strong> 条证据</span>
          <span><strong>${event.sources.map(sourceName).join(" · ")}</strong></span>
          <span>状态：<strong>${esc(reviewLabel(event.review_status))}</strong></span>
          <span>首次：${formatTime(event.first_seen)}</span>
        </div>
        <div class="event-actions">
          <button class="text-button" type="button" data-open-event="${esc(event.id)}">查看事件链</button>
          <a class="source-link primary-link" href="${safeUrl(lead.url)}" target="_blank" rel="noopener noreferrer">打开原文 ↗</a>
        </div>
      </article>
    `;
  }).join("");
}

function renderItems(list) {
  const items = filteredItems();
  const visible = items.slice(0, 150);
  $("#resultNote").textContent = items.length
    ? `显示 ${visible.length} / ${items.length} 条原始信号 · 跨平台聚合前保留独立来源`
    : "当前筛选条件下没有原始信号";

  if (!visible.length) {
    list.innerHTML = emptyMarkup(
      app.state.stats.items ? "没有符合筛选条件的信号" : "正在读取公开热榜",
      app.state.stats.items
        ? "尝试清除筛选条件或使用新的监测关键词。"
        : "微博、抖音、今日头条、B站和中新网的公开信号会显示在这里。"
    );
    return;
  }

  list.innerHTML = visible.map((item) => `
    <article class="signal-row">
      <div class="signal-rank">${item.rank ? `#${esc(item.rank)}` : "NEW"}</div>
      <div>
        <div class="signal-top">
          <span class="badge ${esc(item.risk_level)}">${esc(riskLabel(item.risk_level))}</span>
          ${item.alert ? `<span class="badge alert">命中</span>` : ""}
          ${item.matched_terms.length ? `<span class="badge match">${esc(item.matched_terms.join(" / "))}</span>` : ""}
        </div>
        <h3 class="signal-title">${esc(item.title)}</h3>
        <div class="signal-meta">${esc(sourceName(item.source))} · 热度 ${formatHotValue(item.hot_value)} · ${formatTime(item.published_at || item.fetched_at)}</div>
      </div>
      <div class="signal-side">
        <span class="review-status">${esc(reviewLabel(item.review_status))}</span>
        <a class="source-link" href="${safeUrl(item.url)}" target="_blank" rel="noopener noreferrer">原文 ↗</a>
      </div>
    </article>
  `).join("");
}

function emptyMarkup(title, text) {
  return `
    <div class="empty-state">
      <div class="radar-loader"><span></span></div>
      <h3>${esc(title)}</h3>
      <p>${esc(text)}</p>
    </div>
  `;
}

function renderRuns(list) {
  const runs = (app.state?.agent_runs || []).filter((run) => {
    const query = $("#searchFilter").value.trim().toLowerCase();
    if (!query) return true;
    return [run.id, run.trigger, ...(run.watch_terms || []), ...(run.steps || []).map((step) => step.summary)]
      .join(" ")
      .toLowerCase()
      .includes(query);
  });
  $("#resultNote").textContent = runs.length
    ? `显示 ${runs.length} 次 Agent 运行 · 每一步均可追溯`
    : "还没有 Agent 运行记录";

  if (!runs.length) {
    list.innerHTML = emptyMarkup("等待 Agent 运行", "点击“立即扫描”后，系统会记录查询计划、数据源、研判和告警步骤。");
    return;
  }

  list.innerHTML = runs.map((run) => {
    const metrics = run.metrics || {};
    const statusLabel = {
      completed: "已完成",
      partial: "部分完成",
      failed: "失败",
      running: "运行中",
    }[run.status] || run.status;
    return `
      <article class="event-card run-card">
        <div class="event-top">
          <div class="badge-row">
            <span class="badge ${run.status === "failed" ? "high" : run.status === "partial" ? "medium" : "alert"}">${esc(statusLabel)}</span>
            <span class="badge neutral">${esc(run.trigger)}</span>
            <span class="badge match">${esc((run.watch_terms || []).join(" / ") || "未设置监测词")}</span>
          </div>
          <time class="event-time">${formatTime(run.started_at)}</time>
        </div>
        <h3>Agent 运行 ${esc(run.id.slice(0, 10))}</h3>
        <p class="event-summary">${esc(run.plan?.objective || "未记录运行目标")}</p>
        <div class="event-meta">
          <span>来源成功 <strong>${metrics.sources_ok ?? 0}</strong></span>
          <span>信号 <strong>${metrics.items_fetched ?? 0}</strong></span>
          <span>命中 <strong>${metrics.items_matched ?? 0}</strong></span>
          <span>告警候选 <strong>${metrics.new_alert_candidates ?? 0}</strong></span>
          <span>耗时 <strong>${metrics.duration_seconds ?? "--"}s</strong></span>
        </div>
        <div class="event-actions">
          <button class="text-button" type="button" data-open-run="${esc(run.id)}">查看完整轨迹</button>
          ${run.error ? `<span class="source-error">${esc(truncate(run.error, 100))}</span>` : ""}
        </div>
      </article>
    `;
  }).join("");
}

function openRunDetail(runId) {
  const run = app.runMap.get(runId);
  if (!run) return;
  const stepRows = (run.steps || []).map((step, index) => `
    <div class="trace-step">
      <div class="trace-index">${index + 1}</div>
      <div class="trace-body">
        <div class="trace-head"><strong>${esc(step.name)}</strong><span class="review-status">${esc(step.status)}</span></div>
        <p>${esc(step.summary)}</p>
        <time>${formatTime(step.at)}</time>
      </div>
    </div>
  `).join("");
  const sourcePlan = (run.plan?.source_names || []).map((name) => `<span class="badge neutral">${esc(name)}</span>`).join("");
  $("#detailContent").innerHTML = `
    <div class="detail-headline">
      <span class="section-kicker">AGENT TRACE</span>
      <h2>运行 ${esc(run.id)}</h2>
    </div>
    <p class="detail-summary">${esc(run.plan?.objective || "")}</p>
    <div class="detail-meta">${sourcePlan}<span class="badge neutral">${esc(run.trigger)}</span></div>
    <div class="detail-block">
      <h3>执行轨迹</h3>
      <div class="trace-list">${stepRows}</div>
    </div>
    <div class="detail-block">
      <h3>运行指标</h3>
      <pre class="metrics-json">${esc(JSON.stringify(run.metrics || {}, null, 2))}</pre>
    </div>
  `;
  $("#detailModal").showModal();
}

function setTab(tab) {
  app.tab = tab;
  ["events", "items", "runs"].forEach((name) => {
    const button = $(`#${name}Tab`);
    button.classList.toggle("active", tab === name);
    button.setAttribute("aria-selected", String(tab === name));
  });
  renderFeed();
}

async function scanNow() {
  if (app.busy) return;
  app.busy = true;
  render(app.state);
  try {
    const result = await api("/api/scan", { method: "POST", body: "{}" });
    if (result.status === "busy") {
      toast("扫描任务已在运行中");
    } else if (result.sources_failed) {
      toast(`扫描完成：${result.sources_ok} 个来源成功，${result.sources_failed} 个异常`);
    } else {
      toast(`扫描完成：${result.items} 条公开信号，${result.sources_ok} 个来源正常`);
    }
    if (result.ai_enabled && result.ai_error) {
      toast(`AI 研判失败，已保留规则结果：${result.ai_error}`, true);
    }
    await loadState({ quiet: true });
  } catch (error) {
    toast(error.message, true);
  } finally {
    app.busy = false;
    if (app.state) render(app.state);
  }
}

async function saveWatchTerms(event) {
  event.preventDefault();
  const value = $("#watchInput").value.trim();
  const terms = value.split(/[,，\n;；]+/).map((term) => term.trim()).filter(Boolean);
  const button = $("#watchButton");
  button.disabled = true;
  button.textContent = "保存中…";
  try {
    await api("/api/watch-terms", {
      method: "POST",
      body: JSON.stringify({ terms }),
    });
    await loadState({ quiet: true });
    await scanNow();
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = "保存并扫描";
  }
}

async function openImportArticle() {
  $("#importUrl").value = "";
  $("#importModal").showModal();
  setTimeout(() => $("#importUrl").focus(), 50);
}

async function submitImportArticle(event) {
  if (event.submitter?.value === "cancel") return;
  event.preventDefault();
  const url = $("#importUrl").value.trim();
  if (!url) { toast("请填写文章链接", true); return; }
  const button = $("#importSubmit");
  button.disabled = true;
  button.textContent = "读取中…";
  try {
    const result = await api("/api/articles/import", {method:"POST", body:JSON.stringify({url})});
    $("#importModal").close();
    const matched = result.analysis?.matched_terms || [];
    toast(matched.length ? `文章已导入，命中监测词：${matched.join("、")}` : "文章已导入，但未命中当前监测词");
    await loadState({quiet:true});
    if (matched.length) {
      $("#matchedOnly").checked = true;
      renderFeed();
    }
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = "读取并导入";
  }
}

async function openArticle(itemId) {
  const item = app.itemMap.get(itemId) || {};
  const content = $("#articleContent");
  const originalUrl = safeUrl(item.url);
  content.innerHTML = `
    <div class="detail-headline"><span class="section-kicker">SOURCE ARTICLE</span><h2>正在读取原文…</h2></div>
    <p class="detail-summary">系统正在提取原网页正文。部分平台可能需要登录或依赖 JavaScript，提取失败时会保留原网页入口。</p>
    <div class="radar-loader"><span></span></div>
  `;
  $("#articleModal").showModal();
  try {
    const result = await api(`/api/article?item_id=${encodeURIComponent(itemId)}`);
    const article = result.article || {};
    const paragraphs = String(article.text || "").split(/\n{2,}/).filter(Boolean);
    content.innerHTML = `
      <div class="detail-headline">
        <span class="section-kicker">SOURCE ARTICLE</span>
        <h2>${esc(article.title || article.original_title || "原始文章")}</h2>
      </div>
      <div class="detail-meta">
        <span class="badge neutral">${esc(article.site_name || sourceName(article.source))}</span>
        <span class="badge neutral">${esc(article.char_count || 0)} 字</span>
        <span class="badge neutral">${formatTime(article.published_at || article.fetched_at)}</span>
      </div>
      <div class="article-body">${paragraphs.map((paragraph) => `<p>${esc(paragraph)}</p>`).join("")}</div>
      <div class="modal-actions">
        <a class="button button-primary" href="${safeUrl(article.canonical_url || article.original_url || item.url)}" target="_blank" rel="noopener noreferrer">打开原网页 ↗</a>
      </div>
      <div class="security-note">正文仅用于当前监测研判，请以原始网页为准，并遵守来源平台版权和访问条款。</div>
    `;
  } catch (error) {
    content.innerHTML = `
      <div class="detail-headline"><span class="section-kicker">SOURCE ARTICLE</span><h2>${esc(item.title || "无法读取原文")}</h2></div>
      <div class="security-note">${esc(error.message)}</div>
      <p class="detail-summary">该平台可能要求登录、验证或 JavaScript 渲染。请通过原始链接查看。</p>
      <div class="modal-actions">
        <a class="button button-primary" href="${originalUrl}" target="_blank" rel="noopener noreferrer">打开原网页 ↗</a>
      </div>
    `;
  }
}

function prStageLabel(value) {
  return {latent:"潜伏期", emerging:"初现期", outbreak:"爆发期", spreading:"扩散期", receding:"回落期", unknown:"阶段不明"}[value] || "阶段不明";
}

function crisisTypeLabel(value) {
  return {victim:"受害者型", accidental:"意外型", preventable:"可预防型", not_crisis:"非危机", unknown:"类型不明"}[value] || "类型不明";
}

function renderPrAnalysis(analysis) {
  const stakeholders = (analysis.stakeholders || []).map((item) => `
    <div class="pr-list-item"><strong>${esc(item.name || "未命名")}</strong><span>${esc(item.priority || "")}</span><p>${esc(item.concern || "")}${item.impact ? ` · ${esc(item.impact)}` : ""}</p></div>
  `).join("");
  const actions = (analysis.immediate_actions || []).map((item) => `
    <div class="pr-list-item"><strong>${esc(item.timing || "ongoing")}</strong><p>${esc(item.action || "")}${item.reason ? `<br><small>${esc(item.reason)}</small>` : ""}</p></div>
  `).join("");
  return `
    <div class="pr-analysis">
      <div class="pr-summary">${esc(analysis.executive_summary || "暂无摘要")}</div>
      <div class="pr-grid">
        <div class="pr-metric"><span>议题阶段</span><strong>${esc(prStageLabel(analysis.issue_stage))}</strong></div>
        <div class="pr-metric"><span>危机类型</span><strong>${esc(crisisTypeLabel(analysis.crisis_type))}</strong></div>
        <div class="pr-metric"><span>严重程度</span><strong>${esc(riskLabel(analysis.severity))}</strong></div>
        <div class="pr-metric"><span>置信度</span><strong>${Math.round(Number(analysis.confidence || 0) * 100)}%</strong></div>
      </div>
      ${(analysis.frameworks_applied || []).length ? `<div class="pr-tags">${analysis.frameworks_applied.map((item) => `<span>${esc(item)}</span>`).join("")}</div>` : ""}
      ${stakeholders ? `<h3>利益相关方</h3><div class="pr-list">${stakeholders}</div>` : ""}
      ${analysis.response_posture ? `<h3>建议响应姿态</h3><p class="pr-copy">${esc(analysis.response_posture)}</p>` : ""}
      ${actions ? `<h3>即时动作</h3><div class="pr-list">${actions}</div>` : ""}
      <div class="pr-two-col">
        <div><h3>事实</h3><ul>${(analysis.facts || []).map((item) => `<li>${esc(item.statement)}</li>`).join("") || "<li>暂无</li>"}</ul></div>
        <div><h3>未证实说法</h3><ul>${(analysis.unverified_claims || []).map((item) => `<li>${esc(item.claim)}</li>`).join("") || "<li>暂无</li>"}</ul></div>
      </div>
      <div class="pr-two-col">
        <div><h3>声誉风险</h3><ul>${(analysis.reputational_risks || []).map((item) => `<li>${esc(item)}</li>`).join("") || "<li>暂无</li>"}</ul></div>
        <div><h3>沟通原则</h3><ul>${(analysis.message_principles || []).map((item) => `<li>${esc(item)}</li>`).join("") || "<li>暂无</li>"}</ul></div>
      </div>
      ${analysis.draft_holding_statement ? `<h3>声明草稿</h3><blockquote class="pr-statement">${esc(analysis.draft_holding_statement)}</blockquote>` : ""}
      <div class="pr-two-col">
        <div><h3>避免动作</h3><ul>${(analysis.avoid_actions || []).map((item) => `<li>${esc(item)}</li>`).join("") || "<li>暂无</li>"}</ul></div>
        <div><h3>证据缺口</h3><ul>${(analysis.evidence_gaps || []).map((item) => `<li>${esc(item)}</li>`).join("") || "<li>暂无</li>"}</ul></div>
      </div>
      <h3>后续监测问题</h3><ul>${(analysis.monitoring_questions || []).map((item) => `<li>${esc(item)}</li>`).join("") || "<li>暂无</li>"}</ul>
      <div class="security-note">公共关系分析由模型辅助生成。声明草稿必须经公关负责人、法务和管理层复核，不构成法律意见或最终决策。</div>
      <div class="modal-actions"><button class="button button-ghost" type="button" data-pr-refresh>重新生成分析</button></div>
    </div>
  `;
}

async function analyzeEventPr(eventId, force = false) {
  const area = $("#prAnalysisArea");
  const button = document.querySelector('[data-pr-analysis]');
  if (area) area.innerHTML = `<div class="pr-loading"><div class="radar-loader"><span></span></div><p>正在读取证据原文并生成公共关系研判…</p></div>`;
  if (button) { button.disabled = true; button.textContent = "分析中…"; }
  try {
    const result = await api("/api/events/analyze", {method:"POST", body:JSON.stringify({event_id:eventId, force})});
    if (area) area.innerHTML = renderPrAnalysis(result.analysis?.analysis || {});
    if (button) { button.disabled = false; button.textContent = "重新生成公共关系研判"; }
    const refresh = document.querySelector('[data-pr-refresh]');
    if (refresh) refresh.dataset.prRefresh = eventId;
  } catch (error) {
    if (area) area.innerHTML = `<div class="security-note">公共关系分析失败：${esc(error.message)}</div>`;
    if (button) { button.disabled = false; button.textContent = "生成公共关系研判"; }
  }
}

function openDetail(eventId) {
  const event = app.eventMap.get(eventId);
  if (!event) return;
  const aiItem = event.items.find((item) => item.ai && item.ai.risk_level);
  const aiBlock = aiItem ? `
    <div class="detail-block">
      <h3>AI 辅助研判</h3>
      <p class="detail-summary">${esc(aiItem.ai.summary || "模型未提供摘要")}</p>
      <div class="detail-reasons">${(aiItem.ai.risk_reasons || []).map((reason) => `<span>${esc(reason)}</span>`).join("") || "<span>模型未提供风险原因</span>"}</div>
      <div class="evidence-meta">
        <span>风险等级：${esc(riskLabel(aiItem.ai.risk_level))}</span>
        <span>信息类型：${esc(aiItem.ai.claim_type || "unverified")}</span>
        <span>置信度：${Math.round(Number(aiItem.ai.confidence || 0) * 100)}%</span>
      </div>
      ${(aiItem.ai.verification_questions || []).length ? `<div class="security-note">核查问题：${aiItem.ai.verification_questions.map(esc).join("；")}</div>` : ""}
    </div>
  ` : "";
  $("#detailContent").innerHTML = `
    <div class="detail-headline">
      <div class="badge-row">
        <span class="badge ${esc(event.risk_level)}">${esc(riskLabel(event.risk_level))}</span>
        ${event.alert ? `<span class="badge alert">监测命中</span>` : ""}
        <span class="badge neutral">${esc(sentimentLabel(event.sentiment))}</span>
        <span class="review-status">${esc(reviewLabel(event.review_status))}</span>
      </div>
      <h2>${esc(event.title)}</h2>
    </div>
    <p class="detail-summary">${esc(event.summary || "暂无摘要")}</p>
    <div class="detail-meta">
      ${event.matched_terms.map((term) => `<span class="badge match">${esc(term)}</span>`).join("")}
      <span class="badge neutral">${event.item_count} 条证据</span>
      <span class="badge neutral">${esc(event.sources.map(sourceName).join(" · "))}</span>
      <span class="badge neutral">首次 ${formatTime(event.first_seen)}</span>
    </div>
    ${aiBlock}
    <div class="detail-block">
      <h3>规则研判依据</h3>
      <div class="detail-reasons">${(event.risk_reasons || []).map((reason) => `<span>${esc(reason)}</span>`).join("") || "<span>未命中明显风险词</span>"}</div>
      <div class="security-note">该等级由本地规则引擎自动生成，属于辅助研判，不是事实认定或法律结论。</div>
    </div>
    <div class="detail-block">
      <h3>证据链</h3>
      <div class="evidence-list">
        ${event.items.map((item) => `
          <article class="evidence-card">
            <h4 class="evidence-title">${esc(item.title)}</h4>
            <div class="evidence-meta">
              <span>${esc(sourceName(item.source))}</span>
              <span>${item.rank ? `榜单 #${esc(item.rank)}` : "新闻信号"}</span>
              <span>热度 ${formatHotValue(item.hot_value)}</span>
              <span>${formatTime(item.published_at || item.fetched_at)}</span>
              <span>${esc(item.author || "未知来源")}</span>
            </div>
            <div class="evidence-actions">
              <div class="source-actions">
                <button class="small-button" type="button" data-read-article="${esc(item.id)}">阅读正文</button>
                <a class="source-link primary-link" href="${safeUrl(item.url)}" target="_blank" rel="noopener noreferrer">打开原网页 ↗</a>
              </div>
              <div class="review-actions">
                <button class="small-button" type="button" data-review="${esc(item.id)}" data-status="reviewing">研判中</button>
                <button class="small-button" type="button" data-review="${esc(item.id)}" data-status="closed">已处置</button>
                <button class="small-button" type="button" data-review="${esc(item.id)}" data-status="false_positive">误报</button>
              </div>
            </div>
          </article>
        `).join("")}
      </div>
    </div>
    <div class="detail-block pr-panel">
      <div class="side-head">
        <div><span class="section-kicker">PUBLIC RELATIONS REVIEW</span><h3>公共关系研判</h3></div>
        <button class="button button-accent" type="button" data-pr-analysis="${esc(event.id)}">生成公共关系研判</button>
      </div>
      <div id="prAnalysisArea"><p class="side-copy">按利益相关方、议题生命周期、危机类型、响应姿态和沟通原则生成辅助研判。</p></div>
    </div>
    <div class="modal-actions">
      <a class="button button-ghost" href="/api/reports/event?event_id=${encodeURIComponent(event.id)}" download>导出 Markdown 报告</a>
      <button class="button button-ghost" type="button" data-review-group="${esc(event.id)}" data-status="reviewing">整组开始研判</button>
      <button class="button button-primary" type="button" data-review-group="${esc(event.id)}" data-status="closed">整组标记已处置</button>
    </div>
  `;
  $("#detailModal").showModal();
}

async function reviewItems(itemIds, status) {
  if (!itemIds.length) return;
  try {
    await api("/api/reviews", {
      method: "POST",
      body: JSON.stringify({ item_ids: itemIds, status }),
    });
    toast(`状态已更新：${reviewLabel(status)}`);
    await loadState({ quiet: true });
    $("#detailModal").close();
  } catch (error) {
    toast(error.message, true);
  }
}

function openAuth(sourceId) {
  const source = app.state?.auth_sources?.find((entry) => entry.id === sourceId);
  if (!source) return;
  $("#authSourceId").value = source.id;
  $("#authTitle").textContent = `${source.name}授权`;
  $("#authDescription").textContent = `${source.coverage}。仅保存凭据不会自动执行全文检索；还需配置可调用的授权接口地址，验证通过后才会进入扫描。`;
  $("#authType").innerHTML = (source.auth_types || ["api_token"])
    .map((type) => `<option value="${esc(type)}">${esc(authTypeLabel(type))}</option>`)
    .join("");
  $("#authSecret").value = "";
  $("#authEndpoint").value = source.credential?.endpoint || "";
  $("#authSubmit").textContent = source.credential?.configured ? "更新授权" : "保存授权";
  $("#revokeButton").style.display = source.credential?.configured ? "" : "none";
  updateAuthFields();
  $("#authModal").showModal();
  setTimeout(() => $("#authSecret").focus(), 50);
}

function authTypeLabel(type) {
  return {
    session_cookie: "浏览器 Session Cookie",
    api_token: "API Token",
    api_key: "API Key",
  }[type] || type;
}

function updateAuthFields() {
  const type = $("#authType").value;
  $("#endpointField").style.display = "";
  $("#authSecret").placeholder = type === "session_cookie"
    ? "粘贴已登录浏览器中该平台域名下的 Cookie，例如 key=value; key2=value2"
    : "粘贴授权 API Token 或 API Key";
}

async function submitAuth(event) {
  if (event.submitter?.value === "cancel") return;
  event.preventDefault();
  const sourceId = $("#authSourceId").value;
  const authType = $("#authType").value;
  const secret = $("#authSecret").value.trim();
  if (!secret) {
    toast("请填写授权凭据", true);
    return;
  }
  const button = $("#authSubmit");
  button.disabled = true;
  button.textContent = "保存中…";
  try {
    await api("/api/authorize", {
      method: "POST",
      body: JSON.stringify({
        source_id: sourceId,
        auth_type: authType,
        secret,
        endpoint: $("#authEndpoint").value.trim(),
      }),
    });
    $("#authModal").close();
    toast("授权凭据已保存在本机，连接器仍待平台验证");
    await loadState({ quiet: true });
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = "保存授权";
  }
}

async function revokeAuth() {
  const sourceId = $("#authSourceId").value;
  try {
    await api("/api/authorize/revoke", {
      method: "POST",
      body: JSON.stringify({ source_id: sourceId }),
    });
    $("#authModal").close();
    toast("本地授权凭据已撤销");
    await loadState({ quiet: true });
  } catch (error) {
    toast(error.message, true);
  }
}

let toastTimer = null;
function toast(message, isError = false) {
  const element = $("#toast");
  element.textContent = message;
  element.classList.toggle("error", isError);
  element.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => element.classList.remove("show"), 4200);
}

function bindEvents() {
  $("#scanButton").addEventListener("click", scanNow);
  $("#watchForm").addEventListener("submit", saveWatchTerms);
  $("#eventsTab").addEventListener("click", () => setTab("events"));
  $("#itemsTab").addEventListener("click", () => setTab("items"));
  $("#runsTab").addEventListener("click", () => setTab("runs"));
  $("#searchFilter").addEventListener("input", renderFeed);
  $("#riskFilter").addEventListener("change", renderFeed);
  $("#sourceFilter").addEventListener("change", renderFeed);
  $("#matchedOnly").addEventListener("change", renderFeed);

  $$(".quick-chip").forEach((button) => {
    button.addEventListener("click", () => {
      const input = $("#watchInput");
      const terms = input.value.split(/[,，\n;；]+/).map((term) => term.trim()).filter(Boolean);
      if (!terms.includes(button.dataset.term)) terms.push(button.dataset.term);
      input.value = terms.join("，");
      input.focus();
    });
  });

  document.addEventListener("click", (event) => {
    const openEvent = event.target.closest("[data-open-event]");
    if (openEvent) {
      openDetail(openEvent.dataset.openEvent);
      return;
    }

    const readArticle = event.target.closest("[data-read-article]");
    if (readArticle) {
      openArticle(readArticle.dataset.readArticle);
      return;
    }

    const prButton = event.target.closest("[data-pr-analysis]");
    if (prButton) {
      analyzeEventPr(prButton.dataset.prAnalysis, false);
      return;
    }

    const prRefresh = event.target.closest("[data-pr-refresh]");
    if (prRefresh) {
      analyzeEventPr(prRefresh.dataset.prRefresh, true);
      return;
    }

    const authButton = event.target.closest("[data-auth-source]");
    if (authButton) {
      openAuth(authButton.dataset.authSource);
      return;
    }

    const reviewButton = event.target.closest("[data-review]");
    if (reviewButton) {
      reviewItems([reviewButton.dataset.review], reviewButton.dataset.status);
      return;
    }

    const openRun = event.target.closest("[data-open-run]");
    if (openRun) {
      openRunDetail(openRun.dataset.openRun);
      return;
    }

    const groupButton = event.target.closest("[data-review-group]");
    if (groupButton) {
      const detailEvent = app.eventMap.get(groupButton.dataset.reviewGroup);
      if (detailEvent) reviewItems(detailEvent.item_ids, groupButton.dataset.status);
    }
  });

  $("#authForm").addEventListener("submit", submitAuth);
  $("#importArticleButton").addEventListener("click", openImportArticle);
  $("#importForm").addEventListener("submit", submitImportArticle);
  $("#authType").addEventListener("change", updateAuthFields);
  $("#revokeButton").addEventListener("click", revokeAuth);
  $("#detailClose").addEventListener("click", () => $("#detailModal").close());
  $("#articleClose").addEventListener("click", () => $("#articleModal").close());

  [$("#authModal"), $("#importModal"), $("#articleModal"), $("#detailModal")].forEach((dialog) => {
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();
    });
  });
}

async function init() {
  bindEvents();
  try {
    await loadState();
  } catch {
    // The toast and connection state already surface the failure.
  }
  setInterval(() => loadState({ quiet: true }).catch(() => {}), 15000);
}

init();
