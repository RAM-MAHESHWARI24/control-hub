"""
Storage Partition Inspector & Atomic Hardlink Validator
Ensures single-mount ext4 hardlink compliance (0 Disk I/O).
"""

import os
import shutil
import time
from pathlib import Path
from typing import Dict, Any, List


def get_disk_partitions() -> List[Dict[str, Any]]:
    """
    Auto-detect disk mounts, total capacity, and available headroom.
    Reads /proc/mounts on Linux; falls back to standard roots on non-Linux.
    """
    partitions = []
    seen_mounts = set()

    # Priority candidate paths to always check
    candidates = ["/", "/mnt/hdd", "/mnt/hdd/data", "/mnt/storage", "/media", "/data"]

    # On Linux, inspect /proc/mounts for real physical mounts
    proc_mounts = Path("/proc/mounts")
    if proc_mounts.exists():
        try:
            with open(proc_mounts, "r") as f:
                for line in f:
                    parts = line.strip().split()
                    if len(parts) >= 3:
                        device, mount, fstype = parts[0], parts[1], parts[2]
                        # Filter out virtual filesystems (proc, sysfs, tmpfs, cgroup, overlay)
                        if device.startswith(("/dev/sd", "/dev/nvme", "/dev/vd", "/dev/mapper")):
                            if mount not in seen_mounts:
                                seen_mounts.add(mount)
                                candidates.append(mount)
        except Exception:
            pass

    # Windows dev fallback drive letters
    if os.name == "nt":
        for drive_letter in ["C:\\", "D:\\", "E:\\", "Z:\\"]:
            if os.path.exists(drive_letter):
                candidates.append(drive_letter)

    for path_str in candidates:
        p = Path(path_str)
        if p.exists() and path_str not in seen_mounts:
            try:
                usage = shutil.disk_usage(str(p))
                total_gb = round(usage.total / (1024 ** 3), 1)
                free_gb = round(usage.free / (1024 ** 3), 1)
                used_gb = round(usage.used / (1024 ** 3), 1)
                percent = round((usage.used / usage.total) * 100, 1) if usage.total > 0 else 0

                seen_mounts.add(path_str)
                partitions.append({
                    "mount_point": path_str,
                    "total_gb": total_gb,
                    "free_gb": free_gb,
                    "used_gb": used_gb,
                    "percent_used": percent,
                    "is_root": path_str in ["/", "C:\\"],
                    "recommended_for": "ssd_config" if path_str == "/" or total_gb < 300 else "hdd_media",
                })
            except Exception:
                continue

    # Sort partitions: non-root mounts first (usually HDDs/storage drives)
    partitions.sort(key=lambda x: (x["is_root"], -x["total_gb"]))
    return partitions


def verify_path_writable(target_path: str) -> Dict[str, Any]:
    """Test if a directory exists or can be created, and is writable"""
    p = Path(target_path)
    try:
        p.mkdir(parents=True, exist_ok=True)
        test_file = p / f".homelab_probe_{os.getpid()}_{int(time.time())}"
        test_file.write_text("ok")
        test_file.unlink()
        return {
            "writable": True,
            "path": str(p.resolve()),
            "exists": True,
            "error": None,
        }
    except Exception as e:
        return {
            "writable": False,
            "path": target_path,
            "exists": p.exists(),
            "error": str(e),
        }


def test_atomic_hardlink(base_path: str) -> Dict[str, Any]:
    """
    Executes an actual atomic hardlink test on the specified base path.
    Creates .hl_src, links to .hl_dst, validates inode match, and measures latency.
    """
    p = Path(base_path)
    src_file = None
    dst_file = None

    try:
        p.mkdir(parents=True, exist_ok=True)
        timestamp = int(time.time() * 1000)
        src_file = p / f".hl_src_probe_{timestamp}"
        dst_file = p / f".hl_dst_probe_{timestamp}"

        # Write small payload
        start_time = time.perf_counter()
        src_file.write_text("homelab_atomic_hardlink_verification")

        # Perform atomic link
        os.link(str(src_file), str(dst_file))
        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 3)

        # Inode verification
        stat_src = os.stat(str(src_file))
        stat_dst = os.stat(str(dst_file))

        is_same_inode = (stat_src.st_ino == stat_dst.st_ino)

        return {
            "supported": is_same_inode,
            "latency_ms": elapsed_ms,
            "inode": stat_src.st_ino,
            "nlink": stat_dst.st_nlink,
            "path": str(p.resolve()),
            "error": None if is_same_inode else "Inode mismatch between source and destination",
        }
    except Exception as e:
        err_msg = str(e)
        tip = "Hardlinks cannot cross separate filesystem mounts or work on FAT32/exFAT. Ensure both torrents and media live on the same ext4/xfs mount."
        return {
            "supported": False,
            "latency_ms": None,
            "inode": None,
            "path": base_path,
            "error": err_msg,
            "tip": tip,
        }
    finally:
        # Cleanup test files
        if dst_file and dst_file.exists():
            try:
                dst_file.unlink()
            except Exception:
                pass
        if src_file and src_file.exists():
            try:
                src_file.unlink()
            except Exception:
                pass


def create_homelab_directory_tree(
    data_dir: str,
    config_dir: str,
    memories_dir: str,
    puid: int = 1000,
    pgid: int = 1000
) -> Dict[str, Any]:
    """
    Creates the required directory tree across data, config, and photo mounts.
    Applies PUID:PGID ownership on Linux systems.
    """
    created_dirs = []
    errors = []

    subdirs = [
        # Data directories (Atomic hardlinks)
        Path(data_dir) / "torrents" / "movies",
        Path(data_dir) / "torrents" / "tv",
        Path(data_dir) / "media" / "movies",
        Path(data_dir) / "media" / "tv",
        # Config directories (SSD application state)
        Path(config_dir) / "jellyfin",
        Path(config_dir) / "seerr",
        Path(config_dir) / "prowlarr",
        Path(config_dir) / "radarr",
        Path(config_dir) / "sonarr",
        Path(config_dir) / "bazarr",
        Path(config_dir) / "qbittorrent",
        # Photo storage
        Path(memories_dir),
    ]

    for directory in subdirs:
        try:
            directory.mkdir(parents=True, exist_ok=True)
            created_dirs.append(str(directory))

            # Set POSIX ownership if running on Linux with sufficient privileges
            if hasattr(os, "chown") and os.name != "nt":
                try:
                    os.chown(str(directory), puid, pgid)
                except PermissionError:
                    pass
        except Exception as e:
            errors.append({"path": str(directory), "error": str(e)})

    return {
        "success": len(errors) == 0,
        "created_dirs": created_dirs,
        "errors": errors,
    }
