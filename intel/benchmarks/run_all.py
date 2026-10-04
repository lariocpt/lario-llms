#!/usr/bin/env python3
"""
Run all benchmarks in sequence
"""

import subprocess
import sys
import os

BENCHMARKS = [
    ("embedding_benchmark.py", ["--models", "bge-m3-int8", "--iterations", "100"]),
    # Add more as implemented
]

def run_benchmark(script: str, args: list):
    """Run a benchmark script."""
    script_path = os.path.join(os.path.dirname(__file__), script)
    cmd = [sys.executable, script_path] + args
    print(f"\n{'='*60}")
    print(f"Running: {' '.join(cmd)}")
    print(f"{'='*60}")
    
    result = subprocess.run(cmd, capture_output=False)
    return result.returncode == 0


def main():
    print("Running all Intel AI benchmarks...")
    
    all_passed = True
    for script, args in BENCHMARKS:
        if not run_benchmark(script, args):
            print(f"FAILED: {script}")
            all_passed = False
        else:
            print(f"PASSED: {script}")
    
    if all_passed:
        print("\nAll benchmarks passed!")
        sys.exit(0)
    else:
        print("\nSome benchmarks failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()
