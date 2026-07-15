// ExhibiReport - Utility Functions

/**
 * トースト通知を表示
 */
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const colors = {
        success: 'bg-green-50 dark:bg-green-900/30 border-green-200 dark:border-green-800 text-green-700 dark:text-green-300',
        error: 'bg-red-50 dark:bg-red-900/30 border-red-200 dark:border-red-800 text-red-700 dark:text-red-300',
        warning: 'bg-amber-50 dark:bg-amber-900/30 border-amber-200 dark:border-amber-800 text-amber-700 dark:text-amber-300',
        info: 'bg-blue-50 dark:bg-blue-900/30 border-blue-200 dark:border-blue-800 text-blue-700 dark:text-blue-300',
    };

    const icons = { success: '✅', error: '⚠️', warning: '⚡', info: 'ℹ️' };

    const toast = document.createElement('div');
    toast.className = `flex items-center gap-2 px-4 py-3 rounded-xl border text-sm font-medium shadow-lg toast-enter ${colors[type] || colors.info}`;
    toast.innerHTML = `<span>${icons[type] || icons.info}</span><span>${message}</span>`;
    container.appendChild(toast);

    setTimeout(() => {
        toast.classList.remove('toast-enter');
        toast.classList.add('toast-exit');
        setTimeout(() => toast.remove(), 200);
    }, 3000);
}

/**
 * テキストファイルをダウンロード
 */
function downloadText(content, filename) {
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

/**
 * クリップボードにコピー（フォールバック付き）
 */
async function copyToClipboard(text) {
    try {
        await navigator.clipboard.writeText(text);
        return true;
    } catch (e) {
        // フォールバック
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        return true;
    }
}

/**
 * キーボードショートカット登録
 */
document.addEventListener('keydown', function(e) {
    // Ctrl+E: Markdown出力
    if (e.ctrlKey && e.key === 'e') {
        e.preventDefault();
        const btn = document.querySelector('[data-action="export-markdown"]');
        if (btn) btn.click();
    }

    // Ctrl+Shift+C: 全体コピー
    if (e.ctrlKey && e.shiftKey && e.key === 'C') {
        e.preventDefault();
        const btn = document.querySelector('[data-action="copy-all"]');
        if (btn) btn.click();
    }
});
