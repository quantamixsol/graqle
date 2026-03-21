"""Interactor — click, type, scroll, hover, drag."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("graqle.phantom.interactor")


class Interactor:
    """Handles UI interactions: clicking, typing, scrolling."""

    async def find_element(self, page: Any, target: str) -> Any | None:
        """Find an element by flexible target specification.

        Accepts:
            - Visible text: 'Dashboard' → finds button/link with that text
            - CSS selector: '#submit-btn' or 'button.primary'
            - Coordinates: '450,300' → element at x=450, y=300
            - Role: 'role:button:Submit' → aria role matching
        """
        if target.startswith("role:"):
            parts = target.split(":", 2)
            role = parts[1]
            name = parts[2] if len(parts) > 2 else None
            if name:
                el = page.get_by_role(role, name=name)
            else:
                el = page.get_by_role(role)
            if await el.count() > 0:
                return el.first
            return None

        # Coordinates: "450,300"
        if "," in target and all(p.strip().isdigit() for p in target.split(",", 1)):
            x, y = (int(p.strip()) for p in target.split(",", 1))
            # Return a pseudo-locator that clicks at coordinates
            return _CoordinateTarget(page, x, y)

        # CSS selector (contains #, ., [, or starts with tag names)
        if any(c in target for c in ("#", ".", "[", ">", "~", "+")):
            try:
                el = page.locator(target)
                if await el.count() > 0:
                    return el.first
            except Exception:
                pass

        # Text-based: try getByText, then getByRole with name
        el = page.get_by_text(target, exact=False)
        if await el.count() > 0:
            return el.first

        # Try as button/link role
        for role in ("button", "link", "menuitem", "tab"):
            el = page.get_by_role(role, name=target)
            if await el.count() > 0:
                return el.first

        return None

    async def find_input(self, page: Any, target: str) -> Any | None:
        """Find an input element by flexible target specification.

        Accepts:
            - placeholder: 'placeholder:Search...'
            - label: 'label:Email address'
            - CSS selector: 'input[name=email]'
            - name: 'name:workspace_name'
            - type: 'type:email'
        """
        if target.startswith("placeholder:"):
            text = target[len("placeholder:"):]
            el = page.get_by_placeholder(text)
            if await el.count() > 0:
                return el.first

        elif target.startswith("label:"):
            text = target[len("label:"):]
            el = page.get_by_label(text)
            if await el.count() > 0:
                return el.first

        elif target.startswith("name:"):
            name = target[len("name:"):]
            el = page.locator(f"input[name='{name}'], textarea[name='{name}'], select[name='{name}']")
            if await el.count() > 0:
                return el.first

        elif target.startswith("type:"):
            input_type = target[len("type:"):]
            el = page.locator(f"input[type='{input_type}']")
            if await el.count() > 0:
                return el.first

        else:
            # Try as CSS selector
            try:
                el = page.locator(target)
                if await el.count() > 0:
                    return el.first
            except Exception:
                pass

            # Try as label
            el = page.get_by_label(target)
            if await el.count() > 0:
                return el.first

            # Try as placeholder
            el = page.get_by_placeholder(target)
            if await el.count() > 0:
                return el.first

        return None

    async def get_element_info(self, element: Any) -> dict[str, Any]:
        """Extract info about an element for reporting."""
        if isinstance(element, _CoordinateTarget):
            return {"tag": "COORDINATE", "x": element.x, "y": element.y}

        try:
            tag = await element.evaluate("el => el.tagName")
            text = await element.evaluate("el => (el.textContent || '').trim().substring(0, 100)")
            bbox = await element.bounding_box()
            return {
                "tag": tag,
                "text": text,
                "width": int(bbox["width"]) if bbox else 0,
                "height": int(bbox["height"]) if bbox else 0,
            }
        except Exception:
            return {"tag": "UNKNOWN", "text": ""}

    async def scroll(self, page: Any, direction: str = "down", amount: int = 500) -> None:
        """Scroll the page."""
        if direction == "down":
            await page.evaluate(f"window.scrollBy(0, {amount})")
        elif direction == "up":
            await page.evaluate(f"window.scrollBy(0, -{amount})")
        elif direction == "top":
            await page.evaluate("window.scrollTo(0, 0)")
        elif direction == "bottom":
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")


class _CoordinateTarget:
    """Pseudo-element for coordinate-based clicking."""

    def __init__(self, page: Any, x: int, y: int):
        self.page = page
        self.x = x
        self.y = y

    async def click(self, **kwargs: Any) -> None:
        await self.page.mouse.click(self.x, self.y)

    async def dblclick(self, **kwargs: Any) -> None:
        await self.page.mouse.dblclick(self.x, self.y)

    async def hover(self) -> None:
        await self.page.mouse.move(self.x, self.y)
