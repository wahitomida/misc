// ExhibiReport - Chart Rendering

/**
 * 分析チャートをレンダリング
 */
function renderAnalysisChart(container, type, data) {
    if (!container || !data) return;
    container.innerHTML = '';

    switch (type) {
        case 1: renderBarChart(container, data); break;
        case 2: renderDoughnutChart(container, data); break;
        case 3: renderMatrixTable(container, data); break;
        case 4: renderWordCloud(container, data); break;
        case 5: renderBubbleChart(container, data); break;
        case 6: renderNetworkGraph(container, data); break;
    }
}

// グローバルへ明示公開（Alpine 側から typeof チェックしても確実に見えるように）
window.renderAnalysisChart = renderAnalysisChart;

/**
 * ズーム・パン操作用コントロールバーを生成
 * @param {HTMLElement} container - チャートコンテナ
 * @param {object} handlers - {zoomIn, zoomOut, reset, fit?}
 * @returns {HTMLElement} コントロールバー要素
 */
function createZoomControls(handlers) {
    const bar = document.createElement('div');
    bar.className = 'flex items-center gap-1 mb-2 text-xs';
    bar.innerHTML = `
        <span class="text-slate-400 mr-1">🔍 スクロールでズーム / ドラッグで移動</span>
        <button type="button" data-act="in" class="px-2 py-0.5 rounded border border-slate-200 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-700" title="ズームイン">➕</button>
        <button type="button" data-act="out" class="px-2 py-0.5 rounded border border-slate-200 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-700" title="ズームアウト">➖</button>
        <button type="button" data-act="reset" class="px-2 py-0.5 rounded border border-slate-200 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-700" title="リセット">↻</button>
    `;
    bar.querySelector('[data-act="in"]').addEventListener('click', () => handlers.zoomIn && handlers.zoomIn());
    bar.querySelector('[data-act="out"]').addEventListener('click', () => handlers.zoomOut && handlers.zoomOut());
    bar.querySelector('[data-act="reset"]').addEventListener('click', () => handlers.reset && handlers.reset());
    return bar;
}

/**
 * 1. 関連度比較 - 横棒グラフ
 */
function renderBarChart(container, data) {
    const canvas = document.createElement('canvas');
    canvas.height = 300;
    container.appendChild(canvas);

    new Chart(canvas, {
        type: 'bar',
        data: {
            labels: data.labels || [],
            datasets: [{
                label: '関連度スコア',
                data: data.scores || [],
                backgroundColor: (data.scores || []).map(s =>
                    s >= 3 ? '#6366F1' : s >= 2 ? '#818CF8' : '#C7D2FE'
                ),
                borderRadius: 6,
                barThickness: 24,
            }],
        },
        options: {
            indexAxis: 'y',
            responsive: true,
            plugins: { legend: { display: false } },
            scales: {
                x: { max: 3, ticks: { stepSize: 1 }, grid: { color: 'rgba(0,0,0,0.05)' } },
                y: { grid: { display: false } },
            },
        },
    });
}

/**
 * 2. 業種・カテゴリ分布 - ドーナツチャート
 */
function renderDoughnutChart(container, data) {
    const canvas = document.createElement('canvas');
    canvas.height = 300;
    container.appendChild(canvas);

    const colors = ['#6366F1', '#8B5CF6', '#EC4899', '#F59E0B', '#10B981', '#06B6D4', '#F97316'];

    new Chart(canvas, {
        type: 'doughnut',
        data: {
            labels: data.labels || [],
            datasets: [{
                data: data.values || [],
                backgroundColor: colors.slice(0, (data.labels || []).length),
                borderWidth: 0,
            }],
        },
        options: {
            responsive: true,
            cutout: '60%',
            plugins: {
                legend: { position: 'right' },
            },
        },
    });

    // 中央に合計表示
    const total = document.createElement('div');
    total.className = 'text-center mt-2 text-sm text-slate-500';
    total.textContent = `合計: ${data.total || 0}社`;
    container.appendChild(total);
}

/**
 * 3. テーマ×企業マトリクス - テーブル
 */
function renderMatrixTable(container, data) {
    if (!data.themes || !data.companies || !data.matrix) return;

    let html = '<div class="overflow-x-auto"><table class="w-full text-xs border-collapse">';
    html += '<thead><tr><th class="p-2 text-left bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700">企業＼テーマ</th>';
    data.themes.forEach(t => { html += `<th class="p-2 text-center bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700">${t}</th>`; });
    html += '</tr></thead><tbody>';

    data.companies.forEach((company, i) => {
        const row = data.matrix[i] || [];
        html += `<tr class="${i % 2 === 0 ? 'bg-white dark:bg-slate-800' : 'bg-slate-50/50 dark:bg-slate-800/50'}">`;
        html += `<td class="p-2 font-medium border border-slate-200 dark:border-slate-700">${company}</td>`;
        row.forEach(cell => {
            const color = cell === '◎' ? 'text-primary font-bold' : cell === '○' ? 'text-blue-500' : 'text-slate-400';
            html += `<td class="p-2 text-center border border-slate-200 dark:border-slate-700 ${color}">${cell}</td>`;
        });
        html += '</tr>';
    });
    html += '</tbody></table></div>';
    container.innerHTML = html;
}

