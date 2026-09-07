#!/usr/bin/env python3

import argparse
import csv
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path


GCOPTER_REPO = Path(
    "/home/wyx/ICRA2027/GCOPTER/src/GCOPTER"
)

EXP_REPO = Path(
    "/home/wyx/tf_paper_exp"
)

EXPECTED_GCOPTER_COMMIT = (
    "0ce1f03a09345c8598defc670d478f885ca773f5"
)

MIN_ROUTE_POINTS = 3
MAX_ROUTE_POINTS = 64

REQUIRED_FILES = (
    "benchmark_corridors_v3.csv",
    "benchmark_e2_v1.csv",
    "benchmark_runs_v2.csv",
)

REQUIRED_DIAGNOSTICS = (
    "TF_BENCHMARK_CORRIDORS_V3",
    "TF_CONTROLLED_E2_COMPARE",
    "TF_BENCHMARK_E2",
    "TF_BENCHMARK_RUN",
)


def git_output(repo, *args):
    return subprocess.check_output(
        [
            "git",
            "-C",
            str(repo),
            *args,
        ],
        text=True,
    ).strip()


def stop_process(proc):
    if proc.poll() is not None:
        return

    try:
        os.killpg(
            proc.pid,
            signal.SIGINT,
        )
    except ProcessLookupError:
        return

    try:
        proc.wait(timeout=3.0)
        return
    except subprocess.TimeoutExpired:
        pass

    try:
        os.killpg(
            proc.pid,
            signal.SIGKILL,
        )
    except ProcessLookupError:
        pass

    try:
        proc.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        pass


def result_files_ready(case_dir):
    for name in REQUIRED_FILES:
        path = case_dir / name

        if (
            not path.exists()
            or path.stat().st_size <= 0
        ):
            return False

    return True


