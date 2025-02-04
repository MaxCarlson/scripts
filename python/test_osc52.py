#!/usr/bin/env python3
import base64
import sys

def send_osc52(text: str):
    # Encode text in base64.
    encoded = base64.b64encode(text.encode("utf-8")).decode("utf-8")
    # Construct the OSC 52 sequence:
    # \033]52;c;<base64-encoded-data>\a
    osc52 = f"\033]52;c;{encoded}\a"
    # Output without a newline to ensure only the OSC sequence is sent.
    print(osc52, end="", flush=True)

if __name__ == "__main__":
    # Test text (or you can use sys.argv to pass a parameter)
    test_text = "OSC52 test: Hello from remote"
    send_osc52(test_text)

