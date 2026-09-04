"""compile_world.py — the first Blender World Compiler rung (Three Cells Demo).

Run INSIDE Blender by hhrc.py:
    blender -b --python compile_world.py -- --world W --patch P --seed 42 --out DIR
              [--res 960x540] [--samples 16] [--still FRAME | --journey FRAMES]

Consumes an accepted world (minimal-world.json) + an accepted World Patch,
compiles terrain, river, vegetation zones, a settlement and a camera journey
deterministically from the seed, validates the result, writes a scene manifest
(hashable, pixel-independent), renders ONE animation call (a still is a
one-frame animation — repeated render() calls deadlock Metal in -b mode),
and writes render timings for the receipt. Open assets only: every mesh is
generated here. Engine identifier BLENDER_EEVEE (Blender 5.x).
"""
import bpy, bmesh, json, sys, os, math, hashlib, time, random
from mathutils import Vector, noise

# ---------------------------------------------------------------- args
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
def arg(name, default=None):
    return argv[argv.index(name) + 1] if name in argv else default
WORLD = arg("--world"); PATCH = arg("--patch"); OUT = arg("--out")
SEED = int(arg("--seed", 42)); RES = tuple(int(x) for x in arg("--res", "960x540").split("x"))
SAMPLES = int(arg("--samples", 16)); STILL = arg("--still"); JOURNEY = arg("--journey")
RIGHTS = arg("--rights"); CAMERA = arg("--camera", "journey"); SHOT = arg("--shot"); RUNG = arg("--rung", "lit")
os.makedirs(OUT, exist_ok=True)
random.seed(SEED)

world = json.load(open(WORLD))
patches = [json.load(open(p)) for p in PATCH.split(",")] if PATCH else []
patch = patches[-1] if patches else None
rights = json.load(open(RIGHTS)) if RIGHTS else None
shot = json.load(open(SHOT)) if SHOT else None
MPU = world["coordinate_system"]["metres_per_unit"]      # 100 m per unit
SEA = world.get("sea_level", 0)

# ---------------------------------------------------------------- apply the patch
def apply_patch(world, patch):
    """Interpret operations as JSON-pointer-like paths relative to the target
    entity (the fixture's reading). Status must be accepted."""
    if patch is None: return
    assert patch["status"] == "accepted", "only accepted patches compile"
    kinds = {"cell": "cells", "edge": "edges", "node": "nodes"}
    for op in patch["operations"]:
        if op["target_kind"] == "world":
            target = world
        else:
            target = next(e for e in world[kinds[op["target_kind"]]] if e["id"] == op["target_id"])
        parts = [p for p in op["path"].split("/") if p]
        for p in parts[:-1]:
            target = target.setdefault(p, {})
        key = parts[-1]
        if op["op"] in ("add", "replace"):
            target[key] = op["value"]
        elif op["op"] == "remove":
            target.pop(key, None)
for _p in patches: apply_patch(world, _p)

# ---------------------------------------------------------------- geometry helpers
def point_in_poly(x, y, poly):
    inside = False; n = len(poly); j = n - 1
    for i in range(n):
        xi, yi = poly[i]; xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi:
            inside = not inside
        j = i
    return inside

def dist_to_segment(p, a, b):
    ab = Vector(b) - Vector(a); ap = Vector(p) - Vector(a)
    t = max(0.0, min(1.0, ap.dot(ab) / (ab.length_squared + 1e-12)))
    return (Vector(a) + ab * t - Vector(p)).length, t

def dist_to_path(p, path):
    """(distance, parameter 0..1 along the polyline) in units."""
    best = (1e9, 0.0); acc = 0.0
    lens = [(Vector(path[i+1]) - Vector(path[i])).length for i in range(len(path) - 1)]
    total = sum(lens)
    for i in range(len(path) - 1):
        d, t = dist_to_segment(p, path[i], path[i+1])
        if d < best[0]:
            best = (d, (acc + t * lens[i]) / total)
        acc += lens[i]
    return best

cells = world["cells"]
river = next(e for e in world["edges"] if e["type"] == "river")
RPATH = river["path"]; RW = river["width"]                     # units
def cell_of(x, y):
    for c in cells:
        if point_in_poly(x, y, c["polygon"]): return c
    # outside every cell: nearest cell centre
    return min(cells, key=lambda c: (Vector((x, y)) - Vector([sum(p[0] for p in c["polygon"]) / len(c["polygon"]),
                                                            sum(p[1] for p in c["polygon"]) / len(c["polygon"])])).length)

def bed_height(t):
    """River bed elevation along the path, strictly descending source -> outlet.
    Anchored by cell: a mountain stream through the highland, a gentle gradient
    through the valley (8 per cent, so the floodplain can be built on), a rapids
    drop into the estuary, sea level minus two at the outlet."""
    src = next(n for n in world["nodes"] if n["type"] == "source")
    top = cell_of(*src["position"])["elevation_range"][0] + 10
    anchors = [(0.0, top), (0.25, 78.0), (0.75, 62.0), (1.0, SEA - 2.0)]
    for (t0, z0), (t1, z1) in zip(anchors, anchors[1:]):
        if t <= t1:
            u = (t - t0) / (t1 - t0); return z0 + (z1 - z0) * u
    return anchors[-1][1]

