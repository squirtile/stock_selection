(function (global) {
    'use strict';

    const WATCH_KEY = 'strategy-lab-watchlist-v1';
    const READ_KEY = 'strategy-lab-read-alerts-v1';

    const STRATEGY_GLOSSARY = [
        { keys: ['缠论二买', '缠论2买'], title: '缠论二买', logic: '下跌段结束后出现第一类买点反弹，回调未创新低并再次转强。', period: '当前系统主要观察 30 分钟与 60 分钟周期。', environment: '更适合趋势企稳、回调结构清晰且成交不过度失真的阶段。', risks: '结构可能继续延伸或重新破底，盘中未完成形态可能发生变化。' },
        { keys: ['缠论三买', '缠论3买'], title: '缠论三买', logic: '价格离开中枢后回踩不重新进入中枢，并出现继续上行信号。', period: '当前系统主要观察 30 分钟与 60 分钟周期。', environment: '更适合已有上升结构、突破后回踩确认的行情。', risks: '假突破、回踩重新进入中枢及高位追涨风险。' },
        { keys: ['MACD金叉背离', 'MACD金叉底背离'], title: 'MACD 金叉背离', logic: '价格与动能出现底背离特征，同时 MACD 形成金叉确认。', period: '当前系统主要用于 30 分钟与 60 分钟结构。', environment: '适合下跌动能衰减、市场风险偏好趋稳的阶段。', risks: '背离可能连续钝化，金叉也可能在弱势趋势中快速失效。' },
        { keys: ['二波埋伏', '二波形态'], title: '二波埋伏', logic: '第一波上涨后回调整理，寻找量价企稳与潜在二次启动结构。', period: '以日线结构为主，结合盘中信号观察。', environment: '适合主线仍有持续性、回调缩量且关键位置未破坏的市场。', risks: '题材退潮、回调转为趋势反转或二次启动失败。' },
        { keys: ['主升-大阳回调不破10日线'], title: '主升回调不破 10 日线', logic: '大阳线或主升启动后回调，价格仍守住 10 日均线附近。', period: '日线策略。', environment: '适合趋势明确、板块有延续且回调有承接的行情。', risks: '均线支撑失效、主升结束或高位补跌。' },
        { keys: ['底部稳定量能', '底部放量'], title: '底部稳定量能与放量', logic: '底部阶段量能长期平稳后出现明显放量，并参考前期试盘痕迹。', period: '日线筛选，盘中观察当日量能确认。', environment: '适合低位整理充分、波动收敛后出现资金关注的阶段。', risks: '放量可能来自出货或事件冲击，低位结构也可能继续下移。' }
    ];

    function escapeText(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function findStrategyDefinition(name) {
        const text = String(name || '').replace(/\s/g, '');
        return STRATEGY_GLOSSARY.find(item => item.keys.some(key => text.includes(key))) || {
            title: String(name || '策略标签'),
            logic: '该标签由现有策略规则计算生成，具体条件以当前策略实现为准。',
            period: '以标签标注或当前扫描周期为准。',
            environment: '需结合趋势、量价和整体市场环境综合观察。',
            risks: '规则信号可能失效，且不代表未来收益概率。'
        };
    }

    function searchStateMarkup(state, query, message) {
        const safeQuery = escapeText(query);
        if (state === 'loading') return '<div class="search-empty search-loading">正在搜索“' + safeQuery + '”…</div>';
        if (state === 'error') return '<div class="search-empty search-error">搜索失败：' + escapeText(message || '接口暂时不可用') + '<button type="button" class="search-retry" data-search-retry>重新搜索</button></div>';
        return '<div class="search-empty">没有找到“' + safeQuery + '”的本地股票资料</div>';
    }

    function marketSessionText(session) {
        const value = session || {};
        if (value.displayText) return String(value.displayText);
        const day = value.latestTradeDate || '--';
        if (value.state === 'closed') return '最近交易日：' + day + ' · 市场休市中 · 下次更新：开市日 18:30';
        return '最近交易日：' + day + ' · ' + (value.stateLabel || '数据状态待确认') + ' · 最后成功更新：' + (value.lastSuccessAt || '--');
    }

    function clearExpandedCharts(root) {
        if (!root || typeof root.querySelectorAll !== 'function') return;
        root.querySelectorAll('.kline-area').forEach(area => area.remove());
        root.querySelectorAll('.stock-card.is-expanded').forEach(card => card.classList.remove('is-expanded'));
    }

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
        const rawCode = String(stock && stock.code || '').replace(/\D/g, '');
        if (!rawCode || rawCode.length > 6) return null;
        const code = rawCode.padStart(6, '0');
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

    function selectStrategyKeys(selected, key, maxSelected) {
        const current = Array.isArray(selected) ? selected.map(String) : [];
        const value = String(key || '');
        const index = current.indexOf(value);
        if (index >= 0) return current.filter(item => item !== value);
        if (!value || current.length >= Math.max(1, Number(maxSelected) || 4)) return current;
        return current.concat(value);
    }

    function buildStrategyComparison(rows, selected) {
        const wanted = new Set((Array.isArray(selected) ? selected : []).map(String));
        return (Array.isArray(rows) ? rows : []).filter(row => wanted.has(String(row.strategy))).map(row => ({
            strategy: String(row.strategy || ''),
            winRate: row.historyWinRate == null ? null : Number(row.historyWinRate),
            avgPct: row.historyAvgPct == null ? null : Number(row.historyAvgPct),
            sample: Number(row.historyEvaluated || 0),
            reviewDays: Number(row.reviewDays || 0)
        }));
    }

    function marketOverviewModel(payload) {
        const data = payload || {};
        const breadth = data.breadth || {};
        const totalSources = Number(data.totalSources || 0);
        const healthySources = Number(data.healthySources || 0);
        const hasBreadth = breadth.status !== 'missing' && breadth.status !== 'error' && Number(breadth.total || 0) > 0;
        return {
            state: data.degraded || !hasBreadth ? 'degraded' : 'ok',
            sourceText: healthySources + '/' + totalSources + ' 数据源可用',
            breadthText: hasBreadth ? '上涨 ' + Number(breadth.advances || 0) + ' / 下跌 ' + Number(breadth.declines || 0) : '市场宽度暂无',
            limitText: hasBreadth ? '涨停 ' + Number(breadth.limitUp || 0) + ' / 跌停 ' + Number(breadth.limitDown || 0) : '涨停强度暂无',
            medianText: breadth.medianPct == null ? '中位涨幅 --' : '中位涨幅 ' + (Number(breadth.medianPct) >= 0 ? '+' : '') + Number(breadth.medianPct).toFixed(2) + '%',
            temperature: hasBreadth ? String(breadth.temperature || '暂无') : '暂无',
            stale: Boolean(breadth.stale),
            tradeDate: String(breadth.tradeDate || '')
        };
    }

    function updateWatchButton(button, active) {
        if (!button) return;
        const label = active ? '★' : '☆';
        button.classList.toggle('is-watched', active);
        if (button.textContent !== label) button.textContent = label;
        button.title = active ? '移出个人观察' : '加入个人观察';
        button.setAttribute('aria-pressed', active ? 'true' : 'false');
    }

    const api = { loadStoredArray, toggleWatchlist, uniqueAlerts, selectStrategyKeys, buildStrategyComparison, marketOverviewModel, updateWatchButton, findStrategyDefinition, searchStateMarkup, marketSessionText, clearExpandedCharts, buildDailySummary };
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
    let overviewCache = null;
    let selectedStrategies = [];
    let alertsLoadError = '';
    let lastSearchQuery = '';
    let searchRequestId = 0;

    const esc = escapeText;
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
            updateWatchButton(button, active);
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
        fetchAlerts().catch(() => {});
    }

    function addCardActions(card) {
        if (!card) return;
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
        if (!side.querySelector('[data-workspace-action="score-info"]')) {
            const scoreHelp = document.createElement('button');
            scoreHelp.type = 'button';
            scoreHelp.className = 'score-help';
            scoreHelp.dataset.workspaceAction = 'score-info';
            scoreHelp.dataset.code = code;
            scoreHelp.dataset.name = name;
            scoreHelp.textContent = '评分说明';
            side.appendChild(scoreHelp);
        }
        if (side.querySelector('.card-actions')) return;
        const actions = document.createElement('div');
        actions.className = 'card-actions';
        actions.innerHTML = '<button type="button" data-workspace-action="watch" data-code="' + esc(code) + '" data-name="' + esc(name) + '" aria-label="收藏' + esc(name) + '" title="加入个人观察">☆</button>' +
            '<button type="button" data-workspace-action="research" data-code="' + esc(code) + '" data-name="' + esc(name) + '" aria-label="研究' + esc(name) + '" title="打开个股研究">研</button>';
        side.appendChild(actions);
    }

    function decorateStrategyTags() {
        document.querySelectorAll('.s-tag:not([data-strategy-info])').forEach(tag => {
            tag.dataset.strategyInfo = tag.textContent.trim();
            tag.setAttribute('role', 'button');
            tag.setAttribute('tabindex', '0');
            tag.setAttribute('title', '查看策略释义');
        });
    }

    function decorateCards() {
        document.querySelectorAll('.stock-card').forEach(addCardActions);
        decorateStrategyTags();
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

    function showUtility(title, subtitle, html) {
        openDrawer('workspaceUtilityDrawer');
        document.getElementById('utilityDrawerTitle').textContent = title;
        document.getElementById('utilityDrawerSubtitle').textContent = subtitle;
        document.getElementById('utilityDrawerBody').innerHTML = html;
    }

    function openMethodology() {
        showUtility('数据与回测口径', '理解评分、胜率、涨幅和更新时间的含义',
            '<section class="research-section"><h3>策略与评分</h3><p class="research-note">策略结果来自既有规则对历史或当前行情的计算。评分综合趋势、量价、策略共振、板块热度和资金表现等现有维度，仅用于研究排序，不代表未来收益概率或投资建议。</p></section>' +
            '<section class="research-section"><h3>历史统计</h3><p class="research-note">胜率必须结合页面显示的命中数/已评价样本数、统计区间和观察周期理解；平均涨幅按已评价样本计算。样本少、市场环境变化或数据缺失都会造成偏差，历史表现不代表未来收益。</p></section>' +
            '<section class="research-section"><h3>行情与更新时间</h3><p class="research-note">盘中实时、盘后快照与延迟数据按最后成功时间区分。接口失败时页面可能继续展示最近快照，并明确标记延迟；页面刷新时间不等于行情成功更新时间。</p></section>' +
            '<div class="drawer-disclaimer">以上信息仅用于方法说明，请独立判断并自行承担风险。</div>');
    }

    function openStrategyDefinition(name) {
        const item = findStrategyDefinition(name);
        showUtility(item.title, '策略标签释义 · 不改变原有策略条件',
            '<section class="research-section definition-grid"><div><span>核心逻辑</span><p>' + esc(item.logic) + '</p></div><div><span>适用周期</span><p>' + esc(item.period) + '</p></div><div><span>适用环境</span><p>' + esc(item.environment) + '</p></div><div><span>主要风险</span><p>' + esc(item.risks) + '</p></div></section>' +
            '<div class="drawer-disclaimer">策略释义用于帮助理解标签，不构成荐股或收益承诺。</div>');
    }

    function openScoreInfo(code, name) {
        showUtility('评分说明', (name || code) + ' · 评分仅用于研究排序',
            '<div class="empty state-panel state-loading"><div class="icon">📐</div><div class="text">正在读取评分依据…</div></div>');
        getJson('/api/stock/' + encodeURIComponent(code) + '/research').then(data => {
            document.getElementById('utilityDrawerBody').innerHTML =
                '<section class="research-section"><h3>构成维度</h3><p class="research-note">综合现有策略中的趋势、量价、策略共振、板块热度、资金表现及置信度修正。没有数据的维度不会被臆测补齐。</p></section>' +
                renderScore(data.scoreExplanation || {}) +
                '<div class="drawer-disclaimer">评分仅用于研究结果排序，不代表上涨概率、未来收益或投资建议。</div>';
        }).catch(error => {
            document.getElementById('utilityDrawerBody').innerHTML = '<div class="empty state-panel state-error"><div class="icon">⚠️</div><div class="text">评分依据加载失败</div><div class="hint">' + esc(error.message) + '</div><button type="button" class="state-action" data-score-retry data-code="' + esc(code) + '" data-name="' + esc(name) + '">重试</button></div>';
        });
    }

    function buildDailySummary(data) {
        const summary = data && data.shareSummary || {};
        const metrics = summary.metrics || {};
        return '策略实验室｜每日市场摘要\n' +
            '最近交易日：' + (summary.tradeDate || '--') + ' · ' + (summary.status || '状态待确认') + '\n' +
            '上涨 ' + Number(metrics.advances || 0) + ' / 下跌 ' + Number(metrics.declines || 0) +
            ' · 涨停 ' + Number(metrics.limitUp || 0) + ' / 跌停 ' + Number(metrics.limitDown || 0) +
            ' · 市场温度 ' + (metrics.temperature || '暂无') + '\n' +
            (summary.disclaimer || '仅供研究，不构成投资建议。');
    }

    function openDailySummary() {
        showUtility('每日市场摘要', '已预留分享卡片数据，不会自动发布',
            '<div class="empty state-panel state-loading"><div class="icon">🗒️</div><div class="text">正在整理摘要…</div></div>');
        const promise = overviewCache ? Promise.resolve(overviewCache) : getJson('/api/workspace/overview');
        promise.then(data => {
            overviewCache = data;
            const summary = buildDailySummary(data);
            document.getElementById('utilityDrawerBody').innerHTML = '<section class="daily-summary-card"><pre>' + esc(summary) + '</pre><button type="button" class="state-action" data-copy-summary>复制摘要</button></section><p class="research-note">这里仅生成可复制的研究摘要，不执行任何自动发布。</p>';
        }).catch(error => {
            document.getElementById('utilityDrawerBody').innerHTML = '<div class="empty state-panel state-error"><div class="icon">⚠️</div><div class="text">摘要生成失败</div><div class="hint">' + esc(error.message) + '</div><button type="button" class="state-action" data-summary-retry>重试</button></div>';
        });
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
        subtitle.textContent = '观察池、已读状态均仅保存在当前浏览器';
        const state = uniqueAlerts(currentAlerts, readAlertIds);
        const notice = '<div class="browser-storage-notice">触发条件：观察池股票进入每日策略或盘中实时结果。提醒与已读状态不会云端同步，清理浏览器数据后可能丢失。</div>';
        if (alertsLoadError) {
            body.innerHTML = notice + '<div class="empty state-panel state-error"><div class="icon">⚠️</div><div class="text">提醒加载失败</div><div class="hint">' + esc(alertsLoadError) + '</div><button type="button" class="state-action" data-alerts-retry>重试</button></div>';
        } else if (!state.all.length) {
            body.innerHTML = notice + '<div class="empty state-panel"><div class="icon">🔔</div><div class="text">暂无观察池信号</div><div class="hint">收藏股票后，命中上述条件时会显示在这里</div></div>';
        } else {
            body.innerHTML = notice + '<div class="alert-list">' + state.all.map(alert => '<article class="alert-item' + (state.unread.includes(alert) ? ' is-unread' : '') + '"><span class="alert-dot"></span><div><b>' + esc(alert.name) + ' <small>' + esc(alert.code) + '</small></b><p>' + esc(alert.title) + ' · ' + esc(alert.message) + '</p><time>' + esc(alert.time || '--') + '</time></div></article>').join('') + '</div>';
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
            alertsLoadError = '';
            updateAlertBadge();
            return Promise.resolve([]);
        }
        return getJson('/api/workspace/alerts?codes=' + encodeURIComponent(watchlist.map(item => item.code).join(','))).then(data => {
            currentAlerts = data.alerts || [];
            alertsLoadError = '';
            updateAlertBadge();
            return currentAlerts;
        }).catch(error => {
            currentAlerts = [];
            alertsLoadError = error.message || '接口暂时不可用';
            updateAlertBadge();
            throw error;
        });
    }

    function openAlerts() {
        openDrawer('workspaceUtilityDrawer');
        document.getElementById('utilityDrawerTitle').textContent = '信号提醒';
        document.getElementById('utilityDrawerSubtitle').textContent = '观察池、已读状态均仅保存在当前浏览器';
        document.getElementById('utilityDrawerBody').innerHTML = '<div class="empty state-panel state-loading"><div class="icon">🔔</div><div class="text">正在读取提醒…</div></div>';
        fetchAlerts().then(() => renderAlerts(true)).catch(() => renderAlerts(false));
    }

    function renderSources(data) {
        const title = document.getElementById('utilityDrawerTitle');
        const subtitle = document.getElementById('utilityDrawerSubtitle');
        const body = document.getElementById('utilityDrawerBody');
        title.textContent = '数据源状态';
        subtitle.textContent = data.degraded ? '部分数据已降级，其他模块仍可使用' : '全部展示数据源可用';
        const statusNames = { ok: '正常', stale: '延迟', future: '时间异常', missing: '缺失', error: '错误' };
        const session = data.marketSession || {};
        body.innerHTML = '<div class="source-session"><b>' + esc(marketSessionText(session)) + '</b><span>交易日历：' + esc(session.calendarSource || '本地状态判断') + '</span></div><div class="source-list">' + Object.values(data.sources || {}).map(source => '<article class="source-item source-' + esc(source.status) + '"><span class="source-status-dot"></span><div><b>' + esc(source.sourceName || source.label) + '</b><p>状态：' + esc(source.statusLabel || statusNames[source.status] || source.status) + ' · 是否延迟：' + (source.delayed ? '是' : '否') + '</p><p>' + esc(source.failureReason || source.message) + '</p><time>最后成功更新：' + esc(source.lastSuccessAt || '暂无') + '<br>来源文件：' + esc(source.file) + '</time></div><strong>' + esc(statusNames[source.status] || source.status) + '</strong></article>').join('') + '</div><button type="button" class="state-action source-retry" data-source-retry>重新检查</button>';
    }

    function openSources() {
        openDrawer('workspaceUtilityDrawer');
        document.getElementById('utilityDrawerTitle').textContent = '数据源状态';
        document.getElementById('utilityDrawerBody').innerHTML = '<div class="empty state-panel state-loading"><div class="icon">◉</div><div class="text">正在检查数据源…</div></div>';
        getJson('/api/workspace/overview').then(data => {
            overviewCache = data;
            renderSources(data);
        }).catch(error => {
            document.getElementById('utilityDrawerBody').innerHTML = '<div class="empty state-panel state-error"><div class="icon">⚠️</div><div class="text">状态检查失败</div><div class="hint">' + esc(error.message) + '</div><button type="button" class="state-action" data-source-retry>重试</button></div>';
        });
    }

    function renderMarketOverview(data) {
        overviewCache = data;
        const container = document.getElementById('marketOverview');
        if (!container) return;
        const model = marketOverviewModel(data);
        const status = document.getElementById('marketSessionStatus');
        if (status) status.textContent = marketSessionText(data.marketSession || {});
        container.className = 'market-overview market-overview-' + model.state;
        container.innerHTML = '<div class="market-pulse-title"><span class="pulse-dot"></span><b>市场温度 ' + esc(model.temperature) + '</b><small>' + esc(model.tradeDate || '日期暂无') + (model.stale ? ' · 历史快照' : '') + '</small></div>' +
            '<div class="market-pulse-metrics"><span>' + esc(model.breadthText) + '</span><span>' + esc(model.limitText) + '</span><span>' + esc(model.medianText) + '</span><button type="button" id="overviewSourceButton">' + esc(model.sourceText) + '</button></div>';
        const button = document.getElementById('overviewSourceButton');
        if (button) button.addEventListener('click', openSources);
    }

    function loadOverview() {
        return getJson('/api/workspace/overview').then(renderMarketOverview).catch(() => {
            const container = document.getElementById('marketOverview');
            if (container) {
                container.className = 'market-overview market-overview-degraded';
                container.innerHTML = '<span class="pulse-dot"></span><b>市场概览暂时不可用</b><span>未确认最新行情状态，请勿将旧快照视为实时</span><button type="button" class="state-action" data-overview-retry>重试</button>';
            }
            const status = document.getElementById('marketSessionStatus');
            if (status) status.textContent = '最近交易日：-- · 数据状态确认失败，请重试';
        });
    }

    function renderStrategyComparison() {
        const rows = Array.isArray(embedded.strategies) ? embedded.strategies : [];
        const choices = document.getElementById('strategyCompareChoices');
        const result = document.getElementById('strategyCompareResult');
        if (!choices || !result) return;
        if (!rows.length) {
            choices.innerHTML = '';
            result.innerHTML = '<div class="research-note">暂无可比较的历史策略数据</div>';
            return;
        }
        const atLimit = selectedStrategies.length >= 4;
        choices.innerHTML = rows.map(row => {
            const key = String(row.strategy || '');
            const checked = selectedStrategies.includes(key);
            return '<label class="strategy-choice' + (checked ? ' is-selected' : '') + '"><input type="checkbox" value="' + esc(key) + '"' + (checked ? ' checked' : '') + (!checked && atLimit ? ' disabled' : '') + '><span>' + esc(key) + '</span><small>' + fmt(row.historyWinRate) + '%</small></label>';
        }).join('');
        const compared = buildStrategyComparison(rows, selectedStrategies);
        if (compared.length < 2) {
            result.innerHTML = '<div class="strategy-compare-empty">再选择 ' + (2 - compared.length) + ' 个策略即可开始比较</div>';
            return;
        }
        result.innerHTML = '<div class="strategy-comparison-grid">' + compared.map(item => {
            const win = item.winRate == null ? 0 : Math.max(0, Math.min(100, item.winRate));
            return '<article class="strategy-comparison-card"><div class="comparison-name">' + esc(item.strategy) + '</div><div class="comparison-win"><b class="' + (win >= 50 ? 'pct-up' : 'pct-down') + '">' + fmt(item.winRate) + '%</b><span>历史胜率</span></div><div class="comparison-bar"><i style="width:' + win + '%"></i></div><dl><div><dt>平均涨幅</dt><dd class="' + (Number(item.avgPct) >= 0 ? 'pct-up' : 'pct-down') + '">' + (Number(item.avgPct) >= 0 ? '+' : '') + fmt(item.avgPct) + '%</dd></div><div><dt>样本量</dt><dd>' + item.sample + ' 条</dd></div><div><dt>观察周期</dt><dd>' + item.reviewDays + ' 天</dd></div></dl></article>';
        }).join('') + '</div>';
    }

    function initStrategyComparison() {
        const rows = Array.isArray(embedded.strategies) ? embedded.strategies : [];
        selectedStrategies = rows.slice(0, Math.min(3, rows.length)).map(row => String(row.strategy || '')).filter(Boolean);
        renderStrategyComparison();
        const choices = document.getElementById('strategyCompareChoices');
        if (!choices) return;
        choices.addEventListener('change', event => {
            if (!event.target.matches('input[type="checkbox"]')) return;
            selectedStrategies = selectStrategyKeys(selectedStrategies, event.target.value, 4);
            renderStrategyComparison();
        });
    }

    function renderSearchResults(rows, query) {
        const results = document.getElementById('globalSearchResults');
        const input = document.getElementById('globalStockSearch');
        if (!results || !input) return;
        if (!rows.length) {
            results.innerHTML = searchStateMarkup('empty', query || lastSearchQuery);
        } else {
            results.innerHTML = rows.map(stock => '<div class="search-result" role="option"><button type="button" class="search-result-main" data-workspace-action="research" data-code="' + esc(stock.code) + '" data-name="' + esc(stock.name) + '"><span><b>' + esc(stock.name) + '</b><small>' + esc(stock.code) + ' · ' + esc(stock.industry || '行业暂无') + '</small></span><strong class="' + (Number(stock.pct) >= 0 ? 'pct-up' : 'pct-down') + '">' + (stock.pct == null ? '--' : (Number(stock.pct) >= 0 ? '+' : '') + fmt(stock.pct) + '%') + '</strong></button><button type="button" class="search-watch" data-workspace-action="watch" data-code="' + esc(stock.code) + '" data-name="' + esc(stock.name) + '" aria-label="收藏' + esc(stock.name) + '">☆</button></div>').join('');
        }
        results.hidden = false;
        input.setAttribute('aria-expanded', 'true');
        syncWatchButtons();
    }

    let searchTimer = 0;
    function runSearch(query) {
        const results = document.getElementById('globalSearchResults');
        const input = document.getElementById('globalStockSearch');
        const requestId = ++searchRequestId;
        lastSearchQuery = query;
        results.innerHTML = searchStateMarkup('loading', query);
        results.hidden = false;
        input.setAttribute('aria-expanded', 'true');
        input.setAttribute('aria-busy', 'true');
        return getJson('/api/stocks/search?q=' + encodeURIComponent(query) + '&limit=12').then(data => {
            if (requestId !== searchRequestId) return;
            renderSearchResults(data.results || [], query);
        }).catch(error => {
            if (requestId !== searchRequestId) return;
            results.innerHTML = searchStateMarkup('error', query, error.message);
            results.hidden = false;
        }).finally(() => {
            if (requestId === searchRequestId) input.setAttribute('aria-busy', 'false');
        });
    }

    function onSearch(event) {
        global.clearTimeout(searchTimer);
        const query = event.target.value.trim();
        const results = document.getElementById('globalSearchResults');
        if (!query) {
            searchRequestId += 1;
            results.hidden = true;
            event.target.setAttribute('aria-expanded', 'false');
            return;
        }
        results.innerHTML = searchStateMarkup('loading', query);
        results.hidden = false;
        event.target.setAttribute('aria-expanded', 'true');
        searchTimer = global.setTimeout(() => runSearch(query), 180);
    }

    function init() {
        const search = document.getElementById('globalStockSearch');
        if (search) search.addEventListener('input', onSearch);
        document.addEventListener('click', event => {
            const strategyTag = event.target.closest('[data-strategy-info]');
            if (strategyTag) {
                event.preventDefault();
                event.stopPropagation();
                openStrategyDefinition(strategyTag.dataset.strategyInfo);
                return;
            }
            if (event.target.closest('[data-search-retry]')) { runSearch(lastSearchQuery); return; }
            if (event.target.closest('[data-source-retry]')) { openSources(); return; }
            if (event.target.closest('[data-overview-retry]')) { loadOverview(); return; }
            if (event.target.closest('[data-alerts-retry]')) { openAlerts(); return; }
            if (event.target.closest('[data-summary-retry]')) { openDailySummary(); return; }
            const scoreRetry = event.target.closest('[data-score-retry]');
            if (scoreRetry) { openScoreInfo(scoreRetry.dataset.code, scoreRetry.dataset.name); return; }
            if (event.target.closest('[data-copy-summary]')) {
                const text = event.target.closest('.daily-summary-card').querySelector('pre').textContent;
                if (global.navigator && global.navigator.clipboard) global.navigator.clipboard.writeText(text);
                event.target.textContent = '已复制';
                return;
            }
            const action = event.target.closest('[data-workspace-action]');
            if (action) {
                event.preventDefault();
                event.stopPropagation();
                const stock = stockFromElement(action);
                if (action.dataset.workspaceAction === 'watch') updateWatchlist(stock);
                else if (action.dataset.workspaceAction === 'score-info' && stock) openScoreInfo(stock.code, stock.name);
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
        document.getElementById('dailySummaryButton').addEventListener('click', openDailySummary);
        document.getElementById('methodologyButton').addEventListener('click', openMethodology);
        document.querySelectorAll('[data-open-methodology]').forEach(button => button.addEventListener('click', openMethodology));
        document.querySelectorAll('[data-open-summary]').forEach(button => button.addEventListener('click', openDailySummary));
        document.querySelector('[data-tab="watchlist"]').addEventListener('click', renderWatchlist);
        document.addEventListener('keydown', event => {
            if (event.key === 'Escape') closeDrawers();
            if ((event.key === 'Enter' || event.key === ' ') && event.target.matches('[data-strategy-info]')) {
                event.preventDefault();
                openStrategyDefinition(event.target.dataset.strategyInfo);
            }
        });
        const observer = new MutationObserver(decorateCards);
        const intraday = document.getElementById('intradayContent');
        if (intraday) observer.observe(intraday, { childList: true, subtree: true });
        decorateCards();
        renderWatchlist();
        fetchAlerts().catch(() => {});
        initStrategyComparison();
        loadOverview();
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, { once: true });
    else init();
}(typeof window !== 'undefined' ? window : globalThis));
