/**
 * CogniGraph Studio — D3 Force-Directed Graph Visualization
 * Ported from GraphVisualizationEU.tsx (React + D3) to vanilla JS + D3
 *
 * Features:
 * - Force simulation with adaptive parameters
 * - Zoom/pan via d3-zoom
 * - Node drag with simulation reheat
 * - Tooltip on hover
 * - Click → HTMX node detail panel
 * - Search/filter integration via Alpine.js
 * - Auto-fit on simulation settle
 * - Entity type color mapping (8 branches, 31 types)
 *
 * @version 0.11.0
 */

// ── graqle:intelligence ──
// module: graqle.studio.static.js.graph-viz
// risk: LOW (impact radius: 0 modules)
// constraints: none
// ── /graqle:intelligence ──

// ============================================================================
// ENTITY TYPE COLORS (matching kg-types-eu.ts)
// ============================================================================

const ENTITY_COLORS = {
  // Agent branch — purples
  PERSON:          '#a78bfa',
  ORGANIZATION:    '#a78bfa',
  // Spatial — cyans
  LOCATION:        '#22d3ee',
  // Temporal — ambers
  DATE:            '#fbbf24',
  EVENT:           '#fbbf24',
  // Governance — reds/oranges
  REGULATION:      '#fb923c',
  POLICY:          '#fb923c',
  CONTROL:         '#34d399',
  RISK:            '#f87171',
  STANDARD:        '#f87171',
  GOV_FRAMEWORK:   '#fb923c',
  GOV_DOMAIN:      '#f87171',
  GOV_REQUIREMENT: '#fb923c',
  GOV_CONTROL:     '#fca5a5',
  // Artifact — indigos
  PRODUCT:         '#818cf8',
  SERVICE:         '#818cf8',
  SYSTEM:          '#a5b4fc',
  PROCESS:         '#c084fc',
  // Measurement — blues
  METRIC:          '#38bdf8',
  NUMBER:          '#38bdf8',
  // Cognitive — pinks
  DECISION:        '#e879f9',
  RATIONALE:       '#e879f9',
  OUTCOME:         '#e879f9',
  ACTION:          '#f472b6',
  STATE:           '#f472b6',
  // Lineage — teals
  QUERY:           '#2dd4bf',
  SOURCE:          '#2dd4bf',
  ANSWER:          '#5eead4',
  CONTEXT:         '#5eead4',
  GROUNDING:       '#99f6e4',
  // Catch-all
  UNKNOWN:         '#cbd5e1',
  // CogniGraph-specific types
  CONCEPT:         '#818cf8',
  LESSON:          '#fbbf24',
  MISTAKE:         '#f87171',
  INSIGHT:         '#e879f9',
  PATTERN:         '#c084fc',
  AGENT:           '#a78bfa',
  CHUNK:           '#94a3b8',
};

function getNodeColor(type) {
  return ENTITY_COLORS[(type || '').toUpperCase()] || ENTITY_COLORS.UNKNOWN;
}

// ============================================================================
// GRAPH VISUALIZATION CLASS
// ============================================================================

class CogniGraphViz {
  constructor(containerId, options = {}) {
    this.container = document.getElementById(containerId);
    if (!this.container) {
      console.error(`CogniGraphViz: container #${containerId} not found`);
      return;
    }

    this.options = {
      apiBase: '/studio/api',
      onNodeClick: null,
      showLabels: true,
      ...options,
    };

    this.nodes = [];
    this.links = [];
    this.simulation = null;
    this.svg = null;
    this.g = null;
    this.zoom = null;
    this.tooltip = null;
    this.dragNodeId = null;
    this.hasFitted = false;

    this._init();
  }

  // ---- INITIALIZATION ----

