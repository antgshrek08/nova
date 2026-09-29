// Transform the entire accumulated response so fences split across tokens
// never leak code into progressive speech. Open fences hide the remainder.
export function spokenText(text, complete = true) {
  let value = String(text || "");
  if (!complete) value = value.replace(/[`~]{1,2}$/, "");
  value = value.replace(/(`{3,}|~{3,})[^\n]*\n?[\s\S]*?(?:\1|$)/g,
    " Look at the transcript for the code. ");
  value = value.replace(/`[^`]*(?:`|$)/g, " the code in the transcript ");
  return value;
}
