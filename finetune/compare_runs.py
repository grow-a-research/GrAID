"""
compare_runs.py — side-by-side of two eval_adapter.py result files (CPU only).

    python finetune/compare_runs.py base_live.json adapter_live.json

Prints headline metrics for each run, which identification items the second
run fixed or broke, and the mean character divergence between the two runs'
outputs on the same crops. The divergence is NOT an error rate; it is a
regression guard for data with no ground truth (e.g. essay lines): a large
number means the adapter reads those crops very differently from the base and
deserves a manual look.
"""
from __future__ import annotations

import json
import sys

from common import cer


def _load(p: str) -> dict:
    return json.load(open(p, encoding="utf-8"))


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    a, b = _load(sys.argv[1]), _load(sys.argv[2])
    print(f"A = {a['label']} ({a['prompt_mode']} prompt, adapter={a['adapter']})")
    print(f"B = {b['label']} ({b['prompt_mode']} prompt, adapter={b['adapter']})\n")

    ia, ib = a.get("identification"), b.get("identification")
    if ia and ib:
        print(f"Identification accuracy:  A {ia['accuracy']:.1%}   B {ib['accuracy']:.1%}   "
              f"(n={ia['n']}/{ib['n']})")
        print(f"Identification abstain:   A {ia['abstain_rate']:.1%}   B {ib['abstain_rate']:.1%}")
        ma = {i["item_id"]: i for i in ia["items"]}
        fixed = [k for k, i in {i["item_id"]: i for i in ib["items"]}.items()
                 if i["correct"] and k in ma and not ma[k]["correct"]]
        broken = [k for k, i in {i["item_id"]: i for i in ib["items"]}.items()
                  if not i["correct"] and k in ma and ma[k]["correct"]]
        print(f"  fixed by B: {len(fixed)}   broken by B: {len(broken)}")
        for k in broken[:10]:
            print(f"    broken {k}: A={ma[k]['got']!r}")
        div = [cer(ma[i['item_id']]['got'], i['got']) for i in ib["items"] if i["item_id"] in ma]
        if div:
            print(f"  mean output divergence A vs B: {sum(div) / len(div):.3f}")
        print()

    for src in sorted(set(a.get("manifest", {})) & set(b.get("manifest", {}))):
        ma, mb = a["manifest"][src], b["manifest"][src]
        print(f"[{src}] n={ma['n']}/{mb['n']}")
        for k in ("cer", "cer_ci", "wer", "exact", "false_abstain_rate"):
            print(f"    {k:20s} A {ma[k]:.3f}   B {mb[k]:.3f}")
        if ma.get("illegible_abstained") is not None or mb.get("illegible_abstained") is not None:
            print(f"    illegible abstained   A {ma.get('illegible_abstained')}   "
                  f"B {mb.get('illegible_abstained')}")
        ia_ = {i["id"]: i["got"] for i in ma["items"]}
        div = [cer(ia_[i["id"]], i["got"]) for i in mb["items"] if i["id"] in ia_]
        if div:
            print(f"    mean output divergence A vs B: {sum(div) / len(div):.3f}")
        print()


if __name__ == "__main__":
    main()
