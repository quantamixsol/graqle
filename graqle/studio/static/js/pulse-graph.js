/**
 * PulseGraph — Cytoscape.js-based graph visualization for GraQle Studio
 * Handles full KG rendering (15,525+ nodes) with governance-aware node states.
 * Coexists with CogniGraphViz (D3) which handles ≤50-node subgraph views.
 *
 * Requires: window.cytoscape, cytoscape-fcose plugin, ENTITY_COLORS (global from graph-viz.js)
 *
 * @version 1.0.0 — Spec 6 PULSE layer
 */

// ── graqle:intelligence ──
// module: graqle.studio.static.js.pulse-graph
// risk: LOW (impact radius: 0 modules)
// constraints: read-only consumption of graph data, no SDK core imports
// ── /graqle:intelligence ──

class PulseGraph {
  constructor(containerId, options = {}) {
    this.containerId = containerId;
    this.options     = Object.assign({ tierLimit: 500 }, options || {});
    this.cy          = null;

    // Internal state
    this._pulseAnimations = new Map();
    this._edgeFlashTimers = new Map();
    this._upgradeOverlay  = null;

    // Edge type → flash color
    this._edgeColors = {
      message:    '#3b82f6',
      cascade:    '#ef4444',
      taint:      '#eab308',
      governance: '#6366f1',
    };

    this._container = document.getElementById(containerId);
    if (!this._container) {
      throw new Error(`PulseGraph: container #${containerId} not found`);
    }
    if (window.getComputedStyle(this._container).position === 'static') {
      this._container.style.position = 'relative';
    }
  }

  // ─────────────────────────────────────────────────────────────────────────
  // PRIVATE: STYLESHEET
  // ─────────────────────────────────────────────────────────────────────────

