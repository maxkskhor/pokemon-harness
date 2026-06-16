from __future__ import annotations

import argparse

from harness.examples.gym_agent import astar
from harness.client import PokemonEnvClient, press, wait

INTRO_STEPS = [
    # Boot to title screen (Pokemon Red logo) then open the start menu
    wait(1700), press("A", 12), wait(240),
    # NEW GAME is the first menu option (no existing battery save)
    press("A", 12), wait(300),

    # Advance through all 13 of Oak's intro dialogue boxes
    press("A", 12), wait(200),
    press("A", 12), wait(200),
    press("A", 12), wait(200),
    press("A", 12), wait(200),
    press("A", 12), wait(200),
    press("A", 12), wait(200),
    press("A", 12), wait(200),
    press("A", 12), wait(200),
    press("A", 12), wait(200),
    press("A", 12), wait(200),
    press("A", 12), wait(200),
    press("A", 12), wait(200),
    press("A", 12), wait(300),  # 13th press; naming preset screen now open

    # Choose preset player name RED. Cursor starts on NEW NAME; one DOWN moves to RED.
    press("DOWN", 12), wait(200),
    press("A", 12), wait(400),

    # Advance through the 6 post-naming dialogue boxes.
    press("A", 12), wait(200),
    press("A", 12), wait(200),
    press("A", 12), wait(200),
    press("A", 12), wait(200),
    press("A", 12), wait(200),
    press("A", 12), wait(300),  # 6th press; rival naming preset screen now open

    # Choose preset rival name BLUE. Cursor starts on NEW NAME; one DOWN moves to BLUE.
    press("DOWN", 12), wait(200),
    press("A", 12), wait(400),

    # Advance through post-rival dialogue, bedroom fade-in, and Mom's greeting
    press("A", 12), wait(220),
    press("A", 12), wait(220),
    press("A", 12), wait(220),
    press("A", 12), wait(220),
    press("A", 12), wait(220),
    press("A", 12), wait(220),
    press("A", 12), wait(220),
    press("A", 12), wait(220),
    press("A", 12), wait(220),
    press("A", 12), wait(220),
    press("A", 12), wait(220),
    press("A", 12), wait(220),
    wait(2000),  # Let the bedroom fully load and any animations settle
]

def _frlg_type(moves: list[str]) -> list[dict]:
    """Cursor moves + A on the FRLG naming keyboard, with settle waits."""
    steps: list[dict] = []
    for move in moves:
        steps += [press(move, 8), wait(40)]
    steps += [press("A", 8), wait(60)]
    return steps


# Pokemon Fire Red new-game intro. The naming keyboard's cursor starts on 'A'
# and never moves while A is mashed, so any stray typed letters are cleared
# with B presses and names are typed with known cursor paths:
#   row 0: A B C D E F .   row 1: G H I J K L ,
#   row 2: M N O P Q R S   row 3: T U V W X Y Z
FRLG_INTRO_STEPS = (
    # Boot to title, then through the main menu / controls help screen.
    [wait(1800), press("A", 8), wait(240), press("A", 8), wait(240),
     press("A", 8), wait(300)]
    # Oak's speech + gender select (A picks BOY) up to the player naming
    # keyboard. Extra A presses at the keyboard just type 'A's (7 max).
    + [step for _ in range(34) for step in (press("A", 8), wait(180))]
    # Clear any typed letters (7 max; an extra B on an empty field would BACK
    # out of the keyboard). Cursor is still on 'A'. Type RED.
    + [step for _ in range(7) for step in (press("B", 8), wait(40))]
    + _frlg_type(["DOWN", "DOWN", "RIGHT", "RIGHT", "RIGHT", "RIGHT", "RIGHT"])  # R
    + _frlg_type(["UP", "UP", "LEFT"])                                           # E
    + _frlg_type(["LEFT"])                                                       # D
    + [press("START", 8), wait(80), press("A", 8), wait(300)]
    # Dialogue up to the rival naming keyboard.
    + [step for _ in range(10) for step in (press("A", 8), wait(180))]
    # Clear and type BLUE (cursor back on 'A' after clearing).
    + [step for _ in range(7) for step in (press("B", 8), wait(40))]
    + _frlg_type(["RIGHT"])                                                      # B
    + _frlg_type(["DOWN", "RIGHT", "RIGHT", "RIGHT", "RIGHT"])                   # L
    + _frlg_type(["DOWN", "DOWN", "LEFT", "LEFT", "LEFT", "LEFT"])               # U
    + _frlg_type(["UP", "UP", "UP", "RIGHT", "RIGHT", "RIGHT"])                  # E
    + [press("START", 8), wait(80), press("A", 8), wait(300)]
    # Remaining dialogue, shrink animation, bedroom fade-in.
    + [step for _ in range(12) for step in (press("A", 8), wait(220))]
    + [wait(900)]
)

