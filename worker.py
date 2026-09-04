#!/usr/bin/env python3
"""worker.py — a render-only worker for the Hitchhiker Render Commons. Standard library only.

Polls a broker OUTWARD over HTTP, needs no inbound port, and will only:
  1. take a capsule whose OpenSSH signature verifies against its allowed_signers file;
  2. take a capsule whose dispatch_class is in its --accept list;
  3. take a capsule whose generator_commit equals the sha256 of the compile_world.py it already has
     (the capsule never carries code; the payload is world, patches and rights manifests: data);
  4. run ONE fixed Blender command, headless, with automatic script execution disabled (-Y),
     arguments derived only from the capsule;
  5. return frames, its scene manifest and a receipt it signs with its own key.

    python3 worker.py --broker http://<broker-tailnet-address>:4290 --worker-id mini-m1-8gb --accept trusted --once
"""
import argparse, json, os, sys, subprocess, tarfile, io, time, hashlib, platform, datetime, urllib.request, shutil, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
BLENDER = os.environ.get("BLENDER", "/opt/homebrew/bin/blender")
ALLOWED = Path(os.path.expanduser("~/.ssh/hhrc-allowed-signers"))
WKEY = Path(os.path.expanduser("~/.ssh/hhrc-worker"))
now = lambda: datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""): h.update(chunk)
    return "sha256:" + h.hexdigest()

def get(url):
    with urllib.request.urlopen(url, timeout=120) as r: return r.read()

def verify_sig(data_path, sig_path, namespace="hhrc-capsule"):
    # any principal in the allowed_signers file may dispatch; the principal name is recorded
    for line in ALLOWED.read_text().splitlines():
        if not line.strip() or line.startswith("#"): continue
        principal = line.split()[0]
        r = subprocess.run(["ssh-keygen", "-Y", "verify", "-f", str(ALLOWED), "-I", principal, "-n", namespace, "-s", str(sig_path)],
                           stdin=open(data_path, "rb"), capture_output=True, text=True)
        if r.returncode == 0: return principal
    return None

def capabilities(worker_id):
    return {"worker_id": worker_id, "os": "macos", "architecture": "arm64",
            "gpu": {"vendor": "Apple", "model": platform.processor() or "Apple M1", "memory_bytes": 8589934592},
            "blender_versions": [subprocess.run([BLENDER, "--version"], capture_output=True, text=True).stdout.split("\n")[0].split()[1]],
            "engines": ["BLENDER_EEVEE"],
            "limits": {"max_width": 1920, "max_height": 1080, "max_job_seconds": 3600, "max_download_bytes": 200_000_000, "max_cache_bytes": 2_000_000_000},
            "content_namespaces": ["earth2"], "energy_metering": "estimated", "schedule": "any", "outward_polling_only": True}

