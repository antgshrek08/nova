// Thin wrapper around the browser's real Web Speech API (SpeechRecognition
// / webkitSpeechRecognition) for voice input. No backend involved -- the
// browser (or its OS) does the actual speech-to-text.

export function isSpeechRecognitionSupported() {
  return Boolean(window.SpeechRecognition || window.webkitSpeechRecognition);
}

/** Creates one real SpeechRecognition session. onResult fires on every
 * result event with {interim, final} text so the caller can show live
 * partial transcripts; onEnd fires when the browser stops listening
 * (silence detected, or explicit stop()); onError surfaces real API errors
 * (e.g. "not-allowed" if mic permission was denied, "network" if the
 * platform's recognition service isn't reachable). */
export function createRecognizer({ onResult, onEnd, onError, lang = "en-US" } = {}) {
  const Ctor = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Ctor) return null;

  const recognition = new Ctor();
  recognition.lang = lang;
  recognition.interimResults = true;
  recognition.continuous = false;

  recognition.onresult = (event) => {
    let final = "";
    let interim = "";
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const transcript = event.results[i][0].transcript;
      if (event.results[i].isFinal) final += transcript;
      else interim += transcript;
    }
    onResult?.({ interim, final });
  };
  recognition.onend = () => onEnd?.();
  recognition.onerror = (event) => onError?.(event.error);

  return recognition;
}