_DIRECTIONS = ["RIGHT", "LEFT", "DOWN", "UP"]


def _move_to(client: PokemonEnvClient, x: int, y: int) -> None:
    """Navigate to a coordinate with learned-wall A* for setup scripts."""
    walls: set[str] = set()
    for _ in range(80):
        px, py = _position(client)
        if (px, py) == (x, y):
            return
        status = client.get_state().get("status") or {}
        avoid = frozenset(
            (e["x"], e["y"]) for e in (status.get("exits") or [])
            if isinstance(e.get("x"), int) and isinstance(e.get("y"), int)
        )
        path = astar((px, py), (x, y), walls, avoid=avoid)
        if not path:
            raise RuntimeError(f"no path to ({x},{y}) from ({px},{py})")
        progressed = False
        before_map = _map_id(client)
        for direction in path:
            px, py = _position(client)
            client.press_sequence([press(direction, 16), wait(60)])
            nx, ny = _position(client)
            if (nx, ny) == (px, py) and _map_id(client) == before_map:
                # First press may only turn the player.
                client.press_sequence([press(direction, 16), wait(60)])
                nx, ny = _position(client)
            if (nx, ny) == (px, py) and _map_id(client) == before_map:
                walls.add(f"{px},{py},{direction}")
                break
            progressed = True
            if _map_id(client) != before_map or (nx, ny) == (x, y):
                return
        if not progressed:
            continue
    raise RuntimeError(f"timed out navigating to ({x},{y})")


def _position(client: PokemonEnvClient) -> tuple[int, int]:
    state = client.get_state()
    pokemon = state.get("pokemon", {})
    status = state.get("status") or {}
    position = status.get("position") if isinstance(status.get("position"), dict) else {}
    px = pokemon.get("x") if isinstance(pokemon.get("x"), int) else position.get("x")
    py = pokemon.get("y") if isinstance(pokemon.get("y"), int) else position.get("y")
    if not isinstance(px, int) or not isinstance(py, int):
        raise RuntimeError("cannot read player position")
    return px, py


def _map_id(client: PokemonEnvClient) -> int | None:
    return (client.get_state().get("status") or {}).get("map_id")


def _walk_onto_exit(client: PokemonEnvClient) -> None:
    status = client.get_state().get("status") or {}
    before_map = status.get("map_id")
    exits = status.get("exits") or []
    if not exits:
        raise RuntimeError(f"no exits on current map {before_map}")
    for exit_tile in exits:
        _move_to(client, int(exit_tile["x"]), int(exit_tile["y"]))
        if _map_id(client) != before_map:
            return
        for direction in ("DOWN", "LEFT", "RIGHT", "UP"):
            client.press_sequence([press(direction, 16), wait(120)])
            if _map_id(client) != before_map:
                return
            opposite = {"DOWN": "UP", "UP": "DOWN", "LEFT": "RIGHT", "RIGHT": "LEFT"}[direction]
            client.press_sequence([press(opposite, 16), wait(120)])
    raise RuntimeError(f"failed to trigger exit on map {before_map}")