/**
 * 4. 技術トレンドワードクラウド
 */
function renderWordCloud(container, data) {
    if (!data.words || !d3 || !d3.layout) {
        // D3 cloud not available, fallback
        let html = '<div class="flex flex-wrap gap-2 justify-center p-4">';
        (data.words || []).forEach(w => {
            const size = Math.max(12, Math.min(36, w.size || 16));
            html += `<span class="px-2 py-1 rounded-lg bg-primary/10 text-primary font-medium" style="font-size:${size}px">${w.text}</span>`;
        });
        html += '</div>';
        container.innerHTML = html;
        return;
    }

    const width = container.clientWidth || 600;
    const height = 300;
    const words = data.words || [];

    const layout = d3.layout.cloud()
        .size([width, height])
        .words(words.map(w => ({ text: w.text, size: w.size || 20 })))
        .padding(5)
        .rotate(() => (~~(Math.random() * 2)) * 90)
        .fontSize(d => d.size)
        .on('end', draw);

    layout.start();

    function draw(words) {
        const svg = d3.select(container).append('svg')
            .attr('width', width)
            .attr('height', height)
            .append('g')
            .attr('transform', `translate(${width / 2},${height / 2})`);

        svg.selectAll('text')
            .data(words)
            .enter().append('text')
            .attr('class', 'word-cloud')
            .style('font-size', d => d.size + 'px')
            .style('fill', () => ['#6366F1', '#8B5CF6', '#EC4899', '#10B981', '#06B6D4'][~~(Math.random() * 5)])
            .style('font-weight', '600')
            .attr('text-anchor', 'middle')
            .attr('transform', d => `translate(${d.x},${d.y}) rotate(${d.rotate})`)
            .text(d => d.text);
    }
}

/**
 * 5. 企業規模×技術成熟度 - バブルチャート（ズーム・パン対応）
 */
function renderBubbleChart(container, data) {
    const canvas = document.createElement('canvas');
    canvas.height = 380;
    container.appendChild(canvas);

    const bubbles = data.bubbles || [];
    const colors = ['#6366F1', '#8B5CF6', '#EC4899', '#F59E0B', '#10B981', '#06B6D4', '#F97316', '#EF4444'];

    const hasZoom = typeof Chart !== 'undefined' && Chart.registry && Chart.registry.plugins.get('zoom');

    const chart = new Chart(canvas, {
        type: 'bubble',
        data: {
            datasets: bubbles.map((b, i) => ({
                label: b.name,
                data: [{ x: b.x, y: b.y, r: Math.max(8, b.size / 3) }],
                backgroundColor: colors[i % colors.length] + '80',
                borderColor: colors[i % colors.length],
                borderWidth: 2,
            })),
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: { title: { display: true, text: '企業規模' }, min: 0, max: 100 },
                y: { title: { display: true, text: '技術成熟度' }, min: 0, max: 100 },
            },
            plugins: {
                legend: { position: 'bottom' },
                tooltip: {
                    callbacks: {
                        label: (ctx) => `${ctx.dataset.label} (規模:${ctx.parsed.x}, 技術:${ctx.parsed.y})`,
                    },
                },
                ...(hasZoom ? {
                    zoom: {
                        pan: { enabled: true, mode: 'xy', modifierKey: null },
                        zoom: {
                            wheel: { enabled: true, speed: 0.1 },
                            pinch: { enabled: true },
                            drag: { enabled: false },
                            mode: 'xy',
                        },
                        limits: {
                            x: { min: -50, max: 150, minRange: 10 },
                            y: { min: -50, max: 150, minRange: 10 },
                        },
                    },
                } : {}),
            },
        },
    });

    if (hasZoom) {
        const controls = createZoomControls({
            zoomIn: () => chart.zoom(1.2),
            zoomOut: () => chart.zoom(0.8),
            reset: () => chart.resetZoom(),
        });
        container.insertBefore(controls, canvas);
        // canvasのサイズを明示（maintainAspectRatio:falseのため）
        canvas.style.maxHeight = '380px';
        canvas.parentElement.style.height = '420px';
    }
}

/**
 * 6. 企業間マップ - ネットワーク図
 * - ノード数に応じて高さを自動調整
 * - コンテナ幅にレスポンシブ（ResizeObserver で再描画）
 * - ノード半径はラベル長で動的算出
 */
