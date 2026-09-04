#!/usr/bin/env python3
"""hhrc — Hitchhiker Render Commons, the first rung (Three Cells Demo).

    hhrc.py validate <file> [--schema NAME]      # jsonschema 2020-12 against contracts/
    hhrc.py compile  --seed N [--still F | --journey N] [--res WxH] [--samples S] [--out DIR]
    hhrc.py sheet    --out DIR --seeds 42 43 44 --frame F   # contact sheet PNG
    hhrc.py capsule  --out DIR --seed N --frames A B          # write a Render Capsule (render-job) JSON
    hhrc.py receipt  --out DIR --seed N --timing FILE --capsule FILE   # write + validate a Render Receipt
    hhrc.py verify   <receipt.json> --out DIR                  # re-hash outputs named in a receipt

Runs on the Air with system Python 3.12 (jsonschema, PIL). Blender is called
as a subprocess for `compile` (one process per render call — see compile_world.py).
"""
import argparse, json, os, sys, subprocess, hashlib, time, platform, socket, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONTRACTS = HERE / "contracts"; FIXTURES = HERE / "fixtures"
BLENDER = os.environ.get("BLENDER", "/opt/homebrew/bin/blender")
WORLD = FIXTURES / "minimal-world.json"; PATCH = FIXTURES / "world-patch-seed-42.json"
RIGHTS = FIXTURES / "rights-earth2-fixture-001.json"

def canonical_hash(doc):
    return "sha256:" + hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""): h.update(chunk)
    return "sha256:" + h.hexdigest()

def schema_for(doc, name=None):
    if name: return CONTRACTS / f"{name}.schema.json"
    keys = set(doc)
    if "cells" in keys: return CONTRACTS / "world.schema.json"
    if "operations" in keys: return CONTRACTS / "world-patch.schema.json"
    if "receipt_id" in keys: return CONTRACTS / "render-receipt.schema.json"
    if "job_id" in keys: return CONTRACTS / "render-job.schema.json"
    if "manifest_id" in keys: return CONTRACTS / "rights-manifest.schema.json"
    if "shot_id" in keys: return CONTRACTS / "shot-plan.schema.json"
    if "worker_id" in keys: return CONTRACTS / "worker-capabilities.schema.json"
    raise SystemExit("cannot infer schema; pass --schema")

def validate(path, name=None):
    from jsonschema import Draft202012Validator, FormatChecker
    doc = json.load(open(path)); sp = schema_for(doc, name)
    v = Draft202012Validator(json.load(open(sp)), format_checker=FormatChecker())
    errs = sorted(v.iter_errors(doc), key=lambda e: list(e.path))
    for e in errs: print(f"  {list(e.path)}: {e.message[:160]}")
    print(f"{Path(path).name} vs {sp.name}: {'VALID' if not errs else str(len(errs)) + ' ERRORS'}")
    return not errs

def compile_(a):
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    for f in (WORLD, PATCH):
        if not validate(f): raise SystemExit("fixture invalid; refusing to compile")
    patches = [FIXTURES / p for p in a.patches] if a.patches else [PATCH]
    for f in patches:
        if not validate(f): raise SystemExit("patch invalid; refusing to compile")
    cmd = [BLENDER, "-b", "--python", str(HERE / "compile_world.py"), "--",
           "--world", str(WORLD), "--patch", ",".join(str(p) for p in patches), "--seed", str(a.seed), "--out", str(out),
           "--res", a.res, "--samples", str(a.samples), "--rights", str(FIXTURES / a.rights), "--camera", a.camera] + (["--shot", str(FIXTURES / a.shot)] if a.shot else [])
    if a.still: cmd += ["--still", str(a.still)]
    if a.journey: cmd += ["--journey", str(a.journey)]
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True)
    line = [l for l in r.stdout.splitlines() if l.startswith("COMPILED")]
    print(line[0] if line else r.stdout[-2000:] + r.stderr[-2000:])
    print(f"blender process wall {time.time() - t0:.1f} s")
    if r.returncode or not line: raise SystemExit("compile failed")

