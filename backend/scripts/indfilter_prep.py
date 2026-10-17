"""İndikatör filtresi çalışması — hazırlık: olaylar + 1 dk pencereler + oynaklık-eşleşmiş rastgele taban (work/indfilter/).

Kullanım (backend/): DATABASE_URL=... python scripts/indfilter_prep.py [--pop ha,notif]
"""
from __future__ import annotations

import argparse
import pickle
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import indfilter_common as K  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pop", default="notif,ha")
    ap.add_argument("--jsonl", default="work/rescan_90g_nogate.jsonl")
    ap.add_argument("--pkl", default="work/confirm_elems/events.pkl")
    args = ap.parse_args(argv)
    K.OUT.mkdir(parents=True, exist_ok=True)
    for pop in args.pop.split(","):
        if pop == "notif":
            ev, ticks = K.notif_events(args.pkl)
            blocks = K.notif_blocks()
        else:
            blocks = K.ha_blocks()
            ev, ticks = K.ha_events(args.jsonl, blocks[0][0], blocks[-1][1])
        print("[%s] olay %d, sembol %d" % (pop, len(ev["t_ms"]), len(set(ev["sym"].tolist()))), flush=True)
        pickle.dump(ev, open(K.OUT / ("events_%s.pkl" % pop), "wb"))
        K.prep_population(pop, ev, ticks, blocks, log=lambda m: print(m, flush=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
