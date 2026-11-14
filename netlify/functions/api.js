// Netlify Function wrapper for Python FastAPI backend via mangum
// This JS shim invokes the Python handler as a subprocess because
// Netlify Functions natively support Node.js, not Python directly.

const { spawnSync } = require('child_process');
const path = require('path');

exports.handler = async (event) => {
  const projectRoot = path.resolve(__dirname, '..', '..');
  const pythonScript = path.join(projectRoot, 'netlify', 'functions', '_invoke_handler.py');

  // Pass the Lambda event as JSON via stdin
  const result = spawnSync(
    process.env.PYTHON_PATH || 'python3',
    [pythonScript],
    {
      input: JSON.stringify(event),
      encoding: 'utf-8',
      timeout: 25000, // Netlify Functions have 26s max
      cwd: projectRoot,
      env: {
        ...process.env,
        PYTHONPATH: projectRoot,
        JHC_DATA_ROOT: path.join(projectRoot, 'data'),
      },
    }
  );

  if (result.error) {
    return {
      statusCode: 500,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ error: 'Python invocation failed', detail: result.error.message }),
    };
  }

  if (result.status !== 0) {
    return {
      statusCode: 500,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        error: 'Python handler error',
        stderr: (result.stderr || '').substring(0, 500),
      }),
    };
  }

  try {
    const response = JSON.parse(result.stdout);
    return {
      statusCode: response.statusCode || 200,
      headers: response.headers || { 'Content-Type': 'application/json' },
      body: response.body || '',
      isBase64Encoded: response.isBase64Encoded || false,
    };
  } catch (e) {
    return {
      statusCode: 500,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ error: 'Failed to parse Python response', raw: (result.stdout || '').substring(0, 300) }),
    };
  }
};