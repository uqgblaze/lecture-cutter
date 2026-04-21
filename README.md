# Lecture Cutter v2.1

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
No extra packages are required for basic use — only the Python standard library is used.

### 2 — ffmpeg

Download a Windows build from [ffmpeg.org](https://ffmpeg.org/download.html) (look for a "Windows builds" link, e.g. from gyan.dev or BtbN).

For portable use (no install, no admin rights):

- Extract the download
- Copy `ffmpeg.exe` from the `bin/` folder into the same folder as `lecture_cutter.py`

The app will find it automatically. If you already have ffmpeg installed system-wide, it will be detected from PATH.

### 3 — faster-whisper (optional — only needed to generate transcripts)

If you want the app to generate a VTT transcript from your audio (rather than supplying one), install the `faster-whisper` package:

```
pip install faster-whisper
```

If this package is not installed, the transcript generation panel will display an install reminder. All other features work without it.

---

## Preparing Your Files

Place these files in the same folder (your **working directory**):

| File | Required | Description |
|------|----------|-------------|
| `lecture.mp3` / `.mp4` / `.m4a` | Yes | Your source recording |
| `lecture-timestamps.md` | Yes | Markdown table defining where each clip starts and ends |
| `lecture.vtt` | No | WebVTT transcript — used to generate per-clip subtitles |

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

The file must contain `timestamps` somewhere in its name (e.g. `lecture-timestamps.md`) so the app can auto-detect it.

---

## Getting a VTT Transcript

A `.vtt` file contains the spoken words of your lecture, time-coded. The app uses it to produce per-clip subtitle files.

**The VTT file is optional.** If you don't have one, the app will still cut your audio — it just won't generate subtitles.

### Option A — Microsoft Teams / Stream (recommended if available)

If your lecture was recorded in Microsoft Teams or uploaded to Stream:

1. Open the recording in **Microsoft Stream**
2. Go to the transcript panel → click the `⋯` menu → **Download transcript**
3. Save the `.vtt` file into your working directory

### Option B — Generate inside the app using Whisper (built-in, v2.1+)

The app can generate a transcript directly from your source audio using a local AI model (faster-whisper / OpenAI Whisper). No data is sent anywhere — everything runs on your computer.

See [Generating a Transcript with Whisper](#generating-a-transcript-with-whisper) below for full details.

### Option C — `make_vtt` tool (this repository)

The `make_vtt` tool (located in a separate folder in this repo) can batch-generate VTT files from a folder of MP3s using the same Whisper engine.  
See the `make_vtt` folder for its own README and instructions.

---

## Running the App

Double-click **`run.bat`**.

This opens the GUI:

```
┌──────────────────────────────────────────────────────────────────┐
│  ffmpeg executable    [path/to/ffmpeg.exe]         [Browse…]     │
│  Working Directory    [path/to/folder    ]         [Browse…]     │
│                                                                  │
│  Input Files                                                     │
│    Audio / Video:     [auto-detected     ]         [Change…]     │
│    VTT Transcript:    [auto-detected     ] [Change…] [Whisper ▼] │
│    Timestamps (.md):  [auto-detected     ]         [Change…]     │
│                                                                  │
│  Output Directory     [path/to/output   ]          [Browse…]     │
│                                                                  │
│  [ ▶  Cut Audio  +  Generate VTTs ]                              │
│                                                                  │
│  Log ──────────────────────────────────────────────────────────  │
│  Output directory ready.                                         │
│  Found 28 segments in timestamps file.                           │
│  [1/28] 1. Introduction.mp3  (0:00:00 → 0:05:10)                │
│    ✓ saved                                                       │
│  ...                                                             │
└──────────────────────────────────────────────────────────────────┘
```

### Steps

1. **Working Directory** — browse to the folder containing your audio and timestamps files. All input files are detected automatically.
2. **Override if needed** — if a file was misidentified, click **Change…** next to it and select the correct file.
3. **VTT Transcript** — if a VTT was found it will be auto-populated. If not, see [Generating a Transcript with Whisper](#generating-a-transcript-with-whisper) below.
4. **Output Directory** — defaults to an `output/` subfolder in your working directory. **Must be a local folder** — see the warning below.
5. Click **▶ Cut Audio + Generate VTTs** and watch the log.

### Output Directory — Important

> ⚠ **Do not save to OneDrive, iCloud, Google Drive, SharePoint, or any other cloud-synced folder.** These locations prevent the app from creating the output directory, causing the conversion to fail silently. Choose a local directory (e.g. `C:\Users\You\Desktop\output`) and upload the finished files when complete.

The app will display a red warning automatically if it detects a cloud path.

### Output Files

| Path | Contents |
|------|----------|
| `output/1. Introduction.mp3` | One MP3 per timestamp row |
| `output/vtt_out/1. Introduction.vtt` | Matching VTT, rebased to `00:00:00` |
| `output/vtt_files.zip` | All VTTs zipped for easy upload |
| `output/lecture_transcript.vtt` | Full-lecture transcript (only if generated by Whisper) |

---

## Generating a Transcript with Whisper

If no VTT file is available, the app can transcribe your source audio locally using [faster-whisper](https://github.com/SYSTRAN/faster-whisper).

Click **Generate with Whisper ▼** in the VTT Transcript row to expand the panel.

> ⏱ **Time estimate:** a few minutes for short recordings on a modern CPU; 30 minutes to over an hour for a full lecture. Using a CUDA-capable NVIDIA GPU is significantly faster.  
> ⬇ The first time you use a model it will be downloaded automatically (75 MB – 1.5 GB depending on model size).

### Settings

| Setting | Description |
|---------|-------------|
| **Model** | Controls the size/accuracy trade-off. **Turbo** is recommended for most users. Use **Large v3** for the highest possible accuracy. Use **Tiny** or **Base** only for testing. |
| **Device** | `cpu` works on any computer. `cuda` requires an NVIDIA GPU and is typically 5–10× faster. |
| **Compute type** | Numerical precision used during inference. `int8` is fastest on CPU with minimal quality loss. `float16` is best for NVIDIA GPUs. Updates automatically when you change Device. |
| **Language** | Two-letter language code (`en`, `fr`, `de`, `zh`, etc.). Leave blank or set to `auto` to detect automatically. |
| **Beam size** | Search width during decoding. Higher values improve accuracy at the cost of speed. Default is 5. |
| **VAD filter** | Skips silence and non-speech regions, reducing processing time. Recommended on. |
| **Word-level timestamps** | Produces timestamps for each individual word rather than each phrase. Not all players support this. |
| **Skip if transcript exists** | If a transcript VTT for this audio already exists in the output folder, reuse it instead of re-transcribing. |
| **Initial prompt** | Optional freeform text to help the model recognise domain-specific vocabulary. Useful for technical lectures. Example: `"Australian university lecture. Mining engineering: orebody, stope, tailings, longwall, haul truck."` |

### Model Size Reference

| Model | Size | Speed | Best for |
|-------|------|-------|----------|
| Turbo | ~810 MB | Fast | General use — recommended starting point |
| Medium | ~780 MB | Moderate | Good accuracy, reasonable speed |
| Large v3 | ~1.5 GB | Slow | Highest accuracy, complex content |
| Small | ~250 MB | Fast | Clear speech, less technical content |
| Base | ~150 MB | Very fast | Basic transcription only |
| Tiny | ~75 MB | Fastest | Testing only |

### Workflow

1. Set your **Audio / Video** and **Output Directory** fields first.
2. Expand the Whisper panel and configure settings.
3. Click **▶ Generate Transcript VTT**.
4. The transcript is saved as `{audio_name}_transcript.vtt` in your output directory and the VTT field is populated automatically.
5. Click **▶ Cut Audio + Generate VTTs** to proceed with cutting.

---

## Troubleshooting

**"Output directory still does not exist" / "not writable"**  
The app cannot create folders in a cloud-synced or restricted location. Change the Output Directory to a local path such as `C:\Users\YourName\Desktop\output`.

**"No valid timestamp rows found"**  
Check that your timestamps file name contains `timestamps` and that your time values match `H:MM:SS` or `HH:MM:SS` format. Single-digit hours (`0:05:10`) are supported.

**ffmpeg not found**  
Place `ffmpeg.exe` in the same folder as `lecture_cutter.py`, or use the Browse button to point to it manually.

**"faster-whisper is not installed"**  
Open a terminal and run `pip install faster-whisper`. The panel will show this reminder if the package is missing.

**Whisper generates poor results**  
Try a larger model (Medium or Large v3). Add domain vocabulary to the **Initial prompt** field. Make sure **VAD filter** is on. If the language is being misdetected, set it explicitly.

**Clip is shorter / longer than expected**  
ffmpeg seeks to the nearest keyframe, which can differ by a fraction of a second for MP3 files. This is normal behaviour for VBR audio.

---

## File Structure

```
mp3_cutter_v2.0/
├── lecture_cutter.py       ← main GUI app (v2.1)
├── run.bat                 ← double-click launcher
├── ffmpeg.exe              ← place here for portable use
├── README.md               ← this file
│
└── M6A/                    ← example working directory
    ├── M6_JORC Code_Part A.mp3
    ├── M06A_JORC Code.vtt
    ├── lecture-timestamps.md
    └── output/             ← created on first run
        ├── 1. Introduction.mp3
        ├── ...
        ├── lecture_transcript.vtt
        ├── vtt_files.zip
        └── vtt_out/
            ├── 1. Introduction.vtt
            └── ...
```
