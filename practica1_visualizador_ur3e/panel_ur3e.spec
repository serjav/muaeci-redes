# PyInstaller build of the web UI. From practica1_visualizador_ur3e/:
#   pyinstaller panel_ur3e.spec
# Result: dist/panel_ur3e/ (zip the whole folder; sequences are saved in its data/ folder).
from PyInstaller.utils.hooks import collect_data_files

a = Analysis(
    ["src/visualizador_ur3e/web/interfaz_web.py"],
    pathex=["src"],
    datas=[
        ("src/visualizador_ur3e/web/interfaz", "interfaz"),  # web page
        *collect_data_files("UR3e_rg2"),  # robot URDF and meshes
    ],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="panel_ur3e", console=True)  # console shows the logs
coll = COLLECT(exe, a.binaries, a.datas, name="panel_ur3e")
