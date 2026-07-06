#!/usr/bin/env python3
"""
Script de compilación para MkPFS GUI (PyQt6)
Genera un solo ejecutable .exe con PyInstaller.
Incluye el icono para el .exe.
Las carpetas 'payloads' y 'payloads_botones' se excluyen intencionalmente.
Incluye payload_sender.py como módulo empaquetado.
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path

def clean_build():
    """Elimina directorios anteriores de compilación."""
    dirs = ["build", "dist"]
    for d in dirs:
        path = Path(d)
        if path.exists():
            shutil.rmtree(path)
            print(f"🧹 Eliminado: {d}")

def build():
    """Ejecuta PyInstaller con las opciones adecuadas."""
    # Asegurarse de que PyInstaller está instalado
    try:
        import PyInstaller
    except ImportError:
        print("❌ PyInstaller no está instalado. Ejecuta: pip install pyinstaller")
        sys.exit(1)

    # Nombre del script principal
    main_script = "mkpfs_gui.py"
    if not Path(main_script).exists():
        print(f"❌ No se encuentra el script '{main_script}'")
        sys.exit(1)

    # Verificar que existe el archivo de icono
    icon_file = Path("icon.ico")
    icon_option = []
    if icon_file.exists() and icon_file.stat().st_size > 0:
        icon_option = ["--icon", str(icon_file.absolute())]
        print(f"✅ Icono encontrado: {icon_file.absolute()}")
    else:
        print(f"⚠️ No se encuentra 'icon.ico' o está vacío. Se compilará sin icono personalizado.")

    # Verificar que existe payload_sender.py
    payload_file = Path("payload_sender.py")
    payload_add = []
    if payload_file.exists():
        payload_add = ["--add-data", f"payload_sender.py{os.pathsep}."]
        print(f"✅ payload_sender.py encontrado. Se incluirá en el ejecutable.")
    else:
        print(f"⚠️ No se encuentra 'payload_sender.py'. La funcionalidad de envío de payloads no estará disponible.")

    # Comando base
    cmd = [
        "pyinstaller",
        "--paths", str(Path.cwd()),
        "--onefile",
        "--windowed",
        "--name", "MkPFS",
        "--add-data", f"logo.png{os.pathsep}.",
        "--add-data", f"build_ampr_index.py{os.pathsep}.",
        "--collect-all", "mkpfs",
        "--collect-all", "cryptography",
        "--collect-all", "zlib_ng",
        "--hidden-import", "PyQt6",
        "--hidden-import", "payload_sender",
        "--exclude-module", "tkinter",
        "--exclude-module", "test",
        "--exclude-module", "unittest",
        "--clean",
        "--noconfirm",
        *icon_option,
        *payload_add,
        main_script
    ]

    print("🚀 Iniciando compilación...")
    print("Comando:", " ".join(cmd))
    result = subprocess.run(cmd)

    if result.returncode == 0:
        print("\n✅ ¡Compilación exitosa!")
        exe_path = Path("dist") / "MkPFS.exe"
        print(f"📁 Ejecutable generado en: {exe_path}")
        if icon_option:
            print("✅ El icono personalizado ha sido incrustado.")
        else:
            print("⚠️ No se incrustó icono (archivo .ico no encontrado).")
        if payload_file.exists():
            print("✅ payload_sender.py ha sido incluido en el ejecutable.")
        else:
            print("⚠️ payload_sender.py no se incluyó porque no se encontró.")
        print("\n📌 Recuerda colocar las carpetas 'payloads' y 'payloads_botones' junto al .exe.")
    else:
        print("\n❌ La compilación falló. Revisa los mensajes de error.")
        sys.exit(1)

if __name__ == "__main__":
    clean_build()
    build()