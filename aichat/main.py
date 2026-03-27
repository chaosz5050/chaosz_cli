import sys
import os
import json
import re
import urllib.request
import urllib.error
import threading
from datetime import datetime

from rich.console import Console
from rich.markdown import Markdown
from rich.text import Text
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, DownloadColumn, TransferSpeedColumn
from ollama import Client, pull

from prompt_toolkit import Application
from prompt_toolkit.layout import Layout, HSplit, Window, FormattedTextControl, ScrollablePane, ScrollOffsets, Dimension
from prompt_toolkit.layout.containers import VSplit, ConditionalContainer, DynamicContainer
from prompt_toolkit.layout.controls import BufferControl
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style
from prompt_toolkit.formatted_text import HTML, ANSI
from prompt_toolkit.widgets import TextArea
from prompt_toolkit.data_structures import Point

# Configuration constants
CONFIG_FILE = "config.json"
MEMORY_FILE = "memory.json"
HISTORY_FILE = "history.json"
LOG_FILE = "llm.log"
MAX_MODELS = 8
VALID_CATEGORIES = {"about_user", "preferences", "projects", "top_of_mind"}
MAX_FILE_READS = 10
MAX_FILE_LINES = 500

DEFAULT_SYSTEM_PROMPT = """You are an intelligent, autonomous coding assistant. You prefer clean, well-structured code.

CRITICAL INSTRUCTIONS FOR FILE OPERATIONS:
You can interact with the local filesystem using these specific tags. Use them EXACTLY as shown.

1. [LIST:path]
   - List files in a directory to explore the project structure.
2. [READ:filename]
   - Read the entire contents of a file.
3. [WRITE:filename]
   - Create a NEW file or completely overwrite an existing one.
4. [EDIT:filename]
   - Perform surgical, line-by-line changes using SEARCH/REPLACE blocks.

IMPORTANT RULES:
- If a file exists, the system will ask for permission. Approve to apply IMMEDIATELY.
- Keep your explanations brief."""

console = Console()

ASCII_LOGO = r"""  ██████╗██╗  ██╗ █████╗  ██████╗ ███████╗███████╗
 ██╔════╝██║  ██║██╔══██╗██╔═══██╗██╔════╝╚══███╔╝
 ██║     ███████║███████║██║   ██║███████╗  ███╔╝ 
 ██║     ██╔══██║██╔══██║██║   ██║╚════██║ ███╔╝  
 ╚██████╗██║  ██║██║  ██║╚██████╔╝███████║███████╗
  ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚══════╝
        C L I  —  Local AI. No leash. No cloud."""

# --- Shared State ---
class AppState:
    def __init__(self):
        self.messages = []
        self.config = {}
        self.memory = {}
        self.active_model = ""
        self.max_ctx = 4096
        self.session_tokens = 0
        self.history_text = ""
        self.status_message = "Ready"
        self.system_prompt_base = DEFAULT_SYSTEM_PROMPT
        self.is_thinking = False
        self.mode = "CHAT" # CHAT or SYSTEM_SET
        self.current_app = None

state = AppState()

# --- Logic Helpers ---

def load_config():
    if not os.path.exists(CONFIG_FILE): return {"models": [], "active_model": None}
    with open(CONFIG_FILE, "r") as f:
        try: return json.load(f)
        except: return {"models": [], "active_model": None}

def save_config(config):
    with open(CONFIG_FILE, "w") as f: json.dump(config, f, indent=2)

def is_model_available(model_name):
    try:
        models_info = Client().list()
        for m in models_info.models:
            if m.model == model_name or m.model.startswith(model_name + ":"): return True
    except: pass
    return False

def apply_surgical_edit(content, blocks):
    new_content = content
    for search_text, replace_text in blocks:
        count = new_content.count(search_text)
        if count != 1: return None, f"Found {count} matches for SEARCH block."
        new_content = new_content.replace(search_text, replace_text)
    return new_content, None

def get_max_context(model_name):
    url = "http://localhost:11434/api/show"
    try:
        data = json.dumps({"name": model_name}).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=5) as response:
            result = json.loads(response.read().decode('utf-8'))
            for key, value in result.get("model_info", {}).items():
                if key.endswith(".context_length"): return value, True
    except: pass
    return 4096, False

