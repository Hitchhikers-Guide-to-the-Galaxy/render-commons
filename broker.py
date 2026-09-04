#!/usr/bin/env python3
"""broker.py — the smallest Render Capsule gateway. Standard library only.

Runs on the Air, bound to its tailnet address. Workers poll OUTWARD; the
broker never connects to a worker.

    python3 broker.py serve --bind <broker-tailnet-address> --port 4290 [--root broker/]
    python3 broker.py enqueue <job-id> --capsule FILE --payload FILE1 FILE2 ...   # signs with the dispatch key

Layout under --root:
    queue/<job-id>/capsule.json       the Render Capsule (render-job contract)
    queue/<job-id>/capsule.sig        OpenSSH signature of capsule.json, namespace hhrc-capsule
    queue/<job-id>/payload.tar.gz     world, patches, rights manifest: DATA ONLY, never code
    results/<job-id>/                 what a worker returned: receipt.json, receipt.sig, manifest, frames tar
    log.jsonl                         every request, one line each

HTTP:
    GET  /jobs                         -> {"jobs": [{"job_id", "dispatch_class", "expires_at", "done"}]}
    GET  /jobs/<id>/capsule.json | capsule.sig | payload.tar.gz
    POST /jobs/<id>/result             multipart-free: body is a tar.gz; headers X-Worker-Id, X-Receipt-Sha256
"""
import argparse, json, os, sys, subprocess, tarfile, io, time, hashlib, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE / "broker"
KEY = Path(os.path.expanduser("~/.ssh/hhrc-dispatch"))
NS = "hhrc-capsule"

def log(root, **kw):
    kw["ts"] = datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")
    with open(root / "log.jsonl", "a") as f: f.write(json.dumps(kw) + "\n")

def sign(path):
    subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(KEY), "-n", NS, str(path)], check=True, capture_output=True)
    return path.with_suffix(path.suffix + ".sig")

def enqueue(a):
    root = Path(a.root); d = root / "queue" / a.job; d.mkdir(parents=True, exist_ok=True)
    cap = json.load(open(a.capsule)); assert cap["job_id"] == a.job, "capsule job_id must match"
    cp = d / "capsule.json"; json.dump(cap, open(cp, "w"), indent=1, sort_keys=True)
    sign(cp).rename(d / "capsule.sig")   # ssh-keygen writes capsule.json.sig
    with tarfile.open(d / "payload.tar.gz", "w:gz") as t:
        for f in a.payload: t.add(f, arcname=Path(f).name)
    log(root, event="enqueue", job=a.job, files=[Path(f).name for f in a.payload])
    print("enqueued", d)

class H(BaseHTTPRequestHandler):
    root = ROOT
    def _send(self, code, body=b"", ctype="application/octet-stream"):
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        parts = self.path.strip("/").split("/")
        if parts == ["jobs"]:
            jobs = []
            for d in sorted((self.root / "queue").glob("*")):
                cap = json.load(open(d / "capsule.json"))
                jobs.append({"job_id": d.name, "dispatch_class": cap["dispatch_class"], "expires_at": cap["expires_at"],
                             "done": (self.root / "results" / d.name / "receipt.json").exists()})
            log(self.root, event="list", client=self.client_address[0]); return self._send(200, json.dumps({"jobs": jobs}).encode(), "application/json")
        if len(parts) == 3 and parts[0] == "jobs" and parts[2] in ("capsule.json", "capsule.sig", "payload.tar.gz"):
            f = self.root / "queue" / parts[1] / parts[2]
            if not f.exists(): return self._send(404)
            log(self.root, event="get", job=parts[1], file=parts[2], client=self.client_address[0], bytes=f.stat().st_size)
            return self._send(200, f.read_bytes())
        return self._send(404)
    def do_POST(self):
        parts = self.path.strip("/").split("/")
        if len(parts) == 3 and parts[0] == "jobs" and parts[2] == "result":
            n = int(self.headers.get("Content-Length", "0")); body = self.rfile.read(n)
            out = self.root / "results" / parts[1]; out.mkdir(parents=True, exist_ok=True)
            (out / "result.tar.gz").write_bytes(body)
            with tarfile.open(fileobj=io.BytesIO(body), mode="r:gz") as t:
                for m in t.getmembers():
                    if m.name.startswith("/") or ".." in m.name: return self._send(400)
                t.extractall(out, filter="data")
            log(self.root, event="result", job=parts[1], worker=self.headers.get("X-Worker-Id"), bytes=n, client=self.client_address[0])
            return self._send(200, b'{"ok":true}', "application/json")
        return self._send(404)
    def log_message(self, *a): pass

def serve(a):
    H.root = Path(a.root); (H.root / "queue").mkdir(parents=True, exist_ok=True); (H.root / "results").mkdir(exist_ok=True)
    srv = ThreadingHTTPServer((a.bind, a.port), H); print(f"broker on http://{a.bind}:{a.port}  root {H.root}", flush=True); srv.serve_forever()

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve"); s.add_argument("--bind", default="127.0.0.1"); s.add_argument("--port", type=int, default=4290); s.add_argument("--root", default=str(ROOT))
    e = sub.add_parser("enqueue"); e.add_argument("job"); e.add_argument("--capsule", required=True); e.add_argument("--payload", nargs="+", required=True); e.add_argument("--root", default=str(ROOT))
    a = ap.parse_args(); {"serve": serve, "enqueue": enqueue}[a.cmd](a)
