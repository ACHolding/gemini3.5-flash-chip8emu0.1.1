#!/usr/bin/env python3
"""
CHIP-8 Emulator (v4k0.1.1.1)
An mGBA-style dark/blue themed CHIP-8 interpreter built with Tkinter.

Features:
- Pure blue-on-black visual palette.
- Dynamic phosphor persistence decay effect (simulating authentic CRT glow).
- Sidebar with real-time registers (V0-VF, PC, I, DT, ST) inspector.
- Interactive keypad visualizer (lights up when keys are pressed).
- Typewriter-style diagnostic log terminal.
- Built-in games library (IBM Logo, Maze Generator, Digits Test) loadable via "PLAY ROM".
- Non-blocking async audio buzzer for macOS (afplay) and fallback system bell.
- Complete and accurate CHIP-8 instruction interpreter.

Keyboard controls:
  CHIP-8 Keypad    QWERTY Mapping
  -------------    --------------
  1  2  3  C  -->  1  2  3  4
  4  5  6  D  -->  Q  W  E  R
  7  8  9  E  -->  A  S  D  F
  A  0  B  F  -->  Z  X  C  V

  SpaceBar: Play / Pause
  Escape:   Reset Game
"""

import sys
import os
import random
import time
import subprocess
import platform
import tkinter as tk
from tkinter import filedialog, messagebox

# --- CONFIGURATION CONSTANTS ---
WINDOW_TITLE = "ac'schip 8 emu 0.1"
SCREEN_W = 64
SCREEN_H = 32
PIXEL_SCALE = 7  # 64*7 = 448x224 display

# Colors
COLOR_BG = "#000000"
COLOR_TEXT_BLUE = "#00BFFF"       # Deep Sky Blue
COLOR_BORDER_BLUE = "#0055ff"     # Neon Border Blue
COLOR_PANEL_BG = "#080b18"        # Dark Blue-Black Panel
COLOR_TEXT_DIM = "#0088cc"

# Phosphor Decay Glow Colors (0 = Black, 5 = Full Neon Blue)
GLOW_COLORS = [
    "#000000",  # Decay step 0
    "#00162b",  # Decay step 1
    "#003366",  # Decay step 2
    "#005999",  # Decay step 3
    "#008cd4",  # Decay step 4
    "#00BFFF",  # Decay step 5 (Full active)
]

# Standard QWERTY to CHIP-8 keypad mapping
KEY_MAP = {
    "1": 0x1, "2": 0x2, "3": 0x3, "4": 0xC,
    "q": 0x4, "w": 0x5, "e": 0x6, "r": 0xD,
    "a": 0x7, "s": 0x8, "d": 0x9, "f": 0xE,
    "z": 0xA, "x": 0x0, "c": 0xB, "v": 0xF,
}

KEY_LABELS = {
    0x1: "1", 0x2: "2", 0x3: "3", 0xC: "C",
    0x4: "4", 0x5: "5", 0x6: "6", 0xD: "D",
    0x7: "7", 0x8: "8", 0x9: "9", 0xE: "E",
    0xA: "A", 0x0: "0", 0xB: "B", 0xF: "F",
}

KEYPAD_ROWS = [
    [0x1, 0x2, 0x3, 0xC],
    [0x4, 0x5, 0x6, 0xD],
    [0x7, 0x8, 0x9, 0xE],
    [0xA, 0x0, 0xB, 0xF],
]


# --- BUILT-IN ROMS ---
IBM_LOGO_ROM = bytes.fromhex(
    "00e0a22a600c6108d0147009a239d0147008d1147004a248d1147008d0147017"
    "a257d0147008d1147004a266d1147008d01412323c7cc0c0c0c0c0c0c0c0c0c0"
    "c0c0c8d8703000003c7cc0c0c0c0c0c0c0c0c0c0c0c0c0c00000fcfcc0c0c0c0"
    "c0c0c0c0c0c0fcfcc0c0c0c0c0c0c0c0c0c0fcfc000000003c7cc0c0c0c0c0c0"
    "c0c0c0c0c0c0c0c00000fcfcc0c0c0c0c0c0c0c0c0c0fcfcc0c0c0c0c0c0c0c0"
    "c0c0fcfc000000003c7cc0c0c0c0ccccccccccccccccfcfc000000003c7cc0c0"
    "c0c0c0c0c0c0c0c0c0c0c0c00000fcfcc0c0c0c0c0c0c0c0c0c0fcfcc0c0c0c0"
    "c0c0c0c0c0c0fcfc000000003c7cc0c0c0c0ccccccccccccccccfcfc00000000"
)