def load_memory():
    if not os.path.exists(MEMORY_FILE): return {cat: [] for cat in VALID_CATEGORIES}
    with open(MEMORY_FILE, "r") as f:
        try:
            mem = json.load(f)
            for cat in VALID_CATEGORIES:
                if cat not in mem: mem[cat] = []
            return mem
        except: return {cat: [] for cat in VALID_CATEGORIES}

def add_memory(cat, text):
    if cat not in VALID_CATEGORIES or text in state.memory[cat]: return
    state.memory[cat].append(text)
    with open(MEMORY_FILE, "w") as f: json.dump(state.memory, f, indent=2)

def build_system_prompt():
    parts = [state.system_prompt_base]
    mem_parts = []
    for cat in sorted(VALID_CATEGORIES):
        if state.memory.get(cat):
            mem_parts.append(f"- {cat.replace('_', ' ').title()}:")
            for item in state.memory[cat]: mem_parts.append(f"  * {item}")
    if mem_parts: parts.append("\nMemory Context:\n" + "\n".join(mem_parts))
    return "\n".join(parts)

# --- UI Components ---

kb = KeyBindings()

@kb.add('c-c')
def _(event):
    event.app.exit()

@kb.add('enter')
def _(event):
    buffer = event.current_buffer
    if state.mode == "SYSTEM_SET":
        # In multi-line mode, enter just adds a line. 
        # We'll use a special keybind or logic to finish.
        return
    text = buffer.text.strip()
    if text:
        buffer.validate_and_handle()

@kb.add('escape', 'enter')
def _(event):
    """Save multi-line system prompt."""
    if state.mode == "SYSTEM_SET":
        buffer = event.current_buffer
        state.system_prompt_base = buffer.text.strip()
        state.mode = "CHAT"
        state.status_message = "System prompt updated."
        append_to_history(Text("\nSystem prompt updated successfully.", style="green"))
        buffer.reset()
        event.app.invalidate()

# Style Definition
style = Style.from_dict({
    'input-area': 'bg:#333333 #ffffff',
    'status-bar': 'bg:#222222 #cccccc',
    'status-line': 'bg:#111111 #888888 italic', 
    'history-area': '#ffffff',
    'separator': '#444444',
    'prompt-label': 'ansiblue bold',
    'mode-label': 'bg:ansired #ffffff bold',
})

def get_history_content():
    return ANSI(state.history_text)

def get_status_line():
    return HTML(f' <style fg="#666666">▶</style> {state.status_message}')

def get_toolbar():
    ratio = state.session_tokens / state.max_ctx if state.max_ctx > 0 else 0
    ctx_color = "ansicyan"
    if ratio > 0.9: ctx_color = "ansired"
    elif ratio > 0.7: ctx_color = "ansiyellow"
    
    thinking = " [THINKING...]" if state.is_thinking else ""
    return HTML(
        f' <b>Model:</b> <ansicyan>{state.active_model}</ansicyan> | '
        f'<b>Tokens:</b> <ansiyellow>{state.session_tokens}</ansiyellow> | '
        f'<b>Context:</b> <{ctx_color}>{int(ratio*100)}%</{ctx_color}>'
        f'{thinking} <style fg="#888888">(/help for commands)</style>'
    )

def get_prompt_label():
    if state.mode == "SYSTEM_SET":
        return HTML('<style fg="white" bg="ansired"><b> SET SYSTEM PROMPT (Esc+Enter to save): </b></style> ')
    return HTML('<ansiblue><b>You:</b> </ansiblue>')

# --- Main Application Logic ---

def append_to_history(rich_obj):
    with console.capture() as capture:
        console.print(rich_obj)
    state.history_text += capture.get()
    if state.current_app: state.current_app.invalidate()

def handle_input(buffer):
    user_input = buffer.text.strip()
    buffer.reset()
    
    if not user_input: return
    if user_input.lower() in ('quit', 'exit'):
        state.current_app.exit()
        return

    append_to_history(Text(f"\nYou: {user_input}", style="bold blue"))
    
    if user_input.startswith('/'):
        handle_command(user_input)
        return

    state.messages.append({"role": "user", "content": user_input})
    run_ai_turn()

