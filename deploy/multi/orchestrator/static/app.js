// chat2api Orchestrator 前端
// 原生 fetch + 简单 DOM 操作，无框架

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

function getCookie(name) {
    return document.cookie.split('; ')
        .find(r => r.startsWith(name + '='))?.split('=')[1] || '';
}

function csrf() {
    return getCookie('orch_csrf');
}

async function api(method, path, body) {
    const opts = { method, headers: {} };
    if (body !== undefined) {
        opts.headers['Content-Type'] = 'application/json';
        opts.body = JSON.stringify(body);
    }
    // 所有请求都带 CSRF 头：少数 GET（如 /api/secrets/{slug} reveal）也走 CSRF 校验
    const c = csrf();
    if (c) opts.headers['X-CSRF-Token'] = c;
    const r = await fetch('.' + path, opts);
    if (r.status === 401) {
        location.href = './login';
        return;
    }
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(formatApiError(data.detail) || `HTTP ${r.status}`);
    return data;
}

function formatApiError(detail) {
    if (!detail) return '';
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) {
        return detail.map((item) => {
            if (typeof item === 'string') return item;
            const loc = Array.isArray(item.loc) ? item.loc.join('.') : '';
            return [loc, item.msg].filter(Boolean).join(': ');
        }).join('\n');
    }
    if (typeof detail === 'object') {
        return detail.message || detail.msg || JSON.stringify(detail);
    }
    return String(detail);
}

function toast(msg, isErr = false) {
    const el = $('#toast');
    el.textContent = msg;
    el.classList.remove('hidden', 'bg-gray-900', 'bg-red-600');
    el.classList.add(isErr ? 'bg-red-600' : 'bg-gray-900');
    setTimeout(() => el.classList.add('hidden'), 3000);
}

function fmtUptime(sec) {
    if (sec == null) return '-';
    if (sec < 60) return sec + 's';
    if (sec < 3600) return Math.floor(sec / 60) + 'm';
    if (sec < 86400) return Math.floor(sec / 3600) + 'h';
    return Math.floor(sec / 86400) + 'd';
}

function fmtCookieAge(ts) {
    if (!ts) return '<span class="text-gray-400">未刷新</span>';
    const age = Math.floor(Date.now() / 1000 - ts);
    let txt, color;
    if (age < 600) { txt = age + 's 前'; color = 'text-green-600'; }
    else if (age < 3600) { txt = Math.floor(age / 60) + 'm 前'; color = 'text-green-600'; }
    else if (age < 86400) { txt = Math.floor(age / 3600) + 'h 前'; color = 'text-yellow-600'; }
    else { txt = Math.floor(age / 86400) + 'd 前'; color = 'text-red-600'; }
    return `<span class="${color}">${txt}</span>`;
}

function healthBadge(state, health) {
    if (state !== 'running') {
        return `<span><span class="dot dot-na"></span>${state}</span>`;
    }
    if (health === 'healthy') return `<span><span class="dot dot-healthy"></span>healthy</span>`;
    if (health === 'unhealthy') return `<span><span class="dot dot-unhealthy"></span>unhealthy</span>`;
    if (health === 'starting') return `<span><span class="dot dot-starting"></span>starting</span>`;
    return `<span><span class="dot dot-na"></span>${health}</span>`;
}

