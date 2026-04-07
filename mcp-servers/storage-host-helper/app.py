import logging
import os
import subprocess
import time
import shlex
import base64
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

app = FastAPI(title="storage-host-helper")

HOST_MOUNT_NS_PATH = str(os.environ.get("STORAGE_HOST_MOUNT_NS_PATH", "/proc/1/ns/mnt") or "").strip()
SUPPORTED_FILESYSTEMS = {"ext4", "xfs", "vfat", "btrfs"}


class DeviceRequest(BaseModel):
    device: str


class MountRequest(BaseModel):
    device: str
    mountpoint: str
    filesystem: str = ""
    options: str = ""
    create_mountpoint: bool = False
    persist: bool = False


class MkdirsRequest(BaseModel):
    paths: List[str]
    mode: str = "0750"
    owner: str = ""
    group: str = ""


class ListDirRequest(BaseModel):
    path: str


class PathExistsRequest(BaseModel):
    path: str


class WriteFileRequest(BaseModel):
    path: str
    content_b64: str
    mode: str = ""
    overwrite: bool = False
    owner: str = ""
    group: str = ""


class EnsureSymlinkRequest(BaseModel):
    target: str
    link_path: str
    replace: bool = True


class SystemctlUserRequest(BaseModel):
    user: str
    args: List[str]
    runtime_dir: str = ""
    check: bool = True


class InstallDebUrlRequest(BaseModel):
    url: str
    package_name: str = ""
    binary_path: str = ""
    allow_downgrade: bool = False


class AptInstallRequest(BaseModel):
    packages: List[str]
    update_cache: bool = True


class RemovePathsRequest(BaseModel):
    paths: List[str]
    missing_ok: bool = True


class FormatRequest(BaseModel):
    device: str
    filesystem: str
    label: str = ""


class PartitionItem(BaseModel):
    label: str = ""
    size_gib: Optional[float] = None   # None = consume remaining space
    filesystem: str = "ext4"


class PartitionRequest(BaseModel):
    device: str
    table_type: str = "gpt"            # gpt | mbr
    partitions: List[PartitionItem]
    dry_run: bool = True


def _require_device(device: str) -> str:
    dev = str(device or "").strip()
    if not dev.startswith("/dev/"):
        raise HTTPException(status_code=400, detail="device must be an absolute /dev path")
    return dev


def _require_mountpoint(mountpoint: str) -> str:
    target = str(mountpoint or "").strip()
    if not target.startswith("/"):
        raise HTTPException(status_code=400, detail="mountpoint must be an absolute path")
    return target


def _nsenter_prefix() -> List[str]:
    if not HOST_MOUNT_NS_PATH:
        raise HTTPException(status_code=500, detail="host mount namespace path not configured")
    return ["nsenter", f"--mount={HOST_MOUNT_NS_PATH}", "--"]


def _run_host_command(cmd: List[str], timeout: int) -> subprocess.CompletedProcess:
    full_cmd = _nsenter_prefix() + list(cmd)
    log.info("[storage-host-helper] exec: %s", " ".join(full_cmd))
    env = os.environ.copy()
    env["LC_ALL"] = "C"
    env["LANG"] = "C"
    return subprocess.run(full_cmd, capture_output=True, text=True, timeout=timeout, env=env)


def _run_host_shell(script: str, timeout: int) -> subprocess.CompletedProcess:
    # We rely on bash semantics such as `set -o pipefail` in helper scripts.
    return _run_host_command(["bash", "-lc", script], timeout=timeout)


def _blkid_value(device: str, field: str) -> str:
    try:
        result = _run_host_command(["blkid", "-o", "value", "-s", str(field or "").strip(), device], timeout=10)
    except Exception:
        return ""
    if result.returncode != 0:
        return ""
    return str(result.stdout or "").strip()


def _escape_fstab_field(value: str) -> str:
    return str(value or "").replace("\\", "\\\\").replace(" ", "\\040").replace("\t", "\\011")


def _resolve_mount_spec(device: str) -> str:
    uuid = _blkid_value(device, "UUID")
    if uuid:
        return f"UUID={uuid}"
    partuuid = _blkid_value(device, "PARTUUID")
    if partuuid:
        return f"PARTUUID={partuuid}"
    return device


def _resolve_mount_filesystem(device: str, requested: str) -> str:
    fs = str(requested or "").strip()
    if fs:
        return fs
    return _blkid_value(device, "TYPE")


