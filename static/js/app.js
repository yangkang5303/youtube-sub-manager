// YouTube Subscription Manager - Frontend

let ALL_SUBS = [];        // full subscription list with details
let SUMMARY = {};         // summary stats + categories
// showChips：点顶部「分类」统计项后展开分类筛选
// bulk：批量打标签模式（开启后点卡片 = 选中）
let STATE = { filter: "all", category: null, showChips: false, bulk: false };

// 批量模式下已选中的 channel_id
let SELECTED = new Set();

// ── API helper ──
// 统一的 fetch 包装：遇到 401（授权过期/被撤销）自动跳转重新授权，
// 而不是只弹一个看不懂的「未授权」。
let AUTH_REDIRECTING = false;
async function apiFetch(url, opts) {
    const res = await fetch(url, opts);
    if (res.status === 401) {
        if (!AUTH_REDIRECTING) {
            AUTH_REDIRECTING = true;
            let msg = "登录已过期";
            try { msg = (await res.clone().json()).error || msg; } catch (e) { /* ignore */ }
            showError(msg + "，正在跳转重新授权…");
            setTimeout(() => { window.location.href = "/authorize"; }, 900);
        }
        throw new Error("未授权");
    }
    return res;
}

// ── Init ──
document.addEventListener("DOMContentLoaded", () => {
    setupTheme();
    setupTabs();
    setupFilters();
    setupCards();
    setupRefresh();
    setupBulk();
    loadData();
});

// ── 深浅色主题 ──
// 初始主题由 index.html 里的内联脚本设定（避免闪屏），这里只负责切换与跟随系统。
const THEME_KEY = "ytsm-theme";

function currentTheme() {
    return document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
}

function applyTheme(theme, persist) {
    document.documentElement.setAttribute("data-theme", theme);
    if (persist) {
        try { localStorage.setItem(THEME_KEY, theme); } catch (e) { /* 隐私模式忽略 */ }
    }
    const btn = document.getElementById("themeBtn");
    if (btn) {
        // 显示「将要切换到的」目标模式
        btn.textContent = theme === "light" ? "☀️" : "🌙";
        btn.title = theme === "light" ? "当前浅色模式，点击切换到深色" : "当前深色模式，点击切换到浅色";
    }
}

function setupTheme() {
    applyTheme(currentTheme(), false);

    const btn = document.getElementById("themeBtn");
    if (btn) {
        btn.addEventListener("click", () => {
            applyTheme(currentTheme() === "light" ? "dark" : "light", true);
        });
    }

    // 用户没手动选过时，跟随系统切换
    try {
        window.matchMedia("(prefers-color-scheme: light)").addEventListener("change", (e) => {
            let saved = null;
            try { saved = localStorage.getItem(THEME_KEY); } catch (err) { /* ignore */ }
            if (saved !== "light" && saved !== "dark") {
                applyTheme(e.matches ? "light" : "dark", false);
            }
        });
    } catch (e) { /* 旧浏览器不支持 addEventListener */ }
}

// ── Tabs ──
function setupTabs() {
    document.querySelectorAll(".tab-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            activateTab(btn.dataset.tab);
            // 手动切换 tab 时清掉筛选状态
            STATE.filter = btn.dataset.tab === "inactive" ? "inactive" : "all";
            STATE.category = null;
            updateFilterUI();
            renderCurrentTab();
        });
    });
}

function activateTab(tab) {
    document.querySelectorAll(".tab-btn").forEach(b => {
        b.classList.toggle("active", b.dataset.tab === tab);
    });
    document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
    const el = document.getElementById("tab-" + tab);
    if (el) el.classList.add("active");
}

// ── 顶部统计条（点击即筛选）──
function setupCards() {
    document.querySelectorAll(".stat[data-filter]").forEach(card => {
        card.addEventListener("click", () => applyCardFilter(card.dataset.filter));
    });

    document.getElementById("clearFilterBtn").addEventListener("click", () => {
        STATE.filter = "all";
        STATE.category = null;
        STATE.showChips = false;
        activateTab("list");
        updateFilterUI();
        renderCurrentTab();
    });
}

