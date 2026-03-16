class CLIError(Exception):
    """Base exception for CLI errors."""
    def __init__(self, message: str, exit_code: int = 2):
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code

class FileNotFoundError(CLIError):
    def __init__(self, path: str):
        super().__init__(f"✗ File not found: {path}", exit_code=2)

class APIAuthError(CLIError):
    def __init__(self, provider: str):
        super().__init__(f"✗ Authentication failed for {provider}", exit_code=2)

class APITimeoutError(CLIError):
    def __init__(self, lang: str):
        super().__init__(f"✗ timeout for {lang}", exit_code=1)
