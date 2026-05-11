#!/usr/bin/env python3
import subprocess
import time
import logging

logger = logging.getLogger(__name__)

def send_whatsapp_message(phone: str, message: str) -> bool:
    """
    Send WhatsApp message using Desktop app via AppleScript + cliclick
    """
    try:
        subprocess.run([
            'osascript', '-e',
            'tell application "WhatsApp" to activate'
        ], check=True, capture_output=True)
        time.sleep(0.5)

        search_x, search_y = 1100, 120
        subprocess.run(['cliclick', f'c:{search_x},{search_y}'], check=True)
        time.sleep(0.3)

        subprocess.run([
            'osascript', '-e',
            f'tell application "System Events" to tell process "WhatsApp" to keystroke "{phone}"'
        ], check=True, capture_output=True)
        time.sleep(1)

        subprocess.run([
            'osascript', '-e',
            'tell application "System Events" to tell process "WhatsApp" to key code 36'
        ], check=True, capture_output=True)
        time.sleep(1)

        input_x, input_y = 1600, 700
        subprocess.run(['cliclick', f'c:{input_x},{input_y}'], check=True)
        time.sleep(0.3)

        subprocess.run([
            'osascript', '-e',
            f'tell application "System Events" to tell process "WhatsApp" to keystroke "{message}"'
        ], check=True, capture_output=True)
        time.sleep(0.3)

        subprocess.run([
            'osascript', '-e',
            'tell application "System Events" to tell process "WhatsApp" to key code 36'
        ], check=True, capture_output=True)

        logger.info(f"WhatsApp message sent to {phone}: {message}")
        return True

    except Exception as e:
        logger.error(f"Failed to send WhatsApp message: {e}")
        return False


def send_whatsapp_message_by_name(name: str, message: str) -> bool:
    """
    Send WhatsApp message to a contact by name
    """
    try:
        subprocess.run([
            'osascript', '-e',
            'tell application "WhatsApp" to activate'
        ], check=True, capture_output=True)
        time.sleep(0.5)

        search_x, search_y = 1100, 120
        subprocess.run(['cliclick', f'c:{search_x},{search_y}'], check=True)
        time.sleep(0.3)

        subprocess.run([
            'osascript', '-e',
            f'tell application "System Events" to tell process "WhatsApp" to keystroke "{name}"'
        ], check=True, capture_output=True)
        time.sleep(1)

        subprocess.run([
            'osascript', '-e',
            'tell application "System Events" to tell process "WhatsApp" to key code 36'
        ], check=True, capture_output=True)
        time.sleep(1)

        input_x, input_y = 1600, 700
        subprocess.run(['cliclick', f'c:{input_x},{input_y}'], check=True)
        time.sleep(0.3)

        subprocess.run([
            'osascript', '-e',
            f'tell application "System Events" to tell process "WhatsApp" to keystroke "{message}"'
        ], check=True, capture_output=True)
        time.sleep(0.3)

        subprocess.run([
            'osascript', '-e',
            'tell application "System Events" to tell process "WhatsApp" to key code 36'
        ], check=True, capture_output=True)

        logger.info(f"WhatsApp message sent to {name}: {message}")
        return True

    except Exception as e:
        logger.error(f"Failed to send WhatsApp message: {e}")
        return False


if __name__ == "__main__":
    print("WhatsApp Desktop module loaded")
    print("Usage: import whatsapp_desktop and call send_whatsapp_message_by_name('Name', 'Message')")