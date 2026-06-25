const express = require('express');
const path = require('path');
const fs = require('fs');
const { spawn, execSync } = require('child_process');

const app = express();
const PORT = process.env.PORT || 3000;

app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

const WORKSPACE_DIR = __dirname;
const RUNNER_DIR = path.join(WORKSPACE_DIR, '.runner');
const PYTHON_RUNNER_DIR = path.join(RUNNER_DIR, 'python');
const CSHARP_RUNNER_DIR = path.join(RUNNER_DIR, 'csharp');

// Ensure runner directories exist
if (!fs.existsSync(RUNNER_DIR)) fs.mkdirSync(RUNNER_DIR);
if (!fs.existsSync(PYTHON_RUNNER_DIR)) fs.mkdirSync(PYTHON_RUNNER_DIR);
if (!fs.existsSync(CSHARP_RUNNER_DIR)) fs.mkdirSync(CSHARP_RUNNER_DIR);

// Initialize C# project if it doesn't exist
function initCSharpProject() {
  const programPath = path.join(CSHARP_RUNNER_DIR, 'Program.cs');
  const csprojPath = path.join(CSHARP_RUNNER_DIR, 'csharp.csproj');
  if (!fs.existsSync(programPath) || !fs.existsSync(csprojPath)) {
    console.log('Initializing C# console template in .runner/csharp...');
    try {
      execSync('dotnet new console -o .runner/csharp --force --no-restore', { cwd: WORKSPACE_DIR });
      console.log('C# console template initialized successfully.');
    } catch (err) {
      console.error('Failed to initialize C# project:', err.message);
    }
  }
}
initCSharpProject();

// Helper to filter workspace files (ignore node_modules, .runner, etc.)
function getFilesRecursively(dir, fileList = []) {
  const files = fs.readdirSync(dir);
  for (const file of files) {
    const filePath = path.join(dir, file);
    const stat = fs.statSync(filePath);

    // Ignore hidden or system directories
    if (file === 'node_modules' || file === '.runner' || file === '.git' || file === '.agents' || file === '.gemini') {
      continue;
    }

    if (stat.isDirectory()) {
      fileList.push({
        name: file,
        path: path.relative(WORKSPACE_DIR, filePath).replace(/\\/g, '/'),
        type: 'directory',
        children: getFilesRecursively(filePath)
      });
    } else {
      fileList.push({
        name: file,
        path: path.relative(WORKSPACE_DIR, filePath).replace(/\\/g, '/'),
        type: 'file',
        size: stat.size
      });
    }
  }
  return fileList;
}

// --- FILE SYSTEM API ENDPOINTS ---

