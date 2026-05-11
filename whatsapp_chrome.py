#!/usr/bin/env python3
import subprocess
import os

def send_whatsapp(phone: str, message: str) -> bool:
    """
    Send WhatsApp message via Chrome WhatsApp Web using CDP
    """
    wa_cdp_path = os.path.join(os.path.dirname(__file__), "wa_cdp.js")
    node_path = os.path.join(os.path.dirname(__file__), "venv_parse/bin/python")

    env = os.environ.copy()
    env["NODE_PATH"] = os.path.join(os.path.dirname(__file__), "whatsapp_service/node_modules")

    try:
        result = subprocess.run(
            ["node", wa_cdp_path, phone, message],
            capture_output=True,
            text=True,
            timeout=30,
            env=env
        )
        return result.returncode == 0
    except Exception as e:
        print(f"WA send error: {e}")
        return False


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3:
        phone = sys.argv[1]
        message = " ".join(sys.argv[2:])
        result = send_whatsapp(phone, message)
        print(f"Result: {result}")
    else:
        print("Usage: python whatsapp_chrome.py <phone> <message>")