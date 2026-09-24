"""
tests/test_radio.py — the radio: stations from config, and the player end to end.

The station list is only as good as its round trip through config_to_toml,
which is what Preferences writes the file with: a layout that did not survive
that would lose every user-added station the first time anyone pressed Apply.

The player is exercised against a local Icecast-style server and miniaudio's
null audio backend, which consumes samples in real time without a sound card.
That covers the real decoder, the real device callback and the real network
reader — everything except the speaker.  Each failure a station can present
is checked to arrive as a readable message rather than as silence.
"""
from __future__ import annotations

import http.server
import io
import json
import socketserver
import sys
import threading
import time
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import core.radio as R                                        # noqa: E402
from core.config import (                                     # noqa: E402
    CFG_DEFAULTS_RADIO, STANDARD_SECTIONS, config_to_toml, load_setting,
)

TONE = (ROOT / "tests" / "data" / "radio_tone.mp3").read_bytes()

needs_miniaudio = pytest.mark.skipif(R._ma is None, reason="miniaudio not installed")


def _resolve(config: dict, profile: str | None = None) -> dict:
    return load_setting(config, profile, "Radio", CFG_DEFAULTS_RADIO,
                        warn_missing=False, include_extra=True)


# ── Stations from config ──────────────────────────────────────────────────────

def test_the_three_default_stations_in_order():
    stations, problems = R.stations_from_config(_resolve({}))
    assert [s.name for s in stations] == [
        "Radio Sidewinder", "Hutton Orbital Radio", "Radio Skvortsov"]
    assert all(s.url.startswith("https://") for s in stations)
    assert problems == []


def test_a_global_station_is_added_after_the_defaults():
    cfg = {"Radio": {"Name_Lave": "Lave Radio", "Url_Lave": "https://x.invalid/s"}}
    stations, _ = R.stations_from_config(_resolve(cfg))
    assert stations[-1] == R.Station("Lave", "Lave Radio", "https://x.invalid/s")


def test_a_profile_adds_overrides_and_hides():
    cfg = {
        "Radio": {"Name_Lave": "Lave Radio", "Url_Lave": "https://x.invalid/s"},
        "EDP1": {"Radio": {
            "Name_Mine":         "My Station",
            "Url_Mine":          "http://y.invalid/m",
            "Url_HuttonOrbital": "",
            "Name_Lave":         "Lave (profile)",
        }},
    }
    names = [s.name for s in R.stations_from_config(_resolve(cfg, "EDP1"))[0]]
    assert names == ["Radio Sidewinder", "Radio Skvortsov",
                     "Lave (profile)", "My Station"]
    # …and only inside that profile.
    names = [s.name for s in R.stations_from_config(_resolve(cfg, None))[0]]
    assert "Hutton Orbital Radio" in names and "My Station" not in names


def test_a_station_without_a_name_uses_its_id():
    stations, problems = R.stations_from_config({"Url_Bare": "https://z.invalid"})
    assert stations == [R.Station("Bare", "Bare", "https://z.invalid")]
    assert problems == []


@pytest.mark.parametrize("section,fragment", [
    ({"Name_Orphan": "Orphan"},                    "has no Url_Orphan"),
    ({"Url_Ftp": "ftp://nope.invalid/"},           "must start with http"),
    ({"Url_Num": 42},                              "quoted string"),
    ({"Stream_Wrong": "https://w.invalid"},        "not a Name_ or Url_ key"),
])
def test_an_unusable_entry_is_reported_not_dropped_silently(section, fragment):
    stations, problems = R.stations_from_config(section)
    assert stations == []
    assert any(fragment in p for p in problems), problems


def test_radio_is_a_standard_section():
    """Otherwise migration and backfill treat [Radio] as a profile."""
    assert "Radio" in STANDARD_SECTIONS


def test_stations_survive_the_preferences_writer():
    cfg = {
        "Radio": {**CFG_DEFAULTS_RADIO,
                  "Name_Lave": "Lave Radio — \"LR\"",
                  "Url_Lave":  "https://x.invalid/s?a=1&b=2"},
        "EDP1": {"Radio": {"Name_Mine": "My Station",
                           "Url_Mine":  "http://y.invalid/m",
                           "Url_RadioSkvortsov": ""}},
    }
    reread = tomllib.loads(config_to_toml(cfg))
    for profile in (None, "EDP1"):
        before = R.stations_from_config(_resolve(cfg, profile))
        after  = R.stations_from_config(_resolve(reread, profile))
        assert before == after


def test_the_example_config_carries_the_defaults():
    parsed = tomllib.loads((ROOT / "example.config.toml").read_text("utf-8"))
    stations, problems = R.stations_from_config(_resolve(parsed))
    assert problems == []
    assert [s.id for s in stations][:3] == [
        "RadioSidewinder", "HuttonOrbital", "RadioSkvortsov"]