def sheet(a):
    from PIL import Image, ImageDraw, ImageFont
    out = Path(a.out); tiles = []
    frames = a.frames or [a.frame]
    for s in a.seeds:
        for fr in frames:
            p = out / f"still-seed{s}-f{fr:03d}.png"; tiles.append(((s, fr), Image.open(p).convert("RGB")))
    w, h = tiles[0][1].size; pad = 12; label = 34
    sheet_ = Image.new("RGB", (w * len(tiles) + pad * (len(tiles) + 1), h + label + pad * 2), (24, 24, 24))
    d = ImageDraw.Draw(sheet_)
    try: font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 22)
    except Exception: font = ImageFont.load_default()
    for i, (s, im) in enumerate(tiles):
        x = pad + i * (w + pad); sheet_.paste(im, (x, pad))
        d.text((x + 6, pad + h + 6), f"seed {s[0]} · frame {s[1]} · {w}x{h}", fill=(230, 230, 230), font=font)
    name = out / (f"contact-sheet-f{a.frame:03d}.png" if not a.frames else "contact-sheet-beats.png"); sheet_.save(name); print("wrote", name)

def capsule(a):
    out = Path(a.out); man = json.load(open(out / f"scene-manifest-seed{a.seed}.json"))
    rights = json.load(open(FIXTURES / a.rights))
    cap = {
        "job_id": f"three-cells-seed{a.seed}-{datetime.date.today().isoformat()}",
        "world_id": man["world_id"], "region": [c["id"] for c in json.load(open(WORLD))["cells"]],
        "world_spec_hash": sha256(WORLD), "generator_commit": hashlib.sha256(open(HERE / "compile_world.py", "rb").read()).hexdigest(),
        "blender_version": man["blender_version"].split()[0], "engine": "BLENDER_EEVEE", "seed": a.seed,
        "camera_journey": man.get("camera", "journey"), "frames": a.frames, "resolution": man["resolution"], "fps": 24,
        "assets": [{"hash": sha256(WORLD), "rights_item_id": rights["items"][0]["item_id"]}] + [
            {"hash": sha256(os.path.expanduser("~/Code/marvin-blender/assets/charge/huginn_v2/huginn_release_v2.blend")), "rights_item_id": c["rights_item_id"]}
            for c in man.get("characters", [])] + ([{"hash": sha256(HERE / "assets" / "marvin" / "marvin-stand.png"), "rights_item_id": man["performer"]["rights_item_id"]}] if man.get("performer") else []),
        "rights_manifest_id": rights["manifest_id"], "validation_profile": "three-cells-0.1",
        "dispatch_class": "private", "expires_at": (datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=30)).isoformat().replace("+00:00", "Z"),
    }
    # public dispatch is gated by the rights record, not by the schema (Draft Contracts ambiguity 5)
    pub = all(i["human_verified"] and i["permissions"]["public_distribution"] for i in rights["items"])
    cap["dispatch_class"] = "public" if pub else ("trusted" if a.dispatch == "trusted" else "private")
    if a.job: cap["job_id"] = a.job
    p = out / f"render-capsule-seed{a.seed}.json"; json.dump(cap, open(p, "w"), indent=1); validate(p); print("wrote", p)

def receipt(a):
    out = Path(a.out); tm = json.load(open(a.timing)); cap = json.load(open(a.capsule)); man = json.load(open(out / f"scene-manifest-seed{a.seed}.json"))
    outputs = [{"path": f.name, "hash": sha256(f), "bytes": f.stat().st_size}
               for f in sorted(out.iterdir()) if f.suffix in (".png", ".mp4") and f"seed{a.seed}" in f.name]
    wall = tm["wall_seconds"]; render = tm["render_seconds"]
    # energy: macOS has no per-process meter; estimate from an assumed 15 W package draw while rendering on the M2
    est_wh = round(15.0 * wall / 3600, 4)
    rec = {
        "receipt_id": f"{cap['job_id']}-receipt", "job_id": cap["job_id"],
        "worker_id": "air-m2-8gb", "worker_capability_hash": "sha256:" + hashlib.sha256(json.dumps({
            "os": "macos", "arch": platform.machine(), "cpu": "Apple M2", "memory_bytes": 8589934592,
            "blender": tm["blender"], "engines": ["BLENDER_EEVEE"]}, sort_keys=True).encode()).hexdigest(),
        "started_at": datetime.datetime.fromtimestamp(Path(a.timing).stat().st_mtime - wall, datetime.UTC).isoformat().replace("+00:00", "Z"),
        "completed_at": datetime.datetime.fromtimestamp(Path(a.timing).stat().st_mtime, datetime.UTC).isoformat().replace("+00:00", "Z"),
        "wall_seconds": wall, "render_seconds": render, "blender_version": tm["blender"],
        "seed": a.seed, "world_spec_hash": cap["world_spec_hash"], "engine": "BLENDER_EEVEE",
        "scene_manifest_hash": man["scene_manifest_hash"],
        "energy": {"watt_hours": est_wh, "method": "estimated", "meter": "assumed 15 W package draw on an M2 Air; powermetrics needs root"},
        "outputs": outputs, "validation": man["validation"], "status": "completed",
        "warnings": ["energy is an estimate, not a measurement", "pixels are not asserted reproducible across GPUs; the scene manifest hash is"],
    }
    p = out / f"render-receipt-seed{a.seed}-{Path(a.timing).stem.split('-')[-1]}.json"
    json.dump(rec, open(p, "w"), indent=1); validate(p); print("wrote", p)

