import { textToSpeech } from "../api.js";

const phrases = ["Let me take a look.", "Give me a second."];
const cache = new Map();
let next = 0;
export function acknowledgmentPhrase() {
  return phrases[next++ % phrases.length];
}
export function speechAudio(text, signal) {
  if (!phrases.includes(text)) return textToSpeech(text, null, signal);
  if (!cache.has(text)) {
    cache.set(text, textToSpeech(text, null).catch(error => { cache.delete(text); throw error; }));
  }
  return cache.get(text);
}
export function warmAcknowledgment() {
  speechAudio(phrases[next % phrases.length]).catch(() => {});
}
