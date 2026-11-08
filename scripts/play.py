"""Play the Cyberpunk TCG yourself against the bot, in your browser.

    python scripts/play.py                  # opens http://127.0.0.1:8765
    python scripts/play.py --port 9000 --no-browser
    python scripts/play.py --prefetch-images  # download all card pictures once, then exit

Only the Python standard library is needed. Card pictures come from the links in
data/card_images.json: each one is downloaded the first time it's shown and kept
in .card_art/ next to this repo, so later games work offline. Run with --no-images
to play with text-only cards.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cpbot import default_db, random_deck  # noqa: E402
from cpbot.agents import EagerRandomAgent  # noqa: E402
from cpbot.play import IMAGES_FILE, SAMPLE_DECK, Match, deck_summary, parse_decklist  # noqa: E402
from cpbot.search import ISMCTSAgent  # noqa: E402

PAGE = ROOT / "cpbot" / "play.html"
ART_DIR = ROOT / ".card_art"
REPLAY_DIR = ROOT / "games" / "played"      # every game you play is saved here
USER_AGENT = "cptcg-sim-research/0.1 (personal deck-testing project)"

# Bot strengths: the search agent with a time budget per decision. It guesses your
# hidden cards from what you have revealed (infer_rival) instead of using your decklist.
BOTS = {
    "easy": ("Easy bot (random)", lambda seed: EagerRandomAgent(seed)),
    "quick": ("Bot (0.5 s a move)", lambda seed: ISMCTSAgent(seconds=0.5, seed=seed, infer_rival=True)),
    "normal": ("Bot (2 s a move)", lambda seed: ISMCTSAgent(seconds=2.0, seed=seed, infer_rival=True)),
    "strong": ("Bot (5 s a move)", lambda seed: ISMCTSAgent(seconds=5.0, seed=seed, infer_rival=True)),
}

db = default_db()
IMAGES = json.loads(IMAGES_FILE.read_text(encoding="utf-8")) if IMAGES_FILE.exists() else {}
state = {"match": None, "images": True, "bot_thread": None, "server": None}
_art_locks: dict = {}
_art_failed: dict = {}                                   # card id -> time of the last failed download
_art_lock = threading.Lock()


# --------------------------------------------------------------- pictures
# The game's logo, shown on face-down cards when you haven't supplied a card back.
LOGO_URL = "https://cyberpunktcg.com/images/logos/cyberpunk-tcg-logo-yellow.webp"
EXTRA = {"_logo": {"url": LOGO_URL}}


def back_path() -> Path | None:
    """Your own card-back picture: --card-back, or .card_art/card-back.png (.jpg, .webp)."""
    if state.get("back"):
        p = Path(state["back"])
        return p if p.exists() else None
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        p = ART_DIR / f"card-back{ext}"
        if p.exists():
            return p
    return None


def art_path(card_id: str) -> Path | None:
    """The local copy of a card picture, downloading it the first time."""
    if card_id == "_back":
        return back_path()
    info = IMAGES.get(card_id) or EXTRA.get(card_id)
    if not info:
        return None
    url = info["url"]
    ext = Path(urlparse(url).path).suffix or ".webp"
    path = ART_DIR / f"{card_id}{ext}"
    if path.exists():
        return path
    if time.time() - _art_failed.get(card_id, -1e9) < 120:
        raise OSError("download failed recently; will retry in a couple of minutes")
    with _art_lock:
        lock = _art_locks.setdefault(card_id, threading.Lock())
    with lock:
        if path.exists():
            return path
        ART_DIR.mkdir(exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                data = r.read()
        except Exception:
            _art_failed[card_id] = time.time()
            raise
        tmp = path.with_suffix(path.suffix + ".part")
        tmp.write_bytes(data)
        tmp.replace(path)
    return path


def prefetch():
    todo = [c for c in IMAGES if art_path_cached(c) is None]
    print(f"{len(IMAGES) - len(todo)} pictures already here, downloading {len(todo)}")
    for i, cid in enumerate(todo, 1):
        try:
            art_path(cid)
        except Exception as e:  # noqa: BLE001
            print(f"  {cid}: {e}")
        if i % 20 == 0:
            print(f"  {i}/{len(todo)}")
        time.sleep(0.5)                                  # be polite to the host
    try:
        art_path("_logo")
    except Exception as e:  # noqa: BLE001
        print(f"  logo: {e}")
    print("done")


def art_path_cached(card_id):
    info = IMAGES.get(card_id)
    if not info:
        return None
    ext = Path(urlparse(info["url"]).path).suffix or ".webp"
    p = ART_DIR / f"{card_id}{ext}"
    return p if p.exists() else None


# ------------------------------------------------------------------ games
def make_deck(spec, rng):
    spec = spec or {"kind": "random"}
    if spec.get("kind") == "sample":
        return parse_decklist(SAMPLE_DECK, db)
    if spec.get("kind") == "text":
        return parse_decklist(spec.get("text", ""), db)
    return random_deck(rng, db)


def new_game(body):
    seed = body.get("seed")
    seed = random.randrange(1_000_000) if seed in (None, "") else int(seed)
    rng = random.Random(seed)
    you = make_deck(body.get("you"), rng)
    bot_deck = make_deck(body.get("bot"), rng)
    level = body.get("level", "normal")
    name, make = BOTS.get(level, BOTS["normal"])
    m = Match(you, bot_deck, make(seed + 1), seed=seed, db=db, bot_name="Bot")
    m.level_name = name
    m.deck_lists = [deck_summary(you, db), deck_summary(bot_deck, db)]
    m.replay_path = REPLAY_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}-seed{seed}.json"
    m.saved = None
    state["match"] = m
    start_bot(m)
    return m


def start_bot(m: Match):
    """Run the bot in the background so the page can show its moves as they happen."""
    if m.g.over or m.g.decision.player != 1 or m.thinking:
        return

    gen = m.gen

    def run():
        try:
            m.run_bot(gen=gen)
        except Exception:  # noqa: BLE001
            m.error = traceback.format_exc()
            traceback.print_exc()
        finally:
            if m.gen == gen:                             # an undo may have moved on already
                m.thinking = False

    m.thinking = True
    t = threading.Thread(target=run, daemon=True)
    state["bot_thread"] = t
    t.start()


def save_replay(m: Match):
    """Keep games/played/<time>-seed<seed>.json up to date (and an .html replay page
    once the game is over), so a game can be looked at move by move afterwards."""
    path = getattr(m, "replay_path", None)
    if path is None:
        return
    rec = m.record()
    key = (len(rec["choices"]), rec["winner"])
    if key == m.saved:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rec), encoding="utf-8")
        if rec["winner"] is not None:
            from cpbot.watch import replay
            page = replay(rec, db).html(title=f"Your game, seed {rec['seed']}")
            path.with_suffix(".html").write_text(page, encoding="utf-8")
        m.saved = key
    except Exception:  # noqa: BLE001  (a failed save must never stop the game)
        traceback.print_exc()


def view():
    m = state["match"]
    if m is None:
        return {"match": None, "images": state["images"], "card_back": back_path() is not None}
    save_replay(m)
    v = m.view()
    v["match"] = True
    v["seed"] = m.seed
    v["level"] = m.level_name
    v["decks"] = m.deck_lists
    v["images"] = state["images"] and bool(IMAGES)
    v["card_back"] = back_path() is not None
    return v


# ----------------------------------------------------------------- server
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body: bytes, ctype, cache=False):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "max-age=86400" if cache else "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj).encode("utf-8"), "application/json")

    def do_GET(self):  # noqa: N802
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        elif path == "/api/state":
            self._json(view())
        elif path == "/api/sample_deck":
            self._json({"text": SAMPLE_DECK})
        elif path.startswith("/art/"):
            cid = path[len("/art/"):]
            if not state["images"]:
                return self._send(404, b"", "text/plain")
            try:
                p = art_path(cid)
            except Exception as e:  # noqa: BLE001
                return self._send(502, str(e).encode(), "text/plain")
            if p is None:
                return self._send(404, b"", "text/plain")
            ctype = {".webp": "image/webp", ".png": "image/png", ".jpg": "image/jpeg",
                     ".jpeg": "image/jpeg"}.get(p.suffix.lower(), "application/octet-stream")
            self._send(200, p.read_bytes(), ctype, cache=True)
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):  # noqa: N802
        path = urlparse(self.path).path
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return self._json({"error": "bad request"}, 400)
        try:
            if path == "/api/new":
                new_game(body)
            elif path == "/api/act":
                m = state["match"]
                if m is None:
                    raise ValueError("no game running")
                m.choose(int(body["i"]))
                start_bot(m)
            elif path == "/api/quit":
                self._json({"ok": True})
                print("Quit from the page.")
                threading.Thread(target=state["server"].shutdown, daemon=True).start()
                return
            elif path in ("/api/undo", "/api/resign"):
                m = state["match"]
                if m is None:
                    raise ValueError("no game running")
                m.undo() if path == "/api/undo" else m.resign()
            elif path == "/api/check_deck":
                d = parse_decklist(body.get("text", ""), db)
                return self._json({"ok": True, "deck": deck_summary(d, db)})
            else:
                return self._json({"error": "not found"}, 404)
        except ValueError as e:
            return self._json({"error": str(e)}, 400)
        self._json(view())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--no-images", action="store_true", help="text-only cards; nothing is downloaded")
    ap.add_argument("--card-back", default=None, help="a picture to use for face-down cards")
    ap.add_argument("--art-dir", default=None, help="where card pictures are kept (default .card_art/)")
    ap.add_argument("--prefetch-images", action="store_true", help="download every card picture, then exit")
    a = ap.parse_args()
    global ART_DIR
    if a.art_dir:
        ART_DIR = Path(a.art_dir)
    state["back"] = a.card_back
    if a.prefetch_images:
        prefetch()
        return
    state["images"] = not a.no_images
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    url = f"http://{a.host}:{a.port}/"
    print(f"Playing at {url}  (Ctrl+C to stop)")
    if not a.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    # Serve from a worker thread and keep the main thread in short sleeps: on Windows,
    # Ctrl+C isn't delivered while the main thread is blocked inside serve_forever().
    state["server"] = srv
    worker = threading.Thread(target=srv.serve_forever, daemon=True)
    worker.start()
    try:
        while worker.is_alive():
            time.sleep(0.25)
    except KeyboardInterrupt:
        pass
    srv.shutdown()
    srv.server_close()
    print("\nStopped.")


if __name__ == "__main__":
    main()