  _buildStylesheet() {
    const entitySelectors = (typeof ENTITY_COLORS !== 'undefined')
      ? Object.entries(ENTITY_COLORS).map(([type, color]) => ({
          selector: `node[entity_type="${type}"]`,
          style: { 'background-color': color },
        }))
      : [];

    return [
      // ── Base node ──
      {
        selector: 'node',
        style: {
          'label':               'data(label)',
          'text-valign':         'center',
          'text-halign':         'center',
          'font-size':           '10px',
          'font-family':         'Inter, system-ui, sans-serif',
          'color':               '#f1f5f9',
          'text-outline-color':  '#0f172a',
          'text-outline-width':  1,
          'width':               'data(size)',
          'height':              'data(size)',
          'background-color':    '#64748b',
          'border-width':        2,
          'border-color':        '#1e293b',
          'border-style':        'solid',
          'opacity':             1,
          'transition-property': 'border-color, border-width, opacity, width, height',
          'transition-duration': '0.3s',
        },
      },

      // ── Entity type colors (from ENTITY_COLORS global) ──
      ...entitySelectors,

      // ── state: idle ──
      {
        selector: 'node[state="idle"]',
        style: {
          'border-color': '#1e293b',
          'border-width': 2,
          'border-style': 'solid',
          'opacity':      1,
        },
      },

      // ── state: active (amber border; JS drives pulse via cy.animate) ──
      {
        selector: 'node[state="active"]',
        style: {
          'border-color': '#fbbf24',
          'border-width': 4,
          'border-style': 'solid',
          'opacity':      1,
        },
      },

      // ── state: done (green border + confidence label overlay) ──
      {
        selector: 'node[state="done"]',
        style: {
          'border-color': '#34d399',
          'border-width': 3,
          'border-style': 'solid',
          'label':        'data(confidenceLabel)',
          'color':        '#34d399',
          'opacity':      1,
        },
      },

      // ── state: error (red dashed border + fault code label) ──
      {
        selector: 'node[state="error"]',
        style: {
          'border-color': '#f87171',
          'border-width': 3,
          'border-style': 'dashed',
          'label':        'data(faultLabel)',
          'color':        '#f87171',
          'opacity':      1,
        },
      },

      // ── state: isolated ──
      {
        selector: 'node[state="isolated"]',
        style: {
          'border-color': '#94a3b8',
          'border-width': 2,
          'border-style': 'solid',
          'opacity':      0.4,
        },
      },

      // ── state: redacted (reduced size + lock label) ──
      {
        selector: 'node[state="redacted"]',
        style: {
          'border-color':       '#64748b',
          'border-width':       2,
          'border-style':       'solid',
          'opacity':            0.3,
          'width':              18,
          'height':             18,
          'label':              '\ud83d\udd12',
          'font-size':          '10px',
          'text-outline-width': 0,
        },
      },

      // ── state: decayed ──
      {
        selector: 'node[state="decayed"]',
        style: {
          'border-color': '#334155',
          'border-width': 1,
          'border-style': 'solid',
          'opacity':      0.15,
        },
      },

      // ── state: budget_rejected (orange border + "$" label) ──
      {
        selector: 'node[state="budget_rejected"]',
        style: {
          'border-color': '#fb923c',
          'border-width': 3,
          'border-style': 'solid',
          'label':        'data(budgetLabel)',
          'color':        '#fb923c',
          'opacity':      1,
        },
      },

      // ── Hub nodes (degree > 20): shadow ──
      {
        selector: 'node[hub="true"]',
        style: {
          'shadow-blur':     12,
          'shadow-color':    '#0f172a',
          'shadow-opacity':  0.65,
          'shadow-offset-x': 0,
          'shadow-offset-y': 3,
        },
      },

      // ── Tier-gated nodes (beyond tierLimit) ──
      {
        selector: 'node[tiergated="true"]',
        style: { 'display': 'none' },
      },

      // ── Base edge ──
      {
        selector: 'edge',
        style: {
          'width':               1.5,
          'line-color':          '#475569',
          'target-arrow-color':  '#475569',
          'target-arrow-shape':  'triangle',
          'curve-style':         'bezier',
          'opacity':             0.7,
          'arrow-scale':         0.8,
          'transition-property': 'line-color, width, opacity',
          'transition-duration': '0.2s',
        },
      },

      // ── edge type: message (blue) ──
      {
        selector: 'edge[relationship="message"]',
        style: {
          'line-color':         '#3b82f6',
          'target-arrow-color': '#3b82f6',
        },
      },

      // ── edge type: cascade (red) ──
      {
        selector: 'edge[relationship="cascade"]',
        style: {
          'line-color':         '#ef4444',
          'target-arrow-color': '#ef4444',
        },
      },

      // ── edge type: taint (yellow) ──
      {
        selector: 'edge[relationship="taint"]',
        style: {
          'line-color':         '#eab308',
          'target-arrow-color': '#eab308',
        },
      },

      // ── edge type: governance (indigo) ──
      {
        selector: 'edge[relationship="governance"]',
        style: {
          'line-color':         '#6366f1',
          'target-arrow-color': '#6366f1',
        },
      },

      // ── flashing edge (temporary class added by animateEdge) ──
      {
        selector: 'edge.flashing',
        style: {
          'width':   4,
          'opacity': 1,
        },
      },
    ];
  }

  // ─────────────────────────────────────────────────────────────────────────
  // PRIVATE: HELPERS
  // ─────────────────────────────────────────────────────────────────────────

  _getNode(id) {
    if (!this.cy) return null;
    const node = this.cy.getElementById(String(id));
    return node.length ? node : null;
  }

  _showUpgradeOverlay(hiddenCount) {
    if (this._upgradeOverlay) this._upgradeOverlay.remove();

    const overlay = document.createElement('div');
    overlay.className = 'pulse-graph-upgrade-overlay';
    overlay.style.cssText = `
      position: absolute;
      bottom: 12px;
      right: 12px;
      background: rgba(15, 23, 42, 0.92);
      color: #f8fafc;
      padding: 8px 14px;
      border-radius: 8px;
      font-size: 12px;
      font-family: Inter, system-ui, sans-serif;
      border: 1px solid #fb923c;
      z-index: 999;
      pointer-events: auto;
      box-shadow: 0 4px 16px rgba(0,0,0,0.4);
    `;
    overlay.innerHTML =
      `<span style="color:#fb923c">\u26a1</span> ` +
      `${hiddenCount} node${hiddenCount !== 1 ? 's' : ''} hidden \u2014 ` +
      `<a href="/upgrade" style="color:#fb923c;text-decoration:underline;">Upgrade to see all</a>`;

    this._container.appendChild(overlay);
    this._upgradeOverlay = overlay;
  }

