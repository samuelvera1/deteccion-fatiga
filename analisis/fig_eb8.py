"""Figura: F1 de parpadeos por video de Eyeblink8 (análisis principal y con postura válida)."""
import glob
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

root = sys.argv[1]
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fig", "fig_eyeblink8.png")
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.spines.top": False,
                     "axes.spines.right": False, "savefig.dpi": 220, "savefig.bbox": "tight"})
rows = []
for path in glob.glob(os.path.join(root, "sesiones", "*_EB8_*")):
    rep = json.load(open(os.path.join(path, "evaluacion_eyeblink8.json"), encoding="utf-8"))
    vid = int(os.path.basename(path).split("_EB8_")[1])
    rows.append((vid, rep["principal"]["parpadeo"]["f1"], rep["secundario_parpadeos_postura_valida"]["f1"],
                 rep["principal"]["parpadeo"]["aciertos"] + rep["principal"]["parpadeo"]["falsos_negativos"]))
rows.sort()
x = np.arange(len(rows))
fig, ax = plt.subplots(figsize=(7.2, 3.4))
ax.bar(x - 0.19, [r[1] for r in rows], 0.36, color="#2563EB", label="Análisis principal")
ax.bar(x + 0.19, [r[2] for r in rows], 0.36, color="#EA580C", label="Solo postura válida y rostro detectado")
ax.set_xticks(x, [f"Video {r[0]}\n(n = {r[3]})" + ("\ngafas" if r[0] == 11 else "") for r in rows], fontsize=8.5)
ax.set_ylabel("F1 de parpadeos")
ax.set_ylim(0, 1.08)
ax.axhline(0.83, color="#2563EB", ls="--", lw=0.9)
ax.axhline(0.90, color="#EA580C", ls="--", lw=0.9)
ax.text(len(rows) - 0.5, 0.835, "total 0,83", color="#2563EB", fontsize=8, ha="right", va="bottom")
ax.text(len(rows) - 0.5, 0.905, "total 0,90", color="#EA580C", fontsize=8, ha="right", va="bottom")
ax.legend(loc="lower left", fontsize=8, frameon=False, ncol=2, bbox_to_anchor=(0, 1.0))
fig.savefig(out)
print(out)
