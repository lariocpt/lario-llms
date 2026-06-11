import base64
import json
import requests
import sys

def test_bifrost():
    try:
        with open("/tmp/rendered_ui.png", "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
    except Exception as e:
        print("Failed to read image:", e)
        return

    payload = {
        "model": "llama3.2-vision:latest",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What do you see in this image?"},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
                ]
            }
        ]
    }

    try:
        r = requests.post("http://127.0.0.1:8080/v1/chat/completions", json=payload)
        r.raise_for_status()
        print("Response from Bifrost:", r.json()["choices"][0]["message"]["content"])
    except Exception as e:
        print("Failed:", e)
        if hasattr(e, "response") and e.response is not None:
            print(e.response.text)

if __name__ == "__main__":
    test_bifrost()
