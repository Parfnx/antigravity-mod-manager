"""Unified app.asar mod manager for Antigravity sidebar extensions."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import urllib.request
import zipfile
from typing import Any

RESOURCES_DIR = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "antigravity", "resources")
DEFAULT_ASAR = os.path.join(RESOURCES_DIR, "app.asar")
DEFAULT_MODS_CACHE = os.path.join(os.path.expanduser("~"), ".gemini", "antigravity", "mods")
STATE_FILE = os.path.join(os.path.expanduser("~"), ".gemini", "antigravity", "mod-manager.json")
SCRATCH_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MODULES: dict[str, dict[str, str]] = {
    "fast-switch": {
        "repo": "https://github.com/Parfnx/antigravity-fast-switch.git",
        "dir": "antigravity-fast-switch",
        "start": "// BEGIN LOCAL FAST SWITCH",
        "end": "// END LOCAL FAST SWITCH",
        "label": "Fast Switch (Account Switcher)",
    },
    "mcp-panel": {
        "repo": "https://github.com/Parfnx/antigravity-mcp-panel.git",
        "dir": "antigravity-mcp-panel",
        "start": "// BEGIN LOCAL MCP PANEL",
        "end": "// END LOCAL MCP PANEL",
        "label": "MCP Panel (Server Monitor & Toggle)",
    },
    "context-panel": {
        "repo": "https://github.com/Parfnx/antigravity-context-panel.git",
        "dir": "antigravity-context-panel",
        "start": "// BEGIN LOCAL CONTEXT PANEL",
        "end": "// END LOCAL CONTEXT PANEL",
        "label": "Context & Memory Panel (Memories, Rules, Skills)",
    },
}

ASCII_MARKER = "// BEGIN LOCAL ASCII WALLPAPERS"

FS_HOOK_TARGET = """        handle = await (0, languageServer_1.startAndMonitorLanguageServer)(targetPort, csrf, {
            headless: HEADLESS,"""
FS_HOOK_REPLACEMENT = """        const __fastSwitchLsOpts = {
            headless: HEADLESS,"""
FS_HOOK_END_TARGET = """                            }
                        }
                    }
                }
            },
        });"""
FS_HOOK_END_REPLACEMENT = """                            }
                        }
                    }
                }
            },
        };
        global.__fastSwitchStorage = () => storageManager;
        global.__fastSwitchRestartLs = async () => {
            await (0, languageServer_1.killLanguageServer)();
            handle = await (0, languageServer_1.startAndMonitorLanguageServer)(targetPort, csrf, __fastSwitchLsOpts);
        };
        handle = await (0, languageServer_1.startAndMonitorLanguageServer)(targetPort, csrf, __fastSwitchLsOpts);"""


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1048576), b""):
            h.update(chunk)
    return h.hexdigest()


def read_asar(path: str) -> tuple[bytes, int, dict[str, Any]]:
    with open(path, "rb") as f:
        raw = f.read()
    u = struct.unpack("<IIII", raw[:16])
    base = 8 + u[1]
    header = json.loads(raw[16 : 16 + u[3]].decode("utf-8"))
    return raw, base, header


def extract_file(raw: bytes, base: int, header: dict[str, Any], rel: str) -> str:
    node = header
    for part in rel.split("/"):
        node = node["files"][part]
    off = base + int(node["offset"])
    return raw[off : off + int(node["size"])].decode("utf-8")


def compute_integrity(data: bytes) -> dict[str, Any]:
    block_size = 4194304
    full_hash = hashlib.sha256(data).hexdigest()
    blocks = (
        [hashlib.sha256(data[i : i + block_size]).hexdigest() for i in range(0, len(data), block_size)]
        if data
        else [full_hash]
    )
    return {
        "algorithm": "SHA256",
        "hash": full_hash,
        "blockSize": block_size,
        "blocks": blocks,
    }


def repack_asar(raw: bytes, base: int, header: dict[str, Any], overrides: dict[str, bytes], out_path: str) -> None:
    blobs: list[bytes] = []
    offset = 0

    def walk_build(node: dict[str, Any], prefix: str = "") -> dict[str, Any]:
        nonlocal offset
        if "files" in node:
            return {
                "files": {
                    k: walk_build(v, f"{prefix}/{k}" if prefix else k)
                    for k, v in node["files"].items()
                }
            }
        if node.get("unpacked"):
            return dict(node)
        if prefix in overrides:
            content = overrides[prefix]
        else:
            old_off = base + int(node["offset"])
            content = raw[old_off : old_off + int(node["size"])]
        entry: dict[str, Any] = {
            "size": len(content),
            "offset": str(offset),
            "integrity": compute_integrity(content),
        }
        if node.get("executable"):
            entry["executable"] = True
        blobs.append(content)
        offset += len(content)
        return entry

    new_header = walk_build(header)
    header_bytes = json.dumps(new_header, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    json_len = len(header_bytes)
    pad = (4 - (json_len % 4)) % 4
    header_pickle_size = 8 + json_len + pad
    prefix = struct.pack("<IIII", 4, header_pickle_size, header_pickle_size - 4, json_len)
    padded_header = header_bytes + (b"\x00" * pad)

    tmp_path = out_path + ".tmp"
    with open(tmp_path, "wb") as f:
        f.write(prefix)
        f.write(padded_header)
        for b in blobs:
            f.write(b)
    os.replace(tmp_path, out_path)


def strip_block(text: str, start: str, end: str) -> str:
    return re.sub(r"\n?" + re.escape(start) + r"[\s\S]*?" + re.escape(end) + r"\n?", "\n", text).rstrip() + "\n"


def ensure_fast_switch_hook(main_text: str) -> str:
    if "__fastSwitchRestartLs" in main_text:
        return main_text
    if FS_HOOK_TARGET not in main_text:
        raise RuntimeError("Could not locate startAndMonitorLanguageServer start in dist/main.js")
    idx_start = main_text.index(FS_HOOK_TARGET)
    idx_end = main_text.find(FS_HOOK_END_TARGET, idx_start)
    if idx_end == -1 or idx_end - idx_start > 3500:
        raise RuntimeError("Could not locate startAndMonitorLanguageServer end in dist/main.js")
    return (
        main_text[:idx_start]
        + FS_HOOK_REPLACEMENT
        + main_text[idx_start + len(FS_HOOK_TARGET) : idx_end]
        + FS_HOOK_END_REPLACEMENT
        + main_text[idx_end + len(FS_HOOK_END_TARGET) :]
    )


def download_module_zip(repo_url: str, dest_dir: str) -> None:
    zip_url = repo_url.removesuffix(".git").rstrip("/") + "/archive/refs/heads/main.zip"
    req = urllib.request.Request(zip_url, headers={"User-Agent": "AntigravityModManager/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read()
    tmp_dir = dest_dir + ".tmp"
    if os.path.exists(tmp_dir):
        shutil.rmtree(tmp_dir)
    os.makedirs(tmp_dir, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        zf.extractall(tmp_dir)
    entries = [os.path.join(tmp_dir, e) for e in os.listdir(tmp_dir)]
    root_dir = entries[0] if len(entries) == 1 and os.path.isdir(entries[0]) else tmp_dir
    if os.path.exists(dest_dir):
        shutil.rmtree(dest_dir)
    shutil.move(root_dir, dest_dir)
    if os.path.exists(tmp_dir):
        shutil.rmtree(tmp_dir, ignore_errors=True)


def resolve_module_dir(mod_id: str, offline: bool = False) -> str:
    meta = MODULES[mod_id]
    sibling = os.path.join(SCRATCH_ROOT, meta["dir"])
    if os.path.isfile(os.path.join(sibling, "main_patch.js")) and os.path.isfile(os.path.join(sibling, "preload_patch.js")):
        return sibling

    os.makedirs(DEFAULT_MODS_CACHE, exist_ok=True)
    cached = os.path.join(DEFAULT_MODS_CACHE, meta["dir"])
    has_git = shutil.which("git") is not None
    has_files = os.path.isfile(os.path.join(cached, "main_patch.js")) and os.path.isfile(os.path.join(cached, "preload_patch.js"))

    if os.path.isdir(os.path.join(cached, ".git")) and has_git:
        if not offline:
            subprocess.run(["git", "-C", cached, "pull", "--ff-only"], check=False)
        return cached
    if has_files:
        if not offline:
            download_module_zip(meta["repo"], cached)
        return cached
    if offline:
        raise RuntimeError(f"Module '{mod_id}' not found locally and --offline is set")
    if has_git:
        subprocess.run(["git", "clone", "--depth", "1", meta["repo"], cached], check=True)
    else:
        download_module_zip(meta["repo"], cached)
    return cached


def verify_asar(asar_path: str, expected_mods: list[str], require_ascii: dict[str, bool]) -> None:
    raw, base, header = read_asar(asar_path)
    tmp_dir = os.path.dirname(asar_path)
    for rel in ("dist/main.js", "dist/preload.js"):
        node = header
        for part in rel.split("/"):
            node = node["files"][part]
        off = base + int(node["offset"])
        content = raw[off : off + int(node["size"])]
        if node["integrity"]["hash"] != hashlib.sha256(content).hexdigest():
            raise RuntimeError(f"SHA-256 integrity mismatch on {rel}")
        tmp_js = os.path.join(tmp_dir, f"_modmgr_verify_{os.path.basename(rel)}")
        try:
            with open(tmp_js, "wb") as f:
                f.write(content)
            subprocess.run(["node", "--check", tmp_js], check=True)
        finally:
            if os.path.exists(tmp_js):
                os.remove(tmp_js)
        text = content.decode("utf-8")
        if require_ascii.get(rel) and ASCII_MARKER not in text:
            raise RuntimeError(f"Lost ascii-wallpapers marker in {rel}")
        for m in expected_mods:
            if MODULES[m]["start"] not in text or MODULES[m]["end"] not in text:
                raise RuntimeError(f"Missing {m} markers in {rel}")


def detect_installed(asar_path: str) -> dict[str, Any]:
    raw, base, header = read_asar(asar_path)
    main_js = extract_file(raw, base, header, "dist/main.js")
    preload_js = extract_file(raw, base, header, "dist/preload.js")
    active = [
        mod_id
        for mod_id, meta in MODULES.items()
        if meta["start"] in main_js and meta["start"] in preload_js
    ]
    return {
        "asar": asar_path,
        "sha256": file_sha256(asar_path),
        "ascii_wallpapers": ASCII_MARKER in preload_js,
        "modules": active,
    }


def load_state() -> dict[str, Any]:
    if not os.path.isfile(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(mods: list[str], asar_hash: str) -> None:
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"modules": mods, "last_patched_sha256": asar_hash}, f, indent=2)


def apply_mods(asar_path: str, mods: list[str], stage: bool, offline: bool) -> str:
    for m in mods:
        if m not in MODULES:
            raise ValueError(f"Unknown module: {m}. Valid: {', '.join(MODULES)}")

    raw, base, header = read_asar(asar_path)
    orig_main = extract_file(raw, base, header, "dist/main.js")
    orig_preload = extract_file(raw, base, header, "dist/preload.js")

    require_ascii = {
        "dist/main.js": ASCII_MARKER in orig_main,
        "dist/preload.js": ASCII_MARKER in orig_preload,
    }

    new_main = orig_main
    new_preload = orig_preload
    for meta in MODULES.values():
        new_main = strip_block(new_main, meta["start"], meta["end"])
        new_preload = strip_block(new_preload, meta["start"], meta["end"])

    for m in mods:
        mod_dir = resolve_module_dir(m, offline=offline)
        with open(os.path.join(mod_dir, "main_patch.js"), "r", encoding="utf-8") as f:
            mp = f.read().strip()
        with open(os.path.join(mod_dir, "preload_patch.js"), "r", encoding="utf-8") as f:
            pp = f.read().strip()
        if m == "fast-switch":
            new_main = ensure_fast_switch_hook(new_main)
        new_main = new_main.rstrip() + "\n\n" + mp + "\n"
        new_preload = new_preload.rstrip() + "\n\n" + pp + "\n"

    out_path = os.path.join(os.path.dirname(asar_path), "app.asar.mod-manager.staged") if stage else asar_path
    repack_asar(
        raw,
        base,
        header,
        {"dist/main.js": new_main.encode("utf-8"), "dist/preload.js": new_preload.encode("utf-8")},
        out_path,
    )
    verify_asar(out_path, mods, require_ascii)
    save_state(mods, file_sha256(out_path))
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Unified Antigravity app.asar mod manager")
    parser.add_argument("action", choices=["status", "apply", "reapply", "remove"])
    parser.add_argument("--asar", default=DEFAULT_ASAR)
    parser.add_argument("--mods", default="", help="Comma-separated modules (fast-switch,mcp-panel,context-panel)")
    parser.add_argument("--stage", action="store_true", help="Write app.asar.mod-manager.staged instead of app.asar")
    parser.add_argument("--offline", action="store_true", help="Use cached/local modules without git pull/clone")
    args = parser.parse_args()

    if not os.path.isfile(args.asar):
        print(f"app.asar not found: {args.asar}", file=sys.stderr)
        return 1

    if args.action == "status":
        info = detect_installed(args.asar)
        saved = load_state()
        update_detected = bool(
            saved.get("last_patched_sha256") and saved["last_patched_sha256"] != info["sha256"]
        )
        print(json.dumps({**info, "saved_profile": saved.get("modules", []), "asar_changed": update_detected}, indent=2))
        return 0

    if args.action == "reapply":
        saved = load_state()
        mods = [m for m in saved.get("modules", []) if m in MODULES]
        if not mods:
            mods = list(MODULES.keys())
        out = apply_mods(args.asar, mods, stage=args.stage, offline=args.offline)
        print("OK:", out, "mods:", ",".join(mods))
        return 0

    if args.action == "remove":
        target_remove = {m.strip() for m in args.mods.split(",") if m.strip()}
        current = detect_installed(args.asar)["modules"]
        remaining = [m for m in current if m not in target_remove]
        out = apply_mods(args.asar, remaining, stage=args.stage, offline=args.offline)
        print("OK:", out, "remaining:", ",".join(remaining) or "none")
        return 0

    mods = [m.strip() for m in args.mods.split(",") if m.strip()]
    if not mods:
        mods = list(MODULES.keys())
    out = apply_mods(args.asar, mods, stage=args.stage, offline=args.offline)
    print("OK:", out, "mods:", ",".join(mods))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
