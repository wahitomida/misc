/**
 * AI Orchestra — 共通ユーティリティ & トーストマネージャ。
 *
 * グローバル関数:
 *   - toast(message, type)          — トースト通知を表示
 *   - formatTime(sec)               — 秒数を MM:SS / HH:MM:SS にフォーマット
 *   - formatDate(iso)               — ISO 日時文字列を読みやすい形式に
 *   - debounce(fn, ms)              — デバウンス関数
 *   - renderMarkdown(md)            — markdown.js 提供 (グローバル)
 *
 * Alpine.js コンポーネント:
 *   - toastManager()                — トースト通知の状態管理
 *
 * 設計書: doc/ui/03_components.md §9.3, doc/ui/09_styling_animation.md
 */

// ----------------------------------------------------------------------
// Constants
// ----------------------------------------------------------------------

const TOAST_DURATIONS = {
  success: 3000,
  info: 3000,
  warning: 5000,
  error: null, // 手動消去のみ
};
const MAX_TOASTS = 3;

let _toastIdCounter = 0;

// ----------------------------------------------------------------------
// Toast Manager (Alpine.js component)
// ----------------------------------------------------------------------

/**
 * トースト通知の状態管理コンポーネント。
 *
 * @returns {object} Alpine.js データオブジェクト
 */
function toastManager() {
  return {
    toasts: [],

    add(message, type = 'info') {
      const id = ++_toastIdCounter;
      this.toasts.push({ id, message, type, visible: true });

      // 最大数制限 (先頭から削除)
      while (this.toasts.length > MAX_TOASTS) {
        this.toasts.shift();
      }

      // 自動消去
      const duration = TOAST_DURATIONS[type];
      if (duration) {
        setTimeout(() => this.dismiss(id), duration);
      }
    },

    dismiss(id) {
      const t = this.toasts.find((t) => t.id === id);
      if (t) {
        t.visible = false;
        setTimeout(() => {
          this.toasts = this.toasts.filter((t) => t.id !== id);
        }, 200);
      }
    },
  };
}

// ----------------------------------------------------------------------
// Global helpers
// ----------------------------------------------------------------------

/**
 * トースト通知を表示する。
 *
 * @param {string} message - 表示メッセージ
 * @param {'success'|'info'|'warning'|'error'} type - 通知タイプ
 */
function toast(message, type = 'info') {
  window.dispatchEvent(
    new CustomEvent('show-toast', { detail: { message, type } })
  );
}

/**
 * 秒数を MM:SS または HH:MM:SS にフォーマットする。
 *
 * @param {number} sec - 秒数
 * @returns {string} フォーマット済み文字列
 */
function formatTime(sec) {
  if (sec == null || !isFinite(sec)) return '--:--';
  const total = Math.max(0, Math.floor(sec));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const pad = (n) => String(n).padStart(2, '0');
  if (h > 0) return `${h}:${pad(m)}:${pad(s)}`;
  return `${pad(m)}:${pad(s)}`;
}

/**
 * ISO 日時文字列を読みやすい形式に変換する。
 *
 * @param {string} iso - ISO 8601 形式の日時文字列
 * @returns {string} "YYYY/MM/DD HH:MM" 形式
 */
function formatDate(iso) {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    const pad = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}/${pad(d.getMonth() + 1)}/${pad(d.getDate())} ` +
           `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  } catch (e) {
    return iso;
  }
}

/**
 * 関数呼び出しをデバウンスする。
 *
 * @param {Function} fn - デバウンス対象関数
 * @param {number} ms - 待機ミリ秒
 * @returns {Function} デバウンス済み関数
 */
function debounce(fn, ms) {
  let timer = null;
  return function (...args) {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      fn.apply(this, args);
      timer = null;
    }, ms);
  };
}

/**
 * テキストをクリップボードにコピーする (execCommand フォールバック付き)。
 *
 * @param {string} text - コピー対象文字列
 * @returns {Promise<boolean>} 成功時 true
 */
async function copyToClipboard(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    ta.style.left = '-9999px';
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    return ok;
  } catch (e) {
    console.error('copyToClipboard failed:', e);
    return false;
  }
}

/**
 * 文字列をテキストファイルとしてダウンロードする。
 *
 * @param {string} content - ファイル内容
 * @param {string} filename - 保存ファイル名
 * @param {string} mimeType - MIME タイプ (デフォルト text/plain)
 */
function downloadText(content, filename, mimeType = 'text/plain;charset=utf-8') {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

