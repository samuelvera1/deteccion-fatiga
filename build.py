# build.py
"""Compila el ejecutable de Windows con PyInstaller y lo comprime para entregarlo.

    python build.py                # compila y crea el instalador y el .zip portátil en dist/
    python build.py --sin-zip      # solo compila (dist/FatigaDetector/FatigaDetector.exe) y el instalador
    python build.py --sin-instalador

El instalador (dist/FatigaDetector-Setup-<versión>.exe, un solo archivo) es lo que se entrega a quien use el programa;
necesita Inno Setup (winget install JRSoftware.InnoSetup). El .zip es la versión portátil: lleva un portable.txt, así
que guarda los datos junto al .exe en lugar de en Documentos.

Antes de compilar escribe build_info.json con la versión, el commit y los archivos con cambios sin commit: el
ejecutable no tiene git, y así cada sesión que haga queda ligada al commit del que salió. Para un ejecutable de
entrega, compila con el árbol limpio (sin cambios sin commit)."""
import argparse
import json
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime

import version

ROOT = os.path.dirname(os.path.abspath(__file__))
NAME = "FatigaDetector"


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=10).stdout


def write_build_info():
    # formato porcelain "XY ruta": no recortar la salida o se pierde la primera columna de estado
    changed = [line[3:] for line in git("status", "--porcelain", "--untracked-files=no").splitlines() if line]
    info = {"version": version.VERSION, "commit": git("rev-parse", "HEAD").strip() or None, "cambios_sin_commit": changed,
            "fecha": datetime.now().isoformat(timespec="seconds")}
    with open(os.path.join(ROOT, "build_info.json"), "w", encoding="utf-8") as f:
        json.dump(info, f, indent=1, ensure_ascii=False)
    return info


def write_readme(folder, info):
    with open(os.path.join(ROOT, "docs", "LEEME_ejecutable.txt"), encoding="utf-8") as f:
        text = f.read()
    text = text.replace("{VERSION}", info["version"]).replace("{COMMIT}", (info["commit"] or "desconocido")[:7])
    with open(os.path.join(folder, "LEEME.txt"), "w", encoding="utf-8") as f:
        f.write(text)


# Datos de participantes que nunca deben viajar dentro de la entrega, aunque alguien haya probado el .exe en la carpeta
PRIVATE = ("sesiones", "participantes_privado.csv", "fatiga_detector.log", "cache_revisor", "sonidos")


def find_iscc():
    """Compilador de Inno Setup, o None si no está instalado."""
    candidates = [os.path.join(base, "Inno Setup 6", "ISCC.exe") for base in (
        os.environ.get("ProgramFiles(x86)", ""), os.environ.get("ProgramFiles", ""),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs"))]
    return next((p for p in candidates if os.path.exists(p)), None)


def make_installer(info):
    iscc = find_iscc()
    if iscc is None:
        print("[AVISO] No se encontró Inno Setup: no se crea el instalador (winget install JRSoftware.InnoSetup).")
        return None
    subprocess.run([iscc, f"/DAppVersion={info['version']}", "/Qp", os.path.join(ROOT, "installer", "fatiga_detector.iss")],
                   cwd=ROOT, check=True)
    return os.path.join(ROOT, "dist", f"FatigaDetector-Setup-{info['version']}.exe")


def make_zip(folder, info):
    path = os.path.join(ROOT, "dist", f"{NAME}-{info['version']}-portatil.zip")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for base, dirs, files in os.walk(folder):
            if base == folder:
                dirs[:] = [d for d in dirs if d not in PRIVATE]
                files = [f for f in files if f not in PRIVATE]
            for file in files:
                full = os.path.join(base, file)
                archive.write(full, os.path.join(NAME, os.path.relpath(full, folder)))
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--sin-zip", action="store_true", help="no crear el .zip portátil")
    parser.add_argument("--sin-instalador", action="store_true", help="no crear el instalador")
    args = parser.parse_args()

    info = write_build_info()
    print(f"Versión {info['version']}, commit {(info['commit'] or '?')[:7]}")
    if info["cambios_sin_commit"]:
        print(f"[AVISO] Cambios sin commit en {info['cambios_sin_commit']}: el ejecutable NO será reproducible "
              f"desde ese commit. Haz commit antes de compilar una entrega.")
    try:
        subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "fatiga_detector.spec"],
                       cwd=ROOT, check=True)
    finally:
        os.remove(os.path.join(ROOT, "build_info.json"))
    folder = os.path.join(ROOT, "dist", NAME)
    write_readme(folder, info)
    # el editor de anotación remite a esta guía (definiciones de cada evento)
    os.makedirs(os.path.join(folder, "docs"), exist_ok=True)
    shutil.copy(os.path.join(ROOT, "docs", "guia_anotacion.md"), os.path.join(folder, "docs", "guia_anotacion.md"))
    size = sum(os.path.getsize(os.path.join(b, f)) for b, _, fs in os.walk(folder) for f in fs) / 1e6
    print(f"\nEjecutable: {os.path.join(folder, NAME + '.exe')}  ({size:.0f} MB)")
    if not args.sin_instalador:
        installer = make_installer(info)          # antes de portable.txt: el instalador no debe llevarlo
        if installer:
            print(f"Instalador: {installer}  ({os.path.getsize(installer) / 1e6:.0f} MB)")
    # marca de versión portátil: el programa guarda sus datos junto al .exe (también sirve para las pruebas)
    with open(os.path.join(folder, "portable.txt"), "w", encoding="utf-8") as f:
        f.write("Versión portátil: Fatiga Detector guarda sus datos (sesiones, registro) junto a FatigaDetector.exe.\n"
                "Borra este archivo para que los guarde en Documentos\\Fatiga Detector.\n")
    if not args.sin_zip:
        print(f"Portátil:   {make_zip(folder, info)}")


if __name__ == "__main__":
    main()
