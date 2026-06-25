import os
import sys
import subprocess
import shutil

def build():
    print("==========================================")
    print("TermIDE Executable Compiler (PyInstaller)")
    print("==========================================")
    print()

    # Determine paths
    venv_pyinstaller = os.path.join(".venv", "Scripts", "pyinstaller.exe") if sys.platform == 'win32' else os.path.join(".venv", "bin", "pyinstaller")
    pyinstaller_cmd = venv_pyinstaller if os.path.exists(venv_pyinstaller) else "pyinstaller"

    # Verify static directory exists
    if not os.path.exists("static"):
        print("[ERROR] 'static' directory not found. Cannot build without frontend assets.")
        sys.exit(1)

    print("[INFO] Building single-file executable using PyInstaller...")
    
    # PyInstaller arguments:
    # --onefile: Create a single executable file
    # --add-data: Include static/ directory (Windows uses ; separator, Unix uses :)
    # --name: Name of output executable
    # --clean: Clean cache before building
    separator = ";" if sys.platform == "win32" else ":"
    cmd = [
        pyinstaller_cmd,
        "--onefile",
        f"--add-data=static{separator}static",
        "--name=TermIDE",
        "--clean",
        "server.py"
    ]

    print(f"[RUNNING] {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, check=True)
        if result.returncode == 0:
            print("\n==========================================")
            print("[SUCCESS] Build completed successfully!")
            exe_path = os.path.abspath(os.path.join("dist", "TermIDE.exe" if sys.platform == "win32" else "TermIDE"))
            print(f"[INFO] Executable created at: {exe_path}")
            print("==========================================")
            
            # Clean up build directories to keep workspace clean
            print("\n[INFO] Cleaning up temporary build artifacts...")
            if os.path.exists("build"):
                shutil.rmtree("build")
            if os.path.exists("TermIDE.spec"):
                os.remove("TermIDE.spec")
            print("[INFO] Cleanup complete. Only 'dist/TermIDE.exe' is retained.")
    except subprocess.CalledProcessError as e:
        print(f"\n[ERROR] PyInstaller compilation failed: {e}")
        sys.exit(1)
    except FileNotFoundError:
        print("\n[ERROR] PyInstaller was not found. Make sure dependencies are installed via 'pip install -r requirements.txt'")
        sys.exit(1)

if __name__ == "__main__":
    build()
