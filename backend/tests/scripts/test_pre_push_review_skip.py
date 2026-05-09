"""Skip-path test: when no dispatch paths are provided, exit 0 with skip message."""

from __future__ import annotations

import pre_push_review


def test_main_exits_0_with_no_dispatch_paths(capsys, tmp_path) -> None:
    rc = pre_push_review.main(
        [
            "--dispatch-paths",
            "--branch",
            "test-branch",
            "--head-sha",
            "deadbeef",
            "--repo-root",
            str(tmp_path),
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0
    assert "no dispatch files in push range" in captured.out