def base_height(x, y):
    """Metres. Cell elevation range interpolated by distance from the river
    (near = low end) plus seeded noise; river bed carved to a monotone descent."""
    c = cell_of(x, y)
    lo, hi = c["elevation_range"]
    d, t = dist_to_path((x, y), RPATH)
    # a flat floodplain 0.7 units (70 m) either side of the river, then the
    # cell's range climbs over the next 1.3 units; gentle seeded noise on top
    k = max(0.0, min(1.0, (d - 0.7) / 1.3)) ** 2
    n = noise.noise(Vector((x * 1.2 + SEED * 0.13, y * 1.2 + SEED * 0.29, SEED * 0.01)))
    # the floodplain sits just above the river bed at this point along the river, never below it:
    # the river is always the lowest line in the landscape (rung 1 fix: it used to run on a levee)
    floor = max(lo, bed_height(t) + 2.0)
    h = floor + (hi - floor) * (0.05 + 0.95 * k) + n * (hi - lo) * 0.025
    return h, d, t

def height(x, y):
    h, d, t = base_height(x, y)
    b = bed_height(t)
    if d < RW:                                                     # in the bed
        return min(h, b)
    if d < RW * 3:                                                 # banks blend
        w = (d - RW) / (RW * 2)
        return b + (h - b) * (w * w)
    return h

# ---------------------------------------------------------------- scene
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE"
scene.render.resolution_x, scene.render.resolution_y = RES
scene.render.resolution_percentage = 100
scene.render.use_compositing = False
scene.render.fps = 24
scene.eevee.taa_render_samples = SAMPLES
scene.unit_settings.system = "METRIC"

def collection(name):
    c = bpy.data.collections.new(name); scene.collection.children.link(c); return c
COL = {n: collection(n) for n in ["MAP_CELLS", "RIVERS", "SETTLEMENTS", "SOURCES", "FLORA", "CAMERA", "LIGHTS"]}

def material(name, rgb, rough=0.8):
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*rgb, 1); b.inputs["Roughness"].default_value = rough
    return m
BIOME_RGB = {"temperate-highland": (0.38, 0.40, 0.30), "temperate-river-valley": (0.25, 0.45, 0.18),
             "temperate-estuary": (0.30, 0.42, 0.28)}
MAT = {c["id"]: material(c["biome"], BIOME_RGB.get(c["biome"], (0.4, 0.4, 0.4))) for c in cells}
MAT_WATER = material("water", (0.10, 0.28, 0.42), 0.05)
MAT_WOOD = material("timber", (0.45, 0.30, 0.16)); MAT_ROOF = material("roof", (0.35, 0.18, 0.12))
MAT_ROAD = material("road", (0.55, 0.50, 0.42)); MAT_LEAF = material("leaf", (0.12, 0.35, 0.10))

# terrain heightfield over the world bbox
xs = [p[0] for c in cells for p in c["polygon"]]; ys = [p[1] for c in cells for p in c["polygon"]]
X0, X1, Y0, Y1 = min(xs) - 0.2, max(xs) + 0.2, min(ys) - 0.2, max(ys) + 0.2
NX, NY = 248, 96
def terrain():
    bm = bmesh.new(); grid = {}
    for j in range(NY + 1):
        for i in range(NX + 1):
            x = X0 + (X1 - X0) * i / NX; y = Y0 + (Y1 - Y0) * j / NY
            grid[(i, j)] = bm.verts.new((x * MPU, y * MPU, height(x, y)))
    bm.verts.ensure_lookup_table()
    faces = []
    for j in range(NY):
        for i in range(NX):
            faces.append(bm.faces.new((grid[(i, j)], grid[(i+1, j)], grid[(i+1, j+1)], grid[(i, j+1)])))
    me = bpy.data.meshes.new("terrain"); bm.to_mesh(me); bm.free()
    ob = bpy.data.objects.new("terrain", me); COL["MAP_CELLS"].objects.link(ob)
    for c in cells: me.materials.append(MAT[c["id"]])
    ids = [c["id"] for c in cells]
    for poly in me.polygons:
        cx, cy = poly.center.x / MPU, poly.center.y / MPU
        poly.material_index = ids.index(cell_of(cx, cy)["id"])
    me.shade_smooth() if hasattr(me, "shade_smooth") else None
    for poly in me.polygons: poly.use_smooth = True
    return ob
terrain_ob = terrain()

def terrain_z(x, y):           # units in
    return height(x, y)
def slope(x, y, h=0.02):
    dzdx = (height(x + h, y) - height(x - h, y)) / (2 * h * MPU)
    dzdy = (height(x, y + h) - height(x, y - h)) / (2 * h * MPU)
    return math.hypot(dzdx, dzdy)

