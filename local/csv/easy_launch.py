import subprocess

# Path to the Python interpreter in your virtual environment
venv_python = "../local-venv/bin/python"

# Run the two Python commands using the venv's interpreter
subprocess.run([venv_python, "config2init.py"])
subprocess.run([venv_python, "../launch.py", "aws-init.yaml"])