function escapeHtml(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({
        '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[c]));
}

function fmtNum(n) {
    const value = Number(n || 0);
    if (value >= 1000000) return (value / 1000000).toFixed(value >= 10000000 ? 0 : 2) + 'M';
    if (value >= 1000) return value.toLocaleString();
    return String(value);
}

function fmtMs(ms) {
    const value = Number(ms || 0);
    if (value >= 1000) return (value / 1000).toFixed(value >= 10000 ? 1 : 2) + 's';
    return Math.round(value) + 'ms';
}

function parseUsageTs(ts) {
    const t = Date.parse(ts || '');
    return Number.isFinite(t) ? t : 0;
}

/**
 * 紧凑型行内模型 chip 渲染：最多展示 maxVisible 个，超出显示 "+N"。
 * 入参：models 可以是 ["gpt-5", ...] 或 [{id, source}, ...]
 */
function renderInlineModels(models, maxVisible = 4) {
    if (!models || !models.length) {
        return '<div class="mt-1 text-xs text-gray-400">无可用模型</div>';
    }
    const ids = models.map(m => (typeof m === 'string') ? m : (m && m.id));
    const visible = ids.slice(0, maxVisible);
    const more = ids.length - visible.length;
    const chips = visible.map(id => `<span class="model-chip">${escapeHtml(id)}</span>`).join('');
    const moreBadge = more > 0
        ? `<span class="model-chip" style="background:#f3f4f6;color:#6b7280;border-color:#e5e7eb">+${more}</span>`
        : '';
    return `<div class="flex flex-wrap gap-1 mt-1 max-w-md">${chips}${moreBadge}</div>`;
}

let latestInstances = [];
let selectedSlug = '';
let instanceSearchQuery = '';
let activePanel = 'instances';
let usageRecords = [];
let usageFilteredRecords = [];
let usageLoaded = false;

function switchPanel(panel) {
    activePanel = panel || 'instances';
    $$('[data-panel-body]').forEach(el => {
        el.classList.toggle('hidden', el.dataset.panelBody !== activePanel);
    });
    $$('.orch-nav-item[data-panel]').forEach(btn => {
        btn.classList.toggle('orch-nav-active', btn.dataset.panel === activePanel);
    });
    if (activePanel === 'usage' && !usageLoaded) {
        loadUsage();
    }
}

$$('.orch-nav-item[data-panel]').forEach(btn => {
    btn.addEventListener('click', () => switchPanel(btn.dataset.panel));
});

function isHealthy(it) {
    return it.state === 'running' && it.health === 'healthy';
}

function isCookieFresh(it) {
    if (!it.cookie_last_success_at) return false;
    return Math.floor(Date.now() / 1000 - it.cookie_last_success_at) < 3600;
}

function instanceInitial(it) {
    return String(it.note || it.slug || 'A').trim().slice(0, 1).toUpperCase();
}

function statusPill(it) {
    if (isHealthy(it)) {
        return '<span class="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-700"><span class="status-dot bg-emerald-500"></span>Healthy</span>';
    }
    if (it.state === 'running') {
        return `<span class="inline-flex items-center gap-1.5 rounded-full bg-orange-50 px-2.5 py-1 text-xs font-semibold text-orange-700"><span class="status-dot bg-orange-500"></span>${escapeHtml(it.health || 'running')}</span>`;
    }
    return `<span class="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-600"><span class="status-dot bg-slate-400"></span>${escapeHtml(it.state || 'absent')}</span>`;
}

function planPill(it) {
    const label = it.plan_label || it.plan_type || '未知';
    return `<span class="inline-flex rounded-lg border border-blue-100 bg-blue-50 px-2 py-1 text-xs font-semibold text-blue-700">${escapeHtml(label)}</span>`;
}

function getFilteredInstances() {
    const q = instanceSearchQuery.trim().toLowerCase();
    if (!q) return latestInstances;
    return latestInstances.filter(it => [
        it.slug,
        it.note,
        it.proxy_masked,
        it.exit_ip,
        it.state,
        it.health,
        it.plan_label,
        it.plan_type,
        ...(it.models || []),
    ].some(v => String(v || '').toLowerCase().includes(q)));
}

function renderMetrics(instances) {
    const total = instances.length;
    const healthy = instances.filter(isHealthy).length;
    const degraded = total - healthy;
    const proxied = instances.filter(it => it.has_proxy).length;
    const models = instances.reduce((sum, it) => sum + ((it.models || []).length), 0);
    const fresh = instances.filter(isCookieFresh).length;
    const pairs = [
        ['#metric-total', total],
        ['#metric-healthy', healthy],
        ['#metric-degraded', degraded],
        ['#metric-proxy', proxied],
        ['#metric-models', models],
        ['#metric-cookie', fresh],
    ];
    for (const [sel, val] of pairs) {
        const el = $(sel);
        if (el) el.textContent = val;
    }
}

function renderDetail(it) {
    const empty = $('#detail-empty');
    const body = $('#detail-body');
    if (!empty || !body) return;
    if (!it) {
        empty.classList.remove('hidden');
        body.classList.add('hidden');
        body.innerHTML = '';
        return;
    }
    empty.classList.add('hidden');
    body.classList.remove('hidden');
    body.innerHTML = `
        <div class="flex items-start gap-3">
            <div class="grid h-12 w-12 place-items-center rounded-2xl bg-gradient-to-br from-blue-500 to-cyan-400 text-lg font-semibold text-white">${escapeHtml(instanceInitial(it))}</div>
            <div class="min-w-0">
                <div class="orch-detail-title truncate text-base">${escapeHtml(it.note || it.slug)}</div>
                <div class="mt-1 font-mono text-xs text-slate-400">${escapeHtml(it.slug)}</div>
            </div>
        </div>
        <div class="mt-5 flex flex-wrap gap-2">${statusPill(it)}${planPill(it)}</div>
        <div class="mt-5 space-y-3 text-sm">
            <div class="rounded-2xl bg-slate-50 p-3">
                <div class="text-xs font-semibold text-slate-400">代理</div>
                <div class="mt-1 break-all font-mono text-xs text-slate-600">${escapeHtml(it.proxy_masked || '未绑定')}</div>
            </div>
            <div class="grid grid-cols-2 gap-3">
                <div class="rounded-2xl bg-slate-50 p-3"><div class="text-xs font-semibold text-slate-400">出口 IP</div><div class="orch-label-strong mt-1 text-slate-800">${escapeHtml(it.exit_ip || '?')}</div></div>
                <div class="rounded-2xl bg-slate-50 p-3"><div class="text-xs font-semibold text-slate-400">运行时长</div><div class="orch-label-strong mt-1 text-slate-800">${fmtUptime(it.uptime_seconds)}</div></div>
            </div>
            <div class="rounded-2xl bg-slate-50 p-3">
                <div class="text-xs font-semibold text-slate-400">Cookie 鲜度</div>
                <div class="orch-label-strong mt-1 text-sm">${fmtCookieAge(it.cookie_last_success_at)}</div>
            </div>
            <div class="rounded-2xl bg-slate-50 p-3">
                <div class="text-xs font-semibold text-slate-400">可用模型</div>
                ${renderInlineModels(it.models, 12)}
            </div>
        </div>
        <div class="mt-5 grid grid-cols-2 gap-2">
            <button class="row-action-btn border border-indigo-100 bg-indigo-50 text-indigo-700" data-action="invoke" data-slug="${escapeHtml(it.slug)}">调用</button>
            <button class="row-action-btn border border-blue-100 bg-blue-50 text-blue-700" data-action="secret" data-slug="${escapeHtml(it.slug)}">凭证</button>
            <button class="row-action-btn border border-slate-200 bg-white text-slate-700" data-action="edit" data-slug="${escapeHtml(it.slug)}" data-proxy="${escapeHtml(it.proxy_masked || '')}" data-note="${escapeHtml(it.note || '')}">编辑</button>
            <button class="row-action-btn border border-orange-100 bg-orange-50 text-orange-700" data-action="restart" data-slug="${escapeHtml(it.slug)}">重启</button>
            ${it.state === 'running'
                ? `<button class="row-action-btn border border-yellow-100 bg-yellow-50 text-yellow-700" data-action="stop" data-slug="${escapeHtml(it.slug)}">停止</button>`
                : `<button class="row-action-btn border border-emerald-100 bg-emerald-50 text-emerald-700" data-action="start" data-slug="${escapeHtml(it.slug)}">启动</button>`}
            <button class="row-action-btn border border-red-100 bg-red-50 text-red-600" data-action="delete" data-slug="${escapeHtml(it.slug)}">删除</button>
        </div>
    `;
    $$('#detail-body button').forEach(btn => {
        btn.addEventListener('click', () => onRowAction(btn.dataset));
    });
}

function selectInstance(slug) {
    selectedSlug = slug || '';
    renderRows(getFilteredInstances(), false);
    renderDetail(latestInstances.find(it => it.slug === selectedSlug));
}

function renderRows(instances, updateDetail = true) {
    const tbody = $('#tbody');
    if (!tbody) return;
    const count = $('#table-count');
    if (count) count.textContent = `${instances.length} / ${latestInstances.length} 个实例`;
    if (!instances.length) {
        tbody.innerHTML = '<tr><td colspan="8" class="px-4 py-12 text-center text-slate-400">暂无匹配实例，清空搜索或新增账号。</td></tr>';
        if (updateDetail) renderDetail(null);
        return;
    }
    if (!selectedSlug || !latestInstances.some(it => it.slug === selectedSlug)) {
        selectedSlug = instances[0].slug;
    }
    tbody.innerHTML = instances.map(it => {
        const selected = it.slug === selectedSlug;
        return `
        <tr class="instance-row cursor-pointer border-t border-slate-100 ${selected ? 'bg-blue-50/70' : 'bg-white'}" data-slug="${escapeHtml(it.slug)}">
            <td class="py-4 pl-4 pr-3">
                <div class="flex items-center gap-3">
                    <div class="grid h-10 w-10 shrink-0 place-items-center rounded-2xl bg-gradient-to-br from-blue-500 to-cyan-400 text-sm font-semibold text-white shadow-sm">${escapeHtml(instanceInitial(it))}</div>
                    <div class="min-w-0"><div class="truncate orch-label-strong text-slate-950">${escapeHtml(it.note || it.slug)}</div><div class="mt-1 font-mono text-xs text-slate-400">${escapeHtml(it.slug)}</div></div>
                </div>
            </td>
            <td class="px-3 py-4"><div class="flex flex-wrap items-center gap-2">${planPill(it)}</div>${renderInlineModels(it.models, 3)}</td>
            <td class="px-3 py-4 max-w-56 truncate font-mono text-xs text-slate-500">${escapeHtml(it.proxy_masked || '-')}</td>
            <td class="px-3 py-4">${statusPill(it)}</td>
            <td class="px-3 py-4 font-mono text-xs text-slate-600">${escapeHtml(it.exit_ip || '?')}</td>
            <td class="px-3 py-4 text-xs">${fmtCookieAge(it.cookie_last_success_at)}</td>
            <td class="px-3 py-4 text-xs text-slate-500">${fmtUptime(it.uptime_seconds)}</td>
            <td class="py-4 pl-3 pr-4 text-right whitespace-nowrap">
                <button class="row-action-btn text-indigo-600" data-action="invoke" data-slug="${escapeHtml(it.slug)}">调用</button>
                <button class="row-action-btn text-blue-600" data-action="secret" data-slug="${escapeHtml(it.slug)}">凭证</button>
                <button class="row-action-btn text-slate-700" data-action="edit" data-slug="${escapeHtml(it.slug)}" data-proxy="${escapeHtml(it.proxy_masked || '')}" data-note="${escapeHtml(it.note || '')}">编辑</button>
                <button class="row-action-btn text-orange-600" data-action="restart" data-slug="${escapeHtml(it.slug)}">重启</button>
                ${it.state === 'running'
                    ? `<button class="row-action-btn text-yellow-600" data-action="stop" data-slug="${escapeHtml(it.slug)}">停止</button>`
                    : `<button class="row-action-btn text-green-600" data-action="start" data-slug="${escapeHtml(it.slug)}">启动</button>`}
                <button class="row-action-btn text-red-600" data-action="delete" data-slug="${escapeHtml(it.slug)}">删除</button>
            </td>
        </tr>`;
    }).join('');

    $$('#tbody button').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            onRowAction(btn.dataset);
        });
    });
    $$('#tbody .instance-row').forEach(row => {
        row.addEventListener('click', () => selectInstance(row.dataset.slug));
    });
    if (updateDetail) renderDetail(latestInstances.find(it => it.slug === selectedSlug));
}

