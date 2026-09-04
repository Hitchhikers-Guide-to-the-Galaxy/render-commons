#!/usr/bin/env python3
"""decisions.py — the decisions ARE the workflow.

Reads the review pages of the wiki (their live JSON), finds the decision
checkboxes a person has ticked, and turns them into state:

  - an acceptance record per accepted item: who (the journal entry that carried
    the tick), when, what (the page, the seed or patch), the world version it makes;
  - a rejection record per rejected item, with the reason line, for the World Soil;
  - expiry: proposals older than --expire-days with no decision are marked expired;
  - the accepted world's version graph, written as a wiki page (graphviz item whose
    nodes are page titles, so the graph is navigation) plus decisions.json beside it.

    python3 decisions.py --site agentic.blender.anarchive.earth --farm ~/Nextcloud/fedwiki [--dry-run] [--expire-days 90]

Standard library plus the Fedwiki Library for page writes. Nothing here renders;
it reads pages and writes two pages. A tick is a human act on the wiki; this script
only carries it forward.
"""
import argparse, json, os, sys, re, datetime, urllib.request
sys.path.insert(0, os.path.expanduser("~/.claude/skills/fedwiki-lib")); import fedwiki

now = datetime.datetime.now(datetime.UTC)

# the review pages and what each of their decision lines means
REVIEWS = {
    "three-cells-demo":       {"kind": "patch", "id": "patch-river-settlement-001", "parent": "earth2-three-cell", "created": "2026-09-04"},
    "huginn-at-the-river":    {"kind": "patch", "id": "patch-huginn-at-the-river-001", "parent": "patch-river-settlement-001", "created": "2026-09-04"},
    "marvin-mock-journey":    {"kind": "shot", "id": "shot-marvin-road-001", "parent": "patch-river-settlement-001", "created": "2026-09-04"},
    "mini-round-trip":        {"kind": "receipt", "id": "three-cells-seed42-mini-001", "parent": "patch-river-settlement-001", "created": "2026-09-04"},
    "river-journey-review":   {"kind": "render", "id": "journey", "parent": "patch-river-settlement-001", "created": "2026-09-05", "seeds": [42, 43, 44]},
    "overview-journey-review": {"kind": "render", "id": "high", "parent": "patch-river-settlement-001", "created": "2026-09-05", "seeds": [42, 43, 44]},
    "town-journey-review":    {"kind": "render", "id": "town", "parent": "patch-river-settlement-001", "created": "2026-09-05", "seeds": [42, 43, 44]},
}
TITLES = {"three-cells-demo": "Three Cells Demo", "huginn-at-the-river": "Huginn at the River", "marvin-mock-journey": "Marvin Mock Journey",
          "mini-round-trip": "Mini Round Trip", "river-journey-review": "River Journey Review", "overview-journey-review": "Overview Journey Review",
          "town-journey-review": "Town Journey Review"}

def fetch(site, slug):
    with urllib.request.urlopen(f"https://{site}/{slug}.json", timeout=30) as r: return json.load(r)

def decision_lines(page):
    """Every '- [x]' / '- [ ]' line in a Decision section, with the item id it lives in."""
    out = []
    for it in page.get("story", []):
        t = it.get("text", "")
        if "## Decision" not in t and "Decision, one line" not in t: continue
        for line in t.splitlines():
            m = re.match(r"- \[( |x)\] (.*)", line)
            if m: out.append({"ticked": m.group(1) == "x", "text": m.group(2).strip(), "item": it["id"]})
        # a reasons line after the checklist
        rm = re.search(r"reasons?:\s*(.+)", t, re.I)
        if rm and rm.group(1).strip() and not rm.group(1).strip().startswith("- ["): out.append({"reason": rm.group(1).strip()})
        dm = re.search(r"Dissent or reservations:\s*(.+)", t)
        if dm and dm.group(1).strip(): out.append({"dissent": dm.group(1).strip()})
    return out

