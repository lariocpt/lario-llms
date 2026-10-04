#!/usr/bin/env python3
"""
Intel AI Stack Validation Script
Checks that all components are working correctly.
"""

import subprocess
import sys
import os

def run_cmd(cmd, check=True):
    """Run command and return output."""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=check)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        return e.stdout + e.stderr

def check_docker():
    print("=== Docker ===")
    out = run_cmd("docker --version")
    print(f"  Docker: {out}")
    out = run_cmd("docker compose version")
    print(f"  Compose: {out}")

def check_gpu():
    print("\n=== GPU/NPU ===")
    out = run_cmd("rocm-smi --showid 2>/dev/null | head -5", check=False)
    print(f"  AMD GPU: {out if out else 'Not found'}")
    
    out = run_cmd("clinfo 2>/dev/null | grep -i 'intel' | head -3", check=False)
    print(f"  Intel OpenCL: {out if out else 'Not found'}")
    
    out = run_cmd("ls /usr/lib/x86_64-linux-gnu/libze_intel_gpu.so 2>/dev/null", check=False)
    print(f"  Level Zero: {'Found' if out else 'Missing'}")

def check_npu():
    print("\n=== NPU ===")
    out = run_cmd("ls -la /dev/accel/ 2>/dev/null", check=False)
    print(f"  /dev/accel/: {out if out else 'Not found'}")
    
    try:
        import openvino as ov
        core = ov.Core()
        devices = core.available_devices
        print(f"  OpenVINO devices: {devices}")
    except ImportError:
        print("  OpenVINO: Not installed")
    except Exception as e:
        print(f"  OpenVINO error: {e}")

def check_containers():
    print("\n=== Containers ===")
    out = run_cmd("docker ps --format 'table {{.Names}}\\t{{.Status}}\\t{{.Ports}}' | grep -E 'ipex|openvino|llama|intel|gpu'")
    print(out if out else "  No Intel containers running")

def check_models():
    print("\n=== Models (OpenVINO IR) ===")
    model_dir = "./intel/models"
    if os.path.exists(model_dir):
        for root, dirs, files in os.walk(model_dir):
            for f in files:
                if f.endswith(('.xml', '.bin')):
                    path = os.path.join(root, f)
                    size = os.path.getsize(path) / (1024**2)
                    rel = os.path.relpath(path, model_dir)
                    print(f"  {rel}: {size:.1f} MB")
    else:
        print(f"  Model dir not found: {model_dir}")

def check_huggingface_models():
    print("\n=== HuggingFace Cache ===")
    hf_dir = "/mnt/xfs/AI_Models/huggingface"
    if os.path.exists(hf_dir):
        for f in sorted(os.listdir(hf_dir)):
            path = os.path.join(hf_dir, f)
            if os.path.isdir(path):
                print(f"  {f}/")
    else:
        print(f"  HF cache not found: {hf_dir}")

def check_network():
    print("\n=== Network ===")
    out = run_cmd("docker network inspect lario-net --format '{{.Name}}: {{.Driver}}'")
    print(f"  {out}")

def check_service_endpoints():
    print("\n=== Service Endpoints (if running) ===")
    endpoints = [
        ("ipex-server", "http://127.0.0.1:8081/health"),
        ("openvino-genai", "http://127.0.0.1:8082/health"),
        ("intel-embedding", "http://127.0.0.1:8001/health"),
        ("intel-asr", "http://127.0.0.1:8002/health"),
        ("intel-translation", "http://127.0.0.1:8003/health"),
        ("intel-tts", "http://127.0.0.1:8004/health"),
        ("intel-gateway", "http://127.0.0.1:8000/health"),
        ("intel-gpu-monitor", "http://127.0.0.1:9090"),
    ]
    
    import urllib.request
    for name, url in endpoints:
        try:
            req = urllib.request.Request(url, method='GET')
            resp = urllib.request.urlopen(req, timeout=2)
            print(f"  {name}: OK ({resp.status})")
        except Exception as e:
            print(f"  {name}: Not responding ({type(e).__name__})")

def main():
    print("=" * 60)
    print("Intel AI Stack Validation")
    print("=" * 60)
    
    check_docker()
    check_gpu()
    check_npu()
    check_containers()
    check_models()
    check_huggingface_models()
    check_network()
    check_service_endpoints()
    
    print("\n" + "=" * 60)
    print("Validation complete")
    print("=" * 60)

if __name__ == "__main__":
    main()
