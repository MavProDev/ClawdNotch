"""
Generate Clawd .ico icon and create a desktop shortcut for Claude Notch.
Run once: python create_shortcut.py

The shortcut points to a stable launcher at ~/.claude-notch/launcher.pyw
so moving the project folder only requires re-running this script — the
shortcut itself never needs to change.
"""
import struct, os, sys, zlib, json, tempfile
from pathlib import Path

# ── Clawd pixel grid (11x10) — body=1, eyes=2, empty=0 ──
CLAWD = [
    [0,0,1,1,0,0,0,1,1,0,0],
    [0,1,1,1,1,1,1,1,1,1,0],
    [0,1,1,1,1,1,1,1,1,1,0],
    [0,1,2,2,1,1,1,2,2,1,0],
    [0,1,2,2,1,1,1,2,2,1,0],
    [0,1,1,1,1,1,1,1,1,1,0],
    [0,0,1,1,1,1,1,1,1,0,0],
    [0,0,1,0,1,0,1,0,1,0,0],
    [0,0,1,0,1,0,1,0,1,0,0],
    [0,0,1,0,1,0,1,0,1,0,0],
]

CORAL = (217, 119, 87, 255)   # body
EYE   = (35, 25, 22, 255)     # eyes
TRANS = (0, 0, 0, 0)          # transparent

def render_clawd_rgba(size):
    """Render Clawd grid into an RGBA pixel buffer at the given square size."""
    rows, cols = len(CLAWD), len(CLAWD[0])
    # Scale factor — integer scale, centered in canvas
    scale = size // max(rows, cols)
    if scale < 1: scale = 1
    pw = cols * scale
    ph = rows * scale
    ox = (size - pw) // 2
    oy = (size - ph) // 2

    pixels = [[TRANS] * size for _ in range(size)]
    for ri, row in enumerate(CLAWD):
        for ci, cell in enumerate(row):
            if cell == 0:
                continue
            color = CORAL if cell == 1 else EYE
            for dy in range(scale):
                for dx in range(scale):
                    px = ox + ci * scale + dx
                    py = oy + ri * scale + dy
                    if 0 <= px < size and 0 <= py < size:
                        pixels[py][px] = color
    return pixels


def make_png(pixels, size):
    """Create a minimal PNG from RGBA pixel data."""
    def chunk(ctype, data):
        c = ctype + data
        return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xFFFFFFFF)

    raw = b''
    for row in pixels:
        raw += b'\x00'  # filter: none
        for r, g, b, a in row:
            raw += struct.pack('BBBB', r, g, b, a)

    ihdr = struct.pack('>IIBBBBB', size, size, 8, 6, 0, 0, 0)  # 8-bit RGBA
    compressed = zlib.compress(raw, 9)

    png = b'\x89PNG\r\n\x1a\n'
    png += chunk(b'IHDR', ihdr)
    png += chunk(b'IDAT', compressed)
    png += chunk(b'IEND', b'')
    return png


def make_ico(sizes=(16, 32, 48, 64, 128, 256)):
    """Create a multi-resolution .ico file with PNG-compressed images."""
    images = []
    for sz in sizes:
        pixels = render_clawd_rgba(sz)
        png_data = make_png(pixels, sz)
        images.append((sz, png_data))

    # ICO header: 2 reserved + 2 type (1=icon) + 2 count
    header = struct.pack('<HHH', 0, 1, len(images))
    entries = b''
    data = b''
    offset = 6 + len(images) * 16  # header + all directory entries

    for sz, png_data in images:
        w = 0 if sz >= 256 else sz
        h = 0 if sz >= 256 else sz
        entries += struct.pack('<BBBBHHII', w, h, 0, 0, 1, 32, len(png_data), offset)
        data += png_data
        offset += len(png_data)

    return header + entries + data


CONFIG_DIR = Path.home() / ".claude-notch"


