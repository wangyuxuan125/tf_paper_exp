#!/usr/bin/env python3

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path


METHODS = {
    "proposed",
    "identity",
    "firi",
    "rils",
}


def read_csv(path):
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def unique(rows, key):
    return {
        row[key]
        for row in rows
    }


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--result-root",
        default="/home/wyx/tf_paper_exp/results/e1e2_prod"
    )

    parser.add_argument(
        "--summary",
        default="/home/wyx/tf_paper_exp/summaries/e1e2_acceptance.csv"
    )

    parser.add_argument(
        "--strict",
        action="store_true"
    )

    args = parser.parse_args()

    root = Path(args.result_root)

    summary_rows = []
    structural_failures = 0
    strict_failures = 0

    for case_dir in sorted(root.iterdir()):
        if not case_dir.is_dir():
            continue

        case_id = case_dir.name

        e1_path = (
            case_dir /
            "benchmark_corridors_v3.csv"
        )

        e2_path = (
            case_dir /
            "benchmark_e2_v1.csv"
        )

        run_path = (
            case_dir /
            "benchmark_runs_v2.csv"
        )

        errors = []

        if not e1_path.exists():
            errors.append("missing_e1")

        if not e2_path.exists():
            errors.append("missing_e2")

        if not run_path.exists():
            errors.append("missing_run")

        if errors:
            structural_failures += 1

            summary_rows.append({
                "case_id": case_id,
                "structural_valid": 0,
                "errors": ";".join(errors),
            })

            continue

        e1 = read_csv(e1_path)
        e2 = read_csv(e2_path)
        runs = read_csv(run_path)

        # -----------------------------
        # Structural E1 checks
        # -----------------------------
        if unique(e1, "schema_version") != {"3"}:
            errors.append("e1_schema")

        e1_methods = Counter(
            row["method"]
            for row in e1
        )

        if set(e1_methods) != METHODS:
            errors.append("e1_methods")

        method_counts = [
            e1_methods[m]
            for m in METHODS
        ]

        if (
            not method_counts
            or min(method_counts) <= 0
            or len(set(method_counts)) != 1
        ):
            errors.append("e1_method_counts")
            segment_count = 0
        else:
            segment_count = method_counts[0]

        expected_e1_rows = (
            4 * segment_count
        )

        if len(e1) != expected_e1_rows:
            errors.append(
                f"e1_rows={len(e1)}"
                f"_expected={expected_e1_rows}"
            )

        expected_overlap_rows = (
            4 *
            max(
                0,
                segment_count - 1
            )
        )

        actual_overlap_rows = sum(
            int(
                row[
                    "junction_overlap_valid"
                ]
            )
            for row in e1
        )

        if (
            actual_overlap_rows !=
            expected_overlap_rows
        ):
            errors.append(
                "e1_overlap_rows="
                f"{actual_overlap_rows}"
                "_expected="
                f"{expected_overlap_rows}"
            )

        # -----------------------------
        # Structural E2 checks
        # -----------------------------
        if len(e2) != 4:
            errors.append(
                f"e2_rows={len(e2)}"
            )

        if unique(e2, "schema_version") != {"1"}:
            errors.append("e2_schema")

        if unique(e2, "method") != METHODS:
            errors.append("e2_methods")

        # -----------------------------
        # Pairing / fingerprint checks
        # -----------------------------
        e1_fp = unique(
            e1,
            "route_fingerprint"
        )

        e2_fp = unique(
            e2,
            "route_fingerprint"
        )

        run_fp = unique(
            runs,
            "route_fingerprint"
        )

        if not (
            len(e1_fp) == 1
            and e1_fp == e2_fp
            and e1_fp == run_fp
        ):
            errors.append("fingerprint_mismatch")

        if unique(e1, "case_id") != {case_id}:
            errors.append("e1_case_id")

        if unique(e2, "case_id") != {case_id}:
            errors.append("e2_case_id")

        # -----------------------------
        # Experimental outcomes
        # Do NOT use baseline failures as structural errors.
        # -----------------------------
        e1_mapping = sum(
            int(row["geometry_mapping_valid"])
            for row in e1
        )

        e1_safe = sum(
            int(row["common_safe"])
            for row in e1
        )

        e2_setup = sum(
            int(row["setup_success"])
            for row in e2
        )

        e2_opt = sum(
            int(row["optimize_success"])
            for row in e2
        )

        e2_metrics = sum(
            int(row["trajectory_metrics_valid"])
            for row in e2
        )

        e2_exact = sum(
            int(row["soft_exact_contained"])
            for row in e2
        )

        proposed_runs = [
            row for row in runs
            if row["method"] == "proposed"
        ]

        proposed_final_exact = (
            len(proposed_runs) == 1
            and proposed_runs[0][
                "final_exact_contained"
            ] == "1"
        )

        structural_valid = (
            len(errors) == 0
        )

        if not structural_valid:
            structural_failures += 1

        strict_valid = (
            structural_valid
            and e1_mapping == expected_e1_rows
            and e1_safe == expected_e1_rows
            and e2_setup == 4
            and e2_opt == 4
            and e2_metrics == 4
            and proposed_final_exact
        )

        if args.strict and not strict_valid:
            strict_failures += 1

        summary_rows.append({
            "case_id": case_id,
            "structural_valid": int(
                structural_valid
            ),
            "strict_valid": int(
                strict_valid
            ),
            "e1_mapping_rows": e1_mapping,
            "e1_safe_rows": e1_safe,
            "e2_setup_success": e2_setup,
            "e2_opt_success": e2_opt,
            "e2_metrics_valid": e2_metrics,
            "e2_soft_exact_contained": e2_exact,
            "proposed_final_exact": int(
                proposed_final_exact
            ),
            "errors": ";".join(errors),
        })

    summary = Path(args.summary)

    summary.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    fields = [
        "case_id",
        "structural_valid",
        "strict_valid",
        "e1_mapping_rows",
        "e1_safe_rows",
        "e2_setup_success",
        "e2_opt_success",
        "e2_metrics_valid",
        "e2_soft_exact_contained",
        "proposed_final_exact",
        "errors",
    ]

    with summary.open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fields,
            extrasaction="ignore"
        )

        writer.writeheader()
        writer.writerows(summary_rows)

    print("cases =", len(summary_rows))
    print(
        "structural failures =",
        structural_failures
    )

    if args.strict:
        print(
            "strict failures =",
            strict_failures
        )

    print("summary =", summary)

    if structural_failures:
        sys.exit(1)

    if args.strict and strict_failures:
        sys.exit(2)


if __name__ == "__main__":
    main()