# sea and river water
def plane(name, x0, x1, y0, y1, z, mat, col):
    me = bpy.data.meshes.new(name); bm = bmesh.new()
    vs = [bm.verts.new((x, y, z)) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
    bm.faces.new(vs); bm.to_mesh(me); bm.free()
    ob = bpy.data.objects.new(name, me); COL[col].objects.link(ob); me.materials.append(mat); return ob
plane("sea", X0 * MPU, (X1 + 3) * MPU, Y0 * MPU, Y1 * MPU, SEA - 0.5, MAT_WATER, "RIVERS")

def river_ribbon():
    """A ribbon following the river path at bed height + 0.6 m, width from the edge."""
    steps = 120; bm = bmesh.new(); left = []; right = []
    for s in range(steps + 1):
        t = s / steps
        # point at parameter t along the polyline
        lens = [(Vector(RPATH[i+1]) - Vector(RPATH[i])).length for i in range(len(RPATH) - 1)]
        total = sum(lens); acc = 0.0; d = t * total
        for i, L in enumerate(lens):
            if d <= acc + L or i == len(lens) - 1:
                u = (d - acc) / L; a, b = Vector(RPATH[i]), Vector(RPATH[i+1]); break
            acc += L
        p = a.lerp(b, u); tang = (b - a).normalized(); nrm = Vector((-tang.y, tang.x))
        z = bed_height(t) + 0.6
        left.append(bm.verts.new((*((p + nrm * RW) * MPU), z)))
        right.append(bm.verts.new((*((p - nrm * RW) * MPU), z)))
    for s in range(steps):
        bm.faces.new((left[s], right[s], right[s+1], left[s+1]))
    me = bpy.data.meshes.new("river-01"); bm.to_mesh(me); bm.free()
    ob = bpy.data.objects.new("river-01", me); COL["RIVERS"].objects.link(ob); me.materials.append(MAT_WATER)
river_ribbon()

# nodes: source + settlement + port markers
for n in world["nodes"]:
    x, y = n["position"]
    e = bpy.data.objects.new(n["id"], None); e.empty_display_type = "SPHERE"; e.empty_display_size = 8
    e.location = (x * MPU, y * MPU, terrain_z(x, y) + 3)
    COL["SOURCES" if n["type"] == "source" else "SETTLEMENTS"].objects.link(e)

# vegetation: three zones, one per cell, procedural low-poly trees, instanced
def tree_proto(name, trunk, crown, rgb):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=6, radius1=0.35, radius2=0.25, depth=trunk)
    for v in bm.verts: v.co.z += trunk / 2
    r = bmesh.ops.create_cone(bm, cap_ends=True, segments=7, radius1=crown, radius2=0.0, depth=crown * 2.2)
    for v in r["verts"]: v.co.z += trunk + crown * 1.1
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    me.materials.append(MAT_WOOD); me.materials.append(material(name + "-leaf", rgb))
    for i, p in enumerate(me.polygons): p.material_index = 0 if i < 8 else 1
    ob = bpy.data.objects.new(name, me); ob.hide_render = True; ob.hide_viewport = True
    COL["FLORA"].objects.link(ob); return ob
PROTO = {"temperate-highland": tree_proto("pine", 4.0, 2.2, (0.10, 0.28, 0.12)),
         "temperate-river-valley": tree_proto("oak", 3.0, 3.5, (0.16, 0.42, 0.12)),
         "temperate-estuary": tree_proto("willow", 2.5, 2.8, (0.30, 0.48, 0.20))}
settlement = next(n for n in world["nodes"] if n["type"] == "settlement")
SX, SY = settlement["position"]
cons = settlement.get("constraints", {})
SETBACK = cons.get("minimum_river_setback_metres", 18) / MPU   # units
MAXSLOPE = cons.get("maximum_slope", 0.18)
TOWN_R = 0.55                                                    # units, settlement footprint radius
trees = []
rng = random.Random(SEED)
for c in cells:
    poly = c["polygon"]; bx = [p[0] for p in poly]; by = [p[1] for p in poly]
    density = int(60 + 220 * c["moisture"] * c["fertility"])
    made = 0; tries = 0
    while made < density and tries < density * 20:
        tries += 1
        x = rng.uniform(min(bx), max(bx)); y = rng.uniform(min(by), max(by))
        if not point_in_poly(x, y, poly): continue
        d, _ = dist_to_path((x, y), RPATH)
        if d < RW * 2.2: continue                                   # not in the water
        if (Vector((x, y)) - Vector((SX, SY))).length < TOWN_R: continue
        if slope(x, y) > 0.9: continue
        if height(x, y) < SEA + 1: continue
        ob = bpy.data.objects.new(f"tree-{c['id']}-{made}", PROTO[c["biome"]].data)
        s = rng.uniform(0.8, 1.4); ob.scale = (s, s, s); ob.rotation_euler.z = rng.uniform(0, 6.28)
        ob.location = (x * MPU, y * MPU, terrain_z(x, y)); COL["FLORA"].objects.link(ob)
        trees.append((c["id"], round(x, 3), round(y, 3))); made += 1

# characters: placed by a patch, gated by the rights manifest, appended from known CC BY files
ASSETS = {"huginn": {"blend": os.path.expanduser("~/Code/marvin-blender/assets/charge/huginn_v2/huginn_release_v2.blend"),
                     "collections": ["CH-huginn", "PR-armchair"], "root": "RIG-armchair", "height": 1.08,
                     "credit": "Huginn Rig (CC-BY) Blender Foundation | studio.blender.org"}}