def _persist_mount_entry(device: str, mountpoint: str, filesystem: str, options: str) -> None:
    spec = _escape_fstab_field(_resolve_mount_spec(device))
    mount_field = _escape_fstab_field(mountpoint)
    fs = _escape_fstab_field(_resolve_mount_filesystem(device, filesystem))
    if not fs:
        raise HTTPException(status_code=409, detail=f"filesystem for '{device}' could not be determined for persistent mount")
    opts = _escape_fstab_field(str(options or "").strip() or "defaults")

    script = "\n".join(
        [
            "set -euo pipefail",
            f"spec={shlex.quote(spec)}",
            f"mountpoint={shlex.quote(mount_field)}",
            f"fstype={shlex.quote(fs)}",
            f"opts={shlex.quote(opts)}",
            'tmp="$(mktemp)"',
            "touch /etc/fstab",
            "awk -v spec=\"$spec\" -v mountpoint=\"$mountpoint\" 'BEGIN{OFS=\"\\t\"} /^[[:space:]]*#/ {print; next} NF < 2 {print; next} $1==spec || $2==mountpoint {next} {print}' /etc/fstab > \"$tmp\"",
            "printf '%s\\t%s\\t%s\\t%s\\t0\\t2\\n' \"$spec\" \"$mountpoint\" \"$fstype\" \"$opts\" >> \"$tmp\"",
            "cat \"$tmp\" > /etc/fstab",
            "rm -f \"$tmp\"",
        ]
    )
    result = _run_host_shell(script, timeout=30)
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}")


def _parse_mode(raw_mode: str) -> int:
    text = str(raw_mode or "0750").strip() or "0750"
    try:
        mode = int(text, 8)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="mode must be an octal string like 0750") from exc
    if mode < 0 or mode > 0o777:
        raise HTTPException(status_code=400, detail="mode must be between 0000 and 0777")
    return mode


def _mount_targets(device: str) -> List[str]:
    result = _run_host_command(["findmnt", "-rn", "-S", device, "-o", "TARGET"], timeout=10)
    if result.returncode not in (0, 1):
        raise HTTPException(status_code=500, detail=result.stderr.strip() or f"exit {result.returncode}")
    return [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]


def _ensure_unmounted(device: str) -> List[str]:
    targets = _mount_targets(device)
    if not targets:
        return []

    result = _run_host_command(["umount", device], timeout=30)
    if result.returncode != 0:
        raise HTTPException(status_code=409, detail=result.stderr.strip() or f"exit {result.returncode}")

    remaining = _mount_targets(device)
    if remaining:
        lazy = _run_host_command(["umount", "-l", device], timeout=30)
        if lazy.returncode != 0:
            raise HTTPException(status_code=409, detail=lazy.stderr.strip() or f"exit {lazy.returncode}")
        remaining = _mount_targets(device)
        if remaining:
            raise HTTPException(status_code=409, detail=f"device still mounted at {remaining}")

    return targets


def _device_exists(device: str) -> bool:
    result = _run_host_command(["test", "-b", device], timeout=5)
    return result.returncode == 0


def _busy_partition_table_error(stderr: str) -> bool:
    text = str(stderr or "").strip().lower()
    return "unable to inform the kernel of the change" in text or "old partition(s) will remain in use" in text


def _mkfs_busy_error(stderr: str) -> bool:
    text = str(stderr or "").strip().lower()
    return "apparently in use by the system" in text or "device is busy" in text


def _device_busy_detail(device: str) -> str:
    details: List[str] = []
    try:
        mounts = _mount_targets(device)
        if mounts:
            details.append(f"mounted at {mounts}")
    except Exception:
        pass

    try:
        result = _run_host_command(["fuser", "-v", device], timeout=10)
        text = "\n".join(
            line.strip()
            for line in ((result.stdout or "") + "\n" + (result.stderr or "")).splitlines()
            if line.strip()
        )
        if text:
            details.append(f"fuser: {text}")
    except Exception:
        pass

    return " | ".join(details)


def _wait_for_device_idle(device: str, timeout_s: float = 15.0) -> str:
    deadline = time.time() + timeout_s
    last_detail = ""
    while time.time() < deadline:
        detail = _device_busy_detail(device)
        if not detail:
            return ""
        last_detail = detail
        try:
            _run_host_command(["udevadm", "settle"], timeout=15)
        except Exception:
            pass
        time.sleep(0.5)
    return last_detail or _device_busy_detail(device)