  _init() {
    const rect = this.container.getBoundingClientRect();
    this.width = rect.width || 800;
    this.height = rect.height || 600;

    // Create SVG
    this.svg = d3.select(this.container)
      .append('svg')
      .attr('width', '100%')
      .attr('height', '100%')
      .style('cursor', 'grab');

    // Grid pattern
    const defs = this.svg.append('defs');

    defs.append('pattern')
      .attr('id', 'grid-studio')
      .attr('width', 40)
      .attr('height', 40)
      .attr('patternUnits', 'userSpaceOnUse')
      .append('path')
      .attr('d', 'M 40 0 L 0 0 0 40')
      .attr('fill', 'none')
      .attr('stroke', '#1e293b')
      .attr('stroke-width', 0.5);

    // Arrow marker
    defs.append('marker')
      .attr('id', 'arrow-studio')
      .attr('viewBox', '0 0 10 6')
      .attr('refX', 10)
      .attr('refY', 3)
      .attr('markerWidth', 8)
      .attr('markerHeight', 6)
      .attr('orient', 'auto-start-reverse')
      .append('path')
      .attr('d', 'M 0 0 L 10 3 L 0 6 z')
      .attr('fill', '#94a3b8');

    // Glow filter
    const glow = defs.append('filter')
      .attr('id', 'glow-studio')
      .attr('x', '-50%')
      .attr('y', '-50%')
      .attr('width', '200%')
      .attr('height', '200%');
    glow.append('feGaussianBlur')
      .attr('stdDeviation', 3)
      .attr('result', 'blur');
    const merge = glow.append('feMerge');
    merge.append('feMergeNode').attr('in', 'blur');
    merge.append('feMergeNode').attr('in', 'SourceGraphic');

    // Background
    this.svg.append('rect')
      .attr('width', '100%')
      .attr('height', '100%')
      .attr('fill', 'url(#grid-studio)')
      .on('click', () => {
        this._clearSelection();
      });

    // Main group for zoom
    this.g = this.svg.append('g');

    // Groups for layering
    this.linkGroup = this.g.append('g').attr('class', 'links');
    this.nodeGroup = this.g.append('g').attr('class', 'nodes');

    // Setup zoom
    this.zoom = d3.zoom()
      .scaleExtent([0.1, 8])
      .on('zoom', (event) => {
        this.g.attr('transform', event.transform);
        this._currentTransform = event.transform;
        // Show/hide labels based on zoom level
        const showLabels = event.transform.k > 0.5;
        const showEdgeLabels = event.transform.k > 0.8;
        this.g.selectAll('.node-label').style('display', showLabels ? 'block' : 'none');
        this.g.selectAll('.edge-label').style('display', showEdgeLabels ? 'block' : 'none');
      });

    this.svg.call(this.zoom);
    this._currentTransform = d3.zoomIdentity;

    // Tooltip element
    this.tooltip = d3.select(this.container)
      .append('div')
      .attr('class', 'graph-tooltip')
      .style('display', 'none');

    // Resize observer
    this._resizeObserver = new ResizeObserver((entries) => {
      const { width, height } = entries[0].contentRect;
      if (width > 0 && height > 0) {
        this.width = width;
        this.height = height;
        if (this.simulation) {
          this.simulation
            .force('center', d3.forceCenter(width / 2, height / 2).strength(0.05))
            .force('x', d3.forceX(width / 2).strength(0.03))
            .force('y', d3.forceY(height / 2).strength(0.03))
            .alpha(0.3)
            .restart();
        }
      }
    });
    this._resizeObserver.observe(this.container);
  }

  // ---- DATA LOADING ----

  async load(query, types) {
    try {
      let url = `${this.options.apiBase}/graph/visualization?`;
      const params = [];
      if (query) params.push(`q=${encodeURIComponent(query)}`);
      if (types && types.length) params.push(`types=${encodeURIComponent(types.join(','))}`);
      url += params.join('&');

      const response = await fetch(url);
      const data = await response.json();

      this.nodes = data.nodes || [];
      this.links = data.links || [];

      this._render();
      return { nodes: this.nodes.length, links: this.links.length };
    } catch (err) {
      console.error('CogniGraphViz: failed to load data', err);
      return { nodes: 0, links: 0, error: err.message };
    }
  }

  loadData(data) {
    this.nodes = data.nodes || [];
    this.links = data.links || [];
    this._render();
  }

  // ---- RENDERING ----

