# Copyright (c) 2026 Shashikanth Dhanekula
# SPDX-License-Identifier: MIT
"""Tests for multi-OS host profile detection."""

from __future__ import annotations

from dgx_lab.host import (
    CheckResult,
    HostProfile,
    HostReport,
    check_arch,
    check_disk,
    check_host,
    detect_profile,
    profile_matches_requires,
)


def test_check_arch_on_this_machine():
    result = check_arch()
    assert result.name == "arch"
    assert result.ok is True
    assert "machine=" in result.detail


def test_detect_profile_records_memory_and_os():
    profile = detect_profile(probe_docker_gpu=False, preferred_disk_gb=0.0)
    assert isinstance(profile, HostProfile)
    assert profile.os
    assert profile.arch
    assert profile.cpu_count is None or profile.cpu_count >= 1
    # memory may be None on exotic hosts, but Linux VMs should populate it
    assert "HOST PROFILE: OK" in profile.summary()


def test_host_report_disk_warn_not_hard_fail():
    report = HostReport(
        checks=[
            CheckResult("arch", True, "ok"),
            CheckResult("nvidia_smi", True, "ok"),
            CheckResult("cuda", True, "ok"),
            CheckResult("docker", True, "ok"),
            CheckResult("docker_gpu", True, "ok"),
            CheckResult("disk_preferred", False, "only 100 GiB"),
        ]
    )
    assert report.ok is True
    assert report.hard_failures == []
    assert "WARN" in report.summary() or "HOST GATE: PASS" in report.summary()


def test_host_report_hard_fail():
    report = HostReport(
        checks=[
            CheckResult("arch", False, "x86_64"),
            CheckResult("disk_preferred", False, "low"),
        ]
    )
    assert report.ok is False
    assert any(c.name == "arch" for c in report.hard_failures)
    assert "HOST GATE: FAIL" in report.summary()


def test_check_disk_tmp(tmp_path):
    result = check_disk(tmp_path, preferred_gb=0.0001)
    assert result.name == "disk_preferred"
    assert result.ok is True


def test_check_host_skip_gpu_probe():
    report = check_host(probe_docker_gpu=False, preferred_disk_gb=0.001)
    assert report.ok is True
    assert report.profile is not None
    names = [c.name for c in report.checks]
    assert "arch" in names
    assert "docker_gpu" in names
    gpu = next(c for c in report.checks if c.name == "docker_gpu")
    assert gpu.ok is True
    assert "skipped" in gpu.detail


def test_profile_matches_requires_spark():
    profile = HostProfile(
        os="Linux",
        arch="x86_64",
        python="3.12.0",
        cpu_count=4,
        memory_bytes=8 * 1024**3,
        memory_gib=8.0,
        nvidia_smi=False,
        cuda_version=None,
        docker=True,
        docker_gpu=False,
        disk_free_gib=100.0,
        hostname="dev",
    )
    errors = profile_matches_requires(
        profile,
        {"arch": ["aarch64", "arm64"], "os": "Linux", "platform": "linux/arm64", "nvidia": True},
    )
    assert any("arch=" in e for e in errors)
    assert any("nvidia" in e for e in errors)

    sparkish = HostProfile(
        os="Linux",
        arch="aarch64",
        python="3.12.0",
        cpu_count=20,
        memory_bytes=128 * 1024**3,
        memory_gib=128.0,
        nvidia_smi=True,
        cuda_version="13.0",
        docker=True,
        docker_gpu=True,
        disk_free_gib=800.0,
        hostname="spark-1",
    )
    assert profile_matches_requires(
        sparkish,
        {"arch": ["aarch64", "arm64"], "os": "Linux", "platform": "linux/arm64", "nvidia": True},
    ) == []
