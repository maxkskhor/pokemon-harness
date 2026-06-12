from __future__ import annotations

import argparse

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


def main() -> None:
    parser = argparse.ArgumentParser(description="Internal setup helpers for pokemon-harness.")
    parser.add_argument("--create-bedroom-state", action="store_true")
    parser.add_argument("--rom", help="ROM filename in roms/ (default: backend's default ROM)")
    args = parser.parse_args()

    if args.create_bedroom_state:
        create_bedroom_state(rom=args.rom)
    else:
        parser.error("choose a setup action")


if __name__ == "__main__":
    main()
