#!/bin/bash
# run_demo.sh — the Three Cells Demo, end to end, on the Air. One Blender process per render call.
set -e
cd "$(dirname "$0")"
rm -rf out out2; mkdir -p out out2
echo "== stills (seeds 42 43 44, frame 120, 960x540, 16 samples)"
for s in 42 43 44; do python3 hhrc.py compile --seed $s --still 120 | grep COMPILED; done
python3 hhrc.py sheet --frame 120 | tail -1
echo "== determinism: seed 42 again into out2"
python3 hhrc.py compile --seed 42 --still 120 --out out2 | grep COMPILED
python3 - <<'PY'
import json
a=json.load(open('out/scene-manifest-seed42.json'))['scene_manifest_hash']; b=json.load(open('out2/scene-manifest-seed42.json'))['scene_manifest_hash']
print('DETERMINISM', 'SAME' if a==b else 'DIFFERENT', a[:23], b[:23])
PY
echo "== journey: seed 42, 240 frames, 1920x1080, 24 fps, 16 samples (the Phase 1 number)"
python3 hhrc.py compile --seed 42 --journey 240 --res 1920x1080 | grep -E 'COMPILED|wall'
ffmpeg -y -loglevel error -framerate 24 -i out/journey-seed42/frame-%04d.png -c:v libx264 -pix_fmt yuv420p -crf 20 -movflags +faststart out/journey-seed42-240f.mp4
ls -la out/journey-seed42-240f.mp4 && rm -rf out/journey-seed42
echo "== capsule + receipts"
python3 hhrc.py capsule --seed 42 --frames 1 240 | tail -2
python3 hhrc.py receipt --seed 42 --timing out/timing-seed42-still120.json --capsule out/render-capsule-seed42.json | tail -2
python3 hhrc.py receipt --seed 42 --timing out/timing-seed42-journey240.json --capsule out/render-capsule-seed42.json | tail -2
for r in out/render-receipt-seed42-*.json; do python3 hhrc.py verify $r | tail -1; done
ls -la out/
echo DEMO-DONE
