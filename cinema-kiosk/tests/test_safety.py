"""Archive of removed films, the MAX_ITEM_DROP safety check, multiple run times, the log file."""
import logging
import os
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "updater"))
import updater  # noqa: E402
from test_e2e import Resp  # noqa: E402
from test_updater import jpeg  # noqa: E402


def films(n, start=1):
    out = []
    for i in range(start, start + n):
        f = updater.Film(str(i), f"Film number {i}", f"https://x.test/{i}.jpg", f"https://x.test/f{i}")
        f.showings = [("Sat 21 Nov", ["7:30pm"])]
        out.append(f)
    return out


def use(listing):
    updater.REQUEST_DELAY = 0
    updater.parse_listing = lambda html, *a, **k: list(listing)
    updater.fetch = lambda s, url, **k: (Resp(text="x") if url.endswith("/WhatsOn")
                                         else Resp(content=jpeg(300, 450, (9, 9, 90)), ctype="image/jpeg"))


def names(path):
    return sorted(f for f in os.listdir(path) if f != "manifest.json")


def test_archive_and_manifest():
    data = tempfile.mkdtemp()
    use(films(4))
    updater.run_update(data)
    assert not os.path.exists(os.path.join(data, "archive"))
    use(films(3, start=2))                                  # film 1 dropped off, film 5 not yet there
    import time; time.sleep(1.1)
    updater.run_update(data)
    day = os.path.join(data, "archive", datetime.now(updater.TZ).strftime("%Y-%m-%d"))
    archived = sorted(os.listdir(day))
    assert archived and all("film-number-1_" in a for a in archived), archived
    assert not any("film-number-1_" in f for f in os.listdir(os.path.join(data, "current")))
    assert any("film-number-4_" in f for f in os.listdir(os.path.join(data, "current")))
    # old set still intact for the display until it is pruned
    gens = sorted(d for d in os.listdir(data) if d.startswith("gen-"))
    assert any("film-number-1_" in f for f in os.listdir(os.path.join(data, gens[0])))
    print("test_archive_and_manifest ok")


def test_manifest_fallback_from_file_names():
    d = tempfile.mkdtemp()
    for n in ("01_alpha_a_poster.jpg", "01_alpha_b_info.jpg", "02_beta-two_b_info.jpg", "notes.txt"):
        open(os.path.join(d, n), "w").close()
    got = updater.read_manifest(d)
    assert [f["slug"] for f in got] == ["alpha", "beta-two"] and len(got[0]["files"]) == 2
    print("test_manifest_fallback_from_file_names ok")


def test_drop_check():
    data = tempfile.mkdtemp()
    use(films(12))
    updater.run_update(data)
    before = os.readlink(os.path.join(data, "current"))
    saved = updater.MAX_ITEM_DROP
    try:
        updater.MAX_ITEM_DROP = 5
        use(films(7))                                       # drop of 5: allowed
        import time; time.sleep(1.1)
        updater.run_update(data)
        ok_target = os.readlink(os.path.join(data, "current"))
        assert ok_target != before
        arch = lambda: sorted(os.listdir(os.path.join(data, "archive", os.listdir(os.path.join(data, "archive"))[0])))
        archived_before = arch()
        assert len(archived_before) == 10                  # the 5 films that dropped, 2 files each
        use(films(1))                                       # drop of 6 from 7: refused
        try:
            updater.run_update(data)
            raise SystemExit("expected SuspiciousUpdate")
        except updater.SuspiciousUpdate as e:
            assert "--force" in str(e)
        assert os.readlink(os.path.join(data, "current")) == ok_target
        assert not [d for d in os.listdir(data) if d.startswith(".tmp-")]
        assert arch() == archived_before                    # nothing more archived on refusal
        time.sleep(1.1)
        updater.run_update(data, force=True)                # --force accepts it
        assert os.readlink(os.path.join(data, "current")) != ok_target
        updater.MAX_ITEM_DROP = 0                           # 0 switches the check off
        use(films(12)); time.sleep(1.1); updater.run_update(data)
        use(films(1)); time.sleep(1.1); updater.run_update(data)
    finally:
        updater.MAX_ITEM_DROP = saved
    print("test_drop_check ok")


