#!/usr/bin/env python3
"""
MkPFS GUI – Versión PyQt6
Actualizado para núcleo v0.0.9 (exFAT nativo, compresión en un solo paso).
Elimina dependencia de OSFMount, scripts externos y preflight obsoleto.
Mantiene la misma interfaz: pestañas de Conversión y Payload Sender.
Mejoras en Payload Sender: botón para seleccionar payload arbitrario,
separación de carpetas (payloads_botones para botones rápidos, payloads para lista manual).
Mejoras visuales: barra azul superior con logo y título "MKPFS 🎮".
Corrección: el logo se carga correctamente desde el ejecutable compilado.

MODIFICACIÓN PRINCIPAL (Opción 2 mejorada):
- Se añade modo "--worker" para ejecutar la conversión en un subproceso sin GUI.
- El proceso padre lanza el mismo ejecutable o script con "--worker" y argumentos.
- El worker imprime líneas estructuradas (PROGRESS|, STATUS|) para actualizar la GUI.
- Se elimina la generación de scripts temporales y la dependencia de sys.executable para scripts.
- Se corrige el error "Unknown option: --worker" al ejecutar en modo desarrollo.
- Se elimina el parámetro 'progress' de las llamadas al núcleo (no soportado en v0.0.9).
"""

import sys
import os
import ctypes
import tempfile
import shutil
import time
import traceback
import subprocess
import threading
import queue
import argparse
from pathlib import Path

# ---- MANEJO DE ERRORES: imprimir en consola y esperar ----
def print_error_and_wait(exc_type, exc_value, exc_tb) -> None:
    tb_lines = traceback.format_exception(exc_type, exc_value, exc_tb)
    error_msg = "".join(tb_lines)
    print("=" * 70, file=sys.stderr)
    print("ERROR FATAL en MkPFS GUI:", file=sys.stderr)
    print(error_msg, file=sys.stderr)
    print("=" * 70, file=sys.stderr)
    try:
        input("Presiona Enter para salir...")
    except KeyboardInterrupt:
        pass
    sys.exit(1)

sys.excepthook = print_error_and_wait

# ---- AUTO-ELEVACIÓN (WINDOWS) ----
def is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False

def elevate_and_restart() -> None:
    script = os.path.abspath(sys.argv[0])
    params = " ".join(f'"{arg}"' for arg in sys.argv[1:])
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, f'"{script}" {params}', None, 1
    )
    sys.exit()

if sys.platform == "win32" and not is_admin():
    elevate_and_restart()
# ------------------------------------------------

# ---- IMPORTACIONES DE QT (solo en modo GUI) ----
try:
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QLineEdit, QPushButton, QComboBox, QSpinBox, QCheckBox,
        QProgressBar, QGroupBox, QFileDialog, QMessageBox, QTabWidget,
        QTextEdit, QListWidget, QSplitter, QFrame, QGridLayout, QListWidgetItem
    )
    from PyQt6.QtCore import Qt, QThread, pyqtSignal, QMutex, QObject, QTimer
    from PyQt6.QtGui import QIntValidator, QPixmap, QFont
except ImportError as e:
    print(f"Error de importación: {e}", file=sys.stderr)
    input("Presiona Enter para salir...")
    sys.exit(1)

# ---- IMPORTACIONES DEL NÚCLEO MkPFS ----
try:
    from mkpfs.utils import human_readable_size
    from mkpfs.logging import info, warning, error
    from mkpfs.exfat_writer import write_exfat_image
    from mkpfs.pfs import (
        build_pfs,
        build_pfs_stream_from_exfat,
        build_pfs_stream_single_file,
        BuildStats,
        BuildError,
    )
    from mkpfs.pbar import Progress
    try:
        from mkpfs.consts import PFSC_LOGICAL_BLOCK_SIZE
    except ImportError:
        PFSC_LOGICAL_BLOCK_SIZE = 0x10000
except ImportError as e:
    print(f"Error de importación del núcleo MkPFS: {e}", file=sys.stderr)
    input("Presiona Enter para salir...")
    sys.exit(1)

try:
    import payload_sender
except ImportError:
    payload_sender = None


# ============================================================================
# 0. PROGRESS PARA SALIDA ESTÁNDAR (MODO WORKER) - NO SE USA DIRECTAMENTE
#    (se mantiene por si se quiere usar en el futuro, pero no se pasa al núcleo)
# ============================================================================
class StdoutProgress(Progress):
    def __init__(self, enabled: bool = True, width: int = 32) -> None:
        super().__init__(enabled=enabled, width=width)
        self._start_time = time.time()

    def step(self, phase: str, done: int, total: int, bytes_processed: int = 0) -> None:
        super().step(phase, done, total, bytes_processed)
        pct = (done / total) * 100.0 if total > 0 else 0.0
        sys.stdout.write(f"PROGRESS|{pct:.2f}|{phase}\n")
        sys.stdout.flush()

    def status(self, message: str) -> None:
        super().status(message)
        sys.stdout.write(f"STATUS|{message}\n")
        sys.stdout.flush()


# ============================================================================
# 0b. FUNCIÓN DE CONVERSIÓN PARA MODO WORKER (SIN PASAR PROGRESS)
# ============================================================================
def run_conversion_task(
    src_path: Path,
    dest_path: Path,
    format_type: str,
    compression_level: int = 5,
    cpu_count: int = 0,
    silent: bool = False,
    zlib_backend: str = "zlib",
    use_ram: bool = True,
    cluster_size: str = "Auto",
    temp_folder: Path | None = None,
) -> None:
    """
    Ejecuta la conversión llamando directamente a las funciones del núcleo.
    No se pasa el parámetro 'progress' porque el núcleo v0.0.9 no lo soporta.
    El núcleo imprime su propio progreso en stdout/stderr, que el padre capturará.
    """
    # No usamos StdoutProgress porque el núcleo no lo acepta.
    # Simplemente llamamos a las funciones sin el argumento progress.

    is_dir = src_path.is_dir()

    # ===== exFAT =====
    if format_type == "exfat":
        cluster_int = None
        if cluster_size.lower() != "auto":
            try:
                cluster_int = int(cluster_size)
            except ValueError:
                pass
        write_exfat_image(
            source_root=src_path,
            output_path=dest_path,
            cluster_size=cluster_int,
            # progress NO se pasa (no soportado)
        )
        return

    # ===== ffpfsc (comprimido) =====
    if format_type == "ffpfsc":
        if is_dir:
            build_pfs_stream_from_exfat(
                source_root=src_path,
                output_path=dest_path,
                block_size=PFSC_LOGICAL_BLOCK_SIZE,
                pfs_version=2,
                case_insensitive=True,
                zlib_level=compression_level,
                threshold_gain=0,
                cpu_count=cpu_count,
                encrypted=False,
                verbose=not silent,
                # progress NO se pasa
            )
        else:
            build_pfs_stream_single_file(
                source_file=src_path,
                output_path=dest_path,
                block_size=PFSC_LOGICAL_BLOCK_SIZE,
                pfs_version=2,
                case_insensitive=True,
                zlib_level=compression_level,
                threshold_gain=0,
                min_file_gain=0,
                min_compress_size=0,
                cpu_count=cpu_count,
                compress=True,
                encrypted=False,
                verbose=not silent,
                # progress NO se pasa
            )
        return

    # ===== ffpfs (sin comprimir) =====
    if format_type == "ffpfs":
        if is_dir:
            build_pfs(
                source_root=src_path,
                output_path=dest_path,
                block_size=PFSC_LOGICAL_BLOCK_SIZE,
                pfs_version=2,
                inode_bits=32,
                case_insensitive=True,
                signed=False,
                compress=False,
                threshold_gain=0,
                cpu_count=cpu_count,
                zlib_level=0,
                dry_run=False,
                verbose=not silent,
                # progress NO se pasa
            )
        else:
            build_pfs_stream_single_file(
                source_file=src_path,
                output_path=dest_path,
                block_size=PFSC_LOGICAL_BLOCK_SIZE,
                pfs_version=2,
                case_insensitive=True,
                zlib_level=0,
                threshold_gain=0,
                min_file_gain=0,
                min_compress_size=0,
                cpu_count=1,
                compress=False,
                encrypted=False,
                verbose=not silent,
                # progress NO se pasa
            )
        return

    raise ValueError(f"Formato desconocido: {format_type}")


