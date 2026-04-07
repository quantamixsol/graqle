/**
 * ProtocolFlow — SVG 7-step protocol sequence visualization
 * Renders: inspect → context → impact → preflight → reason → generate → review
 * Dark theme, responsive SVG, no external dependencies.
 * @version 1.0.0 — Spec 6 FLOW layer
 */
(function (root) {
  'use strict';

  var STEPS = [
    { id: 'inspect',   label: 'Inspect' },
    { id: 'context',   label: 'Context' },
    { id: 'impact',    label: 'Impact' },
    { id: 'preflight', label: 'Preflight' },
    { id: 'reason',    label: 'Reason' },
    { id: 'generate',  label: 'Generate' },
    { id: 'review',    label: 'Review' },
  ];

  var THEME = {
    bg: '#0f172a', border: '#1e293b', text: '#94a3b8',
    idle: '#1e293b', idleStroke: '#334155',
    active: '#fbbf24', done: '#34d399', error: '#f87171',
    connector: '#334155', badge: '#7c3aed', cost: '#38bdf8',
  };

  var SVG_NS = 'http://www.w3.org/2000/svg';
  var R = 28, PADDING = 24, CY = 72, BADGE_R = 9;

  // Ring buffer (50 events)
  function RingBuffer(cap) { this._b = []; this._cap = cap; }
  RingBuffer.prototype.push = function(v) { this._b.push(v); if (this._b.length > this._cap) this._b.shift(); };
  RingBuffer.prototype.toArray = function() { return this._b.slice(); };
  RingBuffer.prototype.clear = function() { this._b = []; };

  function mk(tag, attrs) {
    var el = document.createElementNS(SVG_NS, tag);
    for (var k in attrs) { if (attrs.hasOwnProperty(k)) el.setAttribute(k, attrs[k]); }
    return el;
  }

  function ProtocolFlow(containerId) {
    this._container = typeof containerId === 'string' ? document.getElementById(containerId) : containerId;
    if (!this._container) throw new Error('ProtocolFlow: container not found');
    this._events = new RingBuffer(50);
    this._states = {};
    this._els = {};
    STEPS.forEach(function(s) { this._states[s.id] = 'idle'; }.bind(this));
    this._build();
  }

  ProtocolFlow.prototype._build = function() {
    var w = this._container.clientWidth || 700, h = 140;
    var step = (w - PADDING * 2) / (STEPS.length - 1);
    var svg = mk('svg', { viewBox: '0 0 ' + w + ' ' + h, xmlns: SVG_NS });
    svg.style.cssText = 'display:block;width:100%;height:auto;background:' + THEME.bg + ';border-radius:8px;border:1px solid ' + THEME.border;

    // Connectors
    for (var i = 0; i < STEPS.length - 1; i++) {
      svg.appendChild(mk('line', {
        x1: PADDING + i * step + R, y1: CY,
        x2: PADDING + (i + 1) * step - R, y2: CY,
        stroke: THEME.connector, 'stroke-width': 2,
      }));
    }

    // Steps
    var self = this;
    STEPS.forEach(function(s, i) {
      var cx = PADDING + i * step;
      var g = {};

      // Circle
      g.circle = mk('circle', { cx: cx, cy: CY, r: R, fill: THEME.idle, stroke: THEME.idleStroke, 'stroke-width': 2 });
      svg.appendChild(g.circle);

      // Number
      g.num = mk('text', { x: cx, y: CY - 5, 'text-anchor': 'middle', 'dominant-baseline': 'middle', fill: THEME.text, 'font-size': '11', 'font-weight': '600', 'font-family': 'monospace' });
      g.num.textContent = String(i + 1);
      svg.appendChild(g.num);

      // ID label inside
      g.inner = mk('text', { x: cx, y: CY + 9, 'text-anchor': 'middle', 'dominant-baseline': 'middle', fill: THEME.text, 'font-size': '8', 'font-family': 'monospace' });
      g.inner.textContent = s.id.toUpperCase();
      svg.appendChild(g.inner);

      // Label below
      g.label = mk('text', { x: cx, y: CY + R + 16, 'text-anchor': 'middle', fill: THEME.text, 'font-size': '10', 'font-family': 'sans-serif' });
      g.label.textContent = s.label;
      svg.appendChild(g.label);

      // Badge (hidden)
      g.badgeG = mk('g', { visibility: 'hidden' });
      g.badgeCircle = mk('circle', { cx: cx + R - 2, cy: CY - R + 2, r: BADGE_R, fill: THEME.badge });
      g.badgeText = mk('text', { x: cx + R - 2, y: CY - R + 2, 'text-anchor': 'middle', 'dominant-baseline': 'middle', fill: '#fff', 'font-size': '8', 'font-weight': '700' });
      g.badgeG.appendChild(g.badgeCircle);
      g.badgeG.appendChild(g.badgeText);
      svg.appendChild(g.badgeG);

      // Cost label (hidden)
      g.costEl = mk('text', { x: cx, y: CY + R + 30, 'text-anchor': 'middle', fill: THEME.cost, 'font-size': '9', visibility: 'hidden', 'font-family': 'monospace' });
      svg.appendChild(g.costEl);

      self._els[s.id] = g;
    });

    this._container.innerHTML = '';
    this._container.appendChild(svg);
  };

  ProtocolFlow.prototype._apply = function(id) {
    var g = this._els[id]; if (!g) return;
    var s = this._states[id];
    var c = { idle: { f: THEME.idle, s: THEME.idleStroke, t: THEME.text },
              active: { f: '#451a03', s: THEME.active, t: THEME.active },
              done: { f: '#022c22', s: THEME.done, t: THEME.done },
              error: { f: '#2d0a0a', s: THEME.error, t: THEME.error } }[s] || { f: THEME.idle, s: THEME.idleStroke, t: THEME.text };
    g.circle.setAttribute('fill', c.f);
    g.circle.setAttribute('stroke', c.s);
    g.num.setAttribute('fill', c.t);
    g.inner.setAttribute('fill', c.t);
    g.label.setAttribute('fill', c.t);
  };

  ProtocolFlow.prototype.setActiveStep = function(id) { this._states[id] = 'active'; this._apply(id); this._events.push({ ts: Date.now(), type: 'active', step: id }); return this; };
  ProtocolFlow.prototype.completeStep = function(id) { this._states[id] = 'done'; this._apply(id); this._events.push({ ts: Date.now(), type: 'done', step: id }); return this; };
  ProtocolFlow.prototype.failStep = function(id) { this._states[id] = 'error'; this._apply(id); this._events.push({ ts: Date.now(), type: 'error', step: id }); return this; };

  ProtocolFlow.prototype.addBadge = function(id, text) {
    var g = this._els[id]; if (!g) return this;
    g.badgeText.textContent = String(text);
    g.badgeG.setAttribute('visibility', 'visible');
    return this;
  };

  ProtocolFlow.prototype.addCostLabel = function(id, costUsd) {
    var g = this._els[id]; if (!g) return this;
    g.costEl.textContent = '$' + Number(costUsd).toFixed(4);
    g.costEl.setAttribute('visibility', 'visible');
    return this;
  };

  ProtocolFlow.prototype.reset = function() {
    var self = this;
    STEPS.forEach(function(s) {
      self._states[s.id] = 'idle';
      self._apply(s.id);
      self._els[s.id].badgeG.setAttribute('visibility', 'hidden');
      self._els[s.id].costEl.setAttribute('visibility', 'hidden');
    });
    this._events.clear();
    return this;
  };

  ProtocolFlow.prototype.appendEvent = function(e) { this._events.push(e); };
  ProtocolFlow.prototype.getEvents = function() { return this._events.toArray(); };

  root.ProtocolFlow = ProtocolFlow;
}(window));
