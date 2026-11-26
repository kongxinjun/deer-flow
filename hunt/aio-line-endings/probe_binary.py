import httpx, base64
c = httpx.Client(base_url="http://localhost:18080", timeout=60, trust_env=False)
c.post("/v1/file/write", json={"file": "/tmp/t/a.bin", "content": base64.b64encode(b"\xafI~m\xd3").decode(), "encoding": "base64"})
print(c.get("/v1/file/download", params={"path": "/tmp/t/a.bin"}).content)
r = c.post("/v1/file/read", json={"file": "/tmp/t/a.bin"}); print("read binary:", r.status_code, r.text[:200])
r = c.post("/v1/file/read", json={"file": "/tmp/t/missing"}); print("read missing:", r.status_code, r.text[:200])
r = c.post("/v1/file/read", json={"file": "/tmp/t"}); print("read dir:", r.status_code, r.text[:200])
