"""
core/radio.py — community radio for the Crew / Alerts window's Radio tab.

One player, shared by both front ends.  The terminal dashboard and the desktop
window each draw their own controls, but neither plays anything itself: both
call into the ``RadioPlayer`` returned by ``get_player()`` and poll its
``status()`` to redraw.  That is what keeps the two in step — there is only
one implementation of connecting, decoding, buffering and failing.

Stations
--------
Stations come from the ``[Radio]`` config section, two keys per station:

    Name_<Id> = "Shown in the station list"
    Url_<Id>  = "https://host:port/mount"

``<Id>`` is any TOML bare key (letters, digits, ``_`` and ``-``) and only has
to pair the two lines up.  The layout is dictated by ``config_to_toml``, which
writes scalars under bare keys and nothing else: an array of tables would be
flattened to a string, and a station name with a space in it cannot be a key,
the first time Preferences saved the file.  One key per attribute survives
that round trip, and it is the same shape ``[OverlayPanels]`` already uses.

Profiles override and extend the global list with dotted keys, exactly like
every other setting.  An empty ``Url_<Id>`` hides a station — the way to drop a
default, because the defaults are re-added to a ``[Radio]`` section they are
missing from.

Playback
--------
Decoding is miniaudio's, which is MIT licensed, has wheels for every platform
EDLD ships on, and needs no player installed on the machine.  It decodes MP3,
FLAC and Ogg Vorbis.  It does not decode AAC or Opus, and a station that
broadcasts either is told so by name rather than left silent.

miniaudio's own ``IceCastClient`` is not used.  It connects twice — once in
its constructor and again in a background thread that is given no SSL
context, so in a frozen build the second connection fails certificate
verification while the first one reported success.  When that thread dies its
``read()`` waits for data forever, and its metadata reader loops forever on a
dropped connection.  Each of those presents as a station that says it is
playing and makes no sound.  The reader here makes one connection, fails
loudly, and returns end-of-stream when it stops.

Nothing is played until the user presses play.  EDLD never starts audio on
its own, and that includes at launch: the last station is remembered and
preselected, not resumed.
"""
from __future__ import annotations

import array
import atexit
import json
import re
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from core.config import CFG_DEFAULTS_RADIO

try:                                    # optional dependency — see requirements.txt
    import miniaudio as _ma
except Exception as _exc:               # ImportError, or a broken cffi build
    _ma = None
    _MA_IMPORT_ERROR = f"{type(_exc).__name__}: {_exc}"
else:
    _MA_IMPORT_ERROR = ""


# ── Stations ──────────────────────────────────────────────────────────────────

#: Defaults for the ``[Radio]`` section, declared with the rest in
#: core/config.py so backfill, the generated config and the example-file tests
#: all see them.  Their order is the order of the station list.
RADIO_DEFAULTS = CFG_DEFAULTS_RADIO

_KEY_RE = re.compile(r"^(Name|Url)_([A-Za-z0-9_-]+)$")


@dataclass(frozen=True)
class Station:
    id:   str
    name: str
    url:  str


def stations_from_config(section: dict) -> tuple[list[Station], list[str]]:
    """Build the station list from a resolved ``[Radio]`` section.

    ``section`` is what ``load_setting("Radio", RADIO_DEFAULTS,
    include_extra=True)`` returns: defaults first, then global additions,
    then profile additions, with later layers already winning per key.

    Returns ``(stations, problems)``.  A station that cannot be used is left
    out and described in ``problems`` so the panel can say why it is missing
    — an entry that silently fails to appear is indistinguishable from a typo
    the user will never find.  A blank URL is not a problem; it is how a
    station is hidden.
    """
    order: list[str] = []
    names: dict[str, object] = {}
    urls:  dict[str, object] = {}
    problems: list[str] = []

    for key, value in (section or {}).items():
        m = _KEY_RE.match(str(key))
        if not m:
            problems.append(f"[Radio] {key}: not a Name_ or Url_ key")
            continue
        kind, sid = m.groups()
        if sid not in order:
            order.append(sid)
        (names if kind == "Name" else urls)[sid] = value

    stations: list[Station] = []
    for sid in order:
        url = urls.get(sid)
        if url is None:
            problems.append(f"[Radio] Name_{sid} has no Url_{sid}")
            continue
        if not isinstance(url, str):
            problems.append(f"[Radio] Url_{sid} must be a quoted string")
            continue
        url = url.strip()
        if not url:
            continue                                    # hidden on purpose
        if not re.match(r"^https?://", url, re.IGNORECASE):
            problems.append(f"[Radio] Url_{sid} must start with http:// or https://")
            continue
        name = names.get(sid, sid)
        if not isinstance(name, str) or not name.strip():
            name = sid
        stations.append(Station(sid, name.strip(), url))
    return stations, problems


def load_stations(core) -> tuple[list[Station], list[str]]:
    """Resolve the station list through the live config, profile included.

    Tolerates a core without a config manager (the block tests boot blocks
    against a stand-in) by falling back to the defaults.
    """
    section: dict = dict(RADIO_DEFAULTS)
    cfg = getattr(core, "cfg", None)
    loader = getattr(cfg, "load_setting", None)
    if callable(loader):
        try:
            section = loader("Radio", RADIO_DEFAULTS, False, True)
        except Exception as exc:
            _log(f"reading [Radio] failed: {exc}")
    return stations_from_config(section)