async function loadStatus() {
    try {
        const data = await api('GET', '/api/status');
        latestInstances = data.instances || [];
        renderMetrics(latestInstances);
        renderRows(getFilteredInstances());
        const serverTime = new Date(data.server_time * 1000);
        const statusText = `共 ${latestInstances.length} 个实例 · 服务器时间 ${serverTime.toLocaleTimeString()}`;
        $('#server-status').textContent = statusText;
        const serverTimeEl = $('#server-time');
        if (serverTimeEl) serverTimeEl.textContent = serverTime.toLocaleString('zh-CN', { hour12: false });
    } catch (e) {
        toast('加载状态失败：' + e.message, true);
    }
}

const instanceSearchInput = $('#instance-search');
if (instanceSearchInput) {
    instanceSearchInput.addEventListener('input', () => {
        instanceSearchQuery = instanceSearchInput.value || '';
        renderRows(getFilteredInstances());
    });
}
const clearDetailButton = $('#btn-clear-detail');
if (clearDetailButton) {
    clearDetailButton.addEventListener('click', () => selectInstance(''));
}

// ---------- 模态 ----------

let modalMode = 'add';   // 'add' | 'edit'
let modalSlug = '';

function openModal(mode, prefill = {}) {
    modalMode = mode;
    modalSlug = prefill.slug || '';
    $('#modal-title').textContent = mode === 'add' ? '新增账号' : `编辑 ${prefill.slug}`;
    $('#f-slug').value = prefill.slug || '';
    $('#f-slug').disabled = mode === 'edit';
    $('#slug-help').textContent = mode === 'edit'
        ? 'slug 是容器路径/数据目录 ID，创建后不可改；列表会优先显示备注'
        : '小写字母 / 数字 / 连字符，最多 16 位';
    $('#f-proxy').value = mode === 'edit' ? '' : (prefill.proxy_url || '');
    $('#f-proxy').placeholder = mode === 'edit'
        ? `当前：${prefill.proxy || '(无)'}; 留空则不变`
        : 'socks5://user:pass@host:port';
    $('#f-note').value = prefill.note || '';
    $('#modal-error').classList.add('hidden');
    $('#modal').classList.remove('hidden');
    $('#modal').classList.add('flex');
}

function closeModal() {
    $('#modal').classList.add('hidden');
    $('#modal').classList.remove('flex');
}

$('#btn-add').addEventListener('click', () => openModal('add'));
$('#btn-cancel').addEventListener('click', closeModal);
$('#btn-refresh').addEventListener('click', () => loadStatus());

$('#modal-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const slug = $('#f-slug').value.trim();
    const proxy_url = $('#f-proxy').value.trim();
    const note = $('#f-note').value.trim();
    $('#btn-submit').disabled = true;
    $('#btn-submit').textContent = '处理中...';
    try {
        if (modalMode === 'add') {
            await api('POST', '/api/accounts', { slug, proxy_url, note });
            toast('新增成功，等待容器启动...');
        } else {
            const body = { note };
            if (proxy_url) body.proxy_url = proxy_url;
            await api('PATCH', '/api/accounts/' + encodeURIComponent(modalSlug), body);
            toast('编辑成功，正在重建...');
        }
        closeModal();
        await loadStatus();
    } catch (e) {
        $('#modal-error').textContent = e.message;
        $('#modal-error').classList.remove('hidden');
    } finally {
        $('#btn-submit').disabled = false;
        $('#btn-submit').textContent = '保存';
    }
});

// ---------- 行操作 ----------

async function onRowAction({ action, slug, proxy, note }) {
    if (action === 'edit') {
        openModal('edit', { slug, proxy, note });
        return;
    }
    if (action === 'secret') {
        await showSecret(slug);
        return;
    }
    if (action === 'invoke') {
        await openInvokeModal(slug);
        return;
    }
    if (action === 'delete') {
        if (!confirm(`确认删除 ${slug}？\n容器将被销毁，data/${slug}/ 会保留。`)) return;
        try {
            await api('DELETE', '/api/accounts/' + encodeURIComponent(slug));
            toast(`已删除 ${slug}`);
            await loadStatus();
        } catch (e) {
            toast('删除失败：' + e.message, true);
        }
        return;
    }
    if (['start', 'stop', 'restart'].includes(action)) {
        try {
            await api('POST', `/api/instances/${encodeURIComponent(slug)}/${action}`);
            toast(`${action} ${slug} 已发出`);
            setTimeout(loadStatus, 1500);
        } catch (e) {
            toast(`${action} 失败：` + e.message, true);
        }
    }
}

// ---------- 凭证查看 ----------

async function showSecret(slug) {
    if (!confirm(`查看 ${slug} 的明文凭证？\n该操作会写入审计日志。`)) return;
    try {
        const d = await api('GET', '/api/secrets/' + encodeURIComponent(slug));
        const origin = location.origin;   // e.g. http://107.172.96.31:60403
        const adminUrl = `${origin}/${d.slug}/admin/login`;
        const apiUrl   = `${origin}/${d.slug}/v1/chat/completions`;
        $('#secret-body').innerHTML = `
            <div class="text-xs text-gray-500 mb-2">仅展示用户侧需要的凭证；后端 API_PREFIX 由 nginx 自动改写，不应直接访问。</div>
            <div><span class="font-semibold">slug:</span> <code class="bg-gray-100 px-1">${escapeHtml(d.slug)}</code></div>
            <div><span class="font-semibold">AUTHORIZATION:</span> <code class="bg-gray-100 px-1 break-all">${escapeHtml(d.AUTHORIZATION)}</code></div>
            <div><span class="font-semibold">ADMIN_PASSWORD:</span> <code class="bg-gray-100 px-1 break-all">${escapeHtml(d.ADMIN_PASSWORD)}</code></div>
            <div><span class="font-semibold">PROXY_URL:</span> <code class="bg-gray-100 px-1 break-all">${escapeHtml(d.PROXY_URL || '(无)')}</code></div>
            <div class="pt-3 mt-3 border-t space-y-2">
                <div>
                    <div class="text-xs text-gray-500 mb-1">① Admin 后台（粘 cookie 用）</div>
                    <a class="text-blue-600 underline break-all" href="${escapeHtml(adminUrl)}" target="_blank" rel="noopener">${escapeHtml(adminUrl)}</a>
                    <div class="text-xs text-gray-400">用上面 ADMIN_PASSWORD 登录</div>
                </div>
                <div>
                    <div class="text-xs text-gray-500 mb-1">② API 调用示例</div>
                    <code class="bg-gray-100 px-1 block break-all text-xs">curl ${escapeHtml(apiUrl)} -H "Authorization: Bearer ${escapeHtml(d.AUTHORIZATION)}" -H "Content-Type: application/json" -d '{"model":"gpt-5-5","messages":[{"role":"user","content":"hi"}]}'</code>
                </div>
            </div>
        `;
        $('#modal-secret').classList.remove('hidden');
        $('#modal-secret').classList.add('flex');
    } catch (e) {
        toast('获取凭证失败：' + e.message, true);
    }
}

$('#btn-close-secret').addEventListener('click', () => {
    $('#modal-secret').classList.add('hidden');
    $('#modal-secret').classList.remove('flex');
    $('#secret-body').innerHTML = '';   // 立即清屏
});

// ---------- 统一 API ----------

