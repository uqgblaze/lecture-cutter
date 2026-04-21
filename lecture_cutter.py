#!/usr/bin/env python3
"""
Lecture Cutter v2.1
- Auto-detects audio, VTT transcript, and timestamp table from a working directory.
- Cuts audio into labelled MP3/MP4 segments via ffmpeg.
- Rebases per-segment VTT subtitle files to start at 00:00:00.
- Optional: generate a VTT transcript from the source audio using faster-whisper (local AI).
- Drop ffmpeg.exe (or bin/ffmpeg.exe) next to this script for fully portable use.
"""
import os
import re
import zipfile
import threading
import subprocess
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

SCRIPT_DIR = Path(__file__).parent

# Substrings that indicate a cloud-synced path
_CLOUD_KEYWORDS = [
    "onedrive", "icloud drive", "google drive", "googledrive",
    "dropbox", "sharepoint", "box sync", "synology drive",
]


# ── helpers ──────────────────────────────────────────────────────────────────

def find_ffmpeg() -> str:
    for candidate in [
        SCRIPT_DIR / "ffmpeg.exe",
        SCRIPT_DIR / "bin" / "ffmpeg.exe",
        SCRIPT_DIR / "ffmpeg" / "bin" / "ffmpeg.exe",
    ]:
        if candidate.exists():
            return str(candidate)
    import shutil
    return shutil.which("ffmpeg") or ""


def _is_cloud_path(path: str) -> bool:
    low = path.lower().replace("\\", "/")
    return any(kw in low for kw in _CLOUD_KEYWORDS)


def _whisper_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def safe_filename(name: str) -> str:
    name = name.strip()
    name = re.sub(r'[\\/:*?"<>|]', "-", name)
    name = re.sub(r"\s+", " ", name)
    return name


def hms_to_ms(hms: str) -> int:
    m = re.match(r"^(\d{1,2}):(\d{2}):(\d{2})(?:\.(\d{1,3}))?$", hms.strip())
    if not m:
        raise ValueError(f"Invalid time format: {hms!r}")
    ms_str = (m.group(4) or "0").ljust(3, "0")
    return (int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))) * 1000 + int(ms_str)


def ms_to_vtt(ms: int) -> str:
    ms = max(0, ms)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1_000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def parse_timestamps(md_text: str) -> list:
    rows = []
    for line in md_text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        if "Start" in line or "---" in line:
            continue
        parts = [p.strip() for p in line.strip("|").split("|")]
        if len(parts) < 4:
            continue
        start, stop, title = parts[0], parts[2], parts[3].strip()
        if not re.match(r"^\d{1,2}:\d{2}:\d{2}(\.\d{1,3})?$", start):
            continue
        if not re.match(r"^\d{1,2}:\d{2}:\d{2}(\.\d{1,3})?$", stop):
            continue
        rows.append({"start": start, "stop": stop, "title": title})
    return rows


def parse_vtt(vtt_text: str) -> list:
    lines = vtt_text.replace("\ufeff", "").splitlines()
    i = 0
    if i < len(lines) and lines[i].strip().upper().startswith("WEBVTT"):
        i += 1
    while i < len(lines) and lines[i].strip():
        i += 1
    while i < len(lines) and not lines[i].strip():
        i += 1
    timing_re = re.compile(
        r"^(\d{1,2}:\d{2}:\d{2}(?:\.\d{3})?)\s*-->\s*(\d{1,2}:\d{2}:\d{2}(?:\.\d{3})?)(?:\s+.*)?$"
    )
    cues = []
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        if i + 1 < len(lines) and timing_re.match(lines[i + 1].strip()):
            i += 1
            line = lines[i].strip()
        m = timing_re.match(line)
        if not m:
            i += 1
            continue
        start_ms, end_ms = hms_to_ms(m.group(1)), hms_to_ms(m.group(2))
        i += 1
        text_lines = []
        while i < len(lines) and lines[i].strip():
            text_lines.append(lines[i].rstrip())
            i += 1
        cues.append({"start_ms": start_ms, "end_ms": end_ms,
                     "text": "\n".join(text_lines).strip()})
        while i < len(lines) and not lines[i].strip():
            i += 1
    return cues