def worker_main(argv: list[str]) -> None:
    """
    Punto de entrada para el modo worker. Parsea argumentos y ejecuta la tarea.
    """
    parser = argparse.ArgumentParser(description="MkPFS Worker")
    parser.add_argument("--worker", action="store_true", help="(ignorado)")
    parser.add_argument("--src", required=True, help="Ruta origen (archivo o carpeta)")
    parser.add_argument("--dest", required=True, help="Ruta destino")
    parser.add_argument("--format", required=True, choices=["exfat", "ffpfsc", "ffpfs"])
    parser.add_argument("--compression", type=int, default=5)
    parser.add_argument("--cpu", type=int, default=0)
    parser.add_argument("--silent", action="store_true")
    parser.add_argument("--zlib-backend", default="zlib")
    parser.add_argument("--use-ram", action="store_true")
    parser.add_argument("--cluster", default="Auto")
    parser.add_argument("--temp", default=None, help="Carpeta temporal (opcional)")

    args, unknown = parser.parse_known_args(argv[1:])

    src_path = Path(args.src)
    dest_path = Path(args.dest)
    temp_folder = Path(args.temp) if args.temp else None

    try:
        run_conversion_task(
            src_path=src_path,
            dest_path=dest_path,
            format_type=args.format,
            compression_level=args.compression,
            cpu_count=args.cpu,
            silent=args.silent,
            zlib_backend=args.zlib_backend,
            use_ram=args.use_ram,
            cluster_size=args.cluster,
            temp_folder=temp_folder,
        )
        sys.exit(0)
    except Exception as e:
        print(f"ERROR en worker: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)


# ============================================================================
# 1. PROGRESS PERSONALIZADO PARA Qt (se mantiene igual, solo para referencia)
# ============================================================================
class QtProgress(Progress, QObject):
    progress_signal = pyqtSignal(float, str)
    phase_signal = pyqtSignal(str, int)
    log_signal = pyqtSignal(str)
    stats_signal = pyqtSignal(dict)

    def __init__(self, enabled: bool = True, width: int = 32, parent: QObject | None = None) -> None:
        Progress.__init__(self, enabled=enabled, width=width)
        QObject.__init__(self, parent)
        self._start_time: float = time.time()
        self._phase_index_map: dict[str, int] = {
            "scan": 0,
            "exfat": 1,
            "compress": 2,
            "verify": 3,
            "write": 4,
            "move": 4,
        }

    def step(self, phase: str, done: int, total: int, bytes_processed: int = 0) -> None:
        super().step(phase, done, total, bytes_processed)
        pct = (done / total) * 100.0 if total > 0 else 0.0
        self.progress_signal.emit(pct, phase)
        phase_lower = phase.lower()
        for key, idx in self._phase_index_map.items():
            if key in phase_lower:
                self.phase_signal.emit(phase, idx)
                break
        elapsed = time.time() - self._start_time
        if elapsed > 0.1 and bytes_processed > 0:
            speed = bytes_processed / elapsed
            eta = 0.0
            if done < total and done > 0:
                eta = (total - done) * elapsed / done
            self.stats_signal.emit({
                "speed": speed,
                "eta": eta,
                "elapsed": elapsed,
                "percent": pct,
            })

    def status(self, message: str) -> None:
        super().status(message)
        self.log_signal.emit(message)


# ============================================================================
# 2. WORKER PARA CONVERSIÓN (LANZA SUBPROCESO CON --worker)
# ============================================================================
class ConversionWorker(QThread):
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(float, str)
    phase_signal = pyqtSignal(str, int)
    stats_signal = pyqtSignal(dict)
    finished_signal = pyqtSignal(bool, str)

    def __init__(
        self,
        src_path: Path,
        dest_path: Path,
        format_type: str,
        temp_folder: Path | None = None,
        compression_level: int = 5,
        cpu_count: int = 0,
        silent: bool = False,
        zlib_backend: str = "zlib",
        use_ram: bool = True,
        cluster_size: str = "Auto",
    ):
        super().__init__()
        self.src_path = src_path
        self.dest_path = dest_path
        self.format_type = format_type
        self.temp_folder = temp_folder
        self.compression_level = compression_level
        self.cpu_count = cpu_count
        self.silent = silent
        self.zlib_backend = zlib_backend
        self.use_ram = use_ram
        self.cluster_size = cluster_size
        self._cancel = False
        self._mutex = QMutex()
        self._process = None
        self._reader_thread = None
        self._stop_reader = False

    def cancel(self) -> None:
        self._mutex.lock()
        self._cancel = True
        self._mutex.unlock()
        if self._process is not None and self._process.poll() is None:
            self._process.terminate()
            time.sleep(0.5)
            if self._process.poll() is None:
                self._process.kill()
            self._stop_reader = True

    def _parse_line(self, line: str) -> None:
        """Interpreta líneas del worker y emite las señales correspondientes."""
        if line.startswith("PROGRESS|"):
            parts = line.split("|")
            if len(parts) >= 3:
                try:
                    pct = float(parts[1])
                    phase = parts[2]
                    self.progress_signal.emit(pct, phase)
                except ValueError:
                    self.log_signal.emit(line)
            else:
                self.log_signal.emit(line)
        elif line.startswith("STATUS|"):
            msg = line[7:]
            self.log_signal.emit(msg)
        else:
            # Cualquier otra línea se muestra como log
            self.log_signal.emit(line)

    def _reader_loop(self) -> None:
        """Hilo que lee la salida estándar del subproceso."""
        while not self._stop_reader:
            if self._process is None or self._process.stdout is None:
                break
            line = self._process.stdout.readline()
            if not line:
                break
            line = line.rstrip()
            if line:
                self._parse_line(line)
        # Leer lo que haya quedado en el buffer
        if self._process and self._process.stdout:
            for line in self._process.stdout.readlines():
                line = line.rstrip()
                if line:
                    self._parse_line(line)

    def run(self) -> None:
        try:
            # Construir la línea de comandos para el modo worker
            if getattr(sys, 'frozen', False):
                cmd = [sys.executable, "--worker"]
            else:
                cmd = [sys.executable, __file__, "--worker"]

            cmd.extend([
                "--src", str(self.src_path),
                "--dest", str(self.dest_path),
                "--format", self.format_type,
                "--compression", str(self.compression_level),
                "--cpu", str(self.cpu_count),
                "--cluster", self.cluster_size,
            ])
            if self.silent:
                cmd.append("--silent")
            if self.use_ram:
                cmd.append("--use-ram")
            if self.zlib_backend:
                cmd.extend(["--zlib-backend", self.zlib_backend])
            if self.temp_folder:
                cmd.extend(["--temp", str(self.temp_folder)])

            self.log_signal.emit(f"[INFO] Lanzando worker: {' '.join(cmd)}")

            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                bufsize=1,
            )

            self._stop_reader = False
            self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
            self._reader_thread.start()

            while self._process.poll() is None:
                time.sleep(0.1)
                if self._cancel:
                    self._process.terminate()
                    time.sleep(0.5)
                    if self._process.poll() is None:
                        self._process.kill()
                    self._stop_reader = True
                    self.finished_signal.emit(False, "Operación cancelada por el usuario")
                    if self._reader_thread and self._reader_thread.is_alive():
                        self._reader_thread.join(timeout=1)
                    return

            exitcode = self._process.poll()
            self._stop_reader = True
            if self._reader_thread and self._reader_thread.is_alive():
                self._reader_thread.join(timeout=1)

            if self._process.stdout:
                for line in self._process.stdout.readlines():
                    line = line.rstrip()
                    if line:
                        self._parse_line(line)

            if exitcode == 0:
                self.finished_signal.emit(True, f"Imagen creada correctamente: {self.dest_path}")
            else:
                self.finished_signal.emit(False, f"El proceso finalizó con código {exitcode}")

        except Exception as e:
            self.log_signal.emit(f"[EXCEPTION] {str(e)}")
            traceback.print_exc()
            self.finished_signal.emit(False, f"Error inesperado: {e}")


