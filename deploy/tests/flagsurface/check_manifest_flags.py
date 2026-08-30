#!/usr/bin/env python3
# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2025 Open Computer Use Contributors
"""Assert every flag a compose manifest passes is one the built image defines.

A manifest that passes an undefined flag does not degrade: Go's flag package
exits, so the service never boots. The component repos can only check that a
flag exists in THEIR tree; this checks the artifact the stand actually runs,
which is the half that catches an image built from a different tree.

The oracle is exact rather than heuristic. Run the image with the flag and a
dummy value: an undefined flag answers `flag provided but not defined: -x`,
while a defined flag fails later (or not at all) for some other reason. A value
parse error is therefore still a pass -- the flag exists.

Usage:
  check_manifest_flags.py --compose <path> [--service NAME]... [--docker "CMD"]
  check_manifest_flags.py --self-test --image IMAGE [--docker "CMD"]

Exit 0 when every probed flag is defined, 1 on the first undefined flag, 2 on a
usage or environment error. Services whose entrypoint is not a Go stdlib-flag
binary are skipped BY NAME with the reason printed -- never silently.
"""

import argparse
import json
import re
import shlex
import subprocess
import sys

# Images whose entrypoint does not parse flags with Go's stdlib package. Each
# entry states why, so a future reader does not have to rediscover it.
NON_GO_FLAG_IMAGES = {
    "envoyproxy/envoy": "Envoy parses its own CLI; an unknown option is not the Go signature",
    "nginx": "nginx CLI, not Go flags",
    "minio/minio": "MinIO uses cobra subcommands",
    "postgres": "postgres CLI",
    "redis": "redis CLI",
}

UNDEFINED_RE = re.compile(r"flag provided but not defined:\s*(-{1,2}[A-Za-z0-9_.-]+)")


def run(argv, timeout=90):
    """Run argv with NO shell.

    Both callers reached for shlex.quote, which is the tell that a shell was
    in the loop at all: with shell=True the quoting is the only thing standing
    between an image name or a path and a second command. Passing a list hands
    the words to execve directly, so a value carrying a quote, a semicolon or a
    newline stays one argument by construction rather than by escaping.

    docker_cmd is split rather than concatenated because it is a command line,
    not a word -- deployments set it to "sudo docker".
    """
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


def load_compose(docker_cmd, compose_path):
    """Resolve the compose file through docker so extends/env are applied."""
    res = run(shlex.split(docker_cmd)
              + ["compose", "-f", compose_path, "config", "--format", "json"])
    if res.returncode != 0:
        # Fall back to a plain read: config resolution needs env the caller may
        # not have. Report it rather than pretending the manifest is empty.
        print(f"NOTE: `compose config` failed ({res.stderr.strip()[:160]}); "
              "falling back to the raw file", file=sys.stderr)
        import yaml  # only needed on the fallback path
        with open(compose_path) as fh:
            return yaml.safe_load(fh)
    return json.loads(res.stdout)


def flags_of(command):
    """Extract long-form flag NAMES from a compose command list or string."""
    if command is None:
        return []
    if isinstance(command, str):
        parts = shlex.split(command)
    else:
        parts = [str(p) for p in command]
    names = []
    for part in parts:
        if part.startswith("-") and len(part) > 1 and not part.startswith("--"):
            names.append(part.lstrip("-").split("=", 1)[0])
        elif part.startswith("--") and len(part) > 2:
            names.append(part.lstrip("-").split("=", 1)[0])
    return names


def probe(docker_cmd, image, flag):
    """True when the image DEFINES the flag."""
    cmd = shlex.split(docker_cmd) + [
        "run", "--rm", "--network", "none", image, f"-{flag}=probe",
    ]
    res = run(cmd)
    blob = res.stdout + res.stderr
    hit = UNDEFINED_RE.search(blob)
    if hit and hit.group(1).lstrip("-") == flag:
        return False, blob.strip()[:240]
    return True, blob.strip()[:240]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--compose")
    ap.add_argument("--service", action="append", default=[])
    ap.add_argument("--docker", default="docker",
                    help='docker command prefix, e.g. "limactl shell ocu-linux -- docker"')
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--image")
    args = ap.parse_args()

    if args.self_test:
        if not args.image:
            print("--self-test needs --image", file=sys.stderr)
            return 2
        bogus = "definitely-not-a-real-flag"
        defined, blob = probe(args.docker, args.image, bogus)
        if defined:
            print(f"SELF-TEST FAILED: the oracle did not fire on {bogus!r}. "
                  f"It cannot detect an undefined flag, so a green run proves nothing.\n{blob}")
            return 1
        print(f"self-test OK: the oracle fires on a bogus flag ({args.image})")
        return 0

    if not args.compose:
        print("--compose is required (or use --self-test)", file=sys.stderr)
        return 2

    doc = load_compose(args.docker, args.compose)
    services = doc.get("services") or {}
    checked = failed = skipped = 0

    for name, spec in sorted(services.items()):
        if args.service and name not in args.service:
            continue
        image = spec.get("image")
        if not image:
            print(f"SKIP {name}: no image key (build-only service)")
            skipped += 1
            continue
        reason = next((why for pref, why in NON_GO_FLAG_IMAGES.items() if image.startswith(pref)), None)
        if reason:
            print(f"SKIP {name} ({image}): {reason}")
            skipped += 1
            continue
        names = flags_of(spec.get("command"))
        if not names:
            print(f"SKIP {name}: manifest passes no flags")
            skipped += 1
            continue
        for flag in names:
            defined, blob = probe(args.docker, image, flag)
            checked += 1
            if defined:
                print(f"ok   {name}: -{flag}")
            else:
                failed += 1
                print(f"FAIL {name}: manifest passes -{flag}, which the image {image} "
                      f"does NOT define. Go's flag package exits on an undefined flag, "
                      f"so this deployment would not boot.\n     {blob}")

    print(f"\nflags probed: {checked}, undefined: {failed}, services skipped: {skipped}")
    if checked == 0:
        print("NOTHING WAS PROBED -- treat this as a failure, not a pass: a gate that "
              "checks nothing is indistinguishable from a gate that passes.")
        return 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
