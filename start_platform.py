import os
import subprocess
import sys
import threading
import time
import signal

# Colored log prefixes using ANSI escape codes
COLOR_BACKEND = "\033[94m" # Blue
COLOR_FRONTEND = "\033[96m" # Cyan
COLOR_SYSTEM = "\033[93m"   # Yellow
COLOR_RESET = "\033[0m"

processes = []

def run_log_reader(process, prefix, color):
    """Reads stdout of a subprocess and prints it with a colored prefix."""
    try:
        for line in iter(process.stdout.readline, ''):
            if not line:
                break
            print(f"{color}{prefix}{COLOR_RESET} {line.strip()}", flush=True)
    except Exception as e:
        print(f"{COLOR_SYSTEM}[LAUNCHER-ERROR] Error reading output from {prefix}: {e}{COLOR_RESET}", flush=True)

def install_backend_deps():
    print(f"{COLOR_SYSTEM}[LAUNCHER] Checking backend virtual environment...{COLOR_RESET}")
    venv_dir = os.path.join(os.getcwd(), "pilssVenv")
    
    # Path to pip/python inside venv depending on OS
    if os.name == "nt":  # Windows
        python_exe = os.path.join(venv_dir, "Scripts", "python.exe")
        pip_exe = os.path.join(venv_dir, "Scripts", "pip.exe")
    else:  # Linux/macOS
        python_exe = os.path.join(venv_dir, "bin", "python")
        pip_exe = os.path.join(venv_dir, "bin", "pip")

    if not os.path.exists(venv_dir):
        print(f"{COLOR_SYSTEM}[LAUNCHER] venv not found. Creating virtual environment...{COLOR_RESET}")
        subprocess.run([sys.executable, "-m", "venv", "pilssVenv"])
        print(f"{COLOR_SYSTEM}[LAUNCHER] Upgrading pip...{COLOR_RESET}")
        subprocess.run([python_exe, "-m", "pip", "install", "--upgrade", "pip"])

    root_req = os.path.join(os.getcwd(), "requirements.txt")
    print(f"{COLOR_SYSTEM}[LAUNCHER] Verifying packages from root requirements.txt...{COLOR_RESET}")
    subprocess.run([pip_exe, "install", "-r", root_req])
    return python_exe

def install_frontend_deps():
    print(f"{COLOR_SYSTEM}[LAUNCHER] Checking frontend node_modules...{COLOR_RESET}")
    frontend_dir = os.path.join(os.getcwd(), "frontend")
    node_modules = os.path.join(frontend_dir, "node_modules")
    
    if not os.path.exists(node_modules):
        print(f"{COLOR_SYSTEM}[LAUNCHER] node_modules not found. Installing packages...{COLOR_RESET}")
        # Run npm install using cmd shell wrapper on Windows to bypass policy issues
        shell_arg = True if os.name == "nt" else False
        subprocess.run("npm install", shell=shell_arg, cwd=frontend_dir)
    else:
        print(f"{COLOR_SYSTEM}[LAUNCHER] node_modules verified.{COLOR_RESET}")

def start_backend(python_exe):
    print(f"{COLOR_SYSTEM}[LAUNCHER] Starting FastAPI Backend on port 8000...{COLOR_RESET}")
    backend_dir = os.path.join(os.getcwd(), "backend")
    
    # Launch runner script inside venv
    run_file = os.path.join(backend_dir, "run.py")
    proc = subprocess.Popen(
        [python_exe, run_file],
        cwd=backend_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )
    processes.append(proc)
    
    # Start thread to read logs
    t = threading.Thread(target=run_log_reader, args=(proc, "[BACKEND]", COLOR_BACKEND), daemon=True)
    t.start()

def start_frontend():
    print(f"{COLOR_SYSTEM}[LAUNCHER] Starting Next.js Frontend on port 3000...{COLOR_RESET}")
    frontend_dir = os.path.join(os.getcwd(), "frontend")
    
    shell_arg = True if os.name == "nt" else False
    proc = subprocess.Popen(
        "npm run dev",
        shell=shell_arg,
        cwd=frontend_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )
    processes.append(proc)
    
    # Start thread to read logs
    t = threading.Thread(target=run_log_reader, args=(proc, "[FRONTEND]", COLOR_FRONTEND), daemon=True)
    t.start()

def shutdown_handler(signum, frame):
    clean_exit()

def clean_exit():
    print(f"\n{COLOR_SYSTEM}[LAUNCHER] Intercepted exit signal. Shutting down platform...{COLOR_RESET}")
    for p in processes:
        try:
            print(f"{COLOR_SYSTEM}[LAUNCHER] Stopping subprocess PID: {p.pid}...{COLOR_RESET}")
            # Under Windows, shell subprocesses might require taskkill to clean up children
            if os.name == "nt":
                subprocess.run(f"taskkill /F /T /PID {p.pid}", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                p.terminate()
                p.wait(timeout=3)
        except Exception as e:
            print(f"Error terminating process: {e}")
    print(f"{COLOR_SYSTEM}[LAUNCHER] Exited cleanly.{COLOR_RESET}")
    sys.exit(0)

def main():
    # Setup signal handlers for standard exit calls
    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)
    
    print(f"{COLOR_SYSTEM}=== PILSS PLATFORM LAUNCHER ==={COLOR_RESET}")
    try:
        # Step 1: Pre-flight installations
        python_exe = install_backend_deps()
        install_frontend_deps()
        
        # Step 2: Start services
        start_backend(python_exe)
        # Wait a moment for database / schema sync before starting frontend
        time.sleep(2.0)
        start_frontend()

        print(f"{COLOR_SYSTEM}[LAUNCHER] System running! Press Ctrl+C to terminate services.{COLOR_RESET}")
        
        # Keep launcher thread alive
        while True:
            time.sleep(1)
            # Check if subprocesses died unexpectedly
            for p in processes:
                if p.poll() is not None:
                    print(f"{COLOR_SYSTEM}[LAUNCHER] A server subprocess exited with code {p.returncode}. Stopping all...{COLOR_RESET}")
                    clean_exit()
                    
    except KeyboardInterrupt:
        clean_exit()
    except Exception as e:
        print(f"{COLOR_SYSTEM}[LAUNCHER-FATAL] Startup failed: {e}{COLOR_RESET}")
        clean_exit()

if __name__ == "__main__":
    main()