def _only_udev_worker_busy(detail: str) -> bool:
    text = str(detail or "").strip().lower()
    return bool(text) and "udev-worker" in text and "mounted at" not in text and "fuser:" in text


def _child_block_devices(device: str) -> List[str]:
    result = _run_host_command(["lsblk", "-rno", "NAME", device], timeout=10)
    if result.returncode != 0:
        return []
    children: List[str] = []
    for raw in (result.stdout or "").splitlines():
        name = raw.strip()
        if not name:
            continue
        child = f"/dev/{name}"
        if child != device:
            children.append(child)
    return children


def _prepare_disk_for_repartition(device: str) -> List[str]:
    children = _child_block_devices(device)
    for child in children:
        _ensure_unmounted(child)
        wipe = _run_host_command(["wipefs", "-a", "-f", child], timeout=20)
        if wipe.returncode != 0:
            raise HTTPException(status_code=409, detail=wipe.stderr.strip() or f"wipefs failed for {child}")

    wipe_disk = _run_host_command(["wipefs", "-a", "-f", device], timeout=20)
    if wipe_disk.returncode != 0:
        raise HTTPException(status_code=409, detail=wipe_disk.stderr.strip() or f"wipefs failed for {device}")

    _run_host_command(["partx", "-d", device], timeout=10)
    _run_host_command(["udevadm", "settle"], timeout=15)
    busy_detail = _wait_for_device_idle(device, timeout_s=10.0)
    if busy_detail:
        raise HTTPException(status_code=409, detail=f"device still busy before repartition: {busy_detail}")
    return children


def _reread_partition_table(device: str) -> bool:
    success = False
    commands = [
        ["blockdev", "--rereadpt", device],
        ["partprobe", device],
        ["partx", "-u", device],
    ]
    for cmd in commands:
        try:
            result = _run_host_command(cmd, timeout=15)
        except Exception:
            continue
        if result.returncode == 0:
            success = True
    try:
        _run_host_command(["udevadm", "settle"], timeout=15)
    except Exception:
        pass
    return success


def _wait_for_block_device(device: str, timeout_s: float = 10.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if _device_exists(device):
            return True
        time.sleep(0.2)
    return _device_exists(device)


def _partition_device(disk: str, index: int) -> str:
    """Return e.g. /dev/sdb1 or /dev/nvme0n1p1 depending on disk type."""
    if "nvme" in disk or "mmcblk" in disk:
        return f"{disk}p{index}"
    return f"{disk}{index}"


def _mkfs_command(filesystem: str, label: str, device: str) -> List[str]:
    fs = str(filesystem or "").strip().lower()
    if fs not in SUPPORTED_FILESYSTEMS:
        raise HTTPException(status_code=400, detail=f"unsupported filesystem '{filesystem}'")
    base = {
        "ext4": ["mkfs.ext4", "-F", "-E", "lazy_itable_init=1,lazy_journal_init=1"],
        "xfs": ["mkfs.xfs", "-f"],
        "vfat": ["mkfs.vfat"],
        "btrfs": ["mkfs.btrfs", "-f"],
    }[fs]
    if label:
        base += ["-L", label]
    base.append(device)
    return base


@app.get("/health")
def health():
    return {"ok": True, "service": "storage-host-helper"}


@app.post("/v1/mount-targets")
def mount_targets(req: DeviceRequest):
    device = _require_device(req.device)
    try:
        targets = _mount_targets(device)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, "device": device, "targets": targets}


@app.post("/v1/mkdirs")
def mkdirs(req: MkdirsRequest):
    raw_paths = list(req.paths or [])
    if not raw_paths:
        raise HTTPException(status_code=400, detail="at least one absolute path is required")

    paths = [_require_mountpoint(path) for path in raw_paths]
    mode = _parse_mode(req.mode)
    owner = str(req.owner or "").strip()
    group = str(req.group or "").strip()
    created = []

    for path in paths:
        try:
            quoted_path = shlex.quote(path)
            script = [f"mkdir -p -m {mode:04o} {quoted_path}"]
            if owner or group:
                subject = owner or ""
                if group:
                    subject = f"{subject}:{group}" if subject else f":{group}"
                script.append(f"chown {shlex.quote(subject)} {quoted_path}")
            result = _run_host_shell("\n".join(script), timeout=30)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=result.stderr.strip() or f"exit {result.returncode}")
        created.append(path)

    return {
        "ok": True,
        "paths": created,
        "mode": f"{mode:04o}",
        "owner": owner,
        "group": group,
    }