async function showUnifiedApi() {
    if (!confirm('查看统一 API Key？\n该 Key 可调用所有实例，请勿泄露。')) return;
    try {
        const d = await api('GET', '/api/unified');
        const baseUrl = location.origin + (d.base_path || '/v1');
        const chatUrl = location.origin + (d.chat_completions_path || '/v1/chat/completions');
        const responsesUrl = location.origin + (d.responses_path || '/v1/responses');
        const compactUrl = location.origin + (d.responses_compact_path || '/v1/responses/compact');
        $('#unified-base-url').textContent = baseUrl;
        $('#unified-api-key').textContent = d.api_key;
        $('#unified-chat-url').textContent = chatUrl;
        $('#unified-responses-url').textContent = responsesUrl;
        $('#unified-compact-url').textContent = compactUrl;
        $('#unified-curl').textContent =
`curl ${chatUrl} \\
  -H "Authorization: Bearer ${d.api_key}" \\
  -H "Content-Type: application/json" \\
  -d '{"model":"gpt-5-5","messages":[{"role":"user","content":"你好"}]}'

curl ${responsesUrl} \\
  -H "Authorization: Bearer ${d.api_key}" \\
  -H "Content-Type: application/json" \\
  -d '{"model":"gpt-5-5","input":"你好"}'`;
        $('#unified-strategy').textContent = d.strategy || '';
        $('#modal-unified-api').classList.remove('hidden');
        $('#modal-unified-api').classList.add('flex');
    } catch (e) {
        toast('获取统一 API 失败：' + e.message, true);
    }
}

$('#btn-unified-api').addEventListener('click', showUnifiedApi);
$('#btn-close-unified-api').addEventListener('click', () => {
    $('#modal-unified-api').classList.add('hidden');
    $('#modal-unified-api').classList.remove('flex');
    $('#unified-api-key').textContent = '';
    $('#unified-curl').textContent = '';
});

// ---------- 管理中心 ----------

async function openAdminCenter() {
    $('#admin-center-error').classList.add('hidden');
    $('#admin-center-error').textContent = '';
    $('#admin-current-password').value = '';
    $('#admin-new-password').value = '';
    $('#modal-admin-center').classList.remove('hidden');
    $('#modal-admin-center').classList.add('flex');
    try {
        const d = await api('GET', '/api/orchestrator/account');
        $('#admin-username').value = d.username || 'admin';
    } catch (e) {
        $('#admin-center-error').textContent = e.message;
        $('#admin-center-error').classList.remove('hidden');
    }
}

function closeAdminCenter() {
    $('#modal-admin-center').classList.add('hidden');
    $('#modal-admin-center').classList.remove('flex');
}

$('#btn-admin-center').addEventListener('click', openAdminCenter);
$('#btn-close-admin-center').addEventListener('click', closeAdminCenter);
$('#btn-cancel-admin-center').addEventListener('click', closeAdminCenter);

$('#admin-center-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = $('#btn-save-admin-center');
    btn.disabled = true;
    btn.textContent = '保存中...';
    $('#admin-center-error').classList.add('hidden');
    try {
        await api('PATCH', '/api/orchestrator/account', {
            username: $('#admin-username').value.trim(),
            current_password: $('#admin-current-password').value,
            new_password: $('#admin-new-password').value,
        });
        toast('已更新，请重新登录');
        setTimeout(() => { location.href = './login'; }, 600);
    } catch (e) {
        $('#admin-center-error').textContent = e.message;
        $('#admin-center-error').classList.remove('hidden');
    } finally {
        btn.disabled = false;
        btn.textContent = '保存';
    }
});

// ---------- 审计 ----------

$('#btn-audit').addEventListener('click', async () => {
    try {
        const d = await api('GET', '/api/audit?limit=200');
        $('#audit-body').innerHTML = d.records.map(r => `
            <tr class="border-t border-gray-100">
                <td class="px-2 py-1 kbd-row text-gray-600">${escapeHtml(r.ts || '')}</td>
                <td class="px-2 py-1 kbd-row">${escapeHtml(r.ip || '')}</td>
                <td class="px-2 py-1 font-medium">${escapeHtml(r.action || '')}</td>
                <td class="px-2 py-1 kbd-row">${escapeHtml(r.slug || '-')}</td>
                <td class="px-2 py-1">${r.ok ? '<span class="text-green-600">✓</span>' : '<span class="text-red-600">✗</span>'}</td>
                <td class="px-2 py-1 text-gray-500">${escapeHtml(JSON.stringify({...r, ts:undefined, ip:undefined, action:undefined, slug:undefined, ok:undefined, actor:undefined}).replace(/^\{\}$/, ''))}</td>
            </tr>
        `).join('');
        $('#modal-audit').classList.remove('hidden');
        $('#modal-audit').classList.add('flex');
    } catch (e) {
        toast('加载审计失败：' + e.message, true);
    }
});

$('#btn-close-audit').addEventListener('click', () => {
    $('#modal-audit').classList.add('hidden');
    $('#modal-audit').classList.remove('flex');
});

// ---------- 诊断日志 ----------

let logTargetsLoaded = false;

async function loadLogTargets() {
    const d = await api('GET', '/api/log-targets');
    const targets = d.targets || [];
    $('#log-target').innerHTML = targets.map(t =>
        `<option value="${escapeHtml(t.id)}">${escapeHtml(t.label)} · ${escapeHtml(t.container)}</option>`
    ).join('');
    logTargetsLoaded = true;
}

async function refreshLogs() {
    const target = $('#log-target').value || 'orchestrator';
    const tail = $('#log-tail').value || '200';
    $('#logs-body').textContent = '加载中...';
    $('#logs-meta').textContent = '';
    try {
        const d = await api('GET', `/api/logs?target=${encodeURIComponent(target)}&tail=${encodeURIComponent(tail)}`);
        $('#logs-body').textContent = d.logs || '(无日志输出)';
        $('#logs-meta').textContent = `${d.ok ? 'OK' : '异常'} · ${d.container || target} · 最近 ${d.tail || tail} 行`;
        if (!d.ok) toast('日志目标返回异常，内容已显示', true);
    } catch (e) {
        $('#logs-body').textContent = '加载日志失败：' + e.message;
        $('#logs-meta').textContent = '加载失败';
        toast('加载日志失败：' + e.message, true);
    }
}

async function openLogsModal() {
    $('#modal-logs').classList.remove('hidden');
    $('#modal-logs').classList.add('flex');
    try {
        if (!logTargetsLoaded) await loadLogTargets();
        await refreshLogs();
    } catch (e) {
        $('#logs-body').textContent = '加载日志失败：' + e.message;
        toast('加载日志失败：' + e.message, true);
    }
}

$('#btn-diag-logs').addEventListener('click', openLogsModal);
$('#btn-close-logs').addEventListener('click', () => {
    $('#modal-logs').classList.add('hidden');
    $('#modal-logs').classList.remove('flex');
});
$('#btn-refresh-logs').addEventListener('click', refreshLogs);
$('#log-target').addEventListener('change', refreshLogs);
$('#log-tail').addEventListener('change', refreshLogs);

// ---------- 使用日志 ----------

function usageInRange(record, range) {
    if (!range || range === 'all') return true;
    const seconds = Number(range);
    if (!seconds) return true;
    const ts = parseUsageTs(record.ts);
    if (!ts) return true;
    return Date.now() - ts <= seconds * 1000;
}

function uniqueSorted(values) {
    return Array.from(new Set(values.filter(Boolean).map(v => String(v)))).sort();
}

