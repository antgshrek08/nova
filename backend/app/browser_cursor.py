"""Nova's visible virtual cursor for browser automation.

Provides a visible pointer tagged "Nova" that glides across web pages,
clicks buttons, and drags interactive elements (such as Knewton Alta graphs,
ALEKS sliders, coordinate plane points) without touching the user's
real Windows desktop mouse cursor.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

CURSOR_INIT_JS = """
(() => {
    if (document.getElementById('nova-virtual-cursor')) return;
    const container = document.createElement('div');
    container.id = 'nova-virtual-cursor';
    container.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        pointer-events: none !important;
        z-index: 2147483647;
        transition: transform 0.22s cubic-bezier(0.2, 0.85, 0.4, 1);
        will-change: transform;
        transform: translate3d(-50px, -50px, 0);
    `;

    // SVG Cursor Arrow + Pulsing Glow Ring + "Nova" Badge
    container.innerHTML = `
        <div style="position: relative; width: 32px; height: 32px;">
            <div id="nova-cursor-ripple" style="
                position: absolute;
                top: 0;
                left: 0;
                width: 24px;
                height: 24px;
                border-radius: 50%;
                background: rgba(16, 185, 129, 0.4);
                transform: scale(0);
                transition: transform 0.2s ease-out, opacity 0.2s ease-out;
                pointer-events: none;
            "></div>
            <svg width="26" height="26" viewBox="0 0 24 24" fill="none" style="filter: drop-shadow(0 2px 4px rgba(0,0,0,0.4));">
                <path d="M3 3L10.07 20.97L12.58 13.58L19.97 11.07L3 3Z" fill="#10b981" stroke="#ffffff" stroke-width="1.5" stroke-linejoin="round"/>
            </svg>
            <div id="nova-cursor-badge" style="
                position: absolute;
                left: 18px;
                top: 14px;
                background: #0f172a;
                border: 1px solid #10b981;
                color: #34d399;
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                font-size: 11px;
                font-weight: 700;
                letter-spacing: 0.5px;
                padding: 1px 6px;
                border-radius: 4px;
                box-shadow: 0 4px 10px rgba(0,0,0,0.5);
                white-space: nowrap;
                user-select: none;
            ">Nova</div>
        </div>
    `;
    (document.body || document.documentElement).appendChild(container);
})();
"""

CURSOR_MOVE_JS = """
(pos) => {
    const el = document.getElementById('nova-virtual-cursor');
    if (el) {
        el.style.transform = `translate3d(${pos.x}px, ${pos.y}px, 0)`;
    }
}
"""

CURSOR_CLICK_ANIM_JS = """
(pos) => {
    const el = document.getElementById('nova-virtual-cursor');
    const ripple = document.getElementById('nova-cursor-ripple');
    if (el) {
        el.style.transform = `translate3d(${pos.x}px, ${pos.y}px, 0) scale(0.92)`;
        if (ripple) {
            ripple.style.transform = 'scale(2.2)';
            ripple.style.opacity = '0.7';
            setTimeout(() => {
                ripple.style.transform = 'scale(0)';
                ripple.style.opacity = '0';
                el.style.transform = `translate3d(${pos.x}px, ${pos.y}px, 0) scale(1)`;
            }, 220);
        }
    }
}
"""

CURSOR_DRAG_START_JS = """
(pos) => {
    const el = document.getElementById('nova-virtual-cursor');
    const badge = document.getElementById('nova-cursor-badge');
    if (el) {
        el.style.transform = `translate3d(${pos.x}px, ${pos.y}px, 0) scale(1.15)`;
        if (badge) {
            badge.innerText = 'Nova (Dragging)';
            badge.style.background = '#047857';
            badge.style.color = '#ffffff';
        }
    }
}
"""

CURSOR_DRAG_END_JS = """
(pos) => {
    const el = document.getElementById('nova-virtual-cursor');
    const badge = document.getElementById('nova-cursor-badge');
    if (el) {
        el.style.transform = `translate3d(${pos.x}px, ${pos.y}px, 0) scale(1)`;
        if (badge) {
            badge.innerText = 'Nova';
            badge.style.background = '#0f172a';
            badge.style.color = '#34d399';
        }
    }
}
"""


async def ensure_cursor(page: Any) -> None:
    """Ensure Nova's virtual cursor is injected into the active page."""
    try:
        await page.evaluate(CURSOR_INIT_JS)
    except Exception:
        pass


async def glide_to(page: Any, x: float, y: float, delay: float = 0.25) -> None:
    """Smoothly glide Nova's cursor to a coordinate."""
    await ensure_cursor(page)
    try:
        await page.evaluate(CURSOR_MOVE_JS, {"x": round(x), "y": round(y)})
        await asyncio.sleep(delay)
    except Exception:
        pass


async def click_at(page: Any, x: float, y: float) -> None:
    """Glide Nova's cursor to (x, y), animate a click, and dispatch Playwright mouse event."""
    await ensure_cursor(page)
    await glide_to(page, x, y, delay=0.22)
    try:
        await page.evaluate(CURSOR_CLICK_ANIM_JS, {"x": round(x), "y": round(y)})
    except Exception:
        pass
    await page.mouse.click(x, y)
    await asyncio.sleep(0.15)


async def click_element(page: Any, selector_or_locator: Any) -> None:
    """Glide Nova's cursor to the center of an element and click it."""
    loc = selector_or_locator if hasattr(selector_or_locator, 'bounding_box') else page.locator(selector_or_locator).first
    box = await loc.bounding_box()
    if box:
        cx = box['x'] + box['width'] / 2.0
        cy = box['y'] + box['height'] / 2.0
        await click_at(page, cx, cy)
    else:
        # Fallback to direct locator click if not visible in geometry
        await loc.click()


async def drag_and_drop(
    page: Any,
    from_x: float,
    from_y: float,
    to_x: float,
    to_y: float,
    steps: int = 16,
    duration: float = 0.4
) -> None:
    """Drag an object (e.g. Knewton Alta graph point) from (from_x, from_y) to (to_x, to_y)

    Glides Nova's visible cursor to the origin, grips the point with visual feedback,
    moves along intermediate points using CDP mouse events, and releases at the target.
    Zero interference with the Windows desktop mouse cursor.
    """
    await ensure_cursor(page)
    # 1. Glide to starting position
    await glide_to(page, from_x, from_y, delay=0.25)
    
    # 2. Press down (grab element)
    try:
        await page.evaluate(CURSOR_DRAG_START_JS, {"x": round(from_x), "y": round(from_y)})
    except Exception:
        pass
    await page.mouse.move(from_x, from_y)
    await page.mouse.down()
    await asyncio.sleep(0.08)

    # 3. Interpolate movement steps smoothly
    step_delay = duration / max(steps, 1)
    for i in range(1, steps + 1):
        ratio = i / float(steps)
        # Ease in-out cubic
        t = 3 * ratio * ratio - 2 * ratio * ratio * ratio
        cur_x = from_x + (to_x - from_x) * t
        cur_y = from_y + (to_y - from_y) * t
        
        try:
            await page.evaluate(CURSOR_MOVE_JS, {"x": round(cur_x), "y": round(cur_y)})
        except Exception:
            pass
        await page.mouse.move(cur_x, cur_y)
        await asyncio.sleep(step_delay)

    # 4. Release mouse at final coordinate
    await page.mouse.up()
    try:
        await page.evaluate(CURSOR_DRAG_END_JS, {"x": round(to_x), "y": round(to_y)})
    except Exception:
        pass
    await asyncio.sleep(0.2)
