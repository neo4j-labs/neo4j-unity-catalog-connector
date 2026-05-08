#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# ///

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

METADATA_URL = "https://repo1.maven.org/maven2/org/neo4j/neo4j-jdbc-bom/maven-metadata.xml"
BUILD_COMMAND = ["./mvnw", "-q", "clean", "verify", "-Drevision=0.0.0-SNAPSHOT"]
PUSH_COMMAND = ["git", "push"]
POM = Path("pom.xml")
VERSION_RE = re.compile(r"(<neo4j-jdbc\.version>)([^<]+)(</neo4j-jdbc\.version>)")
VALID_VERSION_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._-]*$")


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def pom_has_changes() -> bool:
    unstaged = subprocess.run(
        ["git", "diff", "--quiet", "--", str(POM)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    staged = subprocess.run(
        ["git", "diff", "--cached", "--quiet", "--", str(POM)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return unstaged.returncode != 0 or staged.returncode != 0


def prompt_yes_no(question: str, *, require_tty: bool = False) -> bool:
    if not sys.stdin.isatty():
        if not require_tty:
            print(f"{question} Skipping because this is not an interactive terminal.")
            return False
        raise RuntimeError(f"{question} Run from an interactive terminal to choose.")

    answer = input(f"{question} [y/N] ").strip().lower()
    return answer in {"y", "yes"}


def latest_release() -> str:
    with urllib.request.urlopen(METADATA_URL, timeout=30) as response:
        root = ET.fromstring(response.read())

    release = root.findtext("./versioning/release")
    latest = root.findtext("./versioning/latest")
    version = release or latest
    if not version:
        raise RuntimeError("No release/latest version found in Maven metadata")

    return version


def validate_version(version: str) -> str:
    if not VALID_VERSION_RE.fullmatch(version):
        raise RuntimeError(f"Invalid Neo4j JDBC version: {version!r}")

    return version


def current_version() -> str:
    text = POM.read_text(encoding="utf-8")
    matches = list(VERSION_RE.finditer(text))
    if len(matches) != 1:
        raise RuntimeError(f"Expected exactly one neo4j-jdbc.version property, found {len(matches)}")

    return matches[0].group(2)


def update_pom(version: str) -> tuple[str, bool]:
    text = POM.read_text(encoding="utf-8")
    matches = list(VERSION_RE.finditer(text))
    if len(matches) != 1:
        raise RuntimeError(f"Expected exactly one neo4j-jdbc.version property, found {len(matches)}")

    current = matches[0].group(2)
    if current == version:
        return current, False

    updated = VERSION_RE.sub(rf"\g<1>{version}\g<3>", text, count=1)
    POM.write_text(updated, encoding="utf-8")
    return current, True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync the Neo4j JDBC BOM version in pom.xml and run the Maven build."
    )
    parser.add_argument(
        "--version",
        help="Use an explicit Neo4j JDBC version instead of Maven Central latest release.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report the current and target versions without changes.",
    )
    parser.add_argument("--skip-build", action="store_true", help="Update pom.xml without running the Maven build.")
    parser.add_argument(
        "--build-arg",
        action="append",
        default=[],
        help="Additional argument to pass to ./mvnw. May be used more than once.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not POM.exists():
        raise RuntimeError("pom.xml not found; run from the repository root")

    target = validate_version(args.version or latest_release())
    current = current_version()

    if args.dry_run:
        print(f"current={current}")
        print(f"target={target}")
        return 0

    had_local_pom_changes = pom_has_changes()
    if had_local_pom_changes and not prompt_yes_no(
        "pom.xml has local changes. Continue and update neo4j-jdbc.version in that file?",
        require_tty=True,
    ):
        print("Aborted; pom.xml was not changed.")
        return 1

    old, changed = update_pom(target)
    if changed:
        print(f"neo4j-jdbc.version: {old} -> {target}", flush=True)
    else:
        print(f"neo4j-jdbc.version already {target}", flush=True)

    if not args.skip_build:
        run([*BUILD_COMMAND, *args.build_arg])

    if pom_has_changes():
        if had_local_pom_changes:
            commit_question = (
                "pom.xml had pre-existing local changes. "
                f"Commit all current pom.xml changes with message 'Sync Neo4j JDBC to {target}' and push?"
            )
        else:
            commit_question = f"Commit pom.xml with message 'Sync Neo4j JDBC to {target}' and push?"

        if prompt_yes_no(commit_question):
            run(["git", "add", str(POM)])
            run(["git", "commit", "-m", f"Sync Neo4j JDBC to {target}"])
            run(PUSH_COMMAND)

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
