"""Feedback-verified procedural learning for supported homework graph widgets.

Candidate procedures require explicit equations, calibrated axes, and supported tools.
Only portal correctness feedback promotes a candidate into persistent learning.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from typing import Any

import sympy as sp

from . import browser_cursor, db

logger = logging.getLogger(__name__)


def compute_widget_signature(portal: str, tool_names: list[str], widget_type: str) -> str:
    """Generate a deterministic signature for an interactive widget or toolset."""
    key = f"{portal}:{widget_type}:{':'.join(sorted(tool_names))}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
    return f"{portal}:{widget_type}:{digest}"


async def inspect_interactive_surface(target_frame: Any) -> dict[str, Any]:
    """Inspects the page for novel interactive drawing, graphing, or manipulation tools."""
    surface_info = {
        "has_canvas": False,
        "has_svg": False,
        "has_toolbar": False,
        "tools": [],
        "box": None,
        "widget_type": "unknown",
        "container_selector": None,
    }

    try:
        # 1. Search for interactive graphing canvas or SVG
        canvases = target_frame.locator('canvas, svg.graph-container, svg.alta-graph, svg[data-graph], .graph-canvas, .coordinate-plane')
        if await canvases.count() > 0:
            box = await canvases.first.bounding_box()
            if box and box["width"] >= 60 and box["height"] >= 60:
                surface_info["has_canvas"] = True
                surface_info["box"] = box
                surface_info["container_selector"] = "canvas, svg.graph-container, svg.alta-graph, svg[data-graph], .graph-canvas, .coordinate-plane"

        # 2. Search for drawing / graphing toolbars
        # Buttons with labels like: Line, Parabola, Circle, Point, Ray, Segment, Shade, Eraser
        toolbar_buttons = target_frame.locator(
            'button:has-text("Line"), button:has-text("Parabola"), button:has-text("Circle"), '
            'button:has-text("Point"), button:has-text("Ray"), button:has-text("Segment"), '
            'button:has-text("Shade"), button:has-text("Plot"), button[data-tool], [role="toolbar"] button'
        )
        t_count = await toolbar_buttons.count()
        tools = []
        if t_count > 0:
            surface_info["has_toolbar"] = True
            for i in range(min(t_count, 12)):
                btn = toolbar_buttons.nth(i)
                txt = (await btn.inner_text()).strip() or (await btn.get_attribute("title") or "") or (await btn.get_attribute("aria-label") or "")
                if txt and txt not in tools:
                    tools.append(txt)
            surface_info["tools"] = tools

        # 3. Classify widget type
        if tools and surface_info["has_canvas"]:
            surface_info["widget_type"] = "graph_drawing_toolbar"
        elif surface_info["has_canvas"]:
            surface_info["widget_type"] = "canvas_coordinate_plane"
        elif await target_frame.locator('.draggable, [draggable="true"]').count() > 0:
            surface_info["widget_type"] = "drag_and_drop_matching"

    except Exception as exc:
        logger.warning("Error inspecting interactive surface: %s", exc)

    return surface_info


def derive_mathematical_geometry(q_text: str, math_tags: list[str]) -> dict[str, Any]:
    """Derive only explicit, supported equations; ambiguity is not a default curve."""
    text = (q_text + " " + " ".join(math_tags)).lower()
    unknown = {"curve_type": "unknown", "points": [], "description": "No supported explicit equation"}
    circle = re.search(r"\(x\s*([+-]\s*\d+(?:\.\d+)?)?\)\s*(?:\^2|\*\*2)\s*\+\s*\(y\s*([+-]\s*\d+(?:\.\d+)?)?\)\s*(?:\^2|\*\*2)\s*=\s*(\d+(?:\.\d+)?)", text)
    if circle:
        h, k = [-float((part or "0").replace(" ", "")) for part in circle.groups()[:2]]
        radius = float(circle[3]) ** .5
        return {"curve_type": "circle", "tool_needed": "Circle", "points": [(h, k), (h + radius, k)],
                "description": f"Circle centered at ({h:g}, {k:g}), radius {radius:g}"}
    match = re.search(r"\by\s*=\s*([0-9x\s+*/^().-]+)", text)
    if not match:
        return unknown
    expression = match[1].strip().rstrip(".").replace("^", "**")
    expression = re.sub(r"(\d|\))\s*(?=x|\()", r"\1*", expression)
    try:
        # The allowlisted expression has no names except x and no callable identifiers.
        x = sp.Symbol('x')
        polynomial = sp.Poly(sp.sympify(expression, locals={'x': x}), x)
        degree = polynomial.degree()
        if degree not in (0, 1, 2):
            return unknown
        a, b, c = (float(polynomial.nth(i)) for i in (2, 1, 0))
        if not all(__import__('math').isfinite(v) for v in (a, b, c)):
            return unknown
        if degree == 2:
            vx = -b / (2 * a)
            vy = a * vx * vx + b * vx + c
            return {"curve_type": "parabola", "tool_needed": "Parabola",
                    "points": [(vx, vy), (vx + 1, vy + a)], "description": f"Parabola y = {expression}"}
        return {"curve_type": "line", "tool_needed": "Line", "points": [(0., c), (1., b + c)],
                "description": f"Line y = {expression}"}
    except (ValueError, TypeError, SyntaxError, sp.PolynomialError):
        return unknown


def data_to_pixel(box: dict, x: float, y: float, x_range: tuple[float, float] = (-10, 10), y_range: tuple[float, float] = (-10, 10)) -> tuple[float, float]:
    """Converts mathematical coordinate (x, y) to screen pixels inside the bounding box."""
    cx = box["x"] + box["width"] / 2.0
    cy = box["y"] + box["height"] / 2.0
    span_x = x_range[1] - x_range[0]
    span_y = y_range[1] - y_range[0]
    scale_x = box["width"] / span_x
    scale_y = box["height"] / span_y
    if span_x <= 0 or span_y <= 0 or not (x_range[0] <= x <= x_range[1] and y_range[0] <= y <= y_range[1]):
        raise ValueError("Point or axes outside the calibrated graph")
    px = box["x"] + (x - x_range[0]) * scale_x
    py = box["y"] + (y_range[1] - y) * scale_y
    return px, py


async def solve_novel_question(
    target_frame: Any,
    page_tab: Any,
    q_text: str,
    math_tags: list[str],
    portal_type: str = "generic"
) -> dict[str, Any]:
    """Autonomous self-healing solver for novel question modalities.

    1. Checks if a procedure was already learned and saved.
    2. If not, inspects the tools, discovers the sequence, executes with virtual cursor.
    3. Persists the recipe to SQLite for permanent zero-friction future recall.
    """
    surface = await inspect_interactive_surface(target_frame)
    if not surface["has_canvas"] and not surface["has_toolbar"]:
        return {"handled": False, "reason": "No novel interactive drawing/graphing surface detected."}

    geom = derive_mathematical_geometry(q_text, math_tags)
    if geom["curve_type"] in {"unknown", "inequality"}:
        return {"handled": False, "reason": "No supported verified graph procedure"}
    container = target_frame.locator(surface["container_selector"]).first
    axes = await read_graph_axes(container)
    if not axes:
        return {"handled": False, "reason": "Graph axis calibration is unavailable"}
    sig = compute_widget_signature(portal_type, surface["tools"], surface["widget_type"] + ":v2:" + geom["curve_type"])
    learned = await db.get_learned_procedure(sig)
    if learned and learned["recipe"].get("verified"):
        recipe = dict(learned["recipe"], axes=axes)
        success = await execute_recipe(target_frame, page_tab, recipe, surface["box"], q_text, math_tags)
        return {"handled": success, "success": success, "signature": sig, "recipe": recipe,
                "description": geom["description"], "mode": "recalled_recipe"}

    # Formulate interaction recipe
    recipe_steps = []
    tool_needed = geom["tool_needed"]

    # Step 1: Select Tool from toolbar
    matching_tool = None
    for t in surface["tools"]:
        if tool_needed.lower() in t.lower():
            matching_tool = t
            break
    if not matching_tool:
        return {"handled": False, "reason": "Required drawing tool is unavailable"}

    if matching_tool:
        recipe_steps.append({
            "step": "select_tool",
            "tool": matching_tool,
            "selector": f'button:has-text("{matching_tool}"), [aria-label*="{matching_tool}"]'
        })

    # Step 2: Plot mathematical anchor points
    for idx, pt in enumerate(geom["points"]):
        recipe_steps.append({
            "step": "click_point",
            "index": idx,
            "math_x": pt[0],
            "math_y": pt[1]
        })

    # Step 3: Shading if required
    if geom.get("shade_tool"):
        recipe_steps.append({
            "step": "select_tool",
            "tool": geom["shade_tool"],
            "selector": f'button:has-text("{geom["shade_tool"]}"), [aria-label*="{geom["shade_tool"]}"]'
        })
        sp_pt = geom.get("shade_point", (0.0, 0.0))
        recipe_steps.append({
            "step": "click_point",
            "index": "shade",
            "math_x": sp_pt[0],
            "math_y": sp_pt[1]
        })

    recipe = {
        "portal": portal_type,
        "signature": sig,
        "widget_type": surface["widget_type"],
        "curve_type": geom["curve_type"],
        "axes": axes,
        "steps": recipe_steps
    }

    # Execute the formulated recipe with Nova's visible virtual cursor
    success = await execute_recipe(target_frame, page_tab, recipe, surface["box"], q_text, math_tags)

    return {"handled": success, "success": success, "signature": sig,
            "mode": "candidate_procedure", "recipe": recipe, "description": geom["description"]}


async def record_verified_outcome(result: dict, correct: bool) -> None:
    recipe = dict(result["recipe"], verified=correct)
    await db.save_learned_procedure(
        portal_pattern=recipe["portal"], widget_signature=result["signature"],
        widget_type=recipe["widget_type"], instruction_summary=result["description"],
        recipe=recipe, success=correct)


async def read_graph_axes(container: Any) -> dict | None:
    """Use explicit widget bounds; never infer [-10, 10] from its appearance."""
    try:
        values = [float(await container.get_attribute(name)) for name in
                  ("data-x-min", "data-x-max", "data-y-min", "data-y-max")]
        if values[0] < values[1] and values[2] < values[3]:
            return {"x_range": values[:2], "y_range": values[2:]}
    except (TypeError, ValueError):
        pass
    return None


async def execute_recipe(
    target_frame: Any,
    page_tab: Any,
    recipe: dict,
    box: dict | None,
    q_text: str,
    math_tags: list[str]
) -> bool:
    """Executes a formulated or learned recipe step-by-step using Nova's virtual cursor."""
    active_tab = page_tab or (target_frame.page if hasattr(target_frame, 'page') else target_frame)
    if not box:
        canvases = target_frame.locator('canvas, svg.graph-container, svg.alta-graph, svg[data-graph], .graph-canvas, .coordinate-plane')
        if await canvases.count() > 0:
            box = await canvases.first.bounding_box()
    if not box:
        return False

    geom = derive_mathematical_geometry(q_text, math_tags)
    if not recipe.get("steps") or not recipe.get("axes") or geom["curve_type"] != recipe.get("curve_type"):
        return False
    # Validate every point before any interaction.
    try:
        for mx, my in geom["points"]:
            data_to_pixel(box, mx, my, **recipe["axes"])
    except (ValueError, ZeroDivisionError):
        return False

    try:
        for st in recipe.get("steps", []):
            st_type = st.get("step")
            if st_type == "select_tool":
                sel = st.get("selector")
                tool_btn = target_frame.locator(sel).first
                if await tool_btn.count() == 0:
                    return False
                if await tool_btn.count() > 0:
                    logger.info("Nova virtual cursor clicking tool: %s", st.get("tool"))
                    await browser_cursor.click_element(active_tab, tool_btn)
                    await asyncio.sleep(0.3)

            elif st_type == "click_point":
                idx = st.get("index")
                if isinstance(idx, int) and idx < len(geom["points"]):
                    mx, my = geom["points"][idx]
                elif idx == "shade" and geom.get("shade_point"):
                    mx, my = geom["shade_point"]
                else:
                    mx = float(st.get("math_x", 0))
                    my = float(st.get("math_y", 0))

                px, py = data_to_pixel(box, mx, my, **recipe["axes"])
                logger.info("Nova virtual cursor clicking graph point (%g, %g) -> pixel (%g, %g)", mx, my, px, py)
                await browser_cursor.click_at(active_tab, px, py)
                await asyncio.sleep(0.4)

        return True
    except Exception as exc:
        logger.error("Error executing interaction recipe: %s", exc)
        return False
