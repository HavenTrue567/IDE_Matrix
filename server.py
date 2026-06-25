import os
import sys
import subprocess
import threading
import shutil
import queue
from flask import Flask, jsonify, request, send_from_directory
from flask_socketio import SocketIO, emit

# Since we are on Windows, we cannot use pty. We will use a subprocess with pipes and background reader threads.
# For a true terminal feel on Windows, we spawn powershell.exe with stdin, stdout, stderr piped.

if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    # Running in a PyInstaller bundle
    static_dir = os.path.join(sys._MEIPASS, 'static')
else:
    # Running in normal python environment
    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')

app = Flask(__name__, static_folder=static_dir, static_url_path='')
app.config['SECRET_KEY'] = 'termide_secret'
socketio = SocketIO(app, cors_allowed_origins="*")

# The workspace is the current directory of the server (or where it's launched)
WORKSPACE_DIR = os.path.abspath(os.getcwd())

# Keep track of active processes per client session
# session_id -> { 'process': Subprocess, 'thread': Thread, 'queue': Queue }
active_shells = {}
active_runs = {}

def safe_path(rel_path):
    """Ensure paths are inside the workspace to prevent directory traversal attacks."""
    abs_path = os.path.abspath(os.path.join(WORKSPACE_DIR, rel_path))
    if not abs_path.startswith(WORKSPACE_DIR):
        raise ValueError("Access denied: path is outside the workspace.")
    return abs_path

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/api/workspace', methods=['GET'])
def get_workspace_info():
    """Returns the workspace path and the list of files."""
    try:
        files = get_files_recursive(WORKSPACE_DIR)
        return jsonify({
            'workspace': WORKSPACE_DIR,
            'files': files
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def get_files_recursive(dir_path):
    items = []
    try:
        for entry in os.scandir(dir_path):
            # Skip hidden files and virtual envs
            if entry.name.startswith('.') or entry.name == '__pycache__' or entry.name == 'node_modules':
                continue
            
            # Skip python venv folder if matches common names
            if entry.is_dir() and (entry.name == '.venv' or entry.name == 'venv'):
                continue
                
            rel_path = os.path.relpath(entry.path, WORKSPACE_DIR).replace('\\', '/')
            if entry.is_dir():
                items.append({
                    'name': entry.name,
                    'path': rel_path,
                    'type': 'directory',
                    'children': get_files_recursive(entry.path)
                })
            else:
                items.append({
                    'name': entry.name,
                    'path': rel_path,
                    'type': 'file',
                    'size': entry.stat().st_size
                })
    except Exception as e:
        print(f"Error reading directory {dir_path}: {e}")
    # Sort directories first, then files alphabetically
    items.sort(key=lambda x: (0 if x['type'] == 'directory' else 1, x['name'].lower()))
    return items

@app.route('/api/file/read', methods=['POST'])
def read_file():
    data = request.json
    rel_path = data.get('path')
    try:
        abs_path = safe_path(rel_path)
        if not os.path.isfile(abs_path):
            return jsonify({'error': 'File not found'}), 404
        with open(abs_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        return jsonify({'content': content})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/file/write', methods=['POST'])
def write_file():
    data = request.json
    rel_path = data.get('path')
    content = data.get('content', '')
    try:
        abs_path = safe_path(rel_path)
        # Ensure directories exist
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return jsonify({'success': True, 'path': rel_path})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/file/create', methods=['POST'])
def create_item():
    data = request.json
    rel_path = data.get('path')
    item_type = data.get('type', 'file') # 'file' or 'directory'
    try:
        abs_path = safe_path(rel_path)
        if os.path.exists(abs_path):
            return jsonify({'error': 'File or directory already exists'}), 400
            
        if item_type == 'directory':
            os.makedirs(abs_path, exist_ok=True)
        else:
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            with open(abs_path, 'w', encoding='utf-8') as f:
                f.write('')
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/file/delete', methods=['POST'])
def delete_item():
    data = request.json
    rel_path = data.get('path')
    try:
        abs_path = safe_path(rel_path)
        if not os.path.exists(abs_path):
            return jsonify({'error': 'Path not found'}), 404
            
        if os.path.isdir(abs_path):
            shutil.rmtree(abs_path)
        else:
            os.remove(abs_path)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

# WebSockets logic for Terminal Emulator
def read_subprocess_output(proc, sid, event_name):
    """Reads output of a process in a background thread and sends it via SocketIO."""
    while True:
        # Read byte by byte or line by line
        # Reading byte by byte is better for interactive shell (shows prompts, character echoes)
        try:
            # We read raw bytes and decode them with system encoding
            # On Windows, powershell usually outputs in cp850 or utf-8 depending on configuration.
            # Using 'utf-8' with replacement character is safest for modern web.
            char = proc.stdout.read(1)
            if not char:
                break
            
            # Send the character/byte data to the frontend
            # Decode to unicode string
            try:
                decoded = char.decode('utf-8')
            except UnicodeDecodeError:
                try:
                    decoded = char.decode('cp850', errors='replace')
                except Exception:
                    decoded = char.decode('utf-8', errors='replace')
            
            socketio.emit(event_name, {'data': decoded}, to=sid)
        except Exception as e:
            print(f"Error reading process output: {e}")
            break
            
    # Process ended
    socketio.emit(f"{event_name}_exit", {'exit_code': proc.poll()}, to=sid)

@socketio.on('connect')
def handle_connect():
    print(f"Client connected: {request.sid}")

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    print(f"Client disconnected: {sid}")
    cleanup_shell(sid)
    cleanup_run(sid)

def cleanup_shell(sid):
    if sid in active_shells:
        shell = active_shells[sid]
        try:
            shell['process'].terminate()
            shell['process'].wait(timeout=1)
        except Exception:
            try:
                shell['process'].kill()
            except Exception:
                pass
        del active_shells[sid]

def cleanup_run(sid):
    if sid in active_runs:
        run = active_runs[sid]
        try:
            run['process'].terminate()
            run['process'].wait(timeout=1)
        except Exception:
            try:
                run['process'].kill()
            except Exception:
                pass
        del active_runs[sid]

@socketio.on('terminal_init')
def handle_terminal_init():
    sid = request.sid
    cleanup_shell(sid)
    
    # Start a shell subprocess
    # On Windows: powershell.exe
    # On Unix: bash or sh
    if sys.platform == 'win32':
        # Start powershell with standard input/output redirected.
        # We set shell=True and run powershell
        cmd = ['powershell.exe', '-NoExit', '-NoLogo']
    else:
        cmd = ['bash', '-i']
        
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, # Redirect stderr to stdout
            cwd=WORKSPACE_DIR,
            bufsize=0
        )
        
        # Start background reader thread
        thread = threading.Thread(
            target=read_subprocess_output,
            args=(proc, sid, 'terminal_output'),
            daemon=True
        )
        thread.start()
        
        active_shells[sid] = {
            'process': proc,
            'thread': thread
        }
        print(f"Started terminal shell for session {sid}")
    except Exception as e:
        emit('terminal_output', {'data': f"\r\nFailed to start terminal: {str(e)}\r\n"})

@socketio.on('terminal_input')
def handle_terminal_input(payload):
    sid = request.sid
    data = payload.get('data', '')
    if sid in active_shells:
        proc = active_shells[sid]['process']
        try:
            proc.stdin.write(data.encode('utf-8'))
            proc.stdin.flush()
        except Exception as e:
            print(f"Error writing to terminal stdin: {e}")

# WebSocket code execution runner
@socketio.on('run_code')
def handle_run_code(payload):
    sid = request.sid
    cleanup_run(sid)
    
    filename = payload.get('filename')
    language = payload.get('language')
    
    try:
        abs_path = safe_path(filename)
    except Exception as e:
        emit('run_output', {'data': f"Error: {str(e)}\r\n"}, to=sid)
        emit('run_exit', {'exit_code': -1}, to=sid)
        return
        
    if not os.path.exists(abs_path):
        emit('run_output', {'data': f"Error: File '{filename}' not found.\r\n"}, to=sid)
        emit('run_exit', {'exit_code': -1}, to=sid)
        return

    # Determine command based on language
    cmd = []
    if language == 'python':
        # Use active virtual env python if it exists, otherwise system python
        venv_python = os.path.join(WORKSPACE_DIR, '.venv', 'Scripts', 'python.exe') if sys.platform == 'win32' else os.path.join(WORKSPACE_DIR, '.venv', 'bin', 'python')
        python_exe = venv_python if os.path.exists(venv_python) else sys.executable
        cmd = [python_exe, '-u', abs_path]
    elif language == 'javascript':
        cmd = ['node', abs_path]
    elif language == 'csharp':
        # For C#, check if there is a .csproj in the workspace.
        # If not, let's create a temporary console project or a fast CS file runner configuration.
        # Professional approach: Check for project, if none, create a temporary .csproj in the directory
        # of the file or workspace, then dotnet run.
        proj_files = [f for f in os.listdir(WORKSPACE_DIR) if f.endswith('.csproj')]
        if proj_files:
            cmd = ['dotnet', 'run', '--project', WORKSPACE_DIR]
        else:
            # Check if Program.cs or other is in workspace.
            # We will generate a temp.csproj in workspace to compile the single file
            temp_proj_path = os.path.join(WORKSPACE_DIR, 'TermIDETemp.csproj')
            if not os.path.exists(temp_proj_path):
                # Create a basic net10.0 console application project file
                proj_content = """<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <OutputType>Exe</OutputType>
    <TargetFramework>net10.0</TargetFramework>
    <ImplicitUsings>enable</ImplicitUsings>
    <Nullable>enable</Nullable>
  </PropertyGroup>
</Project>
"""
                with open(temp_proj_path, 'w', encoding='utf-8') as f:
                    f.write(proj_content)
            cmd = ['dotnet', 'run', '--project', temp_proj_path]
    elif language == 'cpp':
        # Compile and run (requires g++)
        output_exe = abs_path.replace('.cpp', '.exe') if sys.platform == 'win32' else abs_path.replace('.cpp', '.out')
        # We need to run compiling first, then execute. To keep WebSocket runner simple, we can run a shell wrapper or run compilation synchronously.
        emit('run_output', {'data': "Compiling C++ code using g++...\r\n"}, to=sid)
        try:
            compile_res = subprocess.run(['g++', abs_path, '-o', output_exe], capture_output=True, text=True, timeout=10)
            if compile_res.returncode != 0:
                emit('run_output', {'data': f"Compilation Failed:\r\n{compile_res.stderr}\r\n"}, to=sid)
                emit('run_exit', {'exit_code': compile_res.returncode}, to=sid)
                return
            emit('run_output', {'data': "Compilation successful. Running...\r\n\r\n"}, to=sid)
            cmd = [output_exe]
        except FileNotFoundError:
            emit('run_output', {'data': "Error: g++ (GCC) not found in system PATH. Cannot compile C++.\r\n"}, to=sid)
            emit('run_exit', {'exit_code': -1}, to=sid)
            return
        except Exception as e:
            emit('run_output', {'data': f"Error during compilation: {str(e)}\r\n"}, to=sid)
            emit('run_exit', {'exit_code': -1}, to=sid)
            return
    else:
        emit('run_output', {'data': f"Error: Language '{language}' execution is not supported locally yet.\r\n"}, to=sid)
        emit('run_exit', {'exit_code': -1}, to=sid)
        return

    emit('run_output', {'data': f"Executing: {' '.join(cmd)}\r\n\r\n"}, to=sid)
    
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=WORKSPACE_DIR,
            bufsize=0
        )
        
        thread = threading.Thread(
            target=read_subprocess_output,
            args=(proc, sid, 'run_output'),
            daemon=True
        )
        thread.start()
        
        active_runs[sid] = {
            'process': proc,
            'thread': thread
        }
    except Exception as e:
        emit('run_output', {'data': f"Failed to execute code: {str(e)}\r\n"}, to=sid)
        emit('run_exit', {'exit_code': -1}, to=sid)

@socketio.on('run_input')
def handle_run_input(payload):
    sid = request.sid
    data = payload.get('data', '')
    if sid in active_runs:
        proc = active_runs[sid]['process']
        try:
            proc.stdin.write(data.encode('utf-8'))
            proc.stdin.flush()
        except Exception as e:
            print(f"Error writing to run process stdin: {e}")

@socketio.on('run_kill')
def handle_run_kill():
    sid = request.sid
    cleanup_run(sid)
    emit('run_output', {'data': "\r\n[Execution Terminated by User]\r\n"}, to=sid)
    emit('run_exit', {'exit_code': -1}, to=sid)

if __name__ == '__main__':
    # Auto-open browser on server startup
    import webbrowser
    port = 5000
    webbrowser.open(f'http://127.0.0.1:{port}')
    print(f"TermIDE server running on http://127.0.0.1:{port}")
    socketio.run(app, host='127.0.0.1', port=port, debug=False)
