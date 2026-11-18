import importlib.util
import os
import pathlib
import shutil

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "deploy" / "systemd" / "setup_systemd.py"

spec = importlib.util.spec_from_file_location("setup_systemd", SCRIPT)
setup_systemd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup_systemd)


def test_script_is_executable():
    assert os.access(SCRIPT, os.X_OK)


def test_generate_units_replaces_placeholders(tmp_path):
    out = setup_systemd.generate_units("collector", "/opt/gruenbeck", tmp_path / "out")
    service = (out / "gruenbeck-collector.service").read_text()
    assert "User=collector\n" in service
    assert "WorkingDirectory=/opt/gruenbeck\n" in service
    assert (
        "ExecStart=/opt/gruenbeck/.venv/bin/python3 /opt/gruenbeck/src/data-collector.py\n"
        in service
    )
    assert "{{" not in service
    assert service.endswith("\n")


def test_generate_units_copies_timer_unchanged(tmp_path):
    out = setup_systemd.generate_units("collector", "/opt/gruenbeck", tmp_path)
    timer = SCRIPT.with_name("gruenbeck-collector.timer").read_text()
    assert (out / "gruenbeck-collector.timer").read_text() == timer


def test_generate_units_default_output_is_new_temp_dir_outside_repo():
    out = setup_systemd.generate_units("collector", "/opt/gruenbeck")
    try:
        assert REPO_ROOT not in out.parents
        assert (out / "gruenbeck-collector.service").exists()
        assert (out / "gruenbeck-collector.timer").exists()
    finally:
        shutil.rmtree(out)


@pytest.mark.parametrize("install_path", ["/opt/my gruenbeck", "/opt/gruen%beck", ""])
def test_generate_units_rejects_invalid_install_path(tmp_path, install_path):
    with pytest.raises(ValueError, match="install path"):
        setup_systemd.generate_units("collector", install_path, tmp_path)
    assert not list(tmp_path.iterdir())


def test_generate_units_rejects_invalid_user(tmp_path):
    with pytest.raises(ValueError, match="user"):
        setup_systemd.generate_units("my user", "/opt/gruenbeck", tmp_path)


def test_generate_units_rejects_output_dir_inside_repo():
    with pytest.raises(ValueError, match="inside the repository"):
        setup_systemd.generate_units("collector", "/opt/gruenbeck", REPO_ROOT / "units")
    assert not (REPO_ROOT / "units").exists()


def test_main_prints_system_install_commands(tmp_path, capsys):
    out = tmp_path / "out"
    code = setup_systemd.main(
        ["--user", "collector", "--install-path", "/opt/gruenbeck", "--output-dir", str(out)]
    )
    printed = capsys.readouterr().out
    assert code == 0
    assert f"sudo install -m 644 -t /etc/systemd/system/ {out}/gruenbeck-collector.service" in printed
    assert "sudo systemctl daemon-reload" in printed
    assert "sudo systemctl enable --now gruenbeck-collector.timer" in printed
    assert "enable --now gruenbeck-collector.service" not in printed


def test_main_rejects_invalid_install_path(tmp_path, capsys):
    with pytest.raises(SystemExit) as exit_info:
        setup_systemd.main(["--install-path", "/opt/a b", "--output-dir", str(tmp_path)])
    assert exit_info.value.code == 2
    assert "install path" in capsys.readouterr().err
