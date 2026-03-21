"""Navigator — page navigation + route discovery."""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urljoin, urlparse

logger = logging.getLogger("graqle.phantom.navigator")


class Navigator:
    """Handles page navigation, wait strategies, and automatic route discovery."""

    async def goto(
        self,
        page: Any,
        url: str,
        wait_for: str = "networkidle",
        timeout: int = 30000,
    ) -> dict[str, Any]:
        """Navigate to a URL with configurable wait strategy."""
        import time

        start = time.time()
        response = await page.goto(url, wait_until=wait_for, timeout=timeout)
        load_time = int((time.time() - start) * 1000)

        return {
            "url": page.url,
            "status": response.status if response else None,
            "load_time_ms": load_time,
            "redirected": page.url != url,
        }

    async def discover_routes(
        self,
        page: Any,
        start_url: str,
        max_depth: int = 3,
        max_pages: int = 50,
        exclude_patterns: list[str] | None = None,
    ) -> dict[str, Any]:
        """Auto-discover all navigable pages from a starting URL.

        Crawls sidebar, nav menus, and in-page links to build a route map.
        """
        exclude_patterns = exclude_patterns or []
        base = urlparse(start_url)
        base_origin = f"{base.scheme}://{base.netloc}"

        discovered: list[dict[str, Any]] = []
        visited: set[str] = set()
        queue: list[tuple[str, int, str]] = [(start_url, 0, "direct")]

        while queue and len(discovered) < max_pages:
            url, depth, source = queue.pop(0)

            # Normalize
            parsed = urlparse(url)
            path = parsed.path or "/"
            normalized = f"{base_origin}{path}"

            if normalized in visited or depth > max_depth:
                continue

            # Check exclude patterns
            if any(pattern in path for pattern in exclude_patterns):
                continue

            visited.add(normalized)

            try:
                await self.goto(page, normalized, wait_for="networkidle", timeout=15000)
                await page.wait_for_timeout(1000)

                title = await page.title()
                actual_path = urlparse(page.url).path

                # Detect auth requirement
                auth_required = "/login" in page.url or "/signin" in page.url

                discovered.append({
                    "path": actual_path,
                    "title": title,
                    "auth_required": auth_required and actual_path != path,
                    "nav_source": source,
                })

                # Extract links for further crawling
                if depth < max_depth:
                    links = await self._extract_links(page, base_origin)
                    for link_url, link_source in links:
                        queue.append((link_url, depth + 1, link_source))

            except Exception as exc:
                logger.warning("Failed to visit %s: %s", normalized, exc)
                discovered.append({
                    "path": path,
                    "title": "(error)",
                    "auth_required": False,
                    "nav_source": source,
                    "error": str(exc),
                })

        # Extract nav structure from last visited page
        nav_structure = await self._extract_nav_structure(page)

        return {
            "base_url": base_origin,
            "pages_discovered": len(discovered),
            "route_map": discovered,
            "navigation_structure": nav_structure,
        }

    async def _extract_links(self, page: Any, base_origin: str) -> list[tuple[str, str]]:
        """Extract unique internal links from the current page."""
        links = await page.evaluate("""
            () => {
                const links = [];
                const seen = new Set();

                // Sidebar links
                document.querySelectorAll('nav a, aside a, [role="navigation"] a').forEach(a => {
                    const href = a.getAttribute('href');
                    if (href && !seen.has(href)) {
                        seen.add(href);
                        links.push({url: href, source: 'sidebar'});
                    }
                });

                // Main content links
                document.querySelectorAll('main a, #content a, .content a').forEach(a => {
                    const href = a.getAttribute('href');
                    if (href && !seen.has(href)) {
                        seen.add(href);
                        links.push({url: href, source: 'content'});
                    }
                });

                // Any remaining links
                document.querySelectorAll('a[href]').forEach(a => {
                    const href = a.getAttribute('href');
                    if (href && !seen.has(href)) {
                        seen.add(href);
                        links.push({url: href, source: 'link'});
                    }
                });

                return links;
            }
        """)

        result = []
        for link in links:
            href = link["url"]
            if href.startswith("/"):
                result.append((f"{base_origin}{href}", link["source"]))
            elif href.startswith(base_origin):
                result.append((href, link["source"]))
            # Skip external links, mailto:, tel:, javascript:, #anchors
        return result

    async def _extract_nav_structure(self, page: Any) -> dict[str, Any]:
        """Extract navigation structure from the current page."""
        return await page.evaluate("""
            () => {
                const structure = {sidebar: [], breadcrumbs: false, top_nav: []};

                // Sidebar items
                document.querySelectorAll('nav a, aside a, [role="navigation"] a').forEach(a => {
                    const text = (a.textContent || '').trim();
                    if (text && text.length < 50) {
                        structure.sidebar.push(text);
                    }
                });

                // Breadcrumbs
                structure.breadcrumbs = !!document.querySelector(
                    'nav[aria-label*="breadcrumb"], .breadcrumb, [class*="breadcrumb"]'
                );

                // Top nav
                const header = document.querySelector('header');
                if (header) {
                    header.querySelectorAll('a').forEach(a => {
                        const text = (a.textContent || '').trim();
                        if (text && text.length < 50) {
                            structure.top_nav.push(text);
                        }
                    });
                }

                return structure;
            }
        """)
