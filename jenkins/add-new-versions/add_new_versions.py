#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11, <3.14"
# dependencies = ['GitPython==3.1.45']
# ///

"""
Check released Couchbase Server versions are covered by SUPPORTED_VERSIONS_LIST
in cb-non-package-installer.

If any versions are not covered, automatically updates the file and stages it
for commit. Use the go.sh wrapper script with --push to commit and push to
Gerrit.
"""

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional, Set, Tuple

import git


# Constants
MANIFEST_REPO_URL = "https://github.com/couchbase/manifest.git"
MANIFEST_SUBDIR = "released/couchbase-server"
INSTALLER_FILENAME = "cb-non-package-installer"
SUPPORTED_VERSIONS_PATTERN = r"SUPPORTED_VERSIONS_LIST\s*=\s*\[(.*?)\]"
VERSION_STRING_PATTERN = r"['\"]([^'\"]+)['\"]"
VERSION_FROM_FILENAME_PATTERN = r"^(\d+)\.(\d+)\.\d+"


def clone_manifest_repo() -> Path:
    """
    Clone the Couchbase manifest repository to a temporary directory.

    Returns:
        Path to the cloned repository root

    Raises:
        SystemExit: If cloning fails
    """
    print("Cloning manifest repository...")
    temp_dir = tempfile.mkdtemp(prefix="couchbase-manifest-")

    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", MANIFEST_REPO_URL, temp_dir],
            check=True,
            capture_output=True,
            text=True,
        )
        print("Clone complete.")
        print()
    except subprocess.CalledProcessError as e:
        print(f"Error cloning manifest repository: {e}", file=sys.stderr)
        if e.stderr:
            print(f"stderr: {e.stderr}", file=sys.stderr)
        shutil.rmtree(temp_dir, ignore_errors=True)
        sys.exit(1)

    return Path(temp_dir)


def get_installer_file_path() -> Path:
    """
    Get the path to the cb-non-package-installer file.

    Returns:
        Path to the installer file

    Raises:
        SystemExit: If the file cannot be found
    """
    script_dir = Path(__file__).parent
    # Go up to the repository root (two levels up from add-new-versions/)
    repo_root = script_dir.parent.parent
    installer_file = repo_root / INSTALLER_FILENAME

    if not installer_file.exists():
        print(f"Error: Could not find {INSTALLER_FILENAME} at {installer_file}", file=sys.stderr)
        sys.exit(1)

    return installer_file


def read_file_content(file_path: Path) -> str:
    """
    Read and return file content.

    Args:
        file_path: Path to file

    Returns:
        File content as string

    Raises:
        SystemExit: If file cannot be read
    """
    try:
        return file_path.read_text()
    except Exception as e:
        print(f"Error reading {file_path}: {e}", file=sys.stderr)
        sys.exit(1)


def extract_version_strings(content: str) -> Set[str]:
    """
    Extract version strings from SUPPORTED_VERSIONS_LIST in file content.

    Args:
        content: File content containing SUPPORTED_VERSIONS_LIST

    Returns:
        Set of version strings

    Raises:
        SystemExit: If SUPPORTED_VERSIONS_LIST cannot be found
    """
    match = re.search(SUPPORTED_VERSIONS_PATTERN, content, re.DOTALL)
    if not match:
        print(f"Error: Could not find SUPPORTED_VERSIONS_LIST in {INSTALLER_FILENAME}", file=sys.stderr)
        sys.exit(1)

    versions_str = match.group(1)
    return set(re.findall(VERSION_STRING_PATTERN, versions_str))


def parse_version(version_str: str) -> Tuple[int, int]:
    """
    Parse a version string in format 'MAJOR.MINOR.X' to (major, minor) tuple.

    Args:
        version_str: Version string like '6.0.X'

    Returns:
        Tuple of (major, minor)

    Raises:
        ValueError: If version string is invalid
    """
    parts = version_str.split('.')
    if len(parts) != 3 or parts[2] != 'X':
        raise ValueError(f"Invalid version format: {version_str} (expected X.Y.X)")

    return int(parts[0]), int(parts[1])


def sort_version_strings(version_strings: Set[str]) -> list[str]:
    """
    Sort version strings by their numeric major.minor values.

    Args:
        version_strings: Set of version strings

    Returns:
        Sorted list of version strings
    """
    def sort_key(v: str) -> Tuple[int, int]:
        try:
            return parse_version(v)
        except ValueError:
            # Invalid versions sort to the end
            return (999999, 999999)

    return sorted(version_strings, key=sort_key)


def get_supported_versions() -> Tuple[Set[str], str]:
    """
    Read SUPPORTED_VERSIONS_LIST from cb-non-package-installer.

    Returns:
        Tuple of (set of supported version strings, file content)
    """
    print(f"Reading supported versions from {INSTALLER_FILENAME}...")
    installer_file = get_installer_file_path()
    content = read_file_content(installer_file)
    versions = extract_version_strings(content)
    sorted_versions = sort_version_strings(versions)
    print(f"Found {len(versions)} supported versions: {sorted_versions}")
    print()
    return versions, content