@app.post("/v1/listdir")
def listdir(req: ListDirRequest):
    path = _require_mountpoint(req.path)
    cmd = [
        "find",
        path,
        "-mindepth",
        "1",
        "-maxdepth",
        "1",
        "-type",
        "d",
        "-printf",
        "%p\n",
    ]
    try:
        result = _run_host_command(cmd, timeout=30)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if result.returncode not in (0, 1):
        raise HTTPException(status_code=500, detail=result.stderr.strip() or f"exit {result.returncode}")
    entries = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
    return {"ok": True, "path": path, "entries": entries}


@app.post("/v1/path-exists")
def path_exists(req: PathExistsRequest):
    path = _require_mountpoint(req.path)
    try:
        result = _run_host_command(["test", "-e", path], timeout=5)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, "path": path, "exists": result.returncode == 0}


@app.post("/v1/write-file")
def write_file(req: WriteFileRequest):
    path = _require_mountpoint(req.path)
    parent = os.path.dirname(path.rstrip("/")) or "/"
    mode_text = str(req.mode or "").strip()
    mode = _parse_mode(mode_text) if mode_text else None
    owner = str(req.owner or "").strip()
    group = str(req.group or "").strip()
    try:
        payload = base64.b64decode(str(req.content_b64 or "").encode("ascii"), validate=True)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="content_b64 must be valid base64") from exc

    if not req.overwrite:
        probe = _run_host_command(["test", "-e", path], timeout=5)
        if probe.returncode == 0:
            return {"ok": True, "path": path, "written": False, "exists": True}

    encoded = base64.b64encode(payload).decode("ascii")
    quoted_parent = shlex.quote(parent)
    quoted_path = shlex.quote(path)
    script = [f"mkdir -p {quoted_parent}"]
    if owner or group:
        parent_subject = owner or ""
        if group:
            parent_subject = f"{parent_subject}:{group}" if parent_subject else f":{group}"
        script.append(f"chown {shlex.quote(parent_subject)} {quoted_parent}")
    script.append(f"base64 -d > {quoted_path} <<'__TRION_B64__'\n{encoded}\n__TRION_B64__")
    if owner or group:
        subject = owner or ""
        if group:
            subject = f"{subject}:{group}" if subject else f":{group}"
        script.append(f"chown {shlex.quote(subject)} {quoted_path}")
    if mode is not None:
        script.append(f"chmod {mode:04o} {quoted_path}")
    try:
        result = _run_host_shell("\n".join(script), timeout=30)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=result.stderr.strip() or f"exit {result.returncode}")
    return {"ok": True, "path": path, "written": True, "mode": f"{mode:04o}" if mode is not None else ""}


@app.post("/v1/ensure-symlink")
def ensure_symlink(req: EnsureSymlinkRequest):
    target = _require_mountpoint(req.target)
    link_path = _require_mountpoint(req.link_path)
    parent = os.path.dirname(link_path.rstrip("/")) or "/"
    quoted_target = shlex.quote(target)
    quoted_link = shlex.quote(link_path)
    quoted_parent = shlex.quote(parent)
    script = [
        f"mkdir -p {quoted_parent}",
        f"if [ -L {quoted_link} ]; then",
        f"  current=$(readlink {quoted_link} || true)",
        f"  if [ \"$current\" = {quoted_target} ]; then exit 0; fi",
        "fi",
    ]
    if req.replace:
        script.extend([
            f"if [ -L {quoted_link} ]; then rm -f {quoted_link}; fi",
            f"if [ -e {quoted_link} ]; then echo 'link_path exists and is not a symlink' >&2; exit 1; fi",
        ])
    else:
        script.append(f"if [ -e {quoted_link} ]; then exit 0; fi")
    script.append(f"ln -s {quoted_target} {quoted_link}")
    try:
        result = _run_host_shell("\n".join(script), timeout=30)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=result.stderr.strip() or f"exit {result.returncode}")
    return {"ok": True, "target": target, "link_path": link_path}


