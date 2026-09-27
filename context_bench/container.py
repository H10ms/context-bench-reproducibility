"""Docker isolation helpers. Agent container: no network, no harness mount, no secrets."""
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class DockerInfo:
    available: bool
    version: str
    daemon_ok: bool
    detail: str


def docker_info() -> DockerInfo:
    exe = shutil.which("docker")
    if not exe:
        return DockerInfo(False, "", False, "docker executable not found")
    try:
        v = subprocess.run(["docker", "--version"], capture_output=True, text=True, timeout=15)
        version = (v.stdout or v.stderr).strip()
    except Exception as e:  # noqa: BLE001
        return DockerInfo(True, "", False, f"docker --version failed: {e}")
    try:
        d = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"],
                           capture_output=True, text=True, timeout=20)
        ok = d.returncode == 0
        detail = (d.stdout or d.stderr).strip()[:500] if not ok else f"server {d.stdout.strip()}"
        return DockerInfo(True, version, ok, detail)
    except Exception as e:  # noqa: BLE001
        return DockerInfo(True, version, False, f"docker info failed: {e}")


def agent_docker_args(image: str, workdir: str, name: str) -> list[str]:
    """Canonical isolation args. Single place to audit network/mount policy."""
    return [
        "docker", "run", "--rm",
        "--name", name,
        "--network", "none",          # 6. no network access
        "--workdir", workdir,
        "--env", "NO_PROXY=*",
        # NOTE: no -v mount of experiment root; only the task workdir is mounted
        # by the caller explicitly. No --env passthrough of API keys into the
        # agent container beyond what the OpenCode process itself needs.
        image,
    ]


def swebench_image_for_task(image_field: str | None, default: str = "swebench/swebench:latest") -> str:
    return image_field or default


def materialize_worktree(image: str, workdir: Path, base_commit: str) -> None:
    """Copy a clean task checkout from the official SWE-bench image."""
    if not re.fullmatch(r"[0-9a-fA-F]{7,40}", base_commit or ""):
        raise RuntimeError(f"invalid base_commit: {base_commit!r}")
    prep = (f"git -C /testbed checkout --force {base_commit} && "
            "git -C /testbed clean -fdx && "
            f"test \"$(git -C /testbed rev-parse HEAD)\" = \"{base_commit}\" && "
            "git -C /testbed config core.symlinks false && "
            "find /testbed -type l -delete && git -C /testbed checkout-index -a -f")
    created = subprocess.run(
        ["docker", "create", "--entrypoint", "/bin/bash", image, "-lc", prep],
        capture_output=True, text=True, timeout=900)
    if created.returncode != 0:
        raise RuntimeError(f"docker create failed: {(created.stderr or created.stdout)[-500:]}")
    container_id = created.stdout.strip()
    try:
        started = subprocess.run(["docker", "start", "-a", container_id],
                                 capture_output=True, text=True, timeout=300)
        if started.returncode != 0:
            raise RuntimeError(f"task checkout failed: {(started.stderr or started.stdout)[-500:]}")
        copied = subprocess.run(["docker", "cp", f"{container_id}:/testbed/.", str(workdir)],
                                capture_output=True, text=True, timeout=600)
        if copied.returncode != 0:
            raise RuntimeError(f"docker cp failed: {(copied.stderr or copied.stdout)[-500:]}")
    finally:
        subprocess.run(["docker", "rm", "-f", container_id], capture_output=True,
                       text=True, timeout=60)

    filemode = subprocess.run(["git", "-C", str(workdir), "config", "core.filemode", "false"],
                              capture_output=True, text=True, timeout=60)
    if filemode.returncode != 0:
        raise RuntimeError("failed to disable filemode checks for the Windows worktree")
    symlinks = subprocess.run(["git", "-C", str(workdir), "config", "core.symlinks", "false"],
                              capture_output=True, text=True, timeout=60)
    if symlinks.returncode != 0:
        raise RuntimeError("failed to disable symlink checks for the Windows worktree")
    longpaths = subprocess.run(["git", "-C", str(workdir), "config", "core.longpaths", "true"],
                               capture_output=True, text=True, timeout=60)
    if longpaths.returncode != 0:
        raise RuntimeError("failed to enable long path support for the Windows worktree")
    head = subprocess.run(["git", "-C", str(workdir), "rev-parse", "HEAD"],
                          capture_output=True, text=True, timeout=60)
    status = subprocess.run(["git", "-C", str(workdir), "status", "--porcelain"],
                            capture_output=True, text=True, timeout=60)
    if head.returncode != 0 or head.stdout.strip().lower() != base_commit.lower():
        raise RuntimeError("materialized worktree is not at the requested base_commit")
    if status.returncode != 0 or status.stdout.strip():
        raise RuntimeError("materialized worktree is not clean")
