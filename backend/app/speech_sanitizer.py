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


def _latex_to_spoken(text: str) -> str:
    """Translates LaTeX math notation into natural spoken language."""
    # Common mathematical operators and symbols
    replacements = [
        (r"\pm", " plus or minus "),
        (r"\times", " times "),
        (r"\cdot", " times "),
        (r"\div", " divided by "),
        (r"\neq", " is not equal to "),
        (r"\leq", " is less than or equal to "),
        (r"\geq", " is greater than or equal to "),
        (r"\approx", " is approximately "),
        (r"\infty", " infinity "),
        (r"\pi", " pi "),
        (r"\theta", " theta "),
        (r"\alpha", " alpha "),
        (r"\beta", " beta "),
        (r"\Delta", " delta "),
        (r"\delta", " delta "),
        (r"\rightarrow", " approaches "),
        (r"\to", " approaches "),
    ]
    for pattern, repl in replacements:
        text = text.replace(pattern, repl)

    # Fractions: \frac{a}{b} -> a over b
    text = re.sub(r"\\frac\{([^}]+)\}\{([^}]+)\}", r"\1 over \2", text)

    # Square roots: \sqrt{x} -> square root of x
    text = re.sub(r"\\sqrt\{([^}]+)\}", r"square root of \1", text)
    text = re.sub(r"\\sqrt\[(\d+)\]\{([^}]+)\}", r"\1th root of \2", text)

    # Limits: \lim_{x \to a} -> limit as x approaches a
    text = re.sub(r"\\lim_\{([^}]+)\}", r"limit as \1", text)

    # Integrals: \int_{a}^{b} -> integral from a to b
    text = re.sub(r"\\int_\{([^}]+)\}\^\{([^}]+)\}", r"integral from \1 to \2 of", text)
    text = re.sub(r"\\int", "integral of", text)

    # Derivatives: f'(x) -> f prime of x, f''(x) -> f double prime of x
    text = re.sub(r"(\w)''\((\w+)\)", r"\1 double prime of \2", text)
    text = re.sub(r"(\w)'\((\w+)\)", r"\1 prime of \2", text)
    text = re.sub(r"d([a-zA-Z])/d([a-zA-Z])", r"d \1 d \2", text)

    # Exponents: x^2 -> x squared, x^3 -> x cubed, x^{n} -> x to the n
    text = re.sub(r"(\w)\^2(?!\d)", r"\1 squared", text)
    text = re.sub(r"(\w)\^3(?!\d)", r"\1 cubed", text)
    text = re.sub(r"(\w)\^\{([^}]+)\}", r"\1 to the \2", text)
    text = re.sub(r"(\w)\^(\w+)", r"\1 to the \2", text)

    # Functions: \ln(x) -> natural log of x, \sin(x) -> sine of x
    text = re.sub(r"\\ln\b", "natural log of", text)
    text = re.sub(r"\\log\b", "log of", text)
    text = re.sub(r"\\sin\b", "sine of", text)
    text = re.sub(r"\\cos\b", "cosine of", text)
    text = re.sub(r"\\tan\b", "tangent of", text)

    # Clean up leftover backslashes and dollar signs from math mode
    text = re.sub(r"\$+", "", text)
    text = re.sub(r"\\[a-zA-Z]+", "", text)
    text = text.replace("{", "(").replace("}", ")")

    return text