function renderNetworkGraph(container, data) {
    if (!data.nodes || !data.links || typeof d3 === 'undefined') {
        container.innerHTML = '<p class="text-sm text-slate-400 text-center py-8">ネットワーク図を表示できません</p>';
        return;
    }
    if (data.nodes.length === 0) {
        container.innerHTML = '<p class="text-sm text-slate-400 text-center py-8">表示できる企業がありません</p>';
        return;
    }

    container.classList.add('network-graph-container');

    const draw = () => {
        container.innerHTML = '';
        const width = Math.max(container.clientWidth || 600, 320);
        const nodeCount = data.nodes.length;
        const height = Math.min(720, Math.max(320, 280 + nodeCount * 22));
        const radiusOf = d => Math.max(16, Math.min(36, 6 + (String(d.id || '').length) * 2.5));

        const svg = d3.select(container).append('svg')
            .attr('viewBox', `0 0 ${width} ${height}`)
            .attr('preserveAspectRatio', 'xMidYMid meet')
            .attr('width', '100%')
            .attr('height', height)
            .style('max-width', '100%')
            .style('cursor', 'grab');

        // ズーム・パン対応グループ
        const g = svg.append('g').attr('class', 'zoom-layer');

        const nodes = data.nodes.map(n => ({ ...n }));
        const links = data.links.map(l => ({ ...l }));

        const linkDistance = Math.max(80, Math.min(180, 60 + 400 / Math.sqrt(nodeCount)));
        const chargeStrength = -Math.max(150, Math.min(500, 100 + nodeCount * 15));

        const simulation = d3.forceSimulation(nodes)
            .force('link', d3.forceLink(links).id(d => d.id).distance(linkDistance))
            .force('charge', d3.forceManyBody().strength(chargeStrength))
            .force('center', d3.forceCenter(width / 2, height / 2))
            .force('collision', d3.forceCollide().radius(d => radiusOf(d) + 4));

        const link = g.append('g')
            .selectAll('line')
            .data(links)
            .enter().append('line')
            .attr('stroke', d => d.type === 'competitor' ? '#EF4444' : '#6366F1')
            .attr('stroke-width', 1.8)
            .attr('stroke-opacity', 0.55)
            .attr('stroke-dasharray', d => d.type === 'competitor' ? '0' : '5,5');

        const node = g.append('g')
            .selectAll('g')
            .data(nodes)
            .enter().append('g')
            .style('cursor', 'grab')
            .call(d3.drag()
                .on('start', (event, d) => { if (!event.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
                .on('drag', (event, d) => { d.fx = event.x; d.fy = event.y; })
                .on('end', (event, d) => { if (!event.active) simulation.alphaTarget(0); d.fx = null; d.fy = null; })
            );

        node.append('circle')
            .attr('r', radiusOf)
            .attr('fill', '#6366F1')
            .attr('opacity', 0.85)
            .attr('stroke', '#fff')
            .attr('stroke-width', 2);

        node.append('title').text(d => d.id);
        node.append('text')
            .text(d => {
                const s = String(d.id || '');
                const maxChars = Math.max(4, Math.floor(radiusOf(d) / 4));
                return s.length > maxChars ? s.slice(0, maxChars) + '…' : s;
            })
            .attr('text-anchor', 'middle')
            .attr('dy', '0.35em')
            .attr('font-size', '10px')
            .attr('fill', '#fff')
            .attr('font-weight', '600')
            .style('pointer-events', 'none');

        simulation.on('tick', () => {
            nodes.forEach(d => {
                const r = radiusOf(d);
                d.x = Math.max(r, Math.min(width - r, d.x));
                d.y = Math.max(r, Math.min(height - r, d.y));
            });
            link.attr('x1', d => d.source.x).attr('y1', d => d.source.y)
                .attr('x2', d => d.target.x).attr('y2', d => d.target.y);
            node.attr('transform', d => `translate(${d.x},${d.y})`);
        });

        // d3.zoom でズーム・パン（ノードドラッグと共存）
        const zoom = d3.zoom()
            .scaleExtent([0.3, 4])
            .filter((event) => {
                // ノード上のマウスダウンはノードドラッグに任せる
                if (event.type === 'mousedown' || event.type === 'touchstart') {
                    const target = event.target;
                    if (target && target.closest && target.closest('g.zoom-layer > g:not(:first-child)')) {
                        // ノードグループの子要素(circle/text等)はノード操作扱い
                        const isNode = target.tagName !== 'svg' && target.tagName !== 'g';
                        if (isNode && target.tagName !== 'g') return false;
                    }
                }
                return !event.ctrlKey && !event.button;
            })
            .on('zoom', (event) => {
                g.attr('transform', event.transform);
            });
        svg.call(zoom);

        // ズームコントロール追加
        const controls = createZoomControls({
            zoomIn: () => svg.transition().duration(200).call(zoom.scaleBy, 1.3),
            zoomOut: () => svg.transition().duration(200).call(zoom.scaleBy, 0.7),
            reset: () => svg.transition().duration(300).call(zoom.transform, d3.zoomIdentity),
        });
        container.insertBefore(controls, container.firstChild);
    };

    draw();

    if (typeof ResizeObserver !== 'undefined') {
        if (container.__networkResizeObserver) {
            container.__networkResizeObserver.disconnect();
        }
        let lastWidth = container.clientWidth;
        let debounceTimer = null;
        const observer = new ResizeObserver(() => {
            const w = container.clientWidth;
            if (Math.abs(w - lastWidth) < 20) return;
            lastWidth = w;
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(draw, 200);
        });
        observer.observe(container);
        container.__networkResizeObserver = observer;
    }
}