  // ─────────────────────────────────────────────────────────────────────────
  // PUBLIC: load(data)
  // data = { nodes:[{id,label,type,degree}], edges:[{source,target,relationship}] }
  // ─────────────────────────────────────────────────────────────────────────

  load(data) {
    if (!data || typeof data !== 'object') {
      throw new Error('PulseGraph.load: data must be a non-null object');
    }
    if (this.cy) {
      this.cy.nodes().stop(true);
      this.cy.destroy();
      this.cy = null;
    }
    if (this._upgradeOverlay) {
      this._upgradeOverlay.remove();
      this._upgradeOverlay = null;
    }
    this._pulseAnimations.clear();
    this._edgeFlashTimers.forEach(tid => clearTimeout(tid));
    this._edgeFlashTimers.clear();

    const tierLimit  = this.options.tierLimit;
    const rawNodes   = (data.nodes || []).slice().sort((a, b) => (b.degree || 0) - (a.degree || 0));
    const rawEdges   = data.edges || [];
    let   tieredOut  = 0;

    const cyNodes = rawNodes.map((n, idx) => {
      const degree    = n.degree || 0;
      const isHub     = degree > 20;
      const size      = isHub ? 50 : 30;
      const tiergated = idx >= tierLimit;
      if (tiergated) tieredOut++;

      return {
        data: {
          id:              String(n.id),
          label:           n.label || String(n.id),
          entity_type:     (n.type || n.entity_type || 'UNKNOWN').toUpperCase(),
          degree,
          size,
          hub:             isHub     ? 'true' : 'false',
          tiergated:       tiergated ? 'true' : 'false',
          state:           'idle',
          confidenceLabel: n.label || String(n.id),
          faultLabel:      n.label || String(n.id),
          budgetLabel:     (n.label || String(n.id)) + ' $',
        },
      };
    });

    // Build set of tiergated node IDs to filter dangling edges
    const tiergatedIds = new Set();
    cyNodes.forEach(n => { if (n.data.tiergated === 'true') tiergatedIds.add(n.data.id); });

    const cyEdges = rawEdges
      .filter(e => {
        if (!e.source || !e.target) { console.warn('PulseGraph: edge missing source/target', e); return false; }
        if (tiergatedIds.has(String(e.source)) || tiergatedIds.has(String(e.target))) return false;
        return true;
      })
      .map((e, idx) => ({
        data: {
          id:           e.id || `e_${idx}_${String(e.source)}_${String(e.target)}`,
          source:       String(e.source),
          target:       String(e.target),
          relationship: e.relationship || 'message',
        },
      }));

    this.cy = window.cytoscape({
      container:        this._container,
      elements:         { nodes: cyNodes, edges: cyEdges },
      style:            this._buildStylesheet(),
      layout: {
        name:                        'fcose',
        animate:                     true,
        animationDuration:           600,
        randomize:                   false,
        quality:                     'default',
        nodeDimensionsIncludeLabels: true,
        nodeSeparation:              75,
        idealEdgeLength:             () => 100,
        edgeElasticity:              () => 0.45,
        gravity:                     0.25,
        gravityRange:                3.8,
        numIter:                     2500,
        tile:                        true,
        fit:                         true,
        padding:                     50,
      },
    });

    if (tieredOut > 0) {
      this._showUpgradeOverlay(tieredOut);
    }
  }

  // ─────────────────────────────────────────────────────────────────────────
  // PUBLIC: Node State Methods
  // ─────────────────────────────────────────────────────────────────────────

  activateNode(id) {
    const nid = String(id);
    const n = this._getNode(nid);
    if (!n) return;
    // Cancel any existing pulse on this node
    this._pulseAnimations.set(nid, true);
    n.data('state', 'active');
    const self = this;
    const pulse = () => {
      if (!self._pulseAnimations.get(nid) || !self.cy || n.removed()) return;
      if (n.data('state') !== 'active') { self._pulseAnimations.delete(nid); return; }
      n.animate(
        { style: { 'border-width': 6 } },
        { duration: 400, complete: () => {
          if (!self._pulseAnimations.get(nid) || n.removed()) return;
          n.animate(
            { style: { 'border-width': 2 } },
            { duration: 400, complete: () => {
              if (n.data('state') === 'active' && self._pulseAnimations.get(nid)) pulse();
            }}
          );
        }}
      );
    };
    pulse();
  }