def handle_command(user_input):
    args = user_input.split()
    cmd = args[0].lower()
    
    if cmd == '/help':
        msg = (
            "\n[bold cyan]Available Commands:[/bold cyan]\n"
            "  [purple]/help[/purple]             - Display this help message\n"
            "  [purple]/model[/purple] [green]list[/green]       - Show all model slots and their status\n"
            "  [purple]/model[/purple] [green]add[/green] <m>    - Add a new model to a slot\n"
            "  [purple]/model[/purple] [green]select[/green] <n> - Switch active model by slot number\n"
            "  [purple]/model[/purple] [green]delete[/green] <n> - Remove a model from a slot\n"
            "  [purple]/system[/purple] [green]show[/green]      - Display the current system prompt\n"
            "  [purple]/system[/purple] [green]set[/green]       - Enter multi-line mode to set a new system prompt\n"
            "  [purple]/system[/purple] [green]clear[/green]     - Remove the current system prompt\n"
            "  [purple]/memory[/purple] [green]show[/green]      - Display organized memory categories\n"
            "  [purple]/memory[/purple] [green]add[/green] <c> <t>- Add text to a memory category\n"
            "  [purple]/memory[/purple] [green]forget[/green] <c><i>- Remove specific memory\n"
            "  [purple]/memory[/purple] [green]clear[/green]     - Wipe all memories\n"
            "  [purple]/stats[/purple]            - Show token usage for current session\n"
            "  [purple]quit[/purple], [purple]exit[/purple]        - Exit the application\n"
        )
        append_to_history(Text.from_markup(msg))
    
    elif cmd == '/model':
        sub = args[1].lower() if len(args) > 1 else "list"
        if sub == "list":
            msg = "\n[bold cyan]Model Slots:[/bold cyan]\n"
            for i, m in enumerate(state.config["models"], 1):
                active = "[bold green](active)[/bold green]" if m == state.active_model else ""
                status = "" if is_model_available(m) else "[red](missing)[/red]"
                msg += f"  {i}. {m} {active} {status}\n"
            append_to_history(Text.from_markup(msg))
        elif sub == "select" and len(args) > 2:
            try:
                idx = int(args[2]) - 1
                state.active_model = state.config["models"][idx]
                state.config["active_model"] = state.active_model
                save_config(state.config)
                state.max_ctx, _ = get_max_context(state.active_model)
                append_to_history(Text(f"\nSwitched to {state.active_model}", style="green"))
            except: append_to_history(Text("\nInvalid index", style="red"))
        elif sub == "add" and len(args) > 2:
            m_name = args[2].strip()
            if is_model_available(m_name):
                state.config["models"].append(m_name)
                save_config(state.config)
                append_to_history(Text(f"\nAdded {m_name}", style="green"))
            else: append_to_history(Text(f"\nModel {m_name} not found locally.", style="red"))
        elif sub == "delete" and len(args) > 2:
            try:
                idx = int(args[2]) - 1
                removed = state.config["models"].pop(idx)
                save_config(state.config)
                append_to_history(Text(f"\nRemoved {removed}", style="green"))
            except: append_to_history(Text("\nInvalid index", style="red"))

    elif cmd == '/system':
        sub = args[1].lower() if len(args) > 1 else "show"
        if sub == "show":
            append_to_history(Text(f"\nCurrent System Prompt:\n{state.system_prompt_base}", style="cyan"))
        elif sub == "clear":
            state.system_prompt_base = ""
            append_to_history(Text("\nSystem prompt cleared.", style="green"))
        elif sub == "set":
            state.mode = "SYSTEM_SET"
            state.status_message = "ENTERING SYSTEM PROMPT SET MODE..."
            append_to_history(Text("\nEntering System Prompt mode. Type below, then press Esc+Enter to save.", style="yellow"))

    elif cmd == '/memory':
        sub = args[1].lower() if len(args) > 1 else "show"
        if sub == "show":
            msg = "\n[bold cyan]Current Memories:[/bold cyan]\n"
            for cat in sorted(VALID_CATEGORIES):
                if state.memory[cat]:
                    msg += f"[bold green]{cat}[/bold green]:\n"
                    for idx, item in enumerate(state.memory[cat], 1): msg += f"  {idx}. {item}\n"
            append_to_history(Text.from_markup(msg))
        elif sub == "add" and len(args) > 3:
            add_memory(args[2], " ".join(args[3:]))
            append_to_history(Text(f"\nAdded memory to {args[2]}.", style="green"))
        elif sub == "forget" and len(args) > 3:
            try:
                idx = int(args[3]) - 1
                removed = state.memory[args[2]].pop(idx)
                append_to_history(Text(f"\nRemoved memory: '{removed}'", style="green"))
            except: append_to_history(Text("\nInvalid category or index.", style="red"))
        elif sub == "clear":
            state.memory = {cat: [] for cat in VALID_CATEGORIES}
            append_to_history(Text("\nMemory cleared.", style="green"))

    elif cmd == '/stats':
        append_to_history(Text(f"\nTokens: {state.session_tokens}", style="yellow"))
    else:
        append_to_history(Text(f"\nUnknown command: {cmd}", style="red"))

