"""An offline AIO sandbox: the real AioSandbox and agent_sandbox SDK over an httpx MockTransport.

The routes reproduce what AIO 1.11.0 (ghcr.io/agent-infra/sandbox) does, as
recorded with probe_routes.py:

- GET  /v1/file/download?path=  streams the stored bytes (application/octet-stream);
  404 {"success": false, "message": "File does not exist: ..."} for a missing path,
  400 "Path is not a file" for a directory. No server-side size limit; DeerFlow
  enforces 100 MB while streaming.
- POST /v1/file/write  stores the JSON "content" as given ("\\r" kept);
  "encoding": "base64" stores the decoded bytes; "append" appends.
- POST /v1/file/read  returns the text with "\\r\\n" and "\\r" turned into "\\n".

Usage:
    from offline_aio import offline_aio_sandbox
    with offline_aio_sandbox() as (sandbox, routes):
        routes.files["/mnt/user-data/outputs/f.txt"] = b"a\\r\\nb\\n"
        ...   # sandbox.read_file(...), or the real tools (bind_tools(sandbox))
"""

from __future__ import annotations

import base64
import contextlib
import json
from collections.abc import Iterator

import httpx


class AioFileRoutes:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.streams: dict[str, Iterator[bytes]] = {}  # one-shot chunked bodies
        self.failures: dict[str, type[httpx.TransportError]] = {}
        self.routes: list[str] = []

    @staticmethod
    def _envelope(status: int, message: str, data=None) -> httpx.Response:
        return httpx.Response(status, json={"success": status == 200, "message": message, "data": data, "hint": None})

    def __call__(self, request: httpx.Request) -> httpx.Response:
        route = request.url.path
        self.routes.append(route)
        if route == "/v1/file/download":
            path = request.url.params["path"]
            if path in self.failures:
                raise self.failures[path]("connection reset", request=request)
            if path in self.streams:
                return httpx.Response(200, headers={"content-type": "application/octet-stream"}, content=self.streams.pop(path))
            if path in self.files:
                return httpx.Response(200, headers={"content-type": "application/octet-stream"}, content=self.files[path])
            if any(name.startswith(path.rstrip("/") + "/") for name in self.files):
                return self._envelope(400, f"Path is not a file: {path}")
            return self._envelope(404, f"File does not exist: {path}")
        body = json.loads(request.content)
        if route == "/v1/file/write":
            data = base64.b64decode(body["content"]) if body.get("encoding") == "base64" else body["content"].encode("utf-8")
            self.files[body["file"]] = self.files.get(body["file"], b"") + data if body.get("append") else data
            return self._envelope(200, "File written successfully", {"file": body["file"], "bytes_written": len(data)})
        if route == "/v1/file/read":
            text = self.files[body["file"]].decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
            return self._envelope(200, "File read successfully", {"content": text, "file": body["file"]})
        return self._envelope(404, "Not Found")


@contextlib.contextmanager
def offline_aio_sandbox():
    import deerflow.community.aio_sandbox.aio_sandbox as aio_module
    from agent_sandbox import Sandbox as RealSdkClient

    routes = AioFileRoutes()
    client = httpx.Client(transport=httpx.MockTransport(routes), follow_redirects=True)
    original = aio_module.AioSandboxClient
    aio_module.AioSandboxClient = lambda **kwargs: RealSdkClient(**{**kwargs, "httpx_client": client})
    try:
        yield aio_module.AioSandbox(id="offline", base_url="http://localhost:8080"), routes
    finally:
        aio_module.AioSandboxClient = original
        client.close()


def bind_tools(sandbox):
    """Point the sandbox tools at ``sandbox``; returns a runtime to pass them."""
    from types import SimpleNamespace

    import deerflow.sandbox.tools as tools

    tools.ensure_sandbox_initialized = lambda runtime: sandbox
    tools.ensure_thread_directories_exist = lambda runtime: None
    tools.is_local_sandbox = lambda runtime: False
    return SimpleNamespace(state={"sandbox": {"sandbox_id": sandbox.id}}, context={"thread_id": "offline"})
