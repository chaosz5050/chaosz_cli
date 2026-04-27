import os
import threading
import uuid


class SessionState:
    def __init__(self):
        self.id = uuid.uuid4().hex
        self.messages: list = []
        self.tokens: int = 0
        self.prompt_tokens: int = 0
        self.completion_tokens: int = 0
        self.cached_tokens: int = 0
        self.lock = threading.Lock()
        self.log_path: str | None = None


class ProviderState:
    def __init__(self):
        self.active: str = "deepseek"
        self.model: str = ""
        self.max_ctx: int = 4096
        self.max_output_tokens: int = 8192
        self.temperature: float = 0.7
        self.temp_menu_index: int = 2   # default to Balanced (index 2)
        self.config: dict = {}
        self.available_models: list[str] = []
        self.available_models_index: int = 0
        self.menu_providers: list[str] = []
        self.menu_index: int = 0
        self.pending: str = ""   # staging area during add/del wizard flows


class ReasoningState:
    def __init__(self):
        self.enabled: bool = False
        self.memory: dict = {}
        self.personality: str = ""
        self.personality_buffer: list[str] = []
        self.active_skill: str | None = None
        self.skill_add_name: str = ""
        self.skill_add_buffer: list[str] = []


class WorkspaceState:
    def __init__(self):
        self.working_dir: str | None = None
        self.file_op_log: list[dict] = []


class PermissionsState:
    def __init__(self):
        self.granted: bool = False
        self.awaiting: bool = False
        self.file_session_allowed: set[str] = set()
        self.file_read_session_allowed: set[str] = set()
        self.file_session_granted: bool = False
        self.shell_session_allowed: set = set()
        self.shell_session_granted: bool = False
        self.awaiting_shell: bool = False
        self.pending_shell_command: tuple | None = None
        self.sudo_password: str | None = None
        self.approval_index: int = 0
        self.approval_option_count: int = 3


class UiState:
    def __init__(self):
        # CHAT | PERSONALITY_SET | PERSONALITY_CLEAR_CONFIRM | WORKDIR_SET | APIKEY_SET
        # | SHELL_PERMISSION | PASSWORD | MODEL_SELECT | MODEL_ADD_SELECT | MODEL_ADD_KEY
        # | MODEL_DEL_CONFIRM | EXIT_CONFIRM | EXITING | OLLAMA_SETUP | OLLAMA_DEL_DISK_CONFIRM
        # | MODEL_SELECT_VERSION | TEMP_SELECT | MCP_SETUP | PLAN_APPROVE
        self.mode: str = "CHAT"
        self.is_thinking: bool = False
        self.cancel_requested: bool = False
        self.ctx_estimated_tokens: int = 0
        self.plan_mode: bool = False          # persistent toggle via /plan command
        self.plan_mode_this_turn: bool = False # transient: set by keyword detection, reset after each turn
        self.plan_steps: list = []            # parsed step strings for the step-driver
        self.plan_step_index: int = 0         # which step is currently executing (0-based)
        self.plan_executing: bool = False     # True while step-driver is active
        self.plan_summarizing: bool = False   # True during the post-execution summary turn
        self.plan_goal: str = ""              # original user request that triggered the plan
        self.skill_menu_names: list[str] = []
        self.skill_menu_index: int = 0
        self.theme_menu_names: list[str] = []
        self.theme_menu_index: int = 0
        self.plan_approval_index: int = 0


class OllamaWizardState:
    def __init__(self):
        self.step: str = ""
        self.pending_model: str = ""
        self.input_event: threading.Event | None = None
        self.input_answer: str = ""
        self.del_model: str = ""


class McpWizardState:
    def __init__(self):
        self.step: str = ""
        self.input_answer: str = ""
        self.input_event: threading.Event | None = None
        self.data: dict = {}


class BackgroundState:
    def __init__(self):
        self.compacting: bool = False
        self.reflection_active: bool = False


class AppState:
    def __init__(self):
        self.session = SessionState()
        self.provider = ProviderState()
        self.reasoning = ReasoningState()
        self.workspace = WorkspaceState()
        self.permissions = PermissionsState()
        self.ui = UiState()
        self.ollama_wizard = OllamaWizardState()
        self.mcp_wizard = McpWizardState()
        self.background = BackgroundState()

    def trigger_reflection(self, app=None) -> None:
        """Run a reflection pass: update memory from live context, collapse session file."""
        from chaosz.config import CHAOSZ_DIR
        lock_path = os.path.join(CHAOSZ_DIR, ".reflecting.lock")

        # Remove any stale lock left by a previous crashed session
        if os.path.exists(lock_path):
            try:
                os.remove(lock_path)
            except OSError:
                pass

        self.background.reflection_active = True
        try:
            with open(lock_path, "w") as f:
                f.write("")

            if self.session.log_path:
                try:
                    with open(self.session.log_path, "a") as f:
                        f.write("REFLECTION PASS TRIGGERED\n")
                except OSError:
                    pass

            if app is not None:
                app.call_from_thread(app._start_reflect_glitch)

            from chaosz.session import run_reflection_pass
            run_reflection_pass(app)

        finally:
            if os.path.exists(lock_path):
                try:
                    os.remove(lock_path)
                except OSError:
                    pass
            self.background.reflection_active = False
            if app is not None:
                app.call_from_thread(app._stop_reflect_glitch)


state = AppState()

# Thread synchronisation for permission prompts and working directory setup
_permission_event = threading.Event()
