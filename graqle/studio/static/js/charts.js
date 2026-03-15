/**
 * CogniGraph Studio — Chart Helpers
 * Simple D3 chart components for metrics dashboard
 *
 * @version 0.11.0
 */

// ── graqle:intelligence ──
// module: graqle.studio.static.js.charts
// risk: LOW (impact radius: 0 modules)
// constraints: none
// ── /graqle:intelligence ──

// ============================================================================
// BAR CHART (Session history, node type distribution)
// ============================================================================

function renderBarChart(containerId, data, options = {}) {
  const container = document.getElementById(containerId);
  if (!container || !data || !data.length) return;

  const {
    width = container.clientWidth || 400,
    height = options.height || 180,
    color = '#0ea5e9',
    xKey = 'label',
    yKey = 'value',
    margin = { top: 10, right: 10, bottom: 30, left: 40 },
  } = options;

  // Clear previous
  d3.select(container).selectAll('*').remove();

  const svg = d3.select(container)
    .append('svg')
    .attr('width', width)
    .attr('height', height);

  const innerW = width - margin.left - margin.right;
  const innerH = height - margin.top - margin.bottom;

  const g = svg.append('g')
    .attr('transform', `translate(${margin.left},${margin.top})`);

  // Scales
  const x = d3.scaleBand()
    .domain(data.map(d => d[xKey]))
    .range([0, innerW])
    .padding(0.3);

  const y = d3.scaleLinear()
    .domain([0, d3.max(data, d => d[yKey]) || 1])
    .nice()
    .range([innerH, 0]);

  // Bars
  g.selectAll('rect')
    .data(data)
    .enter()
    .append('rect')
    .attr('x', d => x(d[xKey]))
    .attr('y', d => y(d[yKey]))
    .attr('width', x.bandwidth())
    .attr('height', d => innerH - y(d[yKey]))
    .attr('fill', color)
    .attr('rx', 3)
    .attr('opacity', 0.8)
    .on('mouseenter', function() { d3.select(this).attr('opacity', 1); })
    .on('mouseleave', function() { d3.select(this).attr('opacity', 0.8); });

  // X axis
  g.append('g')
    .attr('transform', `translate(0,${innerH})`)
    .call(d3.axisBottom(x).tickSize(0))
    .selectAll('text')
    .attr('fill', '#64748b')
    .attr('font-size', 10)
    .attr('transform', 'rotate(-30)')
    .attr('text-anchor', 'end');

  g.select('.domain').attr('stroke', '#334155');

  // Y axis
  g.append('g')
    .call(d3.axisLeft(y).ticks(4).tickSize(-innerW))
    .selectAll('text')
    .attr('fill', '#64748b')
    .attr('font-size', 10);

  g.selectAll('.tick line')
    .attr('stroke', '#1e293b')
    .attr('stroke-dasharray', '2,2');

  g.select('.domain').remove();
}

// ============================================================================
// LINE CHART (Confidence trajectory, token usage over time)
// ============================================================================

function renderLineChart(containerId, data, options = {}) {
  const container = document.getElementById(containerId);
  if (!container || !data || !data.length) return;

  const {
    width = container.clientWidth || 400,
    height = options.height || 180,
    color = '#10b981',
    xKey = 'x',
    yKey = 'y',
    margin = { top: 10, right: 10, bottom: 30, left: 40 },
    area = true,
  } = options;

  d3.select(container).selectAll('*').remove();

  const svg = d3.select(container)
    .append('svg')
    .attr('width', width)
    .attr('height', height);

  const innerW = width - margin.left - margin.right;
  const innerH = height - margin.top - margin.bottom;

  const g = svg.append('g')
    .attr('transform', `translate(${margin.left},${margin.top})`);

  const x = d3.scaleLinear()
    .domain(d3.extent(data, d => d[xKey]))
    .range([0, innerW]);

  const y = d3.scaleLinear()
    .domain([0, d3.max(data, d => d[yKey]) || 1])
    .nice()
    .range([innerH, 0]);

  // Area fill
  if (area) {
    const areaGen = d3.area()
      .x(d => x(d[xKey]))
      .y0(innerH)
      .y1(d => y(d[yKey]))
      .curve(d3.curveMonotoneX);

    g.append('path')
      .datum(data)
      .attr('d', areaGen)
      .attr('fill', color)
      .attr('fill-opacity', 0.1);
  }

  // Line
  const line = d3.line()
    .x(d => x(d[xKey]))
    .y(d => y(d[yKey]))
    .curve(d3.curveMonotoneX);

  g.append('path')
    .datum(data)
    .attr('d', line)
    .attr('fill', 'none')
    .attr('stroke', color)
    .attr('stroke-width', 2);

  // Dots
  g.selectAll('circle')
    .data(data)
    .enter()
    .append('circle')
    .attr('cx', d => x(d[xKey]))
    .attr('cy', d => y(d[yKey]))
    .attr('r', 3)
    .attr('fill', color)
    .attr('stroke', '#0f172a')
    .attr('stroke-width', 1.5);

  // Axes
  g.append('g')
    .attr('transform', `translate(0,${innerH})`)
    .call(d3.axisBottom(x).ticks(5).tickSize(0))
    .selectAll('text')
    .attr('fill', '#64748b')
    .attr('font-size', 10);

  g.select('.domain').attr('stroke', '#334155');

  g.append('g')
    .call(d3.axisLeft(y).ticks(4).tickSize(-innerW))
    .selectAll('text')
    .attr('fill', '#64748b')
    .attr('font-size', 10);

  g.selectAll('.tick line')
    .attr('stroke', '#1e293b')
    .attr('stroke-dasharray', '2,2');

  g.selectAll('.domain').filter(function() {
    return this.parentNode !== g.select('g:last-of-type').node();
  }).remove();
}

