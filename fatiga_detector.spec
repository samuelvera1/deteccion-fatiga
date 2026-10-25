# fatiga_detector.spec -- receta de PyInstaller del monitor de fatiga (carpeta dist/FatigaDetector/).
# No se ejecuta a mano: python build.py (escribe build_info.json con la versión y el commit, compila y comprime).
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []
# MediaPipe trae sus modelos (.tflite) y grafos (.binarypb) como archivos de datos: hay que copiarlos enteros
for package in ("mediapipe",):
    package_datas, package_binaries, package_imports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_imports
datas += [("build_info.json", ".")]

analysis = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    # matplotlib NO se excluye: mediapipe lo importa al cargar drawing_utils
    excludes=["tkinter", "tests", "IPython", "jupyter", "notebook", "pytest", "scipy", "pandas", "torch",
              "tensorflow", "jax", "jaxlib", "sounddevice", "ruff", "PyInstaller"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="FatigaDetector",
    console=True,            # el resumen y los avisos se muestran en la consola
    upx=False,
)
coll = COLLECT(exe, analysis.binaries, analysis.datas, upx=False, name="FatigaDetector")