# ── Stream formats ────────────────────────────────────────────────────────────

class RadioError(Exception):
    """A failure worth showing the user verbatim.  Keep it short: it is drawn
    in one row of a narrow window."""


_PLAYLIST_TYPES = {
    "audio/x-mpegurl", "audio/mpegurl", "application/x-mpegurl",
    "audio/x-scpls", "application/pls+xml", "audio/scpls",
}
_UNSUPPORTED_TYPES = {
    "audio/aac":  "AAC",  "audio/aacp": "AAC+", "audio/x-aac": "AAC",
    "audio/mp4":  "AAC",  "audio/x-m4a": "AAC",
    "audio/opus": "Opus", "audio/webm": "WebM",
    "application/vnd.apple.mpegurl": "HLS",
}


def classify_content_type(ctype: str) -> str:
    """Map a Content-Type to ``mp3|flac|vorbis|playlist`` or raise RadioError."""
    base = (ctype or "").split(";", 1)[0].strip().lower()
    if base in ("audio/mpeg", "audio/mp3", "audio/mpeg3", "audio/x-mpeg"):
        return "mp3"
    if base in ("audio/flac", "audio/x-flac"):
        return "flac"
    if base in ("application/ogg", "audio/ogg", "audio/vorbis", "audio/x-ogg"):
        return "vorbis"
    if base in _PLAYLIST_TYPES:
        return "playlist"
    if base in _UNSUPPORTED_TYPES:
        raise RadioError(f"{_UNSUPPORTED_TYPES[base]} stream — not supported")
    if base.startswith("text/html"):
        raise RadioError("address is a web page, not a stream")
    raise RadioError(f"unrecognised stream type: {base or 'none given'}")


def _stream_kind(url: str, resp) -> str:
    """Classify a response.  A .m3u/.pls address is a playlist whatever the
    server calls it — plenty serve them as text/plain."""
    path = urllib.parse.urlsplit(url).path.lower()
    if path.endswith((".m3u", ".m3u8", ".pls")):
        return "playlist"
    return classify_content_type(resp.headers.get("Content-Type", ""))


def first_url_in_playlist(text: str) -> str:
    """The first stream address in an M3U or PLS body, or RadioError."""
    if "#EXT-X-" in text:
        raise RadioError("HLS stream — not supported")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("["):
            continue
        if "=" in line and line.lower().startswith("file"):
            line = line.split("=", 1)[1].strip()          # PLS: File1=http://…
        if re.match(r"^https?://", line, re.IGNORECASE):
            return line
    raise RadioError("playlist contains no stream address")


# ── Network source ────────────────────────────────────────────────────────────

_CONNECT_TIMEOUT = 15.0   # seconds to connect, and to wait on a stalled stream
_PLAYLIST_LIMIT  = 64 * 1024


def _ssl_context() -> ssl.SSLContext:
    # core/certs.install() has already pointed SSL_CERT_FILE at the bundled
    # store in a frozen build; a default context honours it.
    return ssl.create_default_context()


