"""Docs must stay in step with the project: settings documented, links and anchors resolve."""
import os
import re

ROOT = os.path.join(os.path.dirname(__file__), "..")
DOCROOT = os.path.join(ROOT, "..")            # the guides sit beside the cinema-kiosk/ application folder
DOCS = ["README.md", "INSTALL.md", "USAGE.md", "CHANGELOG.md"]


def where(name):
    return os.path.join(DOCROOT if name in DOCS else ROOT, name)


def read(name):
    return open(where(name), encoding="utf-8").read()


def env_keys():
    return [l.split("=", 1)[0] for l in read(".env").splitlines()
            if l.strip() and not l.lstrip().startswith("#") and "=" in l]


def slug(heading):
    """GitHub's heading anchor: lower case, punctuation dropped, spaces to hyphens."""
    h = re.sub(r"[^\w\- ]", "", heading.strip().lower())
    return h.replace(" ", "-")


def anchors(name):
    return {slug(m.group(1)) for m in re.finditer(r"^#{1,6}\s+(.*?)\s*$", read(name), re.M)}


def test_readme_documents_every_env_setting():
    readme = read("README.md")
    missing = [k for k in env_keys() if f"`{k}`" not in readme]
    assert not missing, f"settings in .env but not documented in README.md: {missing}"


def test_usage_documents_every_env_setting():
    usage = read("USAGE.md")
    missing = [k for k in env_keys() if f"`{k}`" not in usage]
    assert not missing, f"settings in .env but not described in USAGE.md: {missing}"


def test_install_covers_the_required_topics():
    install = read("INSTALL.md")
    for needle in ("Raspberry Pi Imager", "cinema", "ssh", "nmcli", "autoconnect-priority", "docker compose up -d --build",
                   "usermod -aG docker", "smbpasswd -a cinema", "[static]", "[slides]", "testparm", "RuntimeWatchdogSec",
                   "tailscale", "wifi.powersave", "NOPASSWD", "64-bit", "cinema-kiosk/cinema-kiosk", "ianpleasance/cinema-kiosk-display", "modetest", "Illegal instruction"):
        assert needle in install, f"INSTALL.md no longer mentions {needle!r}"
    assert "kiosk@" not in install and "sudo -iu" not in install        # one user only: cinema


def test_docs_exist_and_are_not_empty():
    for name in DOCS + ["VERSION", ".env", "docker-compose.yml", ".gitignore"]:
        assert os.path.getsize(where(name)) > 0, name


def test_relative_links_resolve():
    for doc in DOCS:
        for target in re.findall(r"\]\(([^)\s]+)\)", read(doc)):
            if re.match(r"[a-z]+://|mailto:", target):
                continue
            path, _, anchor = target.partition("#")
            file = path or doc
            assert os.path.exists(os.path.normpath(os.path.join(DOCROOT, file))), f"{doc}: broken link to {target}"
            if anchor and file.endswith(".md"):
                assert anchor in anchors(file), f"{doc}: no heading for anchor #{anchor} in {file}"


def test_install_contents_list_matches_headings():
    install = read("INSTALL.md")
    heads = re.findall(r"^## (\d+\. .*)$", install, re.M)
    toc = re.findall(r"^\d+\. \[(.*?)\]\(#", install, re.M)
    assert len(heads) == len(toc) == 15, (len(heads), len(toc))
    for h, t in zip(heads, toc):
        assert h.split(". ", 1)[1] == t, (h, t)


def test_compose_commands_in_docs_use_real_services():
    for doc in ("README.md", "INSTALL.md"):
        for svc in re.findall(r"docker compose (?:exec|logs|restart)(?: -[a-zA-Z]+)* (\w+)", read(doc)):
            assert svc in ("updater", "display", "-f", "--tail", "--since", "-t") or svc.isdigit(), (doc, svc)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(name, "ok")
