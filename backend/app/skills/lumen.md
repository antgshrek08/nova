---
name: lumen
description: Working Lumen Learning homework (Lumen OHM, Waymaker, Lumen One) and MyOpenMath -- experimental routine.
keywords: [lumen, lumen learning, ohm, lumen ohm, waymaker, lumen one, myopenmath, imathas, lumen homework]
---

Lumen and MyOpenMath are **experimental** in Nova: recognized and handled, not yet run end to end on a live assignment.

## Which Lumen

- **Lumen OHM** and **MyOpenMath** run on IMathAS. After each try the page reports a score like "Score on last try: 1 out of 1" -- Nova reads that number as the result, so a full score is correct, zero is incorrect, and anything between is partial.
- **Waymaker** and **Lumen One** mix readings with "check your understanding" questions and quizzes.

## The routine

1. **Inspect** the Lumen frame (`platforms` in the inspect result).
2. **Work the answer out first.**
3. **Enter it.** Math boxes take calculator notation; multiple choice by ref. Check what the box shows.
4. **Submit** is a submission: use `coursework_external_submit` with your reasoning. Many questions allow several tries and some offer a similar question after a miss; don't spend tries guessing.
5. **Read the score** that appears after the try and report it honestly -- partial credit is partial.
6. Continue question by question. Readings are for you to use as sources, not something to click through.

## Stop and tell the user

- A proctored or timed quiz, a sign-in prompt, or a question type you can't enter reliably.

## When done

Report the score shown for each assignment and anything unfinished with the reason.
