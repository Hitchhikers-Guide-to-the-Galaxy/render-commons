#!/bin/bash
# run_phase2.sh — Phase 2, controlled plurality: three seeds by three journeys, the Flow-like rung costed once.
set -e; cd "$(dirname "$0")"
rm -rf out-p2 out-p2b; mkdir -p out-p2 out-p2b
echo "== nine stills: seeds 42 43 44 x journeys journey high town, frame 120, 960x540, lit"
for s in 42 43 44; do for cam in journey high town; do python3 hhrc.py compile --seed $s --still 120 --camera $cam --grid --out out-p2 | grep COMPILED | sed "s/^/seed $s $cam: /"; done; done
python3 hhrc.py grid --out out-p2 | tail -1
echo "== determinism: seed 43 town again"
python3 hhrc.py compile --seed 43 --still 120 --camera town --grid --out out-p2b | grep COMPILED
python3 - <<'PY'
import json
a=json.load(open('out-p2/scene-manifest-seed43.json'))['scene_manifest_hash']; b=json.load(open('out-p2b/scene-manifest-seed43.json'))['scene_manifest_hash']
print('DETERMINISM', 'SAME' if a==b else 'DIFFERENT', a[:23], b[:23])
PY
echo "== the rungs, seed 42 journey frame 120 at 1920x1080: lit, atmosphere, flowlike"
for r in lit atmosphere flowlike; do python3 hhrc.py compile --seed 42 --still 120 --camera journey --rung $r --res 1920x1080 --out out-p2/rung-$r | grep COMPILED | sed "s/^/rung $r: /"; done
echo "== three journeys on video, seed 42, 120 frames each at 960x540, lit"
for cam in journey high town; do
  python3 hhrc.py compile --seed 42 --journey 120 --camera $cam --out out-p2/video-$cam | grep -E 'COMPILED|wall' | sed "s/^/$cam: /"
  ffmpeg -y -loglevel error -framerate 24 -i out-p2/video-$cam/journey-seed42/frame-%04d.png -c:v libx264 -pix_fmt yuv420p -crf 20 -movflags +faststart out-p2/$cam-seed42-120f.mp4
  rm -rf out-p2/video-$cam/journey-seed42
  python3 hhrc.py capsule --out out-p2/video-$cam --seed 42 --frames 1 120 --job three-cells-seed42-$cam-120f | tail -1
  python3 hhrc.py receipt --out out-p2/video-$cam --seed 42 --timing out-p2/video-$cam/timing-seed42-journey120.json --capsule out-p2/video-$cam/render-capsule-seed42.json | tail -1
done
ls -la out-p2/*.mp4 out-p2/contact-grid.png
echo PHASE2-DONE
