/**
 * AI Orchestra — SSE クライアント。
 *
 * 設計書: doc/ui/08_sse_realtime.md §5.1
 *
 * EventSource は GET のみ対応のため、POST SSE は fetch() + ReadableStream で実装する。
 *
 * @example
 *   const sse = new OrchestraSSE('/api/idea/stream');
 *   sse.on('utterance', (data) => addChatBubble(data));
 *   sse.on('done', (data) => showResults(data));
 *   sse.on('error', (data) => toast(data.message, 'error'));
 *   await sse.start({ plan: {...}, prompt: '...' });
 */
class OrchestraSSE {
  /**
   * @param {string} url - SSE エンドポイントの URL
   */
  constructor(url) {
    this._url = url;
    this._handlers = {};
    this._controller = null;
    this._state = 'idle'; // idle | connecting | streaming | done | error
    this._eventCount = 0;
    this._startTime = null;
  }

  /**
   * イベントハンドラを登録する。``'*'`` で全イベントを受信できる。
   *
   * @param {string} eventType - イベント型 (例: 'utterance', 'done', '*')
   * @param {function} handler - コールバック関数 (data) => void
   * @returns {OrchestraSSE} メソッドチェーン用
   */
  on(eventType, handler) {
    if (!this._handlers[eventType]) {
      this._handlers[eventType] = [];
    }
    this._handlers[eventType].push(handler);
    return this;
  }

  /**
   * SSE 接続を開始する (POST)。
   *
   * @param {object} body - リクエストボディ (JSON にシリアライズして送信)
   * @returns {Promise<void>} ストリーム完了時に resolve
   */
  async start(body) {
    this._state = 'connecting';
    this._startTime = Date.now();
    this._controller = new AbortController();

    try {
      const response = await fetch(this._url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'text/event-stream',
        },
        body: JSON.stringify(body),
        signal: this._controller.signal,
      });

      // HTTP エラーチェック
      if (!response.ok) {
        const errorText = await response.text();
        let errorData;
        try {
          errorData = JSON.parse(errorText);
        } catch {
          errorData = { message: errorText || `HTTP ${response.status}` };
        }
        this._state = 'error';
        this._dispatch({
          type: 'error',
          message: errorData.message || errorData.detail || `HTTP ${response.status}`,
          recoverable: response.status >= 500,
        });
        return;
      }

      this._state = 'streaming';
      await this._readStream(response);
    } catch (err) {
      if (err.name === 'AbortError') {
        // ユーザーによる中断
        this._state = 'idle';
        return;
      }
      this._state = 'error';
      this._dispatch({
        type: 'error',
        message: `接続エラー: ${err.message}`,
        recoverable: true,
      });
    }
  }

  /**
   * SSE 接続を中断する。複数回呼んでも安全。
   */
  abort() {
    if (this._controller) {
      this._controller.abort();
      this._controller = null;
    }
    this._state = 'idle';
  }

  /**
   * 接続状態を返す。
   *
   * @returns {'idle'|'connecting'|'streaming'|'done'|'error'}
   */
  get state() {
    return this._state;
  }

  /**
   * 受信イベント数を返す。
   *
   * @returns {number}
   */
  get eventCount() {
    return this._eventCount;
  }

  /**
   * 接続開始からの経過時間 (ミリ秒)。未接続なら null。
   *
   * @returns {number|null}
   */
  get elapsedMs() {
    if (!this._startTime) return null;
    return Date.now() - this._startTime;
  }

  // ====================================================================
  // Private methods
  // ====================================================================

  /**
   * ReadableStream から SSE イベントを順次読み取って dispatch する。
   *
   * @param {Response} response - fetch のレスポンス
   * @private
   */
  async _readStream(response) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';

    try {
      while (true) {
        const { done, value } = await reader.read();

        if (done) {
          // ストリーム終了 (サーバーが閉じた)
          if (buffer.trim()) {
            this._parseAndDispatch(buffer);
          }
          if (this._state === 'streaming') {
            this._state = 'done';
          }
          break;
        }

        // デコード + バッファに追加
        buffer += decoder.decode(value, { stream: true });

        // イベント分割 (\n\n 区切り)
        const events = buffer.split('\n\n');
        // 最後の要素は不完全な可能性があるためバッファに残す
        buffer = events.pop() || '';

        for (const eventText of events) {
          if (eventText.trim()) {
            this._parseAndDispatch(eventText);
          }
        }
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        this._state = 'error';
        this._dispatch({
          type: 'error',
          message: `ストリーム読み取りエラー: ${err.message}`,
          recoverable: false,
        });
      }
    } finally {
      reader.releaseLock();
    }
  }

  /**
   * "data: {...}" 形式の SSE テキストブロックをパースして dispatch する。
   *
   * @param {string} eventText - SSE イベントブロック
   * @private
   */
  _parseAndDispatch(eventText) {
    // 複数行の data: を結合 (event:/id:/retry: は使わない)
    const lines = eventText.split('\n');
    let dataStr = '';

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        dataStr += line.slice(6);
      } else if (line.startsWith('data:')) {
        dataStr += line.slice(5);
      }
    }

    if (!dataStr) return;

    try {
      const data = JSON.parse(dataStr);
      this._eventCount++;
      this._dispatch(data);

      // 終端イベントで状態更新
      if (data.type === 'done') {
        this._state = 'done';
      } else if (data.type === 'error' && !data.recoverable) {
        this._state = 'error';
      }
    } catch (err) {
      console.warn('[OrchestraSSE] JSON parse error:', err, dataStr);
    }
  }

  /**
   * イベントを登録ハンドラに分配する。
   *
   * @param {object} data - パース済みイベントデータ (必ず type プロパティを持つ)
   * @private
   */
  _dispatch(data) {
    // デバッグ用: 受信した全 SSE イベントを console に流す
    // (DevTools > Console で "[SSE]" フィルタして確認可能)
    if (data && data.type) {
      const preview = data.type === 'utterance'
        ? `${data.agent?.emoji || ''} ${data.agent?.name || ''} r${data.round ?? '?'} (${(data.content || '').slice(0, 40)}...)`
        : (data.type === 'round_start' ? `round ${data.round}` : '');
      console.debug(`[SSE] ${data.type}`, preview, data);
    }

    // 型別ハンドラ
    const handlers = this._handlers[data.type] || [];
    for (const handler of handlers) {
      try {
        handler(data);
      } catch (err) {
        console.error(`[OrchestraSSE] Handler error (${data.type}):`, err);
      }
    }

    // ワイルドカードハンドラ ('*')
    const allHandlers = this._handlers['*'] || [];
    for (const handler of allHandlers) {
      try {
        handler(data);
      } catch (err) {
        console.error('[OrchestraSSE] Wildcard handler error:', err);
      }
    }
  }
}

// グローバル公開 (Alpine.js などから参照可能)
window.OrchestraSSE = OrchestraSSE;
