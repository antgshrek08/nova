---
name: python-debugging
description: Structured approach for diagnosing and fixing Python errors, tracebacks, and test failures
keywords: [python, traceback, stack trace, exception, pytest, debug, debugging, valueerror, typeerror, keyerror, attributeerror, importerror, stacktrace]
---

When helping debug a Python problem:

1. Read the traceback bottom-up first -- the last frame is where the error was raised, not necessarily where the real bug is. Identify the actual failing line before speculating about causes.
2. State the root cause in one sentence before proposing a fix. If the traceback doesn't unambiguously show the cause, say what's still uncertain rather than guessing.
3. Prefer the smallest fix that addresses the root cause over a broad rewrite, unless the user's asked for a refactor.
4. If the error is a type mismatch (TypeError, AttributeError on None, etc.), check whether it's a symptom of a bug further upstream (a function returning None on some path) rather than just patching the symptom at the crash site.
5. For flaky or intermittent failures, ask about concurrency, shared mutable state, or test ordering before assuming randomness.
6. When suggesting a fix, show the minimal diff, not the whole file, unless the file is short.