def test_first_run_has_nothing_to_compare():
    data = tempfile.mkdtemp()
    use(films(30))
    updater.run_update(data)           # no previous set -> no check, however many
    print("test_first_run_has_nothing_to_compare ok")


def test_run_times():
    p = updater.parse_run_times
    assert p("0330 1230 1530 2030") == [(3, 30), (12, 30), (15, 30), (20, 30)]
    assert p("20:30, 3:30;12:30 03:30") == [(3, 30), (12, 30), (20, 30)]      # sorted, de-duplicated
    assert p("930") == [(9, 30)]
    before = len(updater.STARTUP_WARNINGS)
    assert p("25:00 abc 1260 0330") == [(3, 30)]
    assert len(updater.STARTUP_WARNINGS) == before + 3
    saved = updater.RUN_TIMES
    try:
        updater.RUN_TIMES = [(3, 30), (12, 30), (15, 30), (20, 30)]
        tz = updater.TZ
        at = lambda h, m: datetime(2026, 11, 21, h, m, tzinfo=tz)
        assert updater.seconds_until_next_run(at(1, 0)) == 2.5 * 3600            # -> 03:30
        assert updater.seconds_until_next_run(at(12, 30)) == 3 * 3600            # exactly on a time -> next
        assert updater.seconds_until_next_run(at(16, 0)) == 4.5 * 3600           # -> 20:30
        assert updater.seconds_until_next_run(at(21, 0)) == 6.5 * 3600           # -> 03:30 tomorrow
    finally:
        updater.RUN_TIMES = saved
    print("test_run_times ok")


def test_compose_mounts_logs():
    root = os.path.join(os.path.dirname(__file__), "..")
    compose = open(os.path.join(root, "docker-compose.yml")).read()
    for host, inside in (("logs", "/logs"), ("video", "/video"), ("slides", "/data")):
        assert f"./{host}:{inside}" in compose, host
        assert os.path.exists(os.path.join(root, host, "README.txt")), host   # so Docker doesn't create it as root
    assert 'user: "1000:1000"' in compose
    assert "\nvolumes:" not in compose                      # no hidden named volume any more
    print("test_compose_mounts_logs ok")


def test_log_file():
    d = tempfile.mkdtemp()
    path = os.path.join(d, "sub", "updater.log")
    saved = updater.LOG_FILE, list(updater.STARTUP_WARNINGS)
    try:
        updater.LOG_FILE = path
        updater.STARTUP_WARNINGS[:] = ["TIME_FORMAT='x' is not 12h or 24h - using 12h"]
        updater.setup_logging()
        updater.log.info("hello from the test")
        for h in logging.getLogger().handlers:
            h.flush()
        text = open(path, encoding="utf-8").read()
        assert "hello from the test" in text and "Setting: TIME_FORMAT" in text, text
        updater.LOG_FILE = "/proc/nope/updater.log"         # unwritable -> console only, no crash
        updater.setup_logging()
        updater.LOG_FILE = "off"
        updater.setup_logging()
        assert len(logging.getLogger().handlers) == 1
    finally:
        updater.LOG_FILE = saved[0]
        updater.STARTUP_WARNINGS[:] = saved[1]
        for h in list(logging.getLogger().handlers):
            logging.getLogger().removeHandler(h)
    print("test_log_file ok")


if __name__ == "__main__":
    test_archive_and_manifest()
    test_manifest_fallback_from_file_names()
    test_drop_check()
    test_first_run_has_nothing_to_compare()
    test_run_times()
    test_compose_mounts_logs()
    test_log_file()