function syncUsageFilterOptions() {
    const slugValue = $('#usage-slug').value;
    const modelValue = $('#usage-model').value;
    const endpointValue = $('#usage-endpoint').value;
    const slugs = uniqueSorted(usageRecords.map(r => r.slug));
    const models = uniqueSorted(usageRecords.map(r => r.model));
    const endpoints = uniqueSorted(usageRecords.map(r => r.endpoint || String(r.path || '').split('/').pop()));
    $('#usage-slug').innerHTML = '<option value="">全部容器</option>' + slugs.map(v => `<option value="${escapeHtml(v)}">${escapeHtml(v)}</option>`).join('');
    $('#usage-model').innerHTML = '<option value="">全部模型</option>' + models.map(v => `<option value="${escapeHtml(v)}">${escapeHtml(v)}</option>`).join('');
    $('#usage-endpoint').innerHTML = '<option value="">全部接口</option>' + endpoints.map(v => `<option value="${escapeHtml(v)}">${escapeHtml(v)}</option>`).join('');
    $('#usage-slug').value = slugs.includes(slugValue) ? slugValue : '';
    $('#usage-model').value = models.includes(modelValue) ? modelValue : '';
    $('#usage-endpoint').value = endpoints.includes(endpointValue) ? endpointValue : '';
}

function applyUsageFilters() {
    const range = $('#usage-range').value;
    const slug = $('#usage-slug').value;
    const model = $('#usage-model').value;
    const endpoint = $('#usage-endpoint').value;
    const ok = $('#usage-ok').value;
    const stream = $('#usage-stream').value;
    const q = ($('#usage-search').value || '').trim().toLowerCase();
    usageFilteredRecords = usageRecords.filter(r => {
        if (!usageInRange(r, range)) return false;
        if (slug && r.slug !== slug) return false;
        if (model && r.model !== model) return false;
        const rowEndpoint = r.endpoint || String(r.path || '').split('/').pop();
        if (endpoint && rowEndpoint !== endpoint) return false;
        if (ok && String(Boolean(r.ok)) !== ok) return false;
        if (stream && String(Boolean(r.stream)) !== stream) return false;
        if (q) {
            const haystack = [
                r.request_id, r.slug, r.model, r.path, rowEndpoint, r.error, r.status
            ].join(' ').toLowerCase();
            if (!haystack.includes(q)) return false;
        }
        return true;
    });
    renderUsage();
}

function summarizeUsage(records) {
    const total = records.length;
    const success = records.filter(r => r.ok).length;
    const failed = total - success;
    const prompt = records.reduce((sum, r) => sum + Number(r.prompt_tokens || 0), 0);
    const completion = records.reduce((sum, r) => sum + Number(r.completion_tokens || 0), 0);
    const tokens = records.reduce((sum, r) => sum + Number(r.total_tokens || 0), 0);
    const durations = records.map(r => Number(r.duration_ms || 0)).filter(n => Number.isFinite(n));
    const avg = durations.length ? Math.round(durations.reduce((a, b) => a + b, 0) / durations.length) : 0;
    const sorted = [...durations].sort((a, b) => a - b);
    const p95 = sorted.length ? sorted[Math.max(0, Math.ceil(sorted.length * 0.95) - 1)] : 0;
    const bySlug = {};
    for (const r of records) {
        const slug = r.slug || '-';
        if (!bySlug[slug]) bySlug[slug] = { slug, requests: 0, tokens: 0, errors: 0 };
        bySlug[slug].requests += 1;
        bySlug[slug].tokens += Number(r.total_tokens || 0);
        if (!r.ok) bySlug[slug].errors += 1;
    }
    const slugs = Object.values(bySlug).sort((a, b) => (b.tokens - a.tokens) || (b.requests - a.requests));
    return {
        total, success, failed, prompt, completion, tokens, avg, p95,
        successRate: total ? (success * 100 / total).toFixed(1) : '0',
        topSlug: slugs[0]?.slug || '-',
        slugs,
    };
}

function renderUsageMetrics(summary) {
    $('#usage-total').textContent = fmtNum(summary.total);
    $('#usage-success-rate').textContent = `${summary.successRate}%`;
    $('#usage-success-note').textContent = `${fmtNum(summary.success)} 成功`;
    $('#usage-tokens').textContent = fmtNum(summary.tokens);
    $('#usage-tokens-note').textContent = `prompt ${fmtNum(summary.prompt)} · output ${fmtNum(summary.completion)}`;
    $('#usage-avg-duration').textContent = fmtMs(summary.avg);
    $('#usage-p95-duration').textContent = `p95 ${fmtMs(summary.p95)}`;
    $('#usage-top-slug').textContent = summary.topSlug;
    $('#usage-failed').textContent = fmtNum(summary.failed);
}

function buildUsageTimeline(records) {
    const buckets = new Map();
    for (const r of records) {
        const ts = parseUsageTs(r.ts);
        if (!ts) continue;
        const d = new Date(ts);
        const key = `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:00`;
        const row = buckets.get(key) || { key, requests: 0, tokens: 0, duration: 0, count: 0 };
        row.requests += 1;
        row.tokens += Number(r.total_tokens || 0);
        row.duration += Number(r.duration_ms || 0);
        row.count += 1;
        buckets.set(key, row);
    }
    return Array.from(buckets.values()).sort((a, b) => a.key.localeCompare(b.key)).slice(-24).map(row => ({
        ...row,
        avg: row.count ? Math.round(row.duration / row.count) : 0,
    }));
}

