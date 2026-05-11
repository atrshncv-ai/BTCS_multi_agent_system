from .prian_cmd import prian_cmd, DESCRIPTION as PRIAN_DESC
from .start_cmd import start_cmd, DESCRIPTION as START_DESC

__all__ = ["all_commands"]

all_commands = [
    {"name": "start", "func": start_cmd, "description": START_DESC},
    {"name": "prian", "func": prian_cmd, "description": PRIAN_DESC},
]