def _advance_until_movable(client: PokemonEnvClient, *, button: str = "A", attempts: int = 30) -> None:
    for _ in range(attempts):
        if _can_move(client):
            return
        client.press_sequence([press(button, 8), wait(180)])
    raise RuntimeError("player did not regain movement")


def _advance_until_map(client: PokemonEnvClient, map_id: int, *, attempts: int = 60) -> None:
    for _ in range(attempts):
        if _map_id(client) == map_id:
            return
        client.press_sequence([press("A", 8), wait(240)])
    raise RuntimeError(f"did not reach map {map_id}")


def _clear_frlg_rival_scene_and_exit_lab(client: PokemonEnvClient) -> None:
    """Trigger Blue's post-starter battle, clear it, and leave Oak's lab."""
    try:
        _move_to(client, 6, 12)
    except RuntimeError as exc:
        px, py = _position(client)
        if _map_id(client) != 1027 or (px, py) != (6, 8):
            raise
        print(f"Rival scene interrupted lab exit as expected: {exc}")

    # A-only safely advances the dialogue, picks the first battle action, and clears
    # the post-battle text. Live probing confirmed this returns Squirtle to free roam.
    for _ in range(120):
        client.press_sequence([press("A", 8), wait(240)])

    for _ in range(8):
        if _map_id(client) != 1027:
            return
        client.press_sequence([press("DOWN", 16), wait(120), press("DOWN", 16), wait(120)])
    if _map_id(client) == 1027:
        _walk_onto_exit(client)


def _can_move(client: PokemonEnvClient) -> bool:
    """Return True if Red can move in at least one direction."""
    before = client.get_state().get("pokemon", {})
    bx, by = before.get("x"), before.get("y")
    for btn in _DIRECTIONS:
        client.press_sequence([press(btn, 20), wait(60)])
        after = client.get_state().get("pokemon", {})
        if after.get("x") != bx or after.get("y") != by:
            opposite = {"RIGHT": "LEFT", "LEFT": "RIGHT", "DOWN": "UP", "UP": "DOWN"}[btn]
            client.press_sequence([press(opposite, 20), wait(60)])
            return True
    return False


def create_bedroom_state(rom: str | None = None) -> None:
    # Non-default ROMs get a ROM-scoped shared state (e.g. bedroom-pokeblue) that
    # the env resolves automatically when an agent loads "bedroom".
    state_name = "bedroom" if rom is None else f"bedroom-{rom.rsplit('.', 1)[0]}"
    print(f"Setting up '{state_name}' save state...")
    is_gba = bool(rom) and rom.endswith(".gba")
    client = PokemonEnvClient(timeout=600.0)
    try:
        client.wait_for_server(timeout=20)
        client.start_run("shared", rom_path=f"roms/{rom}" if rom else None)
        client.set_speed("max")
        print("Running intro at max speed...")
        client.press_sequence(FRLG_INTRO_STEPS if is_gba else INTRO_STEPS)
        client.set_speed("paused")

        print("Verifying free-roaming movement...")
        # Close any menu the trailing intro presses may have opened (e.g. the
        # FRLG bag); B is a no-op during free roam.
        client.press_sequence([press("B", 8), wait(120)] * 4)
        # Retry key: B backs out of FRLG menus; Gen 1 needs A for Mom's dialogue.
        retry_button = "B" if is_gba else "A"
        for attempt in range(20):
            if _can_move(client):
                print(f"Movement confirmed (attempt {attempt + 1})")
                break
            client.press_sequence([press(retry_button, 12), wait(150)])
        else:
            print("WARNING: could not verify movement after 20 attempts; saving anyway")

        client.save_state(state_name)
        state = client.get_state()
        pokemon = state.get("pokemon", {})
        status = state.get("status") or {}
        print(
            f"Saved '{state_name}' at frame {state['frame']} - "
            f"map={pokemon.get('map_id')} x={pokemon.get('x')} y={pokemon.get('y')} "
            f"player={status.get('player_name')}"
        )
        if is_gba and status.get("player_name") != "RED":
            print(
                "WARNING: player name is not RED — the intro script drifted at the "
                "naming keyboard. The state is still playable; names are cosmetic."
            )
        client.stop_run()
    finally:
        client.close()


