"""Autonomous Chained Auto-Pilot Solver Engine for N.O.V.A.

Runs bounded browser steps for supported question controls, with tutor and
submission modes. Portal names identify frames, not universal compatibility.
Authentication may require the user. Answers and assignment completion require
observed feedback; unsupported or uncertain work is reported explicitly.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import re
import time
from typing import Any, Awaitable, Callable
from urllib.parse import urlsplit

import sympy as sp

from . import operator_store, operator_workflows, browser_control, browser_cursor, coursework, coursework_browser, coursework_external, coursework_learner, db, homework_portals

logger = logging.getLogger(__name__)
_ASSIGNMENT_LOCK = asyncio.Lock()

def _detect_portal_type(url: str, text: str = "") -> str:
    """The homework platform (see homework_portals.py), or a Canvas page type."""
    portal = homework_portals.detect(url, text)
    if portal is None and "smartbook" in (text or "").lower():
        portal = homework_portals.get("mheducation")
    if portal is not None and portal.id != "canvas":
        return portal.id
    if "/quizzes/" in url.lower():
        return "canvas_quiz"
    return "canvas_generic"


def _clean_math_text(raw_text: str) -> str:
    """Normalize mathematical symbols and strip excess whitespace."""
    if not raw_text:
        return ""
    text = raw_text.replace("\u2212", "-").replace("\u00d7", "*").replace("\u00f7", "/")
    text = text.replace("\u03c0", "pi").replace("\u221e", "oo")
    return " ".join(text.split())


def solve_math_problem(question_text: str, math_items: list[str]) -> dict[str, Any]:
    """Deterministic math solver using SymPy for calculus, algebra, and arithmetic."""
    q = _clean_math_text(question_text).lower()
    combined_math = " ; ".join(math_items)
    
    # 1. Derivative calculation
    # e.g. "find the derivative of f(x) = 3*x^2 + 5*x"
    deriv_match = re.search(r'(?:derivative|d/dx|find\s+f\'\(x\))\s*(?:of)?\s*[:=]?\s*([0-9a-z\s\^\+\-\*\/\(\)\.=]+)', q)
    if deriv_match:
        expr_str = deriv_match.group(1).strip()
        if '=' in expr_str:
            expr_str = expr_str.split('=', 1)[1].strip()
        expr_str = expr_str.replace('^', '**')
        try:
            x = sp.Symbol('x')
            expr = sp.sympify(expr_str)
            deriv = sp.diff(expr, x)
            return {
                "success": True,
                "answer": str(deriv).replace('**', '^'),
                "reasoning": f"d/dx({expr}) = {deriv} via power/product rule.",
                "engine": "sympy"
            }
        except Exception:
            pass

    # 2. Limit calculation
    # e.g. "limit of (x^2 - 4)/(x - 2) as x approaches 2"
    limit_match = re.search(r'limit\s*(?:of)?\s*[:=]?\s*([0-9a-z\s\^\+\-\*\/\(\)\.=]+?)\s+(?:as\s+)?x\s*(?:->|approaches|to)\s*([0-9\-\.]+)', q)
    if limit_match:
        expr_str = limit_match.group(1).strip()
        if '=' in expr_str:
            expr_str = expr_str.split('=', 1)[1].strip()
        expr_str = expr_str.replace('^', '**')
        pt_str = limit_match.group(2)
        try:
            x = sp.Symbol('x')
            expr = sp.sympify(expr_str)
            pt = sp.sympify(pt_str)
            res = sp.limit(expr, x, pt)
            return {
                "success": True,
                "answer": str(res),
                "reasoning": f"lim x->{pt} of {expr} = {res}.",
                "engine": "sympy"
            }
        except Exception:
            pass

    # 3. Definite / Indefinite Integral
    # e.g. "integrate 3*x^2 dx"
    int_match = re.search(r'(?:integrate|integral\s+of)\s*[:=]?\s*([0-9a-z\s\^\+\-\*\/\(\)\.=]+?)(?:\s*dx)?(?:\s*$|\s+from)', q)
    if int_match:
        expr_str = int_match.group(1).strip()
        if '=' in expr_str:
            expr_str = expr_str.split('=', 1)[1].strip()
        expr_str = expr_str.replace('^', '**')
        try:
            x = sp.Symbol('x')
            expr = sp.sympify(expr_str)
            anti = sp.integrate(expr, x)
            return {
                "success": True,
                "answer": str(anti).replace('**', '^'),
                "reasoning": f"int({expr} dx) = {anti} + C.",
                "engine": "sympy"
            }
        except Exception:
            pass

    # 4. Linear or Polynomial Equation
    # e.g. "solve 2x + 10 = 24" or "find x when 4x - 8 = 0"
    eq_match = re.search(r'(?:solve|find\s+x\s+where|find\s+x\s+when)\s*[:=]?\s*([0-9a-z\s\^\+\-\*\/\(\)\.]+)\s*=\s*([0-9a-z\s\^\+\-\*\/\(\)\.]+)', q)
    if eq_match:
        left_str = eq_match.group(1).replace('^', '**')
        right_str = eq_match.group(2).replace('^', '**')
        try:
            x = sp.Symbol('x')
            eq = sp.Eq(sp.sympify(left_str), sp.sympify(right_str))
            solutions = sp.solve(eq, x)
            if solutions:
                ans = str(solutions[0])
                return {
                    "success": True,
                    "answer": ans,
                    "reasoning": f"Solving {eq} yields x = {solutions}.",
                    "engine": "sympy"
                }
        except Exception:
            pass

    # 5. Economics formulas: Elasticity, Equilibrium, Marginal Cost / Revenue
    # e.g. "if Qd = 100 - 2P and Qs = 20 + 2P, find equilibrium price"
    econ_eq = re.search(r'qd\s*=\s*([0-9p\s\+\-\*\/\.]+?)\s*(?:and|,)\s*qs\s*=\s*([0-9p\s\+\-\*\/\.]+?)(?:[\,\;\.]|\s+calculate|\s+find|$)', q)
    if econ_eq:
        try:
            p = sp.Symbol('p')
            qd_str = re.sub(r'(\d+)\s*([a-zA-Z])', r'\1*\2', econ_eq.group(1).strip())
            qs_str = re.sub(r'(\d+)\s*([a-zA-Z])', r'\1*\2', econ_eq.group(2).strip())
            qd = sp.sympify(qd_str)
            qs = sp.sympify(qs_str)
            sol = sp.solve(sp.Eq(qd, qs), p)
            if sol:
                eq_p = sol[0]
                eq_q = qd.subs(p, eq_p)
                return {
                    "success": True,
                    "answer": str(eq_p),
                    "reasoning": f"Equilibrium Price P = {eq_p}, Quantity Q = {eq_q} (where Qd = Qs).",
                    "engine": "sympy_economics"
                }
        except Exception:
            pass

    # 6. Direct numerical evaluation
    eval_match = re.search(r'(?:evaluate|calculate|what is|compute)\s*[:=]?\s*([0-9\s\+\-\*\/\(\)\.\^\%]+)\??', q)
    if eval_match:
        calc_str = eval_match.group(1).replace('^', '**')
        try:
            res = sp.sympify(calc_str)
            return {
                "success": True,
                "answer": str(res),
                "reasoning": f"{calc_str} = {res}",
                "engine": "sympy"
            }
        except Exception:
            pass

    return {
        "success": False,
        "answer": "",
        "reasoning": "Standard mathematical rule could not extract exact closed-form expression.",
        "engine": "none"
    }


async def solve_conceptual_question(question_text: str, options: list[str], context: str = "") -> dict[str, Any]:
    """Solves conceptual questions using local/Everyday model routing (never Claude Opus 5.5)."""
    from . import providers, routing
    prompt = (
        f"You are an expert academic tutor. Analyze the following college homework question carefully:\n\n"
        f"Question:\n{question_text}\n\n"
    )
    if options:
        prompt += f"Options:\n" + "\n".join(f"- {opt}" for opt in options) + "\n\n"
    if context:
        prompt += f"Context/Math/Formula:\n{context}\n\n"
    prompt += (
        "Instructions:\n"
        "1. Identify the single best, precise answer.\n"
        "2. If multiple choice, output the exact text of the matching option.\n"
        "3. If numerical or algebraic, output the final simplified value.\n"
        "Format your reply as JSON:\n"
        '{"answer": "<precise answer string>", "reasoning": "<concise step-by-step justification>"}'
    )

    messages = [
        {"role": "system", "content": "You are a precise academic solver. Return only valid JSON."},
        {"role": "user", "content": prompt}
    ]

    try:
        async with asyncio.timeout(90):
            settings = await db.get_app_settings()
            route = await routing.resolve(routing.HOMEWORK_CATEGORY, prefer_local=bool(settings.get("prefer_local", False)))
            reply = (await providers.run_model_call(route, messages)).strip()
        match = re.search(r'\{.*\}', reply, re.DOTALL)
        if match:
            data = json.loads(match.group(0))
            return {
                "success": bool(str(data.get("answer") or "").strip()),
                "answer": str(data.get("answer") or "").strip(),
                "reasoning": str(data.get("reasoning", "")).strip(),
                "engine": "configured_homework_model"
            }
    except Exception as exc:
        logger.warning("Conceptual model solver error: %s", exc)

    # Model failed — do NOT pretend we have a real answer
    return {
        "success": False,
        "answer": "",
        "reasoning": "All model attempts failed to produce a verified answer.",
        "engine": "none"
    }


async def get_course_assignments(course_filter: str = "") -> list[dict]:
    """Retrieve unsubmitted assignments for a given course or subject."""
    # 1. Check local database
    db_assignments = await db.list_canvas_assignments(include_submitted=False)
    filtered = []
    cf_low = (course_filter or "").lower().strip()

    for a in db_assignments:
        c_name = (a.get("course_name") or a.get("course") or "").lower()
        title = (a.get("title") or "").lower()
        if not cf_low or cf_low in c_name or cf_low in title or ("calc" in cf_low and "math" in c_name) or ("econ" in cf_low and "eco" in c_name):
            filtered.append({
                "id": str(a.get("canvas_id") or a.get("id")),
                "title": a.get("title"),
                "course_name": a.get("course_name") or a.get("course"),
                "due_at": a.get("due_at"),
                "url": a.get("url"),
                "submission_types": a.get("submission_types") or ["external_tool"]
            })

    if filtered:
        return filtered

    # 2. Try browser discovery if available
    try:
        browser_res = await coursework_browser.assignments(include_submitted=False)
        for a in browser_res.get("assignments", []):
            c_name = (a.get("course_name") or "").lower()
            title = (a.get("title") or "").lower()
            if not cf_low or cf_low in c_name or cf_low in title:
                filtered.append(a)
    except Exception as exc:
        raise RuntimeError(f"Assignment discovery failed: {exc}") from exc

    return filtered


async def _handle_interactive_graph(target_frame: Any, page_tab: Any, q_text: str, math_tags: list[str]) -> bool:
    """Detects and solves interactive Cartesian graph and slider questions (Knewton Alta, ALEKS, Lumen).
    Physically drags coordinate points with Nova's virtual cursor.
    """
    try:
        points = target_frame.locator('.graph-point, circle.graph-point, [data-qa="graph-point"], .alta-point, .line-handle, circle.draggable-point')
        point_count = await points.count()
        if point_count < 2:
            return False

        svg_container = target_frame.locator('svg, .graph-container, [data-qa="graph"]').first
        box = await svg_container.bounding_box()
        if not box or box["width"] < 50:
            return False

        geometry = coursework_learner.derive_mathematical_geometry(q_text, math_tags)
        if geometry["curve_type"] != "line":
            return False
        axes = await coursework_learner.read_graph_axes(svg_container)
        if not axes:
            return False
        p1_math, p2_math = geometry["points"]

        t1_x, t1_y = coursework_learner.data_to_pixel(box, *p1_math, **axes)
        t2_x, t2_y = coursework_learner.data_to_pixel(box, *p2_math, **axes)

        active_page = page_tab or (target_frame.page if hasattr(target_frame, 'page') else target_frame)
        p1_box = await points.nth(0).bounding_box()
        p2_box = await points.nth(1).bounding_box()
        if not p1_box or not p2_box:
            return False
        if p1_box:
            await browser_cursor.drag_and_drop(
                active_page,
                p1_box["x"] + p1_box["width"] / 2.0,
                p1_box["y"] + p1_box["height"] / 2.0,
                t1_x, t1_y
            )

        p2_box = await points.nth(1).bounding_box()
        if p2_box:
            await browser_cursor.drag_and_drop(
                active_page,
                p2_box["x"] + p2_box["width"] / 2.0,
                p2_box["y"] + p2_box["height"] / 2.0,
                t2_x, t2_y
            )
        return True
    except Exception as exc:
        logger.warning("Interactive graph drag handler notice: %s", exc)
        return False


def classify_feedback(before: str, after: str, portal: str | None = None) -> str:
    """correct | incorrect | partial | unknown. A stale banner from before the
    answer was checked is not evidence (homework_portals.feedback)."""
    return homework_portals.feedback(before, after, portal)


def assignment_complete(text: str, portal: str | None = None) -> bool:
    return homework_portals.complete(text, portal)


async def run_autopilot_assignment(assignment_info: dict, browser_channel: str | None = None, mode: str = "autopilot",
                                   submission_guard: Callable[[], Awaitable[None]] | None = None) -> dict:
    async with _ASSIGNMENT_LOCK:
        return await _run_autopilot_assignment(assignment_info, browser_channel, mode, submission_guard)


async def _run_autopilot_assignment(
    assignment_info: dict,
    browser_channel: str | None = None,
    mode: str = "autopilot",
    submission_guard: Callable[[], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    """Execute autonomous solving on a single assignment until complete.

    submission_guard, when given, is awaited immediately before every submit
    click and raises to refuse it (e.g. a queue whose authorization lapsed).
    """
    url = assignment_info.get("url")
    title = assignment_info.get("title", "Assignment")
    course_name = assignment_info.get("course_name", "Course")
    logger.info("Auto-pilot opening assignment: %s (%s)", title, url)

    if mode not in {"autopilot", "tutor"}:
        return {"status": "failed", "error": "Unknown learning mode"}
    session_id = None
    questions_solved = 0
    start_time = time.time()
    log_entries = []
    final_status = "attempted"
    submission_pending = False
    seen_questions = set()

    try:
        operator_workflows.require_running()
        tab = await browser_control.page(channel=browser_channel)
        # Navigate to Canvas assignment page
        try:
            await tab.goto(url, wait_until="domcontentloaded", timeout=12000)
            await asyncio.sleep(1.0)
        except Exception as exc:
            logger.warning("Could not reach %s: %s", url, exc)
            return {
                "title": title,
                "course": course_name,
                "url": url,
                "questions_solved": 0,
                "duration_seconds": round(time.time() - start_time, 1),
                "steps": [{"step": "navigation", "status": f"Canvas destination unreachable: {exc}"}],
                "status": "unreachable"
            }

        # Check for Canvas or Portal login wall
        curr_url = tab.url.lower()
        title_low = (await tab.title()).lower()
        if "/login" in curr_url or "sign in" in curr_url or "sso" in curr_url or "log in" in title_low or "sign in" in title_low:
            logger.info("Canvas / portal login required at %s", tab.url)
            return {
                "title": title,
                "course": course_name,
                "url": url,
                "questions_solved": 0,
                "duration_seconds": round(time.time() - start_time, 1),
                "steps": [{"step": "authentication", "status": "Canvas sign-in screen detected. Finish signing into Canvas once to enable autonomous solving."}],
                "status": "auth_required"
            }

        # Detect and handle LTI external launch button or iframe
        # Detect and handle LTI external launch button or iframe
        # Many Canvas courses render: "Load [Assignment] in a new window"
        try:
            launch_btn = tab.locator('a.load_external_tool_button, button:has-text("Load in a new window"), button:has-text("Open in new window"), a:has-text("Load")').first
            if await launch_btn.count() > 0 and await launch_btn.is_visible():
                logger.info("Found external tool launch button, clicking via Nova cursor...")
                before_pages = list(tab.context.pages)
                await browser_cursor.click_element(tab, launch_btn)
                await asyncio.sleep(1.5)
                new_pages = [p for p in tab.context.pages if p not in before_pages and not p.is_closed()]
                if new_pages:
                    tab = new_pages[-1]
                    await tab.bring_to_front()
        except Exception:
            pass

        # Determine target frame (main tab or embedded iframe)
        target_frame = tab
        for frame in tab.frames:
            f_url = frame.url.lower()
            if any(h in f_url for h in ("knerd.com", "knewton.com", "aleks.com", "mheducation.com", "lumenlearning.com", "webassign.net")):
                target_frame = frame
                break

        portal_type = _detect_portal_type(target_frame.url, await target_frame.locator('body').inner_text() if await target_frame.locator('body').count() > 0 else "")
        logger.info("Target portal detected: %s on %s", portal_type, target_frame.url)

        # Problem-solving iteration loop (cap at 30 questions per assignment)
        max_questions = 30
        for q_idx in range(1, max_questions + 1):
            operator_workflows.require_running()
            await asyncio.sleep(1.5)
            body_text = await target_frame.locator('body').inner_text()
            
            # Proctored, locked-down or live work is never Nova's to do.
            stops = homework_portals.blockers(body_text)
            if stops:
                final_status = "blocked"
                log_entries.append({"step": "stopped", "status": f"This page is {', '.join(stops)}. Nova does not work around that."})
                break

            # Check for completion indicators
            if assignment_complete(body_text, portal_type):
                final_status = "completed"
                log_entries.append({"step": "verification", "status": "Assignment completion receipt observed"})
                break

            # Extract question text and math formulas
            q_elem = target_frame.locator('.question-view, .problem-statement, .prompt, [data-qa="question-text"], .exercise-container, form').first
            q_text = await q_elem.inner_text() if await q_elem.count() > 0 else body_text[:1200]
            
            # Extract LaTeX or MathML
            math_tags = await target_frame.locator('math, [data-latex], annotation[encoding="application/x-tex"], script[type^="math/tex"]').evaluate_all(
                "els => els.map(e => e.getAttribute('data-latex') || e.textContent || '').filter(Boolean)"
            )

            # Check if this is an interactive Cartesian graph or slider question (Knewton Alta, ALEKS, Lumen)
            fingerprint = q_text + str(math_tags)
            if fingerprint in seen_questions:
                final_status = "blocked"
                log_entries.append({"status": "Question unchanged; refusing duplicate submission"})
                break
            seen_questions.add(fingerprint)
            location = urlsplit(target_frame.url)
            attempt_key = hashlib.sha256((location.netloc + location.path + fingerprint).encode()).hexdigest()
            prior = operator_store.get("autopilot_submission", attempt_key)
            if mode != "tutor" and prior and prior.get("status") in {"pending", "unknown"}:
                final_status = "unknown"
                log_entries.append({"status": "Previous submission is uncertain. Reconcile the portal result before retrying."})
                break
            novel_res = {}
            answered = mode != "tutor" and await _handle_interactive_graph(target_frame, tab, q_text, math_tags)

            # Novel Question Discovery & Self-Healing:
            # If standard handlers didn't resolve and interactive drawing/graphing surfaces are present
            if not answered and mode != "tutor":
                novel_res = await coursework_learner.solve_novel_question(
                    target_frame=target_frame,
                    page_tab=tab,
                    q_text=q_text,
                    math_tags=math_tags,
                    portal_type=portal_type
                )
                if novel_res.get("handled") and novel_res.get("success"):
                    answered = True
                    ans = novel_res.get("description", "Novel interaction procedure")
                    reasoning = f"Executed candidate interaction via {novel_res.get('mode')} ({novel_res.get('signature')})"
                    logger.info("Autonomous solver handled novel question: %s", reasoning)

            # Extract multiple choice options if present
            options_loc = target_frame.locator('label:has(input[type=radio]), label:has(input[type=checkbox]), [role="radio"], [role="checkbox"], .answer-option, .choice')
            opt_count = await options_loc.count()
            options = []
            if opt_count > 0:
                for i in range(min(opt_count, 8)):
                    opt_t = (await options_loc.nth(i).inner_text()).strip()
                    if opt_t and opt_t not in options:
                        options.append(opt_t)

            inputs_count = await target_frame.locator('input, textarea, .mathquill-editable').count()
            if not answered and opt_count == 0 and inputs_count == 0:
                log_entries.append({"step": f"Question {q_idx}", "status": "No active question controls rendered on portal"})
                break

            # Solve question
            math_sol = solve_math_problem(q_text, math_tags) if not answered else {"success": True, "answer": novel_res.get("description", "Graph drawn"), "reasoning": "Candidate graph procedure executed"}
            if math_sol["success"]:
                solution = math_sol
            else:
                solution = await solve_conceptual_question(q_text, options, context=" ; ".join(math_tags[:5]))

            ans = solution.get("answer", "")
            reasoning = solution.get("reasoning", "")
            logger.info("Solved Q%d [%s]: Ans='%s'", q_idx, solution.get("engine"), ans)

            # Guard: if no solver produced a verified answer and the interactive
            # handler didn't already resolve the question, skip it.
            if not answered and not solution.get("success"):
                log_entries.append({
                    "step": f"Question {q_idx}",
                    "answer": "",
                    "reasoning": reasoning,
                    "status": "skipped_unsolvable"
                })
                final_status = "blocked"
                break

            if mode == "tutor":
                log_entries.append({"question": q_text[:180], "mode": "tutor", "answer": ans,
                                    "reasoning": reasoning, "status": "Prepared worked step"})
                final_status = "guidance_ready"
                break

            # Apply Answer to the Portal with Nova's visible virtual cursor
            # 1. Multiple choice click
            if not answered and options:
                for i in range(min(opt_count, 8)):
                    opt_handle = options_loc.nth(i)
                    opt_t = (await opt_handle.inner_text()).strip()
                    if ans.strip() and ans.casefold() == opt_t.casefold():
                        await browser_cursor.click_element(tab, opt_handle)
                        answered = True
                        break

            # 2. Text / numeric / MathQuill input
            if not answered and not options:
                inputs = target_frame.locator('input:not([type]), input[type="text"], input[type="number"], textarea, .mathquill-editable, [contenteditable="true"]')
                if await inputs.count() == 1:
                    inp = inputs.first
                    await browser_cursor.click_element(tab, inp)
                    await inp.fill(ans)
                    answered = True

            if not answered:
                final_status = "blocked"
                log_entries.append({"status": "No unambiguous answer control"})
                break

            # 4. Submit / Check Answer button with Nova's virtual cursor
            submit_btn = target_frame.locator('button:has-text("Submit"), button:has-text("Check"), button:has-text("Submit Answer"), button:has-text("Check My Work"), input[type="submit"]').first
            if await submit_btn.count() > 0 and await submit_btn.is_visible():
                operator_workflows.require_running()
                if submission_guard is not None:
                    await submission_guard()
                submission_pending = True
                operator_store.put("autopilot_submission", attempt_key, {"status": "pending"})
                await browser_cursor.click_element(tab, submit_btn)
                await asyncio.sleep(1.5)

            else:
                final_status = "blocked"
                log_entries.append({"status": "No submission control"})
                break

            post_body = await target_frame.locator('body').inner_text()
            feedback_status = classify_feedback(body_text, post_body, portal_type)
            operator_store.put("autopilot_submission", attempt_key, {"status": feedback_status})
            submission_pending = False
            if novel_res.get("recipe") and feedback_status in {"correct", "incorrect"}:
                await coursework_learner.record_verified_outcome(novel_res, feedback_status == "correct")
            if feedback_status == "correct":
                questions_solved += 1
            if assignment_complete(post_body, portal_type):
                final_status = "completed"
            elif feedback_status != "correct":
                final_status = "blocked" if feedback_status in {"incorrect", "partial"} else "unknown"
            log_entries.append({
                "step": f"Question {q_idx}",
                "answer": ans,
                "reasoning": reasoning,
                "status": feedback_status
            })

            if final_status in {"completed", "blocked", "unknown"}:
                break

            # Advance to Next Question with Nova's virtual cursor
            next_btn = target_frame.locator('button:has-text("Next"), button:has-text("Continue"), button:has-text("Next Question"), a:has-text("Next")').first
            if await next_btn.count() > 0 and await next_btn.is_visible():
                await browser_cursor.click_element(tab, next_btn)
                await asyncio.sleep(1.0)
            else:
                # If no next button, check if assignment finished
                break

    except Exception as exc:
        logger.error("Error during auto-pilot on assignment '%s': %s", title, exc, exc_info=True)
        final_status = "unknown" if submission_pending else ("cancelled" if operator_workflows.stopped() else "failed")
        log_entries.append({"step": "error", "message": str(exc)})

    duration = round(time.time() - start_time, 1)
    return {
        "title": title,
        "course": course_name,
        "url": url,
        "questions_solved": questions_solved,
        "duration_seconds": duration,
        "steps": log_entries,
        "status": final_status
    }


async def run_autopilot_queue(
    subject: str = "calculus",
    browser: str | None = None,
    max_assignments: int = 10,
    mode: str = "autopilot"
) -> dict[str, Any]:
    """Chained auto-pilot solver that loops through all open assignments for a course."""
    # None means the browser chosen in Settings, which is also the one Canvas
    # reads use -- a different one here would relaunch the browser between them.
    browser = browser_control.normalize_browser(browser)
    if browser == "onyx":
        browser = None
    if mode not in {"autopilot", "tutor"} or not 1 <= max_assignments <= 50:
        return {"ok": False, "error": "Choose a supported mode and 1-50 assignments"}
    try:
        assignments = await get_course_assignments(subject)
    except Exception as exc:
        return {"ok": False, "status": "discovery_failed", "error": str(exc)}
    if not assignments:
        return {
            "ok": True,
            "subject": subject,
            "found": 0,
            "message": f"No pending unsubmitted assignments found for subject/course: '{subject}'."
        }

    results = []
    total_questions = 0
    total_time = 0.0

    target_queue = assignments[:max_assignments]
    logger.info("Auto-pilot launching queue: %d assignments for '%s'", len(target_queue), subject)

    for idx, item in enumerate(target_queue, 1):
        if operator_workflows.stopped():
            break
        logger.info("Auto-pilot chaining assignment [%d/%d]: %s", idx, len(target_queue), item.get("title"))
        run_res = await run_autopilot_assignment(item, browser_channel=browser, mode=mode)
        results.append(run_res)
        total_questions += run_res.get("questions_solved", 0)
        total_time += run_res.get("duration_seconds", 0)

        if run_res.get("status") in {"auth_required", "unknown", "guidance_ready", "cancelled"}:
            break

        # Self-healing brief interval between assignments
        await asyncio.sleep(2)

    completed = sum(result.get("status") == "completed" for result in results)
    return {
        "ok": completed == len(target_queue),
        "total_assignments_completed": completed,
        "subject": subject,
        "browser": browser or browser_control._current_channel,
        "mode": mode,
        "total_assignments_processed": len(results),
        "total_questions_solved": total_questions,
        "total_duration_seconds": round(total_time, 1),
        "assignments": results,
        "summary": f"Processed {len(results)} assignments; verified {completed} completed assignments ({total_questions} questions) in {round(total_time, 1)}s via {browser_control.BROWSERS[browser or browser_control._current_channel or 'chrome']['name']} ({mode.capitalize()} mode)."
    }
