"""E4b: procesa una parte de UTA-RLDD (un .zip o una carpeta ya extraída) con la versión actual del sistema.
Solo los videos alerta (0) y somnoliento (10). Con un .zip extrae cada video a una carpeta temporal, lo analiza y
lo borra; las sesiones (traza, eventos, metadatos) quedan en eval_rldd_b. 4 análisis en paralelo.
Uso: python rldd_pipeline.py RUTA_ZIP_O_CARPETA [--borrar-zip]"""
import os
import re
import shutil
import subprocess
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor

REPO = r"C:\Users\Practicante\Downloads\vision computacional"
PY = os.path.join(REPO, "venv", "Scripts", "python.exe")
CODE = r"C:\Users\Practicante\Documents\datasets\e4b_code"   # copia congelada (COMMIT.txt): E4b con una sola versión
WORK = r"C:\Users\Practicante\Documents\datasets\eval_rldd_b"
TMP = r"C:\Users\Practicante\Documents\datasets\rldd_tmp"
LABELS = {"0", "10"}
PATTERN = re.compile(r"(?:^|/)(Fold\d+_part\d+)/(\d+)/(\d+)\.(mov|mp4|m4v|avi)$", re.IGNORECASE)


def jobs_from_zip(path):
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            m = PATTERN.search(info.filename.replace("\\", "/"))
            if m and m.group(3) in LABELS:
                yield m.group(1), m.group(2), m.group(3), info.filename


def jobs_from_folder(path):
    fold = os.path.basename(os.path.normpath(path))
    for subj in sorted(os.listdir(path)):
        folder = os.path.join(path, subj)
        if not os.path.isdir(folder):
            continue
        for name in os.listdir(folder):
            stem, ext = os.path.splitext(name)
            if stem in LABELS and ext.lower() in (".mov", ".mp4", ".m4v", ".avi"):
                yield fold, subj, stem, os.path.join(folder, name)


def already_done(tag):
    sessions = os.path.join(WORK, "sesiones")
    return os.path.isdir(sessions) and any(d.endswith(tag) and os.path.exists(os.path.join(sessions, d, "metadata.json"))
                                           and '"resumen"' in open(os.path.join(sessions, d, "metadata.json"),
                                                                   encoding="utf-8").read()
                                           for d in os.listdir(sessions))


def run(job, source_zip):
    fold, subj, label, member = job
    tag = f"RLDD_{fold}_{subj}_{label}"
    if already_done(tag):
        return f"{tag}: ya estaba"
    video, extracted = member, None
    if source_zip:
        target = os.path.join(TMP, fold, subj)
        os.makedirs(target, exist_ok=True)
        with zipfile.ZipFile(source_zip) as zf, zf.open(member) as src:
            extracted = os.path.join(target, f"{label}{os.path.splitext(member)[1]}")
            with open(extracted, "wb") as dst:
                shutil.copyfileobj(src, dst, 16 * 1024 * 1024)
        video = extracted
    with open(os.path.join(WORK, "logs", f"{tag}.log"), "w", encoding="utf-8") as log:
        code = subprocess.call([PY, os.path.join(CODE, "main.py"), "--fuente", video, "--sujeto", tag, "--sin-sonido",
                                "--calibracion-auto", "--sin-ventana"], cwd=WORK, stdout=log, stderr=subprocess.STDOUT,
                               env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    if extracted:
        os.remove(extracted)
    return f"{tag}: código {code}"


def main():
    source = sys.argv[1]
    os.makedirs(os.path.join(WORK, "logs"), exist_ok=True)
    is_zip = source.lower().endswith(".zip")
    jobs = list(jobs_from_zip(source) if is_zip else jobs_from_folder(source))
    print(f"{len(jobs)} videos (alerta y somnoliento) en {os.path.basename(source)}", flush=True)
    with ThreadPoolExecutor(4) as pool:
        for line in pool.map(lambda j: run(j, source if is_zip else None), jobs):
            print(line, flush=True)
    if is_zip and "--borrar-zip" in sys.argv:
        os.remove(source)
        print("zip borrado", flush=True)
    shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    main()
