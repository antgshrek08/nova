---
name: knewton-alta
description: Working Knewton Alta assignments (Canvas calculus homework) in Onyx with browser_act -- the tested routine from start to mastery.
keywords: [knewton, alta, mastery, "100% mastery", calculus homework, math homework, open canvas, do my homework, do the homework, do all, knewton alta, "3.3b", "3.3c", "3.4", "3.5", "3.6", "3.7", "3.8", "3.9", "3.9c"]
---

This is a tested routine for Knewton Alta homework in Canvas. It worked live on 3.3c: START, the question read correctly, the answer typed into the math box and checked, SUBMIT, and the answer graded correct.

## Where to work

- Use `browser_act`. It drives Onyx, where the Knewton frame is visible. Don't use Brainfuse, other Canvas tools, or deliberately pick a different browser yourself.
- If the user has taken over Onyx's mouse or keyboard, Onyx pauses itself and `browser_act` switches to Nova's own separate Edge window automatically -- the result says `"browser": "edge"` when this happened. Don't try to work around the pause in Onyx itself; that's not a bug to route past, it's Onyx correctly getting out of his way. Just keep going in Edge: navigate to the assignment's Canvas URL again (it's a fresh tab, so re-inspect from scratch) and continue the routine below the same way.
- The Canvas sidebar is not the homework. Never click "Brainfuse Online Tutoring", "Home", "Modules", "Grades", "Discussions" or any other Canvas menu link.
- Open each assignment by its Canvas URL with `browser_act` navigate, for example `https://<school>.instructure.com/courses/<course>/assignments/<id>`. If you don't have the URLs, get them from the Canvas assignment tools, or open the course's Assignments page and use the links there.

If you have Onyx's own tools instead of browser_act (they're named `mcp__onyx__...`), use them the same way:
- "inspect" is `page_read` with the tabId.
- "click N" is `click` with `ref: N`.
- "fill N" is `type` with `ref: N`, the text, and `clear: true`.
Find the assignment's tab with `tabs_list`; it's the one whose URL ends in the assignment's id.

## The routine, one assignment at a time

1. **Inspect.** Knewton's controls are the ones marked as being inside `www.knewton.com`. They usually come first; when the frame sits lower on the page they come after the Canvas links. Knewton's text is the part under "[... embedded from www.knewton.com ...]"; read that and ignore the Canvas text around it.
2. **Start.** Click **START**, **KEEP GOING** or **CONTINUE** (whichever is there) by its number. A control that is off screen is scrolled into view automatically, so you don't need to scroll first.
3. **Dismiss the intro.** If a "GOT IT" dialog appears (the "Adaptive is personalized" intro), click the **GOT IT** button by its number.
4. **Inspect again and read the question.** It's the text between "Question" and "Provide your answer below". Pay attention to signs, primes (′) and the point to evaluate at. Work the answer out step by step before touching the page.
5. **Find the answer box.** It's listed as a math box named "Response input area", marked `(math box)`. Use `fill` with its number as the selector.
6. **Type the answer the way you'd type it on a calculator.** No spaces, no "=", no Enter.
   - Numbers: `17`, `-3`, `2.5`.
   - Powers: `^` with the exponent in parentheses: `x^(2)`, `-12x^(-5/2)`.
   - Fractions: `/` with each part in parentheses when there's more than one term: `(2x+1)/(x-4)`.
   - Square roots: `sqrt(x)`.
   Onyx turns this into a real math expression and puts it in whole, with exponents and fractions closed properly. Don't type it key by key, and don't switch to another typing tool: typing `^` key by key leaves the cursor inside the exponent, so `x^(2)+50` became x to the power 2+50.
7. **Check before submitting.** The result of `fill` or `type` includes `mathShows`, which is what the box now displays. For example, `x^(2)+50` shows as `x2+50`, and `(a)/(b)` shows the top and bottom on separate lines. If that doesn't match your answer, `fill` it again with `clear`.
8. **Submit.** Click **SUBMIT** by its number. Don't click by the word "Submit": Canvas has the words "Submitting an external tool" nearby.
9. **Read the result.** Inspect. The page says "correct" or shows the right answer, and the **MASTERY** percentage at the top changes. If it was wrong, read the "Answer Explanation" and use it on the next question.
10. **Next question.** Click **NEXT QUESTION** (or **CONTINUE**) by its number and go back to step 4. Keep going until MASTERY reads 100% or Knewton says the assignment is complete, then move on to the next assignment.