def build_segment_vtt(seg_start_ms: int, seg_end_ms: int, cues: list) -> str | None:
    if seg_end_ms <= seg_start_ms:
        return None
    out_lines = ["WEBVTT", ""]
    wrote_any = False
    for cue in cues:
        if cue["end_ms"] <= seg_start_ms or cue["start_ms"] >= seg_end_ms:
            continue
        s = max(cue["start_ms"], seg_start_ms) - seg_start_ms
        e = min(cue["end_ms"],   seg_end_ms)   - seg_start_ms
        if e <= s:
            continue
        out_lines += [f"{ms_to_vtt(s)} --> {ms_to_vtt(e)}", cue["text"], ""]
        wrote_any = True
    return ("\n".join(out_lines).rstrip() + "\n") if wrote_any else None


# ── Whisper VTT generation worker ────────────────────────────────────────────

def generate_vtt_worker(audio_path, out_vtt_path, model_size, device, compute_type,
                         language, beam_size, vad_filter, word_timestamps,
                         initial_prompt, log_fn, done_fn):
    try:
        from faster_whisper import WhisperModel

        log_fn(f"Loading Whisper model '{model_size}' on {device}…")
        log_fn("  (First run will download the model — this may take several minutes.)")
        model = WhisperModel(model_size, device=device, compute_type=compute_type)
        log_fn("  Model ready. Starting transcription…\n")

        lang_arg = None if language.strip().lower() in ("auto", "") else language.strip()

        segments, info = model.transcribe(
            str(audio_path),
            beam_size=beam_size,
            language=lang_arg,
            vad_filter=vad_filter,
            word_timestamps=word_timestamps,
            initial_prompt=initial_prompt.strip() or None,
        )

        detected = getattr(info, "language", "unknown")
        duration = getattr(info, "duration", 0)
        log_fn(f"  Detected language: {detected}   Duration: {duration:.1f}s")
        log_fn("  Writing VTT file…")

        out_vtt_path = Path(out_vtt_path)
        out_vtt_path.parent.mkdir(parents=True, exist_ok=True)

        def _fmt(sec):
            t = int(round(sec * 1000))
            h = t // 3_600_000; t %= 3_600_000
            m = t // 60_000;    t %= 60_000
            s = t // 1_000;     ms = t % 1_000
            return f"{h:02}:{m:02}:{s:02}.{ms:03}"

        count = 0
        with out_vtt_path.open("w", encoding="utf-8", newline="\n") as f:
            f.write("WEBVTT\n\n")
            for seg in segments:
                text = " ".join(seg.text.strip().split())
                if not text:
                    continue
                f.write(f"{_fmt(seg.start)} --> {_fmt(seg.end)}\n{text}\n\n")
                count += 1

        log_fn(f"\nTranscript saved ({count} cues):\n  {out_vtt_path}")
        done_fn(True, str(out_vtt_path))

    except ImportError:
        log_fn("ERROR: faster-whisper is not installed.")
        log_fn("Install it by running:  pip install faster-whisper")
        done_fn(False, None)
    except Exception as exc:
        import traceback
        log_fn(f"ERROR: {exc}\n{traceback.format_exc()}")
        done_fn(False, None)


# ── Main cut + VTT-split worker ───────────────────────────────────────────────