  _render() {
    // Stop previous simulation
    if (this.simulation) {
      this.simulation.stop();
    }

    this.hasFitted = false;

    const n = this.nodes.length;
    if (n === 0) {
      this.linkGroup.selectAll('*').remove();
      this.nodeGroup.selectAll('*').remove();
      return;
    }

    // Adaptive force parameters
    const chargeStrength = n > 100 ? -120 : n > 40 ? -180 : -250;
    const linkDistance = n > 100 ? 50 : n > 40 ? 70 : 90;

    // Build simulation
    this.simulation = d3.forceSimulation(this.nodes)
      .force('link', d3.forceLink(this.links)
        .id(d => d.id)
        .distance(linkDistance)
        .strength(0.5))
      .force('charge', d3.forceManyBody()
        .strength(chargeStrength)
        .distanceMax(350))
      .force('center', d3.forceCenter(this.width / 2, this.height / 2)
        .strength(0.12))
      .force('collide', d3.forceCollide()
        .radius(d => (this._nodeRadius(d)) + 6)
        .strength(0.8))
      .force('x', d3.forceX(this.width / 2).strength(0.08))
      .force('y', d3.forceY(this.height / 2).strength(0.08))
      .alphaDecay(0.025)
      .velocityDecay(0.35);

    // Render links
    this.linkGroup.selectAll('*').remove();

    const linkEnter = this.linkGroup.selectAll('g')
      .data(this.links)
      .enter()
      .append('g');

    linkEnter.append('line')
      .attr('stroke', d => d.color || '#475569')
      .attr('stroke-width', d => d.width || 1.5)
      .attr('stroke-opacity', 0.6)
      .attr('marker-end', 'url(#arrow-studio)');

    linkEnter.append('text')
      .attr('class', 'edge-label')
      .attr('text-anchor', 'middle')
      .attr('fill', '#94a3b8')
      .attr('font-size', 9)
      .attr('font-weight', 500)
      .attr('dy', -4)
      .text(d => d.label || d.relationship || '');

    // Render nodes
    this.nodeGroup.selectAll('*').remove();

    const nodeEnter = this.nodeGroup.selectAll('g')
      .data(this.nodes)
      .enter()
      .append('g')
      .attr('class', 'node')
      .style('cursor', 'pointer')
      .call(this._drag())
      .on('click', (event, d) => {
        event.stopPropagation();
        this._selectNode(d);
      })
      .on('mouseenter', (event, d) => {
        this._showTooltip(event, d);
      })
      .on('mouseleave', () => {
        this._hideTooltip();
      });

    // Node circle
    nodeEnter.append('circle')
      .attr('r', d => this._nodeRadius(d))
      .attr('fill', d => getNodeColor(d.type || d.entity_type))
      .attr('stroke', '#334155')
      .attr('stroke-width', 2);

    // Inner letter
    nodeEnter.append('text')
      .attr('text-anchor', 'middle')
      .attr('dominant-baseline', 'central')
      .attr('fill', '#fff')
      .attr('font-size', d => this._nodeRadius(d) * 0.8)
      .attr('font-weight', 700)
      .style('pointer-events', 'none')
      .style('user-select', 'none')
      .style('text-shadow', '0 1px 2px rgba(0,0,0,0.3)')
      .text(d => (d.label || d.name || '?')[0].toUpperCase());

    // Label background + text
    const labelGroup = nodeEnter.append('g')
      .attr('class', 'node-label');

    labelGroup.append('rect')
      .attr('rx', 4)
      .attr('fill', 'rgba(15,23,42,0.85)')
      .style('pointer-events', 'none');

    labelGroup.append('text')
      .attr('text-anchor', 'middle')
      .attr('fill', '#e2e8f0')
      .attr('font-size', 11)
      .attr('font-weight', 600)
      .style('pointer-events', 'none')
      .style('user-select', 'none')
      .text(d => {
        const label = d.label || d.name || d.id;
        return label.length > 18 ? label.slice(0, 17) + '\u2026' : label;
      })
      .each(function(d) {
        // Size the background rect
        const bbox = this.getBBox();
        const r = (d.size || 20) / 2;
        d3.select(this.previousSibling)
          .attr('x', -bbox.width / 2 - 4)
          .attr('y', r + 4)
          .attr('width', bbox.width + 8)
          .attr('height', 16);
        d3.select(this)
          .attr('y', r + 16);
      });

    // Tick handler
    let tickCount = 0;
    this.simulation.on('tick', () => {
      tickCount++;
      if (tickCount % 2 !== 0 && this.simulation.alpha() > 0.1) return;

      // Update link positions
      linkEnter.select('line')
        .attr('x1', d => {
          const src = d.source;
          const tgt = d.target;
          const dx = tgt.x - src.x;
          const dy = tgt.y - src.y;
          const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
          const sr = this._nodeRadius(src) + 2;
          return src.x + (dx / dist) * sr;
        })
        .attr('y1', d => {
          const src = d.source;
          const tgt = d.target;
          const dx = tgt.x - src.x;
          const dy = tgt.y - src.y;
          const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
          const sr = this._nodeRadius(src) + 2;
          return src.y + (dy / dist) * sr;
        })
        .attr('x2', d => {
          const src = d.source;
          const tgt = d.target;
          const dx = tgt.x - src.x;
          const dy = tgt.y - src.y;
          const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
          const tr = this._nodeRadius(tgt) + 2;
          return tgt.x - (dx / dist) * tr;
        })
        .attr('y2', d => {
          const src = d.source;
          const tgt = d.target;
          const dx = tgt.x - src.x;
          const dy = tgt.y - src.y;
          const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
          const tr = this._nodeRadius(tgt) + 2;
          return tgt.y - (dy / dist) * tr;
        });

      // Update edge labels
      linkEnter.select('text')
        .attr('x', d => (d.source.x + d.target.x) / 2)
        .attr('y', d => (d.source.y + d.target.y) / 2);

      // Update node positions
      nodeEnter.attr('transform', d => `translate(${d.x},${d.y})`);

      // Auto-fit once settled
      if (!this.hasFitted && this.simulation.alpha() < 0.08 && this.nodes.length > 1) {
        this.hasFitted = true;
        this.fitToView(600);
      }
    });
  }

