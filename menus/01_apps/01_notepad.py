"""Command button: launch Notepad. The printed line shows on the button."""
import subprocess

subprocess.Popen(["notepad.exe"])
print("Launched")