  completeNode(id, confidence) {
    const nid = String(id);
    const n = this._getNode(nid);
    if (!n) return;
    this._pulseAnimations.delete(nid);
    n.stop(true);
    n.data('state', 'done');
    const pct = (typeof confidence === 'number' && isFinite(confidence))
      ? Math.round(Math.min(Math.max(confidence, 0), 1) * 100) : '?';
    n.data('confidenceLabel', n.data('label') + ' ' + pct + '%');
  }

  failNode(id, faultCode) {
    const nid = String(id);
    const n = this._getNode(nid);
    if (!n) return;
    this._pulseAnimations.delete(nid);
    n.stop(true);
    n.data('state', 'error');
    n.data('faultLabel', n.data('label') + ' ' + String(faultCode ?? 'ERR'));
  }

  isolateNode(id) {
    const n = this._getNode(id);
    if (n) n.data('state', 'isolated');
  }

  redactNode(id) {
    const n = this._getNode(id);
    if (n) n.data('state', 'redacted');
  }

  decayNode(id) {
    const n = this._getNode(id);
    if (!n) return;
    const self = this;
    n.stop(true);
    n.animate(
      { style: { opacity: 0.15 } },
      { duration: 2000, complete: () => {
        if (self.cy && !n.removed()) n.data('state', 'decayed');
      }}
    );
  }

  rejectBudget(id) {
    const n = this._getNode(id);
    if (n) n.data('state', 'budget_rejected');
  }

  // ─────────────────────────────────────────────────────────────────────────
  // PUBLIC: Edge Animation
  // ─────────────────────────────────────────────────────────────────────────

  animateEdge(sourceId, targetId, type) {
    if (!this.cy) return;
    const src = String(sourceId);
    const tgt = String(targetId);
    const e = this.cy.edges().filter(edge =>
      edge.data('source') === src && edge.data('target') === tgt
    );
    if (e.empty()) return;

    const color = this._edgeColors[type] || '#94a3b8';
    e.addClass('flashing');
    e.style('line-color', color);
    e.style('target-arrow-color', color);

    const edgeKey = JSON.stringify([src, tgt]);
    if (this._edgeFlashTimers.has(edgeKey)) {
      clearTimeout(this._edgeFlashTimers.get(edgeKey));
    }
    const self = this;
    this._edgeFlashTimers.set(edgeKey, setTimeout(() => {
      if (!self.cy || e.cy() !== self.cy) return;
      e.removeClass('flashing');
      e.removeStyle('line-color');
      e.removeStyle('target-arrow-color');
      self._edgeFlashTimers.delete(edgeKey);
    }, 600));
  }

  // ─────────────────────────────────────────────────────────────────────────
  // PUBLIC: View Controls
  // ─────────────────────────────────────────────────────────────────────────

  fitToView() {
    if (this.cy) this.cy.fit(undefined, 50);
  }

  // ─────────────────────────────────────────────────────────────────────────
  // PUBLIC: Cleanup
  // ─────────────────────────────────────────────────────────────────────────

  destroy() {
    // Cancel all pulse animations
    this._pulseAnimations.clear();
    // Clear all edge flash timers
    this._edgeFlashTimers.forEach(tid => clearTimeout(tid));
    this._edgeFlashTimers.clear();
    // Stop all node animations and destroy cy
    if (this.cy) {
      this.cy.nodes().stop(true);
      this.cy.destroy();
      this.cy = null;
    }
    // Remove upgrade overlay
    if (this._upgradeOverlay && this._upgradeOverlay.parentNode) {
      this._upgradeOverlay.parentNode.removeChild(this._upgradeOverlay);
      this._upgradeOverlay = null;
    }
  }
}

window.PulseGraph = PulseGraph;