def create_launcher(project_dir: Path, pythonw: str):
    """Create a stable launcher at ~/.claude-notch/launcher.pyw.

    The launcher reads install_path from config.json and runs
    ``python -m claude_notch`` from that directory.  The shortcut always
    points to a fixed location and survives the project folder being
    moved — just re-run create_shortcut.py.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    # Update config.json with the current install path
    config_file = CONFIG_DIR / "config.json"
    config = {}
    if config_file.exists():
        try:
            with open(config_file) as f:
                config = json.load(f)
        except Exception:
            pass
    config["install_path"] = str(project_dir)
    # Atomic write: write to temp file then rename (Bug #15 fix)
    fd, tmp_path = tempfile.mkstemp(dir=str(CONFIG_DIR), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(config, f, indent=2)
        os.replace(tmp_path, str(config_file))
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    # Write the launcher script
    launcher = CONFIG_DIR / "launcher.pyw"
    launcher.write_text('''"""Claude Notch launcher — points to wherever the project currently lives."""
import json, subprocess, sys, os
from pathlib import Path

CONFIG = Path.home() / ".claude-notch" / "config.json"

def main():
    if not CONFIG.exists():
        raise SystemExit("Claude Notch config not found. Run create_shortcut.py first.")
    with open(CONFIG) as f:
        config = json.load(f)
    install_path = config.get("install_path", "")
    # Validate install_path is a real local directory (not UNC, not empty)
    if not install_path or install_path.startswith("\\\\\\\\") or install_path.startswith("//"):
        raise SystemExit("Invalid install_path in config.json.")
    if not os.path.isabs(install_path) or not os.path.isdir(install_path):
        raise SystemExit(f"install_path does not exist: {install_path}")
    pkg_dir = Path(install_path) / "claude_notch"
    init_file = pkg_dir / "__init__.py"
    if not pkg_dir.is_dir() or not init_file.is_file():
        raise SystemExit(
            f"claude_notch/ package not found at {pkg_dir}.\\n"
            f"If you moved the folder, re-run create_shortcut.py from the new location."
        )
    # Launch with pythonw to avoid console window
    pythonw = Path(sys.executable).parent / "pythonw.exe"
    if not pythonw.exists():
        pythonw = sys.executable
    subprocess.Popen([str(pythonw), "-m", "claude_notch"], cwd=install_path)

if __name__ == "__main__":
    main()
''', encoding="utf-8")

    # Also copy icon to stable location so shortcut icon survives moves
    icon_src = project_dir / "clawd.ico"
    icon_dst = CONFIG_DIR / "clawd.ico"
    if icon_src.exists():
        icon_dst.write_bytes(icon_src.read_bytes())

    return launcher, icon_dst


def _ps_escape(s: str) -> str:
    """Escape a string for safe embedding in PowerShell double-quoted strings."""
    return str(s).replace('`', '``').replace('"', '`"').replace('$', '`$').replace('#', '`#')


def create_windows_shortcut(target, shortcut_path, icon_path, args=""):
    """Create a .lnk shortcut using PowerShell (no COM dependencies)."""
    ps_script = f'''
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut("{_ps_escape(shortcut_path)}")
$sc.TargetPath = "{_ps_escape(target)}"
$sc.Arguments = '"{_ps_escape(args)}"'
$sc.WorkingDirectory = "{_ps_escape(Path(args).parent if args else "")}"
$sc.IconLocation = "{_ps_escape(icon_path)},0"
$sc.Description = "Claude Notch — Desktop Overlay by @ReelDad"
$sc.WindowStyle = 7
$sc.Save()
'''
    import subprocess
    result = subprocess.run(
        ['powershell', '-ExecutionPolicy', 'Bypass', '-Command', ps_script],
        capture_output=True, text=True
    )
    return result.returncode == 0, result.stderr


def find_pythonw():
    """Find pythonw.exe path."""
    # Try alongside current python
    pdir = Path(sys.executable).parent
    pw = pdir / "pythonw.exe"
    if pw.exists():
        return str(pw)
    # Fallback
    import shutil
    found = shutil.which("pythonw")
    return found or str(pw)


def main():
    project_dir = Path(__file__).parent.resolve()
    icon_path = project_dir / "clawd.ico"

    # Generate icon
    print("Generating Clawd icon...")
    ico_data = make_ico()
    icon_path.write_bytes(ico_data)
    print(f"  Created: {icon_path} ({len(ico_data):,} bytes)")

    # Find pythonw
    pythonw = find_pythonw()
    print(f"  Using: {pythonw}")

    # Create stable launcher at ~/.claude-notch/
    print("Creating stable launcher...")
    launcher, stable_icon = create_launcher(project_dir, pythonw)
    print(f"  Launcher: {launcher}")
    print(f"  Icon: {stable_icon}")

    # Create desktop shortcut pointing to the LAUNCHER (not directly to claude_notch.py)
    desktop = Path.home() / "OneDrive" / "Desktop"
    if not desktop.exists():
        desktop = Path.home() / "Desktop"
    shortcut_path = desktop / "Claude Notch.lnk"

    print("Creating desktop shortcut...")
    ok, err = create_windows_shortcut(
        target=pythonw,
        shortcut_path=str(shortcut_path),
        icon_path=str(stable_icon),
        args=str(launcher),
    )

    if ok:
        print(f"  Created: {shortcut_path}")
        print("\nDone! The shortcut now uses a stable launcher.")
        print("If you move the project folder, just re-run:")
        print("  python create_shortcut.py")
        print("The shortcut itself never needs to change.")
    else:
        print(f"  Error: {err}")
        print("  Try running as administrator if it fails.")


if __name__ == "__main__":
    main()