def who_ticked(page, item_id):
    """The latest journal entry that edited the decision item: the acceptance record's who and when."""
    for e in reversed(page.get("journal", [])):
        if e.get("type") == "edit" and e.get("id") == item_id:
            return {"date": datetime.datetime.fromtimestamp(e.get("date", 0) / 1000, datetime.UTC).isoformat().replace("+00:00", "Z"),
                    "site": e.get("site"), "provenance": e.get("provenance")}
    return None

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--site", default="agentic.blender.anarchive.earth"); ap.add_argument("--farm", default=os.path.expanduser("~/Nextcloud/fedwiki"))
    ap.add_argument("--expire-days", type=int, default=90); ap.add_argument("--dry-run", action="store_true"); a = ap.parse_args()
    state = {"read_at": now.isoformat().replace("+00:00", "Z"), "site": a.site, "accepted": [], "rejected": [], "forked": [], "pending": [], "expired": []}
    for slug, meta in REVIEWS.items():
        try: page = fetch(a.site, slug)
        except Exception as e: print("skip", slug, e); continue
        lines = decision_lines(page); ticked = [l for l in lines if l.get("ticked")]
        reason = next((l["reason"] for l in lines if "reason" in l), None); dissent = next((l["dissent"] for l in lines if "dissent" in l), None)
        age = (now - datetime.datetime.fromisoformat(meta["created"]).replace(tzinfo=datetime.UTC)).days
        rec_base = {"page": slug, "title": TITLES[slug], "kind": meta["kind"], "id": meta["id"], "parent": meta["parent"], "created": meta["created"], "dissent": dissent}
        if not ticked:
            (state["expired"] if age > a.expire_days else state["pending"]).append({**rec_base, "age_days": age}); continue
        for l in ticked:
            who = who_ticked(page, l["item"]) or {}
            rec = {**rec_base, "line": l["text"], "who": who}
            txt = l["text"].lower()
            if txt.startswith("accept") or ": accept" in txt: state["accepted"].append(rec)
            elif txt.startswith("reject"): state["rejected"].append({**rec, "reason": reason})
            elif txt.startswith("fork"): state["forked"].append(rec)
    # ---- the version graph: nodes are page titles so the graph is navigation
    def node(title, fill): return f'"{title}" [style="rounded,filled", fillcolor="{fill}"];'
    G = ['digraph {', 'rankdir=LR; node [shape=box, fontname="Helvetica", fontsize=11];', node("Earth Is Three Cells", "#e8e2d4")]
    acc_pages = {r["page"] for r in state["accepted"]}; rej_pages = {r["page"] for r in state["rejected"]}
    for slug, meta in REVIEWS.items():
        fill = "#cfe8c4" if slug in acc_pages else ("#f2c7c0" if slug in rej_pages else "#f4efe6")
        G.append(node(TITLES[slug], fill))
    G += ['"Earth Is Three Cells" -> "Three Cells Demo";', '"Three Cells Demo" -> "Huginn at the River";', '"Three Cells Demo" -> "Marvin Mock Journey";',
          '"Three Cells Demo" -> "Mini Round Trip";', '"Three Cells Demo" -> "River Journey Review";', '"Three Cells Demo" -> "Overview Journey Review";',
          '"Three Cells Demo" -> "Town Journey Review";', node("World Soil", "#ddd6c8")]
    for slug in rej_pages: G.append(f'"{TITLES[slug]}" -> "World Soil" [style=dashed];')
    G.append("}")
    dot = "\n".join(G)
    counts = {k: len(v) for k, v in state.items() if isinstance(v, list)}
    print(json.dumps(counts))
    if a.dry_run: print(dot); return
    # ---- write the Version Graph page and decisions.json
    site = fedwiki.site_dir(a.site); slug = "version-graph"; path = fedwiki.page_path(a.site, slug)
    os.makedirs(f"{site}/assets/{slug}", exist_ok=True); json.dump(state, open(f"{site}/assets/{slug}/decisions.json", "w"), indent=1)
    rows = "\n".join(f"| [[{r['title']}]] | {r['kind']} | {r['id']} | {r.get('line', '')} | {(r.get('who') or {}).get('date', '')[:10]} |" for r in state["accepted"]) or "| none yet | | | | |"
    rej = "\n".join(f"| [[{r['title']}]] | {r['kind']} | {r.get('reason') or 'no reason given'} |" for r in state["rejected"]) or "| none yet | | |"
    pend = "\n".join(f"| [[{r['title']}]] | {r['kind']} | {r['age_days']} days |" for r in state["pending"] + state["expired"]) or "| none | | |"
    PROV = f"Generated by decisions.py from the review pages' ticks, {state['read_at']}; re-run after any decision"
    items = [
        f"The **Version Graph** is the accepted world as the decisions on this wiki have made it, drawn by `decisions.py` from the tick boxes on the review pages. Green is accepted, red is rejected, plain is waiting for a person. Every node is a page. Read at {state['read_at'][:16]} UTC; re-run the script after any decision and this page redraws itself.",
        {"type": "graphviz", "text": dot},
        "## How a tick becomes a decision\n\nA person ticks a line in a Decision section on a review page. The wiki writes that edit into the page's journal with the date and the editor's site, and the page is only editable by its owner. That journal entry is the [[Human Acceptance]] record: who, when, what. `decisions.py` reads the live page, finds the ticked line, reads the journal entry that carried it, and files the result here and in the [[World Soil]]. Nothing an agent renders acquires standing any other way.",
        "## Accepted",
        {"type": "table", "text": f"CAPTION Accepted, with the acceptance record\nLAYOUT stack\nKEY Page\nFOLD none\n\n| Page | Kind | Id | Line | When |\n|---|---|---|---|---|\n{rows}"},
        "## Rejected, to the Soil",
        {"type": "table", "text": f"CAPTION Rejected\nFIT\n\n| Page | Kind | Reason |\n|---|---|---|\n{rej}"},
        "## Waiting for a person",
        {"type": "table", "text": f"CAPTION Pending and expired\nFIT\n\n| Page | Kind | Age |\n|---|---|---|\n{pend}"},
        f"Proposals with no decision after {a.expire_days} days are listed as expired here and compost per [[Expiry and Composting]]; the pages stay, the standing does not.",
    ]
    pg = fedwiki.make_page("Version Graph", items, provenance=PROV)
    fedwiki.ensure_assets(pg, slug, journal=False)
    fedwiki.ensure_see(pg, ["[[Render Commons Plan]] · [[Human Acceptance]] · [[World Soil]] · [[Expiry and Composting]]",
                           "[[Propose a World Patch]] · [[Mice and Hitchhikers]] · [[Controlled Plurality]]"], journal=False)
    pg["journal"] = [fedwiki.create_entry("Version Graph", pg["story"], PROV)]
    fedwiki.save_page(path, pg); print("wrote", path)

if __name__ == "__main__":
    main()
