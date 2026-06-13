import sys
import os
import subprocess
import time

print("App starting. PID:", os.getpid())
time.sleep(2)
print("Restarting now...")

script = f'ping 127.0.0.1 -n 3 > nul & "{sys.executable}" test_restart.py'
subprocess.Popen(["cmd.exe", "/c", script], creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
os._exit(0)