def hash_world(a):
    """Canonical hash of the world after applying the named patches, for a new patch's parent_world_hash."""
    w = json.load(open(WORLD))
    for name in a.patches:
        p = json.load(open(FIXTURES / name)); kinds = {"cell": "cells", "edge": "edges", "node": "nodes"}
        for op in p["operations"]:
            t = w if op["target_kind"] == "world" else next(e for e in w[kinds[op["target_kind"]]] if e["id"] == op["target_id"])
            parts = [x for x in op["path"].split("/") if x]
            for x in parts[:-1]: t = t.setdefault(x, {})
            if op["op"] in ("add", "replace"): t[parts[-1]] = op["value"]
            else: t.pop(parts[-1], None)
    print(canonical_hash(w))

def verify(a):
    rec = json.load(open(a.receipt)); out = Path(a.out); ok = True
    for o in rec["outputs"]:
        h = sha256(out / o["path"]); good = h == o["hash"]; ok &= good
        print(f"  {'OK ' if good else 'BAD'} {o['path']} {h[:20]}…")
    print("receipt outputs", "VERIFIED" if ok else "MISMATCH")

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate"); v.add_argument("file"); v.add_argument("--schema")
    c = sub.add_parser("compile"); c.add_argument("--seed", type=int, default=42); c.add_argument("--still", type=int)
    c.add_argument("--journey", type=int); c.add_argument("--res", default="960x540"); c.add_argument("--samples", type=int, default=16)
    c.add_argument("--out", default=str(HERE / "out")); c.add_argument("--patches", nargs="*", help="fixture patch files, applied in order")
    c.add_argument("--rights", default="rights-earth2-fixture-001.json"); c.add_argument("--camera", default="journey"); c.add_argument("--shot", help="fixture shot plan file")
    s = sub.add_parser("sheet"); s.add_argument("--out", default=str(HERE / "out")); s.add_argument("--seeds", type=int, nargs="+", default=[42, 43, 44]); s.add_argument("--frame", type=int, default=120); s.add_argument("--frames", type=int, nargs="*", help="beat frames of one seed")
    k = sub.add_parser("capsule"); k.add_argument("--out", default=str(HERE / "out")); k.add_argument("--seed", type=int, default=42); k.add_argument("--frames", type=int, nargs=2, default=[1, 240]); k.add_argument("--rights", default="rights-earth2-fixture-001.json"); k.add_argument("--dispatch", default="private", choices=["private", "trusted"]); k.add_argument("--job")
    h = sub.add_parser("hash-world"); h.add_argument("--patches", nargs="*", default=[])
    r = sub.add_parser("receipt"); r.add_argument("--out", default=str(HERE / "out")); r.add_argument("--seed", type=int, default=42); r.add_argument("--timing", required=True); r.add_argument("--capsule", required=True)
    w = sub.add_parser("verify"); w.add_argument("receipt"); w.add_argument("--out", default=str(HERE / "out"))
    a = ap.parse_args()
    {"validate": lambda: validate(a.file, a.schema), "compile": lambda: compile_(a), "sheet": lambda: sheet(a),
     "capsule": lambda: capsule(a), "receipt": lambda: receipt(a), "verify": lambda: verify(a), "hash-world": lambda: hash_world(a)}[a.cmd]()

if __name__ == "__main__":
    main()