MAZE_ROM = bytes.fromhex(
    "a21ec2013201a21ad01470043040120412008040201020408010"
)

DIGITS_TEST_ROM = bytes.fromhex(
    "00e0610660046200f229d015600c6201f229d01560146202f229d015601c6203"
    "f229d01560246204f229d015602c6205f229d01560346206f229d015603c6207"
    "f229d015611060046208f229d015600c6209f229d0156014620af229d015601c"
    "620bf229d0156024620cf229d015602c620df229d0156034620ef229d015603c"
    "620ff229d0151254"
)

BUILTIN_GAMES = {
    "IBM Logo": IBM_LOGO_ROM,
    "Maze Generator": MAZE_ROM,
    "Digits Test": DIGITS_TEST_ROM,
}


# --- CHIP-8 CPU CORE ---
class Chip8Core:
    def __init__(self):
        self.memory = bytearray(4096)
        self.v = bytearray(16)
        self.i = 0
        self.pc = 0x200
        self.stack = []
        self.delay_timer = 0
        self.sound_timer = 0
        self.display = [0] * (SCREEN_W * SCREEN_H)
        self.keys = [False] * 16
        self.draw_flag = True
        self.waiting_for_key_reg = None
        self.halted = False
        self.last_rom = None
        self.rom_name = "No ROM Loaded"
        self.load_fontset()

    def reset(self):
        self.memory = bytearray(4096)
        self.v = bytearray(16)
        self.i = 0
        self.pc = 0x200
        self.stack.clear()
        self.delay_timer = 0
        self.sound_timer = 0
        self.display = [0] * (SCREEN_W * SCREEN_H)
        self.keys = [False] * 16
        self.draw_flag = True
        self.waiting_for_key_reg = None
        self.halted = False
        self.load_fontset()
        if self.last_rom:
            for idx, byte in enumerate(self.last_rom):
                self.memory[0x200 + idx] = byte

    def load_fontset(self):
        fontset = [
            0xF0, 0x90, 0x90, 0x90, 0xF0,  # 0
            0x20, 0x60, 0x20, 0x20, 0x70,  # 1
            0xF0, 0x10, 0xF0, 0x80, 0xF0,  # 2
            0xF0, 0x10, 0xF0, 0x10, 0xF0,  # 3
            0x90, 0x90, 0xF0, 0x10, 0x10,  # 4
            0xF0, 0x80, 0xF0, 0x10, 0xF0,  # 5
            0xF0, 0x80, 0xF0, 0x90, 0xF0,  # 6
            0xF0, 0x10, 0x20, 0x40, 0x40,  # 7
            0xF0, 0x90, 0xF0, 0x90, 0xF0,  # 8
            0xF0, 0x90, 0xF0, 0x10, 0xF0,  # 9
            0xF0, 0x90, 0xF0, 0x90, 0x90,  # A
            0xE0, 0x90, 0xE0, 0x90, 0xE0,  # B
            0xF0, 0x80, 0x80, 0x80, 0xF0,  # C
            0xE0, 0x90, 0x90, 0x90, 0xE0,  # D
            0xF0, 0x80, 0xF0, 0x80, 0xF0,  # E
            0xF0, 0x80, 0xF0, 0x80, 0x80   # F
        ]
        for idx, byte in enumerate(fontset):
            self.memory[0x50 + idx] = byte

    def load_rom(self, data, name="ROM File"):
        self.last_rom = data
        self.rom_name = name
        self.reset()

    def step(self):
        if self.halted:
            return

        # Handle wait keypress opcode FX0A
        if self.waiting_for_key_reg is not None:
            for idx, pressed in enumerate(self.keys):
                if pressed:
                    self.v[self.waiting_for_key_reg] = idx
                    self.waiting_for_key_reg = None
                    break
            if self.waiting_for_key_reg is not None:
                return  # Block execution

        if self.pc + 1 >= 4096:
            self.halted = True
            return

        opcode = (self.memory[self.pc] << 8) | self.memory[self.pc + 1]
        self.pc = (self.pc + 2) & 0xFFF

        x = (opcode & 0x0F00) >> 8
        y = (opcode & 0x00F0) >> 4
        n = opcode & 0x000F
        nn = opcode & 0x00FF
        nnn = opcode & 0x0FFF
        op = opcode & 0xF000

        # Decode CHIP-8 instruction
        if opcode == 0x00E0:  # CLS
            self.display = [0] * (SCREEN_W * SCREEN_H)
            self.draw_flag = True
        elif opcode == 0x00EE:  # RET
            if self.stack:
                self.pc = self.stack.pop()
            else:
                self.halted = True
        elif op == 0x1000:  # JP nnn
            self.pc = nnn
        elif op == 0x2000:  # CALL nnn
            self.stack.append(self.pc)
            self.pc = nnn
        elif op == 0x3000:  # SE Vx, nn
            if self.v[x] == nn:
                self.pc = (self.pc + 2) & 0xFFF
        elif op == 0x4000:  # SNE Vx, nn
            if self.v[x] != nn:
                self.pc = (self.pc + 2) & 0xFFF
        elif op == 0x5000 and n == 0:  # SE Vx, Vy
            if self.v[x] == self.v[y]:
                self.pc = (self.pc + 2) & 0xFFF
        elif op == 0x6000:  # LD Vx, nn
            self.v[x] = nn
        elif op == 0x7000:  # ADD Vx, nn
            self.v[x] = (self.v[x] + nn) & 0xFF
        elif op == 0x8000:
            if n == 0x0:  # LD Vx, Vy
                self.v[x] = self.v[y]
            elif n == 0x1:  # OR Vx, Vy
                self.v[x] |= self.v[y]
            elif n == 0x2:  # AND Vx, Vy
                self.v[x] &= self.v[y]
            elif n == 0x3:  # XOR Vx, Vy
                self.v[x] ^= self.v[y]
            elif n == 0x4:  # ADD Vx, Vy
                total = self.v[x] + self.v[y]
                self.v[0xF] = 1 if total > 255 else 0
                self.v[x] = total & 0xFF
            elif n == 0x5:  # SUB Vx, Vy
                self.v[0xF] = 1 if self.v[x] >= self.v[y] else 0
                self.v[x] = (self.v[x] - self.v[y]) & 0xFF
            elif n == 0x6:  # SHR Vx
                self.v[0xF] = self.v[x] & 1
                self.v[x] >>= 1
            elif n == 0x7:  # SUBN Vx, Vy
                self.v[0xF] = 1 if self.v[y] >= self.v[x] else 0
                self.v[x] = (self.v[y] - self.v[x]) & 0xFF
            elif n == 0xE:  # SHL Vx
                self.v[0xF] = (self.v[x] >> 7) & 1
                self.v[x] = (self.v[x] << 1) & 0xFF
        elif op == 0x9000 and n == 0:  # SNE Vx, Vy
            if self.v[x] != self.v[y]:
                self.pc = (self.pc + 2) & 0xFFF
        elif op == 0xA000:  # LD I, nnn
            self.i = nnn
        elif op == 0xB000:  # JP V0, nnn
            self.pc = (nnn + self.v[0]) & 0xFFF
        elif op == 0xC000:  # RND Vx, nn
            self.v[x] = random.randint(0, 255) & nn
        elif op == 0xD000:  # DRW Vx, Vy, n
            vx = self.v[x] % SCREEN_W
            vy = self.v[y] % SCREEN_H
            self.v[0xF] = 0
            for row in range(n):
                if self.i + row >= 4096:
                    break
                sprite_byte = self.memory[self.i + row]
                py = vy + row
                if py >= SCREEN_H:
                    break
                for col in range(8):
                    px = vx + col
                    if px >= SCREEN_W:
                        break
                    if (sprite_byte & (0x80 >> col)) != 0:
                        idx = px + py * SCREEN_W
                        if self.display[idx] == 1:
                            self.v[0xF] = 1
                        self.display[idx] ^= 1
            self.draw_flag = True
        elif op == 0xE000:
            key_val = self.v[x] & 0xF
            if nn == 0x9E:  # SKP Vx
                if self.keys[key_val]:
                    self.pc = (self.pc + 2) & 0xFFF
            elif nn == 0xA1:  # SKNP Vx
                if not self.keys[key_val]:
                    self.pc = (self.pc + 2) & 0xFFF
        elif op == 0xF000:
            if nn == 0x07:  # LD Vx, DT
                self.v[x] = self.delay_timer
            elif nn == 0x0A:  # LD Vx, K
                self.waiting_for_key_reg = x
            elif nn == 0x15:  # LD DT, Vx
                self.delay_timer = self.v[x]
            elif nn == 0x18:  # LD ST, Vx
                self.sound_timer = self.v[x]
            elif nn == 0x1E:  # ADD I, Vx
                self.i = (self.i + self.v[x]) & 0xFFFF
            elif nn == 0x29:  # LD F, Vx
                self.i = 0x50 + (self.v[x] & 0xF) * 5
            elif nn == 0x33:  # LD B, Vx
                val = self.v[x]
                self.memory[self.i] = val // 100
                self.memory[self.i + 1] = (val // 10) % 10
                self.memory[self.i + 2] = val % 10
            elif nn == 0x55:  # LD [I], Vx
                for idx in range(x + 1):
                    self.memory[self.i + idx] = self.v[idx]
            elif nn == 0x65:  # LD Vx, [I]
                for idx in range(x + 1):
                    self.v[idx] = self.memory[self.i + idx]

    def tick_timers(self):
        if self.delay_timer > 0:
            self.delay_timer -= 1
        if self.sound_timer > 0:
            self.sound_timer -= 1


# --- SOUND GENERATOR ---
class AudioEngine:
    def __init__(self, root):
        self.root = root
        self.is_mac = platform.system() == "Darwin"

    def beep(self):
        if self.is_mac:
            try:
                # Play Tink sound asynchronously so it does not block the Tkinter thread
                subprocess.Popen(
                    ["afplay", "/System/Library/Sounds/Tink.aiff"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            except Exception:
                self.bell_fallback()
        else:
            self.bell_fallback()

    def bell_fallback(self):
        try:
            self.root.bell()
        except Exception:
            pass


# --- EMULATOR USER INTERFACE ---
class Chip8App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(WINDOW_TITLE)
        self.geometry("640x440")
        self.resizable(False, False)
        self.configure(bg=COLOR_BG)

        self.chip = Chip8Core()
        self.audio = AudioEngine(self)
        self.running = False
        self.cycles_per_frame = 10
        self.last_sound_active = False

        # Phosphor Persistence Tracking
        self.pixel_brightness = [0] * (SCREEN_W * SCREEN_H)
        self.rendered_states = [-1] * (SCREEN_W * SCREEN_H)

        self.make_menu()
        self.build_ui()
        self.bind_events()

        # Load default demo
        self.load_builtin_rom("Maze Generator")
        self.log("System initialized. Ready.")

        # Start master update loop
        self.update_loop()

    # --- MENU SETUP ---
    def make_menu(self):
        menubar = tk.Menu(
            self,
            bg=COLOR_BG,
            fg=COLOR_TEXT_BLUE,
            activebackground=COLOR_PANEL_BG,
            activeforeground="#FFFFFF"
        )

        file_menu = tk.Menu(menubar, tearoff=0, bg=COLOR_BG, fg=COLOR_TEXT_BLUE)
        file_menu.add_command(label="Load ROM File...", command=self.action_load_rom)
        file_menu.add_separator()
        file_menu.add_command(label="Exit Console", command=self.action_exit)
        menubar.add_cascade(label="File", menu=file_menu)

        emu_menu = tk.Menu(menubar, tearoff=0, bg=COLOR_BG, fg=COLOR_TEXT_BLUE)
        emu_menu.add_command(label="Pause / Resume", command=self.action_play_game)
        emu_menu.add_command(label="Reset ROM", command=self.action_reset)
        emu_menu.add_separator()
        emu_menu.add_command(label="Cycles: Normal (10)", command=lambda: self.set_speed(10))
        emu_menu.add_command(label="Cycles: Fast (20)", command=lambda: self.set_speed(20))
        emu_menu.add_command(label="Cycles: Turbo (40)", command=lambda: self.set_speed(40))
        menubar.add_cascade(label="Emulation", menu=emu_menu)

        help_menu = tk.Menu(menubar, tearoff=0, bg=COLOR_BG, fg=COLOR_TEXT_BLUE)
        help_menu.add_command(label="Controls Help", command=self.action_help)
        help_menu.add_command(label="About Emulator", command=self.action_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.config(menu=menubar)

    # --- UI BUILDING ---
    def build_ui(self):
        # Master Body
        body = tk.Frame(self, bg=COLOR_BG)
        body.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # Left Column (Display & Terminal Logs)
        left_col = tk.Frame(body, bg=COLOR_BG)
        left_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))

        # Main Screen Wrapper (Sleek Border)
        screen_frame = tk.Frame(
            left_col,
            bg=COLOR_PANEL_BG,
            highlightbackground=COLOR_BORDER_BLUE,
            highlightcolor=COLOR_BORDER_BLUE,
            highlightthickness=1,
            bd=0
        )
        screen_frame.pack(side=tk.TOP, anchor=tk.NW)

        # CRT Display Canvas
        canvas_width = SCREEN_W * PIXEL_SCALE
        canvas_height = SCREEN_H * PIXEL_SCALE
        self.canvas = tk.Canvas(
            screen_frame,
            width=canvas_width,
            height=canvas_height,
            bg=COLOR_BG,
            highlightthickness=0,
            bd=0
        )
        self.canvas.pack(padx=4, pady=4)

        # Precreate rects (6x6 pixels in a 7x7 grid yields 1px scanline gaps)
        self.pixel_rects = []
        for y in range(SCREEN_H):
            for x in range(SCREEN_W):
                x1 = x * PIXEL_SCALE
                y1 = y * PIXEL_SCALE
                rect = self.canvas.create_rectangle(
                    x1, y1, x1 + PIXEL_SCALE - 2, y1 + PIXEL_SCALE - 2,
                    fill=COLOR_BG, outline=""
                )
                self.pixel_rects.append(rect)

        # Scroll/Log Terminal Box
        log_frame = tk.Frame(
            left_col,
            bg=COLOR_BG,
            highlightbackground="#002850",
            highlightthickness=1,
            bd=0
        )
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(6, 0))

        self.log_list = tk.Listbox(
            log_frame,
            bg=COLOR_BG,
            fg=COLOR_TEXT_BLUE,
            bd=0,
            highlightthickness=0,
            font=("Courier", 9),
            height=6
        )
        self.log_list.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)

        # Right Column (Monitor Sidebar)
        right_col = tk.Frame(
            body,
            bg=COLOR_PANEL_BG,
            highlightbackground=COLOR_BORDER_BLUE,
            highlightthickness=1,
            bd=0,
            width=156
        )
        right_col.pack(side=tk.RIGHT, fill=tk.Y, padx=(6, 0))
        right_col.pack_propagate(False)

        # Sidebar Title
        lbl_sidebar = tk.Label(
            right_col,
            text="CHIP8-HUD",
            bg=COLOR_PANEL_BG,
            fg=COLOR_TEXT_BLUE,
            font=("Courier", 11, "bold"),
            pady=4
        )
        lbl_sidebar.pack(fill=tk.X)

        # Registers Inspector Layout
        reg_frame = tk.Frame(right_col, bg=COLOR_PANEL_BG)
        reg_frame.pack(fill=tk.X, padx=4)

        self.lbl_v = []
        for r in range(16):
            lbl = tk.Label(
                reg_frame,
                text=f"V{r:X}:00",
                bg=COLOR_PANEL_BG,
                fg=COLOR_TEXT_BLUE,
                font=("Courier", 8),
                anchor="w"
            )
            lbl.grid(row=r // 2, column=r % 2, sticky="ew", padx=2, pady=1)
            self.lbl_v.append(lbl)

        # System Status Registers
        sys_frame = tk.Frame(right_col, bg=COLOR_PANEL_BG)
        sys_frame.pack(fill=tk.X, padx=4, pady=4)

        self.lbl_pc = tk.Label(sys_frame, text="PC:0x200", bg=COLOR_PANEL_BG, fg=COLOR_TEXT_BLUE, font=("Courier", 8), anchor="w")
        self.lbl_pc.grid(row=0, column=0, sticky="ew", padx=2)
        self.lbl_i = tk.Label(sys_frame, text="I: 0x000", bg=COLOR_PANEL_BG, fg=COLOR_TEXT_BLUE, font=("Courier", 8), anchor="w")
        self.lbl_i.grid(row=0, column=1, sticky="ew", padx=2)

        self.lbl_timer = tk.Label(sys_frame, text="DT:00 ST:00", bg=COLOR_PANEL_BG, fg=COLOR_TEXT_BLUE, font=("Courier", 8), anchor="w")
        self.lbl_timer.grid(row=1, column=0, columnspan=2, sticky="ew", padx=2, pady=2)

        # Interactive Keypad Panel
        key_label = tk.Label(
            right_col,
            text="INPUT KEYPAD",
            bg=COLOR_PANEL_BG,
            fg=COLOR_TEXT_BLUE,
            font=("Courier", 8, "bold")
        )
        key_label.pack(pady=(4, 0))

        keypad_frame = tk.Frame(right_col, bg=COLOR_PANEL_BG)
        keypad_frame.pack(pady=4)

        self.visual_keys = {}
        for row_idx, row in enumerate(KEYPAD_ROWS):
            for col_idx, key in enumerate(row):
                lbl = tk.Label(
                    keypad_frame,
                    text=KEY_LABELS[key],
                    bg="black",
                    fg=COLOR_TEXT_BLUE,
                    font=("Courier", 8, "bold"),
                    width=2,
                    height=1,
                    bd=1,
                    relief="solid",
                    highlightbackground=COLOR_BORDER_BLUE
                )
                lbl.grid(row=row_idx, column=col_idx, padx=1, pady=1)
                self.visual_keys[key] = lbl

        # Bottom Bar: Buttons Toolbar
        bottom_bar = tk.Frame(self, bg=COLOR_BG)
        bottom_bar.pack(side=tk.BOTTOM, fill=tk.X, padx=8, pady=(0, 8))

        btn_style = {
            "bg": "black",
            "fg": COLOR_TEXT_BLUE,
            "activebackground": "#002850",
            "activeforeground": "#FFFFFF",
            "font": ("Courier", 9, "bold"),
            "relief": "flat",
            "bd": 0,
            "highlightbackground": COLOR_BORDER_BLUE,
            "highlightcolor": COLOR_TEXT_BLUE,
            "highlightthickness": 1,
            "padx": 6,
            "pady": 2,
            "cursor": "hand2"
        }

        # Setup buttons
        self.btn_load = tk.Button(bottom_bar, text="LOAD ROM", command=self.action_load_rom, **btn_style)
        self.btn_load.pack(side=tk.LEFT, padx=(0, 4))
        self.add_hover(self.btn_load)

        self.btn_play = tk.Button(bottom_bar, text="PLAY GAME", command=self.action_play_game, **btn_style)
        self.btn_play.pack(side=tk.LEFT, padx=4)
        self.add_hover(self.btn_play)

        self.btn_play_rom = tk.Button(bottom_bar, text="PLAY ROM ▾", **btn_style)
        self.btn_play_rom.pack(side=tk.LEFT, padx=4)
        self.btn_play_rom.bind("<Button-1>", self.show_play_rom_dropdown)
        self.add_hover(self.btn_play_rom)

        self.btn_help = tk.Button(bottom_bar, text="HELP", command=self.action_help, **btn_style)
        self.btn_help.pack(side=tk.LEFT, padx=4)
        self.add_hover(self.btn_help)

        self.btn_about = tk.Button(bottom_bar, text="ABOUT", command=self.action_about, **btn_style)
        self.btn_about.pack(side=tk.LEFT, padx=4)
        self.add_hover(self.btn_about)

        self.btn_exit = tk.Button(bottom_bar, text="EXIT", command=self.action_exit, **btn_style)
        self.btn_exit.pack(side=tk.RIGHT, padx=(4, 0))
        self.add_hover(self.btn_exit)

    # --- UI INTERACTION STYLING ---
    def add_hover(self, widget):
        widget.bind("<Enter>", lambda e: widget.config(bg="#002850", fg="#ffffff"))
        widget.bind("<Leave>", lambda e: widget.config(bg="black", fg=COLOR_TEXT_BLUE))

    # --- EVENT BINDINGS ---
    def bind_events(self):
        self.bind("<KeyPress>", self.key_down)
        self.bind("<KeyRelease>", self.key_up)

    def key_down(self, event):
        key = event.keysym.lower()
        if key == "space":
            self.action_play_game()
            return
        if key == "escape":
            self.action_reset()
            return

        if key in KEY_MAP:
            chip_key = KEY_MAP[key]
            self.chip.keys[chip_key] = True
            # Update key visualizer
            self.visual_keys[chip_key].config(bg=COLOR_TEXT_BLUE, fg="black")
            # Complete key waiting logic immediately if waiting
            if self.chip.waiting_for_key_reg is not None:
                self.chip.v[self.chip.waiting_for_key_reg] = chip_key
                self.chip.waiting_for_key_reg = None
                self.log(f"Key waiting cleared via {key.upper()}")

    def key_up(self, event):
        key = event.keysym.lower()
        if key in KEY_MAP:
            chip_key = KEY_MAP[key]
            self.chip.keys[chip_key] = False
            self.visual_keys[chip_key].config(bg="black", fg=COLOR_TEXT_BLUE)

    # --- LOG TERMINAL ---
    def log(self, message):
        timestamp = time.strftime("%H:%M:%S")
        formatted = f"[{timestamp}] {message}"
        self.log_list.insert(tk.END, formatted)
        self.log_list.see(tk.END)

    # --- DROPDOWN SELECTOR ---
    def show_play_rom_dropdown(self, event):
        dropdown = tk.Menu(
            self,
            tearoff=0,
            bg="black",
            fg=COLOR_TEXT_BLUE,
            activebackground="#002850",
            activeforeground="#ffffff"
        )
        for game_name in BUILTIN_GAMES:
            dropdown.add_command(
                label=f"  {game_name}",
                command=lambda name=game_name: self.load_builtin_rom(name)
            )
        dropdown.post(event.x_root, event.y_root)

    def load_builtin_rom(self, name):
        rom_data = BUILTIN_GAMES[name]
        self.chip.load_rom(rom_data, name)
        self.log(f"Selected Built-in ROM: '{name}'")
        self.log(f"Loaded {len(rom_data)} bytes.")
        self.action_play_game(force_run=True)

    # --- ACTION HANDLERS ---
    def action_load_rom(self):
        filepath = filedialog.askopenfilename(
            title="Load CHIP-8 ROM File",
            filetypes=[("CHIP-8 ROMs (*.ch8)", "*.ch8"), ("All Files (*.*)", "*.*")]
        )
        if filepath:
            try:
                with open(filepath, "rb") as f:
                    rom_data = f.read()
                name = os.path.basename(filepath)
                self.chip.load_rom(rom_data, name)
                self.log(f"ROM loaded: {name}")
                self.log(f"ROM Size: {len(rom_data)} bytes.")
                self.action_play_game(force_run=True)
            except Exception as e:
                self.log(f"Error loading ROM: {e}")
                messagebox.showerror("Error", f"Could not load ROM:\n{e}")

    def action_play_game(self, force_run=None):
        if force_run is True:
            self.running = True
        elif force_run is False:
            self.running = False
        else:
            self.running = not self.running

        if self.running:
            self.btn_play.config(text="PAUSE GAME")
            self.log("Emulation resumed.")
        else:
            self.btn_play.config(text="PLAY GAME")
            self.log("Emulation paused.")

    def action_reset(self):
        self.chip.reset()
        self.log("Console Core reset triggered.")
        self.action_play_game(force_run=True)

    def set_speed(self, speed):
        self.cycles_per_frame = speed
        self.log(f"Cycles-per-frame adjusted to: {speed}")

    def action_help(self):
        help_text = (
            "Keyboard Mappings:\n"
            "------------------\n"
            "CHIP-8 keypad maps to QWERTY letters:\n"
            "  1 2 3 C   -->   1 2 3 4\n"
            "  4 5 6 D   -->   Q W E R\n"
            "  7 8 9 E   -->   A S D F\n"
            "  A 0 B F   -->   Z X C V\n\n"
            "Console Hotkeys:\n"
            "  Spacebar: Pause / Play game\n"
            "  Escape:   Reset current ROM\n"
        )
        messagebox.showinfo("Keyboard Helper", help_text)

    def action_about(self):
        about_text = (
            "CHIP-8 Emulator Console\n"
            "Version 4k0.1.1.1\n\n"
            "Designed by Antigravity AI.\n"
            "Features a high-fidelity retro CRT phosphor decay renderer, "
            "macOS sound pipeline, real-time debugging sidebar, "
            "and a built-in ROM library."
        )
        messagebox.showinfo("About Emulator", about_text)

    def action_exit(self):
        self.running = False
        self.destroy()
        sys.exit(0)

    # --- MONITOR REFRESH ---
    def update_sidebar(self):
        # Update Registers display
        for idx in range(16):
            val = self.chip.v[idx]
            self.lbl_v[idx].config(text=f"V{idx:X}:{val:02X}")

        self.lbl_pc.config(text=f"PC:0x{self.chip.pc:03X}")
        self.lbl_i.config(text=f"I: 0x{self.chip.i:03X}")
        self.lbl_timer.config(
            text=f"DT:{self.chip.delay_timer:02X} ST:{self.chip.sound_timer:02X}"
        )

    # --- PERSISTENT RENDERING & SYSTEM TICK ---
    def draw_screen(self):
        # Compute Phosphor persistence decay
        for idx in range(SCREEN_W * SCREEN_H):
            target = self.chip.display[idx]
            current_level = self.pixel_brightness[idx]

            if target == 1:
                # Instant light up
                new_level = 5
            else:
                # Decaying glow frame by frame
                new_level = max(0, current_level - 1)

            self.pixel_brightness[idx] = new_level

            # Draw to Canvas only if state changes (Massive speed up!)
            if new_level != self.rendered_states[idx]:
                color = GLOW_COLORS[new_level]
                self.canvas.itemconfig(self.pixel_rects[idx], fill=color)
                self.rendered_states[idx] = new_level

    def update_loop(self):
        # Execute Emulation Steps
        if self.running and not self.chip.halted:
            for _ in range(self.cycles_per_frame):
                self.chip.step()
                if self.chip.halted:
                    self.running = False
                    self.log("Emulation halted. Out of bounds or bad code.")
                    self.btn_play.config(text="PLAY GAME")
                    break

            self.chip.tick_timers()

        # Audio beep synchronization
        sound_active = (self.chip.sound_timer > 0) and self.running and not self.chip.halted
        if sound_active and not self.last_sound_active:
            self.audio.beep()
        self.last_sound_active = sound_active

        # Refresh Graphics
        if self.chip.draw_flag or not self.running:
            self.draw_screen()
            self.chip.draw_flag = False

        # Refresh Debug Sidebar
        self.update_sidebar()

        # Loop at ~60 Hz (16ms intervals)
        self.after(16, self.update_loop)


# --- ENTRY POINT ---
if __name__ == "__main__":
    app = Chip8App()
    app.mainloop()
