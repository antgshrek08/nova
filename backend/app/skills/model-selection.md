---
name: model-selection
description: Pick a model for a job — local versus hosted, cost, context, tool support — and say why.
keywords: [which model, model choice, best model, gpt, claude, gemini, llama, qwen, ollama, local model, openrouter, cheaper model, context window, tokens, rate limit]
---

Match the model to the job rather than reaching for the largest available.

Four things decide it. **Does it need tools?** Many small and local models
accept tool schemas and then ignore them, or emit malformed calls; if the task
is agentic, that is the first filter, not an afterthought. **How much context
does it actually need?** A long context window does not make a model good at
using the far end of it. **Does the work leave the machine?** Anything touching
private files, credentials or personal data is an argument for a local model
regardless of quality. **What does a mistake cost?** Cheap and wrong is not
cheap when the answer gets acted on.

Prefer local for bulk, private, or repetitive work — summarising, classifying,
drafting, anything run many times. Prefer a strong hosted model for work where
being wrong is expensive: architecture, debugging something subtle, writing that
will be read by someone who matters.

Say which model was used and why, in one line. When output is disappointing,
name the model before rewriting the prompt — a prompt tuned to rescue an
underpowered model is a prompt that will mislead a better one later.

Watch the failure modes that look like success: a model that answers confidently
without the tool result it needed, one that truncates rather than admitting the
input was too long, and one that produces plausible code for an API it has never
seen. Each of these reads as a good answer.
