"""Nova's deliberately small Hermes tool profile; upstream stays unmodified."""
import toolsets

toolsets.TOOLSETS["hermes-acp"] = {
    "description": "Nova local coding assistant",
    "tools": ["read_file", "write_file", "patch", "search_files", "terminal",
              "process_manage", "todo_list", "memory", "skills_list", "skill_view"],
    "includes": [],
}

from acp_adapter.entry import main

if __name__ == "__main__":
    main()
