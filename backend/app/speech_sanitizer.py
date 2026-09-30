"""Speech Sanitizer for N.O.V.A.
Transforms LLM responses into natural, conversational spoken text.
Strips out raw code, stack traces, debug logs, markdown noise,
and translates LaTeX math formulas into clear spoken English.
"""
from __future__ import annotations

import re


def clean_for_speech(text: str) -> str:
    """Prepares model output for text-to-speech reading.
    Ensures Nova never reads raw code, stack traces, JSON, or ugly markup aloud.
    """
    if not text:
        return ""

    cleaned = text

    # 1. Detect and remove stack traces / tracebacks
    cleaned = re.sub(
        r"Traceback \(most recent call last\):.*?(?=(\n\n|\Z))",
        " An error occurred. ",
        cleaned,
        flags=re.DOTALL | re.IGNORECASE,
    )
    cleaned = re.sub(r'File ".*?", line \d+.*', "", cleaned)

    # 2. Handle fenced code blocks:
    # If the response contains code blocks, replace them with a natural spoken indicator
    has_code_block = bool(re.search(r"```[\w]*\n[\s\S]*?```", cleaned))
    if has_code_block:
        cleaned = re.sub(r"```[\w]*\n[\s\S]*?```", " [code omitted] ", cleaned)

    # 3. Strip inline code snippets longer than 20 chars, or short variable names keep plain
    def _replace_inline_code(match: re.Match) -> str:
        snippet = match.group(1).strip()
        if len(snippet) > 25 or any(ch in snippet for ch in "{};()=>[]"):
            return " "
        return f" {snippet} "

    cleaned = re.sub(r"`([^`]+)`", _replace_inline_code, cleaned)

    # 4. Remove Markdown tables
    cleaned = re.sub(r"\|[^\n]+\|\n\|[-:\s|]+\|\n(?:\|[^\n]+\|\n?)*", " [table omitted] ", cleaned)
    cleaned = re.sub(r"^\|.*\|$", "", cleaned, flags=re.MULTILINE)

    # 5. Translate common LaTeX math formulas into natural speech
    cleaned = _latex_to_spoken(cleaned)

    # 6. Convert markdown links [title](url) -> title
    cleaned = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", cleaned)

    # 7. Remove raw URLs
    cleaned = re.sub(r"https?://\S+", " the link ", cleaned)

    # 8. Remove markdown headers, bold, italics, strikethrough, blockquotes
    cleaned = re.sub(r"^#{1,6}\s+", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\*\*([^*]+)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"\*([^*]+)\*", r"\1", cleaned)
    cleaned = re.sub(r"__([^_]+)__", r"\1", cleaned)
    cleaned = re.sub(r"_([^_]+)_", r"\1", cleaned)
    cleaned = re.sub(r"~~([^~]+)~~", r"\1", cleaned)
    cleaned = re.sub(r"^>\s+", "", cleaned, flags=re.MULTILINE)

    # 9. Clean up bullet points into smooth flow
    cleaned = re.sub(r"^\s*[-*+]\s+", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*\d+\.\s+", "", cleaned, flags=re.MULTILINE)

    # 10. Strip raw HTML tags
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)

    # 11. Normalize phrase replacements
    cleaned = cleaned.replace("[code omitted]", "I've written the code for you in the editor.")
    cleaned = cleaned.replace("[table omitted]", "I've organized the details into a table for you.")

    # 12. Strip leftover special characters and collapse extra whitespace
    cleaned = re.sub(r"[\r\n]+", " ", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = cleaned.strip()

    # If the response was purely code or empty after cleaning
    if not cleaned or cleaned == "I've written the code for you in the editor.":
        if has_code_block:
            return "I've generated the code and placed it in your workspace."
        return ""

    return cleaned


# ---------------------------------------------------------------- math aloud
#
# Math is where speech trips: "sec²x", "d/dx" and "f′g − fg′" read as a blur
# of letters. Each formula becomes the words a teacher would say, with a
# short pause on either side, and a reply full of math is spoken a little
# slower (speech_pace).

TRIG = {
    "arcsin": "inverse sine", "arccos": "inverse cosine", "arctan": "inverse tangent",
    "sinh": "hyperbolic sine", "cosh": "hyperbolic cosine", "tanh": "hyperbolic tangent",
    "sin": "sine", "cos": "cosine", "tan": "tangent", "sec": "secant", "csc": "cosecant", "cot": "cotangent",
}
SUPERSCRIPTS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻ⁿˣʸ⁽⁾", "0123456789+-nxy()")
SUPER_RUN = re.compile(r"([⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻ⁿˣʸ⁽⁾]+)")
MATH_SPAN = re.compile(r"\$\$(.+?)\$\$|\$([^$\n]+?)\$|\\\((.+?)\\\)|\\\[(.+?)\\\]", re.DOTALL)
GREEK = ["alpha", "beta", "gamma", "delta", "epsilon", "theta", "lambda", "mu", "pi", "sigma", "phi", "omega"]
SYMBOLS = [
    ("±", " plus or minus "), ("∓", " minus or plus "), ("·", " times "), ("×", " times "), ("÷", " divided by "),
    ("−", " minus "), ("≠", " is not equal to "), ("≤", " is at most "), ("≥", " is at least "), ("≈", " is about "),
    ("∞", " infinity "), ("π", " pi "), ("θ", " theta "), ("→", " approaches "), ("√", " the square root of "),
    ("∫", " the integral of "), ("Δ", " change in "), ("′′", " double prime "), ("″", " double prime "), ("′", " prime "),
]


def _power(exp: str) -> str:
    exp = exp.strip().strip("()")
    if exp == "2":
        return " squared"
    if exp == "3":
        return " cubed"
    if exp in ("-1", "−1"):
        return " to the negative one"
    exp = re.sub(r"\s*-\s*", " minus ", exp)
    exp = re.sub(r"\s*\+\s*", " plus ", exp).strip()
    return f" to the {exp}"


def _speak_math(text: str) -> str:
    t = text
    # LaTeX structure first.
    t = re.sub(r"\\left|\\right|\\,|\\;|\\!|\\quad|\\displaystyle", " ", t)
    t = re.sub(r"\\frac\{d\}\{d([a-zA-Z])\}", r" the derivative with respect to \1 of ", t)
    t = re.sub(r"\\frac\{d\^2\}\{d([a-zA-Z])\^2\}", r" the second derivative with respect to \1 of ", t)
    for _ in range(3):  # nested fractions, innermost first
        t = re.sub(r"\\[dt]?frac\{([^{}]+)\}\{([^{}]+)\}", r" \1, over \2, ", t)
    t = re.sub(r"\\sqrt\[(\d+)\]\{([^{}]+)\}", r" the \1th root of \2 ", t)
    t = re.sub(r"\\sqrt\{([^{}]+)\}", r" the square root of \1 ", t)
    t = re.sub(r"\\lim_\{([^{}]+)\}", r" the limit as \1 of ", t)
    t = re.sub(r"\\int_\{?([^{}\s^]+)\}?\^\{?([^{}\s]+)\}?", r" the integral from \1 to \2 of ", t)
    t = re.sub(r"\\sum_\{([^{}]+)\}\^\{?([^{}\s]+)\}?", r" the sum from \1 to \2 of ", t)
    t = re.sub(r"\\(ln|log)\b", lambda m: " the natural log of " if m.group(1) == "ln" else " log of ", t)
    t = re.sub(r"\\(" + "|".join(TRIG) + r")\b", lambda m: m.group(1), t)
    for name in GREEK:
        t = re.sub(r"\\" + name + r"\b", f" {name} ", t)
    for tex, word in [(r"\pm", "±"), (r"\cdot", "·"), (r"\times", "×"), (r"\div", "÷"), (r"\neq", "≠"),
                      (r"\leq", "≤"), (r"\le", "≤"), (r"\geq", "≥"), (r"\ge", "≥"), (r"\approx", "≈"),
                      (r"\infty", "∞"), (r"\to", "→"), (r"\rightarrow", "→"), (r"\prime", "′")]:
        t = t.replace(tex, word)
    # Plain-text calculus: d/dx, dy/dx.
    t = re.sub(r"\bd\s*/\s*d([a-zA-Z])\b", r" the derivative with respect to \1 of ", t)
    t = re.sub(r"\bd([a-zA-Z])\s*/\s*d([a-zA-Z])\b", r" d \1 d \2 ", t)
    # Unicode superscripts: x² -> x^2, xⁿ⁻¹ -> x^(n-1).
    t = SUPER_RUN.sub(lambda m: "^(" + m.group(1).translate(SUPERSCRIPTS) + ")", t)
    # Trig with a power: sec^2 x -> secant squared of x.
    t = re.sub(r"\b(" + "|".join(TRIG) + r")\s*\^\s*\{?\(?([^\s{}()]+?)\)?\}?(?=[\s(a-zA-Zθ])",
               lambda m: f" {TRIG[m.group(1)]}{_power(m.group(2))} of ", t)
    # Trig applied to something: sin x, cos(2x) -- but not "30 sec" (seconds).
    t = re.sub(r"\b(" + "|".join(TRIG) + r")\b(?=\s*(\(|[a-zA-Zθ]\b|\d*[a-zA-Zθ]\b))", lambda m: f" {TRIG[m.group(1)]} of ", t)
    # Powers.
    t = re.sub(r"\^\{([^{}]+)\}", lambda m: _power(m.group(1)), t)
    t = re.sub(r"\^\(([^()]+)\)", lambda m: _power(m.group(1)), t)
    t = re.sub(r"\^(-?\w+)", lambda m: _power(m.group(1)), t)
    # Primes: f'(x) / f′(x) -> f prime of x.
    t = re.sub(r"([a-zA-Z])('{2}|″|′′)\s*\(([^()]+)\)", r"\1 double prime of \3", t)
    t = re.sub(r"([a-zA-Z])('|′)\s*\(([^()]+)\)", r"\1 prime of \3", t)
    t = re.sub(r"([a-zA-Z])'", r"\1 prime ", t)
    for sym, word in SYMBOLS:
        t = t.replace(sym, word)
    t = re.sub(r"prime\s+\(", "prime of (", t)
    # Operators said as words, so the pace holds.
    t = re.sub(r"(?<=\s)=(?=\s)|(?<=[\w)])\s*=\s*(?=[\w(])", " equals ", t)
    t = re.sub(r"(?<=[\w)])\s*\+\s*(?=[\w(])", " plus ", t)
    t = re.sub(r"(?<=[\w)])\s+-\s+(?=[\w(])", " minus ", t)
    t = re.sub(r"(?<=[\w)])\s*/\s*(?=[\w(])", " over ", t)
    t = re.sub(r"\\[a-zA-Z]+", " ", t)
    t = t.replace("{", " ").replace("}", " ")
    t = re.sub(r"\bof(\s+of)+\b", "of", t)  # "d/dx of x" -> "... of x", not "of of"
    return re.sub(r"\s{2,}", " ", t)


def _latex_to_spoken(text: str) -> str:
    """Math into spoken words: LaTeX spans ($...$, $$...$$, \\(...\\),
    \\[...\\]) first, each with a pause either side, then math written in
    plain text or Unicode (sec²x, d/dx, f′(x))."""
    text = MATH_SPAN.sub(lambda m: ", " + _speak_math(next(g for g in m.groups() if g is not None)).strip() + ", ", text)
    return _speak_math(text)


def speech_pace(text: str) -> float:
    """How much slower than normal to speak a reply (1.0 = normal): math
    goes a little slower so each term is clear."""
    if not text:
        return 1.0
    marks = len(re.findall(r"\$|\\frac|\\sqrt|\^|[²³ⁿ′±√∫]|\b(sin|cos|tan|sec|csc|cot|ln|d/d[a-z])\b", text))
    if marks < 3:
        return 1.0
    density = marks / max(1, len(text.split()))
    return 0.85 if density > 0.12 else 0.92 if density > 0.04 else 1.0
