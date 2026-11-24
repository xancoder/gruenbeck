import importlib.util
import os
import pathlib
import shutil

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "deploy" / "systemd" / "setup_systemd.py"

spec = importlib.util.spec_from_file_location("setup_systemd", SCRIPT)
assert spec is not None
assert spec.loader is not None
setup_systemd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup_systemd)


def test_script_is_executable() -> None:
    assert os.access(SCRIPT, os.X_OK)


def test_generate_units_replaces_placeholders(tmp_path: pathlib.Path) -> None:
    out = setup_systemd.generate_units("collector", "/opt/gruenbeck", tmp_path / "out")
    service = (out / "gruenbeck-collector.service").read_text()
    assert "User=collector\n" in service
    assert "WorkingDirectory=/opt/gruenbeck\n" in service
    assert "ExecStart=/opt/gruenbeck/.venv/bin/gruenbeck-collect\n" in service
    assert "{{" not in service
    assert service.endswith("\n")


def settings(service: str) -> dict[str, str]:
    """the `[Service]` settings of a unit as name and value (comments and sections skipped)"""
    pairs = (
        line.partition("=")
        for line in service.splitlines()
        if line and not line.startswith(("#", "["))
    )
    return {name: value for name, _, value in pairs}


def test_generated_service_is_limited_in_time_and_hardened(tmp_path: pathlib.Path) -> None:
    out = setup_systemd.generate_units("collector", "/opt/gruenbeck", tmp_path)
    service = settings((out / "gruenbeck-collector.service").read_text())

    assert service["TimeoutStartSec"] == "30min"
    for name in (
        "NoNewPrivileges",
        "PrivateTmp",
        "PrivateDevices",
        "ProtectKernelTunables",
        "ProtectKernelModules",
        "ProtectKernelLogs",
        "ProtectControlGroups",
        "ProtectClock",
        "ProtectHostname",
        "RestrictSUIDSGID",
        "RestrictRealtime",
        "RestrictNamespaces",
        "LockPersonality",
    ):
        assert service[name] == "true", name
    assert service["ProtectSystem"] == "strict"
    assert service["ProtectHome"] == "read-only"
    assert service["SystemCallArchitectures"] == "native"
    assert service["CapabilityBoundingSet"] == ""
    assert service["RestrictAddressFamilies"] == "AF_INET AF_INET6 AF_UNIX AF_NETLINK"


def test_generated_service_may_write_to_data_and_log_of_the_install_path(
    tmp_path: pathlib.Path,
) -> None:
    out = setup_systemd.generate_units("collector", "/opt/gruenbeck", tmp_path)

    service = (out / "gruenbeck-collector.service").read_text()
    assert "ReadWritePaths=/opt/gruenbeck/data /opt/gruenbeck/log\n" in service


def test_write_paths_replace_the_default_paths(tmp_path: pathlib.Path) -> None:
    out = setup_systemd.generate_units(
        "collector",
        "/opt/gruenbeck",
        tmp_path,
        write_paths=["/srv/water/data", pathlib.Path("/var/log/gruenbeck/../gruenbeck")],
    )

    service = (out / "gruenbeck-collector.service").read_text()
    # the paths are normalized: systemd refuses ".."
    assert "ReadWritePaths=/srv/water/data /var/log/gruenbeck\n" in service
    assert "/opt/gruenbeck/data" not in service
    assert "{{" not in service