# ============================================================================
# 3. WORKER PAYLOAD SENDER (sin cambios)
# ============================================================================
class PayloadWorker(QThread):
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, ip, port, filepath="", mode="auto", use_socat=False, command=None):
        super().__init__()
        self.ip = ip
        self.port = int(port)
        self.filepath = filepath
        self.mode = mode
        self.use_socat = use_socat
        self.command = command

    def run(self):
        if payload_sender is None:
            self.log_signal.emit("[ERROR] payload_sender.py no está disponible")
            self.finished_signal.emit(False, "payload_sender.py no está disponible")
            return

        try:
            if self.command is not None:
                success = payload_sender.send_command(self.ip, self.port, self.command, self.log_signal.emit)
                if success:
                    self.log_signal.emit("[OK] Comando enviado correctamente")
                    self.finished_signal.emit(True, f"Comando {'enable' if self.command == 1 else 'disable'} enviado")
                else:
                    self.log_signal.emit("[ERROR] Fallo al enviar comando")
                    self.finished_signal.emit(False, "Error al enviar comando")
            else:
                success = payload_sender.send_payload(
                    self.ip, self.port, self.filepath,
                    mode=self.mode,
                    output_callback=self.log_signal.emit,
                    use_socat=self.use_socat
                )
                if success:
                    self.log_signal.emit("[OK] Payload enviado con éxito")
                    self.finished_signal.emit(True, "Payload enviado con éxito")
                else:
                    self.log_signal.emit("[ERROR] Fallo al enviar payload")
                    self.finished_signal.emit(False, "Error al enviar payload")
        except Exception as e:
            self.log_signal.emit(f"[EXCEPTION] {str(e)}")
            self.finished_signal.emit(False, str(e))


