"""The version must be the same everywhere, and the changelog must describe it."""
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
DOCROOT = os.path.join(ROOT, "..")          # guides live beside the application folder
sys.path.insert(0, os.path.join(ROOT, "updater"))
sys.path.insert(0, os.path.join(ROOT, "display"))
import display  # noqa: E402
import updater  # noqa: E402

SEMVER = r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?"


def version_file():
    return open(os.path.join(ROOT, "VERSION")).read().strip()


def test_version_is_semver():
    assert re.fullmatch(SEMVER, version_file()), version_file()


def test_code_matches_version_file():
    v = version_file()
    assert updater.__version__ == v, f"updater.py says {updater.__version__}, VERSION says {v}"
    assert display.__version__ == v, f"display.py says {display.__version__}, VERSION says {v}"


def test_changelog_matches_version():
    text = open(os.path.join(DOCROOT, "CHANGELOG.md")).read()
    assert "## [Unreleased]" in text
    released = re.findall(rf"^## \[({SEMVER})\] - \d{{4}}-\d{{2}}-\d{{2}}$", text, re.M)
    assert released, "CHANGELOG.md has no released version heading"
    assert released[0] == version_file(), f"newest changelog entry is {released[0]}, VERSION says {version_file()}"
    assert len(set(released)) == len(released), "duplicate version in changelog"


def test_readme_shows_version():
    readme = open(os.path.join(DOCROOT, "README.md")).read()
    assert f"**Version {version_file()}**" in readme, "README's Version line is out of date"


def test_updater_reports_version():
    import subprocess
    out = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "updater", "updater.py"), "--version"],
                         capture_output=True, text=True, check=True).stdout
    assert version_file() in out


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(name, "ok")
