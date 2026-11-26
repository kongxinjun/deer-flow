import httpx
import sys
B = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:18080"
c=httpx.Client(base_url=B, timeout=60, trust_env=False)
r=c.post("/v1/file/write", json={"file":"/tmp/t/a.txt","content":"a\r\nb\rc\n"}); print("write", r.status_code, r.headers.get("content-type"), r.text[:300])
r=c.get("/v1/file/download", params={"path":"/tmp/t/a.txt"}); print("download", r.status_code, dict(r.headers), r.content)
r=c.post("/v1/file/read", json={"file":"/tmp/t/a.txt"}); print("read", r.status_code, r.text[:300])
r=c.get("/v1/file/download", params={"path":"/tmp/t/missing.txt"}); print("missing", r.status_code, dict(r.headers), r.text[:300])
r=c.get("/v1/file/download", params={"path":"/tmp/t"}); print("dir", r.status_code, r.headers.get("content-type"), r.text[:300])
r=c.post("/v1/file/write", json={"file":"/tmp/t","content":"x"}); print("write-dir", r.status_code, r.text[:300])