// ============================================================================
// DONUT CHART (Node type distribution)
// ============================================================================

function renderDonutChart(containerId, data, options = {}) {
  const container = document.getElementById(containerId);
  if (!container || !data || !data.length) return;

  const {
    width = container.clientWidth || 200,
    height = options.height || 200,
    innerRadius = 40,
    outerRadius = Math.min(width, height) / 2 - 10,
  } = options;

  d3.select(container).selectAll('*').remove();

  const svg = d3.select(container)
    .append('svg')
    .attr('width', width)
    .attr('height', height);

  const g = svg.append('g')
    .attr('transform', `translate(${width / 2},${height / 2})`);

  const pie = d3.pie()
    .value(d => d.value)
    .sort(null)
    .padAngle(0.02);

  const arc = d3.arc()
    .innerRadius(innerRadius)
    .outerRadius(outerRadius);

  const arcs = g.selectAll('path')
    .data(pie(data))
    .enter()
    .append('path')
    .attr('d', arc)
    .attr('fill', d => d.data.color || '#64748b')
    .attr('stroke', '#0f172a')
    .attr('stroke-width', 2)
    .attr('opacity', 0.85)
    .on('mouseenter', function() { d3.select(this).attr('opacity', 1); })
    .on('mouseleave', function() { d3.select(this).attr('opacity', 0.85); });

  // Center text (total)
  const total = data.reduce((sum, d) => sum + d.value, 0);
  g.append('text')
    .attr('text-anchor', 'middle')
    .attr('dominant-baseline', 'central')
    .attr('fill', '#e2e8f0')
    .attr('font-size', 20)
    .attr('font-weight', 700)
    .text(total);
}

// ============================================================================
// GAUGE CHART (Health score, safety score)
// ============================================================================

function renderGauge(containerId, value, options = {}) {
  const container = document.getElementById(containerId);
  if (!container) return;

  const {
    width = container.clientWidth || 120,
    height = options.height || 80,
    max = 100,
    color = value >= 80 ? '#10b981' : value >= 50 ? '#f59e0b' : '#ef4444',
    label = '',
  } = options;

  d3.select(container).selectAll('*').remove();

  const svg = d3.select(container)
    .append('svg')
    .attr('width', width)
    .attr('height', height);

  const g = svg.append('g')
    .attr('transform', `translate(${width / 2},${height - 10})`);

  const r = Math.min(width / 2, height) - 10;
  const startAngle = -Math.PI / 2;
  const endAngle = Math.PI / 2;

  const arcGen = d3.arc()
    .innerRadius(r - 10)
    .outerRadius(r)
    .startAngle(startAngle);

  // Background arc
  g.append('path')
    .attr('d', arcGen({ endAngle }))
    .attr('fill', '#1e293b');

  // Value arc
  const valueAngle = startAngle + (endAngle - startAngle) * (Math.min(value, max) / max);
  g.append('path')
    .attr('d', arcGen({ endAngle: valueAngle }))
    .attr('fill', color);

  // Value text
  g.append('text')
    .attr('text-anchor', 'middle')
    .attr('y', -15)
    .attr('fill', '#e2e8f0')
    .attr('font-size', 18)
    .attr('font-weight', 700)
    .text(Math.round(value));

  if (label) {
    g.append('text')
      .attr('text-anchor', 'middle')
      .attr('y', 2)
      .attr('fill', '#64748b')
      .attr('font-size', 9)
      .text(label);
  }
}

// ============================================================================
// MINI SPARKLINE (For metric cards)
// ============================================================================

function renderSparkline(containerId, data, options = {}) {
  const container = document.getElementById(containerId);
  if (!container || !data || !data.length) return;

  const {
    width = container.clientWidth || 100,
    height = options.height || 30,
    color = '#0ea5e9',
  } = options;

  d3.select(container).selectAll('*').remove();

  const svg = d3.select(container)
    .append('svg')
    .attr('width', width)
    .attr('height', height);

  const x = d3.scaleLinear()
    .domain([0, data.length - 1])
    .range([2, width - 2]);

  const y = d3.scaleLinear()
    .domain([0, d3.max(data) || 1])
    .range([height - 2, 2]);

  const line = d3.line()
    .x((d, i) => x(i))
    .y(d => y(d))
    .curve(d3.curveMonotoneX);

  // Area
  const area = d3.area()
    .x((d, i) => x(i))
    .y0(height)
    .y1(d => y(d))
    .curve(d3.curveMonotoneX);

  svg.append('path')
    .datum(data)
    .attr('d', area)
    .attr('fill', color)
    .attr('fill-opacity', 0.1);

  svg.append('path')
    .datum(data)
    .attr('d', line)
    .attr('fill', 'none')
    .attr('stroke', color)
    .attr('stroke-width', 1.5);
}

// Export
window.renderBarChart = renderBarChart;
window.renderLineChart = renderLineChart;
window.renderDonutChart = renderDonutChart;
window.renderGauge = renderGauge;
window.renderSparkline = renderSparkline;
