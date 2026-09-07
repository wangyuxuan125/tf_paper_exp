#!/usr/bin/env python3

import argparse
import csv
import re
from pathlib import Path


PROFILE_FILE = Path(
    "/home/wyx/tf_paper_exp/manifests/environment_profiles.csv"
)

LAUNCH_FILE = Path(
    "/home/wyx/tf_paper_exp/scripts/paper_mockamap_benchmark.launch"
)

MIN_ROUTE_POINTS = 3
MAX_ROUTE_POINTS = 64

def load_profiles():
    with PROFILE_FILE.open(newline="") as f:
        rows = list(csv.DictReader(f))

    return {
        (
            row["environment_family"],
            row["difficulty"],
        ): row
        for row in rows
    }


def read_route(path):
    points = []

    with path.open() as f:
        for line in f:
            line = line.strip()

            if not line or line.startswith("#"):
                continue

            values = line.split()

            if len(values) != 3:
                raise RuntimeError(
                    f"{path}: invalid route row"
                )

            points.append(
                tuple(map(float, values))
            )

    if len(points) < 2:
        raise RuntimeError(
            f"{path}: fewer than 2 points"
        )

    return points


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--route-root",
        default="/home/wyx/tf_route_bank",
    )

    parser.add_argument(
        "--output",
        default="/home/wyx/tf_paper_exp/manifests/e1e2_all.csv",
    )

    args = parser.parse_args()

    root = Path(
        args.route_root
    ).resolve()

    output = Path(
        args.output
    ).resolve()

    profiles = load_profiles()

    pattern = re.compile(
        r"_m(?P<map_seed>-?\d+)"
        r"_r(?P<route_seed>-?\d+)"
    )

    rows = []

    for path in sorted(
        root.glob("*/*/*.route")
    ):
        rel = path.relative_to(root)

        difficulty = rel.parts[0]
        family = rel.parts[1]
        case_id = path.stem

        match = pattern.search(
            case_id
        )

        if match is None:
            raise RuntimeError(
                f"Cannot parse seeds: {path}"
            )

        points = read_route(path)

        key = (
            family,
            difficulty,
        )

        profile = profiles.get(key)

        route_qc_valid = (
            MIN_ROUTE_POINTS
            <= len(points)
            <= MAX_ROUTE_POINTS
        )

        runnable = (
            1
            if (
                profile is not None
                and route_qc_valid
            )
            else 0
        )

        row = {
            "case_id": case_id,
            "difficulty": difficulty,
            "environment_family": family,
            "map_seed": int(
                match.group("map_seed")
            ),
            "route_seed": int(
                match.group("route_seed")
            ),
            "route_file": str(path),
            "route_point_count": len(points),
            "route_segment_count": len(points) - 1,
            "route_qc_valid": int(route_qc_valid),
            "start_x": points[0][0],
            "start_y": points[0][1],
            "start_z": points[0][2],
            "goal_x": points[-1][0],
            "goal_y": points[-1][1],
            "goal_z": points[-1][2],
            "launch_file": str(
                LAUNCH_FILE
            ),
            "runnable": runnable,
        }

        profile_fields = [
            "map_type",
            "complexity",
            "fill",
            "fractal",
            "attenuation",
            "width_min",
            "width_max",
            "obstacle_number",
            "road_width",
            "add_wall_x",
            "add_wall_y",
            "maze_type",
        ]

        for field in profile_fields:
            row[field] = (
                profile[field]
                if profile is not None
                else ""
            )

        rows.append(row)

    output.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    fields = [
        "case_id",
        "difficulty",
        "environment_family",
        "map_seed",
        "route_seed",
        "route_file",
        "route_point_count",
        "route_segment_count",
        "route_qc_valid",
        "start_x",
        "start_y",
        "start_z",
        "goal_x",
        "goal_y",
        "goal_z",
        "launch_file",
        "runnable",
        "map_type",
        "complexity",
        "fill",
        "fractal",
        "attenuation",
        "width_min",
        "width_max",
        "obstacle_number",
        "road_width",
        "add_wall_x",
        "add_wall_y",
        "maze_type",
    ]

    with output.open(
        "w",
        newline=""
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fields,
        )

        writer.writeheader()
        writer.writerows(rows)

    runnable_rows = [
        row
        for row in rows
        if row["runnable"] == 1
    ]

    print("manifest =", output)
    print("cases =", len(rows))
    print(
        "runnable =",
        len(runnable_rows)
    )
    print(
        "unresolved =",
        len(rows) -
        len(runnable_rows)
    )


if __name__ == "__main__":
    main()