function pointsFor(values, width, height, maxValue) {
    if (!values.length) return '';
    const max = maxValue || Math.max(...values, 1);
    return values.map((v, i) => {
        const x = values.length === 1 ? width : i * (width / (values.length - 1));
        const y = height - ((v || 0) / max) * (height - 18) - 9;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(' ');
}

function renderUsageTrend(records) {
    const el = $('#usage-trend');
    const data = buildUsageTimeline(records);
    if (!data.length) {
        el.innerHTML = '<div class="flex h-full min-h-[220px] items-center justify-center text-sm text-slate-400">暂无趋势数据</div>';
        return;
    }
    const width = 760;
    const height = 190;
    const req = data.map(d => d.requests);
    const tokens = data.map(d => d.tokens);
    const avg = data.map(d => d.avg);
    el.innerHTML = `
        <svg viewBox="0 0 ${width} ${height}" class="h-[220px] w-full">
            <polyline points="${pointsFor(req, width, height, Math.max(...req, 1))}" fill="none" stroke="#2563eb" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"></polyline>
            <polyline points="${pointsFor(tokens, width, height, Math.max(...tokens, 1))}" fill="none" stroke="#0f766e" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"></polyline>
            <polyline points="${pointsFor(avg, width, height, Math.max(...avg, 1))}" fill="none" stroke="#f59e0b" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"></polyline>
            <text x="8" y="22" fill="#64748b" font-size="12">${escapeHtml(data[0].key)}</text>
            <text x="${width - 92}" y="${height - 12}" fill="#64748b" font-size="12">${escapeHtml(data[data.length - 1].key)}</text>
        </svg>
    `;
}

function renderUsageSlugBars(summary) {
    const rows = summary.slugs.slice(0, 8);
    const max = Math.max(...rows.map(r => r.tokens), 1);
    $('#usage-slug-bars').innerHTML = rows.length ? rows.map(row => `
        <div>
            <div class="mb-1 flex items-center justify-between gap-3 text-xs">
                <span class="font-semibold text-slate-700">${escapeHtml(row.slug)}</span>
                <span class="font-mono text-slate-500">${fmtNum(row.tokens)} tokens · ${fmtNum(row.requests)} 次</span>
            </div>
            <div class="usage-bar-track"><div class="usage-bar-fill" style="width:${Math.max(4, row.tokens * 100 / max)}%"></div></div>
        </div>
    `).join('') : '<div class="rounded-3xl border border-dashed border-slate-200 p-8 text-center text-sm text-slate-400">暂无容器消耗数据</div>';
}

function renderUsageTable(records) {
    $('#usage-table-count').textContent = `${records.length} / ${usageRecords.length} 条记录`;
    $('#usage-meta').textContent = usageLoaded ? `最近加载 ${new Date().toLocaleTimeString()}` : '';
    $('#usage-body').innerHTML = records.length ? records.slice(0, 500).map(r => {
        const time = parseUsageTs(r.ts) ? new Date(parseUsageTs(r.ts)).toLocaleString('zh-CN', { hour12: false }) : (r.ts || '-');
        const endpoint = r.endpoint || String(r.path || '').split('/').pop() || '-';
        return `
            <tr class="usage-row border-t border-slate-100" data-request-id="${escapeHtml(r.request_id || '')}">
                <td class="py-3 pl-4 pr-3 font-mono text-xs text-slate-500">${escapeHtml(time)}</td>
                <td class="px-3 py-3"><span class="model-chip">${escapeHtml(r.slug || '-')}</span></td>
                <td class="px-3 py-3 font-mono text-xs text-slate-700">${escapeHtml(r.model || '-')}</td>
                <td class="px-3 py-3 font-mono text-xs text-slate-600">${escapeHtml(endpoint)}</td>
                <td class="px-3 py-3"><span class="usage-mode-pill ${r.stream ? '' : 'usage-mode-pill-normal'}">${r.stream ? (r.stream_compat ? 'stream compat' : 'stream') : 'normal'}</span></td>
                <td class="px-3 py-3 font-mono text-xs">${escapeHtml(r.prompt_tokens ?? '-')}</td>
                <td class="px-3 py-3 font-mono text-xs">${escapeHtml(r.completion_tokens ?? '-')}</td>
                <td class="px-3 py-3 font-mono text-xs">${escapeHtml(r.total_tokens ?? '-')}</td>
                <td class="px-3 py-3 font-mono text-xs">${fmtMs(r.duration_ms)}</td>
                <td class="px-3 py-3"><span class="${r.ok ? 'usage-status-ok' : 'usage-status-error'}">${r.ok ? '成功' : `失败 ${escapeHtml(r.status || '')}`}</span></td>
                <td class="py-3 pl-3 pr-4 max-w-sm truncate text-xs text-slate-500">${escapeHtml(r.error || '-')}</td>
            </tr>
        `;
    }).join('') : '<tr><td colspan="11" class="px-4 py-12 text-center text-slate-400">暂无匹配的使用日志</td></tr>';
    $$('#usage-body .usage-row').forEach(row => {
        row.addEventListener('click', () => {
            const rec = records.find(r => (r.request_id || '') === row.dataset.requestId);
            if (rec) showUsageDetail(rec);
        });
    });
}

function renderUsage() {
    const summary = summarizeUsage(usageFilteredRecords);
    renderUsageMetrics(summary);
    renderUsageTrend(usageFilteredRecords);
    renderUsageSlugBars(summary);
    renderUsageTable(usageFilteredRecords);
}

function showUsageDetail(r) {
    const mode = r.stream ? (r.stream_compat ? 'stream compat' : 'stream') : 'normal';
    const item = (label, value, wide = false) => `
        <div class="${wide ? 'sm:col-span-2' : ''} rounded-2xl bg-slate-50 p-3">
            <div class="mb-1 text-xs font-semibold text-slate-400">${escapeHtml(label)}</div>
            <div class="break-all font-mono text-xs text-slate-700">${escapeHtml(value ?? '-')}</div>
        </div>
    `;
    $('#usage-detail-body').innerHTML = [
        item('Request ID', r.request_id, true),
        item('时间', r.ts),
        item('客户端 IP', r.ip),
        item('容器', r.slug),
        item('模型', r.model),
        item('路径', r.path, true),
        item('模式', mode),
        item('状态', `${r.status || '-'} ${r.ok ? 'OK' : 'ERROR'}`),
        item('Tokens', `${r.prompt_tokens ?? '-'} + ${r.completion_tokens ?? '-'} = ${r.total_tokens ?? '-'}`),
        item('耗时', fmtMs(r.duration_ms)),
        item('错误', r.error || '-', true),
    ].join('');
    $('#modal-usage-detail').classList.remove('hidden');
    $('#modal-usage-detail').classList.add('flex');
}

async function loadUsage() {
    $('#usage-body').innerHTML = '<tr><td colspan="11" class="px-4 py-8 text-center text-slate-400">加载中...</td></tr>';
    try {
        const d = await api('GET', '/api/usage?limit=5000');
        usageRecords = d.records || [];
        usageLoaded = true;
        syncUsageFilterOptions();
        applyUsageFilters();
    } catch (e) {
        $('#usage-body').innerHTML = `<tr><td colspan="11" class="px-4 py-8 text-center text-red-500">加载失败：${escapeHtml(e.message)}</td></tr>`;
        toast('加载使用日志失败：' + e.message, true);
    }
}

function exportUsageCsv() {
    const headers = ['ts','request_id','ip','slug','model','path','stream','stream_compat','status','ok','prompt_tokens','completion_tokens','total_tokens','duration_ms','error'];
    const lines = [headers.join(',')];
    for (const r of usageFilteredRecords) {
        lines.push(headers.map(h => {
            const value = String(r[h] ?? '');
            return `"${value.replace(/"/g, '""')}"`;
        }).join(','));
    }
    const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `chat2api-usage-${Date.now()}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
}

['usage-range','usage-slug','usage-model','usage-endpoint','usage-ok','usage-stream'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('change', applyUsageFilters);
});
const usageSearch = $('#usage-search');
if (usageSearch) usageSearch.addEventListener('input', applyUsageFilters);
const usageRefresh = $('#btn-usage-refresh');
if (usageRefresh) usageRefresh.addEventListener('click', loadUsage);
const usageClear = $('#btn-usage-clear');
if (usageClear) {
    usageClear.addEventListener('click', () => {
        $('#usage-range').value = '86400';
        $('#usage-slug').value = '';
        $('#usage-model').value = '';
        $('#usage-endpoint').value = '';
        $('#usage-ok').value = '';
        $('#usage-stream').value = '';
        $('#usage-search').value = '';
        applyUsageFilters();
    });
}
const usageExport = $('#btn-usage-export');
if (usageExport) usageExport.addEventListener('click', exportUsageCsv);
const usageDetailClose = $('#btn-close-usage-detail');
if (usageDetailClose) {
    usageDetailClose.addEventListener('click', () => {
        $('#modal-usage-detail').classList.add('hidden');
        $('#modal-usage-detail').classList.remove('flex');
        $('#usage-detail-body').innerHTML = '';
    });
}

// ---------- 调用信息 (单实例) ----------

let invokeCurrent = null;   // 当前 modal 展示的 info dict
let invokeSnippetTab = 'curl';

const PLAN_COLOR_CLASS = {
    free: 'bg-gray-200 text-gray-700',
    plus: 'bg-blue-100 text-blue-700',
    team: 'bg-emerald-100 text-emerald-700',
    pro: 'bg-amber-100 text-amber-700',
    enterprise: 'bg-violet-100 text-violet-700',
    unknown: 'bg-rose-100 text-rose-700',
};

function absoluteBaseUrl(rawBaseUrl) {
    if (!rawBaseUrl) return '';
    if (/^https?:\/\//.test(rawBaseUrl)) return rawBaseUrl;
    // 相对路径 → 拼当前 origin
    return location.origin + (rawBaseUrl.startsWith('/') ? rawBaseUrl : '/' + rawBaseUrl);
}

function genSnippets(baseUrl, apiKey, model) {
    const url = (baseUrl || '').replace(/\/$/, '');
    const k = apiKey || 'YOUR_API_KEY';
    const m = model || 'gpt-5-5';
    return {
        curl: `curl ${url}/chat/completions \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer ${k}" \\
  -d '{
    "model": "${m}",
    "messages": [{"role":"user","content":"Hello"}]
  }'`,
        python: `from openai import OpenAI

client = OpenAI(
    base_url="${url}",
    api_key="${k}",
)
resp = client.chat.completions.create(
    model="${m}",
    messages=[{"role": "user", "content": "Hello"}],
)
print(resp.choices[0].message.content)`,
        node: `import OpenAI from "openai";

const client = new OpenAI({
  baseURL: "${url}",
  apiKey: "${k}",
});

const resp = await client.chat.completions.create({
  model: "${m}",
  messages: [{ role: "user", content: "Hello" }],
});
console.log(resp.choices[0].message.content);`,
    };
}

