"""JY-264: scripts/joey_reattach.py, the household CLI for the library re-attach report (ssh + docker exec)."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("joey_reattach", ROOT / "scripts" / "joey_reattach.py")
jr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(jr)


def fake(rc=0, out="PASS  latest - run 3 report (auto) 2026-10-28T09:30:00+00:00\n      strong 2, weak 0\n"):
    calls = []

    def run(cmd, timeout=300.0):
        calls.append(cmd)
        return rc, out
    return run, calls


@pytest.mark.parametrize("argv, cmd", [
    (["report"], "docker exec joey-hub python -m hub.library_reattach --latest"),
    (["dry-run"], "docker exec joey-hub python -m hub.library_reattach --dry-run"),
    (["apply", "3"], "docker exec joey-hub python -m hub.library_reattach --apply-report 3"),
    (["undo", "4"], "docker exec joey-hub python -m hub.library_reattach --undo 4"),
])
def test_each_action_runs_one_docker_exec(argv, cmd, capsys):
    run, calls = fake()
    assert jr.main(argv, runner=run) == 0
    assert calls == [cmd]
    assert capsys.readouterr().out.startswith("PASS  latest - run 3")


def test_apply_and_undo_need_a_run_id(capsys):
    with pytest.raises(SystemExit):
        jr.main(["apply"], runner=fake()[0])


def test_only_the_hub_lines_are_printed_never_the_host_or_a_path(capsys, monkeypatch):
    monkeypatch.setenv("JOEY_NAS", "root@secret-nas.example")
    noise = ("Error response from daemon: /volume1/Docker/joey/data something\n"
             "PASS  dry run - nothing written\n      strong 1, weak 0\n")
    assert jr.main(["dry-run"], runner=fake(out=noise)[0]) == 0
    out = capsys.readouterr().out
    assert "/volume1" not in out and "secret-nas" not in out and "PASS  dry run" in out


def test_a_remote_failure_is_a_fail_line_and_exit_1(capsys):
    assert jr.main(["undo", "9"], runner=fake(rc=1, out="FAIL  undo - ValueError: not an applied run\n")[0]) == 1
    assert capsys.readouterr().out.startswith("FAIL  undo")
    assert jr.main(["report"], runner=fake(rc=125, out="")[0]) == 1
    assert "no answer from joey-hub" in capsys.readouterr().out


def test_an_unreachable_nas_names_no_host(capsys):
    def down(cmd, timeout=300.0):
        raise RuntimeError("ssh could not reach the NAS (is it on? 07:00-22:00)")
    assert jr.main(["report"], runner=down) == 1
    assert capsys.readouterr().out == "FAIL  report - ssh could not reach the NAS (is it on? 07:00-22:00)\n"
