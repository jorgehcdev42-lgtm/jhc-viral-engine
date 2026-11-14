"""Python subprocess bridge for Netlify Functions.

Reads a Lambda-style event from stdin (JSON), invokes the mangum handler,
and writes the Lambda response to stdout (JSON). Called by api.js shim.

Normalizes both API Gateway v1 and v2 events, plus local test payloads.
"""

import json
import os
import sys
from pathlib import Path

# Ensure project root is on sys.path
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

# Set data root for the serverless environment
os.environ.setdefault("JHC_DATA_ROOT", str(project_root / "data"))

from netlify.functions.api import handler


def normalize_event(event: dict) -> dict:
    """Ensure the event has the minimum structure mangum expects."""
    # If it already looks like a proper Lambda event, pass through
    if "requestContext" in event:
        return event

    # Build a minimal API Gateway v1 event from simple HTTP fields
    method = event.get("httpMethod", event.get("method", "GET")).upper()
    path = event.get("path", event.get("url", "/"))
    headers = event.get("headers", {}) or {}
    body = event.get("body", "") or ""
    query_params = event.get("queryStringParameters") or {}

    return {
        "httpMethod": method,
        "path": path,
        "resource": path,
        "headers": headers,
        "multiValueHeaders": {k: [v] for k, v in headers.items()},
        "queryStringParameters": query_params if query_params else None,
        "multiValueQueryStringParameters": (
            {k: [v] for k, v in query_params.items()} if query_params else None
        ),
        "body": body if isinstance(body, str) else json.dumps(body),
        "isBase64Encoded": False,
        "requestContext": {
            "stage": "prod",
            "requestId": "local-test",
            "identity": {"sourceIp": "127.0.0.1"},
        },
        "pathParameters": {},
        "stageVariables": {},
    }


class LambdaContext:
    """Minimal Lambda context stub."""
    function_name = "jhc-viral-engine-api"
    memory_limit_in_mb = 256
    invoked_function_arn = ""
    aws_request_id = ""

    def get_remaining_time_in_millis(self):
        return 25000


def main():
    raw = sys.stdin.read()
    if not raw.strip():
        print(json.dumps({
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Empty request body"}),
        }))
        return

    try:
        event = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": f"Invalid JSON: {e}"}),
        }))
        return

    event = normalize_event(event)

    try:
        response = handler(event, LambdaContext())
    except Exception as e:
        response = {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": str(e)[:500]}),
        }

    print(json.dumps(response))


if __name__ == "__main__":
    main()