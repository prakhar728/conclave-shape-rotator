#!/usr/bin/env python3
"""Score RESOLUTION quality against the Codex gold (`*.expected.yaml`).

The over-merge guardrail only catches one failure mode. The gold is a
*resolution* gold (canonical -> the surface forms that should cluster), so it
catches BOTH:
  - homogeneity  : a predicted entity should hold surfaces from ONE gold entity
                   (penalises OVER-merge / black holes)
  - completeness : all of a gold entity's surfaces should land in ONE predicted
                   entity (penalises UNDER-merge / fragmentation)

Only surfaces that were BOTH extracted and listed in the gold are scored, so this
isolates resolution from extraction recall. Also prints obligation ("insights")
coverage per transcript.

Run against a DB re-ingested from the 3 gold transcripts (sessions named by slug):
    python scripts/eval/score_resolution_vs_gold.py --db /tmp/oi7_gold.db
"""
from __future__ import annotations

import argparse
import re
import sqlite3

import yaml
from sklearn.metrics import homogeneity_completeness_v_measure

GOLD = {
    "dstack-intro-salon": "tests/fixtures/transcripts/dstack-intro-salon.expected.yaml",
    "elocute": "tests/fixtures/transcripts/elocute.expected.yaml",
    "project-intros-agents-day3": "tests/fixtures/transcripts/project-intros-agents-day3.expected.yaml",
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="/tmp/oi7_gold.db")
    args = ap.parse_args(argv)
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    gold_labels, pred_clusters = [], []   # pooled across transcripts
    print("=== RESOLUTION vs GOLD (per gold entity: gold#surf -> predicted clusters) ===")
    for slug, path in GOLD.items():
        gold = yaml.safe_load(open(path))
        # gold surface -> gold canonical (namespaced per transcript)
        surf2gold = {}
        gold_surfs = {}
        for e in gold.get("entities", []):
            can = f"{slug}:{e['canonical_name']}"
            forms = set(_norm(m) for m in (e.get("raw_mentions") or [e["canonical_name"]]))
            gold_surfs[can] = forms
            for f in forms:
                surf2gold[f] = can

        # predicted: entity_id -> set(normalised raw_text) for this session
        pred = {}
        for r in conn.execute(
            "SELECT entity_id, raw_text FROM entity_mentions WHERE session_id = ?",
            (slug,),
        ):
            pred.setdefault(r["entity_id"], set()).add(_norm(r["raw_text"]))

        # surface (in gold) -> predicted entity id
        surf2pred = {}
        for eid, forms in pred.items():
            for f in forms:
                if f in surf2gold:
                    surf2pred[f] = eid

        # report fragmentation per gold entity (only over its EXTRACTED surfaces)
        frag_n = consolidated = 0
        for can, forms in sorted(gold_surfs.items()):
            extracted = [f for f in forms if f in surf2pred]
            if not extracted:
                continue
            clusters = set(surf2pred[f] for f in extracted)
            for f in extracted:
                gold_labels.append(can)
                pred_clusters.append(surf2pred[f])
            tag = "OK" if len(clusters) == 1 else f"SPLIT x{len(clusters)}"
            if len(clusters) == 1:
                consolidated += 1
            else:
                frag_n += 1
            if len(forms) >= 4 or len(clusters) > 1:   # show the interesting ones
                print(f"  [{slug[:14]:<14}] {can.split(':',1)[1][:28]:<28} "
                      f"gold {len(forms)}surf / {len(extracted)} extracted -> {len(clusters)} pred  [{tag}]")
        print(f"  -> {slug}: {consolidated} consolidated, {frag_n} fragmented\n")

    h, c, v = homogeneity_completeness_v_measure(gold_labels, pred_clusters)
    print("=== AGGREGATE (over extracted+gold surfaces) ===")
    print(f"  homogeneity  (1=no over-merge)   : {h:.3f}")
    print(f"  completeness (1=no under-merge)  : {c:.3f}")
    print(f"  V-measure                        : {v:.3f}")
    print(f"  surfaces scored: {len(gold_labels)}")

    print("\n=== INSIGHTS (obligations) coverage per transcript ===")
    for slug, path in GOLD.items():
        gold = yaml.safe_load(open(path))
        g_ob = len(gold.get("obligations", []))
        p_ob = conn.execute(
            "SELECT COUNT(*) FROM obligations WHERE session_id = ?", (slug,)
        ).fetchone()[0]
        print(f"  {slug:<30} gold {g_ob:>2} obligations | predicted {p_ob:>2}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