def _open(url: str):
    req = urllib.request.Request(url, headers={
        "Icy-MetaData": "1",
        "User-Agent":   "EDLD (ED Live Dashboard)",
        "Accept":       "*/*",
    })
    try:
        return urllib.request.urlopen(req, timeout=_CONNECT_TIMEOUT,
                                      context=_ssl_context())
    except urllib.error.HTTPError as exc:
        raise RadioError(f"station refused: HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        reason = exc.reason
        if isinstance(reason, ssl.SSLCertVerificationError):
            raise RadioError("certificate rejected") from exc
        if isinstance(reason, (socket.timeout, TimeoutError)):
            raise RadioError("no answer from station") from exc
        if isinstance(reason, socket.gaierror):
            raise RadioError("host not found") from exc
        raise RadioError(f"cannot connect: {reason}") from exc
    except (socket.timeout, TimeoutError) as exc:
        raise RadioError("no answer from station") from exc
    except ssl.SSLError as exc:
        raise RadioError(f"TLS failed: {exc.reason or exc}") from exc
    except OSError as exc:
        raise RadioError(f"cannot connect: {exc}") from exc


def _socket_of(resp) -> Optional[socket.socket]:
    """The live socket under an http.client response, so stop() can shut it
    and unblock a read in progress.  Internal attributes, hence the guard."""
    try:
        return resp.fp.raw._sock
    except Exception:
        return None


if _ma is not None:
    _SourceBase = _ma.StreamableSource
else:                                   # keep the module importable
    _SourceBase = object


class IcySource(_SourceBase):
    """A single HTTP response as a miniaudio source, with ICY metadata removed.

    ``read`` returns ``b""`` for end of stream, a stop, or a failure; the
    decoder then ends cleanly and the worker reports whichever it was from
    ``eof`` and ``error``.  It never waits indefinitely: a stall surfaces as
    the socket timeout.
    """

    def __init__(self, resp, on_title: Callable[[str], None],
                 stop: threading.Event) -> None:
        self._resp     = resp
        self._on_title = on_title
        self._stop     = stop
        try:
            self._metaint = int(resp.headers.get("icy-metaint") or 0)
        except ValueError:
            self._metaint = 0
        self._until_meta = self._metaint
        self.eof   = False
        self.error: Optional[str] = None

    def _raw(self, n: int) -> bytes:
        out = b""
        while len(out) < n:
            if self._stop.is_set():
                return b""
            chunk = self._resp.read(n - len(out))
            if not chunk:
                # Keep what did arrive: the last few hundred bytes of a stream
                # are audio like any other, and discarding them truncates it.
                self.eof = True
                return out
            out += chunk
        return out

    def _metadata(self) -> None:
        size = self._raw(1)
        if not size:
            return
        body = self._raw(size[0] * 16) if size[0] else b""
        text = body.rstrip(b"\0").decode("utf-8", errors="replace")
        m = re.search(r"StreamTitle='(.*?)';", text)
        if m:
            self._on_title(m.group(1).strip())

    def read(self, num_bytes: int) -> bytes:
        if self.error or self.eof or self._stop.is_set():
            return b""
        try:
            if not self._metaint:
                data = self._resp.read(num_bytes)
                if not data:
                    self.eof = True
                return data or b""
            out = b""
            while len(out) < num_bytes:
                if self._until_meta == 0:
                    self._metadata()
                    if self.eof or self._stop.is_set():
                        return out
                    self._until_meta = self._metaint
                take = min(num_bytes - len(out), self._until_meta)
                chunk = self._raw(take)
                out += chunk
                self._until_meta -= len(chunk)
                if self.eof or not chunk:
                    return out
            return out
        except (socket.timeout, TimeoutError):
            if not self._stop.is_set():
                self.error = "stream stalled"
        except Exception as exc:
            if not self._stop.is_set():
                self.error = f"connection lost: {exc}"
        return b""

    def close(self) -> None:
        try:
            self._resp.close()
        except Exception:
            pass


# ── Player ────────────────────────────────────────────────────────────────────

STOPPED     = "stopped"
CONNECTING  = "connecting"
BUFFERING   = "buffering"
PLAYING     = "playing"
ERROR       = "error"
UNAVAILABLE = "unavailable"

_RATE      = 44100
_CHANNELS  = 2
_FRAME     = 2 * _CHANNELS                     # bytes per s16 stereo frame
_PREROLL   = int(_RATE * 0.75) * _FRAME        # buffered before the device opens
_CEILING   = int(_RATE * 2.0) * _FRAME         # decoder waits above this


@dataclass(frozen=True)
class RadioStatus:
    state:   str
    station: Optional[Station]
    title:   str      # ICY "now playing", when the station sends one
    detail:  str      # e.g. "MP3 · 128 kbps"
    message: str      # the error, or why the radio is unavailable
    volume:  int      # 0-100
    muted:   bool


class _Session:
    """One connection's worth of state.  A new one per play, so a worker left
    over from a station change can never write into the current one."""

    def __init__(self, station: Station) -> None:
        self.station = station
        self.stop    = threading.Event()
        self.lock    = threading.Lock()
        self.pcm: deque[bytes] = deque()
        self.buffered = 0
        self.state   = CONNECTING
        self.title   = ""
        self.detail  = ""
        self.message = ""
        self.device  = None
        self.resp    = None
        self.decoding = True
        self.starved_since: Optional[float] = None

    # PCM queue — producer is the worker, consumer the audio callback.
    def push(self, data: bytes) -> None:
        with self.lock:
            self.pcm.append(data)
            self.buffered += len(data)

    def take(self, nbytes: int) -> bytes:
        parts: list[bytes] = []
        got = 0
        with self.lock:
            while self.pcm and got < nbytes:
                head = self.pcm[0]
                need = nbytes - got
                if len(head) <= need:
                    parts.append(self.pcm.popleft())
                    got += len(head)
                else:
                    parts.append(head[:need])
                    self.pcm[0] = head[need:]
                    got += need
            self.buffered -= got
        return b"".join(parts)

    def shutdown(self) -> None:
        """Silence and release everything.  Safe from any thread, repeatable."""
        self.stop.set()
        dev, self.device = self.device, None
        if dev is not None:
            try:
                dev.close()
            except Exception:
                pass
        sock = _socket_of(self.resp) if self.resp is not None else None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


class RadioPlayer:
    """Plays one station at a time.  Every public method returns at once;
    connecting and decoding happen on a worker thread."""

    def __init__(self, prefs_path: Optional[Path] = None,
                 device_factory: Optional[Callable] = None) -> None:
        self._prefs_path = prefs_path
        self._device_factory = device_factory
        self._lock = threading.Lock()
        self._session: Optional[_Session] = None
        self._volume = 60
        self._muted  = False
        self._last_station_id = ""
        self._load_prefs()

    # ── Availability ──────────────────────────────────────────────────────────

    @property
    def available(self) -> bool:
        return _ma is not None or self._device_factory is not None

    @property
    def unavailable_reason(self) -> str:
        if self.available:
            return ""
        return "miniaudio is not installed — see INSTALL.md"

    # ── Preferences (last station, volume) ───────────────────────────────────

    @property
    def last_station_id(self) -> str:
        return self._last_station_id

    def _load_prefs(self) -> None:
        if not self._prefs_path:
            return
        try:
            data = json.loads(self._prefs_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except Exception as exc:
            _log(f"{self._prefs_path.name} unreadable, using defaults: {exc}")
            return
        vol = data.get("volume")
        if isinstance(vol, int) and not isinstance(vol, bool):
            self._volume = max(0, min(100, vol))
        self._muted = bool(data.get("muted", False))
        sid = data.get("station")
        self._last_station_id = sid if isinstance(sid, str) else ""

    def _save_prefs(self) -> None:
        if not self._prefs_path:
            return
        data = {"station": self._last_station_id,
                "volume": self._volume, "muted": self._muted}
        try:
            self._prefs_path.parent.mkdir(parents=True, exist_ok=True)
            self._prefs_path.write_text(json.dumps(data, indent=2) + "\n",
                                        encoding="utf-8")
        except OSError as exc:
            _log(f"could not save {self._prefs_path}: {exc}")

    def remember_station(self, station_id: str) -> None:
        if station_id and station_id != self._last_station_id:
            self._last_station_id = station_id
            self._save_prefs()

    # ── Controls ─────────────────────────────────────────────────────────────

    def play(self, station: Station) -> None:
        self.stop()
        self.remember_station(station.id)
        if not self.available:
            return
        session = _Session(station)
        with self._lock:
            self._session = session
        threading.Thread(target=self._run, args=(session,),
                         name=f"radio-{station.id}", daemon=True).start()

    def stop(self) -> None:
        with self._lock:
            session, self._session = self._session, None
        if session is not None:
            session.shutdown()

    def is_active(self) -> bool:
        with self._lock:
            s = self._session
        return s is not None and s.state in (CONNECTING, BUFFERING, PLAYING)

    def set_volume(self, volume: int) -> None:
        self._volume = max(0, min(100, int(volume)))
        if self._volume and self._muted:
            self._muted = False
        self._save_prefs()

    def change_volume(self, delta: int) -> None:
        self.set_volume(self._volume + delta)

    def toggle_mute(self) -> None:
        self._muted = not self._muted
        self._save_prefs()

    def status(self) -> RadioStatus:
        with self._lock:
            s = self._session
        if not self.available:
            return RadioStatus(UNAVAILABLE, None, "", "",
                               self.unavailable_reason, self._volume, self._muted)
        if s is None:
            return RadioStatus(STOPPED, None, "", "", "",
                               self._volume, self._muted)
        state = s.state
        if state == PLAYING:
            # The callback marks starvation; a short gap is not worth a
            # flicker, a sustained one is worth saying.
            starved = s.starved_since
            if starved is not None and time.monotonic() - starved > 1.0:
                state = BUFFERING
        return RadioStatus(state, s.station, s.title, s.detail, s.message,
                           self._volume, self._muted)

    def shutdown(self) -> None:
        self.stop()

    # ── Worker ────────────────────────────────────────────────────────────────

    def _gain(self) -> float:
        if self._muted or self._volume <= 0:
            return 0.0
        v = self._volume / 100.0
        return v * v                      # perceptual: 50% sounds like half

    def _make_device(self):
        if self._device_factory is not None:
            return self._device_factory()
        try:
            dev = _ma.PlaybackDevice(output_format=_ma.SampleFormat.SIGNED16,
                                     nchannels=_CHANNELS, sample_rate=_RATE,
                                     buffersize_msec=100, app_name="EDLD")
        except _ma.MiniaudioError as exc:
            raise RadioError("no audio output device found") from exc
        # With no backend requested, miniaudio falls back to its null device
        # rather than failing: playback "succeeds" into nothing.
        if str(getattr(dev, "backend", "")).lower() == "null":
            dev.close()
            raise RadioError("no audio output device found")
        return dev

    def _feeder(self, session: _Session):
        """The audio callback.  Never blocks: silence when the queue is dry."""
        frames = yield b""
        while True:
            nbytes = int(frames) * _FRAME
            data = session.take(nbytes)
            if len(data) < nbytes:
                if session.starved_since is None:
                    session.starved_since = time.monotonic()
                data += b"\0" * (nbytes - len(data))
            else:
                session.starved_since = None
            gain = self._gain()
            if gain <= 0.0:
                data = b"\0" * nbytes
            elif gain < 0.999:
                pcm = array.array("h")
                pcm.frombytes(data)
                data = array.array("h", [int(x * gain) for x in pcm]).tobytes()
            frames = yield data

    def _run(self, session: _Session) -> None:
        source = None
        try:
            url = session.station.url
            resp = _open(url)
            session.resp = resp
            kind = _stream_kind(url, resp)
            if kind == "playlist":
                body = resp.read(_PLAYLIST_LIMIT).decode("utf-8", errors="replace")
                resp.close()
                url = first_url_in_playlist(body)
                resp = _open(url)
                session.resp = resp
                kind = _stream_kind(url, resp)
                if kind == "playlist":
                    raise RadioError("playlist points at another playlist")
            if session.stop.is_set():
                return

            bitrate = (resp.headers.get("icy-br") or "").split(",")[0].strip()
            session.detail = kind.upper() + (f" · {bitrate} kbps" if bitrate.isdigit() else "")

            def _title(t: str) -> None:
                session.title = t
            source = IcySource(resp, _title, session.stop)
            fmt = {"mp3": _ma.FileFormat.MP3, "flac": _ma.FileFormat.FLAC,
                   "vorbis": _ma.FileFormat.VORBIS}[kind]
            try:
                stream = _ma.stream_any(source, fmt,
                                        output_format=_ma.SampleFormat.SIGNED16,
                                        nchannels=_CHANNELS, sample_rate=_RATE,
                                        frames_to_read=2048)
            except _ma.DecodeError as exc:
                if source.error:
                    raise RadioError(source.error) from exc
                raise RadioError(f"cannot decode this {kind.upper()} stream") from exc

            session.state = BUFFERING
            started = False
            try:
                for chunk in stream:
                    if session.stop.is_set():
                        return
                    session.push(chunk.tobytes())
                    if not started and session.buffered >= _PREROLL:
                        started = True
                        dev = self._make_device()
                        feed = self._feeder(session)
                        next(feed)
                        dev.start(feed)
                        session.device = dev
                        # stop() may have run between the check above and
                        # here, and found no device to close.  It set the
                        # event first, so looking again now cannot miss it.
                        if session.stop.is_set():
                            session.device = None
                            dev.close()
                            return
                        session.state = PLAYING
                    while session.buffered > _CEILING and not session.stop.is_set():
                        time.sleep(0.05)
            except _ma.DecodeError as exc:
                if session.stop.is_set():
                    return
                raise RadioError(source.error or "stream data could not be decoded") from exc
            if session.stop.is_set():
                return
            if source.error:
                raise RadioError(source.error)
            raise RadioError("station ended the stream")
        except RadioError as exc:
            if not session.stop.is_set():
                _log(f"{session.station.name}: {exc}")
                self._fail(session, str(exc))
        except Exception as exc:
            if not session.stop.is_set():
                _log_exception(f"{session.station.name}: playback failed", exc)
                name = type(exc).__name__
                self._fail(session, f"playback failed ({name})")
        finally:
            session.decoding = False
            if source is not None:
                source.close()
            elif session.resp is not None:
                try:
                    session.resp.close()
                except Exception:
                    pass

    def _fail(self, session: _Session, message: str) -> None:
        # Let what is already buffered finish rather than cutting it off.
        deadline = time.monotonic() + 3.0
        while (session.device is not None and session.buffered > 0
               and not session.stop.is_set() and time.monotonic() < deadline):
            time.sleep(0.05)
        dev, session.device = session.device, None
        if dev is not None:
            try:
                dev.close()
            except Exception:
                pass
        session.message = message
        session.state = ERROR


# ── Module singleton ──────────────────────────────────────────────────────────

_PLAYER: Optional[RadioPlayer] = None
_PLAYER_LOCK = threading.Lock()


def get_player() -> RadioPlayer:
    """The one player for this process, shared by whichever front end is up."""
    global _PLAYER
    with _PLAYER_LOCK:
        if _PLAYER is None:
            try:
                from core.state import EDLD_DATA_DIR
                prefs = Path(EDLD_DATA_DIR) / "radio.json"
            except Exception:
                prefs = None
            _PLAYER = RadioPlayer(prefs)
            # Close the device before the interpreter tears down: a native
            # audio thread calling back into a half-finalised Python is a
            # crash at exit rather than a clean one.
            atexit.register(_PLAYER.shutdown)
        return _PLAYER


# ── Controller shared by both front ends ─────────────────────────────────────

class RadioController:
    """Everything the Radio tab does, minus the widgets.

    The terminal and desktop tabs each own one, forward clicks to it, and draw
    whatever ``view()`` returns.  Labels, wording, the volume step and what
    happens when the list changes under a playing station are therefore
    decided once, here, and cannot drift between the two.
    """

    VOLUME_STEP = 5

    def __init__(self, core, player: Optional[RadioPlayer] = None) -> None:
        self.core     = core
        self.player   = player if player is not None else get_player()
        self.stations: list[Station] = []
        self.problems: list[str] = []
        self.selected = ""
        self.reload()

    # ── Station list ─────────────────────────────────────────────────────────

    def reload(self) -> bool:
        """Re-read the station list.  True when anything a tab shows changed.

        Called on every poll, which is what makes the list follow config
        hot-reload and a profile switch without a restart.
        """
        stations, problems = load_stations(self.core)
        changed = (stations, problems) != (self.stations, self.problems)
        self.stations, self.problems = stations, problems

        ids = [st.id for st in stations]
        if self.selected not in ids:
            want = self.player.last_station_id
            self.selected = want if want in ids else (ids[0] if ids else "")
            changed = True

        # A station removed or hidden while it plays is stopped: carrying on
        # playing something the list no longer offers leaves no way to tell
        # what it is.
        playing = self.player.status().station
        if playing is not None and self.player.is_active():
            current = next((st for st in stations if st.id == playing.id), None)
            if current is None or current.url != playing.url:
                self.player.stop()
                changed = True
        return changed

    def station(self) -> Optional[Station]:
        return next((st for st in self.stations if st.id == self.selected), None)

    def options(self) -> list[tuple[str, str]]:
        """(label, id) pairs for a dropdown, in list order."""
        return [(st.name, st.id) for st in self.stations]

    # ── Actions ──────────────────────────────────────────────────────────────

    def select(self, station_id: str) -> None:
        """Choose a station.  If one is playing, switch to the new one — the
        behaviour of a radio's tuning dial, rather than a second press."""
        if not station_id or station_id == self.selected:
            return
        if station_id not in (st.id for st in self.stations):
            return
        self.selected = station_id
        self.player.remember_station(station_id)
        if self.player.is_active():
            self.player.play(self.station())

    def toggle_play(self) -> None:
        if self.player.is_active():
            self.player.stop()
            return
        st = self.station()
        if st is not None:
            self.player.play(st)

    def volume_down(self) -> None:
        self.player.change_volume(-self.VOLUME_STEP)

    def volume_up(self) -> None:
        self.player.change_volume(+self.VOLUME_STEP)

    def toggle_mute(self) -> None:
        self.player.toggle_mute()

    # ── Adding and deleting stations ─────────────────────────────────────────
    #
    # Both write config.toml through edit_config_keys(), which changes only
    # the lines concerned and refuses any edit it cannot verify, then reload
    # it at once.  The [Radio] section stays the single source of truth: a
    # station added here is an ordinary pair of keys the user can see and
    # edit by hand, not a second list kept somewhere else.

    NAME_LIMIT = 80

    def _cfg(self):
        cfg = getattr(self.core, "cfg", None)
        if cfg is None or getattr(cfg, "config_path", None) is None:
            raise RadioError("the config file is not available")
        return cfg

    def profile_name(self) -> Optional[str]:
        """The profile loaded now, or None when running on the global config."""
        return getattr(getattr(self.core, "cfg", None), "config_profile", None) or None

    def _raw_radio(self, profile: Optional[str]) -> dict:
        config = getattr(self._cfg(), "config", {}) or {}
        node = config.get(profile, {}) if profile else config
        radio = node.get("Radio", {}) if isinstance(node, dict) else {}
        return radio if isinstance(radio, dict) else {}

    def scope_labels(self) -> tuple[str, str]:
        """Labels for the add dialog's Global / current profile choice."""
        profile = self.profile_name()
        return ("Global — every profile",
                f"Current profile ({profile})" if profile
                else "Current profile (none loaded)")

    def validate_new(self, name: str, url: str) -> Optional[str]:
        """Why this station cannot be added, or None if it can."""
        return self._validate(name, url)

    def _validate(self, name: str, url: str,
                  exclude_id: Optional[str] = None) -> Optional[str]:
        """Why this name and address cannot be saved, or None if they can.

        ``exclude_id`` is the station being edited, whose own name is not a
        clash with itself."""
        name, url = (name or "").strip(), (url or "").strip()
        if not name:
            return "Enter a station name."
        if len(name) > self.NAME_LIMIT:
            return f"Keep the name under {self.NAME_LIMIT} characters."
        if any(ord(c) < 32 for c in name):
            return "The name cannot contain control characters."
        if any(st.name.casefold() == name.casefold() and st.id != exclude_id
               for st in self.stations):
            return f"A station called {name} is already listed."
        if not re.match(r"^https?://", url, re.IGNORECASE):
            return "The address must start with http:// or https://."
        if any(c.isspace() for c in url) or any(ord(c) < 32 for c in url):
            return "The address cannot contain spaces."
        if not urllib.parse.urlsplit(url).hostname:
            return "The address has no host name."
        return None

    def _taken_ids(self) -> set[str]:
        ids = set()
        config = getattr(self._cfg(), "config", {}) or {}
        tables = [RADIO_DEFAULTS, self._raw_radio(None)]
        for value in config.values():
            if isinstance(value, dict) and isinstance(value.get("Radio"), dict):
                tables.append(value["Radio"])        # every profile's, too
        for table in tables:
            for key in table:
                m = _KEY_RE.match(str(key))
                if m:
                    ids.add(m.group(2).casefold())
        return ids

    @staticmethod
    def new_station_id(name: str, taken: set[str]) -> str:
        """A bare-key Id from a station name: "Lave Radio" -> "LaveRadio".

        Unique across the defaults, [Radio] and every profile's Radio table,
        compared without case, so a new station can never pair up with the
        leftover half of another one."""
        words = re.findall(r"[A-Za-z0-9]+", name)
        base = "".join(w[:1].upper() + w[1:] for w in words)[:40] or "Station"
        sid, n = base, 2
        while sid.casefold() in taken:
            sid, n = f"{base}{n}", n + 1
        return sid

    def add_station(self, name: str, url: str, to_profile: bool = False) -> Station:
        """Write a new station to [Radio], or to the current profile's Radio
        table, and select it.  Raises RadioError with a readable reason."""
        problem = self.validate_new(name, url)
        if problem:
            raise RadioError(problem)
        name, url = name.strip(), url.strip()
        cfg = self._cfg()
        profile = self.profile_name() if to_profile else None
        if to_profile and not profile:
            raise RadioError("No profile is loaded — add it globally instead.")
        sid = self.new_station_id(name, self._taken_ids())
        table = (profile, "Radio") if profile else ("Radio",)
        self._write(cfg, {table: {f"Name_{sid}": name, f"Url_{sid}": url}})
        self.reload()
        self.select(sid)
        return next(st for st in self.stations if st.id == sid)

    def _delete_edits(self, station_id: str) -> tuple[dict, list[str]]:
        edits: dict = {}
        notes: list[str] = []
        profile = self.profile_name()
        keys = (f"Name_{station_id}", f"Url_{station_id}")
        if profile:
            present = [k for k in keys if k in self._raw_radio(profile)]
            if present:
                edits[(profile, "Radio")] = {k: None for k in present}
                notes.append(f"It is removed from profile [{profile}].")
        if f"Url_{station_id}" in RADIO_DEFAULTS:
            # Deleted default lines are put back at the next launch, so a
            # default is hidden the documented way instead.
            edits[("Radio",)] = {f"Url_{station_id}": ""}
            notes.append("It is one of the default stations, so its address in "
                         "[Radio] is blanked rather than deleted; set it again "
                         "to bring the station back.")
        else:
            present = [k for k in keys if k in self._raw_radio(None)]
            if present:
                edits[("Radio",)] = {k: None for k in present}
                notes.append("It is removed from [Radio].")
        return edits, notes

    def delete_prompt(self, station_id: str) -> tuple[str, str]:
        """(title, message) for the confirmation, saying exactly what changes."""
        st = next((s for s in self.stations if s.id == station_id), None)
        if st is None:
            raise RadioError("That station is no longer listed.")
        _, notes = self._delete_edits(station_id)
        status = self.player.status()
        if status.station is not None and status.station.id == station_id \
                and self.player.is_active():
            notes.append("It is playing now and will stop.")
        return f"Delete {st.name}?", " ".join(notes)

    def delete_station(self, station_id: str) -> None:
        """Remove a station from config.toml, stopping it first if it plays."""
        edits, _ = self._delete_edits(station_id)
        if not edits:
            raise RadioError("That station is not defined anywhere EDLD can edit.")
        playing = self.player.status().station
        if playing is not None and playing.id == station_id:
            self.player.stop()
        self._write(self._cfg(), edits)
        self.reload()

    # ── Editing a station ────────────────────────────────────────────────────
    #
    # An edit keeps the station's Id and changes its Name_ and Url_ in place,
    # so the remembered station, the selection and anything else keyed on the
    # Id carry on pointing at it.  The keys are written to the layer the
    # station already lives in: the loaded profile's Radio table when that
    # defines it, otherwise [Radio].  Writing a profile's station globally
    # would change nothing — the profile's keys win — and writing a global one
    # into the profile would quietly fork it for that profile alone.

    def _edit_target(self, station_id: str) -> tuple[tuple, str]:
        """(table path, where-it-is-saved label) for an edit to this station."""
        profile = self.profile_name()
        keys = (f"Name_{station_id}", f"Url_{station_id}")
        if profile and any(k in self._raw_radio(profile) for k in keys):
            return (profile, "Radio"), f"profile [{profile}]"
        return ("Radio",), "[Radio], every profile"

    def _listed(self, station_id: str) -> Station:
        st = next((s for s in self.stations if s.id == station_id), None)
        if st is None:
            raise RadioError("That station is no longer listed.")
        return st

    def edit_info(self, station_id: str) -> dict:
        """What the edit form starts from: the station's current name and
        address, and where the change will be saved."""
        st = self._listed(station_id)
        _, where = self._edit_target(station_id)
        return {"id": st.id, "name": st.name, "url": st.url, "saved_to": where}

    def edit_station(self, station_id: str, name: str, url: str) -> Station:
        """Change a station's name and address.  Raises RadioError with a
        readable reason and leaves config.toml untouched if it cannot.

        A station that was playing keeps playing: a new address is tuned in
        straight away rather than leaving the commander on a stopped radio
        they did not stop."""
        st = self._listed(station_id)
        problem = self._validate(name, url, exclude_id=station_id)
        if problem:
            raise RadioError(problem)
        name, url = name.strip(), url.strip()
        if (name, url) == (st.name, st.url):
            return st
        cfg = self._cfg()
        table, _ = self._edit_target(station_id)
        playing = self.player.status().station
        was_playing = (playing is not None and playing.id == station_id
                       and self.player.is_active())
        self._write(cfg, {table: {f"Name_{station_id}": name,
                                  f"Url_{station_id}": url}})
        self.reload()                  # stops it if the address changed
        edited = self._listed(station_id)
        if was_playing and not self.player.is_active():
            self.player.play(edited)
        return edited

    def _write(self, cfg, edits: dict) -> None:
        from core.config import ConfigEditError, edit_config_keys
        try:
            edit_config_keys(Path(cfg.config_path), edits)
        except ConfigEditError as exc:
            raise RadioError(str(exc)) from exc
        try:
            cfg.reload_now()
        except Exception as exc:
            raise RadioError(f"saved, but reloading the config failed: {exc}") from exc

    # ── What to draw ─────────────────────────────────────────────────────────

    def view(self) -> dict:
        st = self.player.status()
        active = st.state in (CONNECTING, BUFFERING, PLAYING)
        if st.state == UNAVAILABLE:
            tone = "health-crit"
        elif st.state == ERROR:
            tone = "health-crit"
        elif st.state == PLAYING:
            tone = "health-good"
        elif active:
            tone = "health-warn"
        else:
            tone = ""
        # The name from the list, not the one the stream was started with, so
        # renaming the station that is playing renames it here too.
        on_air = "—"
        if st.station and active:
            listed = next((s for s in self.stations if s.id == st.station.id), None)
            on_air = (listed or st.station).name
        if not self.stations and st.state != UNAVAILABLE:
            status = "No stations — see [Radio] in config.toml"
            tone = "health-warn"
        else:
            status = status_line(st)
        return {
            "status":      status,
            "status_tone": tone,
            "on_air":      on_air,
            "now":         (st.title or "—") if active else "—",
            "volume":      volume_label(st),
            "play_label":  "■ Stop" if active else "▶ Play",
            "mute_label":  "Unmute" if st.muted else "Mute",
            "can_play":    st.state != UNAVAILABLE and bool(self.stations),
            "can_delete":  self.station() is not None,
            "can_edit":    self.station() is not None,
            "scope_labels": self.scope_labels(),
            "problems":    list(self.problems),
        }


class AlertWatcher:
    """Notices alerts that were not there last time.

    The Crew / Alerts window gained a Radio tab, which breaks the rule that
    an alert never needs a tab change to be seen.  Both front ends restore it
    by returning to the Crew / Alerts tab whenever this reports something
    new.  The first call only takes a baseline, so alerts already standing
    when the window opens do not yank the user off a tab they just chose.
    """

    def __init__(self) -> None:
        self._seen: Optional[set] = None

    def new_since_last(self, alerts: list[dict]) -> bool:
        keys = {(a.get("emoji"), a.get("text"), a.get("mono_time"))
                for a in (alerts or [])}
        if self._seen is None:
            self._seen = keys
            return False
        fresh = bool(keys - self._seen)
        self._seen = keys
        return fresh


# ── Selftest ──────────────────────────────────────────────────────────────────

#: 0.3 s of a 440 Hz sine, 8 kbps mono MP3 (ffmpeg, no tags) — enough for the
#: decoder to prove itself without a network or a sound card.
_SELFTEST_MP3 = (
    "//MQxAACoD64AUMAAXd3d+I4cDAwMDD1xb7/8xLEAgNwRtABjwAAf1cRnqjQnCCsbenJMH//"
    "8xDEAgNIPrlB0gABpHEkikQYBvxmT0aq+f/zEMQBAxg6YAAOeiEMR45ZQ6dpGo1G+rX5//MQ"
    "xAEDGDpgAA56IYrFljjDx2aebUryyvn/8xDEAQL4PmQADjogCm8csoyc2HU5t/kVlv/zEMQC"
    "ArA+aAAGOiBY4xo4ZOF7r3UUnjll//MQxAQCsD5oAAY6IBk4SPR7b/ERyyxxjRz/8xDEBgK4"
    "PmgABjogFoS91nr5Bb+OWT6nU//zEsQIAxA+YAAOOiAuzQbXKhDDLHGGj/stef/zEMQJAog2"
    "aAAGOCGF1QAwh/1nowBgJg8I//MQxAsC6ELigUcAADKcKpBs8BUNQwLhmDf/8xDEDAToXrgB"
    "kBAAC+pS3wxznNWM2qrsoP/zEMQFAtBB1AHDAAEqTCmituyVTEFNRVVV"
)


def selftest() -> str:
    """Prove playback can work in this build, or raise saying why not.

    Run by ``edld.py --selftest``, which the release workflow runs against the
    binary on all three platforms.  Radio playback is otherwise only ever
    exercised by pressing Play, so a binary missing miniaudio's compiled half
    or its decoders would ship looking fine.  This decodes a clip through the
    same reader and decoder a station uses.  It needs no network and no
    audio device, so it can run on a CI runner that has neither.
    """
    import base64
    import io
    if _ma is None:
        raise RuntimeError(f"miniaudio unavailable ({_MA_IMPORT_ERROR})")

    class _Resp:
        headers: dict = {}
        def __init__(self, data: bytes) -> None:
            self._f = io.BytesIO(data)
        def read(self, n: int) -> bytes:
            return self._f.read(n)
        def close(self) -> None:
            pass

    source = IcySource(_Resp(base64.b64decode("".join(_SELFTEST_MP3))),
                       lambda _t: None, threading.Event())
    stream = _ma.stream_any(source, _ma.FileFormat.MP3,
                            output_format=_ma.SampleFormat.SIGNED16,
                            nchannels=_CHANNELS, sample_rate=_RATE,
                            frames_to_read=1024)
    frames = sum(len(chunk) for chunk in stream) // _CHANNELS
    if frames < _RATE // 10:
        raise RuntimeError(f"decoder produced {frames} frames from the test clip")
    return f"miniaudio {getattr(_ma, '__version__', '?')}, MP3 decode OK"


# ── Shared presentation ───────────────────────────────────────────────────────

def status_line(st: RadioStatus) -> str:
    """One-line state readout, identical in both front ends."""
    if st.state == UNAVAILABLE:
        return st.message
    if st.state == STOPPED:
        return "Stopped"
    if st.state == CONNECTING:
        return "Connecting…"
    if st.state == BUFFERING:
        return "Buffering…"
    if st.state == ERROR:
        return f"Error: {st.message}"
    return "Playing" + (f"  ·  {st.detail}" if st.detail else "")


def volume_label(st: RadioStatus) -> str:
    return "Muted" if st.muted else f"Vol {st.volume}%"


def _log(message: str) -> None:
    try:
        from core import debug
        debug.log(f"[radio] {message}", level="INFO")
    except Exception:
        pass


def _log_exception(message: str, exc: BaseException) -> None:
    try:
        from core import debug
        debug.exception(f"[radio] {message}", exc)
    except Exception:
        pass
