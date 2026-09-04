#!/bin/bash
# run_huginn.sh — rung 1, Huginn at the River, end to end on the Air.
set -e; cd "$(dirname "$0")"
P="--patches world-patch-seed-42.json world-patch-huginn-001.json --rights rights-three-cells-huginn-001.json"
rm -rf out-huginn out-huginn2; mkdir -p out-huginn out-huginn2
echo "== hero stills (seeds 42 43 44, frame 60, 960x540, 16 samples)"
for s in 42 43 44; do python3 hhrc.py compile --seed $s --still 60 $P --camera hero --out out-huginn | grep COMPILED; done
python3 hhrc.py sheet --out out-huginn --frame 60 | tail -1
echo "== wide still, seed 42, journey camera frame 120"
python3 hhrc.py compile --seed 42 --still 120 $P --camera journey --out out-huginn-wide | grep COMPILED
cp out-huginn-wide/still-seed42-f120.png out-huginn/wide-seed42-f120.png
echo "== determinism: seed 42 hero again into out-huginn2"
python3 hhrc.py compile --seed 42 --still 60 $P --camera hero --out out-huginn2 | grep COMPILED
python3 - <<'PY'
import json
a=json.load(open('out-huginn/scene-manifest-seed42.json'))['scene_manifest_hash']; b=json.load(open('out-huginn2/scene-manifest-seed42.json'))['scene_manifest_hash']
print('DETERMINISM', 'SAME' if a==b else 'DIFFERENT', a[:23], b[:23])
PY
echo "== rights gate negative test: a character with no rights record"
python3 hhrc.py compile --seed 42 --still 60 --patches world-patch-seed-42.json world-patch-unlicensed-001.json --rights rights-three-cells-huginn-001.json --camera hero --res 320x180 --out out-unlicensed | grep COMPILED
python3 -c "
import json; m=json.load(open('out-unlicensed/scene-manifest-seed42.json')); c=[x for x in m['validation'] if x['check']=='character rights'][0]; print('GATE', c['status'].upper(), '—', c['detail'], '| characters placed:', len(m['characters']))"
echo "== hero dolly: seed 42, 96 frames, 960x540"
python3 hhrc.py compile --seed 42 --journey 96 $P --camera hero --out out-huginn | grep -E 'COMPILED|wall'
ffmpeg -y -loglevel error -framerate 24 -i out-huginn/journey-seed42/frame-%04d.png -c:v libx264 -pix_fmt yuv420p -crf 20 -movflags +faststart out-huginn/dolly-seed42-96f.mp4
ls -la out-huginn/dolly-seed42-96f.mp4 && rm -rf out-huginn/journey-seed42
echo "== capsule + receipts"
python3 hhrc.py capsule --out out-huginn --seed 42 --frames 1 96 --rights rights-three-cells-huginn-001.json | tail -2
python3 hhrc.py receipt --out out-huginn --seed 42 --timing out-huginn/timing-seed42-still60.json --capsule out-huginn/render-capsule-seed42.json | tail -2
python3 hhrc.py receipt --out out-huginn --seed 42 --timing out-huginn/timing-seed42-journey96.json --capsule out-huginn/render-capsule-seed42.json | tail -2
for r in out-huginn/render-receipt-seed42-*.json; do python3 hhrc.py verify $r --out out-huginn | tail -1; done
ls -la out-huginn/
echo HUGINN-DONE