Not every question is a math box -- some are graphs, some ask you to drag something into place, some are plain multiple choice or fill-in-the-blank. The sections below cover the other kinds this course and McGraw Hill's SmartBook/Connect use.

## Other question kinds

### Graph questions ("graph the tangent line", "plot the point")

Inspect lists the graph itself as `(graph, axis x:.. y:.. box x:.. y:.. w:.. h:.. -- ...)` -- that line already works out where data point (0,0) lands in pixels, and gives the formula for any other point. There's usually a default line or point already on the graph (visible in a screenshot if you need to check) that has to be moved, not a blank graph to click on once.

1. Work out the data-space point(s) you need -- for a tangent line, two points on it (the touch point and one more), or a point and the slope.
2. Turn each into a pixel point using the graph's own line from inspect: pixel x is `box.x + (dx-xMin)/(xMax-xMin)*box.width`, pixel y is `box.y + (yMax-dy)/(yMax-yMin)*box.height` (y is flipped -- pixels increase downward).
3. Use `drag` with `selector` and `to` as `"x=<px>,y=<py>"` to move the line's point from where it is now to where it needs to be. If the line has two draggable ends, drag each one in turn.
4. Inspect again (a screenshot helps here) and check the line looks right before submitting.

Onyx works this out from the axis range it can read off the page; it doesn't know Knewton's own coordinate system, so double-check the result looks right rather than trusting one drag blindly.

This covers a straight tangent line. A question that asks for a *curve* to be sketched freehand (not a straight line between two points) isn't something `drag` can do -- it presses once, moves once, releases once. Stop and tell the user rather than guessing at a shape.

### Matching, sequencing and labeling (SmartBook, Connect)

These ask you to drag a term, tile or label onto a target -- a definition, a slot in an ordered list, a spot on a diagram. Inspect both the item and where it goes, then `drag` from one to the other by ref, selector or text -- the same `drag` used for graphs. It tries a real native drag-and-drop first and only falls back to a physical mouse drag if that doesn't apply, so the same call works for both; there's nothing different to do for this kind of question versus a graph one, just target the item and its destination instead of two graph points.

### Multiple choice, checkboxes, and multi-blank questions

- Multiple choice and "select all that apply": `click` the option by its ref. Checkboxes are protected the normal way -- if a click is refused because it would flip something on or off, that's it warning you the ref is a checkbox rather than the choice itself; inspect again and look for the actual clickable label or option role next to it.
- A question with more than one blank or more than one math box: `fill`/`type` targets one box at a time by its ref, and clicking a ref first is what gives it keyboard focus -- so target each box by its own ref in turn rather than typing once and hoping it lands in the right one.
- Fill-in-the-blank with a plain text box (not a math box): `fill` it with the words, not calculator notation -- inspect tells you which kind it is (`(math box -- ...)` only appears for MathQuill fields).

### Highlighting or selecting a range of text (SmartBook)

Some questions ask you to select or highlight a phrase. `drag` from the start of the phrase to the end of it (by pixel point, or by targeting the start/end words) selects it the same way a mouse-drag text-select always has, no different from a graph drag.

## Predicted problems -- stop and tell the user rather than guess

- **A freehand curve-sketch question** (see the graph section above) -- `drag` places a straight line between two points, not an arbitrary shape.
- **A stale ref after the page changes underneath you** ("ref N is stale") -- inspect again and use the new number; this is normal after a question loads new content, not a sign of anything broken.
- **A drag that doesn't look right after the fact** -- always inspect (or screenshot) and check before submitting, for graphs and for matching/labeling both. A wrong drag costs a question; guessing costs the same as not trying.

## Going fast

- Inspect once after each action. Don't take screenshots unless the listing doesn't make sense.
- Stay in one tab. Don't open new tabs for the same assignment.
- If a number stops working ("ref N is stale"), inspect again and use the new number.

## When done

Tell the user, for each assignment, the mastery reached and how many questions were answered, and point out any assignment you couldn't finish and why.