function applyCardFilter(filter) {
    if (filter === "categories") {
        // 「分类」不再跳转独立页面（信息冗余），改为就地展开分类筛选
        STATE.showChips = !STATE.showChips;
        if (!STATE.showChips) STATE.category = null;
        updateFilterUI();
        renderCurrentTab();
        if (STATE.showChips) {
            const el = document.getElementById("catChips");
            el.scrollIntoView({ behavior: "smooth", block: "nearest" });
        }
        return;
    }

    STATE.category = null;
    STATE.filter = filter;
    activateTab(filter === "inactive" ? "inactive" : "list");
    updateFilterUI();
    renderCurrentTab();
}

function updateFilterUI() {
    // 统计项高亮
    document.querySelectorAll(".stat[data-filter]").forEach(c => {
        const f = c.dataset.filter;
        let on;
        if (f === "categories") {
            on = STATE.showChips;
        } else if (f === "all") {
            on = STATE.filter === "all" && !STATE.category;
        } else {
            on = STATE.filter === f;
        }
        c.classList.toggle("selected", on);
    });

    // 筛选提示条
    const ind = document.getElementById("filterIndicator");
    const txt = document.getElementById("filterIndicatorText");
    const parts = [];
    if (STATE.filter === "active") parts.push("仅显示 90 天内有更新的频道");
    if (STATE.filter === "inactive") parts.push("仅显示 90 天未更新的频道");
    if (STATE.category) parts.push(`仅显示分类「${STATE.category}」`);
    if (parts.length) {
        txt.textContent = parts.join(" · ");
        ind.classList.remove("hidden");
    } else {
        ind.classList.add("hidden");
    }

    renderCatChips();
    updateLabelOptions();
}

// 分类筛选胶囊（展开时才显示）
function renderCatChips() {
    const el = document.getElementById("catChips");
    const mine = new Set(SUMMARY.custom_labels || []);
    const cats = Object.keys(SUMMARY.categories || {})
        .sort((a, b) => {
            // 「我的标签」排前面，方便快速取用
            const am = mine.has(a) ? 0 : 1, bm = mine.has(b) ? 0 : 1;
            if (am !== bm) return am - bm;
            return SUMMARY.categories[b].length - SUMMARY.categories[a].length;
        });

    if (!cats.length || (!STATE.showChips && !STATE.category)) {
        el.classList.add("hidden");
        el.innerHTML = "";
        return;
    }

    el.classList.remove("hidden");
    el.innerHTML = cats.map(name => {
        const n = SUMMARY.categories[name].length;
        const on = STATE.category === name ? " chip-on" : "";
        const isMine = mine.has(name);
        const cls = "cat-chip" + (isMine ? " chip-custom" : "");
        const tip = isMine ? "我的标签" : "YouTube 自动分类";
        return `<button class="${cls}${on}" data-cat="${escAttr(name)}" title="${tip}：点击筛选">${escHtml(name)} <span class="chip-count">${n}</span></button>`;
    }).join("");

    el.querySelectorAll(".cat-chip").forEach(btn => {
        btn.addEventListener("click", () => {
            const c = btn.dataset.cat;
            STATE.category = (STATE.category === c) ? null : c;
            if (STATE.category) {
                activateTab("list");
                STATE.filter = "all";
            }
            updateFilterUI();
            renderCurrentTab();
        });
    });
}

// ── Filters ──
function setupFilters() {
    document.getElementById("searchInput").addEventListener("input", renderCurrentTab);
    document.getElementById("sortSelect").addEventListener("change", renderCurrentTab);
}