def run_job(ffmpeg, audio_path, vtt_path, ts_path, out_dir, log_fn, done_fn):
    try:
        out_dir = Path(out_dir)
        log_fn(f"Creating output directory: {out_dir}")
        try:
            os.makedirs(str(out_dir), exist_ok=True)
        except Exception as e:
            log_fn(f"\nERROR: Could not create output directory.\n  {e}")
            log_fn("Choose a local Output Directory (e.g. Desktop or C:\\Temp).")
            done_fn(False)
            return

        if not out_dir.is_dir():
            log_fn(f"\nERROR: Directory does not exist after creation attempt: {out_dir}")
            log_fn("You likely don't have write permission here.")
            log_fn("Choose a local Output Directory (e.g. Desktop or C:\\Temp).")
            done_fn(False)
            return

        try:
            _p = out_dir / ".write_test"
            _p.write_text("ok")
            _p.unlink()
        except Exception as e:
            log_fn(f"\nERROR: Directory is not writable.\n  {e}")
            log_fn("Choose a local Output Directory (e.g. Desktop or C:\\Temp).")
            done_fn(False)
            return

        log_fn("Output directory ready.\n")

        segments = parse_timestamps(Path(ts_path).read_text(encoding="utf-8", errors="ignore"))
        if not segments:
            log_fn("ERROR: No valid timestamp rows found. Check the markdown table format.")
            done_fn(False)
            return
        log_fn(f"Found {len(segments)} segments in timestamps file.")

        cues = []
        if vtt_path and Path(vtt_path).exists():
            cues = parse_vtt(Path(vtt_path).read_text(encoding="utf-8", errors="ignore"))
            log_fn(f"Loaded {len(cues)} VTT cues from transcript.")
        else:
            log_fn("No VTT transcript — skipping subtitle generation.")

        vtt_out = out_dir / "vtt_out"
        if cues:
            vtt_out.mkdir(parents=True, exist_ok=True)

        ext = Path(audio_path).suffix.lower()
        is_video = ext == ".mp4"
        written_audio, written_vtt, warnings = [], [], []

        for i, seg in enumerate(segments, 1):
            title    = seg["title"]
            fname    = safe_filename(title)
            out_ext  = ".mp4" if is_video else ".mp3"
            out_path = out_dir / (fname + out_ext)

            log_fn(f"[{i}/{len(segments)}] {fname}{out_ext}  ({seg['start']} → {seg['stop']})")

            if is_video:
                ff_args = [
                    ffmpeg, "-y", "-hide_banner", "-loglevel", "warning",
                    "-i", str(audio_path),
                    "-ss", seg["start"], "-to", seg["stop"],
                    "-c:v", "libx264", "-preset", "medium", "-crf", "23",
                    "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
                    "-metadata", f"title={title}", str(out_path),
                ]
            else:
                ff_args = [
                    ffmpeg, "-y", "-hide_banner", "-loglevel", "warning",
                    "-i", str(audio_path),
                    "-ss", seg["start"], "-to", seg["stop"],
                    "-vn", "-codec:a", "libmp3lame", "-q:a", "2",
                    "-metadata", f"title={title}", str(out_path),
                ]

            result = subprocess.run(ff_args, capture_output=True, text=True)
            if result.returncode != 0 or not out_path.exists():
                err = (result.stderr or result.stdout).strip()
                log_fn(f"  ✗ ffmpeg failed (exit {result.returncode}):")
                for line in err.splitlines():
                    log_fn(f"      {line}")
                warnings.append(title)
            else:
                written_audio.append(out_path)
                log_fn("  ✓ saved")

            if cues:
                seg_vtt = build_segment_vtt(
                    hms_to_ms(seg["start"]), hms_to_ms(seg["stop"]), cues)
                if seg_vtt:
                    vp = vtt_out / (fname + ".vtt")
                    vp.write_text(seg_vtt, encoding="utf-8")
                    written_vtt.append(vp)
                else:
                    warnings.append(f"No VTT cues overlap segment: {title}")

        if written_vtt:
            zip_path = out_dir / "vtt_files.zip"
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
                for p in written_vtt:
                    z.write(p, arcname=p.name)
            log_fn(f"VTTs zipped → {zip_path}")

        log_fn(
            f"\n{'─'*50}\n"
            f"Complete.  {len(written_audio)}/{len(segments)} audio files written.\n"
            f"Output folder: {out_dir}"
        )
        if warnings:
            log_fn("\nWarnings:")
            for w in warnings:
                log_fn(f"  • {w}")
        done_fn(True)

    except Exception as exc:
        import traceback
        log_fn(f"\nERROR: {exc}\n{traceback.format_exc()}")
        done_fn(False)