def run_job(a, job):
    jid = job["job_id"]; work = Path(tempfile.mkdtemp(prefix=f"hhrc-{jid}-")); out = work / "out"; out.mkdir()
    cap_b = get(f"{a.broker}/jobs/{jid}/capsule.json"); sig_b = get(f"{a.broker}/jobs/{jid}/capsule.sig"); pay_b = get(f"{a.broker}/jobs/{jid}/payload.tar.gz")
    (work / "capsule.json").write_bytes(cap_b); (work / "capsule.sig").write_bytes(sig_b); (work / "payload.tar.gz").write_bytes(pay_b)
    downloaded = len(cap_b) + len(sig_b) + len(pay_b)
    cap = json.loads(cap_b); refusals = []
    signer = verify_sig(work / "capsule.json", work / "capsule.sig")
    if signer is None: refusals.append("signature does not verify against allowed signers")
    if cap["dispatch_class"] not in a.accept: refusals.append(f"dispatch class {cap['dispatch_class']} not accepted (accepts {a.accept})")
    gen = hashlib.sha256((HERE / "compile_world.py").read_bytes()).hexdigest()
    if cap["generator_commit"] != gen: refusals.append(f"generator {cap['generator_commit'][:12]} is not the installed {gen[:12]}")
    if cap["engine"] != "BLENDER_EEVEE": refusals.append(f"engine {cap['engine']} not offered")
    if datetime.datetime.fromisoformat(cap["expires_at"].replace("Z", "+00:00")) < datetime.datetime.now(datetime.UTC): refusals.append("capsule expired")
    caps = capabilities(a.worker_id)
    if cap["resolution"][0] > caps["limits"]["max_width"] or cap["resolution"][1] > caps["limits"]["max_height"]: refusals.append("resolution over limit")
    if refusals:
        print("REFUSED", jid, refusals); return {"job_id": jid, "status": "refused", "refusals": refusals, "signer": signer}
    with tarfile.open(work / "payload.tar.gz") as t:
        for m in t.getmembers():
            if m.name.startswith("/") or ".." in m.name or not m.name.endswith(".json"): raise SystemExit("payload may carry only json data")
        t.extractall(work, filter="data")
    # the fixed command: arguments come from the capsule, never from the payload's contents
    world = work / "minimal-world.json"; patches = ",".join(str(p) for p in sorted(work.glob("world-patch-*.json")))   # ledger: the capsule should list its patches
    rights = work / f"{cap['rights_manifest_id']}.json"
    f0, f1 = cap["frames"]; nframes = f1 - f0 + 1
    cmd = [BLENDER, "-b", "-Y", "--python", str(HERE / "compile_world.py"), "--",
           "--world", str(world), "--patch", patches, "--seed", str(cap["seed"]), "--out", str(out),
           "--res", f"{cap['resolution'][0]}x{cap['resolution'][1]}", "--samples", "16", "--rights", str(rights), "--camera", cap["camera_journey"], "--journey", str(nframes)]
    t0 = time.time(); r = subprocess.run(cmd, capture_output=True, text=True); wall = time.time() - t0
    line = [l for l in r.stdout.splitlines() if l.startswith("COMPILED")]
    if r.returncode or not line: print(r.stdout[-1500:], r.stderr[-1500:]); return {"job_id": jid, "status": "failed"}
    timing = json.load(open(out / f"timing-seed{cap['seed']}-journey{nframes}.json")); man = json.load(open(out / f"scene-manifest-seed{cap['seed']}.json"))
    # frames -> one mp4 (ffmpeg if present) and the PNGs kept for verification of a sample
    frames_dir = out / f"journey-seed{cap['seed']}"; pngs = sorted(frames_dir.glob("frame-*.png"))
    if shutil.which("ffmpeg"):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(cap.get("fps", 24)), "-i", str(frames_dir / "frame-%04d.png"),
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-movflags", "+faststart", str(out / f"journey-{jid}.mp4")], check=True)
    outputs = [{"path": p.name, "hash": sha256(p), "bytes": p.stat().st_size} for p in sorted(out.glob("*.mp4"))] + \
              [{"path": f"frames/{p.name}", "hash": sha256(p), "bytes": p.stat().st_size} for p in pngs]
    load = os.getloadavg()
    rec = {"receipt_id": f"{jid}-receipt-{a.worker_id}", "job_id": jid, "worker_id": a.worker_id,
           "worker_capability_hash": "sha256:" + hashlib.sha256(json.dumps(caps, sort_keys=True).encode()).hexdigest(),
           "started_at": datetime.datetime.fromtimestamp(t0, datetime.UTC).isoformat().replace("+00:00", "Z"), "completed_at": now(),
           "wall_seconds": round(wall, 3), "render_seconds": timing["render_seconds"], "blender_version": timing["blender"],
           "seed": cap["seed"], "world_spec_hash": cap["world_spec_hash"], "engine": "BLENDER_EEVEE", "scene_manifest_hash": man["scene_manifest_hash"],
           "energy": {"watt_hours": round(10.0 * wall / 3600, 4), "method": "estimated", "meter": "assumed 10 W package draw on an M1 Mac mini; no per-process meter"},
           "outputs": outputs, "validation": man["validation"], "status": "completed",
           "warnings": [f"load average at start {load[0]:.2f}: this Mini also runs the radio and the farms", "energy is an estimate", "pixels not asserted reproducible across GPUs; the scene manifest hash is",
                        f"capsule signed by {signer}; downloaded {downloaded} bytes"]}
    rp = out / "receipt.json"; json.dump(rec, open(rp, "w"), indent=1, sort_keys=True)
    subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(WKEY), "-n", "hhrc-receipt", str(rp)], check=True, capture_output=True)
    (out / "receipt.json.sig").rename(out / "receipt.sig")
    json.dump(caps, open(out / "capabilities.json", "w"), indent=1)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for name in ["receipt.json", "receipt.sig", "capabilities.json", f"scene-manifest-seed{cap['seed']}.json"]: t.add(out / name, arcname=name)
        for p in sorted(out.glob("*.mp4")): t.add(p, arcname=p.name)
        for p in pngs: t.add(p, arcname=f"frames/{p.name}")
    body = buf.getvalue()
    req = urllib.request.Request(f"{a.broker}/jobs/{jid}/result", data=body, method="POST",
                                 headers={"Content-Type": "application/gzip", "X-Worker-Id": a.worker_id, "X-Receipt-Sha256": sha256(rp)})
    with urllib.request.urlopen(req, timeout=600) as r: ok = r.status == 200
    print("DONE", jid, "wall", round(wall, 1), "s, uploaded", len(body), "bytes, downloaded", downloaded, "bytes, signer", signer, "manifest", man["scene_manifest_hash"][:23])
    if not a.keep: shutil.rmtree(work)
    return {"job_id": jid, "status": "completed", "uploaded": len(body), "downloaded": downloaded, "wall": wall}

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--broker", required=True); ap.add_argument("--worker-id", default=platform.node())
    ap.add_argument("--accept", nargs="+", default=["public"]); ap.add_argument("--once", action="store_true"); ap.add_argument("--poll", type=int, default=30); ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()
    while True:
        jobs = json.loads(get(f"{a.broker}/jobs"))["jobs"]
        todo = [j for j in jobs if not j["done"]]
        for j in todo: run_job(a, j)
        if a.once: break
        time.sleep(a.poll)

if __name__ == "__main__":
    main()