characters = []; refused = []
COL["CHARACTERS"] = collection("CHARACTERS")
def place_character(spec):
    a = ASSETS.get(spec["asset"])
    if a is None: refused.append((spec["asset"], "unknown asset")); return
    rid = spec.get("rights_item_id"); item = next((i for i in (rights or {}).get("items", []) if i["item_id"] == rid), None)
    if item is None: refused.append((spec["asset"], f"no rights record {rid}")); return
    with bpy.data.libraries.load(a["blend"], link=False) as (src, dst):
        dst.collections = [c for c in src.collections if c in a["collections"]]
    for c in dst.collections:
        if c is not None: COL["CHARACTERS"].children.link(c)
    # fix image paths: the appended file's relative textures, and the missing production plate
    tex = os.path.join(os.path.dirname(a["blend"]), "textures")
    for im in bpy.data.images:
        if im.filepath.startswith("//textures/"): im.filepath = os.path.join(tex, im.filepath[len("//textures/"):])
        elif "/render/" in im.filepath and not os.path.exists(im.filepath):
            im.source = "GENERATED"; im.generated_color = (0.5, 0.5, 0.5, 1)  # neutral grey, not magenta
    root = bpy.data.objects.get(a["root"])
    # where: the settlement's river bank, a step back from the water, facing the river
    bank = RW * 3.2
    spine_dir = Vector((0.0, 1.0)) if SY >= RPATH[0][1] else Vector((0.0, -1.0))
    px = SX + spec.get("offset", [0, 0])[0]; py = RPATH[0][1] + spine_dir.y * bank + spec.get("offset", [0, 0])[1]
    z = terrain_z(px, py)
    root.location = (px * MPU, py * MPU, z); root.rotation_euler = (0, 0, math.radians(spec.get("facing_deg", 180)))
    characters.append({"asset": spec["asset"], "rights_item_id": rid, "at": [round(px, 3), round(py, 3), round(z, 2)],
                       "credit": a["credit"], "objects": sum(len(c.all_objects) for c in dst.collections if c)})
for spec in settlement.get("characters", []): place_character(spec)

# settlement: road spine from the river bank through the centre, parcels, buildings
buildings = []; placed_xy = []; rejected = {"setback": 0, "slope": 0, "water": 0}
def box(name, x, y, w, d, h, rz, mats, col):
    me = bpy.data.meshes.new(name); bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts: v.co = Vector((v.co.x * w, v.co.y * d, (v.co.z + 0.5) * h))
    bm.to_mesh(me); bm.free()
    for m in mats: me.materials.append(m)
    for p in me.polygons: p.material_index = 1 if p.normal.z > 0.5 and len(mats) > 1 else 0
    ob = bpy.data.objects.new(name, me); ob.location = (x * MPU, y * MPU, terrain_z(x, y) - 0.3)
    ob.rotation_euler.z = rz; COL[col].objects.link(ob); return ob
# road spine: from the bank (nearest river point) away through the settlement
d0, t0 = dist_to_path((SX, SY), RPATH)
spine_dir = Vector((0.0, 1.0)) if SY >= RPATH[0][1] else Vector((0.0, -1.0))
for k in range(-1, 6):
    px, py = SX + spine_dir.x * k * 0.09, SY + spine_dir.y * k * 0.09
    if dist_to_path((px, py), RPATH)[0] < RW * 1.5: continue
    box(f"road-{k}", px, py, 5, 9.5, 0.4, 0.0, [MAT_ROAD], "SETTLEMENTS")