// ── Refresh ──
function setupRefresh() {
    const btn = document.getElementById("refreshBtn");
    btn.addEventListener("click", async () => {
        // 非破坏性操作，不再弹确认框；按钮自身展示进度，完成后用 toast 反馈
        btn.disabled = true;
        const old = btn.textContent;
        btn.textContent = "🔄 拉取中...";
        showLoading(true);
        try {
            const res = await apiFetch("/api/refresh", { method: "POST" });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(data.error || "刷新失败");
            await loadData();
            showToast({
                icon: "✓",
                title: "数据已更新",
                subtitle: `共 ${data.count ?? ALL_SUBS.length} 个订阅`,
                duration: 2600,
            });
        } catch (e) {
            if (e.message !== "未授权") {
                showToast({ icon: "⚠", title: "刷新失败", subtitle: e.message, variant: "error" });
            }
        } finally {
            btn.disabled = false;
            btn.textContent = old;
            showLoading(false);
        }
    });
}

function getActiveTab() {
    const activeBtn = document.querySelector(".tab-btn.active");
    return activeBtn ? activeBtn.dataset.tab : "list";
}

// ── Data Loading ──
async function loadData() {
    showLoading(true);
    try {
        const subsRes = await apiFetch("/api/subscriptions");
        if (!subsRes.ok) throw new Error("API 请求失败");
        const subsData = await subsRes.json();
        ALL_SUBS = subsData.subscriptions || [];

        const sumRes = await apiFetch("/api/summary");
        if (!sumRes.ok) throw new Error("API 请求失败");
        SUMMARY = await sumRes.json();

        updateSummary(SUMMARY);
        updateLastUpdated(subsData.last_updated || SUMMARY.last_updated);
        updateFilterUI();
        renderCurrentTab();
    } catch (e) {
        // 401 时 apiFetch 已提示并跳转，别再覆盖成「加载数据失败」
        if (e.message !== "未授权") showError("加载数据失败: " + e.message);
    } finally {
        showLoading(false);
    }
}

