from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from typing import Protocol

from PIL import Image, ImageDraw

from env.models import Button


SCREEN_WIDTH = 160
SCREEN_HEIGHT = 144

BUTTON_TO_PYBOY = {
    "A": "a",
    "B": "b",
    "START": "start",
    "SELECT": "select",
    "UP": "up",
    "DOWN": "down",
    "LEFT": "left",
    "RIGHT": "right",
}


class Emulator(Protocol):
    frame: int

    def tick(self, frames: int = 1) -> None: ...

    def press(self, button: Button, frames: int = 8) -> None: ...

    def screenshot_png(self) -> bytes: ...

    def save_state(self, path: Path) -> None: ...

    def load_state(self, path: Path) -> None: ...

    def read_memory_byte(self, address: int) -> int: ...

    def stop(self) -> None: ...


def file_sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rom_title(path: Path) -> str | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if len(data) < 0x144:
        return None
    raw = data[0x134:0x144]
    title = raw.split(b"\0", 1)[0].decode("ascii", errors="ignore").strip()
    return title or None


def png_sha256(png: bytes) -> str:
    return hashlib.sha256(png).hexdigest()


class PyBoyEmulator:
    def __init__(self, rom_path: Path, sym_path: Path | None = None):
        from pyboy import PyBoy

        self.pyboy = PyBoy(str(rom_path), window="null", log_level="ERROR")
        if hasattr(self.pyboy, "set_emulation_speed"):
            self.pyboy.set_emulation_speed(0)
        self.frame = 0

    def tick(self, frames: int = 1) -> None:
        for _ in range(frames):
            self.pyboy.tick()
            self.frame += 1

    def press(self, button: Button, frames: int = 8) -> None:
        pyboy_button = BUTTON_TO_PYBOY[button]
        self.pyboy.button(pyboy_button, frames)
        self.tick(frames + 1)

    def screenshot_png(self) -> bytes:
        image = self.pyboy.screen.image
        with io.BytesIO() as handle:
            image.save(handle, format="PNG")
            return handle.getvalue()

    def save_state(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as handle:
            self.pyboy.save_state(handle)

    def load_state(self, path: Path) -> None:
        with path.open("rb") as handle:
            self.pyboy.load_state(handle)

    def read_memory_byte(self, address: int) -> int:
        return int(self.pyboy.memory[address])

    def stop(self) -> None:
        self.pyboy.stop(save=False)


class FakeEmulator:
    def __init__(self, rom_path: Path | None = None, sym_path: Path | None = None):
        self.frame = 0
        self.x = 3
        self.y = 6
        self.map_id = 0
        self.direction = 0
        self.party_count = 0
        self.buttons: list[str] = []
        self.memory = {
            0xD35E: self.map_id,
            0xD361: self.y,
            0xD362: self.x,
            0xD163: self.party_count,
        }

    def _sync_memory(self) -> None:
        self.memory[0xD35E] = self.map_id
        self.memory[0xD361] = self.y
        self.memory[0xD362] = self.x
        self.memory[0xD163] = self.party_count

    def tick(self, frames: int = 1) -> None:
        self.frame += frames

    def press(self, button: Button, frames: int = 8) -> None:
        self.buttons.append(button)
        if button == "UP":
            self.y = max(0, self.y - 1)
            self.direction = 0
        elif button == "DOWN":
            self.y += 1
            self.direction = 1
        elif button == "LEFT":
            self.x = max(0, self.x - 1)
            self.direction = 2
        elif button == "RIGHT":
            self.x += 1
            self.direction = 3
        elif button == "A" and len([b for b in self.buttons if b == "A"]) > 8:
            self.party_count = 1
        self._sync_memory()
        self.tick(frames)

    def screenshot_png(self) -> bytes:
        color = ((self.frame * 3) % 255, (80 + self.x * 13) % 255, (120 + self.y * 9) % 255)
        image = Image.new("RGBA", (SCREEN_WIDTH, SCREEN_HEIGHT), color + (255,))
        draw = ImageDraw.Draw(image)
        draw.rectangle((8, 8, 152, 136), outline=(255, 255, 255, 255))
        draw.text((14, 16), f"Fake Pokemon", fill=(255, 255, 255, 255))
        draw.text((14, 34), f"frame {self.frame}", fill=(255, 255, 255, 255))
        draw.text((14, 52), f"x {self.x} y {self.y}", fill=(255, 255, 255, 255))
        with io.BytesIO() as handle:
            image.save(handle, format="PNG")
            return handle.getvalue()

    def save_state(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "frame": self.frame,
                    "x": self.x,
                    "y": self.y,
                    "map_id": self.map_id,
                    "direction": self.direction,
                    "party_count": self.party_count,
                    "buttons": self.buttons,
                }
            ),
            encoding="utf-8",
        )

    def load_state(self, path: Path) -> None:
        data = json.loads(path.read_text(encoding="utf-8"))
        self.frame = int(data["frame"])
        self.x = int(data["x"])
        self.y = int(data["y"])
        self.map_id = int(data["map_id"])
        self.direction = int(data["direction"])
        self.party_count = int(data["party_count"])
        self.buttons = list(data["buttons"])
        self._sync_memory()

    def read_memory_byte(self, address: int) -> int:
        return int(self.memory.get(address, 0))

    def stop(self) -> None:
        return None
