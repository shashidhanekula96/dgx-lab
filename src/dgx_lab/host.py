# Copyright (c) 2026 Shashikanth Dhanekula
# SPDX-License-Identifier: MIT
"""Host profile detection — OS, arch, CPU, memory, optional NVIDIA/Docker."""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


@dataclass
class HostProfile:
    """Detected machine capabilities (never hard-fails on arch alone)."""

    os: str
    arch: str
    python: str
    cpu_count: int | None
    memory_bytes: int | None
    memory_gib: float | None
    nvidia_smi: bool
    cuda_version: str | None
    docker: bool
    docker_gpu: bool | None
    disk_free_gib: float | None
    hostname: str
    checks: list[CheckResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        # Keep checks as plain dicts for JSON
        return payload

    def summary(self) -> str:
        mem = f"{self.memory_gib:.1f} GiB" if self.memory_gib is not None else "unknown"
        lines = [
            f"os={self.os} arch={self.arch} hostname={self.hostname}",
            f"python={self.python} cpu_count={self.cpu_count} memory={mem}",
            f"nvidia_smi={self.nvidia_smi} cuda={self.cuda_version or 'n/a'}",
            f"docker={self.docker} docker_gpu={self.docker_gpu}",
        ]
        if self.disk_free_gib is not None:
            lines.append(f"disk_free_gib={self.disk_free_gib:.1f}")
        for c in self.checks:
            mark = "PASS" if c.ok else "INFO"
            lines.append(f"[{mark}] {c.name}: {c.detail}")
        lines.append("HOST PROFILE: OK (CLI-ready on this machine)")
        return "\n".join(lines)


@dataclass
class HostReport:
    """Compatibility wrapper used by scripts and tests."""

    profile: HostProfile | None = None
    checks: list[CheckResult] = field(default_factory=list)
    preferred_disk_gb: float = 0.0

    @property
    def ok(self) -> bool:
        # A detected profile means the CLI can run on this machine.
        # Optional GPU/Docker absences are informational, not hard failures.
        if self.profile is not None:
            return True
        return all(c.ok for c in self.checks if c.name != "disk_preferred")

    @property
    def hard_failures(self) -> list[CheckResult]:
        if self.profile is not None:
            return []
        return [c for c in self.checks if not c.ok and c.name != "disk_preferred"]

    def summary(self) -> str:
        if self.profile is not None:
            return self.profile.summary()
        lines = []
        for c in self.checks:
            mark = "PASS" if c.ok else ("WARN" if c.name == "disk_preferred" else "FAIL")
            lines.append(f"[{mark}] {c.name}: {c.detail}")
        if self.ok:
            lines.append("HOST GATE: PASS")
        else:
            fails = ", ".join(c.name for c in self.hard_failures)
            lines.append(f"HOST GATE: FAIL ({fails})")
        return "\n".join(lines)


def _run(cmd: list[str], timeout: float = 30.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def probe_memory_bytes() -> int | None:
    """Best-effort physical RAM probe across Linux / macOS / Windows."""
    system = platform.system()
    try:
        if system == "Linux":
            # Prefer /proc/meminfo
            meminfo = Path("/proc/meminfo")
            if meminfo.exists():
                for line in meminfo.read_text(encoding="utf-8").splitlines():
                    if line.startswith("MemTotal:"):
                        kb = int(line.split()[1])
                        return kb * 1024
            page_size = os.sysconf("SC_PAGE_SIZE")
            pages = os.sysconf("SC_PHYS_PAGES")
            return int(page_size) * int(pages)
        if system == "Darwin":
            proc = _run(["sysctl", "-n", "hw.memsize"])
            if proc.returncode == 0 and proc.stdout.strip().isdigit():
                return int(proc.stdout.strip())
        if system == "Windows":
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                return int(stat.ullTotalPhys)
    except Exception:  # noqa: BLE001 — probe is best-effort
        return None
    return None


def check_arch() -> CheckResult:
    machine = platform.machine().lower() or "unknown"
    return CheckResult("arch", True, f"machine={machine}")


def check_nvidia_smi() -> CheckResult:
    if shutil.which("nvidia-smi") is None:
        return CheckResult("nvidia_smi", False, "nvidia-smi not found on PATH (optional)")
    proc = _run(["nvidia-smi"])
    if proc.returncode != 0:
        return CheckResult(
            "nvidia_smi",
            False,
            f"nvidia-smi failed (rc={proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}",
        )
    name_proc = _run(["nvidia-smi", "-L"])
    detail = name_proc.stdout.strip() or "nvidia-smi ok"
    return CheckResult("nvidia_smi", True, detail.replace("\n", "; "))


def check_cuda() -> CheckResult:
    if shutil.which("nvidia-smi") is None:
        return CheckResult("cuda", False, "nvidia-smi missing; CUDA unknown (optional)")
    proc = _run(["nvidia-smi"])
    match = re.search(r"CUDA Version:\s*(\d+)\.(\d+)", proc.stdout)
    if not match:
        return CheckResult("cuda", False, "could not parse CUDA Version from nvidia-smi")
    major, minor = int(match.group(1)), int(match.group(2))
    return CheckResult("cuda", True, f"CUDA {major}.{minor}")


def check_cuda_major(required_major: int = 13) -> CheckResult:
    """Legacy helper: report whether CUDA major matches ``required_major``."""
    base = check_cuda()
    if not base.ok:
        return CheckResult("cuda", False, base.detail)
    match = re.search(r"CUDA (\d+)\.(\d+)", base.detail)
    if not match:
        return CheckResult("cuda", False, base.detail)
    major = int(match.group(1))
    ok = major == required_major
    return CheckResult(
        "cuda",
        ok,
        f"{base.detail} (require major {required_major})" if not ok else base.detail,
    )


def check_docker() -> CheckResult:
    if shutil.which("docker") is None:
        return CheckResult("docker", False, "docker not found on PATH (optional)")
    proc = _run(["docker", "info"])
    if proc.returncode != 0:
        return CheckResult(
            "docker",
            False,
            f"docker info failed (rc={proc.returncode}): {(proc.stderr or proc.stdout)[:200]}",
        )
    return CheckResult("docker", True, "docker daemon reachable")


def check_docker_gpu() -> CheckResult:
    """Verify Docker can see an NVIDIA GPU (CDI or --gpus). Optional capability."""
    if shutil.which("docker") is None:
        return CheckResult("docker_gpu", False, "docker not found")
    info = _run(["docker", "info"])
    blob = (info.stdout + info.stderr).lower()
    hints = ("nvidia.com/gpu", "nvidia", "cdi")
    has_hint = any(h in blob for h in hints)

    probe = _run(
        [
            "docker",
            "run",
            "--rm",
            "--gpus",
            "all",
            "nvidia/cuda:13.0.0-base-ubuntu24.04",
            "nvidia-smi",
            "-L",
        ],
        timeout=120.0,
    )
    if probe.returncode == 0 and "GPU" in probe.stdout:
        return CheckResult("docker_gpu", True, probe.stdout.strip().replace("\n", "; "))

    probe2 = _run(
        [
            "docker",
            "run",
            "--rm",
            "--device",
            "nvidia.com/gpu=all",
            "nvidia/cuda:13.0.0-base-ubuntu24.04",
            "nvidia-smi",
            "-L",
        ],
        timeout=120.0,
    )
    if probe2.returncode == 0 and "GPU" in probe2.stdout:
        return CheckResult(
            "docker_gpu",
            True,
            f"CDI ok: {probe2.stdout.strip().replace(chr(10), '; ')}",
        )

    err = (probe.stderr or probe.stdout or probe2.stderr or "")[:300]
    if has_hint:
        return CheckResult(
            "docker_gpu",
            False,
            f"nvidia hints in docker info but GPU probe failed: {err}",
        )
    return CheckResult("docker_gpu", False, f"no Docker GPU access: {err}")


def check_disk(path: Path | None = None, preferred_gb: float = 0.0) -> CheckResult:
    target = path or Path.home()
    usage = shutil.disk_usage(target)
    free_gb = usage.free / (1024**3)
    if preferred_gb <= 0:
        return CheckResult(
            "disk_preferred",
            True,
            f"{free_gb:.1f} GiB free on {target}",
        )
    ok = free_gb >= preferred_gb
    return CheckResult(
        "disk_preferred",
        ok,
        f"{free_gb:.1f} GiB free on {target} (preferred >= {preferred_gb:.0f} GiB)",
    )


def detect_profile(
    *,
    probe_docker_gpu: bool = False,
    preferred_disk_gb: float = 0.0,
    disk_path: Path | None = None,
) -> HostProfile:
    """Detect the local host. Never rejects a machine for arch alone."""
    mem = probe_memory_bytes()
    checks: list[CheckResult] = []
    arch = check_arch()
    checks.append(arch)
    nvidia = check_nvidia_smi()
    checks.append(nvidia)
    cuda = check_cuda()
    checks.append(cuda)
    docker = check_docker()
    checks.append(docker)
    docker_gpu: CheckResult
    if probe_docker_gpu:
        docker_gpu = check_docker_gpu()
    else:
        docker_gpu = CheckResult("docker_gpu", True, "skipped (probe_docker_gpu=False)")
    checks.append(docker_gpu)
    disk = check_disk(disk_path, preferred_disk_gb)
    checks.append(disk)

    cuda_version = None
    if cuda.ok:
        match = re.search(r"CUDA (\d+\.\d+)", cuda.detail)
        if match:
            cuda_version = match.group(1)

    return HostProfile(
        os=platform.system() or "unknown",
        arch=(platform.machine() or "unknown").lower(),
        python=platform.python_version(),
        cpu_count=os.cpu_count(),
        memory_bytes=mem,
        memory_gib=(mem / (1024**3)) if mem is not None else None,
        nvidia_smi=nvidia.ok,
        cuda_version=cuda_version,
        docker=docker.ok,
        docker_gpu=None if "skipped" in docker_gpu.detail else docker_gpu.ok,
        disk_free_gib=None,
        hostname=platform.node() or "unknown",
        checks=checks,
    )


def profile_matches_requires(profile: HostProfile, requires: dict[str, Any] | None) -> list[str]:
    """Return human-readable mismatch messages for a candidate ``requires`` block."""
    if not requires:
        return []
    errors: list[str] = []
    want_arch = requires.get("arch")
    if want_arch:
        allowed = {a.lower() for a in (want_arch if isinstance(want_arch, list) else [want_arch])}
        # Treat arm64 / aarch64 as aliases
        if "arm64" in allowed:
            allowed.add("aarch64")
        if "aarch64" in allowed:
            allowed.add("arm64")
        if profile.arch not in allowed:
            errors.append(f"arch={profile.arch} (require {sorted(allowed)})")

    want_os = requires.get("os")
    if want_os:
        allowed_os = {o.lower() for o in (want_os if isinstance(want_os, list) else [want_os])}
        if profile.os.lower() not in allowed_os:
            errors.append(f"os={profile.os} (require {sorted(allowed_os)})")

    want_platform = requires.get("platform")
    if want_platform:
        # platform like linux/arm64
        got = f"{profile.os.lower()}/{profile.arch}"
        if profile.arch in {"arm64", "aarch64"}:
            alts = {got, f"{profile.os.lower()}/arm64", f"{profile.os.lower()}/aarch64"}
        else:
            alts = {got}
        expected = (
            {want_platform.lower()}
            if isinstance(want_platform, str)
            else {p.lower() for p in want_platform}
        )
        if not (alts & expected):
            errors.append(f"platform={got} (require {sorted(expected)})")

    if requires.get("nvidia") and not profile.nvidia_smi:
        errors.append("nvidia_smi required but unavailable")

    if requires.get("docker") and not profile.docker:
        errors.append("docker required but unavailable")

    if requires.get("docker_gpu") and not profile.docker_gpu:
        errors.append("docker_gpu required but unavailable")

    min_cuda = requires.get("cuda_major_min")
    if min_cuda is not None and profile.cuda_version:
        major = int(profile.cuda_version.split(".", 1)[0])
        if major < int(min_cuda):
            errors.append(f"cuda={profile.cuda_version} (require major >= {min_cuda})")
    elif min_cuda is not None and not profile.cuda_version:
        errors.append(f"cuda_major_min={min_cuda} but CUDA not detected")

    return errors


def check_host(
    *,
    probe_docker_gpu: bool = False,
    preferred_disk_gb: float = 0.0,
    disk_path: Path | None = None,
) -> HostReport:
    """Detect host profile. Always returns ``ok=True`` for CLI-ready machines."""
    profile = detect_profile(
        probe_docker_gpu=probe_docker_gpu,
        preferred_disk_gb=preferred_disk_gb,
        disk_path=disk_path,
    )
    # Fill disk_free_gib from check
    for c in profile.checks:
        if c.name == "disk_preferred":
            match = re.search(r"([\d.]+) GiB free", c.detail)
            if match:
                profile.disk_free_gib = float(match.group(1))
    report = HostReport(
        profile=profile,
        checks=list(profile.checks),
        preferred_disk_gb=preferred_disk_gb,
    )
    return report
