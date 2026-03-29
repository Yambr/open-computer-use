#!/usr/bin/env python3
"""Safe data file preview — checks size, shows shape/head/describe without overflowing context."""
import argparse
import os
import sys

DISPLAY_COLS = 20  # Max columns to show in head/describe output


def preview(file_path, max_rows=10, max_cols=None):
    import pandas as pd

    size_bytes = os.path.getsize(file_path)
    size_mb = size_bytes / (1024 * 1024)
    ext = os.path.splitext(file_path)[1].lower()

    print(f"File: {os.path.basename(file_path)}")
    print(f"Size: {size_mb:.1f} MB ({size_bytes:,} bytes)")

    read_kwargs = {}
    if size_mb > 1:
        read_kwargs["nrows"] = 500
        print(f"⚠ Large file — reading first 500 rows only")

    if max_cols:
        read_kwargs["usecols"] = list(range(max_cols))

    if ext in (".csv", ".tsv"):
        sep = "\t" if ext == ".tsv" else ","
        df = pd.read_csv(file_path, sep=sep, **read_kwargs)
    elif ext in (".xlsx", ".xls", ".xlsm"):
        df = pd.read_excel(file_path, **read_kwargs)
    elif ext == ".json":
        df = pd.read_json(file_path)
        if size_mb > 1:
            df = df.head(500)
    else:
        print(f"Unsupported format: {ext}")
        sys.exit(1)

    total_cols = df.shape[1]
    print(f"Shape: {df.shape[0]} rows x {total_cols} columns")

    print(f"\n--- Column Types ---")
    print(df.dtypes.to_string())

    # Limit displayed columns to keep output manageable
    if total_cols > DISPLAY_COLS:
        display_df = df.iloc[:, :DISPLAY_COLS]
        hidden = total_cols - DISPLAY_COLS
        col_note = f"  (showing first {DISPLAY_COLS} of {total_cols} columns, {hidden} hidden)"
    else:
        display_df = df
        col_note = ""

    print(f"\n--- First {max_rows} Rows ---{col_note}")
    with pd.option_context("display.max_colwidth", 50, "display.width", 200):
        print(display_df.head(max_rows).to_string())

    print(f"\n--- Statistics ---{col_note}")
    with pd.option_context("display.max_colwidth", 50, "display.width", 200):
        print(display_df.describe(include="all").to_string())

    if total_cols > DISPLAY_COLS:
        print(f"\n⚠ {hidden} columns hidden. To see all: --cols {total_cols}")
        print(f"  Hidden columns: {', '.join(df.columns[DISPLAY_COLS:])}")

    if size_mb > 1:
        print(f"\n⚠ Only first 500 rows shown. Total file: {size_mb:.1f} MB")
        print(
            f"  Use pd.read_csv('{file_path}', nrows=N) or usecols=[...] for targeted analysis."
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Safe data file preview")
    parser.add_argument("file", help="Path to data file (csv, xlsx, tsv, json)")
    parser.add_argument(
        "--rows", type=int, default=10, help="Number of rows to show (default: 10)"
    )
    parser.add_argument(
        "--cols", type=int, help="Max number of columns to display (default: 20)"
    )
    args = parser.parse_args()

    if not os.path.exists(args.file):
        print(f"File not found: {args.file}")
        sys.exit(1)

    if args.cols:
        DISPLAY_COLS = args.cols

    preview(args.file, max_rows=args.rows, max_cols=args.cols)