  // ---- NODE SIZE ----

  _nodeRadius(d) {
    // Base size from degree or explicit size
    if (d.size) return d.size / 2;
    const degree = (d.degree || 1);
    return Math.max(10, Math.min(30, 8 + Math.sqrt(degree) * 5));
  }

  // ---- DRAG BEHAVIOR ----

  _drag() {
    const sim = () => this.simulation;
    const self = this;

    return d3.drag()
      .on('start', function(event, d) {
        if (!event.active) sim()?.alphaTarget(0.3).restart();
        d.fx = d.x;
        d.fy = d.y;
        self.svg.style('cursor', 'grabbing');
      })
      .on('drag', function(event, d) {
        d.fx = event.x;
        d.fy = event.y;
      })
      .on('end', function(event, d) {
        if (!event.active) sim()?.alphaTarget(0);
        d.fx = null;
        d.fy = null;
        self.svg.style('cursor', 'grab');
      });
  }

  // ---- TOOLTIP ----

  _showTooltip(event, d) {
    const containerRect = this.container.getBoundingClientRect();
    const x = event.clientX - containerRect.left + 12;
    const y = event.clientY - containerRect.top - 10;
    const color = getNodeColor(d.type || d.entity_type);

    let html = `<div class="name">${this._escapeHtml(d.label || d.name || d.id)}</div>`;
    html += `<div class="type"><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${color};margin-right:6px;vertical-align:middle;"></span>${d.type || d.entity_type || 'ENTITY'}</div>`;
    if (d.description) {
      html += `<div class="desc">${this._escapeHtml(d.description.slice(0, 150))}</div>`;
    }
    if (d.confidence != null) {
      html += `<div class="confidence">Confidence: ${Math.round(d.confidence * 100)}%</div>`;
    }

    this.tooltip
      .html(html)
      .style('display', 'block')
      .style('left', Math.min(x, containerRect.width - 270) + 'px')
      .style('top', y + 'px');
  }

  _hideTooltip() {
    this.tooltip.style('display', 'none');
  }

  _escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  // ---- NODE SELECTION ----