function fallbackCopyToClipboard(text) {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    ta.style.top = '0';
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    let ok = false;
    try {
        ok = document.execCommand('copy');
    } finally {
        document.body.removeChild(ta);
    }
    if (!ok) throw new Error('浏览器拒绝复制，请手动选中文本复制');
}

async function copyToClipboard(text, btn) {
    const orig = btn.textContent;
    try {
        if (navigator.clipboard && window.isSecureContext) {
            await navigator.clipboard.writeText(text);
        } else {
            fallbackCopyToClipboard(text);
        }
        btn.textContent = '✓ 已复制';
        setTimeout(() => { btn.textContent = orig; }, 1500);
    } catch (e) {
        btn.textContent = orig;
        toast('复制失败：' + (e.message || '当前浏览器不允许在 HTTP 页面直接复制'), true);
    }
}

function renderModelChips(models, sourceHint) {
    const wrap = $('#invoke-models-chips');
    if (!models || !models.length) {
        wrap.innerHTML = '<span class="text-xs text-gray-400">无可用模型</span>';
    } else {
        wrap.innerHTML = models.map(m => {
            const modelId = (typeof m === 'string') ? m : (m && m.id);
            const source = (typeof m === 'string') ? '' : (m && m.source);
            const sourceTag = source === 'probe'
                ? '<span class="ml-1 text-[10px] text-emerald-600">实测</span>'
                : (source === 'alias'
                    ? '<span class="ml-1 text-[10px] text-amber-600">别名</span>'
                    : '');
            return `<span class="model-chip">${escapeHtml(modelId)}${sourceTag}</span>`;
        }).join('');
    }
    $('#invoke-models-source-hint').textContent = sourceHint || '';
}

function renderInvokeSnippet() {
    if (!invokeCurrent) return;
    const baseUrl = absoluteBaseUrl(invokeCurrent.base_url);
    const firstModel = (invokeCurrent.models && invokeCurrent.models[0] && invokeCurrent.models[0].id) || 'gpt-5-5';
    // 注意：因为后端没下发原文 auth，前端代码示例里只能填 masked key。提示用户从「凭证」按钮取原文。
    const apiKey = invokeCurrent.auth_masked || 'YOUR_API_KEY';
    const snippets = genSnippets(baseUrl, apiKey, firstModel);
    $('#invoke-snippet').textContent = snippets[invokeSnippetTab] || snippets.curl;
}

async function openInvokeModal(slug) {
    $('#invoke-slug-label').textContent = slug;
    $('#invoke-base-url').textContent = '加载中...';
    $('#invoke-auth-key').textContent = '加载中...';
    $('#invoke-plan').textContent = '...';
    $('#invoke-plan-source').textContent = '';
    $('#invoke-cached-state').textContent = '';
    $('#invoke-models-chips').innerHTML = '';
    $('#invoke-error').classList.add('hidden');
    $('#invoke-error').textContent = '';
    $('#invoke-snippet').textContent = '';
    $('#modal-invoke').classList.remove('hidden');
    $('#modal-invoke').classList.add('flex');

    try {
        const info = await api('GET', '/api/instances/' + encodeURIComponent(slug) + '/info');
        invokeCurrent = info;
        $('#invoke-base-url').textContent = absoluteBaseUrl(info.base_url) || '(未配置)';
        $('#invoke-auth-key').textContent = info.auth_masked || '(空)';
        const planEl = $('#invoke-plan');
        planEl.textContent = info.plan_label || info.plan_type || 'unknown';
        planEl.className = 'inline-block px-2 py-1 rounded text-xs ' + (PLAN_COLOR_CLASS[info.plan_type] || PLAN_COLOR_CLASS.unknown);
        $('#invoke-plan-source').textContent = info.plan_source === 'jwt' ? '(从 JWT 解析)' : '(无 token, 默认 unknown)';
        $('#invoke-cached-state').textContent = info.cached ? '✓ 使用 5min 缓存' : '✓ 新生成';
        renderModelChips(info.models, '(套餐默认表)');
        $('#invoke-error').classList.add('hidden');
        $('#invoke-error').textContent = '';
        invokeSnippetTab = 'curl';
        $$('.snippet-tab').forEach(b => {
            const active = b.dataset.snippet === 'curl';
            b.classList.toggle('border-blue-600', active);
            b.classList.toggle('text-blue-600', active);
            b.classList.toggle('border-transparent', !active);
            b.classList.toggle('text-gray-500', !active);
        });
        renderInvokeSnippet();
    } catch (e) {
        $('#invoke-base-url').textContent = '加载失败';
        toast('加载调用信息失败：' + e.message, true);
    }
}

function closeInvokeModal() {
    $('#modal-invoke').classList.add('hidden');
    $('#modal-invoke').classList.remove('flex');
    invokeCurrent = null;
}

$('#btn-close-invoke').addEventListener('click', closeInvokeModal);

// 实时探测按钮
$('#btn-probe-models').addEventListener('click', async () => {
    if (!invokeCurrent) return;
    const slug = invokeCurrent.slug;
    const btn = $('#btn-probe-models');
    const originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = '探测中...';
    try {
        const d = await api('POST', '/api/probe-models/' + encodeURIComponent(slug), {});
        const models = d.model_entries || (d.models || []).map(id => ({ id, source: 'probe' }));
        if (invokeCurrent) {
            invokeCurrent.models = models;
            const hasAlias = models.some(m => m.source === 'alias');
            renderModelChips(
                models,
                (hasAlias ? '(实测 + 深度研究别名 @ ' : '(实测 @ ') + new Date(d.probed_at * 1000).toLocaleTimeString() + ')'
            );
            renderInvokeSnippet();   // 用新的第一个 model 刷新代码示例
        }
        $('#invoke-error').classList.add('hidden');
        $('#invoke-error').textContent = '';
        toast('探测成功：' + models.length + ' 个模型');
        // 30s 内置灰
        btn.textContent = '⏳ 30s 冷却中';
        setTimeout(() => {
            btn.disabled = false;
            btn.textContent = originalText;
        }, 30000);
    } catch (e) {
        $('#invoke-error').textContent = e.message;
        $('#invoke-error').classList.remove('hidden');
        toast('探测失败：' + e.message, true);
        btn.disabled = false;
        btn.textContent = originalText;
    }
});

// snippet tab 切换
$$('.snippet-tab').forEach(btn => {
    btn.addEventListener('click', () => {
        invokeSnippetTab = btn.dataset.snippet;
        $$('.snippet-tab').forEach(b => {
            const active = b === btn;
            b.classList.toggle('border-blue-600', active);
            b.classList.toggle('text-blue-600', active);
            b.classList.toggle('border-transparent', !active);
            b.classList.toggle('text-gray-500', !active);
        });
        renderInvokeSnippet();
    });
});

// 通用 copy 按钮事件委托
document.addEventListener('click', (e) => {
    const btn = e.target.closest('.copy-btn');
    if (!btn) return;
    const targetId = btn.dataset.copyTarget;
    if (!targetId) return;
    const el = document.getElementById(targetId);
    if (!el) return;
    const text = el.tagName === 'PRE' ? el.textContent : el.textContent.trim();
    copyToClipboard(text, btn);
});

