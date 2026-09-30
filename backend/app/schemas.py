from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

TabName = Literal["chat", "code"]


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str


class ChatRequest(BaseModel):
    conversation_id: int
    message: str
    homework: bool = False
    attachment_ids: list[int] = []
    # One-off override for this message only, as a catalog model id (same
    # shape /models returns, e.g. "claude_cli:sonnet", "openrouter:<id>") --
    # takes precedence over both the category's automatic chain and any
    # persistent Settings override for this one request. None/omitted means
    # "route automatically", same as before this existed.
    override_model_id: str | None = None


class CategoryOverrideRequest(BaseModel):
    category: str
    model_id: str | None = None  # None clears the override for that category


class OpenClawSendRequest(BaseModel):
    conversation_id: int
    task: str


class SettingsUpdateRequest(BaseModel):
    gemini_api_key: str | None = None
    openrouter_api_key: str | None = None


class DesktopActionResponseRequest(BaseModel):
    approved: bool


class TTSRequest(BaseModel):
    text: str
    voice_id: str | None = None  # None -> use the Settings > Voice default


class AppSettingsUpdateRequest(BaseModel):
    """N.O.V.A. Settings > General/Voice toggles. All optional -- only the
    keys actually sent are persisted, everything else is left as-is."""

    auto_route: bool | None = None
    prefer_local: bool | None = None
    fast_simple_replies: bool | None = None
    enter_sends: bool | None = None
    launch_at_login: bool | None = None
    miniplayer_at_login: bool | None = None
    video_cookies_browser: str | None = None
    show_spend: bool | None = None
    voice_replies: bool | None = None
    show_reactor: bool | None = None
    duck_on_type: bool | None = None
    default_router: str | None = None
    spend_cap_usd: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    handoff_review_enabled: bool | None = None
    tts_voice_id: str | None = None  # "default" or a tts_voices row id, as a string
    desktop_interaction_enabled: bool | None = None
    desktop_trusted_mode: bool | None = None
    desktop_pet_enabled: bool | None = None
    # How long Nova's pointer takes to travel to what it is about to click.
    # 0 means don't animate at all -- the old teleporting click.
    desktop_click_seconds: float | None = Field(default=None, ge=0, le=2.5,
                                                allow_inf_nan=False)
    desktop_click_marker: bool | None = None
    desktop_pointer: Literal["own", "real"] | None = None
    desktop_borrow_mouse: Literal["ask", "never"] | None = None
    browser_backend: Literal["onyx", "edge"] | None = None
    onyx_path: str | None = Field(default=None, max_length=1024)
    speak_summary_only: bool | None = None
    push_to_talk_hotkey: str | None = None
    # How much Nova may do without asking (see nova_tools.AUTONOMY_LEVELS).
    autonomy_level: Literal["readonly", "guarded", "full"] | None = None
    agent_tools_enabled: bool | None = None
    homework_mode: Literal["tutor", "solve"] | None = None
    file_access_roots: str | None = None
    primary_model: str | None = None
    preferred_browser: str | None = None
    browser_visibility_mode: Literal["visible", "hidden", "silent", "headless"] | None = None
    appearance_mode: Literal["day", "night", "auto"] | None = None
    # Where links and sign-in pages open: the user's default browser, or a
    # tab in Nova's (visible) Onyx window, whose sign-ins Nova then shares.
    link_target: Literal["system", "nova"] | None = None
    # Notifications (app/notify.py): which events notify, on which devices,
    # and quiet hours as "HH:MM-HH:MM" ("" = none).
    notify_replies: bool | None = None
    notify_tasks: bool | None = None
    notify_homework: bool | None = None
    notify_reminders: bool | None = None
    notify_needs_you: bool | None = None
    notify_desktop: bool | None = None
    notify_phone: bool | None = None
    notify_phone_replies: bool | None = None
    quiet_hours: str | None = Field(default=None, pattern=r"^$|^\d{2}:\d{2}-\d{2}:\d{2}$")
    # Calendar (app/calendar_hub.py): where Nova writes events, their default
    # reminder, and how long a planned study session is.
    calendar_default_url: str | None = Field(default=None, max_length=2048)
    calendar_reminder_minutes: int | None = Field(default=None, ge=0, le=10080)
    study_block_minutes: int | None = Field(default=None, ge=15, le=480)
    study_block_hour: int | None = Field(default=None, ge=5, le=23)
    color_palette: Literal["grove", "fern", "moss", "dusk", "ember", "glacier", "custom"] | None = None
    custom_palette: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}(,#[0-9A-Fa-f]{6}){2}$")


class TerminalCreateRequest(BaseModel):
    cwd: str | None = None
    shell: str | None = None
    cols: int = 120
    rows: int = 30


class GitActionRequest(BaseModel):
    action: Literal["stage", "unstage", "discard", "commit", "create_branch", "switch_branch"]
    path: str | None = None            # repo root; defaults to the open project
    paths: list[str] = Field(default_factory=list, max_length=500)
    message: str | None = None
    name: str | None = None
    stage_all: bool = False


class SecretPutRequest(BaseModel):
    name: str = Field(max_length=49)
    value: str = Field(max_length=4096)


class CanvasCredentialsRequest(BaseModel):
    base_url: str | None = None
    access_token: str | None = None


class AppleCalendarCredentialsRequest(BaseModel):
    apple_id: str | None = Field(default=None, max_length=320)
    # An app-specific password from appleid.apple.com, not the Apple password.
    # Goes straight into the secrets vault; never read back out to a client.
    app_password: str | None = Field(default=None, max_length=256)


class AppleCalendarEventRequest(BaseModel):
    calendar_url: str = Field(max_length=2048)
    title: str = Field(min_length=1, max_length=500)
    start: str                      # ISO 8601
    end: str | None = None
    location: str = Field(default="", max_length=500)
    notes: str = Field(default="", max_length=4000)
    all_day: bool = False
    reminder_minutes: list[int] | None = Field(default=None, max_length=5)


class CanvasFeedRequest(BaseModel):
    # The per-user Canvas calendar feed link. Carries its own auth token in the
    # path, so it is a credential -- treated like one, never echoed back.
    feed_url: str | None = Field(default=None, max_length=2048)


class CanvasSettingsRequest(BaseModel):
    enabled: bool | None = None
    sync_time: str | None = None  # "HH:MM", 24-hour, local
    reminder_hours: list[int] | None = Field(default=None, max_length=8)
    # Drop work overdue by more than this from calendars (0 disables the filter).
    stale_days: int | None = Field(default=None, ge=0, le=365)
    push_to_apple: bool | None = None
    push_calendar: str | None = Field(default=None, max_length=2048)


class ACPAgentCreateRequest(BaseModel):
    name: str
    command: str
    args: list[str] = Field(default_factory=list, max_length=64)
    env: dict[str, str] = Field(default_factory=dict, max_length=64)
    cwd: str | None = None


class ACPAgentToggleRequest(BaseModel):
    enabled: bool


class ACPPromptRequest(BaseModel):
    prompt: str
    session_id: str | None = None
    cwd: str | None = None


class ModelToggleRequest(BaseModel):
    enabled: bool


class MCPServerCreateRequest(BaseModel):
    name: str
    transport: Literal["stdio", "http", "sse"] = "stdio"
    # stdio:
    command: str = ""
    args: list[str] = Field(default_factory=list, max_length=64)
    env: dict[str, str] = Field(default_factory=dict, max_length=64)
    # http / sse:
    url: str | None = None


class MCPServerToggleRequest(BaseModel):
    enabled: bool


class MCPToolCallRequest(BaseModel):
    tool: str
    arguments: dict = Field(default_factory=dict)


class MCPOAuthClientRequest(BaseModel):
    """Pre-registers a real OAuth client for a remote MCP server that has no
    Dynamic Client Registration (RFC 7591) endpoint -- see main.py's
    /mcp/servers/{id}/oauth-client and mcp_oauth.py's DCR docstring."""

    client_id: str
    client_secret: str | None = None


class CustomModelCreateRequest(BaseModel):
    name: str
    provider: Literal["openrouter", "ollama", "custom"]
    model_id: str
    category: str
    api_base: str | None = None
    api_key: str | None = None


class CustomModelDiscoverRequest(BaseModel):
    api_base: str = Field(max_length=2048)
    api_key: str | None = Field(default=None, max_length=2048)


class CustomModelToggleRequest(BaseModel):
    enabled: bool


class ChainStepRequest(BaseModel):
    model_id: str
    instructions: str


class AgentChainRequest(BaseModel):
    conversation_id: int
    steps: list[ChainStepRequest]


class WorkspaceTaskCreateRequest(BaseModel):
    message: str
    conversation_id: int | None = None


class WorkspaceTaskRetryRequest(BaseModel):
    confirm: bool = False


class TeamRoleOverrideRequest(BaseModel):
    model_id: str | None = None


class MaxHeavyWorkersRequest(BaseModel):
    max_heavy_workers: int


class SkillCreateRequest(BaseModel):
    name: str
    description: str = ""
    keywords: list[str] = Field(default_factory=list, max_length=40)
    body: str
    preferred_model_id: str | None = None


class OllamaPullRequest(BaseModel):
    name: str
    category: str
    display_name: str | None = None


class ProjectCreateRequest(BaseModel):
    name: str
    instructions: str = ""


class ProjectUpdateRequest(BaseModel):
    name: str | None = None
    instructions: str | None = None


class ConversationCreateRequest(BaseModel):
    tab: TabName
    project_id: int | None = None
    title: str = "New conversation"
    homework: bool = False


class ConversationUpdateRequest(BaseModel):
    title: str | None = None
    pinned: bool | None = None
    schedule_label: str | None = None
    clear_schedule_label: bool = False
    homework: bool | None = None


class MemoryUpdateRequest(BaseModel):
    content: str


class CodeFileWriteRequest(BaseModel):
    path: str
    content: str
    # Set by the editor to the fingerprint it got back from its last real
    # read of this file (see code_files.py's read_file/write_file) -- absent
    # (None) only for a brand-new file the editor never read from disk.
    # Task: "Never silently overwrite a file changed externally." Omitting
    # this or passing force=True skips the check entirely, which is exactly
    # what "Overwrite anyway" in the conflict dialog does -- a real,
    # explicit user choice, not a default.
    expected_fingerprint: str | None = None
    force: bool = False


class CodeWorkspaceRootRequest(BaseModel):
    path: str


class TypeSafeCredentialsRequest(BaseModel):
    # A TypeSafe API key. Written straight to the same ~/.ai-council/.env as
    # every other key and never read back out to a client.
    api_key: str | None = Field(default=None, max_length=512)


class ShareRequest(BaseModel):
    """Something shared to Nova from the phone (see share.py). All optional:
    an iOS Shortcut sends whichever of these the source app provided, and a
    share carrying only text is still a share."""

    url: str | None = Field(default=None, max_length=2048)
    text: str | None = Field(default=None, max_length=8000)
    title: str | None = Field(default=None, max_length=500)


class PhoneAccessRequest(BaseModel):
    """Whether the backend should listen beyond this machine (see access.py)."""

    enabled: bool


class OpenLinkRequest(BaseModel):
    url: str = Field(min_length=1, max_length=4000)