  _selectNode(d) {
    // Highlight selected node
    this.nodeGroup.selectAll('circle')
      .attr('stroke', n => n.id === d.id ? '#3b82f6' : '#334155')
      .attr('stroke-width', n => n.id === d.id ? 3 : 2);

    // Callback
    if (this.options.onNodeClick) {
      this.options.onNodeClick(d);
    }

    // HTMX: load node detail if panel exists
    const detailPanel = document.getElementById('node-detail-panel');
    if (detailPanel) {
      htmx.ajax('GET', `/studio/api/partials/node-detail/${encodeURIComponent(d.id)}`, {
        target: '#node-detail-panel',
        swap: 'innerHTML',
      });
    }
  }

  _clearSelection() {
    this.nodeGroup.selectAll('circle')
      .attr('stroke', '#334155')
      .attr('stroke-width', 2);
  }

  // ---- ZOOM CONTROLS ----

  zoomIn() {
    this.svg.transition().duration(300).call(this.zoom.scaleBy, 1.4);
  }

  zoomOut() {
    this.svg.transition().duration(300).call(this.zoom.scaleBy, 0.7);
  }

  fitToView(duration = 500) {
    if (this.nodes.length === 0) return;

    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const node of this.nodes) {
      if (node.x != null && node.y != null) {
        if (node.x < minX) minX = node.x;
        if (node.y < minY) minY = node.y;
        if (node.x > maxX) maxX = node.x;
        if (node.y > maxY) maxY = node.y;
      }
    }

    if (minX === Infinity) return;

    const pad = 60;
    const bw = maxX - minX + pad * 2;
    const bh = maxY - minY + pad * 2;
    const cx = (minX + maxX) / 2;
    const cy = (minY + maxY) / 2;
    const scale = Math.min(this.width / bw, this.height / bh, 1.5);
    const tx = this.width / 2 - cx * scale;
    const ty = this.height / 2 - cy * scale;

    this.svg.transition()
      .duration(duration)
      .call(this.zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(scale));
  }

  resetView() {
    this.svg.transition().duration(500)
      .call(this.zoom.transform, d3.zoomIdentity);
    if (this.simulation) {
      this.simulation.alpha(0.5).restart();
    }
  }

  // ---- FILTERING ----

  filter(query, types) {
    // Re-fetch with filters
    this.load(query, types);
  }

  highlightNodes(nodeIds) {
    const idSet = new Set(nodeIds);
    this.nodeGroup.selectAll('.node')
      .style('opacity', d => idSet.size === 0 || idSet.has(d.id) ? 1 : 0.15);
    this.linkGroup.selectAll('g')
      .style('opacity', d => {
        if (idSet.size === 0) return 1;
        const srcId = typeof d.source === 'object' ? d.source.id : d.source;
        const tgtId = typeof d.target === 'object' ? d.target.id : d.target;
        return idSet.has(srcId) || idSet.has(tgtId) ? 1 : 0.08;
      });
  }

  clearHighlight() {
    this.nodeGroup.selectAll('.node').style('opacity', 1);
    this.linkGroup.selectAll('g').style('opacity', 1);
  }

  // ---- REASONING ANIMATION ----

  pulseNode(nodeId, color) {
    const node = this.nodeGroup.selectAll('.node')
      .filter(d => d.id === nodeId);

    if (node.empty()) return;

    // Add glow ring
    node.insert('circle', ':first-child')
      .attr('class', 'pulse-ring')
      .attr('r', 0)
      .attr('fill', 'none')
      .attr('stroke', color || '#3b82f6')
      .attr('stroke-width', 2.5)
      .attr('stroke-opacity', 0.8)
      .attr('filter', 'url(#glow-studio)')
      .transition()
      .duration(800)
      .attr('r', d => this._nodeRadius(d) + 15)
      .attr('stroke-opacity', 0)
      .remove();
  }

  // ---- CLEANUP ----

  destroy() {
    if (this.simulation) this.simulation.stop();
    if (this._resizeObserver) this._resizeObserver.disconnect();
    if (this.container) {
      d3.select(this.container).selectAll('*').remove();
    }
  }
}

// Export for use
window.CogniGraphViz = CogniGraphViz;
window.getNodeColor = getNodeColor;
window.ENTITY_COLORS = ENTITY_COLORS;