# ── Whisper option tables ─────────────────────────────────────────────────────

_MODELS = [
    ("turbo",    "Turbo  (~810 MB) — best balance of speed and accuracy. Recommended."),
    ("medium",   "Medium  (~780 MB) — good accuracy, moderate speed."),
    ("large-v3", "Large v3  (~1.5 GB) — highest accuracy, slowest."),
    ("small",    "Small  (~250 MB) — fast with lower accuracy. Good for clear speech."),
    ("base",     "Base  (~150 MB) — very fast, basic accuracy."),
    ("tiny",     "Tiny  (~75 MB) — fastest possible. Testing only."),
]
_DEVICES = [
    ("cpu",  "CPU — works on any computer, no special hardware required."),
    ("cuda", "CUDA — NVIDIA GPU only. Typically 5–10× faster than CPU."),
]
_CPU_COMPUTE = [
    ("int8",    "int8 — fastest on CPU, minimal quality loss. Recommended for CPU."),
    ("float32", "float32 — full precision, slowest. Use if int8 gives poor results."),
]
_GPU_COMPUTE = [
    ("float16",      "float16 — fast, high accuracy. Recommended for NVIDIA GPUs."),
    ("int8_float16", "int8_float16 — fastest GPU mode, slight accuracy trade-off."),
    ("float32",      "float32 — full precision, slowest."),
]


