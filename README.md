# Lecture Cutter

Splits a lecture audio or video file into shorter clips based on a timestamp table, and generates matching VTT subtitle files for each clip.

Built for use with PowerPoint narration, LMS uploads, or any workflow where one long lecture recording needs to become many labelled segments.

---

## Use Case

You have recorded a lecture as a single MP3, MP4, or M4A file. You want to:

1. Cut it into individually-named clips (one per slide or topic)
2. Have a matching `.vtt` subtitle file for each clip, time-rebased to start at `00:00:00`
3. Do all of this without writing any code or opening a terminal

---

## Prerequisites

### 1 — Python 3.10 or later

Download from [python.org](https://www.python.org/downloads/).  
During installation, tick **"Add Python to PATH"**.  
No extra packages are required — only the Python standard library is used.

### 2 — ffmpeg

Download a Windows build from [ffmpeg.org](https://ffmpeg.org/download.html) (look for a "Windows builds" link, e.g. from gyan.dev or BtbN).

For portable use (no install, no admin rights):

- Extract the download
- Copy `ffmpeg.exe` from the `bin/` folder into the same folder as `lecture_cutter.py`

The app will find it automatically. If you already have ffmpeg installed system-wide, it will be detected from PATH.

---

## Preparing Your Files

Place these three files in the same folder (your **working directory**):

| File | Description |
|------|-------------|
| `lecture.mp3` / `.mp4` / `.m4a` | Your source recording |
| `lecture.vtt` | WebVTT transcript (see below if you don't have one) |
| `lecture-timestamps.md` | Markdown table defining where each clip starts and ends |

### Timestamp Table Format

The timestamps file must be a Markdown table with this structure:

```markdown
# My Lecture Title

| Start    | - | Stop     | Title                          |
| :------: | - | :------: | :----------------------------- |
| 0:00:00  | - | 0:05:10  | 1. Introduction                |
| 0:05:10  | - | 0:08:45  | 2. Background                  |
| 0:08:45  | - | 0:14:22  | 3. Main Concepts               |
```

- **Start / Stop** — timestamp in `H:MM:SS` or `HH:MM:SS` format
- **Title** — becomes the output filename (characters like `/ \ : * ? " < > |` are replaced with `-`)
- The middle column (`-`) is a visual separator and is ignored

The file must contain `-timestamps` somewhere in its name (e.g. `lecture-timestamps.md`) so the app can auto-detect it.

---

## Getting a VTT Transcript

A `.vtt` file contains the spoken words of your lecture, time-coded. The app uses it to produce per-clip subtitle files.

**The VTT file is optional.** If you don't have one, the app will still cut your audio — it just won't generate subtitles.

### Option A — Microsoft Copilot / Teams (recommended if available)

If your lecture was recorded in Microsoft Teams or uploaded to Stream:

1. Open the recording in **Microsoft Stream**
2. Go to the transcript panel → click the `⋯` menu → **Download transcript**
3. Save the `.vtt` file into your working directory

### Option B — `make_vtt` tool (this repository)

The `make_vtt` tool (located in a separate folder in this repo) can generate a VTT from an audio file using a speech-to-text model.  
See the `make_vtt` folder for its own README and instructions.

### Option C — Local LLM / Whisper (coming soon)

A local Whisper-based transcription option is planned for a future release. It will work fully offline with no cloud dependency.

---

## Running the App

Double-click **`run.bat`**.

This opens the GUI:

```
┌─────────────────────────────────────────────────────────┐
│  ffmpeg executable    [path/to/ffmpeg.exe]  [Browse…]   │
│  Working Directory    [path/to/folder    ]  [Browse…]   │
│                                                         │
│  Input Files                                            │
│    Audio / Video:     [auto-detected     ]  [Change…]   │
│    VTT Transcript:    [auto-detected     ]  [Change…]   │
│    Timestamps (.md):  [auto-detected     ]  [Change…]   │
│                                                         │
│  Output Directory     [path/to/output   ]  [Browse…]    │
│                                                         │
│  [ ▶  Cut Audio  +  Generate VTTs ]                     │
│                                                         │
│  Log ─────────────────────────────────────────────────  │
│  Output directory ready.                                │
│  Found 28 segments in timestamps file.                  │
│  [1/28] 1. Introduction.mp3  (0:00:00 → 0:05:10)       │
│    ✓ saved                                              │
│  ...                                                    │
└─────────────────────────────────────────────────────────┘
```

### Steps

1. **Working Directory** — browse to the folder containing your audio, VTT, and timestamps files. The three input files are detected automatically.
2. **Override if needed** — if a file was misidentified, click **Change…** next to it and select the correct file.
3. **Output Directory** — defaults to an `output/` subfolder in your working directory. Change it to any folder you have write access to (e.g. your Desktop).
4. Click **▶ Cut Audio + Generate VTTs** and watch the log.

### Output

| Path | Contents |
|------|----------|
| `output/1. Introduction.mp3` | One MP3 per timestamp row |
| `output/vtt_out/1. Introduction.vtt` | Matching VTT, rebased to `00:00:00` |
| `output/vtt_files.zip` | All VTTs zipped for easy upload |

---

## Troubleshooting

**"Output directory still does not exist" / "not writable"**  
The app cannot create folders in a restricted location (network drives, OneDrive-managed folders, or drives where you don't have write permission). Change the Output Directory to a local path such as `C:\Users\YourName\Desktop\output`.

**"No valid timestamp rows found"**  
Check that your timestamps file name contains `-timestamps` and that your time values match `H:MM:SS` or `HH:MM:SS` format. Single-digit hours (`0:05:10`) are supported.

**ffmpeg not found**  
Place `ffmpeg.exe` in the same folder as `lecture_cutter.py`, or use the Browse button in the ffmpeg row to point to it manually.

**Clip is shorter / longer than expected**  
ffmpeg seeks to the nearest keyframe, which can differ by a fraction of a second for MP3 files. This is normal behaviour for VBR audio.

---

## File Structure

```
lecture-cutter/
├── lecture_cutter.py       ← main GUI app
├── run.bat                 ← double-click launcher
├── ffmpeg.exe              ← place here for portable use
├── README.md               ← this file
│
└── M6A/                    ← example working directory
    ├── M6_JORC Code_Part A.mp3
    ├── M06A_JORC Code.vtt
    ├── lecture-timestamps.md
    └── output/             ← created on first run
```
