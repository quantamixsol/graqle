/**
 * PulseSSE — Connects PulseGraph to the /reason SSE endpoint.
 * Uses fetch + ReadableStream (POST SSE — EventSource is GET-only).
 *
 * @version 1.0.0 — Spec 6 PULSE layer
 */

// ── graqle:intelligence ──
// module: graqle.studio.static.js.pulse-sse
// risk: LOW (impact radius: 0 modules)
// constraints: read-only, no SDK core imports
// ── /graqle:intelligence ──

class PulseSSE {
  constructor(pulseGraph, statusCallback) {
    this.pulseGraph = pulseGraph;
    this.statusCallback = statusCallback || (() => {});
    this._abortController = null;
    this._reader = null;
    this._activeNodeIds = [];
    this._connected = false;
  }

  /**
   * Start reasoning and stream SSE events into PulseGraph.
   * @param {string} query - The question to reason about
   * @param {string} mode - 'fast' (1 round) or 'deep' (multi-round)
   */
  async connect(query, mode = 'fast') {
    this.disconnect();

    this._abortController = new AbortController();
    this._activeNodeIds = [];
    this._connected = true;

    try {
      const response = await fetch('/studio/api/reason', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, mode }),
        signal: this._abortController.signal,
      });

      if (!response.ok) {
        for (const id of this._activeNodeIds) {
          this.pulseGraph.failNode(id, 'HTTP_ERR');
        }
        this._activeNodeIds = [];
        this._connected = false;
        this.statusCallback({ type: 'error', message: `HTTP ${response.status}` });
        return;
      }

      if (!response.body) {
        this.statusCallback({ type: 'error', message: 'No response body' });
        return;
      }

      const reader = response.body.getReader();
      this._reader = reader;
      const decoder = new TextDecoder('utf-8');
      let buffer = '';

      outer: while (this._connected) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        // Keep the last (potentially incomplete) line in buffer
        buffer = lines.pop() || '';

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed.startsWith('data: ')) continue;

          const payload = trimmed.slice(6);
          if (payload === '[DONE]') {
            this._connected = false;
            break outer;
          }

          try {
            const data = JSON.parse(payload);
            this._handleEvent(data);
          } catch (e) {
            console.warn('PulseSSE: invalid JSON in SSE line', payload);
          }
        }
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        console.error('PulseSSE: connection error', err);
        this.statusCallback({ type: 'error', message: err?.message || String(err) });
        for (const id of this._activeNodeIds) {
          this.pulseGraph.failNode(id, 'CONN_ERR');
        }
        this._activeNodeIds = [];
      }
    } finally {
      this._connected = false;
      this._abortController = null;
      try { this._reader?.cancel(); } catch (_) {}
      this._reader = null;
    }
  }

  /**
   * Handle a parsed SSE event.
   */
  _handleEvent(data) {
    switch (data.type) {
      case 'activation':
        // Fail orphaned nodes from prior rounds before replacing
        for (const id of this._activeNodeIds) {
          this.pulseGraph.failNode(id, 'SUPERSEDED');
        }
        const validNodes = (data.nodes || []).filter(n => n.id != null);
        this._activeNodeIds = validNodes.map(n => n.id);
        for (const node of validNodes) {
          this.pulseGraph.activateNode(node.id);
        }
        this.statusCallback({
          type: 'activation',
          count: data.count,
          latency_ms: data.latency_ms,
          mode: data.mode,
        });
        break;

      case 'final_answer':
        for (const id of this._activeNodeIds) {
          this.pulseGraph.completeNode(id, data.confidence);
        }
        this.statusCallback({
          type: 'final_answer',
          answer: data.answer,
          confidence: data.confidence,
          rounds: data.rounds,
          node_count: data.node_count,
          cost_usd: data.cost_usd,
          latency_ms: data.latency_ms,
        });
        this._activeNodeIds = [];
        break;

      case 'error':
        for (const id of this._activeNodeIds) {
          this.pulseGraph.failNode(id, 'REASON_ERR');
        }
        this.statusCallback({ type: 'error', message: data.message });
        this._activeNodeIds = [];
        break;

      default:
        // Forward unknown events to callback for extensibility
        this.statusCallback(data);
        break;
    }
  }

  /**
   * Abort ongoing SSE connection.
   */
  disconnect() {
    this._connected = false;
    if (this._abortController) {
      this._abortController.abort();
      this._abortController = null;
    }
    try { this._reader?.cancel(); } catch (_) {}
    this._reader = null;
    this._activeNodeIds = [];
  }
}

window.PulseSSE = PulseSSE;