def test_load_stations_tolerates_a_core_without_config():
    stations, _ = R.load_stations(object())
    assert len(stations) == 3


# ── Stream classification ─────────────────────────────────────────────────────

@pytest.mark.parametrize("ctype,kind", [
    ("audio/mpeg", "mp3"), ("audio/mpeg; charset=utf-8", "mp3"),
    ("AUDIO/MPEG", "mp3"), ("audio/flac", "flac"), ("application/ogg", "vorbis"),
    ("audio/x-mpegurl", "playlist"), ("audio/x-scpls", "playlist"),
])
def test_supported_types(ctype, kind):
    assert R.classify_content_type(ctype) == kind


@pytest.mark.parametrize("ctype,fragment", [
    ("audio/aacp", "AAC+"), ("audio/aac", "AAC"), ("audio/opus", "Opus"),
    ("text/html; charset=utf-8", "web page"), ("", "none given"),
    ("application/octet-stream", "unrecognised"),
])
def test_unsupported_types_say_what_they_are(ctype, fragment):
    with pytest.raises(R.RadioError, match=fragment):
        R.classify_content_type(ctype)


def test_playlists():
    assert R.first_url_in_playlist(
        "#EXTM3U\n#EXTINF:-1,Station\nhttps://a.invalid/s\n") == "https://a.invalid/s"
    assert R.first_url_in_playlist(
        "[playlist]\nNumberOfEntries=1\nFile1=http://b.invalid:8000/\n") \
        == "http://b.invalid:8000/"
    with pytest.raises(R.RadioError, match="HLS"):
        R.first_url_in_playlist("#EXTM3U\n#EXT-X-VERSION:3\nseg.ts\n")
    with pytest.raises(R.RadioError, match="no stream address"):
        R.first_url_in_playlist("#EXTM3U\n")


# ── ICY metadata ──────────────────────────────────────────────────────────────

class _FakeResp:
    def __init__(self, body: bytes, metaint: int):
        self._f = io.BytesIO(body)
        self.headers = {"icy-metaint": str(metaint)}

    def read(self, n):
        return self._f.read(n)

    def close(self):
        pass


def _icy(audio: bytes, metaint: int, titles) -> bytes:
    out, titles = b"", list(titles)
    for i in range(0, len(audio), metaint):
        out += audio[i:i + metaint]
        if len(audio[i:i + metaint]) < metaint:
            break
        t = titles.pop(0) if titles else ""
        meta = f"StreamTitle='{t}';".encode() if t else b""
        blocks = (len(meta) + 15) // 16
        out += bytes([blocks]) + meta.ljust(blocks * 16, b"\0")
    return out


@needs_miniaudio
def test_metadata_is_removed_from_the_audio_and_reported():
    audio = bytes(range(256)) * 40                     # 10240 bytes
    seen: list[str] = []
    src = R.IcySource(_FakeResp(_icy(audio, 1000, ["One", "", "Two"]), 1000),
                      seen.append, threading.Event())
    got = b""
    while True:
        chunk = src.read(333)
        if not chunk:
            break
        got += chunk
    assert got == audio
    assert seen == ["One", "Two"]
    assert src.eof and src.error is None


# ── End to end against a local station ────────────────────────────────────────

class _Station(http.server.BaseHTTPRequestHandler):
    """Paths: /live (endless MP3 with ICY titles), /short (MP3, then hang up),
    /aac, /page, /mislabelled (AAC sent as MP3), /list.m3u, /missing."""

    def log_message(self, *a):
        pass

    def _head(self, ctype: str, extra: dict | None = None):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()

    def do_GET(self):
        try:
            p = self.path
            if p == "/live":
                self._head("audio/mpeg", {"icy-metaint": "4096", "icy-br": "32"})
                while True:
                    self.wfile.write(_icy(TONE * 4, 4096, ["Test Artist - Test Song"] * 99))
            elif p == "/short":
                self._head("audio/mpeg")
                self.wfile.write(TONE)
            elif p == "/aac":
                self._head("audio/aacp")
                self.wfile.write(b"\0" * 4096)
            elif p == "/page":
                self._head("text/html")
                self.wfile.write(b"<html></html>")
            elif p == "/mislabelled":
                self._head("audio/mpeg")
                self.wfile.write(b"\x00junk" * 40000)
            elif p == "/list.m3u":
                self._head("text/plain")
                self.wfile.write(f"#EXTM3U\nhttp://127.0.0.1:{self.server.server_port}/live\n".encode())
            else:
                self.send_error(404)
        except (BrokenPipeError, ConnectionResetError):
            pass


