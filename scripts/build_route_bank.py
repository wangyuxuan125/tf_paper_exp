#!/usr/bin/env python3

import argparse
import csv
import os
import signal
import subprocess
import time
from pathlib import Path


ROUTE_ROOT = Path("/home/wyx/tf_route_bank")

PROFILE_FILE = Path(
    "/home/wyx/tf_paper_exp/manifests/environment_profiles.csv"
)

LAUNCH_FILE = Path(
    "/home/wyx/tf_paper_exp/scripts/paper_mockamap_benchmark.launch"
)

LOG_ROOT = Path(
    "/home/wyx/tf_paper_exp/logs/route_bank_generation"
)

START = (
    6.4372711181640625,
    23.116613388061523,
    0.5,
)

GOAL = (
    -4.582256317138672,
    -17.233434677124023,
    3.494147776291897,
)

MIN_ROUTE_POINTS = 3
MAX_ROUTE_POINTS = 64

def read_profiles():
    with PROFILE_FILE.open(newline="") as f:
        return list(csv.DictReader(f))


def read_route(path):
    points = []

    if not path.exists():
        return points

    with path.open() as f:
        for line in f:
            line = line.strip()

            if not line or line.startswith("#"):
                continue

            values = line.split()

            if len(values) != 3:
                return []

            points.append(
                tuple(map(float, values))
            )

    return points


def stop_process(proc):
    if proc.poll() is not None:
        return

    try:
        os.killpg(
            proc.pid,
            signal.SIGINT
        )
    except ProcessLookupError:
        return

    try:
        proc.wait(timeout=2.0)
        return
    except subprocess.TimeoutExpired:
        pass

    try:
        os.killpg(
            proc.pid,
            signal.SIGKILL
        )
    except ProcessLookupError:
        pass

    try:
        proc.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        pass


def launch_attempt(
    profile,
    case_id,
    map_seed,
    route_seed,
    route_file,
    timeout_s,
):
    log_dir = (
        LOG_ROOT /
        profile["difficulty"] /
        profile["environment_family"]
    )

    log_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    log_file = (
        log_dir /
        f"{case_id}.log"
    )

    route_file.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    if route_file.exists():
        route_file.unlink()

    command = [
        "roslaunch",
        str(LAUNCH_FILE),

        f"map_seed:={map_seed}",
        f"route_seed:={route_seed}",
        "rrt_timeout:=1.0",

        f"map_type:={profile['map_type']}",
        f"complexity:={profile['complexity']}",
        f"fill:={profile['fill']}",
        f"fractal:={profile['fractal']}",
        f"attenuation:={profile['attenuation']}",

        f"width_min:={profile['width_min']}",
        f"width_max:={profile['width_max']}",
        f"obstacle_number:={profile['obstacle_number']}",

        f"road_width:={profile['road_width']}",
        f"add_wall_x:={profile['add_wall_x']}",
        f"add_wall_y:={profile['add_wall_y']}",
        f"maze_type:={profile['maze_type']}",

        "fixed_start_goal_enabled:=true",

        f"fixed_start_x:={START[0]}",
        f"fixed_start_y:={START[1]}",
        f"fixed_start_z:={START[2]}",

        f"fixed_goal_x:={GOAL[0]}",
        f"fixed_goal_y:={GOAL[1]}",
        f"fixed_goal_z:={GOAL[2]}",

        "experiment_log_enabled:=false",
        "benchmark_enabled:=false",

        f"benchmark_case_id:={case_id}",
        (
            "benchmark_environment_family:="
            + profile["environment_family"]
        ),
        (
            "benchmark_difficulty:="
            + profile["difficulty"]
        ),

        "benchmark_route_replay_enabled:=false",
        "benchmark_route_save_enabled:=true",
        f"benchmark_route_save_file:={route_file}",
    ]

    with log_file.open("w") as log:
        proc = subprocess.Popen(
            command,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )

        deadline = (
            time.monotonic() +
            timeout_s
        )

        success = False

        while time.monotonic() < deadline:
            points = read_route(
                route_file
            )

            if len(points) >= 2:
                success = True
                break

            if proc.poll() is not None:
                break

            time.sleep(0.1)

        stop_process(proc)

    points = read_route(route_file)

    point_count = len(points)

    route_accepted = (
        success
        and point_count >= MIN_ROUTE_POINTS
        and point_count <= MAX_ROUTE_POINTS
    )

    if not route_accepted:
        if route_file.exists():
            route_file.unlink()

        return False, point_count

    return True, point_count
    
def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--target",
        type=int,
        default=12,
        help="valid routes required per family/difficulty cell",
    )

    parser.add_argument(
        "--max-attempts",
        type=int,
        default=100,
    )

    parser.add_argument(
        "--attempt-timeout",
        type=float,
        default=12.0,
    )

    parser.add_argument(
        "--family",
        default="",
    )

    parser.add_argument(
        "--difficulty",
        default="",
    )

    args = parser.parse_args()

    profiles = read_profiles()

    family_order = {
        "perlin3d": 1,
        "random_boxes": 2,
        "maze2d": 3,
    }

    difficulty_order = {
        "easy": 1,
        "medium": 2,
        "hard": 3,
    }

    for profile in profiles:
        family = (
            profile[
                "environment_family"
            ]
        )

        difficulty = (
            profile[
                "difficulty"
            ]
        )

        if (
            args.family
            and family != args.family
        ):
            continue

        if (
            args.difficulty
            and difficulty != args.difficulty
        ):
            continue

        route_dir = (
            ROUTE_ROOT /
            difficulty /
            family
        )

        route_dir.mkdir(
            parents=True,
            exist_ok=True
        )

        existing = []

        for path in sorted(
            route_dir.glob("*.route")
        ):
            if len(read_route(path)) >= 2:
                existing.append(path)

        valid_count = len(existing)

        print()
        print(
            f"{family}/{difficulty}: "
            f"existing={valid_count}, "
            f"target={args.target}"
        )

        family_id = family_order[family]
        difficulty_id = (
            difficulty_order[difficulty]
        )

        attempt = 1

        while (
            valid_count < args.target
            and attempt <= args.max_attempts
        ):
            seed_key = (
                family_id * 10000 +
                difficulty_id * 1000 +
                attempt
            )

            map_seed = (
                100000 +
                seed_key
            )

            route_seed = (
                200000 +
                seed_key
            )

            case_id = (
                f"{family}_{difficulty}"
                f"_m{map_seed}"
                f"_r{route_seed}"
            )

            route_file = (
                route_dir /
                f"{case_id}.route"
            )

            if (
                route_file.exists()
                and len(
                    read_route(route_file)
                ) >= 2
            ):
                valid_count += 1
                attempt += 1
                continue

            print(
                f"  attempt={attempt:03d} "
                f"map={map_seed} "
                f"route={route_seed}"
            )

            success, point_count = (
                launch_attempt(
                    profile,
                    case_id,
                    map_seed,
                    route_seed,
                    route_file,
                    args.attempt_timeout,
                )
            )

            if success:
                valid_count += 1

                print(
                    f"    ACCEPT "
                    f"points={point_count} "
                    f"count={valid_count}/"
                    f"{args.target}"
                )
            else:
                print("    reject")

            attempt += 1

        print(
            f"{family}/{difficulty}: "
            f"valid={valid_count}"
        )

        if valid_count < args.target:
            raise RuntimeError(
                f"Could not reach target for "
                f"{family}/{difficulty}: "
                f"{valid_count}/{args.target}"
            )


if __name__ == "__main__":
    main()