def preflight():
    if not GCOPTER_REPO.exists():
        raise RuntimeError(
            f"GCOPTER repo not found: {GCOPTER_REPO}"
        )

    head = git_output(
        GCOPTER_REPO,
        "rev-parse",
        "HEAD",
    )

    if head != EXPECTED_GCOPTER_COMMIT:
        raise RuntimeError(
            "Wrong GCOPTER commit:\n"
            f"  expected: {EXPECTED_GCOPTER_COMMIT}\n"
            f"  actual:   {head}"
        )

    status = git_output(
        GCOPTER_REPO,
        "status",
        "--porcelain",
    )

    if status:
        raise RuntimeError(
            "GCOPTER working tree is not clean:\n"
            + status
        )

    return head


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "manifest",
    )

    parser.add_argument(
        "--output-root",
        default=(
            "/home/wyx/tf_paper_exp/"
            "results/e1e2_prod"
        ),
    )

    parser.add_argument(
        "--log-root",
        default=(
            "/home/wyx/tf_paper_exp/"
            "logs/e1e2_prod"
        ),
    )

    parser.add_argument(
        "--family",
        default="",
    )

    parser.add_argument(
        "--difficulty",
        default="",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=0,
    )

    parser.add_argument(
        "--case-timeout",
        type=float,
        default=60.0,
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
    )

    args = parser.parse_args()

    gcopter_head = preflight()

    try:
        experiment_head = git_output(
            EXP_REPO,
            "rev-parse",
            "HEAD",
        )
    except Exception:
        experiment_head = "unknown"

    manifest_path = Path(
        args.manifest
    ).resolve()

    if not manifest_path.exists():
        raise RuntimeError(
            f"Manifest not found: {manifest_path}"
        )

    output_root = Path(
        args.output_root
    ).resolve()

    log_root = Path(
        args.log_root
    ).resolve()

    output_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    log_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    with manifest_path.open(
        newline=""
    ) as f:
        rows = list(
            csv.DictReader(f)
        )

    selected = []

    for row in rows:
        if row.get("runnable") != "1":
            continue

        if (
            args.family
            and row["environment_family"]
            != args.family
        ):
            continue

        if (
            args.difficulty
            and row["difficulty"]
            != args.difficulty
        ):
            continue

        point_count = int(
            row["route_point_count"]
        )

        if not (
            MIN_ROUTE_POINTS
            <= point_count
            <= MAX_ROUTE_POINTS
        ):
            raise RuntimeError(
                "Runnable manifest row violates "
                "route QC: "
                f"{row['case_id']} "
                f"points={point_count}"
            )

        selected.append(row)

    if args.limit > 0:
        selected = selected[:args.limit]

    case_ids = [
        row["case_id"]
        for row in selected
    ]

    if len(case_ids) != len(set(case_ids)):
        raise RuntimeError(
            "Duplicate case_id in selected manifest"
        )

    print(
        "GCOPTER commit =",
        gcopter_head,
        flush=True,
    )

    print(
        "experiment commit =",
        experiment_head,
        flush=True,
    )

    print(
        "selected cases =",
        len(selected),
        flush=True,
    )

    if not selected:
        raise RuntimeError(
            "No runnable cases selected"
        )

    failures = []
    completed_count = 0
    skipped_count = 0

    for index, row in enumerate(
        selected,
        start=1,
    ):
        case_id = row["case_id"]

        case_dir = (
            output_root /
            case_id
        )

        raw_log = (
            log_root /
            f"{case_id}.log"
        )

        complete_marker = (
            case_dir /
            "RUN_COMPLETE"
        )

        if (
            complete_marker.exists()
            and not args.overwrite
        ):
            skipped_count += 1

            print(
                f"[{index}/{len(selected)}] "
                f"SKIP {case_id}",
                flush=True,
            )

            continue

        if case_dir.exists():
            if args.overwrite:
                shutil.rmtree(
                    case_dir
                )
            else:
                failures.append(
                    (
                        case_id,
                        "partial_result_directory_exists",
                    )
                )

                print(
                    f"[{index}/{len(selected)}] "
                    f"FAIL {case_id}: "
                    "partial result directory exists; "
                    "inspect it or use --overwrite",
                    flush=True,
                )

                continue

        if raw_log.exists():
            if args.overwrite:
                raw_log.unlink()
            else:
                failures.append(
                    (
                        case_id,
                        "partial_log_exists",
                    )
                )

                print(
                    f"[{index}/{len(selected)}] "
                    f"FAIL {case_id}: "
                    "partial log exists; "
                    "inspect it or use --overwrite",
                    flush=True,
                )

                continue

        route_file = Path(
            row["route_file"]
        )

        launch_file = Path(
            row["launch_file"]
        )

        if not route_file.exists():
            failures.append(
                (
                    case_id,
                    "missing_route_file",
                )
            )

            print(
                f"[{index}/{len(selected)}] "
                f"FAIL {case_id}: "
                f"missing route {route_file}",
                flush=True,
            )

            continue

        if not launch_file.exists():
            failures.append(
                (
                    case_id,
                    "missing_launch_file",
                )
            )

            print(
                f"[{index}/{len(selected)}] "
                f"FAIL {case_id}: "
                f"missing launch {launch_file}",
                flush=True,
            )

            continue

        case_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        command = [
            "roslaunch",
            str(launch_file),

            f"map_seed:={row['map_seed']}",
            f"route_seed:={row['route_seed']}",

            f"map_type:={row['map_type']}",
            f"complexity:={row['complexity']}",
            f"fill:={row['fill']}",
            f"fractal:={row['fractal']}",
            f"attenuation:={row['attenuation']}",

            f"width_min:={row['width_min']}",
            f"width_max:={row['width_max']}",
            (
                "obstacle_number:="
                + row["obstacle_number"]
            ),

            f"road_width:={row['road_width']}",
            f"add_wall_x:={row['add_wall_x']}",
            f"add_wall_y:={row['add_wall_y']}",
            f"maze_type:={row['maze_type']}",

            "fixed_start_goal_enabled:=true",

            f"fixed_start_x:={row['start_x']}",
            f"fixed_start_y:={row['start_y']}",
            f"fixed_start_z:={row['start_z']}",

            f"fixed_goal_x:={row['goal_x']}",
            f"fixed_goal_y:={row['goal_y']}",
            f"fixed_goal_z:={row['goal_z']}",

            "experiment_log_enabled:=true",
            (
                "experiment_log_directory:="
                + str(case_dir)
            ),
            (
                "experiment_tag:="
                "paper_e1e2_production"
            ),

            "benchmark_enabled:=true",
            f"benchmark_case_id:={case_id}",
            (
                "benchmark_environment_family:="
                + row["environment_family"]
            ),
            (
                "benchmark_difficulty:="
                + row["difficulty"]
            ),
            "benchmark_repeat_id:=0",
            "benchmark_method:=proposed",
            "benchmark_variant:=csgn_active_exact",

            "benchmark_route_replay_enabled:=true",
            (
                "benchmark_route_replay_file:="
                + str(route_file)
            ),

            "benchmark_route_save_enabled:=false",
        ]

        print(
            f"[{index}/{len(selected)}] "
            f"RUN {case_id} "
            f"segments={row['route_segment_count']}",
            flush=True,
        )

        process_returncode = None
        files_ready = False

        with raw_log.open("w") as log:
            proc = subprocess.Popen(
                command,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )

            deadline = (
                time.monotonic()
                + args.case_timeout
            )

            while (
                time.monotonic()
                < deadline
            ):
                if result_files_ready(
                    case_dir
                ):
                    files_ready = True
                    break

                if proc.poll() is not None:
                    break

                time.sleep(0.1)

            stop_process(proc)

            process_returncode = (
                proc.returncode
            )

        text = raw_log.read_text(
            errors="replace"
        )

        missing_files = [
            name
            for name in REQUIRED_FILES
            if (
                not (
                    case_dir /
                    name
                ).exists()
                or (
                    case_dir /
                    name
                ).stat().st_size <= 0
            )
        ]

        missing_diagnostics = [
            token
            for token in REQUIRED_DIAGNOSTICS
            if token not in text
        ]

        completed = (
            files_ready
            and not missing_files
            and not missing_diagnostics
        )

        if completed:
            marker = {
                "case_id": case_id,
                "gcopter_commit": gcopter_head,
                "experiment_commit": experiment_head,
                "route_file": str(route_file),
                "route_point_count": int(
                    row["route_point_count"]
                ),
                "route_segment_count": int(
                    row["route_segment_count"]
                ),
                "environment_family": (
                    row[
                        "environment_family"
                    ]
                ),
                "difficulty": row["difficulty"],
                "map_seed": int(
                    row["map_seed"]
                ),
                "route_seed": int(
                    row["route_seed"]
                ),
            }

            complete_marker.write_text(
                json.dumps(
                    marker,
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            )

            completed_count += 1

            print(
                f"  COMPLETE "
                f"returncode={process_returncode}",
                flush=True,
            )
        else:
            reason = (
                "missing_files="
                + ",".join(missing_files)
                + " missing_diagnostics="
                + ",".join(
                    missing_diagnostics
                )
            )

            failures.append(
                (
                    case_id,
                    reason,
                )
            )

            print(
                f"  FAIL "
                f"returncode={process_returncode} "
                f"{reason}",
                flush=True,
            )

        time.sleep(0.3)

    print()
    print(
        "completed =",
        completed_count,
    )
    print(
        "skipped =",
        skipped_count,
    )
    print(
        "failed =",
        len(failures),
    )

    if failures:
        print(
            "\nfailed cases:",
            file=sys.stderr,
        )

        for case_id, reason in failures:
            print(
                f"  {case_id}: {reason}",
                file=sys.stderr,
            )

        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )
        sys.exit(2)
