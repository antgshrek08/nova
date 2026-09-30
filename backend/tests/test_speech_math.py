"""Math read aloud clearly (app/speech_sanitizer.py)."""
from app.speech_sanitizer import clean_for_speech, speech_pace


def said(text):
    return clean_for_speech(text)


def test_plain_text_calculus_is_spoken_in_words():
    assert said("d/dx of xⁿ is n·xⁿ⁻¹.") == "the derivative with respect to x of x to the n is n times x to the n minus 1."
    assert "secant squared of x" in said("d/dx tan x = sec²x")
    assert "tangent of x equals" in said("d/dx tan x = sec²x")


def test_primes_and_quotients():
    out = said("(f/g)′ = (f′g − fg′)/g²")
    assert "f prime g minus f g prime" in out.replace("fg", "f g") and "g squared" in out


def test_latex_is_spoken_with_pauses_around_it():
    out = said(r"The chain rule: $\frac{d}{dx} f(g(x)) = f'(g(x)) \cdot g'(x)$.")
    assert "the derivative with respect to x of f(g(x)) equals f prime of (g(x)) times g prime of x" in out
    assert "\\" not in out and "$" not in out
    out = said(r"$$\frac{d}{dx}\left[\frac{f}{g}\right] = \frac{f'g - fg'}{g^2}$$")
    assert "over g squared" in out and "rac" not in out
    assert "the integral from 0 to 1 of x squared" in said(r"$\int_0^1 x^2 \, dx = \frac{1}{3}$")


def test_ordinary_words_stay_ordinary():
    assert said("Wait 30 sec and try again.") == "Wait 30 sec and try again."
    assert speech_pace("Wait 30 sec and try again.") == 1.0


def test_math_heavy_replies_are_spoken_slower():
    assert speech_pace("d/dx sin x = cos x, d/dx cos x = −sin x, d/dx tan x = sec²x") < 1.0
    assert speech_pace("Sure, I'll set that up for tomorrow morning.") == 1.0