def update_supported_versions_in_content(content: str, new_versions: Set[str]) -> str:
    """
    Update SUPPORTED_VERSIONS_LIST in file content with new versions.

    Args:
        content: Original file content
        new_versions: Set of new version strings to add

    Returns:
        Updated file content

    Raises:
        SystemExit: If SUPPORTED_VERSIONS_LIST cannot be found or updated
    """
    pattern = r"(SUPPORTED_VERSIONS_LIST\s*=\s*\[)(.*?)(\])"
    match = re.search(pattern, content, re.DOTALL)

    if not match:
        print(f"Error: Could not find SUPPORTED_VERSIONS_LIST in {INSTALLER_FILENAME}", file=sys.stderr)
        sys.exit(1)

    # Extract existing versions and combine with new ones
    existing_versions = extract_version_strings(content)
    all_versions = existing_versions | new_versions

    # Sort versions properly
    sorted_versions = sort_version_strings(all_versions)
    versions_list = ", ".join(f"'{v}'" for v in sorted_versions)

    # Replace the list in the content
    return content[:match.start(2)] + versions_list + content[match.end(2):]


def stage_file_for_commit(file_path: Path) -> None:
    """
    Stage a file for git commit.

    Args:
        file_path: Path to the file to stage

    Raises:
        SystemExit: If not in a git repository or staging fails
    """
    try:
        repo_root = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
            cwd=str(file_path.parent)
        ).stdout.strip()
    except subprocess.CalledProcessError:
        print("Error: Not in a git repository", file=sys.stderr)
        sys.exit(1)

    repo = git.Repo(repo_root)
    relative_path = file_path.relative_to(Path(repo_root))
    repo.git.add(str(relative_path))
    print(f"Staged {relative_path} for commit")


def extract_version_from_filename(filename: str) -> Optional[str]:
    """
    Extract version from manifest filename in format 'MAJOR.MINOR.X'.

    Examples:
        '6.0.0.xml' -> '6.0.X'
        '6.5.1-MP1.xml' -> '6.5.X'
        '7.0.0.xml' -> '7.0.X'
        'basestar-a1.xml' -> None (not a versioned manifest)

    Args:
        filename: Manifest filename

    Returns:
        Version string or None if not a versioned manifest
    """
    base = filename.removesuffix('.xml')
    match = re.match(VERSION_FROM_FILENAME_PATTERN, base)

    if not match:
        return None

    major, minor = match.groups()
    return f"{major}.{minor}.X"


def get_minimum_version(version_strings: Set[str]) -> Tuple[int, int]:
    """
    Get the minimum version from a set of version strings.

    Args:
        version_strings: Set of version strings in 'MAJOR.MINOR.X' format

    Returns:
        Tuple of (major, minor) for the minimum version

    Raises:
        ValueError: If versions set is empty or no valid versions found
    """
    if not version_strings:
        raise ValueError("Cannot determine minimum version from empty set")

    min_version = None
    for version_str in version_strings:
        try:
            version_tuple = parse_version(version_str)
            if min_version is None or version_tuple < min_version:
                min_version = version_tuple
        except ValueError:
            print(f"Warning: Skipping invalid version: {version_str}", file=sys.stderr)
            continue

    if min_version is None:
        raise ValueError("No valid versions found")

    return min_version


def scan_manifest_files(directory: Path, min_major: int, min_minor: int) -> Set[str]:
    """
    Scan directory for manifest files and extract versions >= minimum version.

    Args:
        directory: Directory to scan for manifest files
        min_major: Minimum major version number
        min_minor: Minimum minor version number

    Returns:
        Set of version strings in format 'MAJOR.MINOR.X'
    """
    min_version_str = f"{min_major}.{min_minor}.X"
    print(f"Scanning manifest files for versions >= {min_version_str}...")

    manifest_versions = set()

    for manifest_file in directory.glob("*.xml"):
        version_str = extract_version_from_filename(manifest_file.name)

        if version_str is None:
            continue

        try:
            major, minor = parse_version(version_str)
            if major > min_major or (major == min_major and minor >= min_minor):
                manifest_versions.add(version_str)
        except ValueError:
            # Skip if version parsing fails
            continue

    sorted_versions = sort_version_strings(manifest_versions)
    print(f"Found {len(manifest_versions)} manifest versions: {sorted_versions}")
    print()
    return manifest_versions


def main() -> None:
    repo_root = None
    try:
        repo_root = clone_manifest_repo()
        manifest_dir = repo_root / MANIFEST_SUBDIR

        if not manifest_dir.exists():
            print(f"Error: Directory {manifest_dir} does not exist", file=sys.stderr)
            sys.exit(1)

        supported_versions, installer_content = get_supported_versions()
        min_major, min_minor = get_minimum_version(supported_versions)
        min_supported_version = f"{min_major}.{min_minor}.X"

        manifest_versions = scan_manifest_files(manifest_dir, min_major, min_minor)

        missing_versions = manifest_versions - supported_versions

        if missing_versions:
            sorted_missing = sort_version_strings(missing_versions)
            print(f"Found {len(missing_versions)} released version(s) not supported:")
            for version in sorted_missing:
                print(f"  - {version}")
            print()

            installer_file = get_installer_file_path()
            print(f"Updating {installer_file.name}...")
            updated_content = update_supported_versions_in_content(installer_content, missing_versions)

            installer_file.write_text(updated_content)
            print(f"Updated {INSTALLER_FILENAME} with new versions: {sorted_missing}")
            print()

            stage_file_for_commit(installer_file)
            print()
            print("Changes staged.")
        else:
            print(f"All manifest versions >= {min_supported_version} are supported.")

    finally:
        if repo_root and repo_root.exists():
            shutil.rmtree(repo_root, ignore_errors=True)


if __name__ == "__main__":
    main()
