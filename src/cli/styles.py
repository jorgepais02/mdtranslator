import questionary
from rich.console import Console

# Shared console
console = Console()

WIZARD_STYLE = questionary.Style([
    ("qmark", "fg:blue bold"),
    ("question", "fg:white bold"),
    ("answer", "fg:green bold"),
    ("pointer", "fg:green bold"),         # ❯
    ("highlighted", "fg:green"),           # selected option
    ("selected", "fg:green bold"),
    ("instruction", "fg:#666666 italic"),  # hints dim
])
