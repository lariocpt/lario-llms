#!/usr/bin/env python3
import os
import sys
import argparse
import base64
import json
import subprocess
import requests

def parse_args():
    parser = argparse.ArgumentParser(
        description="Local GPU-Passthrough UI/UX Visual Inspection Tool (Using Lama 3.2 Vision & Chromium)"
    )
    parser.add_argument(
        "source",
        help="Path to the HTML file (e.g. /workspace/index.html) or active URL (e.g. http://localhost:3000)"
    )
    parser.add_argument(
        "--mockup",
        help="Optional path to the design mockup image to compare against",
        default=None
    )
    parser.add_argument(
        "--output",
        help="Path where the headlessly captured screenshot should be saved",
        default="/tmp/rendered_ui.png"
    )
    parser.add_argument(
        "--width",
        help="Viewport width for the headless browser",
        type=int,
        default=1280
    )
    parser.add_argument(
        "--height",
        help="Viewport height for the headless browser",
        type=int,
        default=800
    )
    return parser.parse_args()

def capture_screenshot(source, output_path, width, height):
    print(f"📸 headlessly rendering source: {source}...")
    
    # Resolve file vs URL
    url = source
    if not source.startswith("http://") and not source.startswith("https://"):
        if os.path.exists(source):
            url = f"file://{os.path.abspath(source)}"
        else:
            print(f"❌ Error: Source file or URL '{source}' does not exist.")
            sys.exit(1)
            
    # Locate browser binary (tries google-chrome, chromium-browser, and chromium)
    browser_binary = None
    for binary in ["google-chrome", "chromium-browser", "chromium"]:
        if subprocess.run(["which", binary], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
            browser_binary = binary
            break
            
    if not browser_binary:
        print("❌ Error: No headless browser (google-chrome or chromium) found in PATH.")
        print("Please ensure your containers are rebuilt with the new browser package.")
        sys.exit(1)
        
    cmd = [
        browser_binary,
        "--headless",
        "--disable-gpu",
        "--no-sandbox",
        "--virtual-time-budget=5000",
        f"--screenshot={output_path}",
        f"--window-size={width},{height}",
        url
    ]
    
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"✔ Screenshot captured successfully and saved to {output_path}!")
    except subprocess.CalledProcessError as e:
        print(f"❌ Headless browser screenshot capture failed: {e}")
        sys.exit(1)

def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")

def analyze_ui(screenshot_path, mockup_path):
    print("🧠 Sending screenshot to local AMD GPU-accelerated Llama-Vision model via Bifrost...")
    
    # Auto-detect Ollama native endpoint directly
    endpoints = ["http://ollama:11434/api", "http://127.0.0.1:11434/api", "http://localhost:11434/api"]
    api_url = None
    for ep in endpoints:
        try:
            r = requests.get(f"{ep}/version", timeout=2)
            if r.status_code == 200:
                api_url = f"{ep}/chat"
                print(f"✔ Connected to active Ollama Engine at {ep}!")
                break
        except Exception:
            continue
            
    if not api_url:
        print("❌ Error: Could not reach Bifrost Gateway on standard internal or local ports.")
        print("Please verify the containers are active by running 'docker ps'.")
        sys.exit(1)
        
    # Convert screenshot to Base64
    screenshot_b64 = encode_image(screenshot_path)
    
    # Prepare message payload
    content = [
        {
            "type": "text",
            "text": "You are a professional, elite UI/UX auditor and front-end development QA specialist. Evaluate this headlessly rendered screenshot of our UI. Check for layout bugs, misalignments, overlapping text, poorly sized elements, and bad color contrast. Suggest exact, actionable HTML/CSS/Tailwind refactoring fixes."
        },
        {
            "type": "image_url",
            "images": [screenshot_b64]
        }
    ]
    
    # If a design mockup is provided, append it to compare
    if mockup_path and os.path.exists(mockup_path):
        print(f"🎨 Including design mockup from {mockup_path} for comparison...")
        mockup_b64 = encode_image(mockup_path)
        content[0]["text"] += " Compare the rendered UI (first image) with the original design mockup (second image). Highlight any visual discrepancies, missing elements, wrong spacing, or layout bugs, and specify exactly how to refactor the code to match the mockup perfectly."
        content[1]["images"].append(mockup_b64)
        
    payload = {
        "model": "llama3.2-vision:latest",
        "messages": [
            {
                "role": "user",
                "content": content[0]["text"],
                "images": content[1]["images"]
            }
        ],
        "options": {
            "temperature": 0.2,
            "num_ctx": 8192
        },
        "stream": False
    }
    
    try:
        response = requests.post(api_url, json=payload, headers={"Content-Type": "application/json"})
        response.raise_for_status()
        res_json = response.json()
        
        # Display the result
        print("\n" + "="*80)
        print("🔍 LOCAL VISUAL INSPECTION REVIEW (Llama-Vision):")
        print("="*80)
        print(res_json["message"]["content"])
        print("="*80 + "\n")
        
    except requests.exceptions.RequestException as e:
        print(f"❌ Failed to communicate with Vision model API: {e}")
        if response is not None:
            print(f"Response: {response.text}")
        sys.exit(1)

def main():
    args = parse_args()
    capture_screenshot(args.source, args.output, args.width, args.height)
    analyze_ui(args.output, args.mockup)

if __name__ == "__main__":
    main()