def create_post_starter_state(rom: str | None = None) -> None:
    if rom != "pokefirered.gba":
        raise RuntimeError("--create-post-starter-state currently supports --rom pokefirered.gba")

    state_name = f"post-starter-{rom.rsplit('.', 1)[0]}"
    print(f"Setting up '{state_name}' save state...")
    client = PokemonEnvClient(timeout=600.0)
    try:
        client.wait_for_server(timeout=20)
        client.start_run("shared", rom_path=f"roms/{rom}")
        client.load_state(f"bedroom-{rom.rsplit('.', 1)[0]}")
        client.set_speed("max")

        print("Walking from bedroom to Pallet Town...")
        _walk_onto_exit(client)  # bedroom stairs
        _advance_until_movable(client, button="B")
        _walk_onto_exit(client)  # front door
        _advance_until_movable(client, button="B")

        print("Triggering Oak and entering the lab...")
        _move_to(client, 12, 1)
        _advance_until_map(client, 1027)
        client.press_sequence([step for _ in range(30) for step in (press("A", 8), wait(180))])
        _advance_until_movable(client, button="A", attempts=60)

        state = client.get_state()
        status = state.get("status") or {}
        if status.get("map_id") != 1027:
            raise RuntimeError(f"expected Oak's Lab map 1027, got {status.get('map_id')}")

        print("Taking the middle starter and clearing the rival battle...")
        # Stand below the middle pokeball, face it, and advance the Fire Red starter flow.
        client.press_sequence(
            [press("RIGHT", 16), wait(80)]
            + [press("DOWN", 16), wait(80)] * 2
            + [press("RIGHT", 16), wait(80)] * 2
            + [press("UP", 16), wait(80)]
        )
        px, py = _position(client)
        if (px, py) != (9, 5):
            raise RuntimeError(f"expected to stand beside middle starter at (9,5), got ({px},{py})")
        for _ in range(40):
            client.press_sequence([press("A", 8), wait(300)])
            party = (client.get_state().get("status") or {}).get("party") or []
            if any((mon.get("level") or 0) >= 1 for mon in party):
                break
        else:
            raise RuntimeError("starter was not acquired")

        _advance_until_movable(client, button="A", attempts=60)
        # Blue intercepts only when you walk toward the exit. Clear that scene and save
        # the shared checkpoint outside the lab so benchmark runs resume at true free roam.
        _clear_frlg_rival_scene_and_exit_lab(client)
        if _map_id(client) != 768:
            raise RuntimeError(f"expected Pallet Town after leaving lab, got map {_map_id(client)}")

        client.save_state(state_name)
        state = client.get_state()
        pokemon = state.get("pokemon", {})
        status = state.get("status") or {}
        print(
            f"Saved '{state_name}' at frame {state['frame']} - "
            f"map={pokemon.get('map_id')} x={pokemon.get('x')} y={pokemon.get('y')} "
            f"party={[(m.get('nickname'), m.get('level')) for m in (status.get('party') or [])]}"
        )
        client.stop_run()
    finally:
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Internal setup helpers for pokemon-harness.")
    parser.add_argument("--create-bedroom-state", action="store_true")
    parser.add_argument("--create-post-starter-state", action="store_true")
    parser.add_argument("--rom", help="ROM filename in roms/ (default: backend's default ROM)")
    args = parser.parse_args()

    if args.create_bedroom_state:
        create_bedroom_state(rom=args.rom)
    elif args.create_post_starter_state:
        create_post_starter_state(rom=args.rom)
    else:
        parser.error("choose a setup action")


if __name__ == "__main__":
    main()
