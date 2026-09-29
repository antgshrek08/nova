"""What a real /chat turn actually costs in tokens, measured rather than guessed.

Local models get the tool registry, matched skills, persona, agency and
environment prompts all at once. That fits in a 16k window or it doesn't, and
when it doesn't Ollama truncates silently -- no error, just a worse answer. This
prints the real numbers so the budget is a fact instead of an assumption.

Run:  .venv/Scripts/python.exe measure_context.py
"""
import asyncio
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from app import nova_tools, skills  # noqa: E402


def approx_tokens(text: str) -> int:
    """~3.6 chars/token is a reasonable średnia for English prose plus JSON
    punctuation; exact tokenisation varies per model and the decision here
    (does it fit in 16k) does not turn on a few percent."""
    return round(len(text) / 3.6)


async def main():
    from app.main import NOVA_AGENCY_INSTRUCTIONS, NOVA_PERSONA_INSTRUCTIONS

    tools_json = json.dumps(nova_tools.TOOL_SCHEMAS)
    tool_tokens = approx_tokens(tools_json)

    print("=" * 62)
    print("NOVA CONTEXT BUDGET")
    print("=" * 62)
    print(f"{'tool schemas (' + str(len(nova_tools.TOOL_SCHEMAS)) + ' tools)':<38} {tool_tokens:>7} tok")

    per_tool = sorted(
        ((approx_tokens(json.dumps(s)), s["function"]["name"]) for s in nova_tools.TOOL_SCHEMAS),
        reverse=True,
    )
    print(f"{'  heaviest: ' + ', '.join(n for _, n in per_tool[:4]):<38}")
    print(f"{'  median tool':<38} {per_tool[len(per_tool) // 2][0]:>7} tok")

    persona = approx_tokens(NOVA_PERSONA_INSTRUCTIONS)
    agency = approx_tokens(NOVA_AGENCY_INSTRUCTIONS)
    print(f"{'persona prompt':<38} {persona:>7} tok")
    print(f"{'agency prompt':<38} {agency:>7} tok")

    all_skills = skills.all_skills()
    skill_sizes = sorted(((approx_tokens(s.body), s.name) for s in all_skills), reverse=True)
    print(f"{'skills installed':<38} {len(all_skills):>7}")
    print(f"{'  largest skill (' + skill_sizes[0][1] + ')':<38} {skill_sizes[0][0]:>7} tok")
    print(f"{'  median skill':<38} {skill_sizes[len(skill_sizes) // 2][0]:>7} tok")

    from app import agent_loop, skills as skills_module
    mcp_budget = round(agent_loop.MCP_CONTEXT_BUDGET_CHARS / 3.6)
    skill_budget = round(skills_module.SKILL_CONTEXT_BUDGET_CHARS / 3.6)
    print(f"{'MCP tools (budget cap)':<38} {mcp_budget:>7} tok")

    print("\n" + "-" * 62)
    print("WORST CASE: every budget spent in full")
    print("-" * 62)
    environment = 220   # measured shape of _build_environment_context
    awareness = 160     # measured shape of _build_self_awareness_context
    fixed = tool_tokens + persona + agency + environment + awareness
    total = fixed + skill_budget + mcp_budget

    for label, value in [
        ("Nova's own tools", tool_tokens), ("persona", persona), ("agency", agency),
        ("environment", environment), ("self-awareness", awareness),
        ("skills (capped)", skill_budget), ("MCP tools (capped)", mcp_budget),
    ]:
        print(f"  {label:<34} {value:>7} tok")
    print(f"  {'-' * 34} {'-' * 7}")
    print(f"  {'SYSTEM PROMPT TOTAL':<34} {total:>7} tok")

    ctx = 32768
    print(f"\n  num_ctx                            {ctx:>7} tok")
    print(f"  left for history + reply           {ctx - total:>7} tok")
    headroom = (ctx - total) / ctx
    print(f"  headroom                           {headroom * 100:>6.0f}%")

    if headroom < 0.45:
        print("\n  >> TIGHT. A long conversation will push history out, and Ollama")
        print("     truncates silently. Raise num_ctx or attach fewer tools.")
    else:
        print("\n  >> Comfortable for a normal turn.")

    print("\n" + "-" * 62)
    print("NO-TOOL TURN (message needs no tools)")
    print("-" * 62)
    bare = persona + awareness
    print(f"  system prompt total                {bare:>7} tok")
    print(f"  saving vs. full                    {total - bare:>7} tok")


asyncio.run(main())
