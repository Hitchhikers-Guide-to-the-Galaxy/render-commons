# render-commons

The first rung of the Hitchhiker Render Commons: `hhrc.py` (validate / compile / sheet / capsule / receipt / verify) drives `compile_world.py` inside Blender 5.2 LTS on the Air. Contracts in `contracts/` are the draft schemas from agentic.blender.anarchive.earth with three fixes applied (engine `BLENDER_EEVEE`; energy enum measured/estimated/none; receipt echoes seed, world_spec_hash, engine, scene_manifest_hash). Fixtures in `fixtures/` are the three-cell world, the seed-42 patch and its rights manifest, unchanged.

Plan and demo: https://agentic.blender.anarchive.earth/view/render-commons-plan

## What is here and what is not

- `hhrc.py`, `compile_world.py`, `broker.py`, `worker.py` and the `run_*.sh` scripts: the four rungs of the demo ladder, end to end.
- `contracts/`: seven draft JSON Schema contracts (six from the research package with fixes, one Shot Plan of ours).
- `fixtures/`: the three-cell world, the accepted patches, the shot plan, and the rights manifests. `human_verified` is false on every record until a person ticks it; that is deliberate.
- Not here: renders, receipts and broker results (published as page assets on the wiki); the Marvin cards in `assets/marvin/`, which are Hitchhiker material whose rights record does not yet permit public distribution; the Huginn rig, which is Blender Studio's CC BY download (see `compile_world.py` for the path it expects).
- No licence is chosen for this code or the contracts yet. The rights records say `NOASSERTION`; choosing one is an open question on the plan page, and it is the rights holder's to answer.

Rungs: [Three Cells Demo](https://agentic.blender.anarchive.earth/view/three-cells-demo) · [Huginn at the River](https://agentic.blender.anarchive.earth/view/huginn-at-the-river) · [Marvin Mock Journey](https://agentic.blender.anarchive.earth/view/marvin-mock-journey) · [Mini Round Trip](https://agentic.blender.anarchive.earth/view/mini-round-trip)
