"""Reusable elevated event session. All points use a 1920 x 1080 canvas."""
import argparse
import hashlib
from datetime import datetime, timezone
import msvcrt
import json
import os
from pathlib import Path
import sys
import time

CONTROLLER_VERSION = 2
CONTROLLER_ACTIONS = ("claim", "release", "status", "stop", "snapshot", "wait", "start_game", "navigate",
                      "treasure_steps", "treasure_action", "treasure_open", "map_locate", "plot", "camera", "physical",
                      "key", "move", "click", "drag", "scroll", "screen")
SCRIPT_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


class ControlRequestError(ValueError):
    pass


def check_control(request, owner):
    actions = request.get("actions") or [request]
    kinds = [a.get("action", a.get("type")) for a in actions]
    unknown = set(kinds) - set(CONTROLLER_ACTIONS)
    if unknown:
        raise ControlRequestError(f"Unsupported actions: {unknown}; controller version {CONTROLLER_VERSION}")
    if any(k in ("claim", "release") for k in kinds) and len(kinds) != 1:
        raise ControlRequestError("claim/release must be submitted alone")
    if all(k in ("status", "snapshot", "wait", "map_locate") for k in kinds):
        return owner
    candidate = request.get("owner")
    if not isinstance(candidate, str) or not candidate.strip():
        raise PermissionError("Input requires an owner; submit claim with the same owner first")
    if kinds == ["claim"] and owner is None:
        return candidate
    if owner != candidate:
        raise PermissionError(f"Control belongs to {owner!r}; claim after its release")
    return owner


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--root", required=True, help="March7thAssistant source directory")
parser.add_argument("--session", required=True, help="Session directory shared with session_request.py")
parser.add_argument("--status", action="store_true", help="Check the existing worker without elevation")
args = parser.parse_args()
SESSION = Path(args.session).resolve()
ROOT = Path(args.root).resolve()


