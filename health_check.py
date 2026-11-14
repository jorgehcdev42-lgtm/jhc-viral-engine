#!/usr/bin/env python3
"""Health check via raw socket — no external dependencies."""
import socket
import json
import sys

HOST = "127.0.0.1"
PORT = 8765

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(5)
try:
    s.connect((HOST, PORT))
    request = f"GET /api/health HTTP/1.1\r\nHost: {HOST}:{PORT}\r\nConnection: close\r\n\r\n"
    s.sendall(request.encode())
    response = b""
    while True:
        chunk = s.recv(4096)
        if not chunk:
            break
        response += chunk
    s.close()
    body = response.split(b"\r\n\r\n", 1)[1] if b"\r\n\r\n" in response else response
    data = json.loads(body.decode())
    print("OK")
    print(json.dumps(data, indent=2))
except Exception as e:
    print(f"FAIL:{e}")
    sys.exit(1)