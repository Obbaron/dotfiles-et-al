import sys
print(f"[setup.py] running under {sys.executable}")
print(f"[setup.py] version {sys.version_info.major}.{sys.version_info.minor}")
print(f"[setup.py] args: {sys.argv[1:]}")