def existing_worker():
    # Check the lock BEFORE requesting elevation. ready.json alone may be stale.
    lock_path = SESSION / "worker.lock"
    if not lock_path.exists():
        return None
    with lock_path.open("r+b") as probe:
        try:
            msvcrt.locking(probe.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            ready = SESSION / "ready.json"
            state = json.loads(ready.read_text(encoding="utf-8")) if ready.exists() else {}
            return {**state, "script_matches": state.get("controller", {}).get("script_sha256") == SCRIPT_SHA256, "status": "running" if state else "starting", "reused": True, "session": str(SESSION)}
        else:
            probe.seek(0)
            msvcrt.locking(probe.fileno(), msvcrt.LK_UNLCK, 1)
    return None


current = existing_worker()
if current or args.status:
    print(json.dumps(current or {"status": "stopped", "session": str(SESSION)}))
    raise SystemExit

os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
os.environ["MARCH7TH_CONFIG_READONLY"] = "1"
SESSION.mkdir(parents=True, exist_ok=True)
from utils.admin import is_user_admin, start_as_admin

if not is_user_admin():
    command = [sys.executable, str(Path(__file__).resolve()), "--root", str(ROOT), "--session", str(SESSION)]
    process = start_as_admin(command, show_cmd=0, cwd=str(ROOT))
    print(json.dumps({"status": "starting", "pid": process.pid, "session": str(SESSION)}))
    process.close()
    raise SystemExit

lock = (SESSION / "worker.lock").open("a+b")
lock.seek(0)
lock.write(b"0")
lock.flush()
lock.seek(0)
msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
(SESSION / "ready.json").unlink(missing_ok=True)
stream = (SESSION / "helper.log").open("a", encoding="utf-8", buffering=1)
sys.stdout = sys.stderr = stream

requests = SESSION / "requests"
responses = SESSION / "responses"
requests.mkdir(exist_ok=True)
responses.mkdir(exist_ok=True)
completed_requests = set()
# Do not replay unresolved input from an earlier worker after restart.
for previous in requests.glob("*.json"):
    result_file = responses / previous.stem / "result.json"
    if not result_file.exists():
        result_file.parent.mkdir(exist_ok=True)
        result_file.write_text(json.dumps({"status": "interrupted", "request": previous.stem,
            "error": "Previous worker ended; action outcome unknown. Observe before retrying."}), encoding="utf-8")
    completed_requests.add(previous.name)

from utils.dpi import configure_dpi_awareness
configure_dpi_awareness()
import numpy as np
from PySide6.QtWidgets import QApplication
from module.config import cfg
if not cfg.get_value("auto_update"):
    raise RuntimeError("首次使用请先在小助手图形界面阅读并确认免责声明")
from module.automation import auto
from module.ocr import ocr
from module.screen import screen
from tasks.game import ensure_game_ready
from tasks.tool.autoplot import AutoPlot

app = QApplication.instance() or QApplication([])
plot = AutoPlot(cfg.game_title_name)
plot.update_options({"auto_skip": True, "auto_click": True,
                     "auto_battle_detect_enable": True, "auto_phone_detect_enable": True})
plot_wanted = False
route_game = None
(SESSION / "stopped.json").unlink(missing_ok=True)
controller = {"version": CONTROLLER_VERSION, "actions": CONTROLLER_ACTIONS,
              "script_sha256": SCRIPT_SHA256, "started_at": datetime.now(timezone.utc).isoformat(),
              "script": str(Path(__file__).resolve())}
control_owner = None
last_request = None


def publish_state(phase="idle", active_request=None):
    state = {"pid": os.getpid(), "root": str(ROOT), "canvas": [1920, 1080], "controller": controller,
             "owner": control_owner, "phase": phase, "active_request": active_request,
             "last_request": last_request, "plot": plot_wanted}
    ready = SESSION / "ready.tmp"
    ready.write_text(json.dumps(state), encoding="utf-8")
    ready.replace(SESSION / "ready.json")
    return state


publish_state()


def wait(seconds):
    deadline = time.monotonic() + float(seconds)
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(min(.025, max(0, deadline - time.monotonic())))


def point(xy):
    # Absolute pointer actions refresh geometry once before the input batch.
    left, top, width, height = auto.screenshot_pos
    factor = auto.screenshot_scale_factor or 1
    return (round(left + xy[0] / 1920 * width / factor),
            round(top + xy[1] / 1080 * height / factor))


def observe(output, request):
    profile = {} if request.get("profile") else None
    total_started = time.perf_counter()
    started = time.perf_counter()
    auto.take_screenshot()
    if profile is not None:
        profile["screenshot_ms"] = round((time.perf_counter() - started) * 1000, 1)
    started = time.perf_counter()
    frame = auto.screenshot.convert("RGB").resize((1920, 1080))
    if profile is not None:
        profile["convert_resize_ms"] = round((time.perf_counter() - started) * 1000, 1)
    saved_image = {}
    if request.get("save_image", True):
        started = time.perf_counter()
        frame_path = output / "screen.png"
        frame.save(frame_path)
        saved_image["image"] = str(frame_path)
        if profile is not None:
            profile["png_ms"] = round((time.perf_counter() - started) * 1000, 1)
    region = request.get("ocr_region", [0, 0, 1920, 1080])
    left, top, right, bottom = region
    records = []
    if request.get("ocr", True):
        started = time.perf_counter()
        raw = ocr.run(np.asarray(frame.crop((left, top, right, bottom))))
        if profile is not None:
            profile["ocr_ms"] = round((time.perf_counter() - started) * 1000, 1)
        if isinstance(raw, str):
            raise RuntimeError(raw)
        for item in raw or []:
            item = dict(item)
            item["box"] = [[float(x) + left, float(y) + top] for x, y in item["box"]]
            records.append(item)
    text_path = output / "texts.json"
    started = time.perf_counter()
    text_path.write_text(json.dumps(records, ensure_ascii=False, default=lambda value: value.tolist()), encoding="utf-8")
    if profile is not None:
        profile["texts_write_ms"] = round((time.perf_counter() - started) * 1000, 1)
        profile["observe_ms"] = round((time.perf_counter() - total_started) * 1000, 1)
    result = {**saved_image, "text_path": str(text_path), "texts": [r["txt"] for r in records],
              "records": records, "canvas": [1920, 1080], "plot": plot_wanted}
    if profile is not None:
        result["profile_ms"] = profile
    return result


def get_route_game():
    global route_game
    if route_game is None:
        from tasks.exploration.treasure import TreasureGame
        route_game = TreasureGame(auto, screen, app.processEvents)
    return route_game


def execute(action):
    kind = action.get("action", action.get("type"))
    if kind == "start_game":
        from tasks.game import start_game
        start_game()
        if not ensure_game_ready():
            raise RuntimeError("Game startup did not produce a usable window")
        return {"game": "ready"}
    elif kind == "navigate":
        from utils.treasure_route import load_route, run_route
        route = load_route(ROOT / action["route"])
        started = time.monotonic()
        result = run_route(route, get_route_game(), auto.logger.info,
                           navigate_to=str(action["target"]))
        return {**result, "elapsed_seconds": round(time.monotonic() - started, 3)}
    elif kind == "map_locate":
        game = get_route_game()
        locator = game._map_locator({"image": str(ROOT / action["image"]),
                                     "metadata": str(ROOT / action["metadata"])})
        return game._locate_map(locator, marker_ids=action.get("markers", []),
                                require_player=action.get("require_player", True))
    elif kind in ("treasure_steps", "treasure_action", "treasure_open"):
        from utils.treasure_route import load_route, _steps
        import ctypes
        game = get_route_game()
        scans = []
        def scan():
            held = [name for name, vk in (("shift", 16), ("w", 87), ("a", 65), ("s", 83), ("d", 68))
                    if ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000]
            started = time.perf_counter()
            status = game.open_chest()
            scans.append({"held_keys": held, "status": status,
                          "seconds": round(time.perf_counter() - started, 3)})
            return status
        started = time.perf_counter()
        if kind == "treasure_open":
            return {"chest_status": game.open_chest(), "elapsed_seconds": round(time.perf_counter() - started, 3)}
        if kind == "treasure_action":
            steps = _steps([action["step"]], ROOT, setup=True)
        else:
            route = load_route(ROOT / action["route"])
            steps = route["setup"] if action.get("part") == "setup" else route["chests"][int(action.get("chest", 0))]["steps"]
            steps = steps[int(action.get("start", 0)):action.get("end")]
        outcomes = []
        for step in steps:
            auto.logger.info(f"LIVE_TREASURE_STEP {step['type']}")
            outcome = game.execute(step, after_segment=scan if action.get("scan") else None)
            outcomes.append({"type": step["type"], "status": outcome})
            if outcome == "unconfirmed":
                break
        return {"steps": outcomes, "scans": scans, "elapsed_seconds": round(time.perf_counter() - started, 3)}
    elif kind == "camera":
        import ctypes
        dx, dy = action.get("delta", [0, 0])
        steps = max(1, int(action.get("steps", 10)))
        for _ in range(steps):
            ctypes.windll.user32.mouse_event(1, round(dx / steps), round(dy / steps), 0, 0)
            time.sleep(.02)
    elif kind == "physical":
        import pyautogui
        keys = str(action.get("key", "")).split("+") if action.get("key") else []
        button = action.get("button")
        try:
            for key in keys:
                pyautogui.keyDown(key)
            if button:
                pyautogui.mouseDown(button=button)
            time.sleep(float(action.get("seconds", .2)))
        finally:
            if button:
                pyautogui.mouseUp(button=button)
            for key in reversed(keys):
                pyautogui.keyUp(key)
    elif kind in ("key", "move") and "key" in action:
        keys = str(action["key"]).split("+")
        try:
            for key in keys:
                if auto.press_key_down(key) is False:
                    raise RuntimeError("Key down interrupted")
            time.sleep(float(action.get("seconds", .2)))
        finally:
            for key in reversed(keys):
                auto.press_key_up(key)
    elif kind == "click":
        x, y = point(action["point"])
        if action.get("button", "left") == "right":
            import pyautogui
            try:
                pyautogui.mouseDown(x, y, button="right")
                time.sleep(float(action.get("seconds", .12)))
            finally:
                pyautogui.mouseUp(button="right")
            if action.get("wait", 0):
                wait(action["wait"])
            return
        try:
            if auto.mouse_down(x, y) is False:
                raise RuntimeError("Mouse down interrupted")
            time.sleep(float(action.get("seconds", .12)))
        finally:
            auto.mouse_up()
    elif kind == "move":
        auto.mouse_move(*point(action["point"]))
    elif kind == "drag":
        if auto.mouse_drag(*point(action["start"]), *point(action["end"]), float(action.get("seconds", .5))) is False:
            raise RuntimeError("Drag interrupted")
    elif kind == "scroll":
        if "point" in action:
            auto.mouse_move(*point(action["point"]))
        auto.mouse_scroll(int(action.get("count", 1)), int(action.get("direction", -1)), False)
    elif kind == "screen":
        if action["target"] in ("main", "map"):
            get_route_game()._navigation_screen(action["target"])
        else:
            screen.change_to(action["target"])
    elif kind in ("snapshot", "wait"):
        pass
    else:
        raise ValueError(f"Unknown action: {kind}")
    if action.get("wait", 0) or kind == "wait":
        wait(action.get("wait", action.get("seconds", 0)))


try:
    running = True
    pending = []
    request_stamp = None
    while running:
        app.processEvents()
        if not pending:
            # The client atomically adds immutable request files. Only rescan on a directory change.
            stamp = requests.stat().st_mtime_ns
            if stamp != request_stamp:
                request_stamp = stamp
                pending = sorted((p for p in requests.glob("*.json") if p.name not in completed_requests),
                                 key=lambda p: int(p.stem), reverse=True)
        if not pending:
            time.sleep(.05)
            continue
        path = pending.pop()
        output = responses / path.stem
        output.mkdir(exist_ok=True)
        publish_state("busy", path.stem)
        result = {"status": "ok", "request": path.stem, "controller": controller}
        request = {}
        control_only = True
        capture_failed = False
        profile = None
        balloon_before = getattr(route_game, "last_balloon_result", None)
        request_started = time.perf_counter()
        try:
            request = json.loads(path.read_text(encoding="utf-8-sig"))
            control_owner = check_control(request, control_owner)
            profile = {} if request.get("profile") else None
            actions = request.get("actions", [request])
            if actions is None:
                actions = [request]
            manual = any(a.get("action", a.get("type")) in ("key", "click", "drag", "move", "scroll", "screen", "camera", "physical", "navigate", "start_game", "treasure_steps", "treasure_action", "treasure_open") for a in actions)
            control_only = all(a.get("action", a.get("type")) in ("status", "stop", "claim", "release") for a in actions)
            starting_game = any(a.get("action", a.get("type")) == "start_game" for a in actions)
            if starting_game and len(actions) != 1:
                raise ValueError("start_game must be submitted alone; inspect startup before sending input")
            if manual:
                plot.stop()
                # Manual control stays in effect until plot is explicitly enabled again.
                plot_wanted = False
            if not control_only and not starting_game:
                started = time.perf_counter()
                game_ready = ensure_game_ready()
                if profile is not None:
                    profile["ensure_game_ready_ms"] = round((time.perf_counter() - started) * 1000, 1)
                if not game_ready:
                    raise RuntimeError("Game window unavailable")
            needs_geometry = any(a.get("action", a.get("type")) in ("click", "drag")
                                 or (a.get("action", a.get("type")) in ("move", "scroll") and "point" in a)
                                 for a in actions)
            if needs_geometry:
                try:
                    started = time.perf_counter()
                    auto.take_screenshot()
                    if profile is not None:
                        profile["input_geometry_screenshot_ms"] = round((time.perf_counter() - started) * 1000, 1)
                except Exception:
                    capture_failed = True
                    raise
            started = time.perf_counter()
            for action in actions:
                kind = action.get("action", action.get("type"))
                if kind == "claim":
                    result["owner"] = control_owner
                    continue
                if kind == "release":
                    plot_wanted = False
                    plot.stop()
                    auto.input_handler.release_all()
                    control_owner = None
                    result.update(owner=None, input_released=True)
                    continue
                if kind == "stop":
                    plot_wanted = False
                    plot.stop()
                    running = False
                    break
                if kind == "status":
                    result.update(pid=os.getpid(), root=str(ROOT), plot=plot_wanted, owner=control_owner,
                                  last_request=last_request)
                    continue
                if kind == "plot":
                    plot_wanted = bool(action.get("enabled", True))
                    plot.update_options(action.get("options", {}))
                    if not manual:
                        plot.start() if plot_wanted else plot.stop()
                else:
                    action_result = execute(action)
                    if action_result is not None:
                        result.setdefault("actions", []).append({"action": kind, **action_result})
            if profile is not None:
                profile["actions_ms"] = round((time.perf_counter() - started) * 1000, 1)
            if manual and plot_wanted and running:
                plot.start()
            # Observations and control queries do not need an extra input-settling delay.
            started = time.perf_counter()
            wait(request.get("settle", .3 if manual and running else 0))
            if profile is not None:
                profile["settle_ms"] = round((time.perf_counter() - started) * 1000, 1)
            if running and not control_only and request.get("observe", True):
                try:
                    result.update(observe(output, request))
                except Exception:
                    capture_failed = True
                    raise
        except (PermissionError, ControlRequestError) as exc:
            result.update(status="rejected", error=str(exc), owner=control_owner)
        except Exception as exc:
            plot.stop()
            plot_wanted = False
            auto.input_handler.release_all()
            result.update(status="error", error=str(exc))
            balloon_result = getattr(route_game, "last_balloon_result", None)
            if balloon_result is not None and balloon_result is not balloon_before:
                result["balloon"] = balloon_result
            if not control_only and not capture_failed and request.get("observe", True):
                try:
                    result.update(observe(output, {"ocr": False}))
                except Exception as capture_error:
                    result["capture_error"] = str(capture_error)
        if profile is not None:
            result["profile_ms"] = {**profile, **result.get("profile_ms", {}),
                                     "request_ms": round((time.perf_counter() - request_started) * 1000, 1)}
        result["owner"] = control_owner
        temporary_result = output / "result.tmp"
        temporary_result.write_text(json.dumps(result, ensure_ascii=False, default=lambda value: value.tolist()), encoding="utf-8")
        temporary_result.replace(output / "result.json")
        completed_requests.add(path.name)
        last_request = {"request": path.stem, "status": result["status"]}
        publish_state()
finally:
    plot.stop()
    auto.close_input()
    (SESSION / "ready.json").unlink(missing_ok=True)
    (SESSION / "stopped.json").write_text(json.dumps({"pid": os.getpid(), "controller": controller, "owner": None, "input_released": True, "last_request": last_request}), encoding="utf-8")
    lock.close()
