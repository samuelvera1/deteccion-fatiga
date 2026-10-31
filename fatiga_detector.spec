# fatiga_detector.spec -- receta de PyInstaller del monitor de fatiga (carpeta dist/FatigaDetector/).
# No se ejecuta a mano: python build.py (escribe build_info.json con la versión y el commit, compila y comprime).
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []
# MediaPipe trae sus modelos (.tflite) y grafos (.binarypb) como archivos de datos: hay que copiarlos enteros
# CustomTkinter trae temas (.json) y fuentes como archivos de datos
for package in ("mediapipe", "customtkinter"):
    package_datas, package_binaries, package_imports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_imports
datas += [("build_info.json", "."), ("assets/fatiga.ico", "assets"), ("assets/sounds", "assets/sounds")]

analysis = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    # matplotlib NO se excluye: mediapipe lo importa al cargar drawing_utils
    excludes=["tests", "IPython", "jupyter", "notebook", "pytest", "scipy", "pandas", "torch",
              "tensorflow", "jax", "jaxlib", "sounddevice", "ruff", "PyInstaller"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
# Dos ejecutables que comparten todo lo demás: el normal no abre la pantalla negra (consola) y escribe lo que
# imprimía en fatiga_detector.log; el de consola sirve para usar el programa desde una terminal (--help, --fuente...)
exes = [EXE(pyz, analysis.scripts, [], exclude_binaries=True, name=name, console=console, icon="assets/fatiga.ico",
            upx=False)
        for name, console in (("FatigaDetector", False), ("FatigaDetector-consola", True))]
coll = COLLECT(*exes, analysis.binaries, analysis.datas, upx=False, name="FatigaDetector")
