---
name: webassign
description: Working Cengage WebAssign homework launched from Canvas or webassign.net -- experimental routine.
keywords: [webassign, cengage webassign, web assign, webassign homework]
---

WebAssign is **experimental** in Nova: recognized and handled, not yet run end to end on a live assignment.

## How WebAssign counts

- Submissions are counted per question part, and some assignments limit them. "Your response differs from the correct answer" means that part was wrong.
- An assignment can be submitted question by question or all at once. Submit one question part at a time so each result is checked before the next.

## The routine

1. **Inspect** the WebAssign frame (`platforms` in the inspect result).
2. **Work every part out first**, keeping the units and significant figures the question asks for.
3. **Enter answers** part by part: numeric and math boxes, dropdowns and choices by ref. Check what each box shows.
4. **Submit** is a submission: use `coursework_external_submit` with your reasoning.
5. **Read the marks** that appear after submitting. Rework any part marked wrong before using another submission.
6. Continue until every question is answered, then report the score shown.

## Stop and tell the user

- A proctored test, a lockdown browser, a sign-in prompt, or a question with no submissions left.

## When done

Report the score for each assignment and anything unfinished with the reason.
