#!/bin/bash
# run_roundtrip.sh — rung 3, Mini Round Trip: the Air dispatches, the Mini renders, the Air verifies.
set -e; cd "$(dirname "$0")"
# AIR = the broker host's tailnet address, MINI = the worker's ssh target; set them in the environment
AIR="${AIR:?set AIR to the broker host address}"; MINI="${MINI:?set MINI to user@worker-host}"; PORT="${PORT:-4290}"; JOB=three-cells-seed42-mini-001
rm -rf broker; mkdir -p broker
echo "== broker on the Air ($AIR:$PORT)"
python3 broker.py serve --bind $AIR --port $PORT > broker/broker.log 2>&1 & BPID=$!; sleep 1
trap "kill $BPID 2>/dev/null" EXIT
echo "== enqueue the signed capsule + data payload"
python3 broker.py enqueue $JOB --capsule out-rt/render-capsule-seed42.json --payload fixtures/minimal-world.json fixtures/world-patch-seed-42.json fixtures/rights-earth2-fixture-001.json
echo "== enqueue a tampered twin: same signature, one field changed after signing"
python3 - <<'PY'
import json, shutil, pathlib
src = pathlib.Path('broker/queue/three-cells-seed42-mini-001'); dst = pathlib.Path('broker/queue/three-cells-seed42-mini-tampered'); shutil.copytree(src, dst)
c = json.load(open(dst/'capsule.json')); c['job_id'] = 'three-cells-seed42-mini-tampered'; c['frames'] = [1, 480]
json.dump(c, open(dst/'capsule.json','w'), indent=1, sort_keys=True); print('tampered twin written (frames 1-480, signature untouched)')
PY
curl -s http://$AIR:$PORT/jobs; echo
echo "########## WORKER ($MINI): polls the broker, once ##########"
ssh "$MINI" "cd ~/Code/render-commons && /opt/homebrew/bin/python3 worker.py --broker http://$AIR:$PORT --worker-id mini-m1-8gb --accept trusted --once" 2>&1 | grep -E "REFUSED|DONE|Traceback|Error|COMPILED" | head
echo "########## LAPTOP (Air): verify what came back ##########"
R=broker/results/$JOB; ls -la $R | head -8; ls $R/frames | wc -l
echo "-- receipt signature (the Mini's worker key, allowed on the Air)"
ssh-keygen -Y verify -f ~/.ssh/hhrc-allowed-signers -I mini-worker -n hhrc-receipt -s $R/receipt.sig < $R/receipt.json && echo "RECEIPT-SIGNATURE OK"
echo "-- receipt + capabilities against the contracts"
python3 hhrc.py validate $R/receipt.json | tail -1; python3 hhrc.py validate $R/capabilities.json | tail -1
echo "-- structural: the Mini's scene manifest hash vs the Air's own compile of the same capsule"
python3 - <<'PY'
import json
mini=json.load(open('broker/results/three-cells-seed42-mini-001/receipt.json')); air=json.load(open('out-rt/scene-manifest-seed42.json'))
print('STRUCTURAL', 'SAME' if mini['scene_manifest_hash']==air['scene_manifest_hash'] else 'DIFFERENT', mini['scene_manifest_hash'][:23], air['scene_manifest_hash'][:23])
print('mini render', mini['render_seconds'], 's wall', mini['wall_seconds'], 's; outputs', len(mini['outputs']), '; warnings:', mini['warnings'][0])
PY
echo "-- output hashes as received vs as claimed in the receipt"
python3 - <<'PY'
import json, hashlib, pathlib
R=pathlib.Path('broker/results/three-cells-seed42-mini-001'); rec=json.load(open(R/'receipt.json')); bad=0
for o in rec['outputs']:
    h='sha256:'+hashlib.sha256((R/o['path']).read_bytes()).hexdigest(); bad += (h!=o['hash'])
print('OUTPUT-HASHES', 'VERIFIED' if not bad else f'{bad} MISMATCH', 'of', len(rec['outputs']))
PY
echo "-- perceptual: the Mini's frame 24 vs the Air's frame 24"
python3 - <<'PY'
from PIL import Image, ImageChops, ImageStat
a=Image.open('out-rt/still-seed42-f024.png').convert('RGB'); m=Image.open('broker/results/three-cells-seed42-mini-001/frames/frame-0024.png').convert('RGB')
d=ImageChops.difference(a,m); st=ImageStat.Stat(d); mean=sum(st.mean)/3; mx=max(max(b) for b in d.getextrema())
print(f'PIXELS mean abs diff {mean:.3f}/255, max {mx}/255, identical: {mean==0}')
d.point(lambda v: min(255, v*8)).save('out-rt/diff-f024-x8.png')
PY
echo "-- bytes over the tailnet, from the broker log"
python3 - <<'PY'
import json
ev=[json.loads(l) for l in open('broker/log.jsonl')]
down=sum(e.get('bytes',0) for e in ev if e['event']=='get' and e['job']=='three-cells-seed42-mini-001'); up=sum(e.get('bytes',0) for e in ev if e['event']=='result')
print(f'BYTES down {down} up {up}; events {len(ev)}')
PY
cp broker/log.jsonl out-rt/broker-log.jsonl
echo ROUNDTRIP-DONE
