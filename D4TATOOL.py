#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
D4TATOOL v4.1 - by drako

Gestor de proyectos GitHub: importar, crackear, configurar automáticamente,
lanzar, caja de herramientas. Sin dependencias: solo biblioteca estándar
(Python 3.8+). Requisito: ejecutar setup.bat (Windows).

Uso:
    python d4tatool.py            abre la interfaz
    python d4tatool.py --fast     se salta la animación de intro
    python d4tatool.py --version

Un archivo d4tatool.cfg junto al script acepta:  intro=0
"""
from __future__ import annotations

import ast
import datetime
import getpass
import importlib.util
import json
import math
import os
import platform
import random
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.request
import webbrowser
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

VERSION = "v4.1"
IS_WIN = os.name == "nt"
ROOT = Path(__file__).resolve().parent
PROJECTS = ROOT / "projets"
TMP = Path(tempfile.gettempdir())
LOG = TMP / "d4tatool_setup.log"
RECIPES = ROOT / "d4tatool_recetas.json"
BW = 70          # ancho del marco
PER = 8          # proyectos por página
TIMEOUT_TOTAL = 900     # duración máx. de una operación (s)
CANCEL_GRACE = 8        # margen dejado al hilo tras cancelar (s)
WIN_RESERVED = {"con", "prn", "aux", "nul"} | \
               {"com%d" % i for i in range(1, 10)} | \
               {"lpt%d" % i for i in range(1, 10)}

# ============================================================== colores
# Paleta: degradado de rojo a blanco.
ACCENT = (255, 85, 70)
LIGHT = (255, 190, 185)
DIM = (165, 130, 135)
BORDER = (200, 40, 45)
WHITE = (255, 255, 255)
RED = (255, 45, 45)
GREEN = (120, 255, 180)
AMBER = (255, 200, 90)
ORANGE = (255, 165, 70)
GREY = (130, 110, 115)
TYPE_COL = {
    "AUTO": (255, 190, 80), "PY": (255, 120, 100), "JS": (255, 220, 100),
    "GO": (80, 230, 230), "RS": (255, 140, 80), "NET": (255, 130, 160),
    "JAR": (255, 110, 110), "WEB": (255, 130, 200), "BAT": (120, 255, 180),
    "SH": (170, 230, 120),
}
# Línea 1 = rojo profundo, línea 10 = casi blanco.
GRAD = [(205, 25, 25), (220, 45, 40), (232, 68, 60), (240, 92, 82),
        (246, 116, 105), (250, 140, 130), (253, 165, 158), (255, 190, 185),
        (255, 218, 214), (255, 245, 242)]

RST = "\x1b[0m"
CLR = "\x1b[2K"
HIDE = "\x1b[?25l"
SHOW = "\x1b[?25h"
CLS = "\x1b[2J\x1b[H"


def fg(c):
    return "\x1b[38;2;%d;%d;%dm" % (c[0], c[1], c[2])


def scale(c, pct):
    return (int(c[0] * pct / 100), int(c[1] * pct / 100), int(c[2] * pct / 100))


def at(row, col):
    return "\x1b[%d;%dH" % (row, col)


# ============================================================== terminal
_buf = []


def w(s):
    _buf.append(s)


def flush():
    if _buf:
        data = "".join(_buf)
        _buf.clear()
        try:
            sys.stdout.write(data)
            sys.stdout.flush()
        except Exception:
            pass


class Skip(Exception):
    """Se lanza durante la intro cuando se pulsa una tecla."""


SKIPPABLE = [False]

if IS_WIN:
    import msvcrt

    def key_pressed():
        return msvcrt.kbhit()

    def _read_key():
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            msvcrt.getwch()
            return ""
        return ch

    def flush_keys():
        while msvcrt.kbhit():
            msvcrt.getwch()

    def raw_on():
        pass

    def raw_off():
        pass
else:
    import select
    import termios
    import tty

    _old_term = [None]

    def raw_on():
        if sys.stdin.isatty():
            fd = sys.stdin.fileno()
            if _old_term[0] is None:
                _old_term[0] = termios.tcgetattr(fd)
            tty.setcbreak(fd)

    def raw_off():
        if _old_term[0] is not None:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, _old_term[0])

    def key_pressed():
        return bool(select.select([sys.stdin], [], [], 0)[0])

    def _read_key():
        data = os.read(sys.stdin.fileno(), 32).decode("utf-8", "ignore")
        if not data or data[0] == "\x1b":
            return ""
        return data[0]

    def flush_keys():
        try:
            termios.tcflush(sys.stdin, termios.TCIFLUSH)
        except Exception:
            pass


@contextmanager
def cooked():
    """Terminal en modo normal (entrada de texto, subprocesos)."""
    flush()
    raw_off()
    try:
        yield
    finally:
        raw_on()


def getkey(timeout=None):
    """Devuelve la tecla (en minúscula) o None si se agota el tiempo."""
    flush()
    end = None if timeout is None else time.time() + timeout
    while True:
        if key_pressed():
            ch = _read_key()
            if ch == "\x03":
                raise KeyboardInterrupt
            if ch == "":
                continue
            return ch.lower()
        if end is not None and time.time() >= end:
            return None
        time.sleep(0.03)


def choose(keys):
    while True:
        k = getkey()
        if k in keys:
            return k


def nap(t):
    flush()
    if SKIPPABLE[0] and key_pressed():
        flush_keys()
        raise Skip()
    time.sleep(t)


def ask_line(prompt=""):
    w(SHOW)
    w(prompt)
    flush()
    with cooked():
        try:
            s = input()
        except (EOFError, KeyboardInterrupt):
            s = ""
    w(HIDE + RST)
    flush()
    return s.strip()


def cols():
    try:
        return max(72, shutil.get_terminal_size((100, 34)).columns)
    except Exception:
        return 100


def fc():
    return (cols() - BW) // 2 + 1


def enable_vt():
    if not IS_WIN:
        return
    try:
        import ctypes
        k = ctypes.windll.kernel32
        k.GetStdHandle.restype = ctypes.c_void_p
        k.SetConsoleMode.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        for std in (-11, -12):
            h = k.GetStdHandle(std)
            m = ctypes.c_uint32()
            if k.GetConsoleMode(ctypes.c_void_p(h), ctypes.byref(m)):
                k.SetConsoleMode(h, m.value | 0x0004)
        k.SetConsoleOutputCP(65001)
        k.SetConsoleCP(65001)
    except Exception:
        os.system("")


ALT = [False]


def alt_on():
    """Pantalla alternativa: sin historial, imposible desplazarse."""
    if not ALT[0]:
        ALT[0] = True
        w("\x1b[?1049h\x1b[?1007l" + CLS)
        flush()


def alt_off():
    if ALT[0]:
        ALT[0] = False
        w("\x1b[?1049l")
        flush()


def setup_terminal():
    enable_vt()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if IS_WIN:
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleTitleW("D4TATOOL - by Drako")
        except Exception:
            pass
        os.system("mode con cols=100 lines=34 >nul 2>&1")
    else:
        sys.stdout.write("\x1b]0;D4TATOOL - by drako\x07")


def cline(row, color, text, clear=True):
    x = max(1, (cols() - len(text)) // 2 + 1)
    w(at(row, 1) + (CLR if clear else "") + at(row, x) + fg(color) + text + RST)


def wipe_from(row, delay=0.004):
    for r in range(row, 33):
        w(at(r, 1) + CLR)
        nap(delay)


def type_text(row, color, text, delay=0.02):
    x = max(1, (cols() - len(text)) // 2 + 1)
    w(at(row, x) + fg(color))
    for ch in text:
        w(ch)
        nap(delay)
    w(RST)


def msg(row, color, text, wait=0.0):
    cline(row, color, text)
    flush()
    if wait:
        time.sleep(wait)


# ============================================================== banner
BANNER = [
    "▓█████▄  ▄▄▄     ▄▄▄█████▓ ▄▄▄     ▄▄▄█████▓ ▒█████   ▒█████   ██▓    ",
    "▒██▀ ██▌▒████▄   ▓  ██▒ ▓▒▒████▄   ▓  ██▒ ▓▒▒██▒  ██▒▒██▒  ██▒▓██▒    ",
    "░██   █▌▒██  ▀█▄ ▒ ▓██░ ▒░▒██  ▀█▄ ▒ ▓██░ ▒░▒██░  ██▒▒██░  ██▒▒██░    ",
    "░▓█▄   ▌░██▄▄▄▄██░ ▓██▓ ░ ░██▄▄▄▄██░ ▓██▓ ░ ▒██   ██░▒██   ██░▒██░    ",
    "░▒████▓  ▓█   ▓██▒ ▒██▒ ░  ▓█   ▓██▒ ▒██▒ ░ ░ ████▓▒░░ ████▓▒░░██████▒",
    " ▒▒▓  ▒  ▒▒   ▓▒█░ ▒ ░░    ▒▒   ▓▒█░ ▒ ░░   ░ ▒░▒░▒░ ░ ▒░▒░▒░ ░ ▒░▓  ░",
    " ░ ▒  ▒   ▒   ▒▒ ░   ░      ▒   ▒▒ ░   ░      ░ ▒ ▒░   ░ ▒ ▒░ ░ ░ ▒  ░",
    " ░ ░  ░   ░   ▒    ░        ░   ▒    ░      ░ ░ ░ ▒  ░ ░ ░ ▒    ░ ░   ",
    "   ░          ░  ░              ░  ░            ░ ░      ░ ░      ░  ░",
    " ░                                                                    ",
]
BANNER_W = max(len(l) for l in BANNER)
BANNER = [l.ljust(BANNER_W) for l in BANNER]

FSOC = [
    "████   ████  ███   ████ ███ █████ █████ █   █",
    "█     █     █   █ █      █  █       █    █ █ ",
    "███    ███  █   █ █      █  ████    █     █  ",
    "█         █ █   █ █      █  █       █     █  ",
    "█     ████   ███   ████ ███ █████   █     █  ",
]


def draw_banner_line(i, pct=100, hlc=None):
    x = max(1, (cols() - BANNER_W) // 2 + 1)
    col = hlc if hlc else scale(GRAD[i - 1], pct)
    w(at(i + 1, x) + fg(col) + BANNER[i - 1] + RST)


def draw_banner(pct=100, hl=0, hlc=WHITE):
    for i in range(1, 11):
        draw_banner_line(i, pct, hlc if hl == i else None)


def sweep():
    for n in range(1, 11):
        draw_banner_line(n, 100, (255, 240, 235))
        nap(0.012)
        draw_banner_line(n, 100)
    flush()


# ============================================================== proyectos
@dataclass
class Project:
    folder: Path
    name: str
    desc: str = ""
    run: str = ""
    type: str = ""
    ask: bool = False
    conf: int = 100
    cands: list = field(default_factory=list)


DEFAULT_LAUNCHERS = ["d4ta.bat", "run.bat", "start.bat", "main.bat",
                     "launch.bat", "d4ta.cmd", "run.cmd", "start.cmd"]
USER_KEYS = ("name", "desc", "ask")


def load_project(folder):
    p = Project(folder=folder, name=folder.name)
    cfg = folder / "d4ta.cfg"
    if cfg.is_file():
        try:
            lines = cfg.read_text(encoding="utf-8-sig", errors="ignore").splitlines()
        except OSError:
            lines = []
        for line in lines:
            line = line.strip()
            if not line or line[0] in ";#" or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip().lower(), v.strip()
            if k == "name" and v:
                p.name = v
            elif k == "desc":
                p.desc = v
            elif k == "run":
                p.run = v
            elif k == "type":
                p.type = v
            elif k == "ask":
                p.ask = v.strip().lower() not in ("", "0", "false", "no", "off")
            elif k == "conf":
                try:
                    p.conf = int(v)
                except ValueError:
                    p.conf = 100
            elif k == "cands":
                p.cands = [c.strip() for c in v.split("||") if c.strip()]
    if not p.run and IS_WIN:
        for f in DEFAULT_LAUNCHERS:
            if (folder / f).is_file():
                p.run, p.type = f, "BAT"
                break
    if not p.desc:
        p.desc = ("Ejecuta: " + p.run) if p.run else "Config. automática al 1er arranque"
    if not p.type:
        p.type = "RUN" if p.run else "AUTO"
    return p


def scan():
    if not PROJECTS.is_dir():
        PROJECTS.mkdir(parents=True, exist_ok=True)
    dirs = sorted((d for d in PROJECTS.iterdir()
                   if d.is_dir() and not d.name.startswith(".")),
                  key=lambda d: d.name.lower())
    return [load_project(d) for d in dirs]


def cfg_has_auto(cfg):
    try:
        for line in cfg.read_text(encoding="utf-8-sig", errors="ignore").splitlines():
            if line.strip().lower().startswith("auto=1"):
                return True
    except OSError:
        pass
    return False


def append_cfg(folder, lines):
    cfg = folder / "d4ta.cfg"
    prefix = ""
    if cfg.is_file():
        try:
            if not cfg.read_bytes().endswith(b"\n") and cfg.stat().st_size > 0:
                prefix = "\n"
        except OSError:
            pass
    with open(cfg, "a", encoding="utf-8") as f:
        f.write(prefix + "\n".join(lines) + "\n")


def set_run(folder, run):
    """Cambia run= sin tocar el resto de claves del cfg."""
    cfg = folder / "d4ta.cfg"
    lines = []
    if cfg.is_file():
        try:
            for line in cfg.read_text(encoding="utf-8-sig", errors="ignore").splitlines():
                if line.split("=", 1)[0].strip().lower() != "run":
                    lines.append(line)
        except OSError:
            pass
    lines.append("run=" + run)
    lines.append("auto=1")
    try:
        cfg.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass


def rm_project(folder):
    """Borra un proyecto. Rechaza cualquier ruta fuera de la carpeta de proyectos."""
    if folder.is_symlink():
        try:
            folder.unlink()
            return True
        except OSError:
            return False
    try:
        folder = folder.resolve()
        if PROJECTS.resolve() not in folder.parents:
            return False
    except OSError:
        return False

    def onerr(func, path, exc):
        try:
            os.chmod(path, stat.S_IWRITE)
            func(path)
        except Exception:
            pass

    if sys.version_info >= (3, 12):
        shutil.rmtree(folder, onexc=lambda f, p, e: onerr(f, p, e))
    else:
        shutil.rmtree(folder, onerror=onerr)
    if folder.exists() and IS_WIN:
        subprocess.run(["cmd", "/c", "rd", "/s", "/q", str(folder)],
                       capture_output=True)
        if folder.exists():
            empty = TMP / "d4_empty"
            empty.mkdir(exist_ok=True)
            subprocess.run(["robocopy", str(empty), str(folder), "/mir", "/njh",
                            "/njs", "/nfl", "/ndl", "/np"], capture_output=True)
            subprocess.run(["cmd", "/c", "rd", "/s", "/q", str(folder)],
                           capture_output=True)
            shutil.rmtree(empty, ignore_errors=True)
    return not folder.exists()


# ============================================================== PATH / herramientas
def addpath(p):
    p = str(p)
    cur = os.environ.get("PATH", "")
    if os.path.isdir(p) and p.lower() not in [x.lower() for x in cur.split(os.pathsep)]:
        os.environ["PATH"] = p + os.pathsep + cur


def fixpath():
    """Añade al PATH las herramientas instaladas por la autoconfiguración."""
    if not IS_WIN:
        return
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    la = os.environ.get("LOCALAPPDATA", "")
    ap = os.environ.get("APPDATA", "")
    up = os.environ.get("USERPROFILE", "")
    for d in (pf + r"\nodejs", pf + r"\Git\cmd", pf + r"\Git\bin", pf + r"\Go\bin",
              pf + r"\dotnet", up + r"\.cargo\bin", ap + r"\npm",
              la + r"\Programs\Python\Launcher"):
        addpath(d)
    for base in (Path(la) / "Programs" / "Python", Path(pf)):
        if base.is_dir():
            for p in base.glob("Python3*"):
                addpath(p)
                addpath(p / "Scripts")
    jdk = Path(pf) / "Microsoft"
    if jdk.is_dir():
        for p in jdk.glob("jdk-*"):
            addpath(p / "bin")


def _py_ok(cmd):
    try:
        r = subprocess.run(
            cmd + ["-c", "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)"],
            capture_output=True, timeout=20)
        return r.returncode == 0
    except Exception:
        return False


def find_python():
    """Comando Python 3.8+ (lista). Recurre al intérprete actual."""
    cands = [["py", "-3"], ["python"]] if IS_WIN else [["python3"], ["python"]]
    for c in cands:
        if shutil.which(c[0]) and _py_ok(c):
            return c
    return [sys.executable]


def py_str(cmd):
    return " ".join('"%s"' % c if " " in c else c for c in cmd)


def tool_ok(tok):
    t = tok.lower()
    if t == "python":
        return shutil.which("python") is not None and _py_ok(["python"])
    if t == "py":
        return shutil.which("py") is not None and _py_ok(["py", "-3"])
    return shutil.which(tok) is not None


NEED = ("npm", "node", "go", "cargo", "dotnet", "java", "bash", "python", "py")
TOOL_WINGET = {
    "npm": ("node", "OpenJS.NodeJS.LTS", "Node.js"),
    "node": ("node", "OpenJS.NodeJS.LTS", "Node.js"),
    "go": ("go", "GoLang.Go", "Go"),
    "cargo": ("cargo", "Rustlang.Rustup", "Rust"),
    "dotnet": ("dotnet", "Microsoft.DotNet.SDK.8", ".NET"),
    "java": ("java", "Microsoft.OpenJDK.21", "Java"),
    "bash": ("bash", "Git.Git", "Git"),
}


def open_path(p):
    try:
        if IS_WIN:
            os.startfile(str(p))  # noqa
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
    except Exception:
        pass


def copy_clip(text):
    try:
        if IS_WIN:
            if text.isascii():
                subprocess.run(["clip"], input=text.encode("ascii", "ignore"),
                               creationflags=0x08000000, check=True)
            else:
                subprocess.run(["powershell", "-NoProfile", "-Command",
                                "Set-Clipboard -Value ([Console]::In.ReadToEnd())"],
                               input=text.encode("utf-8"),
                               creationflags=0x08000000, check=True)
            return True
        for cmd in (["pbcopy"], ["wl-copy"], ["xclip", "-selection", "clipboard"],
                    ["xsel", "-ib"]):
            if shutil.which(cmd[0]):
                subprocess.run(cmd, input=text.encode("utf-8"), check=True)
                return True
    except Exception:
        pass
    return False


# ============================================================== registro + comandos
class Status:
    def __init__(self):
        self.msg = "Iniciando"
        self.cancel = threading.Event()

    def set(self, m):
        self.msg = m
        logw("== " + m)


def logw(text):
    try:
        with open(LOG, "a", encoding="utf-8", errors="replace") as f:
            f.write(text + "\n")
    except OSError:
        pass


def _kill(p):
    try:
        if IS_WIN:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)],
                           capture_output=True)
        else:
            p.kill()
    except Exception:
        pass


def run_cmd(cmd, st, cwd=None):
    """Ejecuta un comando (lista o cadena shell), salida al registro."""
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["PYTHONUTF8"] = "1"
    shell = isinstance(cmd, str)
    logw("$ " + (cmd if shell else " ".join(cmd)))
    flags = 0x08000000 if IS_WIN else 0
    with open(LOG, "ab") as lf:
        try:
            p = subprocess.Popen(cmd, shell=shell, cwd=str(cwd) if cwd else None,
                                 env=env, stdin=subprocess.DEVNULL, stdout=lf,
                                 stderr=subprocess.STDOUT, creationflags=flags)
        except OSError as e:
            logw("error: %s" % e)
            return 127
        while True:
            try:
                return p.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                if st.cancel.is_set():
                    _kill(p)
                    return -1


@dataclass
class Result:
    res: str = "FAIL"
    info: str = ""
    warn: str = ""


# ============================================================== importar GitHub
URL_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
BRANCH_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def parse_github(raw):
    """Normaliza una entrada -> (url, owner, name, rama) o None."""
    url = raw.replace('"', "").replace("'", "").strip()
    url = re.split(r"[?#]", url, maxsplit=1)[0].strip()
    if url.lower().startswith("git clone "):
        url = url[10:].strip()
    low = url.lower()
    if low.startswith("git@github.com:"):
        url = "https://github.com/" + url[15:]
    elif low.startswith("ssh://git@github.com/"):
        url = "https://github.com/" + url[21:]
    elif low.startswith("github.com/"):
        url = "https://" + url
    elif low.startswith("www.github.com/"):
        url = "https://github.com/" + url[15:]
    elif low.startswith("http://github.com/"):
        url = "https://" + url[7:]
    elif low.startswith("http://www.github.com/"):
        url = "https://github.com/" + url[22:]
    elif low.startswith("https://www.github.com/"):
        url = "https://github.com/" + url[23:]
    elif URL_RE.match(url):
        url = "https://github.com/" + url
    if not url.lower().startswith("https://github.com/"):
        return None
    branch = ""
    if "/tree/" in url:
        branch = url.split("/tree/", 1)[1].split("/", 1)[0]
        if not BRANCH_RE.match(branch):
            branch = ""
    parts = url.split("/")
    if len(parts) < 5:
        return None
    owner, name = parts[3], parts[4]
    if name.lower().endswith(".git"):
        name = name[:-4]
    if not URL_RE.match(owner + "/" + name):
        return None
    if set(owner) <= {"."} or set(name) <= {"."}:
        return None
    return ("https://github.com/%s/%s" % (owner, name), owner, name, branch)


def download_zip(url, dest, st):
    zpath = TMP / "d4tatool.zip"
    xdir = TMP / "d4tatool_x"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "D4TATOOL"})
        with urllib.request.urlopen(req, timeout=30) as r, open(zpath, "wb") as f:
            while True:
                chunk = r.read(65536)
                if not chunk:
                    break
                if st.cancel.is_set():
                    return False
                f.write(chunk)
        shutil.rmtree(xdir, ignore_errors=True)
        with zipfile.ZipFile(zpath) as z:
            root = xdir.resolve()
            infos = z.infolist()
            if sum(i.file_size for i in infos) > 4 * 1024 ** 3:
                logw("zip: archivo descomprimido demasiado grande")
                return False
            for info in infos:
                target = (xdir / info.filename).resolve()
                if target != root and root not in target.parents:
                    logw("zip: ruta fuera de la carpeta " + info.filename)
                    return False
            z.extractall(xdir)
        subdirs = [d for d in xdir.iterdir() if d.is_dir()]
        if not subdirs:
            return False
        shutil.move(str(subdirs[0]), str(dest))
        return dest.is_dir()
    except Exception as e:
        logw("zip: %s" % e)
        return False
    finally:
        try:
            zpath.unlink()
        except OSError:
            pass
        shutil.rmtree(xdir, ignore_errors=True)


def dl_fetch(url, dest, branch, st):
    st.set("Conectando con GitHub")
    ok = False
    if shutil.which("git"):
        st.set("Clonando el repositorio con git")
        cmd = ["git", "-c", "core.longpaths=true", "clone", "--depth", "1"]
        if branch:
            cmd += ["-b", branch]
        ok = run_cmd(cmd + [url, str(dest)], st) == 0
        if ok and (dest / ".gitmodules").exists():
            st.set("Recuperando los submódulos")
            run_cmd(["git", "-C", str(dest), "submodule", "update", "--init",
                     "--recursive", "--depth", "1"], st)
    if st.cancel.is_set():
        return False
    if not ok:
        if dest.exists():
            rm_project(dest)
        st.set("Descargando el archivo ZIP")
        refs = ["refs/heads/" + branch] if branch else ["HEAD", "refs/heads/main",
                                                          "refs/heads/master"]
        for ref in refs:
            if st.cancel.is_set():
                return False
            if download_zip("%s/archive/%s.zip" % (url, ref), dest, st):
                return True
        return False
    return True


# ============================================================== recetas compartidas
def load_recipes():
    try:
        data = json.loads(RECIPES.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {k: [r for r in v if isinstance(r, str)] for k, v in data.items()
                    if isinstance(v, list)}
    except Exception:
        pass
    return {}


def save_recipe(typ, run):
    """Guarda un método que ha arrancado bien para reutilizarlo en otros proyectos."""
    if not typ or not run or typ in ("RUN", "AUTO"):
        return
    data = load_recipes()
    lst = [r for r in data.get(typ, []) if r != run]
    lst.insert(0, run)
    data[typ] = lst[:12]
    try:
        RECIPES.write_text(json.dumps(data, ensure_ascii=False, indent=0),
                           encoding="utf-8")
    except OSError:
        pass


# ============================================================== cracker
PY_STRONG = ["main.py", "app.py", "run.py", "start.py", "bot.py", "index.py",
             "cli.py", "__main__.py"]
PY_SUB = ["main.py", "app.py", "run.py", "start.py", "bot.py", "cli.py", "__main__.py"]
SKIP_NAT = ("install", "setup", "build", "update", "unins", "make", "deb", "rpm",
            "package", "deploy", "release", "clean", "test", "lint", "docker")
DESCS = {"BAT": "Ejecuta: ", "EXE": "Ejecuta: ", "PS1": "Ejecuta: ", "VBS": "Ejecuta: ",
         "WEB": "Página web: ", "SH": "Script shell: bash ", "JS": "Node.js: ",
         "PY": "Python: ", "JAR": "Java: "}
README_PY = re.compile(r"(?i)\b(python3?|py)[ \t]+(-3[ \t]+)?([\w./\\-]+\.py)\b")


def find_py_entry(folder):
    for f in PY_STRONG:
        if (folder / f).is_file():
            return f
    if (folder / "manage.py").is_file():
        return "manage.py runserver"
    if (folder / (folder.name + ".py")).is_file():
        return folder.name + ".py"
    for d in ("src", "app", "source", "code", "scripts"):
        for f in PY_SUB:
            if (folder / d / f).is_file():
                return d + os.sep + f
    for sub in sorted(p for p in folder.iterdir() if p.is_dir()):
        if (sub / "__main__.py").is_file():
            return "-m " + sub.name
    return None


def find_py_weak(folder):
    bad = ("test", "conftest", "setup", "__init__")
    cands = sorted((p for p in folder.glob("*.py")
                    if p.is_file() and not p.name.lower().startswith(bad)),
                   key=lambda p: p.name.lower())
    for p in cands:
        try:
            if "__main__" in p.read_text(encoding="utf-8", errors="ignore"):
                return p.name
        except OSError:
            pass
    return cands[0].name if cands else None


def nat_pick(folder, patterns):
    for pat in patterns:
        for f in sorted(folder.glob(pat), key=lambda p: p.name.lower()):
            if f.is_file() and not any(s in f.name.lower() for s in SKIP_NAT):
                return f.name
    return None


def py_candidates(folder):
    out = []

    def add(score, rel):
        out.append((score, rel, "PY"))

    for i, f in enumerate(PY_STRONG):
        if (folder / f).is_file():
            add(100 - i, f)
    if (folder / "manage.py").is_file():
        add(96, "manage.py runserver")
    if (folder / (folder.name + ".py")).is_file():
        add(94, folder.name + ".py")
    for d in ("src", "app", "source", "code", "scripts"):
        for i, f in enumerate(PY_SUB):
            if (folder / d / f).is_file():
                add(80 - i, d + os.sep + f)
    for sub in sorted(p for p in folder.iterdir() if p.is_dir()):
        if (sub / "__main__.py").is_file():
            add(70, "-m " + sub.name)
    for p in sorted(folder.glob("*.py")):
        if not p.is_file() or p.name in PY_STRONG:
            continue
        score = 40
        try:
            txt = p.read_text(encoding="utf-8", errors="ignore")
            if "__main__" in txt:
                score += 25
            if "argparse" in txt or "sys.argv" in txt:
                score += 5
            if "input(" in txt:
                score += 3
        except OSError:
            pass
        add(score, p.name)
    return out


def valid_py(folder, run):
    parts = run.split()
    if parts and parts[0].lower() in ("python", "python3", "py"):
        parts = parts[1:]
        if parts and parts[0] == "-3":
            parts = parts[1:]
    if not parts:
        return False
    if parts[0] == "-m":
        return len(parts) > 1 and (folder / parts[1] / "__main__.py").is_file()
    p = folder / parts[0]
    if not p.is_file():
        return False
    try:
        compile(p.read_text(encoding="utf-8", errors="ignore"), str(p), "exec")
        return True
    except (SyntaxError, ValueError, OSError):
        return False


def valid_candidate(folder, run, typ):
    """Comprobación estática y rápida: no ejecuta nada."""
    if not run:
        return False
    if typ == "PY":
        return valid_py(folder, run)
    if typ == "JS":
        parts = run.split()
        if parts and parts[0] == "node":
            return len(parts) > 1 and (folder / parts[1]).is_file()
        return True
    if typ == "WEB":
        return any((folder / h).is_file() for h in
                   ("index.html", "docs/index.html", "public/index.html",
                    "dist/index.html", "build/index.html"))
    if typ in ("GO", "RS", "NET"):
        return True
    return (folder / run.split()[-1]).is_file()


def all_runs(exclude):
    """Métodos de ejecución de los demás proyectos + recetas guardadas."""
    pool = []
    if PROJECTS.is_dir():
        for p in PROJECTS.iterdir():
            if p == exclude or not p.is_dir():
                continue
            try:
                pr = load_project(p)
            except Exception:
                continue
            if pr.run:
                pool.append((pr.type, pr.run))
    for typ, lst in load_recipes().items():
        for r in lst:
            pool.append((typ, r))
    return pool


def borrowed(typ, folder, pool):
    """Adapta los métodos de otros proyectos al proyecto actual."""
    out = []
    for t, run in pool:
        if t != typ:
            continue
        cand = run
        if typ == "PY":
            files = [x for x in run.split() if x.endswith(".py")]
            if files and not (folder / files[0]).is_file():
                alt = find_py_weak(folder)
                if not alt:
                    continue
                cand = run.replace(files[0], alt)
        if cand not in out:
            out.append(cand)
    return out


def crack(folder):
    """Sondea todos los métodos posibles y devuelve (mejor, lista_ordenada)."""
    raw = py_candidates(folder)
    if (folder / "package.json").is_file():
        n = node_start_cmd(folder)
        if n:
            raw.append((95, n, "JS"))
    if (folder / "go.mod").is_file():
        raw.append((95, "go run .", "GO"))
    if (folder / "Cargo.toml").is_file():
        raw.append((95, "cargo run --release", "RS"))
    if next(folder.glob("*.csproj"), None):
        raw.append((95, "dotnet run", "NET"))
    for pat in ("*.jar", "target/*.jar", "build/libs/*.jar"):
        f = next(folder.glob(pat), None)
        if f:
            raw.append((93, "java -jar " + f.relative_to(folder).as_posix(), "JAR"))
            break
    if IS_WIN:
        for pat, tpl, typ in (("*.bat", "%s", "BAT"), ("*.exe", "%s", "EXE"),
                              ("*.ps1", "powershell -NoProfile -ExecutionPolicy Bypass -File %s", "PS1"),
                              ("*.vbs", "wscript %s", "VBS")):
            f = nat_pick(folder, [pat])
            if f:
                raw.append((60, tpl % f, typ))
    for hf in ("index.html", "docs/index.html", "public/index.html",
               "dist/index.html", "build/index.html"):
        if (folder / hf).is_file():
            opener = 'start "" "%s"' % hf if IS_WIN else \
                ("open " if sys.platform == "darwin" else "xdg-open ") + hf
            raw.append((50, opener, "WEB"))
            break
    readme = next(iter(sorted(folder.glob("README*"))), None)
    if readme:
        try:
            text = readme.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            text = ""
        for m in README_PY.finditer(text):
            if (folder / m.group(3)).is_file():
                raw.append((88, m.group(3), "PY"))
                break
    f = nat_pick(folder, ["*.sh"])
    if f:
        raw.append((45, "bash " + f, "SH"))

    pool = all_runs(folder)
    for typ in ("PY", "JS", "GO", "RS", "NET", "JAR", "BAT", "EXE", "PS1", "VBS",
                "SH", "WEB"):
        for i, run in enumerate(borrowed(typ, folder, pool)):
            raw.append((25 - i, run, typ))

    seen, valid = set(), []
    for score, run, typ in sorted(raw, key=lambda x: -x[0]):
        if run in seen or not valid_candidate(folder, run, typ):
            continue
        seen.add(run)
        valid.append((score, run, typ))
    return (valid[0] if valid else None), valid[:8]


def apply_cands(folder, cands, conf):
    runs = [c[1] for c in cands][:8]
    append_cfg(folder, ["cands=" + "||".join(runs), "conf=%d" % max(0, min(100, conf))])


def cycle_candidate(proj):
    """Pasa al siguiente método guardado y lo fija en el cfg."""
    lst = [c for c in proj.cands if c and c != proj.run]
    if not lst:
        return None
    nxt = lst[0]
    proj.cands = lst[1:] + ([proj.run] if proj.run else [])
    proj.run = nxt
    set_run(proj.folder, nxt)
    return nxt


# ============================================================== autoconfiguración
def ensure(exe, wid, label, st):
    if shutil.which(exe):
        return True
    st.set("Instalando %s (winget)" % label)
    if not IS_WIN or not shutil.which("winget"):
        return False
    run_cmd(["winget", "install", "-e", "--id", wid, "--silent",
             "--accept-package-agreements", "--accept-source-agreements"], st)
    fixpath()
    return shutil.which(exe) is not None


def finish(folder, run, typ, desc, warn=""):
    """Escribe la configuración. Conserva name/desc/ask ya puestos por el usuario."""
    cfg = folder / "d4ta.cfg"
    keep = []
    if cfg.is_file() and cfg_has_auto(cfg):
        try:
            for line in cfg.read_text(encoding="utf-8-sig", errors="ignore").splitlines():
                if "=" in line and line.split("=", 1)[0].strip().lower() in USER_KEYS:
                    keep.append(line.strip())
        except OSError:
            pass
        try:
            cfg.unlink()
        except OSError:
            pass
    append_cfg(folder, ["run=" + run, "type=" + typ, "desc=" + desc, "auto=1"] + keep)
    return Result("OK", desc, warn)


def pip_install(pyrun, pipu, args, st, folder):
    base = pyrun + ["-m", "pip", "install"] + pipu + ["--disable-pip-version-check"]
    if run_cmd(base + args, st, folder) == 0:
        return True
    retry = [a for a in pipu if a != "--user"] + ["--break-system-packages"]
    return run_cmd(base[:-1] + ["--disable-pip-version-check"] + retry + args,
                   st, folder) == 0


def py_setup(folder, entry, st):
    st.set("Proyecto Python detectado")
    py = find_python()
    warn = ""
    venv_py = folder / ".venv" / ("Scripts/python.exe" if IS_WIN else "bin/python")
    st.set("Creando el entorno virtual")
    if not venv_py.exists():
        run_cmd(py + ["-m", "venv", ".venv"], st, folder)
    if venv_py.exists():
        pyrun, pipu = [str(venv_py)], []
        run_prefix = ".venv\\Scripts\\python.exe" if IS_WIN else ".venv/bin/python"
        desc = "Python + venv: " + entry
    else:
        pyrun, pipu = py, ["--user"]
        run_prefix = py_str(py)
        desc = "Python: " + entry
        warn = "Entorno virtual imposible: módulos instalados para el usuario"
    req = folder / "requirements.txt"
    if req.is_file():
        st.set("Preparando requirements.txt")
        try:
            b = req.read_bytes()
            if b[:2] in (b"\xff\xfe", b"\xfe\xff"):
                req.write_text(b.decode("utf-16"), encoding="utf-8")
        except Exception:
            pass
        st.set("Instalando las dependencias (pip)")
        if not pip_install(pyrun, pipu, ["-r", "requirements.txt"], st, folder):
            st.set("Instalando paquete por paquete")
            fail = False
            try:
                lines = req.read_text(encoding="utf-8", errors="ignore").splitlines()
            except OSError:
                lines = []
            for line in lines:
                line = line.strip()
                if not line or line.startswith(("#", "-")):
                    continue
                if not pip_install(pyrun, pipu, [line], st, folder):
                    fail = True
            if fail:
                warn = "Algunas dependencias fallaron (ver el registro)"
    elif (folder / "pyproject.toml").is_file() or (folder / "setup.py").is_file():
        st.set("Instalando el proyecto (pip)")
        pip_install(pyrun, pipu, ["."], st, folder)
    st.set("Detectando módulos que faltan")
    run_cmd(pyrun + [str(Path(__file__).resolve()), "--deps", str(folder)], st, folder)
    return finish(folder, run_prefix + " " + entry, "PY", desc, warn)


def node_start_cmd(folder):
    try:
        pkg = json.loads((folder / "package.json").read_text(encoding="utf-8-sig"))
    except Exception:
        pkg = {}
    scripts = pkg.get("scripts") or {}
    if scripts.get("start"):
        return "npm start"
    if scripts.get("dev"):
        return "npm run dev"
    if pkg.get("main"):
        return "node " + str(pkg["main"])
    if (folder / "index.js").is_file():
        return "node index.js"
    return None


def node_setup(folder, st):
    st.set("Proyecto Node.js detectado")
    warn = ""
    if not ensure("node", "OpenJS.NodeJS.LTS", "Node.js", st):
        warn = "Node.js no encontrado - instálalo y relanza"
    if not warn and not (folder / "node_modules").exists():
        st.set("Instalando las dependencias (npm)")
        if run_cmd("npm install --no-audit --no-fund", st, folder) != 0:
            st.set("Nuevo intento (legacy-peer-deps)")
            run_cmd("npm install --no-audit --no-fund --legacy-peer-deps", st, folder)
    st.set("Buscando el script de arranque")
    nrun = node_start_cmd(folder)
    if not nrun:
        return None
    if nrun == "npm start" and not warn:
        try:
            pkg = json.loads((folder / "package.json").read_text(encoding="utf-8-sig"))
        except Exception:
            pkg = {}
        has_build = any((folder / d).exists() for d in ("dist", "build", ".next", "out"))
        if (pkg.get("scripts") or {}).get("build") and not has_build:
            st.set("Compilando el proyecto (npm run build)")
            run_cmd("npm run build", st, folder)
    return finish(folder, nrun, "JS", "Node.js: " + nrun, warn)


def setup_project(folder, st):
    """Crackea el proyecto, instala lo necesario y deja el menú desbloqueado."""
    st.set("Analizando el proyecto")

    if (folder / "go.mod").is_file():
        st.set("Proyecto Go detectado")
        warn = "" if ensure("go", "GoLang.Go", "Go", st) else \
            "Go no encontrado - instálalo y relanza"
        run = "go run ."
        if not (folder / "main.go").exists() and (folder / "cmd").is_dir():
            subs = sorted(p.name for p in (folder / "cmd").iterdir() if p.is_dir())
            if subs:
                run = "go run ./cmd/" + subs[0]
        return finish(folder, run, "GO", "Go: " + run, warn)

    if (folder / "Cargo.toml").is_file():
        st.set("Proyecto Rust detectado")
        warn = "" if ensure("cargo", "Rustlang.Rustup", "Rust", st) else \
            "Rust no encontrado - instálalo y relanza"
        if not warn:
            try:
                ok = subprocess.run(["cargo", "--version"],
                                    capture_output=True).returncode == 0
            except OSError:
                ok = False
            if not ok:
                st.set("Instalando la cadena Rust: rustup")
                run_cmd(["rustup", "default", "stable"], st)
        return finish(folder, "cargo run --release", "RS", "Rust: cargo run", warn)

    if next(folder.glob("*.csproj"), None):
        st.set("Proyecto .NET detectado")
        warn = "" if ensure("dotnet", "Microsoft.DotNet.SDK.8", ".NET", st) else \
            ".NET SDK no encontrado - instálalo y relanza"
        return finish(folder, "dotnet run", "NET", ".NET: dotnet run", warn)

    jar = None
    for pat in ("*.jar", "target/*.jar", "build/libs/*.jar"):
        f = next(folder.glob(pat), None)
        if f:
            jar = f.relative_to(folder).as_posix()
            break
    if jar:
        st.set("Proyecto Java detectado")
        warn = "" if ensure("java", "Microsoft.OpenJDK.21", "Java", st) else \
            "Java no encontrado - instálalo y relanza"
        return finish(folder, "java -jar " + jar, "JAR", "Java: " + jar, warn)

    st.set("Sondeando métodos de ejecución (cracker)")
    best, cands = crack(folder)
    if not best:
        st.set("Ningún método válido encontrado")
        return Result("NORUN", "No se encontró ningún método de ejecución válido "
                               "(ni python, node, bat, exe, html... ni recetas de otros proyectos)")

    score, run, typ = best
    conf = max(0, min(100, score))
    warn = "" if conf >= 50 else "Método deducido con poca confianza - usa [S] si falla"

    if typ == "PY":
        res = py_setup(folder, run, st)
    elif typ == "JS":
        res = node_setup(folder, st) or finish(folder, run, "JS", "Node.js: " + run)
    elif typ == "SH":
        if not ensure("bash", "Git.Git", "Git", st):
            return Result("NORUN", "Script Linux y Git Bash no está instalado")
        res = finish(folder, run, "SH", "Script shell: bash " + run,
                     "Script Linux: puede no funcionar en Windows")
    else:
        desc = ("[?] " if conf < 50 else "") + DESCS.get(typ, "Ejecuta: ") + run
        res = finish(folder, run, typ, desc, warn)

    if res.res == "OK":
        apply_cands(folder, cands, conf)
    return res


def fix_submodules(folder):
    """Recupera los submódulos Git que falten (ej: proyectos Rust)."""
    gm = folder / ".gitmodules"
    if not gm.is_file() or not (folder / ".git").exists() or not shutil.which("git"):
        return
    need = False
    for m in re.finditer(r"path\s*=\s*(.+)", gm.read_text(encoding="utf-8", errors="ignore")):
        sub = folder / m.group(1).strip()
        if not sub.is_dir() or not (sub / ".git").exists():
            need = True
    if not need:
        return
    msg(30, AMBER, "[D4TATOOL] Submódulo(s) faltante(s) detectado(s) - recuperando...")
    subprocess.run(["git", "-C", str(folder), "submodule", "update", "--init",
                    "--recursive"], capture_output=True)
    msg(30, GREEN, "[D4TATOOL] Submódulos al día", 1)
    w(at(30, 1) + CLR)


# ============================================================== detección de módulos (--deps)
ALIAS = {
    "cv2": "opencv-python", "PIL": "pillow", "yaml": "pyyaml", "bs4": "beautifulsoup4",
    "sklearn": "scikit-learn", "skimage": "scikit-image", "dotenv": "python-dotenv",
    "discord": "discord.py", "telegram": "python-telegram-bot", "telebot": "pyTelegramBotAPI",
    "Crypto": "pycryptodome", "Cryptodome": "pycryptodomex", "serial": "pyserial",
    "dateutil": "python-dateutil", "git": "GitPython", "magic": "python-magic",
    "win32api": "pywin32", "win32con": "pywin32", "win32gui": "pywin32",
    "win32com": "pywin32", "win32process": "pywin32", "pythoncom": "pywin32",
    "pywintypes": "pywin32", "usb": "pyusb", "zmq": "pyzmq", "jwt": "pyjwt",
    "OpenSSL": "pyopenssl", "attr": "attrs", "docx": "python-docx", "pptx": "python-pptx",
    "fitz": "pymupdf", "dns": "dnspython", "socks": "pysocks", "nacl": "pynacl",
    "speech_recognition": "SpeechRecognition", "MySQLdb": "mysqlclient",
    "psycopg2": "psycopg2-binary", "flask_cors": "flask-cors",
    "flask_sqlalchemy": "flask-sqlalchemy", "jose": "python-jose",
    "multipart": "python-multipart", "slugify": "python-slugify", "bson": "pymongo",
    "pkg_resources": "setuptools", "Xlib": "python-xlib", "wx": "wxPython",
    "google": None, "gi": None, "nmap": "python-nmap", "whois": "python-whois",
    "webdriver_manager": "webdriver-manager",
    "undetected_chromedriver": "undetected-chromedriver",
    "selenium_stealth": "selenium-stealth", "pyaudio": "PyAudio",
    "Levenshtein": "python-Levenshtein", "unidecode": "Unidecode", "babel": "Babel",
    "websocket": "websocket-client", "socketio": "python-socketio",
    "engineio": "python-engineio", "rest_framework": "djangorestframework",
    "kafka": "kafka-python", "grpc": "grpcio", "fake_useragent": "fake-useragent",
    "OpenGL": "PyOpenGL", "cairo": "pycairo", "Image": "pillow",
    "yoyo": "yoyo-migrations", "jwt_extended": "flask-jwt-extended",
    "frontmatter": "python-frontmatter", "brotli": "Brotli",
    "cchardet": "faust-cchardet", "requests_oauthlib": "requests-oauthlib",
    "authlib": "Authlib", "patoolib": "patool", "pygetwindow": "PyGetWindow",
    "pyautogui": "PyAutoGUI", "ffmpeg": "ffmpeg-python",
}
NEVER = {"fcntl", "termios", "pwd", "grp", "resource", "syslog", "posix", "tty", "pty",
         "crypt", "readline", "curses", "nis", "spwd", "ossaudiodev", "winreg", "msvcrt",
         "winsound", "msilib"}
GENERIC = {"utils", "util", "config", "configs", "settings", "helpers", "helper",
           "common", "constants", "models", "core", "lib", "libs", "tools", "app", "main",
           "src", "test", "tests", "conf", "database", "db", "api", "handlers", "modules",
           "plugins", "functions", "classes", "data", "cogs", "commands", "events"}
DEPS_SKIP = {".venv", "venv", "env", "node_modules", "__pycache__", "site-packages",
             "dist", "build"}


def deps_mode(root_arg):
    """Instala los módulos Python importados y ausentes (ejecutado por el venv del proyecto)."""
    root = os.path.abspath(root_arg)
    local, found = set(), set()

    def scan_file(path):
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                tree = ast.parse(fh.read())
        except Exception:
            return
        optional = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                txt = " ".join(ast.dump(h) for h in node.handlers)
                if "ImportError" in txt or "ModuleNotFoundError" in txt:
                    for stmt in node.body:
                        for sub in ast.walk(stmt):
                            optional.add(id(sub))
        for node in ast.walk(tree):
            if id(node) in optional:
                continue
            if isinstance(node, ast.Import):
                for a in node.names:
                    found.add(a.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    found.add(node.module.split(".")[0])

    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in DEPS_SKIP and not d.startswith(".")]
        if os.path.relpath(dp, root).count(os.sep) >= 4:
            dn[:] = []
        for d in dn:
            local.add(d)
        for f in fn:
            if f.endswith(".py"):
                local.add(f[:-3])
                scan_file(os.path.join(dp, f))

    std = set(getattr(sys, "stdlib_module_names", ()))
    todo, skipped = [], []
    for name in sorted(found):
        if (name in local or name in NEVER or name in std
                or name in sys.builtin_module_names or name.startswith("_")):
            continue
        if name in GENERIC:
            skipped.append(name)
            continue
        try:
            spec = importlib.util.find_spec(name)
        except Exception:
            spec = "x"
        if spec is not None:
            continue
        pkg = ALIAS.get(name, name)
        if pkg and pkg not in todo:
            todo.append(pkg)
    if skipped:
        print("[D4TATOOL] Ignorados (nombres genéricos, probablemente locales): " + ", ".join(skipped))
    if not todo:
        print("[D4TATOOL] Ningún módulo ausente detectado")
        return 0
    base = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check"]
    if sys.prefix == getattr(sys, "base_prefix", sys.prefix):
        base.append("--user")
    try:
        subprocess.run(base + ["--upgrade", "pip"], stdin=subprocess.DEVNULL,
                       capture_output=True, timeout=60)
    except Exception:
        pass

    def install(pkg):
        r = subprocess.run(base + [pkg], stdin=subprocess.DEVNULL, capture_output=True, text=True)
        if r.returncode == 0:
            return True, ""
        out = (r.stdout or "") + (r.stderr or "")
        if "externally-managed-environment" in out or "externally managed" in out:
            base2 = [a for a in base if a != "--user"] + ["--break-system-packages"]
            r2 = subprocess.run(base2 + [pkg],
                                stdin=subprocess.DEVNULL, capture_output=True, text=True)
            if r2.returncode == 0:
                return True, ""
            out = (r2.stdout or "") + (r2.stderr or "")
        lines = [l.strip() for l in out.strip().splitlines() if l.strip()]
        return False, (lines[-1][:120] if lines else "error desconocido")

    ok, ko = [], []
    for pkg in todo:
        print("[D4TATOOL] pip install " + pkg + " ...")
        sys.stdout.flush()
        good, err = install(pkg)
        if good:
            ok.append(pkg)
            print("[D4TATOOL]   -> OK: " + pkg)
        else:
            ko.append(pkg)
            print("[D4TATOOL]   -> FALLO: " + pkg + "  (" + err + ")")
        sys.stdout.flush()
    print("[D4TATOOL] Terminado: %d instalado(s), %d fallo(s)" % (len(ok), len(ko)))
    if ko:
        print("[D4TATOOL] No instalados: " + ", ".join(ko))
    return 0


# ============================================================== estado del menú
TIPS = [
    "Pega simplemente  usuario/proyecto  para importar un repo de GitHub",
    "Si un método falla, [S] prueba otro: se reutilizan los de otros proyectos",
    "Cada proyecto se configura automáticamente en el primer arranque",
    "Tras un lanzamiento:  [R] relanzar   [S] otro método   [A] auto-reparar",
    "Un archivo d4ta.cfg dentro de un proyecto permite fijar run / name / desc",
    "[P] y [N] cambian de página cuando tienes más de 8 proyectos",
    "Truco: lanza con  --fast  para saltarte la intro (o intro=0 en d4tatool.cfg)",
]


class State:
    page = 1
    projects = []
    tick_n = 0
    blink = 0
    tip = 0


S = State()


def n_pages():
    return max(1, math.ceil(len(S.projects) / PER))


def offset():
    return (S.page - 1) * PER


def on_page():
    return max(0, min(PER, len(S.projects) - offset()))


# ============================================================== dibujo del menú
def box_row(row, parts, pct=100):
    x = fc()
    bc, kc, dc = scale(BORDER, pct), scale(ACCENT, pct), scale(DIM, pct)
    s, vis = " ", 1
    for kind, text in parts:
        s += fg(kc if kind == "k" else dc) + text
        vis += len(text)
    w(at(row, x) + fg(bc) + "│" + RST + s + RST + " " * (BW - 2 - vis) + fg(bc) + "│" + RST)


def draw_slot(slot, pct=100, sel=False):
    x, row = fc(), 15 + slot
    bc = scale(BORDER, pct)
    idx = offset() + slot - 1
    bg = "\x1b[48;2;110;20;20m" if sel else ""
    left = fg(bc) + "│" + RST + bg
    right = RST + fg(bc) + "│" + RST
    if idx >= len(S.projects):
        w(at(row, x) + left + RST + " " * (BW - 2) + right)
        return
    p = S.projects[idx]
    nc = WHITE if sel else scale(LIGHT, pct)
    tc = scale(TYPE_COL.get(p.type.upper(), (255, 170, 160)), pct)
    body = (fg(scale(ACCENT, pct)) + "  [%d]  " % slot + fg(nc) + p.name[:20].ljust(20)
            + "  " + fg(tc) + p.type[:4].ljust(4) + "  " + fg(scale(DIM, pct))
            + p.desc[:32].ljust(32) + " ")
    w(at(row, x) + left + body + right)


def draw_frame(pct=100):
    x = fc()
    bc, nc, dc = scale(BORDER, pct), scale(LIGHT, pct), scale(DIM, pct)
    label = " %d/%d " % (S.page, n_pages())
    w(at(14, x) + fg(bc) + "╭─" + fg(nc) + " PROYECTOS " + fg(bc)
      + "─" * (BW - 2 - 11 - len(label) - 2) + fg(dc) + label + fg(bc) + "─╮" + RST)
    blank = fg(bc) + "│" + RST + " " * (BW - 2) + fg(bc) + "│" + RST
    w(at(15, x) + blank)
    w(at(24, x) + blank)
    for s in range(1, PER + 1):
        draw_slot(s, pct)
    w(at(25, x) + fg(bc) + "├" + "─" * (BW - 2) + "┤" + RST)
    box_row(26, [("k", "[I]"), ("d", " Importar     "), ("k", "[D]"),
                 ("d", " Suprimir     "), ("k", "[O]"), ("d", " Herramientas")], pct)
    box_row(27, [("k", "[P]"), ("d", " « Anterior     "), ("k", "[N]"),
                 ("d", " Siguiente »     "), ("k", "[Q]"), ("d", " Salir")], pct)
    w(at(28, x) + fg(bc) + "╰" + "─" * (BW - 2) + "╯" + RST)


def next_tip():
    S.tip = S.tip % len(TIPS) + 1
    cline(31, GREY, TIPS[S.tip - 1])


def tick():
    S.tick_n += 1
    S.blink ^= 1
    if S.tick_n % 5 == 0:
        sweep()
    if S.tick_n % 7 == 0:
        next_tip()
    dot = ACCENT if S.blink else (95, 30, 30)
    x = fc()
    w(at(29, x) + fg(dot) + "●" + fg(LIGHT) + " LISTO   " + fg(DIM)
      + "%d proyecto(s)" % len(S.projects) + "\x1b[K" + at(29, x + 62) + fg(DIM)
      + time.strftime("%H:%M:%S") + RST)
    flush()


def menu_body():
    w(at(12, 1) + "\x1b[J")
    cline(12, (225, 115, 105), "%s  •  by drako" % VERSION)
    for pct in (30, 60, 100):
        draw_frame(pct)
        nap(0.03)
    for s in range(1, PER + 1):
        draw_slot(s, 40)
        nap(0.012)
        draw_slot(s, 100)
    if not S.projects:
        cline(18, LIGHT, "Todavía no hay proyectos")
        cline(20, DIM, "[I] importa un repo de GitHub: todo se instala y configura automáticamente")
        for r in (18, 20):
            w(at(r, fc()) + fg(BORDER) + "│" + at(r, fc() + BW - 1) + "│" + RST)
    S.blink = 0
    next_tip()
    tick()


def back_to_menu(banner=False):
    S.projects = scan()
    S.page = min(S.page, n_pages())
    if banner:
        w(CLS + HIDE)
        for pct in (35, 70, 100):
            draw_banner(pct)
            nap(0.03)
    else:
        wipe_from(12)
    menu_body()


def repage():
    draw_frame(100)
    for s in range(1, PER + 1):
        draw_slot(s, 45)
        nap(0.01)
        draw_slot(s, 100)
    flush()


def blink_slot(slot):
    for _ in range(3):
        draw_slot(slot, 100, True)
        nap(0.06)
        draw_slot(slot, 100, False)
        nap(0.04)
    draw_slot(slot, 100, True)
    flush()


# ============================================================== intro
def intro():
    SKIPPABLE[0] = True
    try:
        hexs = "0123456789ABCDEF"
        for _ in range(34):                               # lluvia de código
            for _ in range(8):
                g = random.randint(90, 255)
                w(at(random.randint(1, 30), random.randint(1, cols()))
                  + fg((g, int(g * .35), int(g * .30))) + random.choice(hexs))
            nap(0.02)
        w(CLS)
        fx = (cols() - 45) // 2 + 1
        for g in range(1, 10):                            # logo en glitch
            amp = (9 - g) // 2
            col = (255, 110, 90) if g % 2 == 0 else (255, 45, 45)
            if g >= 8:
                col = WHITE
            if g == 9:
                col = ACCENT
            for r in range(1, 6):
                cx = max(1, fx + random.randint(-amp, amp))
                w(at(r + 7, 1) + CLR + at(r + 7, cx) + fg(col) + FSOC[r - 1] + RST)
            nap(0.04)
        nap(0.08)
        type_text(14, LIGHT, "Hola, amigo.")
        nap(0.25)
        for row, col, txt in ((16, (185, 55, 45), "[ OK ]  saltando el firewall"),
                              (17, (210, 80, 65), "[ OK ]  inyectando los módulos"),
                              (18, (235, 110, 95), "[ OK ]  acceso root obtenido"),
                              (19, (255, 160, 150), "[ OK ]  bienvenido a D4TATOOL")):
            cline(row, col, txt)
            nap(0.14)
        nap(0.4)
        for col in (WHITE, ACCENT, WHITE):
            for r in range(1, 6):
                w(at(r + 7, fx) + fg(col) + FSOC[r - 1] + RST)
            nap(0.03)
        nap(0.1)
        w(CLS)
        for f in (6, 14, 24, 36, 50, 64, 78, 90, 100):    # banner
            draw_banner(f)
            nap(0.05)
        for n in list(range(1, 11)) + list(range(10, 0, -1)):
            draw_banner(100, n)
            nap(0.03)
        draw_banner(100)
        for _ in range(7):
            draw_banner(100, random.randint(1, 10), (255, 60, 60))
            nap(0.04)
            draw_banner(100)
            nap(0.05)
        w(at(12, 1))
        type_text(12, (225, 115, 105), "%s  •  by drako" % VERSION)
        x = fc()
        w(at(14, x) + fg((200, 40, 45)))
        for _ in range(BW):
            w("═")
            nap(0.006)
        w(RST)
        type_text(15, LIGHT, "Recolección • Análisis • Explotación de datos", 0.02)
        spin = "-\\|/"
        for i in range(1, 31):
            pct = i * 100 // 30
            stage = ("Inicializando el núcleo" if i <= 8 else
                     "Cargando módulos" if i <= 16 else
                     "Analizando la carpeta de proyectos" if i <= 24 else "Finalizando")
            w(at(17, x) + fg((255, 150, 140)) + spin[i & 3] + fg((235, 70, 60)) + " ["
              + "█" * i + fg((90, 25, 25)) + "░" * (30 - i) + fg((235, 70, 60)) + "] "
              + fg((255, 230, 225)) + ("%3d%% " % pct) + fg((230, 140, 130)) + stage + "\x1b[K")
            nap(0.04)
        okc = (cols() - 26) // 2 + 1
        for i in range(10):
            col = WHITE if i % 2 == 0 else (255, 110, 100)
            w(at(19, okc) + fg(col) + "[ OK ]  D4TATOOL está listo " + "\x1b[K")
            nap(0.06)
        nap(0.5)
    except Skip:
        pass
    finally:
        SKIPPABLE[0] = False
    w(CLS + HIDE)
    draw_banner(100)
    flush()


# ============================================================== pantalla de trabajo
def run_work(title, label, fn):
    """Ejecuta fn(status) en un hilo durante una animación. [X] cancela."""
    try:
        LOG.write_text("", encoding="utf-8")
    except OSError:
        pass
    st = Status()
    box = {}

    def target():
        try:
            box["r"] = fn(st)
        except Exception:
            logw(traceback.format_exc())
            box["r"] = Result("FAIL")

    th = threading.Thread(target=target, daemon=True)
    th.start()
    wipe_from(13)
    cline(15, ACCENT, title)
    cline(17, WHITE, label)
    cline(28, (150, 90, 90), "[X] cancelar")
    bar = "█████" + "░" * 27
    bx = (cols() - 34) // 2 + 1
    t0, prev, hist = time.time(), "", []
    timed_out = False
    cancel_at = None
    while th.is_alive():
        bar = bar[-1] + bar[:-1]
        w(at(19, bx) + fg((200, 40, 45)) + "[" + fg((255, 160, 150)) + bar
          + fg((200, 40, 45)) + "]" + RST)
        cur = st.msg
        if cur != prev:
            if prev:
                hist = [prev] + hist[:2]
            prev = cur
            cline(21, WHITE, cur)
            for i, (row, col) in enumerate(((24, (120, 200, 160)), (25, (90, 150, 125)),
                                            (26, (65, 100, 90)))):
                w(at(row, 1) + CLR)
                if i < len(hist):
                    cline(row, col, "√ " + hist[i])
        elapsed = int(time.time() - t0)
        cline(22, DIM, "%d s" % elapsed)
        k = getkey(0.12)
        if k == "x" and not st.cancel.is_set():
            st.cancel.set()
            cancel_at = time.time()
            cline(28, AMBER, "Cancelando...")
        if elapsed > TIMEOUT_TOTAL and not st.cancel.is_set():
            logw("[D4TATOOL] tiempo agotado - operación interrumpida")
            timed_out = True
            st.cancel.set()
            cancel_at = time.time()
        if cancel_at and time.time() - cancel_at > CANCEL_GRACE:
            st.cancel.set()
            break
    th.join(timeout=5)
    wipe_from(15)
    if timed_out:
        return Result("FAIL")
    if st.cancel.is_set():
        return Result("CANCEL")
    return box.get("r", Result("FAIL"))


def show_log_tail(row):
    try:
        lines = LOG.read_text(encoding="utf-8", errors="ignore").splitlines()[-4:]
    except OSError:
        return
    shown = 0
    for l in lines:
        l = re.sub(r"[^A-Za-z0-9 _.,:;/\\()=+@#\[\]-]", " ", l).strip()
        if l and shown < 3:
            cline(row + shown, GREY, l[:80])
            shown += 1


# ============================================================== importar / borrar
def do_import():
    wipe_from(13)
    cline(15, ACCENT, "I M P O R T A R   Y   C R A C K E A R   U N   P R O Y E C T O")
    cline(17, LIGHT, "Pega la URL del repositorio  (o simplemente  usuario/proyecto)")
    cline(18, DIM, "Descarga, dependencias, sondeo de métodos y configuración: todo automático.")
    cline(22, GREY, "Se prueban todos los puntos de entrada y se eligen por confianza.")
    cline(23, AMBER, "Lanza solo repos de confianza: su código se ejecuta en tu PC.")
    w(at(20, fc()))
    raw = ask_line(fg(ACCENT) + "  ›  " + fg(WHITE))
    if not raw:
        return
    parsed = parse_github(raw)
    if not parsed:
        msg(24, RED, "URL inválida - ejemplos: https://github.com/usuario/proyecto  o  usuario/proyecto", 3)
        return
    url, owner, name, branch = parsed
    safe = name.rstrip(". ") or name
    if IS_WIN and safe.lower() in WIN_RESERVED:
        safe = "_" + safe
    dest = PROJECTS / safe
    if dest.exists():
        msg(24, RED, "La carpeta projets\\%s ya existe." % safe)
        msg(25, DIM, "Bórrala con [D] y vuelve a importarlo para actualizarlo.", 4)
        return
    label = "%s / %s" % (owner, name) + ("  (%s)" % branch if branch else "")

    def job(st):
        if not dl_fetch(url, dest, branch, st) or not dest.is_dir():
            return Result("FAIL")
        return setup_project(dest, st)

    res = run_work("I M P O R T A C I Ó N   Y   C R A C K E O", label, job)
    if res.res in ("FAIL", "CANCEL"):
        if dest.exists():
            rm_project(dest)
        if res.res == "CANCEL":
            msg(16, AMBER, "Importación cancelada", 2)
            return
        cline(16, RED, "×  Fallo en la importación")
        cline(18, DIM, "Comprueba la URL, tu conexión, y que el repositorio sea público.")
        show_log_tail(20)
        cline(25, ACCENT, "[L] Abrir el registro        [M] Menú")
        if choose("lm") == "l":
            open_path(LOG)
        return
    cline(16, GREEN, "●  %s importado y crackeado" % name)
    if res.res == "NORUN":
        cline(18, AMBER, "Ningún método válido ni receta reutilizable")
        cline(19, DIM, res.info)
        cline(20, DIM, "Añade un run.bat o un archivo d4ta.cfg  (run=comando)")
        msg(21, DIM, "", 5)
        return
    proj = next((p for p in scan() if p.folder == dest), None)
    if not proj:
        return
    conf = proj.conf
    tone = GREEN if conf >= 70 else AMBER if conf >= 40 else RED
    cline(18, LIGHT, "Método elegido: " + res.info)
    cline(19, tone, "Confianza: %d%%   (%d método(s) guardado(s))" % (conf, len(proj.cands)))
    if res.warn:
        cline(20, AMBER, "Atención: " + res.warn)
    opts = "[L] Lanzar        [M] Menú"
    if len(proj.cands) > 1:
        opts = "[L] Lanzar        [S] Otro método        [M] Menú"
    cline(22, ACCENT, opts)
    k = choose("lsm")
    if k == "l":
        launch(proj, skip_blink=True, tried=True)
    elif k == "s":
        if cycle_candidate(proj):
            launch(proj, skip_blink=True, tried=True)


def do_delete():
    cnt = on_page()
    if cnt < 1:
        return
    keys = "".join(str(i) for i in range(1, cnt + 1)) + "x"
    cline(30, (255, 140, 130), "¿Qué proyecto borrar?  pulsa su número   (X = cancelar)")
    k = choose(keys)
    if k == "x":
        w(at(30, 1) + CLR)
        return
    slot = int(k)
    proj = S.projects[offset() + slot - 1]
    draw_slot(slot, 100, True)
    cline(30, AMBER, "¿Borrar « %s » definitivamente?    [S] Sí    [N] No" % proj.name)
    if choose("sn") == "n":
        draw_slot(slot, 100, False)
        w(at(30, 1) + CLR)
        return
    cline(30, (255, 140, 130), "Borrando « %s »..." % proj.name)
    flush()
    if rm_project(proj.folder):
        msg(30, GREEN, "●  %s borrado" % proj.name, 0.8)
    else:
        msg(30, RED, "No se pudo borrar todo - cierra los programas que usen esa carpeta", 4)


# ============================================================== lanzamiento
def run_setup_screen(proj):
    w(CLS + HIDE)
    draw_banner(100)
    return run_work("C O N F I G U R A C I Ó N   A U T O M Á T I C A", proj.name,
                    lambda st: setup_project(proj.folder, st))


def reconf(proj):
    cfg = proj.folder / "d4ta.cfg"
    if cfg.is_file() and cfg_has_auto(cfg):
        cfg.unlink()
    res = run_setup_screen(proj)
    newp = load_project(proj.folder)
    if newp.run:
        return launch(newp, skip_blink=True, tried=True)
    cline(18, AMBER, "Ningún método válido para este proyecto")
    cline(20, DIM, res.info)
    cline(22, DIM, "Añade un run.bat o un archivo d4ta.cfg  (run=comando)")
    flush()
    time.sleep(5)


def tool_missing(proj, tok):
    w(CLS + HIDE)
    draw_banner(100)
    cline(14, RED, "Herramienta ausente: " + tok)
    cline(16, LIGHT, "Este proyecto necesita %s, que no está instalado en este PC." % tok)
    if tok.lower() in TOOL_WINGET and IS_WIN:
        cline(18, ACCENT, "[I] Instalar automáticamente (winget)")
    else:
        cline(18, ACCENT, "Instálala (ver setup.bat) y relanza.")
    opts = "[M] Menú"
    if len(proj.cands) > 1:
        opts = "[S] Probar otro método        " + opts
    cline(20, ACCENT, opts)
    k = choose("ism" if (tok.lower() in TOOL_WINGET and IS_WIN) else "sm")
    if k == "m":
        return
    if k == "s":
        if cycle_candidate(proj):
            return launch(proj, skip_blink=True, tried=True)
        return
    exe, wid, label = TOOL_WINGET[tok.lower()]

    def job(st):
        return Result("OK") if ensure(exe, wid, label, st) else Result("FAIL")

    res = run_work("I N S T A L A C I Ó N", label, job)
    if res.res == "OK":
        return launch(proj, skip_blink=True, tried=True)
    msg(16, RED, "Instalación imposible: instala %s a mano y relanza." % label, 4)


def launch_anim(name):
    wipe_from(1)
    cline(14, BORDER, "L A N Z A N D O")
    cline(16, WHITE, name)
    x = (cols() - 24) // 2 + 1
    for i in range(1, 25):
        w(at(18, x) + fg(ACCENT) + "█" * i + fg((90, 25, 25)) + "░" * (24 - i) + RST)
        nap(0.02)
    nap(0.2)
    w(CLS + SHOW + RST)
    flush()


def execute(proj, args):
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    cmd = proj.run + (" " + args if args else "")
    flush()
    with cooked():
        try:
            rc = subprocess.call(cmd, shell=True, cwd=str(proj.folder), env=env)
        except KeyboardInterrupt:
            rc = 130
        except OSError:
            rc = 127
    enable_vt()
    return rc


def ask_args(name):
    w("\n" + fg(ACCENT) + "  [D4TATOOL] Argumentos para %s: " % name + fg(WHITE))
    s = ask_line()
    w(RST)
    return s


def project_python(folder):
    venv = folder / ".venv" / ("Scripts/python.exe" if IS_WIN else "bin/python")
    if venv.exists():
        return [str(venv)], []
    return find_python(), ["--user"]


def pip_flow(proj):
    w("\n" + fg(ACCENT) + "  Módulo(s) pip a instalar (vacío = cancelar): " + fg(WHITE))
    mods = ask_line()
    w(RST)
    if not mods:
        return False
    pyrun, pipu = project_python(proj.folder)
    base = pyrun + ["-m", "pip", "install"] + pipu + ["--disable-pip-version-check"]
    with cooked():
        rc = subprocess.call(base + mods.split(), cwd=str(proj.folder))
        if rc != 0:
            w(fg(AMBER) + "  [D4TATOOL] Fallo - nuevo intento (--break-system-packages)...\n" + RST)
            flush()
            retry = [a for a in pipu if a != "--user"] + ["--break-system-packages"]
            rc = subprocess.call(base[:-1] + ["--disable-pip-version-check"] + retry
                                 + mods.split(), cwd=str(proj.folder))
    if rc == 0:
        w(fg(GREEN) + "  [D4TATOOL] Instalación correcta: %s\n" % mods + RST)
    else:
        w(fg(RED) + "  [D4TATOOL] Fallo en la instalación - revisa el/los nombre(s) de módulo(s)\n" + RST)
    flush()
    return True


def autofix(proj):
    w("\n" + fg(ACCENT) + "  [D4TATOOL] Buscando los módulos que faltan...\n" + RST)
    flush()
    pyrun, _ = project_python(proj.folder)
    with cooked():
        subprocess.call(pyrun + [str(Path(__file__).resolve()), "--deps", str(proj.folder)],
                        cwd=str(proj.folder))


def run_session(proj):
    alt_off()            # el proyecto corre en la pantalla normal (salida desplazable)
    try:
        _run_session(proj)
    finally:
        alt_on()


def _run_session(proj):
    w(CLS + SHOW + RST)
    args = ask_args(proj.name) if proj.ask else ""
    arg_tries = 0
    while True:
        rc = execute(proj, args)
        if rc == 0:
            save_recipe(proj.type, proj.run)
        if rc == 2 and not args and arg_tries < 3:
            arg_tries += 1
            w("\n" + fg(AMBER) + "  El programa parece esperar argumentos (ej: un usuario, una URL...)\n")
            w(fg(ACCENT) + "  Argumentos (vacío = volver al menú): " + fg(WHITE))
            args = ask_line()
            w(RST)
            if args:
                append_cfg(proj.folder, ["ask=1"])
                proj.ask = True
                continue
        if rc == 0:
            w("\n" + fg(GREEN) + "  [D4TATOOL] Proyecto terminado - código de salida: 0\n" + RST)
        else:
            w("\n" + fg(RED) + "  [D4TATOOL] El proyecto se detuvo con un error - código: %s\n" % rc + RST)
            if len(proj.cands) > 1:
                w(fg(DIM) + "  Método actual: " + proj.run + "\n" + RST)
        hint = lambda k, t: fg(ACCENT) + "[%s]" % k + fg(DIM) + " %s  " % t
        line = hint("M", "Menú") + hint("R", "Relanzar")
        if len(proj.cands) > 1:
            line += hint("S", "Otro método")
        line += hint("C", "Reconfig.") + hint("A", "Auto-reparar") + hint("I", "pip") + hint("O", "Carpeta")
        w("\n  " + line + RST + "\n")
        while True:
            k = choose("mrsciaon")
            if k == "o":
                open_path(proj.folder)
                continue
            break
        if k == "m":
            return
        if k == "c":
            return reconf(proj)
        if k == "s":
            if not cycle_candidate(proj):
                msg(32, AMBER, "No hay otro método guardado", 1.5)
                continue
            args = ask_args(proj.name) if proj.ask else ""
            arg_tries = 0
            continue
        if k == "r":
            args = ask_args(proj.name) if proj.ask else ""
            arg_tries = 0
        elif k == "i":
            pip_flow(proj)
        elif k == "a":
            autofix(proj)


def launch(proj, slot=None, skip_blink=False, tried=False):
    if not skip_blink and slot:
        blink_slot(slot)
    if not proj.run and proj.cands:
        proj.run = proj.cands[0]
        set_run(proj.folder, proj.run)
    if not proj.run:
        if not tried:
            return reconf(proj)
        msg(30, RED, "Ningún método: añade run.bat / main.py o un archivo d4ta.cfg", 4)
        return
    tok = proj.run.split()[0]
    if tok.lower() in NEED and not tool_ok(tok):
        return tool_missing(proj, tok)
    if tok.lower() == "cargo":
        fix_submodules(proj.folder)
    launch_anim(proj.name)
    fixpath()
    run_session(proj)


# ============================================================== caja de herramientas
class Out:
    def __init__(self):
        self.row = 27

    def put(self, r, label, value, color=(255, 225, 220)):
        x = fc()
        w(at(r, x) + fg(ACCENT) + " ▸ " + fg(DIM) + label[:15] + "\x1b[%dG" % (x + 18)
          + fg(color) + value[:BW - 20] + "\x1b[K" + RST)

    def line(self, label, value, color=(255, 225, 220)):
        if self.row > 32:
            return self.row
        r = self.row
        self.put(r, label, value, color)
        self.row += 1
        nap(0.03)
        return r


ITEMS = [
    ("Info del sistema", "Máquina, CPU, memoria, disco"),
    ("Red", "IP local y pública, latencia, DNS"),
    ("Actualizar todo", "git pull en todos los proyectos"),
    ("Limpiar", "Borra __pycache__ de los proyectos"),
    ("Carpeta de proyectos", "Abre el explorador"),
    ("Terminal", "Consola en la carpeta de proyectos"),
    ("Username Sniper", "Pseudos de 3-5 caracteres Discord"),
]


def draw_tools():
    wipe_from(12)
    cline(12, (225, 115, 105), "H E R R A M I E N T A S")
    x = fc()
    w(at(14, x) + fg(BORDER) + "╭─" + fg(LIGHT) + " HERRAMIENTAS " + fg(BORDER)
      + "─" * (BW - 16) + "╮" + RST)
    w(at(15, x) + fg(BORDER) + "│" + RST + " " * (BW - 2) + fg(BORDER) + "│" + RST)
    for i, (lab, desc) in enumerate(ITEMS, 1):
        w(at(15 + i, x) + fg(BORDER) + "│" + fg(ACCENT) + "  [%d]  " % i + fg(LIGHT)
          + lab.ljust(22)[:22] + fg(DIM) + desc.ljust(38)[:38] + " " + fg(BORDER) + "│" + RST)
        nap(0.03)
    w(at(23, x) + fg(BORDER) + "├" + "─" * (BW - 2) + "┤" + RST)
    box_row(24, [("k", "[R]"), ("d", " Volver al menú")])
    w(at(25, x) + fg(BORDER) + "╰" + "─" * (BW - 2) + "╯" + RST)
    flush()


def windows_caption():
    try:
        ver = platform.version()
        build = int(ver.split(".")[-1]) if ver.split(".")[-1].isdigit() else 0
        name = "Windows 11" if build >= 22000 else "Windows " + platform.release()
        ed = ""
        try:
            ed = " " + platform.win32_edition()
        except Exception:
            pass
        return "%s%s (build %s)" % (name, ed, build)
    except Exception:
        return platform.platform()


def mem_info():
    """(usado_GB, total_GB) o None"""
    try:
        if IS_WIN:
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            ms = MS()
            ms.dwLength = ctypes.sizeof(ms)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))
            tot, free = ms.ullTotalPhys, ms.ullAvailPhys
        else:
            info = {}
            for line in open("/proc/meminfo"):
                k, v = line.split(":", 1)
                info[k] = int(v.split()[0]) * 1024
            tot, free = info["MemTotal"], info.get("MemAvailable", info["MemFree"])
        g = 1024 ** 3
        return round((tot - free) / g, 1), round(tot / g, 1)
    except Exception:
        return None


def uptime_secs():
    try:
        if IS_WIN:
            import ctypes
            ctypes.windll.kernel32.GetTickCount64.restype = ctypes.c_ulonglong
            return int(ctypes.windll.kernel32.GetTickCount64() // 1000)
        return int(float(open("/proc/uptime").read().split()[0]))
    except Exception:
        return None


def cpu_name():
    try:
        if IS_WIN:
            import winreg
            k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                               r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            return winreg.QueryValueEx(k, "ProcessorNameString")[0].strip()
        for line in open("/proc/cpuinfo"):
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return platform.processor() or "desconocido"


def t_system(out):
    r = out.line("Recopilando", "en curso...", ORANGE)
    out.row = r
    out.line("Sistema", windows_caption() if IS_WIN else platform.platform())
    out.line("Procesador", cpu_name())
    out.line("Núcleos", "%s hilos" % os.cpu_count())
    m = mem_info()
    out.line("Memoria", "%s / %s GB usados" % m if m else "no disponible")
    try:
        free = shutil.disk_usage(str(ROOT)).free / 1024 ** 3
        out.line("Disco", "%.1f GB libres" % free)
    except OSError:
        out.line("Disco", "no disponible")
    up = uptime_secs()
    if up is not None:
        out.line("Encendido", "%dd %dh %dmin" % (up // 86400, up % 86400 // 3600, up % 3600 // 60))
    out.line("Sesión", "%s @ %s" % (getpass.getuser(), socket.gethostname()))


def t_network(out):
    r = out.line("Recopilando", "en curso...", ORANGE)
    out.row = r
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except OSError:
        try:
            ip = socket.gethostbyname(socket.gethostname())
        except OSError:
            ip = "no disponible"
    out.line("IP local", ip)
    try:
        req = urllib.request.Request("https://api.ipify.org", headers={"User-Agent": "D4TATOOL"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            pub = resp.read().decode().strip()
    except Exception:
        pub = "sin conexión"
    out.line("IP pública", pub)
    try:
        t0 = time.time()
        socket.create_connection(("1.1.1.1", 443), timeout=2).close()
        lat = "%d ms" % int((time.time() - t0) * 1000)
    except OSError:
        lat = "fallo"
    out.line("Latencia 1.1.1.1", lat)
    try:
        out.line("DNS github.com", "OK (%s)" % socket.gethostbyname("github.com"))
    except OSError:
        out.line("DNS github.com", "fallo")


def t_update(out):
    if not shutil.which("git"):
        out.line("Git", "no encontrado: instala Git para usar esta herramienta", RED)
        return
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    n = 0
    for p in PROJECTS.iterdir() if PROJECTS.is_dir() else []:
        if not (p / ".git").exists():
            continue
        n += 1
        r = out.line(p.name, "actualizando...", ORANGE)
        try:
            rc = subprocess.run(["git", "pull", "--ff-only"], cwd=str(p), env=env,
                                capture_output=True, timeout=300).returncode
            if rc == 0 and (p / ".gitmodules").exists():
                subprocess.run(["git", "submodule", "update", "--init", "--recursive",
                                "--depth", "1"], cwd=str(p), env=env,
                               capture_output=True, timeout=300)
        except Exception:
            rc = 1
        if rc == 0:
            out.put(r, p.name, "al día", GREEN)
        else:
            out.put(r, p.name, "fallo: cambios locales o sin conexión", RED)
        flush()
    if n == 0:
        out.line("Proyectos", "ningún repo Git que actualizar", DIM)


def cleantemp():
    for n in ("d4tatool_tool.txt", "d4tatool_tail.txt", "d4tatool_tmp.txt",
              "d4tatool.zip"):
        try:
            (TMP / n).unlink()
        except OSError:
            pass
    shutil.rmtree(TMP / "d4tatool_x", ignore_errors=True)


def t_clean(out):
    n = 0
    if PROJECTS.is_dir():
        for dp, dn, _ in os.walk(PROJECTS):
            dn[:] = [d for d in dn if d not in (".git", "node_modules")]
            for d in list(dn):
                if d == "__pycache__":
                    shutil.rmtree(os.path.join(dp, d), ignore_errors=True)
                    dn.remove(d)
                    n += 1
    cleantemp()
    try:
        LOG.unlink()
    except OSError:
        pass
    out.line("Cachés Python", "%d carpeta(s) __pycache__ borrada(s)" % n, GREEN)
    out.line("Registros", "archivos temporales borrados", GREEN)


def t_folder(out):
    open_path(PROJECTS)
    out.line("Explorador", "carpeta de proyectos abierta", GREEN)


def t_terminal(out):
    try:
        if IS_WIN:
            subprocess.Popen("cmd /k title D4TATOOL terminal & prompt D4TATOOL$G$S",
                             cwd=str(PROJECTS),
                             creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            for t in ("x-terminal-emulator", "gnome-terminal", "konsole", "xterm"):
                if shutil.which(t):
                    subprocess.Popen([t], cwd=str(PROJECTS))
                    break
            else:
                raise OSError("ningún terminal")
        out.line("Terminal", "abierto en la carpeta de proyectos", GREEN)
    except Exception:
        out.line("Terminal", "no se pudo abrir un terminal", RED)


# ---------------------------------------------------------------- username sniper
SN = {"len": 4, "mode": 3, "n": 10, "list": [], "page": 1, "t": 0, "msg": ""}
SN_FILE = ROOT / "pseudos_sniper.txt"
ALPHA = "abcdefghijklmnopqrstuvwxyz"
DIGITS = "0123456789"


def sn_sets(mode):
    if mode == 1:
        return "letras (a-z)", ALPHA, ALPHA
    if mode == 2:
        return "letras + números", ALPHA + DIGITS, ALPHA + DIGITS
    return "letras, números, _ y . (al menos 1)", ALPHA + DIGITS + "_", ALPHA + DIGITS + "_."


def sn_gen():
    _, ends, mid = sn_sets(SN["mode"])
    n = SN["len"]
    while True:
        s = "".join(random.choice(ends if i in (0, n - 1) else mid) for i in range(n))
        if ".." in s:
            continue
        if SN["mode"] == 3 and not any(c in "_." for c in s):
            continue
        return s


def sn_notepad():
    if not IS_WIN:
        return
    try:
        subprocess.run(["taskkill", "/f", "/im", "notepad.exe", "/fi",
                        "WINDOWTITLE eq %s*" % SN_FILE.stem], capture_output=True)
        subprocess.Popen(["notepad", str(SN_FILE)])
    except Exception:
        pass


def sn_write(lst):
    """Escribe la lista en la carpeta del script o, si no, en la temporal."""
    global SN_FILE
    data = "\n".join(lst) + "\n"
    for p in (ROOT / "pseudos_sniper.txt", TMP / "pseudos_sniper.txt"):
        try:
            p.write_text(data, encoding="utf-8")
            SN_FILE = p
            return True
        except OSError:
            continue
    return False


def sn_batch():
    w(at(31, 3) + "\x1b[J" + fg(LIGHT) + "Generando..." + RST)
    flush()
    seen, lst = set(), []
    while len(lst) < SN["n"]:
        s = sn_gen()
        if s not in seen:
            seen.add(s)
            lst.append(s)
    SN["list"], SN["page"], SN["t"] = lst, 1, 0
    if not sn_write(lst):
        SN["msg"] = "No se pudo escribir el archivo pseudos_sniper.txt"
    sn_notepad()


def sn_ask_count():
    w(at(31, 3) + "\x1b[J")
    s = ask_line(fg(LIGHT) + "¿Cuántos pseudos (1 a 1000, Enter = 10)? ")
    n = 10
    if s.isdigit():
        n = min(1000, max(1, int(s)))
    SN["n"] = n


def sn_page():
    pc = max(1, min(25, (cols() - 4) // (SN["len"] + 2)))
    per_page = pc * 14
    total = max(1, math.ceil(len(SN["list"]) / per_page))
    if SN["page"] > total:
        SN["page"] = 1
    base = (SN["page"] - 1) * per_page
    w(at(13, 1) + "\x1b[J")
    w(at(13, 3) + fg(DIM) + "%d pseudos de %d car. - %s - página %d/%d"
      % (len(SN["list"]), SN["len"], sn_sets(SN["mode"])[0], SN["page"], total) + RST)
    for r in range(14):
        cells = SN["list"][base + r * pc: base + (r + 1) * pc]
        if cells:
            w(at(15 + r, 3) + fg((255, 225, 220)) + "  ".join(cells) + RST)
    if SN["msg"]:
        w(at(29, 3) + fg(AMBER) + SN["msg"] + RST)
        SN["msg"] = ""
    w(at(30, 3) + fg(GREEN) + "Archivo: %s (abierto en el Bloc de notas)" % SN_FILE.name + RST)
    w(at(31, 3) + fg(DIM) + "[S] nueva serie  [P] página siguiente  [N] cantidad  [L] longitud" + RST)
    w(at(32, 3) + fg(DIM) + "[M] modo  [O] Bloc de notas  [C] copiar  [T] siguiente pseudo + Discord  [R] volver" + RST)
    flush()


def t_sniper(out):
    w(at(31, 3) + "\x1b[J")
    s = ask_line(fg(LIGHT) + "Número de caracteres (3 a 5, Enter = 4): ")
    SN["len"] = 3 if s == "3" else 5 if s == "5" else 4
    sn_ask_count()
    sn_batch()
    wipe_from(12)
    cline(12, (225, 115, 105), "U S E R N A M E   S N I P E R")
    while True:
        sn_page()
        k = choose("soclmnptr")
        if k == "s":
            sn_batch()
        elif k == "o":
            sn_notepad()
        elif k == "c":
            copy_clip("\r\n".join(SN["list"]))
        elif k == "l":
            SN["len"] = (SN["len"] - 2) % 3 + 3
            sn_batch()
        elif k == "m":
            SN["mode"] = SN["mode"] % 3 + 1
            sn_batch()
        elif k == "n":
            sn_ask_count()
            sn_batch()
        elif k == "p":
            SN["page"] += 1
        elif k == "t":
            first = SN["t"] == 0
            SN["t"] += 1
            if SN["t"] > len(SN["list"]):
                SN["t"] = 1
            cur = SN["list"][SN["t"] - 1]
            copied = copy_clip(cur)
            if first:
                try:
                    webbrowser.open("https://discord.com/app")
                except Exception:
                    pass
            SN["msg"] = "%s: %s   [%d/%d]   T = siguiente pseudo" % (
                "Copiado" if copied else "Portapapeles no disponible", cur,
                SN["t"], len(SN["list"]))
        else:
            return True


TOOLS = [t_system, t_network, t_update, t_clean, t_folder, t_terminal, t_sniper]


def tools():
    draw_tools()
    n = 0
    while True:
        k = getkey(1.0)
        if k is None:
            n += 1
            if n % 4 == 0:
                sweep()
            continue
        if k == "r":
            return
        if k in "1234567" and k:
            w(at(26, 1) + "\x1b[J")
            redraw = TOOLS[int(k) - 1](Out())
            if redraw:
                draw_tools()
            flush()


# ============================================================== salir / main
def do_quit():
    wipe_from(12)
    for f in (85, 65, 45, 28, 14, 0):
        draw_banner(f)
        nap(0.03)
    for col in ((110, 30, 30), (200, 60, 55), (255, 140, 130)):
        cline(15, col, "H  A  S  T  A     P  R  O  N  T  O")
        nap(0.12)
    nap(0.4)
    cleantemp()


def read_intro_setting():
    cfg = ROOT / "d4tatool.cfg"
    try:
        for line in cfg.read_text(encoding="utf-8-sig", errors="ignore").splitlines():
            if line.strip().lower().replace(" ", "") == "intro=0":
                return False
    except OSError:
        pass
    return True


def run_ui(fast):
    if not PROJECTS.is_dir():
        PROJECTS.mkdir(parents=True, exist_ok=True)
    fixpath()
    w(CLS + HIDE)
    if fast or not read_intro_setting():
        draw_banner(100)
    else:
        intro()
    S.projects = scan()
    menu_body()
    while True:
        k = getkey(1.0)
        if k is None:
            tick()
            continue
        if k.isdigit() and 1 <= int(k) <= on_page():
            slot = int(k)
            launch(S.projects[offset() + slot - 1], slot=slot)
            back_to_menu(banner=True)
        elif k == "i":
            do_import()
            back_to_menu()
        elif k == "d":
            do_delete()
            back_to_menu()
        elif k == "p":
            if S.page > 1:
                S.page -= 1
                repage()
        elif k == "n":
            if S.page < n_pages():
                S.page += 1
                repage()
        elif k == "o":
            tools()
            back_to_menu()
        elif k == "q":
            do_quit()
            return


def main(argv):
    if argv[:1] == ["--deps"] and len(argv) > 1:
        return deps_mode(argv[1])
    if argv[:1] in (["--version"], ["-V"]):
        print("D4TATOOL " + VERSION)
        return 0
    if sys.version_info < (3, 8):
        print("D4TATOOL requiere Python 3.8 o superior.")
        return 1
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("D4TATOOL debe lanzarse en una terminal interactiva.")
        return 1
    fast = any(a.lower() in ("--fast", "/fast") for a in argv)
    setup_terminal()
    if shutil.get_terminal_size((100, 34)).lines < 33:
        print("Ventana demasiado pequeña: agrándala (100x34 recomendado) y relanza.")
        return 1
    raw_on()
    alt_on()
    try:
        run_ui(fast)
    except KeyboardInterrupt:
        pass
    except Exception:
        raw_off()
        alt_off()
        w(RST + SHOW)
        flush()
        traceback.print_exc()
        input("\nError inesperado - pulsa Enter para salir...")
        return 1
    finally:
        w(RST + SHOW)
        flush()
        raw_off()
        alt_off()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