@app.post("/v1/systemctl-user")
def systemctl_user(req: SystemctlUserRequest):
    user = str(req.user or "").strip()
    if not user:
        raise HTTPException(status_code=400, detail="user is required")
    args = [str(arg).strip() for arg in list(req.args or []) if str(arg).strip()]
    if not args:
        raise HTTPException(status_code=400, detail="args are required")
    runtime_dir = str(req.runtime_dir or "").strip() or f"/run/user/{os.getuid()}"
    cmd = [
        "runuser",
        "-u",
        user,
        "--",
        "env",
        f"XDG_RUNTIME_DIR={runtime_dir}",
        f"DBUS_SESSION_BUS_ADDRESS=unix:path={runtime_dir}/bus",
        "systemctl",
        "--user",
        *args,
    ]
    try:
        result = _run_host_command(cmd, timeout=30)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if req.check and result.returncode != 0:
        raise HTTPException(status_code=500, detail=result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}")
    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": (result.stdout or "").strip(),
        "stderr": (result.stderr or "").strip(),
    }


@app.post("/v1/install-deb-url")
def install_deb_url(req: InstallDebUrlRequest):
    url = str(req.url or "").strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        raise HTTPException(status_code=400, detail="url must be http or https")
    package_name = str(req.package_name or "").strip()
    binary_path = str(req.binary_path or "").strip()

    tmp_dir = f"/tmp/trion-host-helper-{int(time.time())}"
    deb_path = f"{tmp_dir}/package.deb"
    script = [
        "set -euo pipefail",
        f"mkdir -p {shlex.quote(tmp_dir)}",
        f"curl -LfsS {shlex.quote(url)} -o {shlex.quote(deb_path)}",
    ]
    if package_name and req.allow_downgrade:
        script.append(f"dpkg -i {shlex.quote(deb_path)} || apt-get install -f -y")
    else:
        script.append(f"apt-get update >/dev/null 2>&1 || true")
        script.append(f"apt-get install -y {shlex.quote(deb_path)}")
    script.append(f"rm -rf {shlex.quote(tmp_dir)}")

    try:
        result = _run_host_shell("\n".join(script), timeout=300)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}")

    exists = False
    if binary_path:
        probe = _run_host_command(["test", "-x", binary_path], timeout=5)
        exists = probe.returncode == 0
    return {
        "ok": True,
        "url": url,
        "package_name": package_name,
        "binary_path": binary_path,
        "binary_exists": exists,
    }


@app.post("/v1/apt-install")
def apt_install(req: AptInstallRequest):
    raw_packages = [str(pkg or "").strip() for pkg in list(req.packages or [])]
    packages = [pkg for pkg in raw_packages if pkg]
    if not packages:
        raise HTTPException(status_code=400, detail="at least one package is required")

    quoted_packages = " ".join(shlex.quote(pkg) for pkg in packages)
    status_checks = " ".join(
        f"dpkg-query -W -f='${{Status}}' {shlex.quote(pkg)} 2>/dev/null | grep -q 'install ok installed'"
        for pkg in packages
    )
    script = [
        "set -euo pipefail",
        "missing=''",
        f"for pkg in {quoted_packages}; do",
        "  if ! dpkg-query -W -f='${Status}' \"$pkg\" 2>/dev/null | grep -q 'install ok installed'; then",
        "    missing=\"$missing $pkg\"",
        "  fi",
        "done",
        "missing=$(printf '%s' \"$missing\" | xargs -r)",
        "if [ -n \"$missing\" ]; then",
    ]
    if req.update_cache:
        script.append("  apt-get update")
    script.extend(
        [
            "  DEBIAN_FRONTEND=noninteractive apt-get install -y $missing",
            "fi",
        ]
    )

    try:
        result = _run_host_shell("\n".join(script), timeout=300)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}")

    installed = []
    for pkg in packages:
        probe = _run_host_shell(
            f"dpkg-query -W -f='${{Status}}' {shlex.quote(pkg)} 2>/dev/null | grep -q 'install ok installed'",
            timeout=10,
        )
        if probe.returncode == 0:
            installed.append(pkg)

    return {
        "ok": True,
        "packages": packages,
        "installed": installed,
        "changed": len(installed) == len(packages),
    }


