# payload_sender.py
import socket
import struct
import select
import os
import shutil
import subprocess
import sys

# Constantes para el modo PS5 (Lua Server)
COMMAND_MAGIC = struct.pack('<Q', 0xFFFFFFFF)
MAGIC_VALUE = struct.pack('<Q', 0x13371337)
MAGIC_VALUE_LEN = len(MAGIC_VALUE)
SIGNAL_LEN = 16
MCONTEXT_LEN = 0x100

DISABLE_SIGNAL_HANDLER = 0
ENABLE_SIGNAL_HANDLER = 1

SIGNALS = {
    4: "SIGILL",
    10: "SIGBUS",
    11: "SIGSEGV",
}


def resolve_app_base_dir():
    """Devuelve el directorio base donde deben buscarse recursos externos."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def resolve_payload_folder():
    """Resuelve la carpeta external 'payload' junto al ejecutable o al script."""
    return os.path.join(resolve_app_base_dir(), "payload")

def print_mcontext(buffer):
    """Convierte el buffer mcontext_t en una cadena formateada."""
    fmt = "<QQQQQQQQQQQQQQQQIHHQIHHQQQQQQ"
    struct_buf = buffer[:struct.calcsize(fmt)]
    struct_data = struct.unpack(fmt, struct_buf)
    regs_name = [
        "onstack", "rdi", "rsi", "rdx", "rcx",
        "r8", "r9", "rax", "rbx", "rbp", "r10",
        "r11", "r12", "r13", "r14", "r15", "trapno",
        "fs", "gs", "addr", "flags", "es", "ds", "err",
        "rip", "cs", "rflags", "rsp", "ss"
    ]
    lines = []
    for i in range(1, len(regs_name), 2):
        lines.append(f"{regs_name[i]:5}: {struct_data[i]:016x}  {regs_name[i+1]:7}: {struct_data[i+1]:016x}")
    return "\n" + "\n".join(lines) + "\n"


# ------------------------------------------------------------------
# Modo PS4/PS5 estándar (sin prefijo de tamaño, igual que SendFile)
# ------------------------------------------------------------------
def _open_tcp_connection(ip, port, output_callback=None):
    """Abre una conexión TCP usando resolución de direcciones IPv4/IPv6."""
    try:
        infos = socket.getaddrinfo(ip, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror as exc:
        if output_callback:
            output_callback(f"[WARN] Unable to resolve {ip}:{port}: {exc}\n")
        return None

    last_error = None
    for family, socktype, proto, _, sockaddr in infos:
        try:
            sock = socket.socket(family, socktype, proto)
            sock.settimeout(15)
            sock.connect(sockaddr)
            return sock
        except OSError as exc:
            last_error = exc
            try:
                sock.close()
            except Exception:
                pass

    if output_callback:
        output_callback(f"[ERROR] Unable to connect to {ip}:{port}: {last_error}\n")
    return None


def send_payload_std(ip, port, filepath, output_callback=None):
    """
    Envía un payload directamente, sin prefijo de tamaño.
    Comportamiento idéntico al SendFile de C#.
    """
    if not os.path.isfile(filepath):
        if output_callback:
            output_callback(f"[ERROR] Payload file not found: {filepath}\n")
        return False

    sock = _open_tcp_connection(ip, port, output_callback)
    if sock is None:
        return False

    try:
        with sock:
            with open(filepath, "rb") as f:
                while True:
                    chunk = f.read(65536)  # 64KB chunks
                    if not chunk:
                        break
                    sock.sendall(chunk)
            try:
                sock.shutdown(socket.SHUT_WR)
            except OSError:
                pass
        if output_callback:
            output_callback(f"[OK] Payload sent to {ip}:{port}\n")
        return True
    except Exception as e:
        if output_callback:
            output_callback(f"[ERROR] Failed to send payload: {e}\n")
        return False


# ------------------------------------------------------------------
# Modo PS5 con servidor Lua (envío con prefijo de tamaño y comandos)
# ------------------------------------------------------------------
def send_payload_lua(ip, port, filepath, output_callback=None):
    """
    Envía un payload a un servidor Lua (como el de PS5) con prefijo de tamaño.
    """
    if not os.path.isfile(filepath):
        if output_callback:
            output_callback(f"[ERROR] Payload file not found: {filepath}\n")
        return False

    try:
        with open(filepath, "rb") as f:
            data = f.read()
    except Exception as e:
        if output_callback:
            output_callback(f"[ERROR] Cannot read payload file: {e}\n")
        return False

    sock = _open_tcp_connection(ip, port, output_callback)
    if sock is None:
        return False

    try:
        with sock:
            size = struct.pack("<Q", len(data))
            sock.sendall(size + data)
            try:
                sock.shutdown(socket.SHUT_WR)
            except OSError:
                pass
            _process_incoming_data(sock, output_callback)
        if output_callback:
            output_callback(f"[OK] Payload sent (Lua mode) to {ip}:{port}\n")
        return True
    except Exception as e:
        if output_callback:
            output_callback(f"[ERROR] Failed to send payload (Lua mode): {e}\n")
        return False


def send_command_lua(ip, port, command, output_callback=None):
    """
    Envía un comando enable/disable signal handler a un servidor Lua.
    """
    sock = _open_tcp_connection(ip, port, output_callback)
    if sock is None:
        return False

    try:
        with sock:
            sock.sendall(COMMAND_MAGIC + struct.pack("B", command))
            try:
                sock.shutdown(socket.SHUT_WR)
            except OSError:
                pass
            _process_incoming_data(sock, output_callback)
        if output_callback:
            cmd_name = "ENABLE" if command == ENABLE_SIGNAL_HANDLER else "DISABLE"
            output_callback(f"[OK] Command '{cmd_name}' sent\n")
        return True
    except Exception as e:
        if output_callback:
            output_callback(f"[ERROR] Command failed: {e}\n")
        return False


# ------------------------------------------------------------------
# Funciones comunes de procesamiento de respuestas (solo para Lua)
# ------------------------------------------------------------------
def _process_incoming_data(sock, output_callback):
    buffer = b""
    while True:
        readable, _, _ = select.select([sock], [], [], 1.0)
        if not readable:
            continue
        try:
            chunk = sock.recv(4096)
        except Exception as e:
            if output_callback:
                output_callback(f"[ERROR] Receive error: {e}\n")
            break
        if not chunk:
            break
        buffer += chunk
        buffer = _process_buffer(buffer, output_callback)


def _process_buffer(buffer, output_callback):
    while True:
        if len(buffer) < MAGIC_VALUE_LEN:
            break
        magic_index = buffer.find(MAGIC_VALUE)
        if magic_index == -1:
            break
        if len(buffer) < magic_index + MAGIC_VALUE_LEN + SIGNAL_LEN + MCONTEXT_LEN:
            break

        prefix = buffer[:magic_index]
        if prefix and output_callback:
            output_callback(prefix.decode("latin-1", errors="replace"))

        start = magic_index + MAGIC_VALUE_LEN
        magic_data = buffer[start:start + SIGNAL_LEN]
        mcontext_data = buffer[start + SIGNAL_LEN: start + SIGNAL_LEN + MCONTEXT_LEN]

        _process_crash_data(magic_data, mcontext_data, output_callback)

        buffer = buffer[start + SIGNAL_LEN + MCONTEXT_LEN:]

    if buffer and output_callback:
        magic_index = buffer.find(MAGIC_VALUE)
        if magic_index == -1:
            output_callback(buffer.decode("latin-1", errors="replace"))
            buffer = b""
    return buffer


def _process_crash_data(magic_data, mcontext_data, output_callback):
    crash_code, crash_address = struct.unpack("<QQ", magic_data)
    signal_name = SIGNALS.get(crash_code, f"Unknown signal {crash_code}")
    if output_callback:
        output_callback(f"\n*** CRASH DETECTED ***\n{signal_name} at 0x{crash_address:016x}\n")
        output_callback(print_mcontext(mcontext_data))


# ------------------------------------------------------------------
# Función unificada (elige automáticamente según el puerto)
# ------------------------------------------------------------------
def resolve_send_mode(port, filepath=None, mode="auto"):
    """
    Resuelve el protocolo de envío a usar.

    - mode="auto": usa el protocolo estándar para payloads .bin/.elf y
      sólo usa Lua cuando el archivo es .lua.
    - mode="lua" / "std": fuerza el protocolo indicado.

    Esta selección evita el prefijo de tamaño sobre el cargador PS5 estándar
    y corrige el error 'Unknown payload format' que aparece con 9021.
    """
    port_int = int(port)

    if mode not in ("auto", "lua", "std"):
        mode = "auto"

    if mode == "auto":
        if filepath and str(filepath).lower().endswith(".lua"):
            return "lua"
        return "std"

    return mode


def find_socat_binary():
    """Busca un socat utilizable en PATH, junto al exe o en el directorio de recursos."""
    candidates = ["socat", "socat.exe"]
    for name in candidates:
        path = shutil.which(name)
        if path:
            return path

    app_base = resolve_app_base_dir()
    for candidate in (
        os.path.join(app_base, "socat.exe"),
        os.path.join(getattr(sys, "_MEIPASS", app_base), "socat.exe"),
        os.path.join(os.path.dirname(__file__), "socat.exe"),
    ):
        if os.path.isfile(candidate):
            return candidate
    return None


def send_payload_via_socat(ip, port, filepath, output_callback=None):
    """
    Envía un payload usando socat cuando está disponible.
    Esto ayuda en casos donde el transporte raw TCP no reproduce el protocolo
    que esperan algunos payloads .bin en PS4/PS5.
    """
    socat = find_socat_binary()
    if not socat:
        if output_callback:
            output_callback("[WARN] socat not available. Falling back to raw socket transport.\n")
        return False

    try:
        cmd = [socat, f"FILE:{filepath},binary", f"TCP:{ip}:{port}"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            if output_callback:
                output_callback(f"[OK] Payload sent via socat to {ip}:{port}\n")
            return True
        if output_callback:
            output_callback(f"[WARN] socat failed (exit {result.returncode}). Falling back to raw socket transport.\n")
        return False
    except FileNotFoundError:
        if output_callback:
            output_callback("[WARN] socat binary not found. Falling back to raw socket transport.\n")
        return False
    except subprocess.TimeoutExpired:
        if output_callback:
            output_callback("[WARN] socat timed out. Falling back to raw socket transport.\n")
        return False
    except Exception as exc:
        if output_callback:
            output_callback(f"[WARN] socat error: {exc}. Falling back to raw socket transport.\n")
        return False


def send_payload(ip, port, filepath, mode="auto", output_callback=None, use_socat=False):
    """
    Envía un payload.
    mode puede ser "std" (PS4/PS5 estándar), "lua" (PS5 con Lua server) o "auto".
    En auto, si el archivo termina en .lua se usa modo lua; en el resto se usa std.
    Si use_socat=True y existe socat utilizable, se intenta esa ruta primero.
    """
    port_int = int(port)
    mode = resolve_send_mode(port_int, filepath, mode)

    if mode == "lua":
        return send_payload_lua(ip, port_int, filepath, output_callback)

    if use_socat:
        result = send_payload_via_socat(ip, port_int, filepath, output_callback)
        if result:
            return True

    return send_payload_std(ip, port_int, filepath, output_callback)


def send_command(ip, port, command, output_callback=None):
    """Envía un comando (solo para modo lua)."""
    return send_command_lua(ip, int(port), command, output_callback)