# ============================================================================
# 4. PESTAÑA DE CONVERSIÓN (sin cambios significativos)
# ============================================================================
class ConversionTab(QWidget):
    log_signal = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._worker = None
        self._running = False
        self._current_format = "ffpfsc"
        self._phase_labels = ["Scan", "Create exFAT", "Compress", "Verify", "Move"]
        self._phase_widgets = []
        self._start_time = 0
        self._last_percent = 0
        self._speed = 0.0
        self._eta = 0
        self._elapsed = 0
        self._timer = QTimer()
        self._timer.timeout.connect(self._update_elapsed)

        self.setup_ui()

    def setup_ui(self):
        main_layout = QHBoxLayout(self)

        # ---- Panel izquierdo ----
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)

        group_source = QGroupBox("🎯 Seleccionar juego")
        left_layout.addWidget(group_source)
        source_layout = QVBoxLayout(group_source)
        self.source_edit = QLineEdit()
        self.source_edit.setPlaceholderText("Ruta de la carpeta o archivo")
        source_layout.addWidget(self.source_edit)

        btn_layout = QHBoxLayout()
        btn_file = QPushButton("📂 Cargar archivo")
        btn_file.clicked.connect(self.browse_file)
        btn_folder = QPushButton("📁 Cargar carpeta")
        btn_folder.clicked.connect(self.browse_folder)
        btn_layout.addWidget(btn_file)
        btn_layout.addWidget(btn_folder)
        source_layout.addLayout(btn_layout)

        group_format = QGroupBox("📦 Formato de salida")
        left_layout.addWidget(group_format)
        format_layout = QHBoxLayout(group_format)
        self.format_buttons = []
        formats = [
            ("ffpfsc", "📦 .ffpfsc (Comprimido, recomendado)"),
            ("ffpfs", "📄 .ffpfs (Sin comprimir)"),
            ("exfat", "💾 .exfat (Imagen exFAT)"),
        ]
        for value, label in formats:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setAutoExclusive(True)
            btn.setProperty("format", value)
            btn.clicked.connect(lambda checked, v=value: self.select_format(v))
            btn.setStyleSheet("font-size: 11pt; padding: 8px 12px;")
            format_layout.addWidget(btn)
        format_layout.addStretch()

        group_dest = QGroupBox("📁 Guardar como")
        left_layout.addWidget(group_dest)
        dest_layout = QHBoxLayout(group_dest)
        self.dest_edit = QLineEdit()
        self.dest_edit.setPlaceholderText("Ruta de destino")
        dest_layout.addWidget(self.dest_edit)
        btn_dest = QPushButton("💾 Guardar como")
        btn_dest.clicked.connect(self.browse_dest)
        dest_layout.addWidget(btn_dest)

        group_temp = QGroupBox("📁 Carpeta temporal")
        left_layout.addWidget(group_temp)
        temp_layout = QVBoxLayout(group_temp)
        self.use_system_temp = QCheckBox("Usar carpeta temporal del sistema (recomendado)")
        self.use_system_temp.setChecked(True)
        self.use_system_temp.toggled.connect(self.toggle_temp_folder)
        temp_layout.addWidget(self.use_system_temp)
        temp_path_layout = QHBoxLayout()
        self.temp_edit = QLineEdit()
        self.temp_edit.setEnabled(False)
        self.temp_edit.setPlaceholderText("Ruta personalizada")
        temp_path_layout.addWidget(self.temp_edit)
        self.browse_temp_btn = QPushButton("📂 Examinar")
        self.browse_temp_btn.setEnabled(False)
        self.browse_temp_btn.clicked.connect(self.browse_temp_folder)
        temp_path_layout.addWidget(self.browse_temp_btn)
        temp_layout.addLayout(temp_path_layout)

        group_advanced = QGroupBox("⚙️ Opciones avanzadas (compresión)")
        left_layout.addWidget(group_advanced)
        adv_layout = QVBoxLayout(group_advanced)

        backend_layout = QHBoxLayout()
        backend_layout.addWidget(QLabel("Backend zlib:"))
        self.backend_combo = QComboBox()
        self.backend_combo.addItems(["zlib", "zlib-ng", "isa-l"])
        self.backend_combo.setCurrentText("zlib")
        backend_layout.addWidget(self.backend_combo)
        adv_layout.addLayout(backend_layout)

        cpu_layout = QHBoxLayout()
        cpu_layout.addWidget(QLabel("Núcleos CPU (0=auto):"))
        self.cpu_spin = QSpinBox()
        self.cpu_spin.setRange(0, 64)
        self.cpu_spin.setValue(0)
        cpu_layout.addWidget(self.cpu_spin)
        adv_layout.addLayout(cpu_layout)

        self.ram_check = QCheckBox("Usar RAM si es posible (recomendado)")
        self.ram_check.setChecked(True)
        adv_layout.addWidget(self.ram_check)

        level_layout = QHBoxLayout()
        level_layout.addWidget(QLabel("Nivel zlib (1-9):"))
        self.zlib_combo = QComboBox()
        self.zlib_combo.addItems([str(i) for i in range(1, 10)])
        self.zlib_combo.setCurrentText("5")
        level_layout.addWidget(self.zlib_combo)
        adv_layout.addLayout(level_layout)

        self.silent_check = QCheckBox("🔇 Modo silencioso (sin barra de progreso)")
        adv_layout.addWidget(self.silent_check)

        self.exfat_group = QGroupBox("⚙️ Opciones exFAT")
        self.exfat_group.setCheckable(False)
        left_layout.addWidget(self.exfat_group)
        exfat_layout = QVBoxLayout(self.exfat_group)

        cluster_layout = QHBoxLayout()
        cluster_layout.addWidget(QLabel("Cluster size:"))
        self.cluster_combo = QComboBox()
        self.cluster_combo.addItems(["Auto", "4096", "8192", "16384", "32768", "65536"])
        self.cluster_combo.setCurrentText("Auto")
        cluster_layout.addWidget(self.cluster_combo)
        exfat_layout.addLayout(cluster_layout)

        exfat_layout.addWidget(QLabel("ℹ️ La imagen exFAT se genera en Python puro (sin OSFMount)."))
        self.exfat_group.setEnabled(False)

        self.preflight_group = QGroupBox("🔎 Verificación de espacio")
        left_layout.addWidget(self.preflight_group)
        preflight_layout = QVBoxLayout(self.preflight_group)

        self.preflight_status_label = QLabel("No verificado")
        self.preflight_status_label.setStyleSheet("color: #888;")
        preflight_layout.addWidget(self.preflight_status_label)

        self.preflight_details = QLabel("")
        self.preflight_details.setWordWrap(True)
        preflight_layout.addWidget(self.preflight_details)

        self.preflight_check_btn = QPushButton("🔍 Verificar espacio ahora")
        self.preflight_check_btn.clicked.connect(self._run_preflight)
        preflight_layout.addWidget(self.preflight_check_btn)

        self.run_btn = QPushButton("🔄 CONVERTIR")
        self.run_btn.setStyleSheet("background-color: #003791; color: white; font-weight: bold;")
        self.run_btn.clicked.connect(self.run_conversion)
        left_layout.addWidget(self.run_btn)

        left_layout.addStretch()

        # ---- Panel derecho: Build activo ----
        right_panel = QWidget()
        self.build_view = QVBoxLayout(right_panel)
        self.build_view.setContentsMargins(0, 0, 0, 0)

        group_build = QGroupBox("⚡ Build activo")
        self.build_view.addWidget(group_build)
        build_layout = QVBoxLayout(group_build)

        phase_container = QWidget()
        phase_layout = QHBoxLayout(phase_container)
        phase_layout.setSpacing(10)
        self._phase_widgets = []
        for i, name in enumerate(self._phase_labels):
            dot = QLabel("●")
            dot.setStyleSheet("color: #555; font-size: 16px;")
            label = QLabel(name)
            label.setStyleSheet("color: #888; font-size: 10pt;")
            phase_layout.addWidget(dot)
            phase_layout.addWidget(label)
            if i < len(self._phase_labels) - 1:
                arrow = QLabel("→")
                arrow.setStyleSheet("color: #555;")
                phase_layout.addWidget(arrow)
            self._phase_widgets.append((dot, label))
        phase_layout.addStretch()
        build_layout.addWidget(phase_container)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #003791;
                border-radius: 4px;
                text-align: center;
                color: white;
            }
            QProgressBar::chunk {
                background-color: #003791;
                border-radius: 4px;
            }
        """)
        build_layout.addWidget(self.progress_bar)

        stats_grid = QGridLayout()
        self.speed_label = QLabel("Velocidad: --")
        self.eta_label = QLabel("ETA: --")
        self.elapsed_label = QLabel("Tiempo: 0s")
        self.processed_label = QLabel("Procesado: 0%")
        stats_grid.addWidget(self.speed_label, 0, 0)
        stats_grid.addWidget(self.eta_label, 0, 1)
        stats_grid.addWidget(self.elapsed_label, 1, 0)
        stats_grid.addWidget(self.processed_label, 1, 1)
        build_layout.addLayout(stats_grid)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(200)
        self.log_text.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                font-family: Consolas, monospace;
                font-size: 9pt;
            }
        """)
        build_layout.addWidget(self.log_text)

        control_layout = QHBoxLayout()
        self.pause_btn = QPushButton("⏸ Pausar")
        self.pause_btn.setEnabled(False)
        self.pause_btn.clicked.connect(self.toggle_pause)
        control_layout.addWidget(self.pause_btn)

        self.cancel_btn = QPushButton("❌ Cancelar")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_conversion)
        control_layout.addWidget(self.cancel_btn)
        control_layout.addStretch()
        build_layout.addLayout(control_layout)

        build_layout.addStretch()

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([450, 450])
        main_layout.addWidget(splitter)

        self.select_format("ffpfsc")

    # ---- Métodos auxiliares ----
    def browse_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Seleccionar archivo")
        if path:
            self.source_edit.setText(path)
            self.suggest_dest()
            self._run_preflight()

    def browse_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta")
        if path:
            self.source_edit.setText(path)
            self.suggest_dest()
            self._run_preflight()

    def browse_dest(self):
        ext_map = {"ffpfsc": "*.ffpfsc", "ffpfs": "*.ffpfs", "exfat": "*.exfat"}
        filtro = ext_map.get(self._current_format, "*.ffpfsc")
        path, _ = QFileDialog.getSaveFileName(self, "Guardar como", filter=filtro)
        if path:
            self.dest_edit.setText(path)
            self._run_preflight()

    def browse_temp_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta temporal")
        if path:
            self.temp_edit.setText(path)

    def toggle_temp_folder(self, checked):
        self.temp_edit.setEnabled(not checked)
        self.temp_edit.setStyleSheet("" if not checked else "background-color: #f0f0f0;")
        self.browse_temp_btn.setEnabled(not checked)

    def select_format(self, value):
        self._current_format = value
        for btn in self.format_buttons:
            btn.setChecked(btn.property("format") == value)
        self.suggest_dest()

        is_ffpfsc = (value == "ffpfsc")
        is_exfat = (value == "exfat")

        self.backend_combo.setEnabled(is_ffpfsc)
        self.cpu_spin.setEnabled(is_ffpfsc)
        self.ram_check.setEnabled(is_ffpfsc)
        self.zlib_combo.setEnabled(is_ffpfsc)
        self.silent_check.setEnabled(is_ffpfsc)
        self.exfat_group.setEnabled(is_exfat)
        self._run_preflight()

    def suggest_dest(self):
        src = self.source_edit.text()
        if not src:
            return
        path = Path(src)
        base = path.stem if path.is_file() else path.name
        ext_map = {"ffpfsc": ".ffpfsc", "ffpfs": ".ffpfs", "exfat": ".exfat"}
        ext = ext_map.get(self._current_format, ".ffpfsc")
        dest = path.parent / f"{base}{ext}"
        self.dest_edit.setText(str(dest))

    def _run_preflight(self):
        src = self.source_edit.text().strip()
        if not src:
            self.preflight_status_label.setText("⚠️ Selecciona un origen primero")
            self.preflight_status_label.setStyleSheet("color: #ffaa00;")
            self.preflight_details.setText("")
            self.run_btn.setEnabled(True)
            return

        src_path = Path(src)
        if not src_path.exists():
            self.preflight_status_label.setText("❌ El origen no existe")
            self.preflight_status_label.setStyleSheet("color: #ff4444;")
            self.preflight_details.setText("")
            self.run_btn.setEnabled(False)
            return

        if src_path.is_dir():
            total_size = 0
            for root, _, files in os.walk(src_path):
                for f in files:
                    try:
                        total_size += os.path.getsize(os.path.join(root, f))
                    except OSError:
                        pass
        else:
            total_size = src_path.stat().st_size

        dest_path = Path(self.dest_edit.text().strip()) if self.dest_edit.text() else None
        if dest_path:
            try:
                dest_parent = dest_path.parent
                while not dest_parent.exists() and dest_parent != dest_parent.parent:
                    dest_parent = dest_parent.parent
                free = shutil.disk_usage(dest_parent).free
                required = int(total_size * 1.2) + 256 * 1024 * 1024

                if free >= required:
                    status = "✅ Espacio suficiente"
                    color = "#4caf50"
                    self.run_btn.setEnabled(True)
                elif free >= total_size:
                    status = "⚠️ Espacio ajustado (margen bajo)"
                    color = "#ffaa00"
                    self.run_btn.setEnabled(True)
                else:
                    status = "❌ Espacio insuficiente"
                    color = "#ff4444"
                    self.run_btn.setEnabled(False)

                self.preflight_status_label.setText(status)
                self.preflight_status_label.setStyleSheet(f"color: {color}; font-weight: bold;")
                self.preflight_details.setText(
                    f"Origen: {human_readable_size(total_size)} | "
                    f"Libre: {human_readable_size(free)} | "
                    f"Estimado: {human_readable_size(required)}"
                )
            except Exception as e:
                self.preflight_status_label.setText(f"⚠️ Error: {e}")
                self.preflight_status_label.setStyleSheet("color: #ffaa00;")
                self.run_btn.setEnabled(True)
        else:
            self.preflight_status_label.setText("ℹ️ Define el destino")
            self.preflight_status_label.setStyleSheet("color: #888;")
            self.run_btn.setEnabled(True)

    def run_conversion(self):
        if self._running:
            return

        source = self.source_edit.text().strip()
        if not source:
            QMessageBox.warning(self, "Error", "Selecciona una carpeta o archivo de origen.")
            return
        src_path = Path(source)
        if not src_path.exists():
            QMessageBox.warning(self, "Error", "El origen no existe.")
            return

        dest = self.dest_edit.text().strip()
        if not dest:
            QMessageBox.warning(self, "Error", "Define la ruta de destino.")
            return
        dest_path = Path(dest)

        self._run_preflight()
        if self.preflight_status_label.text().startswith("❌"):
            QMessageBox.warning(self, "Espacio insuficiente",
                "No hay suficiente espacio en disco para esta conversión.\n"
                "Libera espacio o cambia la carpeta de destino.")
            return

        temp_folder = None
        if not self.use_system_temp.isChecked():
            temp_path = self.temp_edit.text().strip()
            if temp_path:
                temp_folder = Path(temp_path)
                temp_folder.mkdir(parents=True, exist_ok=True)

        compression_level = int(self.zlib_combo.currentText())
        cpu_count = self.cpu_spin.value()
        zlib_backend = self.backend_combo.currentText()
        use_ram = self.ram_check.isChecked()
        silent = self.silent_check.isChecked()
        cluster = self.cluster_combo.currentText()

        self.log_text.clear()
        self.progress_bar.setValue(0)
        self.speed_label.setText("Velocidad: --")
        self.eta_label.setText("ETA: --")
        self.elapsed_label.setText("Tiempo: 0s")
        self.processed_label.setText("Procesado: 0%")
        for dot, label in self._phase_widgets:
            dot.setStyleSheet("color: #555; font-size: 16px;")
            label.setStyleSheet("color: #888; font-size: 10pt;")
        self._start_time = time.time()
        self._last_percent = 0
        self._timer.start(1000)

        self._worker = ConversionWorker(
            src_path=src_path,
            dest_path=dest_path,
            format_type=self._current_format,
            temp_folder=temp_folder,
            compression_level=compression_level,
            cpu_count=cpu_count,
            silent=silent,
            zlib_backend=zlib_backend,
            use_ram=use_ram,
            cluster_size=cluster,
        )
        self._worker.log_signal.connect(self._append_log)
        self._worker.progress_signal.connect(self._update_progress)
        self._worker.phase_signal.connect(self._update_phase)
        self._worker.stats_signal.connect(self._update_stats)
        self._worker.finished_signal.connect(self.conversion_finished)

        self._running = True
        self.run_btn.setEnabled(False)
        self.pause_btn.setEnabled(True)
        self.cancel_btn.setEnabled(True)
        self._worker.start()

    def toggle_pause(self):
        if self.pause_btn.text() == "⏸ Pausar":
            self.pause_btn.setText("▶ Reanudar")
            self._append_log("⚠️ Pausa no implementada; solo cancelar.")
        else:
            self.pause_btn.setText("⏸ Pausar")

    def cancel_conversion(self):
        if self._running and self._worker:
            self._worker.cancel()
            self._append_log("⚠️ Cancelando...")
            self.cancel_btn.setEnabled(False)

    def _append_log(self, text):
        color = "#d4d4d4"
        if text.startswith("✅"):
            color = "#4caf50"
        elif text.startswith("❌") or text.startswith("[ERROR]") or text.startswith("[EXCEPTION]"):
            color = "#f44336"
        elif text.startswith("⚠️") or text.startswith("[WARN]"):
            color = "#ffaa00"
        elif text.startswith("📦") or text.startswith("🔧") or text.startswith("[INFO]"):
            color = "#4a9eff"
        elif text.startswith("📂") or text.startswith("🔄"):
            color = "#aaaaaa"
        html = f'<span style="color:{color};">{text}</span>'
        self.log_text.append(html)
        self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())

    def _update_progress(self, percent, phase):
        self.progress_bar.setValue(int(percent))
        self.processed_label.setText(f"Procesado: {int(percent)}%")
        if phase:
            for i, name in enumerate(self._phase_labels):
                if name.lower() in phase.lower():
                    self._update_phase(name, i)
                    break

    def _update_phase(self, name, index):
        for i, (dot, label) in enumerate(self._phase_widgets):
            if i < index:
                dot.setStyleSheet("color: #4caf50; font-size: 16px;")
                label.setStyleSheet("color: #4caf50; font-size: 10pt; font-weight: bold;")
            elif i == index:
                dot.setStyleSheet("color: #4a9eff; font-size: 16px;")
                label.setStyleSheet("color: #4a9eff; font-size: 10pt; font-weight: bold;")
            else:
                dot.setStyleSheet("color: #555; font-size: 16px;")
                label.setStyleSheet("color: #888; font-size: 10pt;")

    def _update_stats(self, stats):
        speed = stats.get("speed", 0)
        eta = stats.get("eta", 0)
        elapsed = stats.get("elapsed", 0)
        percent = stats.get("percent", 0)
        self._last_percent = percent
        self._elapsed = elapsed
        self._speed = speed
        self._eta = eta
        self.speed_label.setText(f"Velocidad: {human_readable_size(int(speed))}/s")
        if eta > 0:
            eta_str = f"{int(eta // 60)}m {int(eta % 60)}s" if eta > 60 else f"{int(eta)}s"
            self.eta_label.setText(f"ETA: {eta_str}")
        else:
            self.eta_label.setText("ETA: --")
        self.elapsed_label.setText(f"Tiempo: {int(elapsed)}s")
        self.processed_label.setText(f"Procesado: {int(percent)}%")

    def _update_elapsed(self):
        if self._running and self._worker:
            elapsed = time.time() - self._start_time
            self.elapsed_label.setText(f"Tiempo: {int(elapsed)}s")

    def conversion_finished(self, success, message):
        self._running = False
        self._timer.stop()
        self.run_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        if success:
            self.progress_bar.setValue(100)
            self.processed_label.setText("Procesado: 100%")
            self._append_log("✅ " + message)
            for dot, label in self._phase_widgets:
                dot.setStyleSheet("color: #4caf50; font-size: 16px;")
                label.setStyleSheet("color: #4caf50; font-size: 10pt; font-weight: bold;")
        else:
            self._append_log("❌ " + message)
        self.log_signal.emit(message)