// ---------- 调用汇总（跨实例）+ 导出 ----------

async function openSummaryModal() {
    $('#summary-body').innerHTML = '<tr><td colspan="6" class="px-3 py-6 text-center text-gray-400">加载中...</td></tr>';
    $('#summary-empty').classList.add('hidden');
    $('#modal-summary').classList.remove('hidden');
    $('#modal-summary').classList.add('flex');
    try {
        const d = await api('GET', '/api/instances/aggregate');
        const rows = d.instances || [];
        if (!rows.length) {
            $('#summary-body').innerHTML = '';
            $('#summary-empty').classList.remove('hidden');
            return;
        }
        $('#summary-body').innerHTML = rows.map(r => {
            const endpoint = absoluteBaseUrl(r.base_url) || '(未配置)';
            const planClass = PLAN_COLOR_CLASS[r.plan_type] || PLAN_COLOR_CLASS.unknown;
            const health = r.container_state === 'running'
                ? (r.container_health === 'healthy'
                    ? '<span class="text-green-600">● healthy</span>'
                    : '<span class="text-yellow-600">● ' + escapeHtml(r.container_health || '?') + '</span>')
                : '<span class="text-gray-400">○ ' + escapeHtml(r.container_state || 'absent') + '</span>';
            const modelIds = (r.models || []).map(m => (typeof m === 'string') ? m : (m && m.id)).filter(Boolean);
            const modelsHtml = modelIds.length
                ? `<div class="flex flex-wrap gap-1">${modelIds.map(id => `<span class="model-chip">${escapeHtml(id)}</span>`).join('')}</div>`
                : '<span class="text-xs text-gray-400">无</span>';
            return `
                <tr class="border-t border-gray-100 hover:bg-gray-50 align-top">
                    <td class="px-3 py-2 font-medium kbd-row">${escapeHtml(r.slug)}</td>
                    <td class="px-3 py-2"><span class="inline-block px-2 py-0.5 rounded text-xs ${planClass}">${escapeHtml(r.plan_label || r.plan_type)}</span></td>
                    <td class="px-3 py-2 text-xs text-gray-600 kbd-row break-all">${escapeHtml(endpoint)}</td>
                    <td class="px-3 py-2 text-xs text-gray-600 kbd-row">${escapeHtml(r.auth_masked || '-')}</td>
                    <td class="px-3 py-2 text-xs">${modelsHtml}</td>
                    <td class="px-3 py-2 text-xs">${health}</td>
                </tr>
            `;
        }).join('');
    } catch (e) {
        $('#summary-body').innerHTML = `<tr><td colspan="6" class="px-3 py-6 text-center text-red-500">加载失败：${escapeHtml(e.message)}</td></tr>`;
    }
}

function exportConfig(fmt) {
    // 触发文件下载：浏览器会保留 session cookie，FastAPI Response 带 Content-Disposition
    window.location.href = './api/export/' + encodeURIComponent(fmt);
    toast('开始下载 ' + fmt + ' 配置');
}

$('#btn-summary').addEventListener('click', openSummaryModal);
$('#btn-close-summary').addEventListener('click', () => {
    $('#modal-summary').classList.add('hidden');
    $('#modal-summary').classList.remove('flex');
});

document.addEventListener('click', (e) => {
    const btn = e.target.closest('.btn-export');
    if (!btn) return;
    const fmt = btn.dataset.fmt;
    if (fmt) exportConfig(fmt);
});

// ---------- Playground 试调用 ----------

let pgInstances = [];   // 缓存 options 返回值

async function openPlaygroundModal() {
    $('#modal-playground').classList.remove('hidden');
    $('#modal-playground').classList.add('flex');
    $('#pg-result').classList.add('hidden');
    $('#pg-result-error').classList.add('hidden');
    try {
        const d = await api('GET', '/api/playground/options');
        pgInstances = d.instances || [];
        const slugSel = $('#pg-slug');
        if (!pgInstances.length) {
            slugSel.innerHTML = '<option value="">(无实例)</option>';
            $('#pg-model').innerHTML = '';
            return;
        }
        slugSel.innerHTML = pgInstances.map(it =>
            `<option value="${escapeHtml(it.slug)}">${escapeHtml(it.slug)} · ${escapeHtml(it.plan_label || it.plan_type)}</option>`
        ).join('');
        renderPgModels();
    } catch (e) {
        toast('加载实例列表失败：' + e.message, true);
    }
}

function renderPgModels() {
    const slug = $('#pg-slug').value;
    const inst = pgInstances.find(x => x.slug === slug);
    const models = inst ? (inst.models || []) : [];
    $('#pg-model').innerHTML = models.length
        ? models.map(m => `<option value="${escapeHtml(m)}">${escapeHtml(m)}</option>`).join('')
        : '<option value="">(无模型)</option>';
    $('#pg-custom-model').value = '';
}

async function runPlayground() {
    const slug = $('#pg-slug').value;
    const model = ($('#pg-custom-model').value.trim() || $('#pg-model').value).trim();
    const system = $('#pg-system').value;
    const user = $('#pg-user').value.trim();
    const temperature = parseFloat($('#pg-temp').value);
    const max_tokens = parseInt($('#pg-max-tokens').value, 10);

    if (!slug || !model) { toast('请先选择实例，或填写自定义模型', true); return; }
    if (!user) { toast('user prompt 不能为空', true); return; }

    const btn = $('#btn-pg-run');
    const origText = btn.textContent;
    btn.disabled = true;
    btn.innerHTML = '<span class="pg-loading-spinner"></span>运行中...';
    $('#pg-result').classList.remove('hidden');
    $('#pg-result-status').textContent = '...';
    $('#pg-result-latency').textContent = '...';
    $('#pg-result-usage').textContent = '...';
    $('#pg-result-content').textContent = '';
    $('#pg-result-error').classList.add('hidden');

    try {
        const d = await api('POST', '/api/playground/invoke', {
            slug, model, system, user, temperature, max_tokens
        });
        $('#pg-result-latency').textContent = (d.latency_ms || 0) + 'ms';
        if (d.ok) {
            $('#pg-result-status').innerHTML = '<span class="text-green-600">✓ 200</span>';
            const u = d.usage || {};
            $('#pg-result-usage').textContent = `${u.prompt_tokens || '-'} + ${u.completion_tokens || '-'} = ${u.total_tokens || '-'}`;
            $('#pg-result-content').textContent = d.content || '(空响应)';
        } else {
            $('#pg-result-status').innerHTML = `<span class="text-red-600">✗ ${escapeHtml(String(d.status || '?'))}</span>`;
            $('#pg-result-usage').textContent = '-';
            $('#pg-result-content').textContent = '';
            $('#pg-result-error').textContent = typeof d.error === 'string' ? d.error : JSON.stringify(d.error);
            $('#pg-result-error').classList.remove('hidden');
        }
    } catch (e) {
        $('#pg-result-status').innerHTML = '<span class="text-red-600">✗ 异常</span>';
        $('#pg-result-error').textContent = e.message;
        $('#pg-result-error').classList.remove('hidden');
    } finally {
        btn.disabled = false;
        btn.textContent = origText;
    }
}

$('#btn-playground').addEventListener('click', openPlaygroundModal);
$('#btn-close-playground').addEventListener('click', () => {
    $('#modal-playground').classList.add('hidden');
    $('#modal-playground').classList.remove('flex');
});
$('#pg-slug').addEventListener('change', renderPgModels);
$('#pg-temp').addEventListener('input', () => {
    $('#pg-temp-label').textContent = $('#pg-temp').value;
});
$('#btn-pg-run').addEventListener('click', runPlayground);

// ---------- 启动 ----------

loadStatus();
setInterval(loadStatus, 5000);
