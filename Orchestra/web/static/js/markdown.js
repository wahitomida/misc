/**
 * Markdown レンダリングヘルパー。
 *
 * marked.js でパース → DOMPurify でサニタイズ。
 *
 * 設計書: doc/ui/09_styling_animation.md §12.2
 */

/**
 * Markdown テキストをサニタイズ済み HTML に変換する。
 *
 * @param {string} md - Markdown テキスト
 * @returns {string} サニタイズ済み HTML 文字列
 */
function renderMarkdown(md) {
  if (!md) return '';

  // marked 設定
  if (typeof marked !== 'undefined') {
    marked.setOptions({
      gfm: true,
      breaks: false,
      headerIds: false,
      mangle: false,
    });
  } else {
    console.warn('marked.js is not loaded');
    return md;
  }

  const rawHtml = marked.parse(md);

  if (typeof DOMPurify === 'undefined') {
    console.warn('DOMPurify is not loaded; returning raw HTML');
    return rawHtml;
  }

  return DOMPurify.sanitize(rawHtml, {
    ALLOWED_TAGS: [
      'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
      'p', 'br', 'hr',
      'ul', 'ol', 'li',
      'strong', 'em', 'del', 'code', 'pre',
      'blockquote',
      'table', 'thead', 'tbody', 'tr', 'th', 'td',
      'a', 'img',
      'span', 'div',
    ],
    ALLOWED_ATTR: ['href', 'src', 'alt', 'title', 'class'],
    ALLOW_DATA_ATTR: false,
  });
}