# ============================================================================
# 5. PESTAÑA DE PAYLOAD (sin cambios)
# ============================================================================
class PayloadTab(QWidget):
    log_signal = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._payload_worker = None
        self._timer = QTimer()
        self._timer.timeout.connect(self._update_countdown)
        self._remaining_seconds = 50 * 60
        self._countdown_active = False

        self.setup_ui()
        self.refresh_payloads()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        top_layout = QHBoxLayout()
        top_layout.addWidget(QLabel("IP de la consola:"))
        self.ip_edit = QLineEdit("192.168.100.1")
        self.ip_edit.setFixedWidth(180)
        top_layout.addWidget(self.ip_edit)

        top_layout.addWidget(QLabel("  Puerto:"))
        self.port_edit = QLineEdit("9021")
        self.port_edit.setFixedWidth(80)
        self.port_edit.setValidator(QIntValidator(1, 65535))
        top_layout.addWidget(self.port_edit)

        top_layout.addStretch()
        layout.addLayout(top_layout)

        group_buttons = QGroupBox("🚀 Envío rápido (carpeta 'payloads_botones')")
        layout.addWidget(group_buttons)
        btn_layout = QHBoxLayout(group_buttons)

        payloads = [
            ("Kernel", "p2jb.js", 50000, True),
            ("KStuff", "kstuff.elf", 9021, False),
            ("ShadowMount", "shadowmountplus.elf", 9021, False),
            ("ELFLoader", "elfldr.elf", 9021, False),
            ("FTP", "ftpsrv.elf", 9021, False),
        ]

        for label, filename, port, is_kernel in payloads:
            btn = QPushButton(label)
            btn.setStyleSheet("font-weight: bold;")
            btn.clicked.connect(lambda checked, f=filename, p=port, k=is_kernel, lbl=label: self._send_preset(f, p, k, lbl))
            btn_layout.addWidget(btn)

        btn_custom = QPushButton("📂 Seleccionar payload...")
        btn_custom.setStyleSheet("font-weight: bold; background-color: #555;")
        btn_custom.clicked.connect(self._select_custom_payload)
        btn_layout.addWidget(btn_custom)

        btn_layout.addStretch()

        self.countdown_frame = QWidget()
        self.countdown_frame.setVisible(False)
        countdown_layout = QHBoxLayout(self.countdown_frame)
        countdown_layout.setContentsMargins(0, 0, 0, 0)

        self.countdown_label = QLabel("⏱ 50:00")
        self.countdown_label.setStyleSheet("font-size: 14pt; color: white; font-weight: bold;")
        self.countdown_label.setFixedWidth(100)
        countdown_layout.addWidget(self.countdown_label)

        self.countdown_progress = QProgressBar()
        self.countdown_progress.setValue(100)
        self.countdown_progress.setStyleSheet("""
            QProgressBar {
                border: 1px solid #003791;
                border-radius: 4px;
                text-align: center;
                color: white;
            }
            QProgressBar::chunk {
                background-color: #003791;
                border-radius: 4px;
            }
        """)
        countdown_layout.addWidget(self.countdown_progress)
        layout.addWidget(self.countdown_frame)

        group_payloads = QGroupBox("📦 Payloads disponibles (carpeta 'payloads')")
        layout.addWidget(group_payloads)
        payloads_layout = QVBoxLayout(group_payloads)

        self.payload_list = QListWidget()
        self.payload_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.payload_list.setStyleSheet("""
            QListWidget::item:selected {
                background-color: #003791;
                color: white;
            }
            QListWidget::item { padding: 5px; }
        """)
        payloads_layout.addWidget(self.payload_list)

        sel_layout = QHBoxLayout()
        btn_select_all = QPushButton("✅ Seleccionar todos")
        btn_select_all.clicked.connect(self.select_all_payloads)
        sel_layout.addWidget(btn_select_all)

        btn_deselect_all = QPushButton("❌ Deseleccionar todos")
        btn_deselect_all.clicked.connect(self.deselect_all_payloads)
        sel_layout.addWidget(btn_deselect_all)

        btn_refresh = QPushButton("🔄 Refrescar")
        btn_refresh.clicked.connect(self.refresh_payloads)
        sel_layout.addWidget(btn_refresh)

        sel_layout.addStretch()
        payloads_layout.addLayout(sel_layout)

        self.send_btn = QPushButton("📤 Enviar seleccionados (manual)")
        self.send_btn.setStyleSheet("background-color: #003791; color: white; font-weight: bold;")
        self.send_btn.clicked.connect(self.send_selected_payloads)
        layout.addWidget(self.send_btn)

        group_log = QGroupBox("📋 Registro de envío")
        layout.addWidget(group_log)
        log_layout = QVBoxLayout(group_log)

        self.payload_log_text = QTextEdit()
        self.payload_log_text.setReadOnly(True)
        self.payload_log_text.setMinimumHeight(150)
        self.payload_log_text.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                font-family: Consolas, monospace;
                font-size: 9pt;
            }
        """)
        log_layout.addWidget(self.payload_log_text)

        btn_clear_log = QPushButton("🧹 Limpiar log")
        btn_clear_log.clicked.connect(self.payload_log_text.clear)
        log_layout.addWidget(btn_clear_log, alignment=Qt.AlignmentFlag.AlignRight)

        self.status_label = QLabel("Listo")
        layout.addWidget(self.status_label)

        self.refresh_payloads()

    def refresh_payloads(self):
        self.payload_list.clear()
        payloads_dir = Path("payloads")
        if not payloads_dir.exists():
            self.payload_log_text.append("⚠️ La carpeta 'payloads' no existe.")
            return
        found = False
        for ext in ["*.js", "*.elf", "*.jar", "*.bin"]:
            for file in payloads_dir.glob(ext):
                if file.is_file():
                    item = QListWidgetItem(file.name)
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(Qt.CheckState.Unchecked)
                    self.payload_list.addItem(item)
                    found = True
        if not found:
            self.payload_log_text.append("⚠️ No se encontraron payloads (.js, .elf, .jar, .bin) en 'payloads'.")

    def select_all_payloads(self):
        for i in range(self.payload_list.count()):
            item = self.payload_list.item(i)
            item.setCheckState(Qt.CheckState.Checked)

    def deselect_all_payloads(self):
        for i in range(self.payload_list.count()):
            item = self.payload_list.item(i)
            item.setCheckState(Qt.CheckState.Unchecked)

    def _send_preset(self, filename, default_port, is_kernel, label):
        ip = self.ip_edit.text().strip()
        if not ip:
            QMessageBox.warning(self, "Error", "Introduce la IP de la PS5")
            return

        port_text = self.port_edit.text().strip()
        if port_text:
            try:
                port = int(port_text)
                if port < 1 or port > 65535:
                    raise ValueError
            except ValueError:
                QMessageBox.warning(self, "Error", "El puerto debe ser un número entre 1 y 65535")
                return
        else:
            port = default_port

        filepath = os.path.join("payloads_botones", filename)
        if not os.path.isfile(filepath):
            self.payload_log_text.append(f"❌ Archivo no encontrado en 'payloads_botones': {filename}")
            self.status_label.setText("Error: archivo no encontrado")
            return

        if is_kernel:
            self._start_countdown()
            self.payload_log_text.append(f"🚀 Enviando Kernel ({filename}) a {ip}:{port}...")
        else:
            self.payload_log_text.append(f"🚀 Enviando {label} ({filename}) a {ip}:{port}...")

        self.status_label.setText("Enviando...")
        self.send_btn.setEnabled(False)

        self._payload_worker = PayloadWorker(ip, port, filepath, mode="auto", use_socat=False)
        self._payload_worker.log_signal.connect(self._append_payload_log)
        self._payload_worker.finished_signal.connect(self.payload_finished)
        self._payload_worker.start()

    def _select_custom_payload(self):
        ip = self.ip_edit.text().strip()
        if not ip:
            QMessageBox.warning(self, "Error", "Introduce la IP de la PS5")
            return

        port_text = self.port_edit.text().strip()
        if not port_text:
            QMessageBox.warning(self, "Error", "Introduce un puerto")
            return
        try:
            port = int(port_text)
            if port < 1 or port > 65535:
                raise ValueError
        except ValueError:
            QMessageBox.warning(self, "Error", "El puerto debe ser un número entre 1 y 65535")
            return

        filepath, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar payload",
            "",
            "Payloads (*.js *.elf *.jar *.bin);;Todos los archivos (*.*)"
        )
        if not filepath:
            return

        if not os.path.isfile(filepath):
            QMessageBox.warning(self, "Error", "El archivo no existe")
            return

        self.payload_log_text.append(f"📤 Enviando payload personalizado: {os.path.basename(filepath)} a {ip}:{port}")
        self.status_label.setText("Enviando...")
        self.send_btn.setEnabled(False)

        self._payload_worker = PayloadWorker(ip, port, filepath, mode="auto", use_socat=False)
        self._payload_worker.log_signal.connect(self._append_payload_log)
        self._payload_worker.finished_signal.connect(self.payload_finished)
        self._payload_worker.start()

    def send_selected_payloads(self):
        ip = self.ip_edit.text().strip()
        if not ip:
            QMessageBox.warning(self, "Error", "Introduce la IP de la PS5")
            return

        port_text = self.port_edit.text().strip()
        if not port_text:
            QMessageBox.warning(self, "Error", "Introduce un puerto para el envío manual")
            return
        try:
            port = int(port_text)
            if port < 1 or port > 65535:
                raise ValueError
        except ValueError:
            QMessageBox.warning(self, "Error", "El puerto debe ser un número entre 1 y 65535")
            return

        selected = []
        for i in range(self.payload_list.count()):
            item = self.payload_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                selected.append(item.text())

        if not selected:
            QMessageBox.warning(self, "Error", "Selecciona al menos un payload")
            return

        self.payload_log_text.clear()
        self.status_label.setText("Enviando...")
        self.send_btn.setEnabled(False)

        filename = selected[0]
        filepath = os.path.join("payloads", filename)
        self._payload_worker = PayloadWorker(ip, port, filepath, mode="auto", use_socat=False)
        self._payload_worker.log_signal.connect(self._append_payload_log)
        self._payload_worker.finished_signal.connect(self.payload_finished)
        self._payload_worker.start()

    def _append_payload_log(self, text):
        color = "#d4d4d4"
        if text.startswith("[OK]"):
            color = "#4caf50"
        elif text.startswith("[ERROR]") or text.startswith("[EXCEPTION]"):
            color = "#f44336"
        elif text.startswith("[WARN]"):
            color = "#ffaa00"
        elif text.startswith("[INFO]"):
            color = "#4a9eff"
        html = f'<span style="color:{color};">{text}</span>'
        self.payload_log_text.append(html)
        self.payload_log_text.verticalScrollBar().setValue(self.payload_log_text.verticalScrollBar().maximum())

    def payload_finished(self, success, message):
        self.send_btn.setEnabled(True)
        if success:
            self.status_label.setText("✅ " + message)
        else:
            self.status_label.setText("❌ " + message)

    def _start_countdown(self):
        self._remaining_seconds = 50 * 60
        self._countdown_active = True
        self.countdown_frame.setVisible(True)
        self.countdown_progress.setValue(100)
        self._update_countdown_display()
        self._timer.start(1000)

    def _update_countdown(self):
        if not self._countdown_active:
            return
        self._remaining_seconds -= 1
        if self._remaining_seconds <= 0:
            self._remaining_seconds = 0
            self._timer.stop()
            self._countdown_active = False
            self.countdown_frame.setVisible(False)
            self.payload_log_text.append("⏰ Contador de 50 minutos finalizado.")
            self.status_label.setText("⏰ Temporizador finalizado")
            return
        self._update_countdown_display()

    def _update_countdown_display(self):
        mins = self._remaining_seconds // 60
        secs = self._remaining_seconds % 60
        self.countdown_label.setText(f"⏱ {mins:02d}:{secs:02d}")
        progress = (self._remaining_seconds / (50 * 60)) * 100
        self.countdown_progress.setValue(int(progress))


# ============================================================================
# 6. VENTANA PRINCIPAL
# ============================================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MkPFS - Convertidor + Payload Sender (ModGames44)")
        self.resize(1000, 800)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setFixedHeight(70)
        header.setStyleSheet("""
            QFrame {
                background-color: #003791;
                border: none;
            }
        """)

        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(15, 5, 15, 5)

        if getattr(sys, 'frozen', False):
            base_path = Path(sys._MEIPASS)
        else:
            base_path = Path(".")

        logo_label = QLabel()
        logo_path = base_path / "logo.png"
        if logo_path.exists():
            try:
                pixmap = QPixmap(str(logo_path))
                if not pixmap.isNull():
                    pixmap = pixmap.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                    logo_label.setPixmap(pixmap)
                else:
                    logo_label.setText("🎮")
                    logo_label.setStyleSheet("color: white; font-size: 32px;")
            except Exception:
                logo_label.setText("🎮")
                logo_label.setStyleSheet("color: white; font-size: 32px;")
        else:
            logo_label.setText("🎮")
            logo_label.setStyleSheet("color: white; font-size: 32px;")

        logo_label.setFixedSize(70, 64)
        logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(logo_label)

        title_label = QLabel("MKPFS 🎮")
        font = QFont()
        font.setPointSize(20)
        font.setBold(True)
        title_label.setFont(font)
        title_label.setStyleSheet("color: white;")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(title_label, stretch=1)

        right_spacer = QLabel()
        right_spacer.setFixedWidth(70)
        header_layout.addWidget(right_spacer)

        layout.addWidget(header)

        tabs = QTabWidget()

        self.conversion_tab = ConversionTab()
        self.conversion_tab.log_signal.connect(self.append_log)
        tabs.addTab(self.conversion_tab, "🔄 Conversión")

        self.payload_tab = PayloadTab()
        self.payload_tab.log_signal.connect(self.append_log)
        tabs.addTab(self.payload_tab, "📦 Payload Sender")

        layout.addWidget(tabs)
        self.apply_styles()

    def append_log(self, text):
        pass

    def apply_styles(self):
        style = """
        QMainWindow { background-color: #f0f2f5; }
        QGroupBox {
            font-weight: bold;
            border: 1px solid #003791;
            border-radius: 5px;
            margin-top: 1ex;
            color: #003791;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 5px;
            color: #003791;
        }
        QPushButton {
            background-color: #003791;
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 4px;
            font-weight: bold;
        }
        QPushButton:hover { background-color: #0044aa; }
        QPushButton:disabled { background-color: #888; }
        QLineEdit, QSpinBox {
            padding: 5px;
            border: 1px solid #ccc;
            border-radius: 4px;
            background-color: white;
            color: #333;
        }
        QComboBox {
            padding: 5px;
            border: 1px solid #ccc;
            border-radius: 4px;
            background-color: white;
            color: #333;
        }
        QComboBox QAbstractItemView {
            color: #333;
            background-color: white;
            selection-background-color: #003791;
            selection-color: white;
        }
        QLabel { color: #333; }
        QProgressBar {
            border: 1px solid #003791;
            border-radius: 4px;
            text-align: center;
            color: white;
        }
        QProgressBar::chunk {
            background-color: #003791;
            border-radius: 4px;
        }
        QListWidget {
            border: 1px solid #ccc;
            border-radius: 4px;
            color: #333;
        }
        QTabWidget::pane {
            border: 1px solid #ccc;
            background: white;
        }
        QTabBar::tab {
            padding: 8px 16px;
            background: #e0e0e0;
            color: #333;
        }
        QTabBar::tab:selected {
            background: #003791;
            color: white;
        }
        QCheckBox { color: #333; }
        QTextEdit {
            background-color: #1e1e1e;
            color: #d4d4d4;
            font-family: Consolas, monospace;
            font-size: 9pt;
        }
        """
        self.setStyleSheet(style)

    def closeEvent(self, event):
        event.accept()


# ============================================================================
# 7. PUNTO DE ENTRADA
# ============================================================================
def main():
    if "--worker" in sys.argv:
        worker_main(sys.argv)
        return

    try:
        app = QApplication(sys.argv)
        window = MainWindow()
        window.show()
        sys.exit(app.exec())
    except Exception as e:
        print("=" * 70, file=sys.stderr)
        print("ERROR en main():", file=sys.stderr)
        traceback.print_exc()
        print("=" * 70, file=sys.stderr)
        try:
            input("Presiona Enter para salir...")
        except KeyboardInterrupt:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()