// List files
app.get('/api/files', (req, res) => {
  try {
    const files = getFilesRecursively(WORKSPACE_DIR);
    res.json({ success: true, files });
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

// Read file content
app.post('/api/files/read', (req, res) => {
  const { relativePath } = req.body;
  if (!relativePath) return res.status(400).json({ success: false, error: 'Path is required' });

  const safePath = path.join(WORKSPACE_DIR, relativePath);
  // Ensure the file is inside the workspace
  if (!safePath.startsWith(WORKSPACE_DIR)) {
    return res.status(403).json({ success: false, error: 'Access denied' });
  }

  try {
    if (fs.existsSync(safePath)) {
      const content = fs.readFileSync(safePath, 'utf-8');
      res.json({ success: true, content });
    } else {
      res.status(404).json({ success: false, error: 'File not found' });
    }
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

// Write file content / Save
app.post('/api/files/write', (req, res) => {
  const { relativePath, content } = req.body;
  if (!relativePath) return res.status(400).json({ success: false, error: 'Path is required' });

  const safePath = path.join(WORKSPACE_DIR, relativePath);
  if (!safePath.startsWith(WORKSPACE_DIR)) {
    return res.status(403).json({ success: false, error: 'Access denied' });
  }

  try {
    fs.mkdirSync(path.dirname(safePath), { recursive: true });
    fs.writeFileSync(safePath, content || '', 'utf-8');
    res.json({ success: true });
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

// Create new file or folder
app.post('/api/files/create', (req, res) => {
  const { relativePath, type } = req.body;
  if (!relativePath) return res.status(400).json({ success: false, error: 'Path is required' });

  const safePath = path.join(WORKSPACE_DIR, relativePath);
  if (!safePath.startsWith(WORKSPACE_DIR)) {
    return res.status(403).json({ success: false, error: 'Access denied' });
  }

  try {
    if (fs.existsSync(safePath)) {
      return res.status(400).json({ success: false, error: 'Path already exists' });
    }

    if (type === 'directory') {
      fs.mkdirSync(safePath, { recursive: true });
    } else {
      fs.mkdirSync(path.dirname(safePath), { recursive: true });
      fs.writeFileSync(safePath, '', 'utf-8');
    }
    res.json({ success: true });
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

// Delete file or folder
app.post('/api/files/delete', (req, res) => {
  const { relativePath } = req.body;
  if (!relativePath) return res.status(400).json({ success: false, error: 'Path is required' });

  const safePath = path.join(WORKSPACE_DIR, relativePath);
  if (!safePath.startsWith(WORKSPACE_DIR)) {
    return res.status(403).json({ success: false, error: 'Access denied' });
  }

  try {
    if (fs.existsSync(safePath)) {
      const stat = fs.statSync(safePath);
      if (stat.isDirectory()) {
        fs.rmSync(safePath, { recursive: true, force: true });
      } else {
        fs.unlinkSync(safePath);
      }
      res.json({ success: true });
    } else {
      res.status(404).json({ success: false, error: 'Not found' });
    }
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

// --- CODE EXECUTION RUNNERS ---

// Helper function to run code process with a timeout
function executeProcess(cmd, args, options, timeoutMs = 12000) {
  return new Promise((resolve) => {
    const startTime = Date.now();
    let stdout = '';
    let stderr = '';
    let killedDueToTimeout = false;

    const child = spawn(cmd, args, options);

    const timer = setTimeout(() => {
      killedDueToTimeout = true;
      child.kill('SIGKILL');
    }, timeoutMs);

    child.stdout.on('data', (data) => {
      stdout += data.toString();
    });

    child.stderr.on('data', (data) => {
      stderr += data.toString();
    });

    child.on('close', (code) => {
      clearTimeout(timer);
      const executionTime = Date.now() - startTime;
      resolve({
        code: killedDueToTimeout ? null : code,
        stdout,
        stderr: killedDueToTimeout ? `${stderr}\nExecution timed out after ${timeoutMs / 1000}s.` : stderr,
        executionTime,
        timedOut: killedDueToTimeout
      });
    });

    child.on('error', (err) => {
      clearTimeout(timer);
      resolve({
        code: -1,
        stdout,
        stderr: `${stderr}\nFailed to start process: ${err.message}`,
        executionTime: Date.now() - startTime,
        timedOut: false
      });
    });
  });
}

// Python Runner
app.post('/api/run/python', async (req, res) => {
  const { code } = req.body;
  if (!code) return res.status(400).json({ success: false, error: 'No code provided' });

  const tempFile = path.join(PYTHON_RUNNER_DIR, `temp_${Date.now()}.py`);
  try {
    fs.writeFileSync(tempFile, code, 'utf-8');
    
    // Execute Python script
    const result = await executeProcess('python', [tempFile], { cwd: PYTHON_RUNNER_DIR });
    
    // Cleanup temp file
    if (fs.existsSync(tempFile)) fs.unlinkSync(tempFile);

    res.json({ success: true, result });
  } catch (err) {
    if (fs.existsSync(tempFile)) fs.unlinkSync(tempFile);
    res.status(500).json({ success: false, error: err.message });
  }
});

// C# Runner
app.post('/api/run/csharp', async (req, res) => {
  const { code } = req.body;
  if (!code) return res.status(400).json({ success: false, error: 'No code provided' });

  // Make sure template initialized
  initCSharpProject();

  const programFile = path.join(CSHARP_RUNNER_DIR, 'Program.cs');
  try {
    fs.writeFileSync(programFile, code, 'utf-8');

    // Run using dotnet run inside the runner dir
    // We run with --no-restore to speed it up (since we created it and we won't add dependencies dynamically)
    const result = await executeProcess('dotnet', ['run', '--project', '.', '--no-restore'], { cwd: CSHARP_RUNNER_DIR });

    res.json({ success: true, result });
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

// Serve local files for Web Preview and inject console.log override for HTML files
app.get('/workspace/*', (req, res) => {
  const relPath = req.params[0];
  const safePath = path.join(WORKSPACE_DIR, relPath);
  
  if (!safePath.startsWith(WORKSPACE_DIR)) {
    return res.status(403).send('Access Denied');
  }

  try {
    if (fs.existsSync(safePath)) {
      const stat = fs.statSync(safePath);
      if (stat.isDirectory()) {
        return res.status(400).send('Cannot render directory directly');
      }

      const ext = path.extname(safePath).toLowerCase();
      if (ext === '.html') {
        let htmlContent = fs.readFileSync(safePath, 'utf-8');
        
        // Console interceptor script
        const interceptor = `
          <script>
            (function() {
              const originalLog = console.log;
              const originalError = console.error;
              const originalWarn = console.warn;
              const originalInfo = console.info;

              function sendLog(type, args) {
                window.parent.postMessage({
                  source: 'aether-iframe-console',
                  type: type,
                  args: Array.from(args).map(arg => {
                    if (arg instanceof Error) return arg.message + "\\n" + arg.stack;
                    if (typeof arg === 'object') {
                      try { return JSON.stringify(arg); } catch(e) { return String(arg); }
                    }
                    return String(arg);
                  })
                }, '*');
              }

              console.log = function() {
                sendLog('log', arguments);
                originalLog.apply(console, arguments);
              };
              console.error = function() {
                sendLog('error', arguments);
                originalError.apply(console, arguments);
              };
              console.warn = function() {
                sendLog('warn', arguments);
                originalWarn.apply(console, arguments);
              };
              console.info = function() {
                sendLog('info', arguments);
                originalInfo.apply(console, arguments);
              };

              window.addEventListener('error', function(e) {
                sendLog('error', [e.message + " at " + e.filename + ":" + e.lineno + ":" + e.colno]);
              });
            })();
          </script>
        `;
        
        // Inject script inside <head> if possible, otherwise at the top
        if (htmlContent.includes('<head>')) {
          htmlContent = htmlContent.replace('<head>', '<head>' + interceptor);
        } else {
          htmlContent = interceptor + htmlContent;
        }

        res.setHeader('Content-Type', 'text/html');
        return res.send(htmlContent);
      } else {
        return res.sendFile(safePath);
      }
    } else {
      res.status(404).send('File not found');
    }
  } catch (err) {
    res.status(500).send('Error serving file: ' + err.message);
  }
});

// Start Server
app.listen(PORT, '127.0.0.1', () => {
  console.log(`AetherIDE Server is running on http://127.0.0.1:${PORT}`);
});

