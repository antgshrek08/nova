---
name: aleks
description: Working ALEKS learning-mode topics (McGraw Hill) launched from Canvas or aleks.com -- experimental routine.
keywords: [aleks, aleks homework, aleks topics, knowledge check, aleks pie, learning mode, aleks math, aleks chemistry]
---

ALEKS is **experimental** in Nova: recognized and handled, not yet run end to end on a live assignment. Read what the page shows at every step; never assume a result.

## Two kinds of ALEKS work

- **Learning mode (topics):** practice problems per topic. This is the homework Nova can work through.
- **Knowledge Checks and quizzes:** assessments. If inspect returns a `stop` notice (proctored, lockdown browser), stop and tell the user. If it is an unproctored Knowledge Check, ask the user before answering it -- it resets their learning path.

## The routine (learning mode)

1. **Inspect** the ALEKS frame (`platforms` in the inspect result). Read the problem, not the surrounding page.
2. **Work the answer out first.**
3. **Enter it** with the answer tools ALEKS shows: math boxes take calculator notation (`x^(2)`, `(a)/(b)`, `sqrt(x)`); check what the box shows before submitting. Multiple choice: click the option by its ref.
4. **Check** is a submission: use `coursework_external_submit` with your reasoning.
5. **Read the result.** Only new text counts. If incorrect, read the explanation ALEKS offers before trying again. Several correct answers in a row are usually needed to finish a topic.
6. Continue to the next problem or topic until the assignment's goal is met, then report the progress ALEKS shows.

## Stop and tell the user

- A proctored or locked-down Knowledge Check, a sign-in or two-factor prompt.
- A graphing answer you can't place precisely.
- Anything asking the user to confirm their identity or rules of the assessment.

## When done

Report topics completed and the progress ALEKS shows, plus anything left and why.
