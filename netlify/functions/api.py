"""Netlify Function handler for JHC Viral Engine FastAPI backend.

Wraps the existing FastAPI app with mangum adapter so it runs as an
AWS Lambda function on Netlify Functions. This eliminates the need for
a separate Render backend — frontend and API are served from the same
Netlify site at https://jhc-viral-engine.netlify.app.

The /api/* redirect in netlify.toml routes all API calls to this function.
"""

import os
import sys
from pathlib import Path

# Add project root to path so src.* imports work
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

from mangum import Mangum

# Import the FastAPI app
from src.api.main import app

# Create the Lambda handler
handler = Mangum(app, lifespan="off")