# ── GUI ───────────────────────────────────────────────────────────────────────

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Lecture Cutter v2.1")
        self.minsize(740, 600)
        self.resizable(True, True)

        # Core fields
        self._ffmpeg_var  = tk.StringVar(value=find_ffmpeg())
        self._workdir_var = tk.StringVar()
        self._audio_var   = tk.StringVar()
        self._vtt_var     = tk.StringVar()
        self._ts_var      = tk.StringVar()
        self._outdir_var  = tk.StringVar()

        # Whisper settings
        self._w_model   = tk.StringVar(value="turbo")
        self._w_device  = tk.StringVar(value="cpu")
        self._w_compute = tk.StringVar(value="int8")
        self._w_lang    = tk.StringVar(value="en")
        self._w_beam    = tk.StringVar(value="5")
        self._w_vad     = tk.BooleanVar(value=True)
        self._w_word_ts = tk.BooleanVar(value=False)
        self._w_prompt  = tk.StringVar(value="")
        self._w_skip    = tk.BooleanVar(value=True)

        self._whisper_panel  = None   # built in _build_ui, toggled in/out
        self._whisper_open   = False
        self._gen_btn        = None
        self._gen_progress   = None
        self._compute_cb     = None
        self._cloud_warn_lbl = None

        self._build_ui()
        self._outdir_var.trace_add("write", self._on_outdir_change)

    # ── layout ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        p = dict(padx=8, pady=3)

        # ffmpeg row
        ff = ttk.LabelFrame(self, text="ffmpeg executable")
        ff.pack(fill="x", padx=10, pady=(10, 3))
        ttk.Entry(ff, textvariable=self._ffmpeg_var).pack(
            side="left", fill="x", expand=True, **p)
        ttk.Button(ff, text="Browse…", command=self._browse_ffmpeg).pack(side="left", **p)

        # Working directory
        wd = ttk.LabelFrame(self, text="Working Directory  (folder containing your files)")
        wd.pack(fill="x", padx=10, pady=3)
        ttk.Entry(wd, textvariable=self._workdir_var).pack(
            side="left", fill="x", expand=True, **p)
        ttk.Button(wd, text="Browse…", command=self._browse_workdir).pack(side="left", **p)

        # Input files
        fi = ttk.LabelFrame(self, text="Input Files  (auto-detected — click Change to override)")
        fi.pack(fill="x", padx=10, pady=3)
        self._file_row(fi, "Audio / Video:", self._audio_var, self._change_audio)
        self._build_vtt_section(fi)
        self._file_row(fi, "Timestamps (.md):", self._ts_var, self._change_ts)

        # Output directory
        od = ttk.LabelFrame(self, text="Output Directory")
        od.pack(fill="x", padx=10, pady=3)
        ttk.Entry(od, textvariable=self._outdir_var).pack(
            side="left", fill="x", expand=True, **p)
        ttk.Button(od, text="Browse…", command=self._browse_outdir).pack(side="left", **p)

        # Cloud path warning (shown only when needed)
        self._cloud_warn_lbl = ttk.Label(
            od,
            text=(
                "⚠  Do not save to OneDrive, iCloud, Google Drive, SharePoint, or any other "
                "cloud-synced folder — this will cause the conversion to fail silently. "
                "Choose a local directory (e.g. C:\\Users\\You\\Desktop\\output) "
                "and upload the finished files when complete."
            ),
            foreground="#c0392b",
            wraplength=660,
            justify="left",
        )
        # Packed dynamically by _on_outdir_change; hidden by default.

        # Run button
        self._run_btn = ttk.Button(
            self, text="▶  Cut Audio  +  Generate VTTs",
            command=self._run)
        self._run_btn.pack(fill="x", padx=10, pady=6)

        # Log
        lf = ttk.LabelFrame(self, text="Log")
        lf.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self._log_box = tk.Text(lf, state="disabled", wrap="word",
                                font=("Consolas", 9), height=10)
        sb = ttk.Scrollbar(lf, command=self._log_box.yview)
        self._log_box.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._log_box.pack(fill="both", expand=True, padx=4, pady=4)

    def _file_row(self, parent, label, var, cmd):
        row = ttk.Frame(parent)
        row.pack(fill="x", padx=6, pady=2)
        ttk.Label(row, text=label, width=20, anchor="w").pack(side="left")
        ttk.Entry(row, textvariable=var).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(row, text="Change…", command=cmd).pack(side="left", padx=4)
        return row

    # ── VTT section with collapsible Whisper panel ────────────────────────────

    def _build_vtt_section(self, parent):
        # Container so Whisper panel slots in between VTT row and Timestamps row
        self._vtt_section = ttk.Frame(parent)
        self._vtt_section.pack(fill="x")

        # VTT file row
        row = ttk.Frame(self._vtt_section)
        row.pack(fill="x", padx=6, pady=2)
        ttk.Label(row, text="VTT Transcript:", width=20, anchor="w").pack(side="left")
        ttk.Entry(row, textvariable=self._vtt_var).pack(
            side="left", fill="x", expand=True, padx=4)
        ttk.Button(row, text="Change…", command=self._change_vtt).pack(side="left", padx=4)
        self._whisper_toggle_btn = ttk.Button(
            row, text="Generate with Whisper ▼",
            command=self._toggle_whisper)
        self._whisper_toggle_btn.pack(side="left", padx=4)

        # Whisper panel (built but not packed yet)
        self._whisper_panel = ttk.LabelFrame(
            self._vtt_section,
            text="  Generate VTT from source audio  —  local AI transcription (faster-whisper)  ")
        self._build_whisper_panel(self._whisper_panel)

    def _build_whisper_panel(self, parent):
        p = dict(padx=8, pady=2)

        # Disclaimer
        ttk.Label(
            parent,
            text=(
                "ℹ  This generates a transcript entirely on your computer — no data is sent anywhere.\n"
                "⏱  Estimated time: a few minutes for short recordings on a modern CPU; "
                "30 minutes to over an hour for a full lecture. CUDA (NVIDIA GPU) is significantly faster.\n"
                "⬇  The first time you run a model it will be downloaded automatically (~75 MB – 1.5 GB)."
            ),
            foreground="#5a4000",
            wraplength=680,
            justify="left",
        ).pack(fill="x", padx=8, pady=(6, 2))

        ttk.Separator(parent, orient="horizontal").pack(fill="x", padx=8, pady=4)

        # Settings grid
        g = ttk.Frame(parent)
        g.pack(fill="x", padx=8, pady=2)
        g.columnconfigure(1, weight=0)
        g.columnconfigure(2, weight=1)

        def setting(r, label, widget_maker, description):
            ttk.Label(g, text=label, anchor="e", width=17).grid(
                row=r, column=0, sticky="e", padx=(4, 2), pady=3)
            w = widget_maker(g)
            w.grid(row=r, column=1, sticky="w", padx=4, pady=3)
            ttk.Label(g, text=description, foreground="gray", anchor="w").grid(
                row=r, column=2, sticky="w", padx=6, pady=3)
            return w

        # Model
        setting(0, "Model:",
                lambda p: ttk.Combobox(p, textvariable=self._w_model, width=14,
                    values=[m[0] for m in _MODELS], state="readonly"),
                "turbo = best balance  |  large-v3 = highest accuracy  |  tiny = testing only")

        # Device
        dev_cb = setting(1, "Device:",
                lambda p: ttk.Combobox(p, textvariable=self._w_device, width=14,
                    values=[d[0] for d in _DEVICES], state="readonly"),
                "cpu = any computer (slower)  |  cuda = NVIDIA GPU only (much faster)")
        dev_cb.bind("<<ComboboxSelected>>", self._on_device_change)

        # Compute type
        self._compute_cb = setting(2, "Compute type:",
                lambda p: ttk.Combobox(p, textvariable=self._w_compute, width=14,
                    values=[c[0] for c in _CPU_COMPUTE], state="readonly"),
                "Numerical precision used during inference. int8 is fastest on CPU.")

        # Language
        setting(3, "Language:",
                lambda p: ttk.Entry(p, textvariable=self._w_lang, width=10),
                "Language code: en, fr, de, zh, etc.  Leave blank or 'auto' to detect automatically.")

        # Beam size
        setting(4, "Beam size:",
                lambda p: ttk.Spinbox(p, textvariable=self._w_beam,
                    from_=1, to=20, width=6),
                "Decoding search width. Higher = more accurate but slower. Default: 5.")

        # Checkboxes
        chk = ttk.Frame(parent)
        chk.pack(fill="x", padx=12, pady=(2, 0))
        ttk.Checkbutton(chk, text="VAD filter  (skip silence / non-speech regions)",
                        variable=self._w_vad).pack(side="left", padx=8)
        ttk.Checkbutton(chk, text="Word-level timestamps",
                        variable=self._w_word_ts).pack(side="left", padx=8)
        ttk.Checkbutton(chk, text="Skip if transcript already exists",
                        variable=self._w_skip).pack(side="left", padx=8)

        # Initial prompt
        pr = ttk.Frame(parent)
        pr.pack(fill="x", padx=8, pady=(4, 0))
        ttk.Label(pr, text="Initial prompt:", anchor="w").pack(side="left")
        ttk.Entry(pr, textvariable=self._w_prompt).pack(
            side="left", fill="x", expand=True, padx=6)

        ttk.Label(
            parent,
            text=(
                "Optional — provide vocabulary or context to improve accuracy for specialised content.\n"
                'Example: "Australian university lecture. Mining engineering: orebody, stope, tailings, '
                'haul truck, longwall, block caving, geotechnical."'
            ),
            foreground="gray", wraplength=680, justify="left",
        ).pack(fill="x", padx=12, pady=(2, 4))

        # faster-whisper install notice
        if not _whisper_available():
            ttk.Label(
                parent,
                text="⚠  faster-whisper is not installed.  Run:  pip install faster-whisper",
                foreground="#c0392b",
            ).pack(fill="x", padx=8, pady=2)

        # Generate button + progress bar
        btn_row = ttk.Frame(parent)
        btn_row.pack(fill="x", padx=8, pady=(4, 8))
        self._gen_btn = ttk.Button(
            btn_row, text="▶  Generate Transcript VTT",
            command=self._run_generate_vtt)
        self._gen_btn.pack(side="left")
        self._gen_progress = ttk.Progressbar(
            btn_row, mode="indeterminate", length=220)
        self._gen_progress.pack(side="left", padx=12)

    def _toggle_whisper(self):
        if self._whisper_open:
            self._whisper_panel.pack_forget()
            self._whisper_toggle_btn.configure(text="Generate with Whisper ▼")
            self._whisper_open = False
        else:
            self._whisper_panel.pack(fill="x", padx=6, pady=(0, 4))
            self._whisper_toggle_btn.configure(text="Generate with Whisper ▲")
            self._whisper_open = True

    def _on_device_change(self, _=None):
        if self._w_device.get() == "cuda":
            vals = [c[0] for c in _GPU_COMPUTE]
            self._w_compute.set("float16")
        else:
            vals = [c[0] for c in _CPU_COMPUTE]
            self._w_compute.set("int8")
        self._compute_cb.configure(values=vals)

    # ── cloud-path warning ────────────────────────────────────────────────────

    def _on_outdir_change(self, *_):
        if _is_cloud_path(self._outdir_var.get()):
            self._cloud_warn_lbl.pack(fill="x", padx=8, pady=(0, 6))
        else:
            self._cloud_warn_lbl.pack_forget()

    # ── browse helpers ────────────────────────────────────────────────────────

    def _browse_ffmpeg(self):
        p = filedialog.askopenfilename(
            title="Select ffmpeg.exe",
            filetypes=[("Executable", "ffmpeg.exe *.exe"), ("All files", "*")])
        if p:
            self._ffmpeg_var.set(p)

    def _browse_workdir(self):
        d = filedialog.askdirectory(title="Select Working Directory")
        if d:
            self._workdir_var.set(d)
            self._auto_detect(Path(d))

    def _browse_outdir(self):
        d = filedialog.askdirectory(title="Select Output Directory")
        if d:
            self._outdir_var.set(d)

    def _change_audio(self):
        p = filedialog.askopenfilename(
            title="Select audio/video file",
            filetypes=[("Audio/Video", "*.mp3 *.mp4 *.m4a"), ("All files", "*")])
        if p:
            self._audio_var.set(p)

    def _change_vtt(self):
        p = filedialog.askopenfilename(
            title="Select VTT transcript",
            filetypes=[("WebVTT", "*.vtt"), ("All files", "*")])
        if p:
            self._vtt_var.set(p)

    def _change_ts(self):
        p = filedialog.askopenfilename(
            title="Select timestamps markdown",
            filetypes=[("Markdown", "*.md"), ("All files", "*")])
        if p:
            self._ts_var.set(p)

    # ── auto-detect ───────────────────────────────────────────────────────────

    def _auto_detect(self, folder: Path):
        for ext in (".mp3", ".m4a", ".mp4"):
            hits = sorted(folder.glob(f"*{ext}"))
            if hits:
                self._audio_var.set(str(hits[0]))
                break

        vtts = [p for p in sorted(folder.glob("*.vtt"))
                if "vtt_out" not in p.parts and "output" not in p.parts]
        if vtts:
            self._vtt_var.set(str(vtts[0]))
        else:
            self._vtt_var.set("")
            self._log("No VTT transcript found.  Use 'Generate with Whisper' to create one.")

        mds = sorted(folder.glob("*timestamps*.md"),
                     key=lambda x: x.stat().st_mtime, reverse=True)
        if not mds:
            mds = sorted(folder.glob("*.md"),
                         key=lambda x: x.stat().st_mtime, reverse=True)
        if mds:
            self._ts_var.set(str(mds[0]))

        if not self._outdir_var.get():
            self._outdir_var.set(str(folder / "output"))

        self._log(f"Auto-detected files in: {folder}")

    # ── VTT generation ────────────────────────────────────────────────────────

    def _run_generate_vtt(self):
        audio  = self._audio_var.get().strip()
        outdir = self._outdir_var.get().strip()

        errors = []
        if not audio or not Path(audio).exists():
            errors.append("No audio file selected — set the Audio / Video field first.")
        if not outdir:
            errors.append("No output directory set.")
        if not _whisper_available():
            errors.append(
                "faster-whisper is not installed.\n"
                "Open a terminal and run:  pip install faster-whisper")
        if errors:
            messagebox.showerror("Cannot generate VTT", "\n\n".join(errors))
            return

        # Transcript goes into the output directory alongside the MP3 segments
        out_vtt = Path(outdir) / (Path(audio).stem + "_transcript.vtt")

        if self._w_skip.get() and out_vtt.exists():
            self._vtt_var.set(str(out_vtt))
            self._log(f"Existing transcript found, using: {out_vtt}")
            return

        try:
            beam_size = int(self._w_beam.get())
        except ValueError:
            beam_size = 5

        self._gen_btn.configure(state="disabled")
        self._gen_progress.start(10)
        self._log_clear()
        self._log(f"Generating transcript for: {Path(audio).name}")
        self._log(f"Output VTT: {out_vtt}\n")

        def done(ok, vtt_path):
            self.after(0, lambda: self._gen_btn.configure(state="normal"))
            self.after(0, lambda: self._gen_progress.stop())
            if ok and vtt_path:
                self.after(0, lambda: self._vtt_var.set(vtt_path))
                self.after(0, lambda: self._log(
                    "\n✓ Transcript ready.  "
                    "You can now click  ▶ Cut Audio + Generate VTTs."))

        threading.Thread(
            target=generate_vtt_worker,
            args=(
                audio, out_vtt,
                self._w_model.get(), self._w_device.get(), self._w_compute.get(),
                self._w_lang.get(), beam_size,
                self._w_vad.get(), self._w_word_ts.get(), self._w_prompt.get(),
                lambda msg: self.after(0, lambda m=msg: self._log(m)),
                done,
            ),
            daemon=True,
        ).start()

    # ── main cut ──────────────────────────────────────────────────────────────

    def _run(self):
        ffmpeg = self._ffmpeg_var.get().strip()
        audio  = self._audio_var.get().strip()
        vtt    = self._vtt_var.get().strip()
        ts     = self._ts_var.get().strip()
        outdir = self._outdir_var.get().strip()

        errors = []
        if not ffmpeg or not Path(ffmpeg).exists():
            errors.append(
                "ffmpeg.exe not found.\n"
                "Place ffmpeg.exe next to this script, or browse to it above.\n"
                "Download: https://ffmpeg.org/download.html")
        if not audio or not Path(audio).exists():
            errors.append("No audio/video file selected.")
        if not ts or not Path(ts).exists():
            errors.append("No timestamps markdown file selected.")
        if not outdir:
            errors.append("No output directory specified.")
        if errors:
            messagebox.showerror("Cannot start", "\n\n".join(errors))
            return

        self._run_btn.configure(state="disabled", text="⏳  Running…")
        self._log_clear()
        self._log(f"ffmpeg:     {ffmpeg}")
        self._log(f"Audio:      {audio}")
        self._log(f"VTT:        {vtt or '(none — subtitles will not be generated)'}")
        self._log(f"Timestamps: {ts}")
        self._log(f"Output:     {outdir}\n")

        def done(ok):
            self.after(0, lambda: self._run_btn.configure(
                state="normal", text="▶  Cut Audio  +  Generate VTTs"))

        threading.Thread(
            target=run_job,
            args=(ffmpeg, audio, vtt or None, ts, outdir,
                  lambda msg: self.after(0, lambda m=msg: self._log(m)),
                  done),
            daemon=True,
        ).start()

    # ── log ───────────────────────────────────────────────────────────────────

    def _log(self, msg: str):
        self._log_box.configure(state="normal")
        self._log_box.insert("end", msg + "\n")
        self._log_box.see("end")
        self._log_box.configure(state="disabled")

    def _log_clear(self):
        self._log_box.configure(state="normal")
        self._log_box.delete("1.0", "end")
        self._log_box.configure(state="disabled")


if __name__ == "__main__":
    app = App()
    app.mainloop()
