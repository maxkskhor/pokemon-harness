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


def create_bedroom_state() -> None:
    print("Setting up 'bedroom' save state...")
    client = PokemonEnvClient()
    try:
        client.wait_for_server(timeout=20)
        client.start_run("shared")
        client.set_speed("max")
        print("Running intro at max speed...")
        client.press_sequence(INTRO_STEPS)
        client.set_speed("paused")

        print("Verifying free-roaming movement...")
        for attempt in range(20):
            if _can_move(client):
                print(f"Movement confirmed (attempt {attempt + 1})")
                break
            client.press_sequence([press("A", 12), wait(150)])
        else:
            print("WARNING: could not verify movement after 20 attempts; saving anyway")

        client.save_state("bedroom")
        state = client.get_state()
        pokemon = state.get("pokemon", {})
        print(
            f"Saved 'bedroom' at frame {state['frame']} - "
            f"map={pokemon.get('map_id')} x={pokemon.get('x')} y={pokemon.get('y')}"
        )
        client.stop_run()
    finally:
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Internal setup helpers for pokemon-harness.")
    parser.add_argument("--create-bedroom-state", action="store_true")
    args = parser.parse_args()

    if args.create_bedroom_state:
        create_bedroom_state()
    else:
        parser.error("choose a setup action")


if __name__ == "__main__":
    main()