@pytest.fixture(scope="module")
def station_server():
    class _Srv(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True
    srv = _Srv(("127.0.0.1", 0), _Station)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def _null_device():
    return R._ma.PlaybackDevice(
        output_format=R._ma.SampleFormat.SIGNED16, nchannels=2,
        sample_rate=44100, buffersize_msec=50,
        backends=[R._ma.Backend.NULL])


def _wait(player, states, timeout=15.0):
    end = time.monotonic() + timeout
    st = player.status()
    while time.monotonic() < end:
        st = player.status()
        if st.state in states:
            return st
        time.sleep(0.05)
    raise AssertionError(f"still {st.state!r} ({st.message}) after {timeout}s")


@pytest.fixture
def player(tmp_path):
    p = R.RadioPlayer(tmp_path / "radio.json", device_factory=_null_device)
    yield p
    p.shutdown()


@needs_miniaudio
def test_a_live_station_plays_names_its_song_and_stops(player, station_server):
    player.play(R.Station("t", "Test FM", f"{station_server}/live"))
    st = _wait(player, {R.PLAYING})
    assert st.detail == "MP3 · 32 kbps"
    end = time.monotonic() + 5
    while not player.status().title and time.monotonic() < end:
        time.sleep(0.05)
    assert player.status().title == "Test Artist - Test Song"
    assert R.status_line(player.status()).startswith("Playing")
    player.stop()
    assert player.status().state == R.STOPPED


@needs_miniaudio
def test_switching_station_leaves_no_second_stream(player, station_server):
    player.play(R.Station("a", "A", f"{station_server}/live"))
    _wait(player, {R.PLAYING})
    first = player._session
    player.play(R.Station("b", "B", f"{station_server}/live"))
    assert first.stop.is_set() and first.device is None
    _wait(player, {R.PLAYING})
    assert player.status().station.id == "b"


@needs_miniaudio
def test_a_playlist_address_is_followed(player, station_server):
    player.play(R.Station("m", "M3U", f"{station_server}/list.m3u"))
    _wait(player, {R.PLAYING})


@needs_miniaudio
@pytest.mark.parametrize("path,fragment", [
    ("/aac",          "AAC+ stream — not supported"),
    ("/page",         "web page"),
    ("/missing",      "HTTP 404"),
    ("/mislabelled",  "decode"),
    ("/short",        "ended the stream"),
])
def test_every_failure_is_reported(player, station_server, path, fragment):
    player.play(R.Station("x", "X", f"{station_server}{path}"))
    st = _wait(player, {R.ERROR}, timeout=20)
    assert fragment in st.message
    assert R.status_line(st).startswith("Error:")


@needs_miniaudio
def test_an_unreachable_host_is_reported(player):
    player.play(R.Station("x", "X", "http://127.0.0.1:9/"))
    st = _wait(player, {R.ERROR})
    assert "connect" in st.message


def test_no_audio_device_is_an_error_not_silence(tmp_path, station_server):
    if R._ma is None:
        pytest.skip("miniaudio not installed")

    def _none():
        raise R.RadioError("no audio output device found")
    p = R.RadioPlayer(tmp_path / "radio.json", device_factory=_none)
    p.play(R.Station("t", "T", f"{station_server}/live"))
    assert "no audio output device" in _wait(p, {R.ERROR}).message
    p.shutdown()


def test_the_null_backend_is_refused_by_the_default_device(monkeypatch):
    if R._ma is None:
        pytest.skip("miniaudio not installed")
    real = R._ma.PlaybackDevice

    def _forced_null(**kw):
        return real(**kw, backends=[R._ma.Backend.NULL])
    monkeypatch.setattr(R._ma, "PlaybackDevice", _forced_null)
    with pytest.raises(R.RadioError, match="no audio output device"):
        R.RadioPlayer()._make_device()


# ── Volume, mute, remembered station ──────────────────────────────────────────

def test_volume_mute_and_station_are_remembered(tmp_path):
    path = tmp_path / "radio.json"
    p = R.RadioPlayer(path)
    p.set_volume(35)
    p.toggle_mute()
    p.remember_station("HuttonOrbital")
    q = R.RadioPlayer(path)
    assert (q.status().volume, q.status().muted, q.last_station_id) == (35, True, "HuttonOrbital")
    assert json.loads(path.read_text())["volume"] == 35


def test_volume_is_clamped_and_unmutes(tmp_path):
    p = R.RadioPlayer(tmp_path / "r.json")
    p.toggle_mute()
    p.change_volume(+500)
    assert (p.status().volume, p.status().muted) == (100, False)
    p.change_volume(-500)
    assert p.status().volume == 0


def test_a_corrupt_prefs_file_falls_back_to_defaults(tmp_path):
    path = tmp_path / "radio.json"
    path.write_text("{not json")
    assert R.RadioPlayer(path).status().volume == 60


def test_the_feeder_scales_and_silences(tmp_path):
    import array
    p = R.RadioPlayer(tmp_path / "r.json")
    s = R._Session(R.Station("x", "X", "http://x"))
    loud = array.array("h", [10000, -10000] * 4).tobytes()
    feed = p._feeder(s)
    next(feed)
    s.push(loud)
    p.set_volume(100)
    assert feed.send(4) == loud
    s.push(loud)
    p.set_volume(50)
    assert array.array("h", feed.send(4))[:2].tolist() == [2500, -2500]
    s.push(loud)
    p.toggle_mute()
    assert feed.send(4) == b"\0" * 16
    # Starved: pads with silence rather than blocking the audio thread.
    assert feed.send(4) == b"\0" * 16 and s.starved_since is not None


def test_without_miniaudio_the_radio_says_so(monkeypatch, tmp_path):
    monkeypatch.setattr(R, "_ma", None)
    p = R.RadioPlayer(tmp_path / "r.json")
    p.play(R.Station("x", "X", "http://x.invalid"))
    st = p.status()
    assert st.state == R.UNAVAILABLE and "miniaudio" in st.message


# ── Controller (shared by both tabs) ──────────────────────────────────────────

class _FakePlayer:
    def __init__(self):
        self.playing = None
        self.last_station_id = ""
        self.volume, self.muted = 60, False
        self.calls = []

    def play(self, st):
        self.playing = st
        self.calls.append(("play", st.id))

    def stop(self):
        self.playing = None
        self.calls.append(("stop",))

    def is_active(self):
        return self.playing is not None

    def remember_station(self, sid):
        self.last_station_id = sid

    def change_volume(self, d):
        self.volume = max(0, min(100, self.volume + d))

    def toggle_mute(self):
        self.muted = not self.muted

    def status(self):
        state = R.PLAYING if self.playing else R.STOPPED
        return R.RadioStatus(state, self.playing, "", "", "", self.volume, self.muted)


class _Cfg:
    def __init__(self, config, profile=None):
        self.config, self.profile = config, profile

    def load_setting(self, category, defaults, warn=True, extra=False):
        return load_setting(self.config, self.profile, category, defaults, warn, extra)


def _ctl(config=None, player=None):
    from types import SimpleNamespace
    core = SimpleNamespace(cfg=_Cfg(config or {}))
    return R.RadioController(core, player or _FakePlayer()), core


def test_the_remembered_station_is_preselected_but_not_played():
    p = _FakePlayer()
    p.last_station_id = "HuttonOrbital"
    ctl, _ = _ctl(player=p)
    assert ctl.selected == "HuttonOrbital" and p.calls == []


def test_choosing_a_station_while_playing_retunes():
    ctl, _ = _ctl()
    ctl.toggle_play()
    ctl.select("RadioSkvortsov")
    assert ctl.player.calls == [("play", "RadioSidewinder"), ("play", "RadioSkvortsov")]
    ctl.toggle_play()
    assert ctl.player.playing is None


def test_choosing_a_station_while_stopped_does_not_start_it():
    ctl, _ = _ctl()
    ctl.select("RadioSkvortsov")
    assert ctl.player.calls == [] and ctl.player.last_station_id == "RadioSkvortsov"


def test_hiding_the_playing_station_stops_it_on_reload():
    ctl, core = _ctl()
    ctl.toggle_play()
    core.cfg.config = {"Radio": {"Url_RadioSidewinder": ""}}
    assert ctl.reload()
    assert ctl.player.playing is None
    assert ctl.selected == "HuttonOrbital"


def test_a_new_station_appears_on_reload():
    ctl, core = _ctl()
    core.cfg.config = {"Radio": {"Name_X": "X FM", "Url_X": "https://x.invalid"}}
    assert ctl.reload()
    assert ctl.options()[-1] == ("X FM", "X")
    assert not ctl.reload()                   # nothing changed the second time


def test_view_labels():
    ctl, _ = _ctl()
    v = ctl.view()
    assert (v["play_label"], v["mute_label"], v["volume"]) == ("▶ Play", "Mute", "Vol 60%")
    ctl.toggle_play(); ctl.toggle_mute()
    v = ctl.view()
    assert (v["play_label"], v["mute_label"], v["volume"]) == ("■ Stop", "Unmute", "Muted")
    assert v["on_air"] == "Radio Sidewinder"


def test_no_stations_says_where_to_look():
    ctl, _ = _ctl({"Radio": {k: "" for k in CFG_DEFAULTS_RADIO if k.startswith("Url_")}})
    v = ctl.view()
    assert "[Radio]" in v["status"] and not v["can_play"]


def test_alert_watcher():
    w = R.AlertWatcher()
    a = {"emoji": "!", "text": "Hull 50%", "mono_time": 1.0}
    assert not w.new_since_last([a])          # baseline
    assert not w.new_since_last([a])
    b = {"emoji": "!", "text": "Hull 25%", "mono_time": 2.0}
    assert w.new_since_last([b, a])
    assert not w.new_since_last([a])          # one ageing out is not news


# ── The terminal tab ──────────────────────────────────────────────────────────

def _tui_app(core, size=(60, 20), before=None):
    import asyncio
    from textual.app import App
    from tui.theme import build_css
    from tui.blocks.status import StatusBlock
    out = {}

    class _One(App):
        CSS = build_css("default")
        def compose(self):
            yield StatusBlock(core, id="block-under-test")

    async def _run():
        app = _One()
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            if before:
                before(app)
                await pilot.pause()
            out["lines"] = ["".join(s.text for s in strip).rstrip()
                            for strip in app.screen._compositor.render_strips()]
            out["app"] = app
            out["footers"] = {str(w.id): (w.region, w.parent.region)
                              for w in app.query(".footer-lbl")}
            out["active"] = app.query_one("#status-tabs").active
            out["footer_text"] = [str(w.render()) for w in app.query(".footer-lbl")]
    asyncio.run(_run())
    return out


def _stub_core(alerts):
    from types import SimpleNamespace
    return SimpleNamespace(state=SimpleNamespace(), cfg=_Cfg({}),
                           plugin_call=lambda comp, meth, *a: (
                               list(alerts) if meth == "get_alerts" else 1.0))


def _radio_tab(app):
    from textual.widgets import TabbedContent
    app.query_one("#status-tabs", TabbedContent).active = "status-tab-radio"


def test_tui_radio_controls_are_all_drawn(monkeypatch, tmp_path):
    monkeypatch.setattr(R, "_PLAYER", R.RadioPlayer(tmp_path / "r.json"))
    out = _tui_app(_stub_core([]), size=(48, 14), before=_radio_tab)
    footer = [ln for ln in out["lines"] if "Play" in ln and "Mute" in ln]
    assert footer, "\n".join(out["lines"])
    assert "Vol −" in footer[0] and "Vol +" in footer[0]
    for wid, (region, parent) in out["footers"].items():
        assert region.width > 0 and region.right <= parent.right, wid


def test_tui_config_problems_keep_their_brackets(monkeypatch, tmp_path):
    monkeypatch.setattr(R, "_PLAYER", R.RadioPlayer(tmp_path / "r.json"))
    core = _stub_core([])
    core.cfg = _Cfg({"Radio": {"Name_Orphan": "Orphan [/b]"}})
    out = _tui_app(core, size=(70, 20), before=_radio_tab)
    assert any("[Radio] Name_Orphan has no Url_Orphan" in ln for ln in out["lines"])


def test_tui_a_new_alert_brings_crew_alerts_forward(monkeypatch, tmp_path):
    monkeypatch.setattr(R, "_PLAYER", R.RadioPlayer(tmp_path / "r.json"))
    from tui.blocks.status import StatusBlock
    alerts: list[dict] = []
    core = _stub_core(alerts)

    def _go(app):
        blk = app.query_one(StatusBlock)
        blk._refresh_alerts()                                   # baseline
        _radio_tab(app)
        blk._refresh_alerts()
        assert app.query_one("#status-tabs").active == "status-tab-radio"
        alerts.append({"emoji": "!", "text": "Shields down", "mono_time": 5.0})
        blk._refresh_alerts()
    assert _tui_app(core, before=_go)["active"] == "status-tab-crew"


# ── The desktop tab ───────────────────────────────────────────────────────────

@pytest.fixture
def qt_app():
    pytest.importorskip("PySide6")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_gui_a_new_alert_brings_crew_alerts_forward(qt_app, monkeypatch, tmp_path):
    monkeypatch.setattr(R, "_PLAYER", R.RadioPlayer(tmp_path / "r.json"))
    from gui.blocks.status import StatusBlock
    alerts: list[dict] = []
    blk = StatusBlock(_stub_core(alerts))
    blk._refresh_alerts()
    blk._tabs.setCurrentIndex(1)
    blk._refresh_alerts()
    assert blk._tabs.currentIndex() == 1
    alerts.append({"emoji": "!", "text": "Shields down", "mono_time": 5.0})
    blk._refresh_alerts()
    assert blk._tabs.currentIndex() == 0


def test_both_tabs_offer_the_same_controls(qt_app, monkeypatch, tmp_path):
    monkeypatch.setattr(R, "_PLAYER", R.RadioPlayer(tmp_path / "r.json"))
    from PySide6.QtWidgets import QPushButton
    from gui.blocks.status import StatusBlock
    gui = StatusBlock(_stub_core([]))._radio
    gui_labels = [b.text() for b in gui.findChildren(QPushButton)]
    out = _tui_app(_stub_core([]), size=(60, 20), before=_radio_tab)
    tui_labels = out["footer_text"]
    assert gui_labels == tui_labels == ["+", "−", "▶ Play", "Vol −", "Vol +", "Mute"]
    assert [gui._combo.itemText(i) for i in range(gui._combo.count())] == [
        "Radio Sidewinder", "Hutton Orbital Radio", "Radio Skvortsov"]


def test_gui_crew_tab_draws_hired_crew(qt_app, monkeypatch, tmp_path):
    """The regression: fmt_crew_active was never imported here."""
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace
    monkeypatch.setattr(R, "_PLAYER", R.RadioPlayer(tmp_path / "r.json"))
    from gui.blocks.status import StatusBlock
    core = _stub_core([])
    core.state = SimpleNamespace(
        crew_name="Jo", crew_active=True, slf_type="GU-97 (Gelid G)",
        cmdr_in_slf=False, crew_rank=3, has_fighter_bay=False,
        crew_hire_time=datetime.now(timezone.utc) - timedelta(days=400),
        crew_total_paid=0, crew_paid_complete=True)
    blk = StatusBlock(core)
    blk._refresh_crew()
    assert "1y" in blk._kv_active._val.text()


# ── Redraw faults are reported, not swallowed ─────────────────────────────────

@pytest.mark.parametrize("block_id,name", [
    ("block-status", "Crew / Alerts"), ("block-nav", "Navigation"),
    ("block-ship", "Ship"),
])
def test_a_redraw_fault_is_reported_once(block_id, name):
    from types import SimpleNamespace
    from core.ui_helpers import report_block_fault
    pushed = []
    core = SimpleNamespace(plugin_call=lambda *a: pushed.append(a))
    seen: set = set()
    for _ in range(3):
        report_block_fault(core, block_id, NameError("x"), seen)
    assert pushed == [("alerts", "push_fault", "⚠",
                       f"{name} window failed to redraw — see log")]


@pytest.mark.parametrize("module", ["tui.app", "gui.app"])
def test_neither_front_end_swallows_a_redraw_fault(module):
    """The guard around refresh_data() was ``except Exception: pass``."""
    import ast
    import importlib.util
    spec = importlib.util.find_spec(module)
    tree = ast.parse(Path(spec.origin).read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_refresh_block")
    assert "report_block_fault" in ast.unparse(fn)


# ── Editing config.toml in place ──────────────────────────────────────────────

from core.config import (                                     # noqa: E402
    ConfigEditError, ConfigManager, backfill_config_defaults, edit_config_keys,
    load_config_file,
)


@pytest.fixture
def cfg_file(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text((ROOT / "example.config.toml").read_text("utf-8"), "utf-8")
    return p


def _changed_lines(before: str, after: str) -> tuple[list[str], list[str]]:
    import difflib
    diff = list(difflib.ndiff(before.splitlines(), after.splitlines()))
    return ([d[2:] for d in diff if d.startswith("- ")],
            [d[2:] for d in diff if d.startswith("+ ")])


def test_an_edit_touches_only_its_own_lines(cfg_file):
    before = cfg_file.read_text("utf-8")
    edit_config_keys(cfg_file, {("Radio",): {"Url_HuttonOrbital": "",
                                             "Name_Lave": "Lave Radio"}})
    removed, added = _changed_lines(before, cfg_file.read_text("utf-8"))
    assert removed == ['Url_HuttonOrbital    = "https://quincy.torontocast.com/hutton"']
    assert added == ['Url_HuttonOrbital    = ""', 'Name_Lave = "Lave Radio"']


def test_profile_keys_go_where_the_profile_keeps_them(cfg_file):
    edit_config_keys(cfg_file, {("EDP1", "Radio"): {"Url_A": "http://a"}})
    assert 'Radio.Url_A = "http://a"' in cfg_file.read_text("utf-8")
    cfg_file.write_text(cfg_file.read_text("utf-8") + '\n[EDP2.Radio]\nName_B = "B"\n')
    edit_config_keys(cfg_file, {("EDP2", "Radio"): {"Url_B": "http://b"}})
    text = cfg_file.read_text("utf-8")
    assert 'Name_B = "B"\nUrl_B = "http://b"' in text
    assert "Radio.Url_B" not in text


def test_a_missing_table_is_created(cfg_file):
    edit_config_keys(cfg_file, {("EDP9", "Radio"): {"Url_A": "http://a"}})
    parsed = tomllib.loads(cfg_file.read_text("utf-8"))
    assert parsed["EDP9"] == {"Radio": {"Url_A": "http://a"}}


def test_removing_the_last_dotted_key_is_accepted(cfg_file):
    edit_config_keys(cfg_file, {("EDP1", "Radio"): {"Url_A": "http://a"}})
    edit_config_keys(cfg_file, {("EDP1", "Radio"): {"Url_A": None}})
    assert "Radio" not in tomllib.loads(cfg_file.read_text("utf-8"))["EDP1"]


@pytest.mark.parametrize("value", ['Lave "LR" Radio', "a\\b", "x # y", "it's", "[Radio]"])
def test_awkward_values_round_trip(cfg_file, value):
    edit_config_keys(cfg_file, {("Radio",): {"Name_T": value}})
    assert tomllib.loads(cfg_file.read_text("utf-8"))["Radio"]["Name_T"] == value


def test_an_edit_it_cannot_verify_changes_nothing(cfg_file):
    # An inline table the line editor cannot see into: adding a dotted
    # Radio.* key beside it would redefine the table.
    cfg_file.write_text(cfg_file.read_text("utf-8").replace(
        "[EDP2]\n", '[EDP2]\nRadio = { Name_X = "X" }\n', 1), "utf-8")
    before = cfg_file.read_bytes()
    with pytest.raises(ConfigEditError, match="left unchanged"):
        edit_config_keys(cfg_file, {("EDP2", "Radio"): {"Url_X": "http://x"}})
    assert cfg_file.read_bytes() == before
    assert not cfg_file.with_name("config.toml.tmp").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_file_permissions_survive(cfg_file):
    cfg_file.chmod(0o600)
    edit_config_keys(cfg_file, {("Radio",): {"Name_T": "T"}})
    assert cfg_file.stat().st_mode & 0o777 == 0o600


# ── Adding and deleting stations ──────────────────────────────────────────────

def _live(cfg_file, profile=None, player=None):
    from types import SimpleNamespace
    cm = ConfigManager(load_config_file(cfg_file), cfg_file, profile)
    core = SimpleNamespace(cfg=cm, state=SimpleNamespace(), plugin_call=lambda *a: [])
    return R.RadioController(core, player or _FakePlayer()), core


def test_add_globally_writes_radio_and_selects_it(cfg_file):
    ctl, _ = _live(cfg_file, "EDP1")
    st = ctl.add_station("  Lave Radio ", " https://example.org:8000/lave ")
    assert st == R.Station("LaveRadio", "Lave Radio", "https://example.org:8000/lave")
    assert ctl.selected == "LaveRadio" and ctl.player.calls == []
    assert tomllib.loads(cfg_file.read_text("utf-8"))["Radio"]["Url_LaveRadio"] \
        == "https://example.org:8000/lave"


def test_add_to_the_profile(cfg_file):
    ctl, _ = _live(cfg_file, "EDP1")
    ctl.add_station("Mine", "http://m.example/s", to_profile=True)
    parsed = tomllib.loads(cfg_file.read_text("utf-8"))
    assert parsed["EDP1"]["Radio"] == {"Name_Mine": "Mine", "Url_Mine": "http://m.example/s"}
    assert "Name_Mine" not in parsed["Radio"]
    # …and it is only listed under that profile.
    other, _ = _live(cfg_file, None)
    assert "Mine" not in [s.id for s in other.stations]


def test_the_profile_choice_needs_a_profile(cfg_file):
    ctl, _ = _live(cfg_file, None)
    assert ctl.scope_labels()[1] == "Current profile (none loaded)"
    with pytest.raises(R.RadioError, match="No profile"):
        ctl.add_station("Mine", "http://m.example/s", to_profile=True)


def test_a_new_id_never_reuses_an_existing_one(cfg_file):
    ctl, _ = _live(cfg_file)
    assert ctl.add_station("Hutton Orbital", "http://h.example/").id == "HuttonOrbital2"
    assert ctl.add_station("Radio Sidewinder!", "http://s.example/").id == "RadioSidewinder2"


@pytest.mark.parametrize("name,url,fragment", [
    ("", "http://x.example", "Enter a station name"),
    ("Radio Sidewinder", "http://x.example", "already listed"),
    ("X", "ftp://x.example", "must start with http"),
    ("X", "http://x.example/a b", "cannot contain spaces"),
    ("X", "http://", "no host"),
    ("x" * 81, "http://x.example", "under 80"),
])
def test_add_refuses_what_would_not_work(cfg_file, name, url, fragment):
    ctl, _ = _live(cfg_file)
    before = cfg_file.read_bytes()
    with pytest.raises(R.RadioError, match=fragment):
        ctl.add_station(name, url)
    assert cfg_file.read_bytes() == before


def test_deleting_a_default_blanks_it_and_backfill_does_not_restore_it(cfg_file):
    ctl, _ = _live(cfg_file)
    title, message = ctl.delete_prompt("HuttonOrbital")
    assert title == "Delete Hutton Orbital Radio?" and "blanked" in message
    ctl.delete_station("HuttonOrbital")
    assert "HuttonOrbital" not in [s.id for s in ctl.stations]
    backfill_config_defaults(cfg_file)
    again, _ = _live(cfg_file)
    assert "HuttonOrbital" not in [s.id for s in again.stations]


def test_deleting_a_users_station_removes_its_lines(cfg_file):
    ctl, _ = _live(cfg_file, "EDP1")
    ctl.add_station("Lave Radio", "http://l.example/")
    ctl.add_station("Mine", "http://m.example/", to_profile=True)
    ctl.delete_station("LaveRadio")
    ctl.delete_station("Mine")
    text = cfg_file.read_text("utf-8")
    assert "LaveRadio" not in text and "Mine" not in text


def test_deleting_the_playing_station_stops_it(cfg_file):
    ctl, _ = _live(cfg_file)
    ctl.select("RadioSkvortsov")
    ctl.toggle_play()
    assert "playing now and will stop" in ctl.delete_prompt("RadioSkvortsov")[1]
    ctl.delete_station("RadioSkvortsov")
    assert ctl.player.playing is None and ("stop",) in ctl.player.calls


def test_deleting_another_station_leaves_playback_alone(cfg_file):
    ctl, _ = _live(cfg_file)
    ctl.toggle_play()                                  # Radio Sidewinder
    ctl.delete_station("HuttonOrbital")
    assert ctl.player.playing.id == "RadioSidewinder"


# ── …through both front ends ──────────────────────────────────────────────────

def test_tui_add_to_profile_then_delete_while_playing(cfg_file, monkeypatch):
    import asyncio
    from textual.app import App
    from textual.widgets import Input
    from tui.theme import build_css
    from tui.blocks.status import StatusBlock
    player = _FakePlayer()
    monkeypatch.setattr(R, "_PLAYER", player)
    _, core = _live(cfg_file, "EDP1", player)
    seen = {}

    class _One(App):
        CSS = build_css("default")
        def compose(self):
            yield StatusBlock(core, id="b")

    async def _run():
        app = _One()
        async with app.run_test(size=(100, 34)) as pilot:
            _radio_tab(app)
            await pilot.pause()
            await pilot.click("#radio-add-btn")
            await pilot.pause()
            assert app.screen.query_one("#scope-global").value is True
            app.screen.query_one("#station-name", Input).value = "Lave Radio"
            app.screen.query_one("#station-url", Input).value = "http://l.example/s"
            await pilot.click("#scope-profile")
            await pilot.click("#station-add")
            await pilot.pause()
            seen["after_add"] = app.query_one("#radio-select").value
            await pilot.click("#radio-play-btn")
            await pilot.click("#radio-del-btn")
            await pilot.pause()
            seen["confirm"] = type(app.screen).__name__
            await pilot.press("y")
            await pilot.pause()
            seen["after_delete"] = app.query_one("#radio-select").value
    asyncio.run(_run())
    assert seen["after_add"] == "LaveRadio"
    assert seen["confirm"] == "ConfirmModal"
    assert seen["after_delete"] == "RadioSidewinder"
    assert player.playing is None and ("play", "LaveRadio") in player.calls
    assert "LaveRadio" not in cfg_file.read_text("utf-8")


def test_tui_add_shows_why_it_refused(cfg_file, monkeypatch):
    import asyncio
    from textual.app import App
    from tui.station_screen import AddStationScreen
    monkeypatch.setattr(R, "_PLAYER", _FakePlayer())
    ctl, _ = _live(cfg_file)
    out = {}

    class _One(App):
        def on_mount(self):
            self.push_screen(AddStationScreen(ctl))

    async def _run():
        app = _One()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await pilot.click("#station-add")
            await pilot.pause()
            out["msg"] = str(app.screen.query_one("#station-result").render())
            out["disabled"] = app.screen.query_one("#scope-profile").disabled
    asyncio.run(_run())
    assert "Enter a station name" in out["msg"] and out["disabled"]


def test_gui_add_to_profile_then_delete_while_playing(qt_app, cfg_file, monkeypatch):
    from gui.blocks.status import StatusBlock
    from gui.station_dialog import AddStationDialog
    player = _FakePlayer()
    monkeypatch.setattr(R, "_PLAYER", player)
    _, core = _live(cfg_file, "EDP1", player)
    panel = StatusBlock(core)._radio

    dlg = AddStationDialog(panel._ctl)
    assert dlg._global.isChecked() and dlg._profile.isEnabled()
    dlg.set_fields("", "http://l.example/s")
    dlg.submit()
    assert "Enter a station name" in dlg.error() and dlg.station_id is None
    dlg.set_fields("Lave Radio", "http://l.example/s", to_profile=True)
    dlg.submit()
    assert dlg.station_id == "LaveRadio"
    panel._sync_options()
    assert panel._combo.currentText() == "Lave Radio"

    panel._ctl.toggle_play()
    asked = []
    panel._ask = lambda t, m: asked.append((t, m)) or False     # cancelled
    panel._open_delete()
    assert player.playing is not None and "LaveRadio" in cfg_file.read_text("utf-8")
    panel._ask = lambda t, m: asked.append((t, m)) or True
    panel._open_delete()
    assert asked[0][0] == "Delete Lave Radio?" and "[EDP1]" in asked[0][1]
    assert player.playing is None
    assert "LaveRadio" not in cfg_file.read_text("utf-8")
    assert panel._combo.currentText() == "Radio Sidewinder"
