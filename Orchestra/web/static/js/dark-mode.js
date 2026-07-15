/**
 * ダークモード制御。
 *
 * - localStorage に永続化
 * - OS 設定 (prefers-color-scheme) をフォールバック
 * - 白フラッシュ防止の初期化スクリプトは base.html の <head> 内に配置
 *
 * 設計書: doc/ui/09_styling_animation.md §7.3
 */

/**
 * ダークモードを切り替える。
 *
 * @returns {boolean} 切替後がダークなら true
 */
function toggleDarkMode() {
  const isDark = document.documentElement.classList.toggle('dark');
  localStorage.setItem('darkMode', isDark.toString());
  return isDark;
}

/**
 * 現在のダークモード状態を返す。
 *
 * @returns {boolean}
 */
function isDarkMode() {
  return document.documentElement.classList.contains('dark');
}

// OS設定の変更を監視する。localStorage に明示設定がない場合のみ追従。
window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
  const stored = localStorage.getItem('darkMode');
  if (stored === null) {
    document.documentElement.classList.toggle('dark', e.matches);
  }
});
