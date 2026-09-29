# Settings setup verification — 2026-09-13

Installed Ryan medium from the official Piper voice repository, including its
configuration and model card. The default CPU voice uses this model; the prior
Lessac files remain available. A 15-word sample generated in 2.77 seconds.
The Electron miniplayer speech test observed speaking, AA/EE/rest mouth shapes,
one playback call, and return to idle.

Sources:
- https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_US/ryan/medium
- https://github.com/modelcontextprotocol/servers

Git, Fetch, and Time reference MCP servers (2026.8.18) are installed in
backend/.venv-mcp. Their dependency on MCP 1.x is isolated from Nova's MCP 2.x
client. Memory uses the reference npm server with an explicit persistent file.
Existing Filesystem, Sequential Thinking, Context7, both Google Workspace
connections, and LLM Router were retained. The obsolete Test Tools entry pointing
at a missing temporary script was disabled.

Live calls passed: Git status, Fetch example.com, Time America/New_York, and
Memory read_graph. Ten enabled servers reported connected and exposed 96 tools.
Discovery is not proof that every tool or account permission has been tested.

OpenRouter credentials are now editable under Models. Keys is absent from the
navigation. The default model list shows enabled assistants/local models;
Show full catalog exposes disabled models and the dynamic OpenRouter roster.
Canonical model IDs and routing assignments remain unchanged.

Fourteen skills load. Sample frontend, homework, planning, and testing requests
selected their corresponding skills. Selection remains capped at two skills.

Validation: 60 backend tests passed; Vite production build passed. npm 11.13.0
works in the normal environment, so no Node/npm reinstall was needed. Electron
inspection confirmed OpenRouter controls, no Keys button, no horizontal page
overflow, and working miniplayer speech. This is a local desktop build; no
installer or distribution was requested or created.