@app.post("/v1/remove-paths")
def remove_paths(req: RemovePathsRequest):
    raw_paths = [str(path or "").strip() for path in list(req.paths or [])]
    paths = [_require_mountpoint(path) for path in raw_paths if str(path or "").strip()]
    if not paths:
        raise HTTPException(status_code=400, detail="at least one absolute path is required")

    quoted_paths = " ".join(shlex.quote(path) for path in paths)
    script = [f"rm -f {quoted_paths}"]
    try:
        result = _run_host_shell("\n".join(script), timeout=30)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}")
    return {"ok": True, "paths": paths}


@app.post("/v1/mount")
def mount_device(req: MountRequest):
    device = _require_device(req.device)
    mountpoint = _require_mountpoint(req.mountpoint)
    if req.create_mountpoint:
        mkdir_result = _run_host_command(["mkdir", "-p", mountpoint], timeout=30)
        if mkdir_result.returncode != 0:
            raise HTTPException(status_code=500, detail=mkdir_result.stderr.strip() or mkdir_result.stdout.strip() or f"exit {mkdir_result.returncode}")
    cmd = ["mount"]
    if req.filesystem:
        cmd += ["-t", str(req.filesystem).strip()]
    if req.options:
        cmd += ["-o", str(req.options).strip()]
    cmd += [device, mountpoint]
    try:
        result = _run_host_command(cmd, timeout=30)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=result.stderr.strip() or f"exit {result.returncode}")
    if req.persist:
        _persist_mount_entry(device, mountpoint, str(req.filesystem or "").strip(), str(req.options or "").strip())
    return {"ok": True, "device": device, "mountpoint": mountpoint, "persisted": bool(req.persist)}


@app.post("/v1/unmount")
def unmount_device(req: DeviceRequest):
    device = _require_device(req.device)
    try:
        targets = _ensure_unmounted(device)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, "device": device, "unmounted_targets": targets}


@app.post("/v1/format")
def format_device(req: FormatRequest):
    device = _require_device(req.device)
    cmd = _mkfs_command(req.filesystem, str(req.label or "").strip(), device)
    try:
        unmounted_targets = _ensure_unmounted(device)
        busy_detail = _wait_for_device_idle(device, timeout_s=10.0)
        if busy_detail and not _only_udev_worker_busy(busy_detail):
            raise HTTPException(status_code=409, detail=f"device still busy before format: {busy_detail}")

        result = _run_host_command(cmd, timeout=120)
        if result.returncode != 0 and _mkfs_busy_error(result.stderr):
            _ensure_unmounted(device)
            retry_detail = _wait_for_device_idle(device, timeout_s=15.0)
            if retry_detail and not _only_udev_worker_busy(retry_detail):
                raise HTTPException(
                    status_code=409,
                    detail=f"mkfs failed: {result.stderr.strip() or f'exit {result.returncode}'} | busy detail: {retry_detail}",
                )
            try:
                _run_host_command(["udevadm", "settle"], timeout=15)
            except Exception:
                pass
            time.sleep(2.0)
            retry = _run_host_command(cmd, timeout=120)
            if retry.returncode == 0:
                result = retry
            else:
                result = retry
                final_detail = _device_busy_detail(device)
                if final_detail:
                    raise HTTPException(
                        status_code=409,
                        detail=f"mkfs failed: {result.stderr.strip() or f'exit {result.returncode}'} | busy detail: {final_detail}",
                    )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=result.stderr.strip() or f"exit {result.returncode}")
    return {
        "ok": True,
        "device": device,
        "filesystem": req.filesystem,
        "unmounted_targets": unmounted_targets,
    }