def test_default_write_paths_follow_a_relative_install_path(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    assert setup_systemd.default_write_paths("gruenbeck") == [
        tmp_path / "gruenbeck" / "data",
        tmp_path / "gruenbeck" / "log",
    ]


def test_generate_units_copies_timer_unchanged(tmp_path: pathlib.Path) -> None:
    out = setup_systemd.generate_units("collector", "/opt/gruenbeck", tmp_path)
    timer = SCRIPT.with_name("gruenbeck-collector.timer").read_text()
    assert (out / "gruenbeck-collector.timer").read_text() == timer


def test_generate_units_default_output_is_new_temp_dir_outside_repo() -> None:
    out = setup_systemd.generate_units("collector", "/opt/gruenbeck")
    try:
        assert REPO_ROOT not in out.parents
        assert (out / "gruenbeck-collector.service").exists()
        assert (out / "gruenbeck-collector.timer").exists()
    finally:
        shutil.rmtree(out)


@pytest.mark.parametrize("install_path", ["/opt/my gruenbeck", "/opt/gruen%beck", ""])
def test_generate_units_rejects_invalid_install_path(
    tmp_path: pathlib.Path, install_path: str
) -> None:
    with pytest.raises(ValueError, match="install path"):
        setup_systemd.generate_units("collector", install_path, tmp_path)
    assert not list(tmp_path.iterdir())


def test_generate_units_rejects_invalid_user(tmp_path: pathlib.Path) -> None:
    with pytest.raises(ValueError, match="user"):
        setup_systemd.generate_units("my user", "/opt/gruenbeck", tmp_path)


@pytest.mark.parametrize("write_path", ["/srv/my data", "/srv/da%ta", ""])
def test_generate_units_rejects_invalid_write_path(tmp_path: pathlib.Path, write_path: str) -> None:
    with pytest.raises(ValueError, match="write path"):
        setup_systemd.generate_units(
            "collector", "/opt/gruenbeck", tmp_path, write_paths=["/srv/data", write_path]
        )
    assert not list(tmp_path.iterdir())


def test_generate_units_rejects_output_dir_inside_repo() -> None:
    with pytest.raises(ValueError, match="inside the repository"):
        setup_systemd.generate_units("collector", "/opt/gruenbeck", REPO_ROOT / "units")
    assert not (REPO_ROOT / "units").exists()


def test_main_prints_system_install_commands(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "out"
    code = setup_systemd.main(
        ["--user", "collector", "--install-path", "/opt/gruenbeck", "--output-dir", str(out)]
    )
    printed = capsys.readouterr().out
    assert code == 0
    assert (
        f"sudo install -m 644 -t /etc/systemd/system/ {out}/gruenbeck-collector.service" in printed
    )
    assert "sudo systemctl daemon-reload" in printed
    assert "sudo systemctl enable --now gruenbeck-collector.timer" in printed
    assert "enable --now gruenbeck-collector.service" not in printed


def test_main_rejects_invalid_install_path(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        setup_systemd.main(["--install-path", "/opt/a b", "--output-dir", str(tmp_path)])
    assert exit_info.value.code == 2
    assert "install path" in capsys.readouterr().err


def test_main_passes_the_repeated_write_paths_to_the_unit(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "out"
    code = setup_systemd.main(
        [
            "--install-path",
            "/opt/gruenbeck",
            "--output-dir",
            str(out),
            "--write-path",
            "/srv/water",
            "--write-path",
            "/opt/gruenbeck/log",
        ]
    )

    assert code == 0
    service = (out / "gruenbeck-collector.service").read_text()
    assert "ReadWritePaths=/srv/water /opt/gruenbeck/log\n" in service
    capsys.readouterr()


def test_main_rejects_invalid_write_path(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        setup_systemd.main(["--write-path", "/srv/a b", "--output-dir", str(tmp_path)])

    assert exit_info.value.code == 2
    assert "write path" in capsys.readouterr().err
    assert not list(tmp_path.iterdir())


def test_generated_service_has_no_credential_by_default(tmp_path: pathlib.Path) -> None:
    out = setup_systemd.generate_units("collector", "/opt/gruenbeck", tmp_path)

    service = (out / "gruenbeck-collector.service").read_text()
    assert "LoadCredential" not in service
    assert "{{" not in service
    # the line of the placeholder is gone, it leaves no empty line in the [Service] section
    assert "gruenbeck-collect\n# a run takes" in service


def test_smtp_password_file_becomes_the_credential_of_the_service(tmp_path: pathlib.Path) -> None:
    out = setup_systemd.generate_units(
        "collector",
        "/opt/gruenbeck",
        tmp_path,
        smtp_password_file="/etc/gruenbeck/smtp-password",
    )

    service = (out / "gruenbeck-collector.service").read_text()
    assert service.count("LoadCredential=") == 1
    assert "LoadCredential=smtp-password:/etc/gruenbeck/smtp-password\n" in service
    assert settings(service)["ExecStart"] == "/opt/gruenbeck/.venv/bin/gruenbeck-collect"
    assert "{{" not in service


def test_smtp_password_file_is_made_absolute_and_normalized(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    out = setup_systemd.generate_units(
        "collector",
        "/opt/gruenbeck",
        tmp_path / "out",
        smtp_password_file="secrets/../smtp-password",
    )

    service = (out / "gruenbeck-collector.service").read_text()
    assert f"LoadCredential=smtp-password:{tmp_path / 'smtp-password'}\n" in service


@pytest.mark.parametrize("password_file", ["/etc/my dir/smtp-password", "/etc/smtp%password", ""])
def test_generate_units_rejects_invalid_smtp_password_file(
    tmp_path: pathlib.Path, password_file: str
) -> None:
    with pytest.raises(ValueError, match="SMTP password file"):
        setup_systemd.generate_units(
            "collector", "/opt/gruenbeck", tmp_path, smtp_password_file=password_file
        )
    assert not list(tmp_path.iterdir())


def test_main_passes_the_smtp_password_file_to_the_unit(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "out"

    code = setup_systemd.main(
        [
            "--install-path",
            "/opt/gruenbeck",
            "--output-dir",
            str(out),
            "--smtp-password-file",
            "/etc/gruenbeck/smtp-password",
        ]
    )

    assert code == 0
    service = (out / "gruenbeck-collector.service").read_text()
    assert "LoadCredential=smtp-password:/etc/gruenbeck/smtp-password\n" in service
    capsys.readouterr()


def test_main_rejects_invalid_smtp_password_file(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        setup_systemd.main(["--smtp-password-file", "/etc/a b", "--output-dir", str(tmp_path)])

    assert exit_info.value.code == 2
    assert "SMTP password file" in capsys.readouterr().err
    assert not list(tmp_path.iterdir())
