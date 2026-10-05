(function (global) {
    'use strict';

    const WATCH_KEY = 'strategy-lab-watchlist-v1';
    const READ_KEY = 'strategy-lab-read-alerts-v1';

    function loadStoredArray(storage, key) {
        try {
            if (!storage || typeof storage.getItem !== 'function') return [];
            const value = JSON.parse(storage.getItem(key) || '[]');
            return Array.isArray(value) ? value : [];
        } catch (_) {
            return [];
        }
    }

    function normalizeStock(stock) {
        const code = String(stock && stock.code || '').replace(/\D/g, '').padStart(6, '0');
        if (!/^\d{6}$/.test(code)) return null;
        return {
            code,
            name: String(stock.name || code),
            price: stock.price == null ? null : Number(stock.price),
            pct: stock.pct == null ? null : Number(stock.pct),
            industry: String(stock.industry || ''),
            score: stock.score == null ? null : Number(stock.score),
            strategies: Array.isArray(stock.strategies) ? stock.strategies.map(String) : []
        };
    }

    function toggleWatchlist(list, stock) {
        const current = Array.isArray(list) ? list.map(item => ({ ...item })) : [];
        const normalized = normalizeStock(stock);
        if (!normalized) return current;
        const index = current.findIndex(item => String(item.code) === normalized.code);
        if (index >= 0) current.splice(index, 1);
        else current.push(normalized);
        return current;
    }

    function uniqueAlerts(alerts, readIds) {
        const seen = new Set();
        const all = [];
        (Array.isArray(alerts) ? alerts : []).forEach(alert => {
            const id = String(alert && alert.id || '');
            if (!id || seen.has(id)) return;
            seen.add(id);
            all.push(alert);
        });
        const read = new Set((Array.isArray(readIds) ? readIds : []).map(String));
        return { all, unread: all.filter(alert => !read.has(String(alert.id))) };
    }

    const api = { loadStoredArray, toggleWatchlist, uniqueAlerts };
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
    global.ResearchWorkspace = api;

    if (!global.document) return;

    const document = global.document;
    const embedded = (() => {
        try {
            return JSON.parse(document.getElementById('researchWorkspaceData').textContent || '{}');
        } catch (_) {
            return {};
        }
    })();
    let storage = null;
    try {
        storage = global.localStorage;
        storage.getItem(WATCH_KEY);
    } catch (_) {
        storage = null;
    }
    let watchlist = loadStoredArray(storage, WATCH_KEY).map(normalizeStock).filter(Boolean);
    let readAlertIds = loadStoredArray(storage, READ_KEY).map(String);
    let currentAlerts = [];

    const esc = value => String(value == null ? '' : value)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    const fmt = (value, digits = 2) => Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : '--';

    function saveArray(key, value) {
        try {
            if (storage) storage.setItem(key, JSON.stringify(value));
        } catch (_) {
            storage = null;
        }
    }

    function stockFromElement(button) {
        const card = button.closest('.stock-card');
        const catalog = (embedded.stocks || []).find(item => String(item.code) === String(button.dataset.code));
        return normalizeStock({
            ...(catalog || {}),
            code: button.dataset.code,
            name: button.dataset.name || (card && card.querySelector('.name') || {}).textContent || button.dataset.code,
            price: catalog && catalog.price,
            pct: catalog && catalog.pct,
            score: catalog && catalog.score
        });
    }

    function isWatched(code) {
        return watchlist.some(item => item.code === String(code));
    }

    function syncWatchButtons() {
        document.querySelectorAll('[data-workspace-action="watch"]').forEach(button => {
            const active = isWatched(button.dataset.code);
            button.classList.toggle('is-watched', active);
            button.textContent = active ? '★' : '☆';
            button.title = active ? '移出个人观察' : '加入个人观察';
            button.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        const count = document.getElementById('watchlistNavCount');
        if (count) count.textContent = String(watchlist.length);
    }

    function renderWatchlist() {
        const container = document.getElementById('watchlistContent');
        if (!container) return;
        if (!watchlist.length) {
            container.innerHTML = '<div class="empty state-panel"><div class="icon">⭐</div><div class="text">观察池还是空的</div><div class="hint">从股票卡片或顶部搜索结果中点击收藏</div></div>';
            return;
        }
        container.innerHTML = '<div class="watchlist-grid">' + watchlist.map(stock => {
            const tone = Number(stock.pct) >= 0 ? 'pct-up' : 'pct-down';
            return '<article class="watchlist-card"><div><div class="watchlist-name">' + esc(stock.name) + ' <span>' + esc(stock.code) + '</span></div>' +
                '<div class="watchlist-quote">' + (stock.price == null ? '价格暂无' : '¥' + fmt(stock.price)) +
                (stock.pct == null ? '' : ' <b class="' + tone + '">' + (Number(stock.pct) >= 0 ? '+' : '') + fmt(stock.pct) + '%</b>') + '</div>' +
                '<div class="watchlist-meta">' + esc(stock.industry || '行业暂无') + (stock.strategies.length ? ' · ' + esc(stock.strategies.slice(0, 2).join('、')) : '') + '</div></div>' +
                '<div class="watchlist-actions"><button type="button" data-workspace-action="research" data-code="' + esc(stock.code) + '" data-name="' + esc(stock.name) + '">研究</button>' +
                '<button type="button" data-workspace-action="watch" data-code="' + esc(stock.code) + '" data-name="' + esc(stock.name) + '" aria-pressed="true">移除</button></div></article>';
        }).join('') + '</div>';
        syncWatchButtons();
    }

    function updateWatchlist(stock) {
        watchlist = toggleWatchlist(watchlist, stock);
        saveArray(WATCH_KEY, watchlist);
        syncWatchButtons();
        renderWatchlist();
        fetchAlerts();
    }

    function addCardActions(card) {
        if (!card || card.querySelector('[data-workspace-action]')) return;
        const code = String(card.dataset.code || '');
        const nameNode = card.querySelector('.name');
        const name = nameNode ? nameNode.textContent.trim() : code;
        if (!/^\d{6}$/.test(code)) return;
        let side = card.querySelector('.card-side');
        const score = card.querySelector('.card-score');
        if (!side) {
            side = document.createElement('div');
            side.className = 'card-side';
            if (score) side.appendChild(score);
            card.appendChild(side);
        }
        const actions = document.createElement('div');
        actions.className = 'card-actions';
        actions.innerHTML = '<button type="button" data-workspace-action="watch" data-code="' + esc(code) + '" data-name="' + esc(name) + '" aria-label="收藏' + esc(name) + '" title="加入个人观察">☆</button>' +
            '<button type="button" data-workspace-action="research" data-code="' + esc(code) + '" data-name="' + esc(name) + '" aria-label="研究' + esc(name) + '" title="打开个股研究">研</button>';
        side.appendChild(actions);
    }

    function decorateCards() {
        document.querySelectorAll('.stock-card').forEach(addCardActions);
        syncWatchButtons();
    }

    async function getJson(url) {
        const response = await global.fetch(url, { cache: 'no-store' });
        const data = await response.json();
        if (!response.ok || data.success === false) throw new Error(data.error || '请求失败');
        return data;
    }

    function closeDrawers() {
        ['researchDrawer', 'workspaceUtilityDrawer'].forEach(id => {
            const drawer = document.getElementById(id);
            if (drawer) drawer.hidden = true;
        });
        const backdrop = document.getElementById('workspaceDrawerBackdrop');
        if (backdrop) backdrop.hidden = true;
        document.body.classList.remove('drawer-open');
    }

    function openDrawer(id) {
        closeDrawers();
        const drawer = document.getElementById(id);
        const backdrop = document.getElementById('workspaceDrawerBackdrop');
        if (!drawer || !backdrop) return;
        drawer.hidden = false;
        backdrop.hidden = false;
        document.body.classList.add('drawer-open');
        const close = drawer.querySelector('.drawer-close');
        if (close) close.focus();
    }

    function renderScore(explanation) {
        const labels = { base: '基础分', sector: '板块修正', market: '市场修正', strategy: '策略修正', confidence: '置信度修正', sellPenalty: '卖出信号扣分' };
        const breakdown = explanation && explanation.breakdown || {};
        const rows = Object.keys(breakdown).map(key => '<div class="research-detail-row"><span>' + esc(labels[key] || key) + '</span><b>' + (Number(breakdown[key]) > 0 ? '+' : '') + esc(breakdown[key]) + '</b></div>');
        if (!rows.length && explanation && explanation.evidence) {
            rows.push('<div class="research-detail-row"><span>命中策略</span><b>' + Number(explanation.evidence.strategyCount || 0) + ' 个</b></div>');
            rows.push('<div class="research-detail-row"><span>信号分类</span><b>' + esc((explanation.evidence.categories || []).join('、') || '暂无') + '</b></div>');
        }
        return '<section class="research-section"><div class="research-section-head"><h3>评分依据</h3><strong>' + esc(explanation && explanation.total != null ? explanation.total : '--') + ' 分</strong></div>' + rows.join('') + '<p class="research-note">' + esc(explanation && explanation.note || '') + '</p></section>';
    }

    function renderResearch(data) {
        const current = data.current || {};
        const body = document.getElementById('researchDrawerBody');
        document.getElementById('researchDrawerTitle').textContent = (current.name || data.code) + ' ' + data.code;
        document.getElementById('researchDrawerSubtitle').textContent = '更新时间 ' + (current.dataTime || '--') + ' · ' + (current.sources || []).join(' / ');
        const pct = Number(current.pct);
        const signalHtml = (data.signals || []).map(signal => '<article class="research-signal"><b>' + esc(signal.source) + '</b><span>' + esc((signal.strategies || []).join('、') || '当前命中') + '</span>' +
            ((signal.reasons || []).length ? '<p>' + esc(signal.reasons.slice(0, 4).join('；')) + '</p>' : '') + '</article>').join('');
        const historyHtml = (data.historyStats || []).map(item => '<div class="research-detail-row"><span>' + esc(item.strategy) + '</span><b>' + fmt(item.historyWinRate) + '% · ' + Number(item.historyEvaluated || 0) + '条</b></div>').join('');
        const money = data.moneyFlow;
        const moneyHtml = money ? '<section class="research-section"><h3>主力资金</h3><div class="research-detail-row"><span>累计净额</span><b class="' + (Number(money.mainNetInflow) >= 0 ? 'pct-up' : 'pct-down') + '">' + fmt(Number(money.mainNetInflow) / 10000, 0) + ' 万</b></div><div class="research-detail-row"><span>净流入占比</span><b>' + fmt(money.mainNetRatio) + '%</b></div><p class="research-note">' + esc(money.updatedAt || '--') + (money.stale ? ' · 数据已过期' : '') + '</p></section>' : '';
        body.innerHTML = '<div class="research-quote-grid"><div><span>最新价格</span><b>' + (current.price == null ? '--' : '¥' + fmt(current.price)) + '</b></div><div><span>涨跌幅</span><b class="' + (pct >= 0 ? 'pct-up' : 'pct-down') + '">' + (current.pct == null ? '--' : (pct >= 0 ? '+' : '') + fmt(pct) + '%') + '</b></div><div><span>行业</span><b>' + esc(current.industry || '暂无') + '</b></div><div><span>评分</span><b>' + esc(current.score == null ? '--' : current.score) + '</b></div></div>' +
            '<section class="research-section"><h3>当前信号</h3>' + (signalHtml || '<p class="research-note">当前没有日报或盘中信号</p>') + '</section>' +
            renderScore(data.scoreExplanation || {}) + moneyHtml +
            (historyHtml ? '<section class="research-section"><h3>对应策略历史统计</h3>' + historyHtml + '</section>' : '') +
            '<section class="research-section"><div class="research-section-head"><h3>近期日线</h3><span>' + (data.klineAvailable ? '本地行情缓存' : '暂无缓存') + '</span></div><div id="researchKline" class="research-kline"><div class="research-note">正在加载日线…</div></div></section>';
        if (data.klineAvailable) {
            getJson('/api/stock/' + encodeURIComponent(data.code) + '/kline').then(kline => {
                const box = document.getElementById('researchKline');
                if (!box) return;
                const image = document.createElement('img');
                image.alt = data.code + ' 近期日线图';
                box.innerHTML = '';
                box.appendChild(image);
                if (typeof global.drawKline === 'function') global.drawKline(data.code, kline.data || [], image);
            }).catch(() => {
                const box = document.getElementById('researchKline');
                if (box) box.innerHTML = '<p class="research-note">日线暂时加载失败</p>';
            });
        }
    }

    function openResearch(code, name) {
        openDrawer('researchDrawer');
        document.getElementById('researchDrawerTitle').textContent = name || code;
        document.getElementById('researchDrawerSubtitle').textContent = '正在汇总现有行情、信号与评分依据';
        document.getElementById('researchDrawerBody').innerHTML = '<div class="empty state-panel state-loading"><div class="icon">📊</div><div class="text">正在整理个股资料…</div></div>';
        getJson('/api/stock/' + encodeURIComponent(code) + '/research').then(renderResearch).catch(error => {
            document.getElementById('researchDrawerBody').innerHTML = '<div class="empty state-panel state-error"><div class="icon">⚠️</div><div class="text">个股资料加载失败</div><div class="hint">' + esc(error.message) + '</div></div>';
        });
    }

    function renderAlerts(markRead) {
        const title = document.getElementById('utilityDrawerTitle');
        const subtitle = document.getElementById('utilityDrawerSubtitle');
        const body = document.getElementById('utilityDrawerBody');
        title.textContent = '信号提醒';
        subtitle.textContent = '仅提醒当前浏览器观察池中的股票';
        const state = uniqueAlerts(currentAlerts, readAlertIds);
        if (!state.all.length) {
            body.innerHTML = '<div class="empty state-panel"><div class="icon">🔔</div><div class="text">暂无观察池信号</div><div class="hint">收藏股票后，日报或盘中命中会显示在这里</div></div>';
        } else {
            body.innerHTML = '<div class="alert-list">' + state.all.map(alert => '<article class="alert-item' + (state.unread.includes(alert) ? ' is-unread' : '') + '"><span class="alert-dot"></span><div><b>' + esc(alert.name) + ' <small>' + esc(alert.code) + '</small></b><p>' + esc(alert.title) + ' · ' + esc(alert.message) + '</p><time>' + esc(alert.time || '--') + '</time></div></article>').join('') + '</div>';
        }
        if (markRead) {
            readAlertIds = Array.from(new Set(readAlertIds.concat(state.all.map(alert => String(alert.id))))).slice(-500);
            saveArray(READ_KEY, readAlertIds);
            updateAlertBadge();
        }
    }

    function updateAlertBadge() {
        const badge = document.getElementById('alertUnreadBadge');
        if (!badge) return;
        const unread = uniqueAlerts(currentAlerts, readAlertIds).unread.length;
        badge.textContent = String(unread);
        badge.hidden = unread === 0;
    }

    function fetchAlerts() {
        if (!watchlist.length) {
            currentAlerts = [];
            updateAlertBadge();
            return Promise.resolve([]);
        }
        return getJson('/api/workspace/alerts?codes=' + encodeURIComponent(watchlist.map(item => item.code).join(','))).then(data => {
            currentAlerts = data.alerts || [];
            updateAlertBadge();
            return currentAlerts;
        }).catch(() => {
            currentAlerts = [];
            updateAlertBadge();
            return [];
        });
    }

    function openAlerts() {
        openDrawer('workspaceUtilityDrawer');
        renderAlerts(true);
    }

    function renderSources(data) {
        const title = document.getElementById('utilityDrawerTitle');
        const subtitle = document.getElementById('utilityDrawerSubtitle');
        const body = document.getElementById('utilityDrawerBody');
        title.textContent = '数据源状态';
        subtitle.textContent = data.degraded ? '部分数据已降级，其他模块仍可使用' : '全部展示数据源可用';
        body.innerHTML = '<div class="source-list">' + Object.values(data.sources || {}).map(source => '<article class="source-item source-' + esc(source.status) + '"><span class="source-status-dot"></span><div><b>' + esc(source.label) + '</b><p>' + esc(source.message) + '</p><time>' + esc(source.dataTime || '暂无更新时间') + ' · ' + esc(source.file) + '</time></div><strong>' + esc(source.status) + '</strong></article>').join('') + '</div>';
    }

    function openSources() {
        openDrawer('workspaceUtilityDrawer');
        document.getElementById('utilityDrawerTitle').textContent = '数据源状态';
        document.getElementById('utilityDrawerBody').innerHTML = '<div class="empty state-panel state-loading"><div class="icon">◉</div><div class="text">正在检查数据源…</div></div>';
        getJson('/api/workspace/overview').then(renderSources).catch(error => {
            document.getElementById('utilityDrawerBody').innerHTML = '<div class="empty state-panel state-error"><div class="icon">⚠️</div><div class="text">状态检查失败</div><div class="hint">' + esc(error.message) + '</div></div>';
        });
    }

    function renderSearchResults(rows) {
        const results = document.getElementById('globalSearchResults');
        const input = document.getElementById('globalStockSearch');
        if (!results || !input) return;
        if (!rows.length) {
            results.innerHTML = '<div class="search-empty">没有找到本地股票资料</div>';
        } else {
            results.innerHTML = rows.map(stock => '<div class="search-result" role="option"><button type="button" class="search-result-main" data-workspace-action="research" data-code="' + esc(stock.code) + '" data-name="' + esc(stock.name) + '"><span><b>' + esc(stock.name) + '</b><small>' + esc(stock.code) + ' · ' + esc(stock.industry || '行业暂无') + '</small></span><strong class="' + (Number(stock.pct) >= 0 ? 'pct-up' : 'pct-down') + '">' + (stock.pct == null ? '--' : (Number(stock.pct) >= 0 ? '+' : '') + fmt(stock.pct) + '%') + '</strong></button><button type="button" class="search-watch" data-workspace-action="watch" data-code="' + esc(stock.code) + '" data-name="' + esc(stock.name) + '" aria-label="收藏' + esc(stock.name) + '">☆</button></div>').join('');
        }
        results.hidden = false;
        input.setAttribute('aria-expanded', 'true');
        syncWatchButtons();
    }

    let searchTimer = 0;
    function onSearch(event) {
        global.clearTimeout(searchTimer);
        const query = event.target.value.trim();
        const results = document.getElementById('globalSearchResults');
        if (!query) {
            results.hidden = true;
            event.target.setAttribute('aria-expanded', 'false');
            return;
        }
        searchTimer = global.setTimeout(() => {
            getJson('/api/stocks/search?q=' + encodeURIComponent(query) + '&limit=12')
                .then(data => renderSearchResults(data.results || []))
                .catch(() => renderSearchResults([]));
        }, 180);
    }

    function init() {
        const search = document.getElementById('globalStockSearch');
        if (search) search.addEventListener('input', onSearch);
        document.addEventListener('click', event => {
            const action = event.target.closest('[data-workspace-action]');
            if (action) {
                event.preventDefault();
                event.stopPropagation();
                const stock = stockFromElement(action);
                if (action.dataset.workspaceAction === 'watch') updateWatchlist(stock);
                else if (stock) openResearch(stock.code, stock.name);
                const results = document.getElementById('globalSearchResults');
                if (results && action.closest('.search-result')) results.hidden = true;
                return;
            }
            const results = document.getElementById('globalSearchResults');
            if (results && !event.target.closest('.global-search-wrap')) results.hidden = true;
        }, true);
        document.querySelectorAll('[data-drawer-close]').forEach(button => button.addEventListener('click', closeDrawers));
        document.getElementById('workspaceDrawerBackdrop').addEventListener('click', closeDrawers);
        document.getElementById('alertCenterButton').addEventListener('click', openAlerts);
        document.getElementById('sourceStatusButton').addEventListener('click', openSources);
        document.querySelector('[data-tab="watchlist"]').addEventListener('click', renderWatchlist);
        document.addEventListener('keydown', event => { if (event.key === 'Escape') closeDrawers(); });
        const observer = new MutationObserver(decorateCards);
        const intraday = document.getElementById('intradayContent');
        if (intraday) observer.observe(intraday, { childList: true, subtree: true });
        decorateCards();
        renderWatchlist();
        fetchAlerts();
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, { once: true });
    else init();
}(typeof window !== 'undefined' ? window : globalThis));