def run_ai_turn():
    def _thread():
        state.is_thinking = True
        state.status_message = f"AI is thinking..."
        if state.current_app: state.current_app.invalidate()
        try:
            client = Client()
            api_msgs = [{"role": "system", "content": build_system_prompt()}] + state.messages
            full_response = ""
            state.history_text += "\n\033[32mAI:\033[0m "
            stream = client.chat(model=state.active_model, messages=api_msgs, stream=True, options={"num_ctx": state.max_ctx})
            for chunk in stream:
                if 'message' in chunk and 'content' in chunk['message']:
                    full_response += chunk['message']['content']
                if chunk.get('done'):
                    state.session_tokens += chunk.get('prompt_eval_count', 0) + chunk.get('eval_count', 0)
                    break
            disp = re.sub(r'\[REMEMBER:.*?\]', '', full_response, flags=re.IGNORECASE|re.DOTALL)
            state.history_text = state.history_text.rstrip() + " "
            append_to_history(Markdown(disp.strip()))
            state.messages.append({"role": "assistant", "content": full_response})
        except Exception as e: append_to_history(Text(f"\nError: {e}", style="red"))
        finally:
            state.is_thinking = False
            state.status_message = "Ready"
            if state.current_app: state.current_app.invalidate()
    threading.Thread(target=_thread, daemon=True).start()

def main():
    # Note: The sticky bar implementation mentioned in the request was not found in this file.
    # Please provide the correct file or location where the sticky bar is implemented.
    state.config = load_config()
    state.memory = load_memory()
    if not state.config["models"]:
        m = input("No models. Model name: ").strip()
        if m: state.config["models"].append(m); state.config["active_model"] = m; save_config(state.config)
    state.active_model = state.config.get("active_model", state.config["models"][0])
    state.max_ctx, _ = get_max_context(state.active_model)

    # 1. Scrollable History Viewport
    history_control = FormattedTextControl(get_history_content)
    history_window = Window(
        content=history_control, 
        wrap_lines=True,
    )
    # Wrap history in a ScrollablePane to ensure it handles overflow correctly
    scrollable_history = ScrollablePane(history_window)
    
    # 2. Dynamic Input Buffer & Window
    input_buffer = Buffer(accept_handler=handle_input)
    
    def get_input_height():
        """Calculates the height of the input box based on line count, starts at 1."""
        lines = input_buffer.document.line_count
        return Dimension(min=1, max=10, preferred=lines)

    input_window = Window(
        content=BufferControl(buffer=input_buffer),
        height=get_input_height,
        style='class:input-area'
    )
    
    # 3. Mid-level Status Line
    status_line_window = Window(
        content=FormattedTextControl(get_status_line),
        height=1,
        style='class:status-line'
    )
    
    # 4. Global Container
    root_container = HSplit([
        scrollable_history, # Use the scrollable wrapper
        Window(height=1, char='─', style='fg:#444444'),
        status_line_window,
        VSplit([
            Window(
                content=FormattedTextControl(get_prompt_label), 
                dont_extend_width=True, 
                height=get_input_height, # Apply dynamic height here too
                style='class:input-area'
            ),
            input_window
        ]),
        Window(content=FormattedTextControl(get_toolbar), height=1, style='class:status-bar')
    ])

    app = Application(layout=Layout(root_container, focused_element=input_window), key_bindings=kb, style=style, full_screen=True, mouse_support=True)
    state.current_app = app
    with console.capture() as capture: console.print(f"\n[bold cyan]{ASCII_LOGO}[/bold cyan]\n")
    state.history_text = capture.get()
    append_to_history(Text("Welcome to Chaosz CLI. /help for commands.", style="green"))
    app.run()

if __name__ == "__main__": main()