@app.post("/v1/create-partition")
def create_partition(req: PartitionRequest):
    device = _require_device(req.device)
    table_type = str(req.table_type or "gpt").strip().lower()
    if table_type == "mbr":
        parted_label = "msdos"
    elif table_type == "gpt":
        parted_label = "gpt"
    else:
        raise HTTPException(status_code=400, detail="table_type must be 'gpt' or 'mbr'")

    parts = req.partitions
    if not parts:
        raise HTTPException(status_code=400, detail="at least one partition required")

    rest_count = sum(1 for p in parts if p.size_gib is None)
    if rest_count > 1:
        raise HTTPException(status_code=400, detail="only one partition may use remaining space (size_gib=null)")

    # Build parted commands using MiB boundaries (locale-safe, no decimal parsing issues)
    parted_cmds: List[List[str]] = [
        ["parted", "-s", device, "mklabel", parted_label]
    ]
    cursor_mib = 1  # 1 MiB offset for partition alignment
    for i, part in enumerate(parts):
        part_label = str(part.label or f"part{i + 1}").strip()
        fs_hint = str(part.filesystem or "ext4").strip().lower()
        is_rest = part.size_gib is None
        if is_rest:
            start = f"{cursor_mib}MiB"
            end = "100%"
        else:
            size_mib = max(1, int(round(part.size_gib * 1024)))
            start = f"{cursor_mib}MiB"
            end = f"{cursor_mib + size_mib}MiB"
            cursor_mib += size_mib
        if parted_label == "msdos":
            parted_cmds.append(["parted", "-s", device, "mkpart", "primary", fs_hint, start, end])
        else:
            parted_cmds.append(["parted", "-s", device, "mkpart", part_label, fs_hint, start, end])

    # Build mkfs commands
    mkfs_cmds: List[List[str]] = []
    for i, part in enumerate(parts):
        fs = str(part.filesystem or "ext4").strip().lower()
        if fs in SUPPORTED_FILESYSTEMS:
            part_dev = _partition_device(device, i + 1)
            mkfs_cmds.append(_mkfs_command(fs, str(part.label or "").strip(), part_dev))

    if req.dry_run:
        preview = [" ".join(cmd) for cmd in parted_cmds + mkfs_cmds]
        return {"ok": True, "dry_run": True, "device": device, "preview": preview}

    # Execute parted commands
    executed: List[str] = []
    try:
        _prepare_disk_for_repartition(device)

        for cmd in parted_cmds:
            result = _run_host_command(cmd, timeout=30)
            executed.append(" ".join(cmd))
            if result.returncode == 0:
                continue
            if _busy_partition_table_error(result.stderr):
                detail = result.stderr.strip() or f"exit {result.returncode}"
                busy_detail = _device_busy_detail(device)
                if busy_detail and not _only_udev_worker_busy(busy_detail):
                    raise HTTPException(status_code=409, detail=f"parted failed: {detail} | busy detail: {busy_detail}")
                _reread_partition_table(device)
                time.sleep(2.0)
                continue
                raise HTTPException(
                    status_code=500,
                    detail=f"parted failed: {result.stderr.strip() or f'exit {result.returncode}'}",
                )

        # Let kernel re-read partition table
        time.sleep(1)
        reread_ok = _reread_partition_table(device)
        time.sleep(0.5)

        for cmd in mkfs_cmds:
            # Unmount partition before formatting (it may still be mounted from before)
            part_dev = cmd[-1]
            if not _wait_for_block_device(part_dev, timeout_s=10.0):
                detail = f"partition device {part_dev} did not appear after repartitioning"
                if not reread_ok:
                    detail += f" ({device} partition table reread did not confirm)"
                raise HTTPException(status_code=409, detail=detail)
            try:
                _ensure_unmounted(part_dev)
            except HTTPException:
                pass  # ignore unmount errors — mkfs will catch it if still busy
            busy_detail = _wait_for_device_idle(part_dev, timeout_s=10.0)
            if busy_detail and not _only_udev_worker_busy(busy_detail):
                raise HTTPException(status_code=409, detail=f"device still busy before format: {busy_detail}")
            result = _run_host_command(cmd, timeout=120)
            executed.append(" ".join(cmd))
            if result.returncode != 0:
                if _mkfs_busy_error(result.stderr):
                    retry_detail = _wait_for_device_idle(part_dev, timeout_s=15.0)
                    if retry_detail and not _only_udev_worker_busy(retry_detail):
                        raise HTTPException(
                            status_code=409,
                            detail=f"mkfs failed: {result.stderr.strip() or f'exit {result.returncode}'} | busy detail: {retry_detail}",
                        )
                    try:
                        _run_host_command(["udevadm", "settle"], timeout=15)
                    except Exception:
                        pass
                    time.sleep(2.0)
                    retry = _run_host_command(cmd, timeout=120)
                    if retry.returncode == 0:
                        continue
                    result = retry
                raise HTTPException(
                    status_code=500,
                    detail=f"mkfs failed: {result.stderr.strip() or f'exit {result.returncode}'}",
                )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {"ok": True, "dry_run": False, "device": device, "executed": executed}