function updateLastUpdated(iso) {
    const el = document.getElementById("lastUpdated");
    if (!iso) { el.textContent = ""; return; }
    const d = new Date(iso);
    if (isNaN(d.getTime())) { el.textContent = ""; return; }
    const pad = n => String(n).padStart(2, "0");
    el.textContent = `数据更新于 ${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

// ── Summary Cards ──
function updateSummary(data) {
    document.getElementById("totalCount").textContent = data.total ?? "-";
    document.getElementById("activeCount").textContent = data.active_90d ?? "-";
    document.getElementById("inactiveCount").textContent = data.inactive_90d ?? "-";
    document.getElementById("catCount").textContent = Object.keys(data.categories || {}).length;
}

// ── Rendering ──
function renderCurrentTab() {
    const tab = getActiveTab();
    const query = document.getElementById("searchInput").value.toLowerCase().trim();
    const sort = document.getElementById("sortSelect").value;

    let filtered = ALL_SUBS.filter(s => (s.title || "").toLowerCase().includes(query));

    if (STATE.filter === "active") {
        filtered = filtered.filter(s => isActive(daysValue(s)));
    } else if (STATE.filter === "inactive") {
        filtered = filtered.filter(s => daysValue(s) > 90);
    }
    if (STATE.category) {
        // 只要频道的【任一】分类命中就算匹配
        filtered = filtered.filter(s => subCategories(s).includes(STATE.category));
    }

    filtered = sortList(filtered, sort);

    if (tab === "list") {
        renderSubList(filtered, "subList");
    } else if (tab === "inactive") {
        renderSubList(filtered.filter(s => daysValue(s) > 90), "inactiveList");
    }
}

function sortList(list, sortBy) {
    return [...list].sort((a, b) => {
        switch (sortBy) {
            case "name":
                return (a.title || "").localeCompare(b.title || "", "zh");
            case "days_asc":
                return daysValue(a) - daysValue(b);
            case "days_desc":
                return daysValue(b) - daysValue(a);
            case "subs_desc":
                return (b.subscriber_count || 0) - (a.subscriber_count || 0);
            case "video_count":
                return (b.video_count || 0) - (a.video_count || 0);
            default:
                return 0;
        }
    });
}

function formatNum(n) {
    if (!n) return "-";
    if (n >= 1000000) return (n / 1000000).toFixed(1) + "M";
    if (n >= 1000) return (n / 1000).toFixed(1) + "K";
    return n.toString();
}

function daysLabel(days) {
    if (days < 0) return "未知";
    if (days === 0) return "今天";
    if (days === 1) return "昨天";
    if (days < 30) return days + "天前";
    if (days < 365) return Math.round(days / 30) + "个月前";
    return Math.round(days / 365) + "年前";
}

function isActive(days) {
    return days >= 0 && days <= 90;
}

function daysValue(sub) {
    const d = sub.days_since_upload;
    return (d === undefined || d === null || d < 0) ? -1 : d;
}

// 一个频道可能同时属于多个分类
// 频道的全部标签 = YouTube 自动分类 + 用户自定义标签
// 两者合并后，筛选逻辑对「我的标签」和「自动分类」完全一致
function subCategories(sub) {
    const cats = (Array.isArray(sub.categories) && sub.categories.length)
        ? sub.categories
        : [sub.primary_category || "未分类"];
    const custom = Array.isArray(sub.custom_labels) ? sub.custom_labels : [];
    return cats.concat(custom.filter(l => !cats.includes(l)));
}

// 该频道自己的自定义标签（用于区分样式）
function customLabels(sub) {
    return Array.isArray(sub.custom_labels) ? sub.custom_labels : [];
}

// 跳到频道的「视频」标签页（而不是默认的 featured 首页），
// 点进去直接就能看到最新上传。
function channelUrl(sub) {
    const handle = String(sub.custom_url || "").trim().replace(/^@/, "");
    if (handle) {
        // 中文等非 ASCII handle 需要百分号编码，YouTube 能正常解析
        return "https://www.youtube.com/@" + encodeURIComponent(handle) + "/videos";
    }
    // 没有 handle 时退回 channel id 形式，同样带 /videos
    return "https://www.youtube.com/channel/" + encodeURIComponent(sub.channel_id || "") + "/videos";
}

function makeSubRow(sub) {
    const days = daysValue(sub);
    const active = isActive(days);
    // 走本地缓存代理，避免浏览器直连 yt3.ggpht.com 被 CDN 限流 (429)
    const thumb = sub.channel_id
        ? `/thumb/${encodeURIComponent(sub.channel_id)}`
        : (sub.thumbnail || "");
    const subs = formatNum(sub.subscriber_count);
    const videos = formatNum(sub.video_count);
    const uploadStr = daysLabel(days);
    const cid = sub.channel_id || "";
    const mine = customLabels(sub);
    const cats = subCategories(sub);
    const url = channelUrl(sub);
    const fallback = "data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 48 48%22><rect fill=%22%23333%22 width=%2248%22 height=%2248%22/><text x=%2224%22 y=%2230%22 text-anchor=%22middle%22 fill=%22%23666%22 font-size=%2220%22>?</text></svg>";

    // 展示全部标签：YouTube 自动分类 + 我的标签（后者样式不同，可一眼区分）
    const firstCat = cats[0];
    const catBadges = cats.map(c => {
        const isMine = mine.includes(c);
        if (isMine) {
            // 自定义标签：hover 时右上角出现小叉，点击可把这个标签从该频道移除。
            // 外层用 span（里面要嵌一个 button，button 不能嵌套 button）。
            return `<span class="badge badge-category cat-tag cat-tag-custom"
                          data-cat="${escAttr(c)}" title="我的标签：点击筛选该标签">
                        <span class="cat-tag-text">${escHtml(c)}</span>
                        <button type="button" class="tag-remove"
                                data-cat="${escAttr(c)}" data-channel-id="${escAttr(cid)}"
                                title="从该频道移除标签「${escAttr(c)}」"
                                aria-label="移除标签 ${escAttr(c)}">×</button>
                    </span>`;
        }
        const cls = c === firstCat ? "cat-tag-primary" : "";
        return `<button class="badge badge-category cat-tag ${cls}"
                        data-cat="${escAttr(c)}" title="自动分类：点击筛选">${escHtml(c)}</button>`;
    }).join("");

    const selected = SELECTED.has(cid);
    const rowCls = "sub-row" + (selected ? " row-selected" : "");

    return `
        <div class="${rowCls}" data-channel-id="${escAttr(cid)}">
            <span class="row-check" aria-hidden="true"></span>

            <!-- 第 1 区：头像 + 频道名，作为一组水平居中；名字垂直居中对齐头像圆心 -->
            <div class="sub-head">
                <a class="sub-thumb-link" href="${url}" target="_blank" rel="noopener noreferrer" title="在 YouTube 查看该频道的最新视频">
                    <img class="sub-thumb" src="${escAttr(thumb)}" alt="" width="48" height="48"
                         loading="lazy" decoding="async" referrerpolicy="no-referrer"
                         onerror="this.onerror=null;this.src='${fallback}'">
                </a>
                <div class="sub-title">
                    <a href="${url}" target="_blank" rel="noopener noreferrer" title="在 YouTube 查看该频道的最新视频">${escHtml(sub.title || "")}</a>
                </div>
            </div>

            <!-- 第 2 区：订阅数 / 视频数（居中） -->
            <div class="sub-stats">
                ${subs !== '-' ? `<span>👤 ${subs}</span>` : ''}
                ${videos !== '-' ? `<span>🎬 ${videos}</span>` : ''}
            </div>

            <!-- 第 3 区：标签（最多 2 行） -->
            <div class="sub-tags">${catBadges}</div>

            <!-- 第 4 区：活跃情况 + 退订 -->
            <div class="sub-foot">
                <span class="badge ${active ? 'badge-active' : 'badge-inactive'}">
                    ${active ? '● 活跃' : '○ 不活跃'} · ${uploadStr}
                </span>
                <button class="unsub-btn" data-sub-id="${escAttr(sub.subscription_id || '')}" data-sub-title="${escAttr(sub.title || '')}">
                    退订
                </button>
            </div>
        </div>
    `;
}

function escHtml(str) {
    const div = document.createElement("div");
    div.textContent = str == null ? "" : String(str);
    return div.innerHTML;
}

// 用于 HTML 属性（含引号）的安全转义
function escAttr(str) {
    return String(str == null ? "" : str)
        .replace(/&/g, "&amp;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
}

function renderSubList(subs, containerId) {
    const el = document.getElementById(containerId);
    if (subs.length === 0) {
        el.innerHTML = '<div class="empty-tip">暂无数据</div>';
        return;
    }
    el.innerHTML = subs.map(makeSubRow).join("");
}

// ── Unsubscribe：乐观更新 + 撤销（无确认弹窗）──
// 点击立刻执行并从列表移除，底部弹出可撤销提示；误触也能一键恢复。
document.addEventListener("click", (e) => {
    // 批量模式下：整张卡片就是选择开关，屏蔽链接/标签/退订
    if (STATE.bulk) {
        const row = e.target.closest(".sub-row");
        if (row && row.dataset.channelId) {
            e.preventDefault();
            toggleSelect(row.dataset.channelId);
        }
        return;
    }
    // 标签右上角的小叉 → 把该标签从这个频道移除（优先于筛选，否则会误触发筛选）
    const rm = e.target.closest(".tag-remove");
    if (rm) {
        e.preventDefault();
        e.stopPropagation();
        removeLabelFromChannel(rm.dataset.channelId, rm.dataset.cat);
        return;
    }
    // 点击频道上的分类标签 → 按该分类筛选
    const tag = e.target.closest(".cat-tag");
    if (tag) {
        applyCategoryFilter(tag.dataset.cat);
        return;
    }
    const btn = e.target.closest(".unsub-btn");
    if (!btn || btn.disabled) return;
    unsubscribe(btn.dataset.subId, btn);
});

// ── 批量打标签 ──
function setupBulk() {
    document.getElementById("bulkToggleBtn").addEventListener("click", () => setBulkMode(!STATE.bulk));
    document.getElementById("exitBulkBtn").addEventListener("click", () => setBulkMode(false));
    document.getElementById("clearSelBtn").addEventListener("click", () => {
        SELECTED.clear();
        afterSelectionChange();
    });
    document.getElementById("invertSelBtn").addEventListener("click", () => {
        const visible = currentFilteredList();
        for (const s of visible) {
            const cid = s.channel_id;
            if (!cid) continue;
            if (SELECTED.has(cid)) SELECTED.delete(cid); else SELECTED.add(cid);
        }
        afterSelectionChange();
    });
    document.getElementById("selectAllBtn").addEventListener("click", () => {
        for (const s of currentFilteredList()) {
            if (s.channel_id) SELECTED.add(s.channel_id);
        }
        afterSelectionChange();
    });

    document.getElementById("addLabelBtn").addEventListener("click", () => applyLabel("add"));
    document.getElementById("removeLabelBtn").addEventListener("click", () => applyLabel("remove"));
    document.getElementById("labelInput").addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            e.preventDefault();
            applyLabel("add");
        }
    });
}

function setBulkMode(on) {
    STATE.bulk = !!on;
    if (!STATE.bulk) SELECTED.clear();

    const bar = document.getElementById("bulkBar");
    const toggle = document.getElementById("bulkToggleBtn");
    bar.classList.toggle("hidden", !STATE.bulk);
    toggle.classList.toggle("active", STATE.bulk);
    document.body.classList.toggle("bulk-mode", STATE.bulk);

    if (STATE.bulk) {
        updateLabelOptions();
        document.getElementById("labelInput").focus();
    }
    updateBulkCount();
    renderCurrentTab();
}

function toggleSelect(channelId) {
    if (!channelId) return;
    if (SELECTED.has(channelId)) SELECTED.delete(channelId);
    else SELECTED.add(channelId);

    // 只更新这一张卡片的样式，不整列表重绘（避免滚动跳动）
    const row = document.querySelector(`.sub-row[data-channel-id="${cssEscape(channelId)}"]`);
    if (row) row.classList.toggle("row-selected", SELECTED.has(channelId));
    updateBulkCount();
}

function afterSelectionChange() {
    renderCurrentTab();
    updateBulkCount();
}

function updateBulkCount() {
    const el = document.getElementById("bulkCount");
    if (el) el.textContent = `已选 ${SELECTED.size} 个`;
}

// 当前筛选/搜索/排序后实际显示的频道（「全选」只作用于可见结果）
function currentFilteredList() {
    const q = (document.getElementById("searchInput").value || "").toLowerCase().trim();
    let list = ALL_SUBS.filter(s => (s.title || "").toLowerCase().includes(q));
    if (STATE.filter === "active") list = list.filter(s => isActive(daysValue(s)));
    else if (STATE.filter === "inactive") list = list.filter(s => daysValue(s) > 90);
    if (STATE.category) list = list.filter(s => subCategories(s).includes(STATE.category));
    return list;
}

// 已有标签填进 datalist，输入框可以下拉选择
function updateLabelOptions() {
    const dl = document.getElementById("labelOptions");
    if (!dl) return;
    dl.innerHTML = (SUMMARY.custom_labels || [])
        .map(l => `<option value="${escAttr(l)}"></option>`)
        .join("");
}

async function applyLabel(action) {
    const input = document.getElementById("labelInput");
    const label = (input.value || "").trim();

    if (!label) {
        showToast({ icon: "⚠", title: "请先输入标签名", variant: "error", duration: 2600 });
        input.focus();
        return;
    }
    if (!SELECTED.size) {
        showToast({ icon: "⚠", title: "请先点击频道卡片选中", variant: "error", duration: 2600 });
        return;
    }

    const ids = [...SELECTED];
    try {
        const res = await apiFetch("/api/labels", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ channel_ids: ids, label, action }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || "操作失败");

        // 同步本地状态，避免整表重新拉取
        for (const s of ALL_SUBS) {
            if (!SELECTED.has(s.channel_id)) continue;
            const cur = new Set(customLabels(s));
            if (action === "add") cur.add(data.label); else cur.delete(data.label);
            s.custom_labels = [...cur];
        }

        await refreshSummary();
        renderCurrentTab();
        input.value = "";
        updateLabelOptions();
        updateBulkCount();

        if (data.changed === 0) {
            showToast({
                icon: "ℹ",
                title: action === "add" ? `这些频道已经有「${data.label}」了` : `这些频道没有「${data.label}」`,
                duration: 2800,
            });
        } else {
            showToast({
                icon: "✓",
                title: action === "add"
                    ? `已为 ${data.changed} 个频道加上「${data.label}」`
                    : `已从 ${data.changed} 个频道移除「${data.label}」`,
                duration: 2800,
            });
        }
    } catch (e) {
        if (e.message !== "未授权") {
            showToast({ icon: "⚠", title: "操作失败", subtitle: e.message, variant: "error", duration: 3200 });
        }
    }
}

// ── 单个频道的标签移除（标签右上角的小叉）──
async function removeLabelFromChannel(channelId, label) {
    if (!channelId || !label) return;
    const sub = ALL_SUBS.find(s => s.channel_id === channelId);

    try {
        const res = await apiFetch("/api/labels", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ channel_ids: [channelId], label, action: "remove" }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || "移除失败");

        // 本地同步，避免整表重新拉取
        if (sub) {
            sub.custom_labels = customLabels(sub).filter(l => l !== label);
        }
        await refreshSummary();
        renderCurrentTab();

        showToast({
            icon: "✓",
            title: `已移除标签「${label}」`,
            subtitle: sub ? sub.title : "",
            actionLabel: "撤销",
            duration: 6000,
            onAction: () => restoreLabelToChannel(channelId, label),
        });
    } catch (e) {
        if (e.message !== "未授权") {
            showToast({ icon: "⚠", title: "移除失败", subtitle: e.message, variant: "error", duration: 3200 });
        }
    }
}

async function restoreLabelToChannel(channelId, label) {
    try {
        const res = await apiFetch("/api/labels", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ channel_ids: [channelId], label, action: "add" }),
        });
        if (!res.ok) throw new Error("恢复失败");

        const sub = ALL_SUBS.find(s => s.channel_id === channelId);
        if (sub) {
            const cur = new Set(customLabels(sub));
            cur.add(label);
            sub.custom_labels = [...cur];
        }
        await refreshSummary();
        renderCurrentTab();
        showToast({ icon: "↩", title: `已恢复标签「${label}」`, duration: 2400 });
    } catch (e) {
        showToast({ icon: "⚠", title: "撤销失败", subtitle: e.message, variant: "error", duration: 3200 });
    }
}

// 只刷新汇总（标签筛选区），不重新拉订阅列表
async function refreshSummary() {
    try {
        const res = await apiFetch("/api/summary");
        if (!res.ok) return;
        SUMMARY = await res.json();
        updateSummary(SUMMARY);
        updateFilterUI();
    } catch (e) { /* 忽略：界面已本地更新 */ }
}

// 供 querySelector 使用的转义（channel_id 一般是安全的，这里做兜底）
function cssEscape(s) {
    return String(s).replace(/["\\]/g, "\\$&");
}

function applyCategoryFilter(cat) {
    if (!cat) return;
    STATE.category = cat;
    STATE.filter = "all";
    STATE.showChips = true;
    activateTab("list");
    updateFilterUI();
    renderCurrentTab();
    window.scrollTo({ top: 0, behavior: "smooth" });
}

const UNDO_SECONDS = 6;

async function unsubscribe(subId, btn) {
    if (!subId) return;

    const sub = ALL_SUBS.find(s => s.subscription_id === subId);
    const row = btn.closest(".sub-row");

    // 立即反馈：按钮进入 pending，行开始淡出（不等网络返回）
    btn.disabled = true;
    if (row) row.classList.add("row-leaving");

    try {
        const res = await apiFetch(`/api/unsubscribe/${encodeURIComponent(subId)}`, { method: "POST" });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || "退订失败");

        // 从本地状态移除，并让行收起
        ALL_SUBS = ALL_SUBS.filter(s => s.subscription_id !== subId);
        if (row) {
            row.style.height = row.offsetHeight + "px";
            requestAnimationFrame(() => row.classList.add("row-collapsed"));
            setTimeout(() => row.remove(), 320);
        }
        refreshSummaryCounts();

        // 可撤销提示
        showToast({
            icon: "✓",
            title: `已退订「${sub ? sub.title : (btn.dataset.subTitle || "")}」`,
            subtitle: `${UNDO_SECONDS} 秒内可撤销`,
            actionLabel: "撤销",
            duration: UNDO_SECONDS * 1000,
            onAction: () => resubscribe(sub),
        });
    } catch (e) {
        // 失败：把行恢复回来
        if (row) row.classList.remove("row-leaving");
        btn.disabled = false;
        if (e.message !== "未授权") {
            showToast({ icon: "⚠", title: "退订失败", subtitle: e.message, variant: "error" });
        }
    }
}

async function resubscribe(sub) {
    if (!sub) { await loadData(); return; }
    try {
        const res = await apiFetch("/api/resubscribe", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(sub),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || "撤销失败");

        // 重新拉取（读本地 DB，很快），保证排序/统计都正确
        await loadData();
        showToast({ icon: "↩", title: `已恢复「${sub.title}」`, duration: 2600 });
    } catch (e) {
        showToast({ icon: "⚠", title: "撤销失败", subtitle: e.message, variant: "error" });
    }
}

// 退订后不需要重新拉数据，本地估算即可让卡片数字保持准确
function refreshSummaryCounts() {
    const active = ALL_SUBS.filter(s => isActive(daysValue(s))).length;
    const inactive = ALL_SUBS.filter(s => daysValue(s) > 90).length;
    SUMMARY.total = ALL_SUBS.length;
    SUMMARY.active_90d = active;
    SUMMARY.inactive_90d = inactive;
    updateSummary(SUMMARY);
}

// ── Toast（底部通知，支持撤销按钮 + 倒计时进度条）──
function showToast({ icon = "", title = "", subtitle = "", actionLabel = null,
                     onAction = null, duration = 3000, variant = "info" }) {
    let stack = document.getElementById("toastStack");
    if (!stack) {
        stack = document.createElement("div");
        stack.id = "toastStack";
        stack.className = "toast-stack";
        document.body.appendChild(stack);
    }

    const toast = document.createElement("div");
    toast.className = "toast" + (variant === "error" ? " toast-error" : "");
    toast.innerHTML = `
        ${icon ? `<div class="toast-icon">${escHtml(icon)}</div>` : ""}
        <div class="toast-body">
            <div class="toast-title">${escHtml(title)}</div>
            ${subtitle ? `<div class="toast-sub">${escHtml(subtitle)}</div>` : ""}
        </div>
        ${actionLabel ? `<button class="toast-action"></button>` : ""}
        ${onAction ? `<div class="toast-progress"><div class="toast-progress-bar"></div></div>` : ""}
    `;

    const actionBtn = toast.querySelector(".toast-action");
    if (actionLabel && actionBtn) actionBtn.textContent = actionLabel;

    stack.appendChild(toast);
    requestAnimationFrame(() => toast.classList.add("toast-in"));

    let timer = null;
    const close = () => {
        if (timer) clearTimeout(timer);
        toast.classList.remove("toast-in");
        toast.classList.add("toast-out");
        setTimeout(() => toast.remove(), 260);
    };

    if (onAction) {
        const bar = toast.querySelector(".toast-progress-bar");
        if (bar) {
            bar.style.transitionDuration = duration + "ms";
            requestAnimationFrame(() => { bar.style.width = "0%"; });
        }
        timer = setTimeout(close, duration);
        if (actionBtn) {
            actionBtn.addEventListener("click", () => {
                close();
                onAction();
            });
        }
    } else {
        timer = setTimeout(close, duration);
        if (actionBtn) actionBtn.addEventListener("click", close);
    }

    return toast;
}

// ── UI Helpers ──
function showLoading(show) {
    document.getElementById("loading").classList.toggle("hidden", !show);
}

function showError(msg) {
    const el = document.getElementById("errorBanner");
    el.textContent = msg;
    el.classList.remove("hidden");
    setTimeout(() => el.classList.add("hidden"), 5000);
}
