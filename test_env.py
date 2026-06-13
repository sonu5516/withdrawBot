import sys
import os

with open("env_log.txt", "w") as f:
    f.write(f"sys.executable: {sys.executable}\n")
    for k, v in os.environ.items():
        if "MEI" in k or "TCL" in k or k.startswith("_"):
            f.write(f"{k}={v}\n")