grid_n = 9; pitch = 0.085
# the town sits back from the bank: its centre is the node moved 0.3 units (30 m) away from the river
TX, TY = SX + spine_dir.x * 0.3, SY + spine_dir.y * 0.3
for gi in range(grid_n):
    for gj in range(grid_n):
        x = TX + (gi - grid_n // 2) * pitch + rng.uniform(-0.01, 0.01)
        y = TY + (gj - grid_n // 2) * pitch + rng.uniform(-0.01, 0.01)
        if abs(x - TX) < 0.035: continue                              # keep the spine clear
        if (Vector((x, y)) - Vector((TX, TY))).length > TOWN_R * 0.75: continue
        if any((Vector((x, y)) - Vector(c['at'][:2])).length < 0.11 for c in characters): rejected['resident'] = rejected.get('resident', 0) + 1; continue
        d, _ = dist_to_path((x, y), RPATH)
        if d < SETBACK: rejected["setback"] += 1; continue
        if slope(x, y) > MAXSLOPE: rejected["slope"] += 1; continue
        if height(x, y) < SEA + 1: rejected["water"] += 1; continue
        if rng.random() < 0.2: continue
        w, dd, h = rng.uniform(5, 8), rng.uniform(6, 9), rng.uniform(3.5, 7)
        box(f"building-{len(buildings)}", x, y, w, dd, h, rng.uniform(-0.2, 0.2), [MAT_WOOD, MAT_ROOF], "SETTLEMENTS")
        buildings.append((round(x, 3), round(y, 3), round(h, 1)))
        placed_xy.append((x, y))

# fauna: a flock of code-generated birds circling above the bank by the town — the animated element, no assets
FLOCK_N = 16; flock = []
MAT_BIRD = material("bird", (0.12, 0.10, 0.09), 0.9)
def bird(name, size=1.6):
    """Two wing triangles hinged at the body, so they can flap by rotation."""
    body = bpy.data.objects.new(name, None); body.empty_display_size = 0.2; COL["FLORA"].objects.link(body)
    wings = []
    for sign, wn in ((1, "L"), (-1, "R")):
        me = bpy.data.meshes.new(f"{name}-{wn}"); bm = bmesh.new()
        vs = [bm.verts.new(v) for v in ((0, 0.15, 0), (0, -0.15, 0), (sign * size, 0.05, 0))]
        bm.faces.new(vs); bm.to_mesh(me); bm.free(); me.materials.append(MAT_BIRD)
        w = bpy.data.objects.new(f"{name}-{wn}", me); w.parent = body; COL["FLORA"].objects.link(w); wings.append((sign, w))
    return body, wings
frng = random.Random(SEED + 7)
FC = Vector((SX + 0.15, RPATH[0][1] + 0.05)); FZ0 = max(terrain_z(FC.x, FC.y), SEA) + 45.0
for i in range(FLOCK_N):
    body, wings = bird(f"bird-{i:02d}", size=frng.uniform(1.2, 1.9))
    r = frng.uniform(35, 70); phase = frng.uniform(0, 6.283); w = frng.uniform(0.9, 1.3) * (1 if i % 5 else -1); zoff = frng.uniform(-8, 10); flap = frng.uniform(5.0, 7.5)
    for f in range(1, 241, 3):
        t = (f - 1) / 24.0; ang = phase + w * t * 0.35
        pos = Vector((FC.x * MPU + r * math.cos(ang), FC.y * MPU + r * math.sin(ang), FZ0 + zoff + 3.0 * math.sin(t * 0.7 + phase)))
        body.location = pos; body.rotation_euler = (0, 0, ang + (math.pi / 2 if w > 0 else -math.pi / 2))
        body.keyframe_insert("location", frame=f); body.keyframe_insert("rotation_euler", frame=f)
        for sign, wing in wings:
            wing.rotation_euler = (0, sign * 0.6 * math.sin(t * flap * 6.283), 0); wing.keyframe_insert("rotation_euler", frame=f)
    flock.append({"i": i, "radius": round(r, 1), "z": round(FZ0 + zoff, 1)})

# lights + world: the lit rung (one low warm sun, sky colour, no volumetrics)
sun = bpy.data.lights.new("sun", "SUN"); sun.energy = 3.0; sun.angle = math.radians(4); sun.color = (1.0, 0.93, 0.82)
so = bpy.data.objects.new("sun", sun); so.rotation_euler = (math.radians(58), 0, math.radians(-35)); COL["LIGHTS"].objects.link(so)
wd = bpy.data.worlds.new("sky"); scene.world = wd; wd.use_nodes = True
bg = wd.node_tree.nodes["Background"]; bg.inputs[0].default_value = (0.55, 0.68, 0.85, 1); bg.inputs[1].default_value = 0.8
# quality rungs, named after the parent site's Flow ladder: lit / atmosphere / flowlike
ee = scene.eevee
if RUNG in ("atmosphere", "flowlike"):
    ee.taa_render_samples = max(SAMPLES, 64); ee.use_raytracing = True; ee.ray_tracing_options.resolution_scale = "1"
    ee.shadow_ray_count = 2; ee.shadow_step_count = 8; sun.angle = math.radians(12)
    ee.volumetric_start = 1.0; ee.volumetric_end = 900.0; ee.volumetric_samples = 64; ee.volumetric_tile_size = "4"; ee.use_volumetric_shadows = True
    vol = wd.node_tree.nodes.new("ShaderNodeVolumeScatter"); vol.inputs["Density"].default_value = 0.0025; vol.inputs["Color"].default_value = (0.85, 0.9, 1.0, 1)
    wd.node_tree.links.new(vol.outputs["Volume"], wd.node_tree.nodes["World Output"].inputs["Volume"])

# camera journey: along the river, above the far bank, looking ahead — 10 s = 240 frames
FRAMES = 240
cam = bpy.data.cameras.new("journey"); cam.lens = 26
if RUNG == "flowlike": cam.dof.use_dof = True; cam.dof.aperture_fstop = 2.8
co = bpy.data.objects.new("journey", cam); COL["CAMERA"].objects.link(co); scene.camera = co
def path_point(t):
    lens = [(Vector(RPATH[i+1]) - Vector(RPATH[i])).length for i in range(len(RPATH) - 1)]
    total = sum(lens); acc = 0.0; d = t * total
    for i, L in enumerate(lens):
        if d <= acc + L or i == len(lens) - 1:
            u = (d - acc) / L; return Vector(RPATH[i]).lerp(Vector(RPATH[i+1]), u)
        acc += L
    return Vector(RPATH[-1])
def cam_pose(t):
    p = path_point(t); ahead = path_point(min(1.0, t + 0.06))
    if CAMERA == "high":     # the overview: high and slow, the whole world in frame, drifting downstream
        u = 0.35 + 0.45 * t; q = path_point(u)
        eye = Vector((q.x * MPU - 40, (q.y - 1.6) * MPU, 300 + 40 * (1 - t)))
        look = Vector((*(path_point(min(1.0, u + 0.25)) * MPU), bed_height(min(1.0, u + 0.25)) + 20))
        return eye, look
    if CAMERA == "town":     # the flyover: an arc over the settlement from the river side to the hills
        ang = math.radians(-120 + 150 * t); c = Vector((TX, TY)) * MPU
        eye = Vector((c.x + 110 * math.cos(ang), c.y + 110 * math.sin(ang), terrain_z(TX, TY) + 45 + 25 * math.sin(math.pi * t)))
        look = Vector((c.x, c.y, terrain_z(TX, TY) + 4))
        return eye, look
    side = Vector((-0.25, -0.6))
    eye = Vector((*((p + side) * MPU), max(terrain_z(p.x + side.x, p.y + side.y), bed_height(t)) + 55))
    look = Vector((*(ahead * MPU), bed_height(min(1.0, t + 0.06)) + 6))
    return eye, look
# performer: a Shot Plan's card puppet on a path, with beats; gated by the rights manifest like a character
CARDS = {"marvin-card": {"dir": os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "marvin"),
                         "cards": {"stand": "marvin-stand.png", "walk-a": "marvin-walk-a.png", "walk-b": "marvin-walk-b.png", "say": "marvin-sad.png"},
                         "aspect": 332 / 720, "credit": "Marvin, the Hitchhikers puppet rig (htv-puppet/4), the Hitchhikers project"}}
performer = None; shot_refused = None; say_text = None
def card_material(name, png):
    m = bpy.data.materials.new(name); m.use_nodes = True; nt = m.node_tree
    bsdf = nt.nodes["Principled BSDF"]; tex = nt.nodes.new("ShaderNodeTexImage"); tex.image = bpy.data.images.load(png)
    tex.image.alpha_mode = "STRAIGHT"; nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"]); nt.links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
    bsdf.inputs["Roughness"].default_value = 0.9
    m.surface_render_method = "DITHERED"; m.use_backface_culling = False
    return m
def card_object(name, mat, h, aspect):
    me = bpy.data.meshes.new(name); bm = bmesh.new(); w = h * aspect
    vs = [bm.verts.new(v) for v in ((-w/2, 0, 0), (w/2, 0, 0), (w/2, 0, h), (-w/2, 0, h))]
    f = bm.faces.new(vs); bm.to_mesh(me); bm.free()
    me.uv_layers.new(name="uv"); uv = me.uv_layers[0].data
    for li, co in zip(me.polygons[0].loop_indices, ((0, 0), (1, 0), (1, 1), (0, 1))): uv[li].uv = co
    me.materials.append(mat); ob = bpy.data.objects.new(name, me); COL["CHARACTERS"].objects.link(ob); return ob
if shot:
    a = CARDS.get(shot["performer"]["asset"]); rid = shot["performer"]["rights_item_id"]
    item = next((i for i in (rights or {}).get("items", []) if i["item_id"] == rid), None)
    if a is None: shot_refused = f"unknown performer asset {shot['performer']['asset']}"
    elif item is None: shot_refused = f"no rights record {rid}"
    else:
        H = shot["performer"].get("height_m", 1.55)
        cards = {k: card_object(f"marvin-{k}", card_material(f"marvin-{k}", os.path.join(a["dir"], v)), H, a["aspect"]) for k, v in a["cards"].items()}
        # the path: up the road spine from from_m metres past the bank end, at speed, while walking
        fps = shot["fps"]; NF = int(round(shot["duration_s"] * fps)); FRAMES = NF
        sp = shot["path"]; speed = sp.get("speed_mps", 1.3); start = Vector((SX, SY)) + spine_dir * (sp.get("from_m", 0) / MPU)
        beats = sorted(shot["beats"], key=lambda b: b["at_s"])
        def state_at(t):
            st = "stop"; say = None
            for b in beats:
                if b["at_s"] <= t:
                    if b["do"] in ("walk", "stop"): st = b["do"]
                    if b["do"] == "say": say = b if t < b["at_s"] + b.get("seconds", 2.0) else None
            return st, say
        # integrate position frame by frame (walk beats move him)
        pos = []; d = 0.0
        for f in range(1, NF + 1):
            t = (f - 1) / fps; st, say = state_at(t)
            if st == "walk": d += speed / fps
            pos.append((t, d, st, say))
        say_text = next((b["text"] for b in beats if b["do"] == "say"), None)
        # text object for the line
        txt = None
        if say_text:
            fc = bpy.data.curves.new("line", type="FONT"); fc.size = 0.11; fc.align_x = "CENTER"
            words = say_text.split(); half = len(words) // 2; fc.body = " ".join(words[:half]) + "\n" + " ".join(words[half:])
            txt = bpy.data.objects.new("line", fc); COL["CHARACTERS"].objects.link(txt); txt.visible_shadow = False
            tm = bpy.data.materials.new("line-mat"); tm.use_nodes = True; tm.node_tree.nodes["Principled BSDF"].inputs["Emission Color"].default_value = (1, 1, 1, 1)
            tm.node_tree.nodes["Principled BSDF"].inputs["Emission Strength"].default_value = 2.0; fc.materials.append(tm)
        cam.lens = shot["camera"].get("lens_mm", 35); dist = shot["camera"].get("distance_m", 5.0); hgt = shot["camera"].get("height_m", 1.7)
        walk_samples = []
        for f, (t, d, st, say) in enumerate(pos, start=1):
            pu = start + spine_dir * (d / MPU); z = terrain_z(pu.x, pu.y)
            feet = Vector((pu.x * MPU, pu.y * MPU, z + 0.14))   # the road slab tops out 0.1 m above the terrain
            # camera: behind-right of him, low, looking at his chest
            back = -spine_dir; eye = feet + Vector((back.x * dist * 0.75 + 2.6, back.y * dist * 0.75, 0))
            eye.z = max(height(eye.x / MPU, eye.y / MPU), z) + hgt
            look = feet + Vector((0, 0, H * 0.6))
            co.location = eye; co.rotation_euler = (look - eye).to_track_quat("-Z", "Y").to_euler()
            co.keyframe_insert("location", frame=f); co.keyframe_insert("rotation_euler", frame=f)
            # which card shows: walk cycle 6 frames per step, stand when stopped, sad card while saying
            show = "say" if say else ("stand" if st == "stop" else ("walk-a" if (f // 6) % 2 == 0 else "walk-b"))
            face = (eye - feet); face.z = 0
            for k, ob in cards.items():
                ob.location = feet + Vector((0, 0, 0.02 * math.sin(f * 1.1) if st == "walk" else 0))
                ob.rotation_euler = (0, 0, math.atan2(face.y, face.x) + math.pi / 2)   # billboard: the card faces the camera
                ob.hide_render = ob.hide_viewport = (k != show)
                ob.keyframe_insert("location", frame=f); ob.keyframe_insert("rotation_euler", frame=f)
                ob.keyframe_insert("hide_render", frame=f); ob.keyframe_insert("hide_viewport", frame=f)
            if txt:
                txt.location = feet + Vector((-face.x * 0.05, -face.y * 0.05, H + 0.45)); txt.rotation_euler = (math.radians(90), 0, math.atan2(face.y, face.x) + math.pi / 2)
                txt.hide_render = txt.hide_viewport = say is None
                txt.keyframe_insert("location", frame=f); txt.keyframe_insert("rotation_euler", frame=f); txt.keyframe_insert("hide_render", frame=f); txt.keyframe_insert("hide_viewport", frame=f)
            walk_samples.append((round(pu.x, 4), round(pu.y, 4), round(z, 2), st, bool(say)))
        performer = {"asset": shot["performer"]["asset"], "rights_item_id": rid, "credit": a["credit"], "shot_id": shot["shot_id"],
                     "frames": NF, "walked_m": round(d, 2), "start": [round(start.x, 3), round(start.y, 3)], "end": walk_samples[-1][:3], "beats": beats}
        for k, ob in cards.items(): ob.hide_render = ob.hide_viewport = (k != "stand")   # a sane state outside the shot's frames

scene.frame_start, scene.frame_end = 1, FRAMES
HERO = CAMERA == "hero" and bool(characters)
if performer: CAMERA = "follow"
if HERO:
    cam.lens = 40; hx, hy, hz = characters[0]["at"]; H = ASSETS[characters[0]["asset"]]["height"]
    target = Vector((hx * MPU, hy * MPU, hz + H * 0.55))
    for f in range(1, FRAMES + 1, 6):
        u = (f - 1) / (FRAMES - 1)
        ang = math.radians(-125 + 70 * u)                      # a slow arc on the river side, town behind him, river at the edge
        r = 4.6 - 0.8 * u
        eye = target + Vector((r * math.cos(ang), r * math.sin(ang), 0.0))
        eye.z = max(height(eye.x / MPU, eye.y / MPU), hz) + 1.1 + 0.3 * u   # stand on the ground, eye height
        co.location = eye; co.rotation_euler = (target - eye).to_track_quat("-Z", "Y").to_euler()
        co.keyframe_insert("location", frame=f); co.keyframe_insert("rotation_euler", frame=f)
for f in (range(1, FRAMES + 1, 8) if not (HERO or performer) else []):
    t = (f - 1) / (FRAMES - 1) * 0.92 + 0.04
    eye, look = cam_pose(t)
    if RUNG == "flowlike": cam.dof.focus_distance = (look - eye).length; cam.dof.keyframe_insert("focus_distance", frame=f)
    co.location = eye
    co.rotation_euler = (look - eye).to_track_quat("-Z", "Y").to_euler()
    co.keyframe_insert("location", frame=f); co.keyframe_insert("rotation_euler", frame=f)

# ---------------------------------------------------------------- validators
checks = []
def check(name, ok, detail):
    checks.append({"check": name, "status": "pass" if ok else "fail", "detail": detail})
bed = [bed_height(i / 40) for i in range(41)]
check("river descends", all(bed[i] > bed[i+1] for i in range(40)),
      f"bed from {bed[0]:.1f} m to {bed[-1]:.1f} m over 41 samples, monotone")
check("river reaches sea", bed[-1] <= SEA, f"outlet bed {bed[-1]:.1f} m vs sea level {SEA} m")
check("buildings count", 20 <= len(buildings) <= 50, f"{len(buildings)} buildings (brief asks 20 to 50)")
setb = min(dist_to_path(b, RPATH)[0] * MPU for b in placed_xy) if placed_xy else 0
check("floodplain setback", setb >= cons.get("minimum_river_setback_metres", 18),
      f"nearest building {setb:.1f} m from the river; setback {cons.get('minimum_river_setback_metres', 18)} m")
maxs = max(slope(*b) for b in placed_xy) if placed_xy else 0
check("building slope", maxs <= MAXSLOPE, f"steepest building site slope {maxs:.3f}; maximum {MAXSLOPE}")
check("vegetation avoids water", all(dist_to_path((t[1], t[2]), RPATH)[0] >= RW * 2.2 for t in trees),
      f"{len(trees)} trees, none within {RW * 2.2 * MPU:.0f} m of the river centreline")
check("vegetation avoids settlement", all((Vector((t[1], t[2])) - Vector((SX, SY))).length >= TOWN_R for t in trees),
      f"none within {TOWN_R * MPU:.0f} m of the settlement centre")
check("engine", scene.render.engine == "BLENDER_EEVEE", f"scene.render.engine = {scene.render.engine}")
if shot:
    check("shot rights", shot_refused is None, f"performer {shot['performer']['asset']} with record {shot['performer']['rights_item_id']}" if shot_refused is None else f"refused: {shot_refused}")
    if performer:
        road_half = 2.5 / MPU
        check("performer on the road", all(abs(x - SX) <= road_half + 0.005 and SY - 0.01 <= y <= SY + 0.46 for x, y, z, st, sy in walk_samples),
              f"walked {performer['walked_m']} m along the spine; every sample inside the road width")
        check("performer on land", all(z > SEA + 0.5 for x, y, z, st, sy in walk_samples), f"ground from {min(w[2] for w in walk_samples)} to {max(w[2] for w in walk_samples)} m")
        check("beats inside the shot", all(b["at_s"] + b.get("seconds", 0) <= shot["duration_s"] for b in beats), f"{len(beats)} beats in {shot['duration_s']} s")
check("fauna above ground", all(b["z"] > terrain_z(FC.x, FC.y) + 20 for b in flock), f"{len(flock)} birds circling {FLOCK_N and round(FZ0 - terrain_z(FC.x, FC.y))} m above the bank by the town")
if settlement.get("characters"):
    check("character rights", not refused and all(c["rights_item_id"] for c in characters),
          f"{len(characters)} placed with a rights record; refused: {refused or 'none'}")
    check("character on land", all(c["at"][2] > SEA + 0.5 for c in characters), f"ground height {[c['at'][2] for c in characters]} m")

# ---------------------------------------------------------------- scene manifest (deterministic, pixel-free)
def rounded_bbox(ob):
    return [round(v, 2) for v in (min(c[0] for c in ob.bound_box), min(c[1] for c in ob.bound_box), min(c[2] for c in ob.bound_box),
                                  max(c[0] for c in ob.bound_box), max(c[1] for c in ob.bound_box), max(c[2] for c in ob.bound_box))]
objects = []
for ob in sorted(bpy.data.objects, key=lambda o: o.name):
    entry = {"name": ob.name, "type": ob.type, "collection": ob.users_collection[0].name if ob.users_collection else None,
             "location": [round(v, 2) for v in ob.location]}
    if ob.type == "MESH":
        entry["verts"] = len(ob.data.vertices); entry["faces"] = len(ob.data.polygons); entry["bbox"] = rounded_bbox(ob)
    objects.append(entry)
tv = terrain_ob.data.vertices
manifest = {
    "world_id": world["world_id"], "patch_id": patch["patch_id"] if patch else None, "seed": SEED,
    "blender_version": bpy.app.version_string, "engine": scene.render.engine,
    "generator": "compile_world.py three-cells-0.1", "resolution": list(RES), "samples": SAMPLES,
    "terrain": {"grid": [NX + 1, NY + 1], "z_min": round(min(v.co.z for v in tv), 2), "z_max": round(max(v.co.z for v in tv), 2),
                "z_sum": round(sum(v.co.z for v in tv), 1)},
    "river_bed": [round(b, 2) for b in bed],
    "buildings": buildings, "rejected_parcels": rejected, "trees": len(trees), "characters": characters, "refused_characters": refused, "camera": CAMERA, "rung": RUNG, "flock": flock, "performer": performer, "shot_refused": shot_refused, "patches": [p["patch_id"] for p in patches],
    "camera_frames": FRAMES, "objects": objects, "validation": checks,
}
mjson = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
manifest["scene_manifest_hash"] = "sha256:" + hashlib.sha256(mjson.encode()).hexdigest()
json.dump(manifest, open(os.path.join(OUT, f"scene-manifest-seed{SEED}.json"), "w"), indent=1, sort_keys=True)
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, f"world-seed{SEED}.blend"))

# ---------------------------------------------------------------- render: exactly one animation call
timing = {"frames": [], "engine": scene.render.engine, "blender": bpy.app.version_string}
_t = {}
def pre(scene_, *_): _t["t"] = time.perf_counter()
def post(scene_, *_): timing["frames"].append(round(time.perf_counter() - _t["t"], 3))
bpy.app.handlers.render_pre.append(pre); bpy.app.handlers.render_post.append(post)
t0 = time.perf_counter()
if STILL:
    f = int(STILL); scene.frame_start = scene.frame_end = f
    scene.render.image_settings.file_format = "PNG"
    PFX = f"still-{CAMERA}-" if CAMERA in ("high", "town", "journey") and JOURNEY is None and arg("--grid") else f"still-"
    scene.render.filepath = os.path.join(OUT, f"{PFX}seed{SEED}-f{f:03d}-")
    bpy.ops.render.render(animation=True)
    # rename to a stable name
    for name in os.listdir(OUT):
        if name.startswith(f"{PFX}seed{SEED}-f{f:03d}-") and name.endswith(".png"):
            os.replace(os.path.join(OUT, name), os.path.join(OUT, f"{PFX}seed{SEED}-f{f:03d}.png"))
elif JOURNEY:
    # this Blender build has no FFMPEG output (image_settings.file_format enum lacks it);
    # render a PNG sequence and let run_demo.sh assemble the mp4 with the system ffmpeg
    n = int(JOURNEY); scene.frame_start, scene.frame_end = 1, n
    scene.render.image_settings.file_format = "PNG"
    os.makedirs(os.path.join(OUT, f"journey-seed{SEED}"), exist_ok=True)
    scene.render.filepath = os.path.join(OUT, f"journey-seed{SEED}", "frame-")
    bpy.ops.render.render(animation=True)
timing["wall_seconds"] = round(time.perf_counter() - t0, 3)
timing["render_seconds"] = round(sum(timing["frames"]), 3)
json.dump(timing, open(os.path.join(OUT, f"timing-seed{SEED}-{'still' + STILL if STILL else 'journey' + str(JOURNEY)}.json"), "w"), indent=1)
print("COMPILED", manifest["scene_manifest_hash"], "buildings", len(buildings), "trees", len(trees),
      "checks", sum(c["status"] == "pass" for c in checks), "/", len(checks), "render", timing["render_seconds"], "s")
