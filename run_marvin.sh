#!/bin/bash
# run_marvin.sh — rung 2, Marvin Mock Journey, end to end on the Air.
set -e; cd "$(dirname "$0")"
P="--patches world-patch-seed-42.json --rights rights-three-cells-marvin-001.json --shot shot-marvin-road-001.json"
rm -rf out-marvin out-marvin2; mkdir -p out-marvin out-marvin2
echo "== beat stills, seed 42: frame 1 (walk), 90 (say), 180 (walk on)"
for f in 1 90 180; do python3 hhrc.py compile --seed 42 --still $f $P --out out-marvin | grep COMPILED; done
python3 hhrc.py sheet --out out-marvin --seeds 42 --frames 1 90 180 | tail -1
echo "== determinism: seed 42 again into out-marvin2"
python3 hhrc.py compile --seed 42 --still 90 $P --out out-marvin2 | grep COMPILED
python3 - <<'PY'
import json
a=json.load(open('out-marvin/scene-manifest-seed42.json'))['scene_manifest_hash']; b=json.load(open('out-marvin2/scene-manifest-seed42.json'))['scene_manifest_hash']
print('DETERMINISM', 'SAME' if a==b else 'DIFFERENT', a[:23], b[:23])
PY
echo "== the shot: 192 frames, 960x540, follow camera"
python3 hhrc.py compile --seed 42 --journey 192 $P --out out-marvin | grep -E 'COMPILED|wall'
ffmpeg -y -loglevel error -framerate 24 -i out-marvin/journey-seed42/frame-%04d.png -c:v libx264 -pix_fmt yuv420p -crf 20 -movflags +faststart out-marvin/shot-seed42-192f.mp4
ls -la out-marvin/shot-seed42-192f.mp4 && rm -rf out-marvin/journey-seed42
echo "== capsule + receipts"
python3 hhrc.py capsule --out out-marvin --seed 42 --frames 1 192 --rights rights-three-cells-marvin-001.json | tail -2
python3 hhrc.py receipt --out out-marvin --seed 42 --timing out-marvin/timing-seed42-still90.json --capsule out-marvin/render-capsule-seed42.json | tail -2
python3 hhrc.py receipt --out out-marvin --seed 42 --timing out-marvin/timing-seed42-journey192.json --capsule out-marvin/render-capsule-seed42.json | tail -2
for r in out-marvin/render-receipt-seed42-*.json; do python3 hhrc.py verify $r --out out-marvin | tail -1; done
ls -la out-marvin/
echo MARVIN-DONE
