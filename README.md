# ComfyUI-VACE-Tools

ComfyUI custom nodes for WanVideo/VACE workflows — mask/control-frame generation and model saving.

## Installation

```bash
cd ComfyUI/custom_nodes/
git clone https://github.com/ethanfel/Comfyui-VACE-Tools.git
```

Restart ComfyUI. Nodes appear under the **VACE Tools** and **WanVideoWrapper** categories.

## Node: VACE Source Prep

Trims long source clips so they can be used with VACE Mask Generator. Place this node **before** the mask generator when your source clip has more frames than `target_frames`. It selects the relevant frames based on mode and outputs adjusted parameters to wire directly into the mask generator.

Irrelevant widgets are automatically hidden based on the selected mode.

### Inputs

| Input | Type | Default | Description |
|---|---|---|---|
| `source_clip` | IMAGE | — | Full source video frames (B, H, W, C tensor). |
| `mode` | ENUM | `End Extend` | Generation mode — must match the mask generator's mode. |
| `split_index` | INT | `0` | Split position in the full source video (0 = auto-middle for Middle Extend). Same meaning as the mask generator's split_index. |
| `input_left` | INT | `0` | Frames from the left side of the split point to keep (0 = all available). End: trailing context. Middle: frames before split. Edge/Join: start edge size. Bidirectional: trailing context. Replace: context before region. |
| `input_right` | INT | `0` | Frames from the right side of the split point to keep (0 = all available). Pre: leading reference. Middle: frames after split. Edge/Join: end edge size. Replace: context after region. |
| `edge_frames` | INT | `8` | Default edge size for Edge/Join modes (overridden by input_left/input_right if non-zero). Replace/Inpaint: number of frames to replace. |
| `source_clip_2` | IMAGE | *(optional)* | Second clip for Join Extend — join two separate clips instead of splitting one in half. |
| `inpaint_mask` | MASK | *(optional)* | Spatial inpaint mask — trimmed to match output frames for Video Inpaint mode. |
| `keyframe_positions` | STRING | *(optional)* | Keyframe positions pass-through for Keyframe mode. |

### Outputs

| Output | Type | Description |
|---|---|---|
| `trimmed_clip` | IMAGE | Trimmed frames — wire to mask generator's source_clip. |
| `mode` | ENUM | Selected mode — wire to mask generator's mode. |
| `split_index` | INT | Adjusted for the trimmed clip — wire to mask generator. |
| `edge_frames` | INT | Adjusted/passed through — wire to mask generator. |
| `inpaint_mask` | MASK | Trimmed to match output, or placeholder. |
| `keyframe_positions` | STRING | Pass-through. |
| `vace_pipe` | VACE_PIPE | Pipe carrying mode, trim bounds, and context frame counts — wire to VACE Merge Back. |

### Per-Mode Trimming

| Mode | input_left | input_right | Behavior |
|---|---|---|---|
| End Extend | Trailing context frames | — | Keeps last N frames |
| Pre Extend | — | Leading reference frames | Keeps first N frames |
| Middle Extend | Frames before split | Frames after split | Window around split_index |
| Edge Extend | Start edge size | End edge size | Overrides edge_frames; forced symmetric (min of both) |
| Join Extend | Edge from first half/clip | Edge from second half/clip | Edge context around midpoint (or between two clips if source_clip_2 connected); forced symmetric |
| Bidirectional | Trailing context frames | — | Keeps last N frames |
| Frame Interpolation | — | — | Pass-through (no trimming) |
| Replace/Inpaint | Context before region | Context after region | Window around replace region |
| Video Inpaint | — | — | Pass-through (no trimming) |
| Keyframe | — | — | Pass-through (no trimming) |

---

## Node: VACE Mask Generator

Builds mask and control_frames sequences for all VACE generation modes. Works standalone for short clips, or downstream of VACE Source Prep for long clips.

**Note:** For modes that use `target_frames` (End, Pre, Middle, Edge, Join, Bidirectional, Keyframe), `source_clip` must not have more frames than `target_frames`. If your source is longer, use VACE Source Prep upstream to trim it first.

### Inputs

| Input | Type | Default | Description |
|---|---|---|---|
| `source_clip` | IMAGE | — | Source video frames (B, H, W, C tensor). Must not exceed target_frames for modes that use it. |
| `mode` | ENUM | `End Extend` | Generation mode (see below). 10 modes available. |
| `target_frames` | INT | `81` | Total output frame count for mask and control_frames (1–10000). Used by Keyframe to set output length. Unused by Frame Interpolation, Replace/Inpaint, and Video Inpaint. |
| `split_index` | INT | `0` | Where to split the source. Middle: split frame index (0 = auto-middle). Bidirectional: frames before clip (0 = even split). Frame Interpolation: new frames per gap. Replace/Inpaint: start index of replace region. Unused by End/Pre/Edge/Join/Video Inpaint/Keyframe. Raises an error if out of range. |
| `edge_frames` | INT | `8` | Number of edge frames for Edge and Join modes. Replace/Inpaint: number of frames to replace. Unused by End/Pre/Middle/Bidirectional/Frame Interpolation/Video Inpaint/Keyframe. |
| `inpaint_mask` | MASK | *(optional)* | Spatial inpaint mask for Video Inpaint mode (B, H, W). White (1.0) = regenerate, Black (0.0) = keep. Single frame broadcasts to all source frames. |
| `keyframe_positions` | STRING | *(optional)* | Comma-separated frame indices for Keyframe mode (e.g. `0,20,50,80`). One position per source frame, sorted ascending, within [0, target_frames-1]. Leave empty for even auto-spread. |

### Outputs

| Output | Description |
|---|---|
| `control_frames` | Source frames composited with grey (`#7f7f7f`) fill. Fed to VACE as visual reference. |
| `mask` | Black/white frame sequence. Black = keep, White = generate. |
| `target_frames` | INT — total frame count of the output sequence, snapped to 4n+1 (1, 5, 9, …, 81, …). Wire directly to VACE encode. |

## Mode Reference

---

### End Extend

Generate new frames **after** the source clip.

- **`split_index`** — optional trim: `0` keeps the full clip; a negative value (e.g. `-16`) drops that many frames from the end before extending.

<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 90" style="max-width:600px">
  <text y="12" font-size="11" font-family="sans-serif" fill="#888">mask</text>
  <rect x="0" y="18" width="360" height="28" rx="4" fill="#222"/>
  <text x="180" y="36" text-anchor="middle" font-size="12" font-family="sans-serif" fill="#fff">BLACK × source</text>
  <rect x="360" y="18" width="240" height="28" rx="4" fill="#fff" stroke="#ccc"/>
  <text x="480" y="36" text-anchor="middle" font-size="12" font-family="sans-serif" fill="#333">WHITE × generated</text>
  <text y="62" font-size="11" font-family="sans-serif" fill="#888">control_frames</text>
  <rect x="0" y="68" width="360" height="28" rx="4" fill="#4a9ebb"/>
  <text x="180" y="86" text-anchor="middle" font-size="12" font-family="sans-serif" fill="#fff">source clip</text>
  <rect x="360" y="68" width="240" height="28" rx="4" fill="#999"/>
  <text x="480" y="86" text-anchor="middle" font-size="12" font-family="sans-serif" fill="#fff">GREY × generated</text>
</svg>

---

### Pre Extend

Generate new frames **before** a reference portion of the source clip.

- **`split_index`** — how many frames from the start to keep as the reference tail (e.g. `24`).

<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 90" style="max-width:600px">
  <text y="12" font-size="11" font-family="sans-serif" fill="#888">mask</text>
  <rect x="0" y="18" width="240" height="28" rx="4" fill="#fff" stroke="#ccc"/>
  <text x="120" y="36" text-anchor="middle" font-size="12" font-family="sans-serif" fill="#333">WHITE × generated</text>
  <rect x="240" y="18" width="360" height="28" rx="4" fill="#222"/>
  <text x="420" y="36" text-anchor="middle" font-size="12" font-family="sans-serif" fill="#fff">BLACK × reference</text>
  <text y="62" font-size="11" font-family="sans-serif" fill="#888">control_frames</text>
  <rect x="0" y="68" width="240" height="28" rx="4" fill="#999"/>
  <text x="120" y="86" text-anchor="middle" font-size="12" font-family="sans-serif" fill="#fff">GREY × generated</text>
  <rect x="240" y="68" width="360" height="28" rx="4" fill="#4a9ebb"/>
  <text x="420" y="86" text-anchor="middle" font-size="12" font-family="sans-serif" fill="#fff">reference frames</text>
</svg>

---

### Middle Extend

Generate new frames **between** two halves of the source clip, split at `split_index`.

- **`split_index`** — frame index where the source is split (`0` = auto-middle). Raises an error if out of range.

<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 90" style="max-width:600px">
  <text y="12" font-size="11" font-family="sans-serif" fill="#888">mask</text>
  <rect x="0" y="18" width="180" height="28" rx="4" fill="#222"/>
  <text x="90" y="36" text-anchor="middle" font-size="12" font-family="sans-serif" fill="#fff">BLACK × part_a</text>
  <rect x="180" y="18" width="240" height="28" rx="4" fill="#fff" stroke="#ccc"/>
  <text x="300" y="36" text-anchor="middle" font-size="12" font-family="sans-serif" fill="#333">WHITE × generated</text>
  <rect x="420" y="18" width="180" height="28" rx="4" fill="#222"/>
  <text x="510" y="36" text-anchor="middle" font-size="12" font-family="sans-serif" fill="#fff">BLACK × part_b</text>
  <text y="62" font-size="11" font-family="sans-serif" fill="#888">control_frames</text>
  <rect x="0" y="68" width="180" height="28" rx="4" fill="#4a9ebb"/>
  <text x="90" y="86" text-anchor="middle" font-size="12" font-family="sans-serif" fill="#fff">part_a</text>
  <rect x="180" y="68" width="240" height="28" rx="4" fill="#999"/>
  <text x="300" y="86" text-anchor="middle" font-size="12" font-family="sans-serif" fill="#fff">GREY × generated</text>
  <rect x="420" y="68" width="180" height="28" rx="4" fill="#4a9ebb"/>
  <text x="510" y="86" text-anchor="middle" font-size="12" font-family="sans-serif" fill="#fff">part_b</text>
</svg>

---

### Edge Extend

Generate a transition **between the end and start** of a clip (useful for looping).

- **`edge_frames`** — number of frames taken from each edge.
- **`split_index`** — unused.

The end segment is placed first, then the generated gap, then the start segment — so the model learns to connect the clip's end back to its beginning.

<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 90" style="max-width:600px">
  <text y="12" font-size="11" font-family="sans-serif" fill="#888">mask</text>
  <rect x="0" y="18" width="150" height="28" rx="4" fill="#222"/>
  <text x="75" y="36" text-anchor="middle" font-size="12" font-family="sans-serif" fill="#fff">BLACK × end_seg</text>
  <rect x="150" y="18" width="300" height="28" rx="4" fill="#fff" stroke="#ccc"/>
  <text x="300" y="36" text-anchor="middle" font-size="12" font-family="sans-serif" fill="#333">WHITE × generated</text>
  <rect x="450" y="18" width="150" height="28" rx="4" fill="#222"/>
  <text x="525" y="36" text-anchor="middle" font-size="12" font-family="sans-serif" fill="#fff">BLACK × start_seg</text>
  <text y="62" font-size="11" font-family="sans-serif" fill="#888">control_frames</text>
  <rect x="0" y="68" width="150" height="28" rx="4" fill="#4a9ebb"/>
  <text x="75" y="86" text-anchor="middle" font-size="12" font-family="sans-serif" fill="#fff">end_seg</text>
  <rect x="150" y="68" width="300" height="28" rx="4" fill="#999"/>
  <text x="300" y="86" text-anchor="middle" font-size="12" font-family="sans-serif" fill="#fff">GREY × generated</text>
  <rect x="450" y="68" width="150" height="28" rx="4" fill="#4a9ebb"/>
  <text x="525" y="86" text-anchor="middle" font-size="12" font-family="sans-serif" fill="#fff">start_seg</text>
</svg>

---

### Join Extend

Heal/blend **two halves** of a clip (or two separate clips) together. By default, the source is split in half; `edge_frames` from each side of the split form the context. If `source_clip_2` is connected (via VACE Source Prep), the two clips are joined directly instead.

- **`edge_frames`** — context frames taken from each side of the join point.
- **`split_index`** — unused.

<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 170" style="max-width:600px">
  <!-- Single clip source layout -->
  <text y="12" font-size="11" font-family="sans-serif" fill="#888">single clip source</text>
  <rect x="0" y="18" width="120" height="24" rx="4" fill="#4a9ebb" opacity="0.4"/>
  <text x="60" y="34" text-anchor="middle" font-size="11" font-family="sans-serif" fill="#fff">part_1</text>
  <rect x="120" y="18" width="120" height="24" rx="4" fill="#4a9ebb"/>
  <text x="180" y="34" text-anchor="middle" font-size="11" font-family="sans-serif" fill="#fff">part_2</text>
  <rect x="240" y="18" width="120" height="24" rx="4" fill="#4a9ebb"/>
  <text x="300" y="34" text-anchor="middle" font-size="11" font-family="sans-serif" fill="#fff">part_3</text>
  <rect x="360" y="18" width="120" height="24" rx="4" fill="#4a9ebb" opacity="0.4"/>
  <text x="420" y="34" text-anchor="middle" font-size="11" font-family="sans-serif" fill="#fff">part_4</text>
  <line x1="120" y1="44" x2="240" y2="44" stroke="#666" stroke-dasharray="4"/>
  <text x="180" y="54" text-anchor="middle" font-size="10" font-family="sans-serif" fill="#666">← edge → ← edge →</text>
  <!-- Mask bar -->
  <text y="72" font-size="11" font-family="sans-serif" fill="#888">mask</text>
  <rect x="0" y="78" width="150" height="28" rx="4" fill="#222"/>
  <text x="75" y="96" text-anchor="middle" font-size="12" font-family="sans-serif" fill="#fff">BLACK × part_2</text>
  <rect x="150" y="78" width="300" height="28" rx="4" fill="#fff" stroke="#ccc"/>
  <text x="300" y="96" text-anchor="middle" font-size="12" font-family="sans-serif" fill="#333">WHITE × generated</text>
  <rect x="450" y="78" width="150" height="28" rx="4" fill="#222"/>
  <text x="525" y="96" text-anchor="middle" font-size="12" font-family="sans-serif" fill="#fff">BLACK × part_3</text>
  <!-- Control bar -->
  <text y="122" font-size="11" font-family="sans-serif" fill="#888">control_frames</text>
  <rect x="0" y="128" width="150" height="28" rx="4" fill="#4a9ebb"/>
  <text x="75" y="146" text-anchor="middle" font-size="12" font-family="sans-serif" fill="#fff">part_2</text>
  <rect x="150" y="128" width="300" height="28" rx="4" fill="#999"/>
  <text x="300" y="146" text-anchor="middle" font-size="12" font-family="sans-serif" fill="#fff">GREY × generated</text>
  <rect x="450" y="128" width="150" height="28" rx="4" fill="#4a9ebb"/>
  <text x="525" y="146" text-anchor="middle" font-size="12" font-family="sans-serif" fill="#fff">part_3</text>
</svg>

---

### Bidirectional Extend

Generate new frames **both before and after** the source clip.

- **`split_index`** — number of generated frames to place before the clip. `0` = even split (half before, half after).
- **`target_frames`** — total output frame count.

<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 90" style="max-width:600px">
  <text y="12" font-size="11" font-family="sans-serif" fill="#888">mask</text>
  <rect x="0" y="18" width="150" height="28" rx="4" fill="#fff" stroke="#ccc"/>
  <text x="75" y="36" text-anchor="middle" font-size="12" font-family="sans-serif" fill="#333">WHITE × pre</text>
  <rect x="150" y="18" width="300" height="28" rx="4" fill="#222"/>
  <text x="300" y="36" text-anchor="middle" font-size="12" font-family="sans-serif" fill="#fff">BLACK × source</text>
  <rect x="450" y="18" width="150" height="28" rx="4" fill="#fff" stroke="#ccc"/>
  <text x="525" y="36" text-anchor="middle" font-size="12" font-family="sans-serif" fill="#333">WHITE × post</text>
  <text y="62" font-size="11" font-family="sans-serif" fill="#888">control_frames</text>
  <rect x="0" y="68" width="150" height="28" rx="4" fill="#999"/>
  <text x="75" y="86" text-anchor="middle" font-size="12" font-family="sans-serif" fill="#fff">GREY × pre</text>
  <rect x="150" y="68" width="300" height="28" rx="4" fill="#4a9ebb"/>
  <text x="300" y="86" text-anchor="middle" font-size="12" font-family="sans-serif" fill="#fff">source clip</text>
  <rect x="450" y="68" width="150" height="28" rx="4" fill="#999"/>
  <text x="525" y="86" text-anchor="middle" font-size="12" font-family="sans-serif" fill="#fff">GREY × post</text>
</svg>

---

### Frame Interpolation

Insert generated frames **between each consecutive pair** of source frames.

- **`split_index`** — number of new frames to insert per gap (min 1). `target_frames` is unused.

<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 90" style="max-width:600px">
  <text y="12" font-size="11" font-family="sans-serif" fill="#888">mask</text>
  <rect x="0" y="18" width="40" height="28" rx="4" fill="#222"/>
  <text x="20" y="36" text-anchor="middle" font-size="11" font-family="sans-serif" fill="#fff">B</text>
  <rect x="40" y="18" width="110" height="28" rx="4" fill="#fff" stroke="#ccc"/>
  <text x="95" y="36" text-anchor="middle" font-size="11" font-family="sans-serif" fill="#333">W × step</text>
  <rect x="150" y="18" width="40" height="28" rx="4" fill="#222"/>
  <text x="170" y="36" text-anchor="middle" font-size="11" font-family="sans-serif" fill="#fff">B</text>
  <rect x="190" y="18" width="110" height="28" rx="4" fill="#fff" stroke="#ccc"/>
  <text x="245" y="36" text-anchor="middle" font-size="11" font-family="sans-serif" fill="#333">W × step</text>
  <rect x="300" y="18" width="40" height="28" rx="4" fill="#222"/>
  <text x="320" y="36" text-anchor="middle" font-size="11" font-family="sans-serif" fill="#fff">B</text>
  <rect x="340" y="18" width="110" height="28" rx="4" fill="#fff" stroke="#ccc"/>
  <text x="395" y="36" text-anchor="middle" font-size="11" font-family="sans-serif" fill="#333">W × step</text>
  <rect x="450" y="18" width="40" height="28" rx="4" fill="#222"/>
  <text x="470" y="36" text-anchor="middle" font-size="11" font-family="sans-serif" fill="#fff">B</text>
  <text x="520" y="36" font-size="14" font-family="sans-serif" fill="#888">…</text>
  <text y="62" font-size="11" font-family="sans-serif" fill="#888">control_frames</text>
  <rect x="0" y="68" width="40" height="28" rx="4" fill="#4a9ebb"/>
  <text x="20" y="86" text-anchor="middle" font-size="11" font-family="sans-serif" fill="#fff">f0</text>
  <rect x="40" y="68" width="110" height="28" rx="4" fill="#999"/>
  <text x="95" y="86" text-anchor="middle" font-size="11" font-family="sans-serif" fill="#fff">GREY</text>
  <rect x="150" y="68" width="40" height="28" rx="4" fill="#4a9ebb"/>
  <text x="170" y="86" text-anchor="middle" font-size="11" font-family="sans-serif" fill="#fff">f1</text>
  <rect x="190" y="68" width="110" height="28" rx="4" fill="#999"/>
  <text x="245" y="86" text-anchor="middle" font-size="11" font-family="sans-serif" fill="#fff">GREY</text>
  <rect x="300" y="68" width="40" height="28" rx="4" fill="#4a9ebb"/>
  <text x="320" y="86" text-anchor="middle" font-size="11" font-family="sans-serif" fill="#fff">f2</text>
  <rect x="340" y="68" width="110" height="28" rx="4" fill="#999"/>
  <text x="395" y="86" text-anchor="middle" font-size="11" font-family="sans-serif" fill="#fff">GREY</text>
  <rect x="450" y="68" width="40" height="28" rx="4" fill="#4a9ebb"/>
  <text x="470" y="86" text-anchor="middle" font-size="11" font-family="sans-serif" fill="#fff">f3</text>
  <text x="520" y="86" font-size="14" font-family="sans-serif" fill="#888">…</text>
</svg>

---

### Replace/Inpaint

Regenerate a range of frames **in-place** within the source clip.

- **`split_index`** — start index of the region to replace. Raises an error if out of range.
- **`edge_frames`** — number of frames to replace (clamped to remaining frames after start).
- `target_frames` is unused. Total output = `source_frames` (in-place replacement).

<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 90" style="max-width:600px">
  <text y="12" font-size="11" font-family="sans-serif" fill="#888">mask</text>
  <rect x="0" y="18" width="200" height="28" rx="4" fill="#222"/>
  <text x="100" y="36" text-anchor="middle" font-size="12" font-family="sans-serif" fill="#fff">BLACK × before</text>
  <rect x="200" y="18" width="200" height="28" rx="4" fill="#fff" stroke="#ccc"/>
  <text x="300" y="36" text-anchor="middle" font-size="12" font-family="sans-serif" fill="#333">WHITE × replace</text>
  <rect x="400" y="18" width="200" height="28" rx="4" fill="#222"/>
  <text x="500" y="36" text-anchor="middle" font-size="12" font-family="sans-serif" fill="#fff">BLACK × after</text>
  <text y="62" font-size="11" font-family="sans-serif" fill="#888">control_frames</text>
  <rect x="0" y="68" width="200" height="28" rx="4" fill="#4a9ebb"/>
  <text x="100" y="86" text-anchor="middle" font-size="12" font-family="sans-serif" fill="#fff">before frames</text>
  <rect x="200" y="68" width="200" height="28" rx="4" fill="#999"/>
  <text x="300" y="86" text-anchor="middle" font-size="12" font-family="sans-serif" fill="#fff">GREY × replace</text>
  <rect x="400" y="68" width="200" height="28" rx="4" fill="#4a9ebb"/>
  <text x="500" y="86" text-anchor="middle" font-size="12" font-family="sans-serif" fill="#fff">after frames</text>
</svg>

---

### Video Inpaint

Regenerate **spatial regions** within frames using a per-pixel mask. Unlike other modes that work at the frame level (entire frames kept or generated), Video Inpaint operates at the pixel level — masked regions are regenerated while the rest of each frame is preserved.

- **`inpaint_mask`** *(required)* — a `MASK` (B, H, W) where white (1.0) marks regions to regenerate and black (0.0) marks regions to keep. A single-frame mask is automatically broadcast to all source frames; a multi-frame mask must have the same frame count as `source_clip`.
- **`target_frames`**, **`split_index`**, **`edge_frames`** — unused.
- Total output = `source_frames` (same length — in-place spatial replacement).

Compositing formula per pixel:

```
control_frames = source × (1 − mask) + grey × mask
```

<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 90" style="max-width:600px">
  <text y="12" font-size="11" font-family="sans-serif" fill="#888">mask (per-pixel)</text>
  <defs>
    <pattern id="checker" width="16" height="16" patternUnits="userSpaceOnUse">
      <rect width="8" height="8" fill="#222"/>
      <rect x="8" width="8" height="8" fill="#fff"/>
      <rect y="8" width="8" height="8" fill="#fff"/>
      <rect x="8" y="8" width="8" height="8" fill="#222"/>
    </pattern>
  </defs>
  <rect x="0" y="18" width="600" height="28" rx="4" fill="url(#checker)"/>
  <rect x="0" y="18" width="600" height="28" rx="4" fill="rgba(0,0,0,0.4)"/>
  <text x="300" y="36" text-anchor="middle" font-size="12" font-family="sans-serif" fill="#fff">per-pixel mask broadcast to (B, H, W, 3)</text>
  <text y="62" font-size="11" font-family="sans-serif" fill="#888">control_frames (per-pixel composite)</text>
  <rect x="0" y="68" width="300" height="28" rx="4" fill="#4a9ebb"/>
  <rect x="300" y="68" width="300" height="28" rx="4" fill="#999"/>
  <text x="150" y="86" text-anchor="middle" font-size="11" font-family="sans-serif" fill="#fff">source pixels (mask=0)</text>
  <text x="450" y="86" text-anchor="middle" font-size="11" font-family="sans-serif" fill="#fff">grey pixels (mask=1)</text>
  <text x="300" y="82" text-anchor="middle" font-size="9" font-family="sans-serif" fill="#ddd">↕ blended per-pixel</text>
</svg>

---

### Keyframe

Place keyframe images at specific positions within a `target_frames`-length output, and generate everything between them.

- **`source_clip`** — a small batch of keyframe images (e.g. 4 frames).
- **`target_frames`** — total output frame count.
- **`keyframe_positions`** *(optional)* — comma-separated frame indices (e.g. `"0,20,50,80"`). Must have one value per source frame, sorted ascending, no duplicates, all within [0, target_frames-1]. Leave empty for **auto-spread** (first keyframe at frame 0, last at `target_frames-1`, others evenly distributed).
- **`split_index`**, **`edge_frames`** — unused.

<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 100" style="max-width:600px">
  <text y="12" font-size="10" font-family="sans-serif" fill="#888">Example: 4 keyframes, target_frames=81, positions auto-spread to 0, 27, 53, 80</text>
  <text y="30" font-size="11" font-family="sans-serif" fill="#888">mask</text>
  <rect x="0" y="36" width="30" height="26" rx="4" fill="#222"/>
  <text x="15" y="53" text-anchor="middle" font-size="10" font-family="sans-serif" fill="#fff">B</text>
  <rect x="30" y="36" width="150" height="26" rx="4" fill="#fff" stroke="#ccc"/>
  <text x="105" y="53" text-anchor="middle" font-size="10" font-family="sans-serif" fill="#333">W × 26</text>
  <rect x="180" y="36" width="30" height="26" rx="4" fill="#222"/>
  <text x="195" y="53" text-anchor="middle" font-size="10" font-family="sans-serif" fill="#fff">B</text>
  <rect x="210" y="36" width="140" height="26" rx="4" fill="#fff" stroke="#ccc"/>
  <text x="280" y="53" text-anchor="middle" font-size="10" font-family="sans-serif" fill="#333">W × 25</text>
  <rect x="350" y="36" width="30" height="26" rx="4" fill="#222"/>
  <text x="365" y="53" text-anchor="middle" font-size="10" font-family="sans-serif" fill="#fff">B</text>
  <rect x="380" y="36" width="150" height="26" rx="4" fill="#fff" stroke="#ccc"/>
  <text x="455" y="53" text-anchor="middle" font-size="10" font-family="sans-serif" fill="#333">W × 26</text>
  <rect x="530" y="36" width="30" height="26" rx="4" fill="#222"/>
  <text x="545" y="53" text-anchor="middle" font-size="10" font-family="sans-serif" fill="#fff">B</text>
  <text y="78" font-size="11" font-family="sans-serif" fill="#888">control_frames</text>
  <rect x="0" y="84" width="30" height="26" rx="4" fill="#4a9ebb"/>
  <text x="15" y="101" text-anchor="middle" font-size="10" font-family="sans-serif" fill="#fff">k0</text>
  <rect x="30" y="84" width="150" height="26" rx="4" fill="#999"/>
  <text x="105" y="101" text-anchor="middle" font-size="10" font-family="sans-serif" fill="#fff">GREY</text>
  <rect x="180" y="84" width="30" height="26" rx="4" fill="#4a9ebb"/>
  <text x="195" y="101" text-anchor="middle" font-size="10" font-family="sans-serif" fill="#fff">k1</text>
  <rect x="210" y="84" width="140" height="26" rx="4" fill="#999"/>
  <text x="280" y="101" text-anchor="middle" font-size="10" font-family="sans-serif" fill="#fff">GREY</text>
  <rect x="350" y="84" width="30" height="26" rx="4" fill="#4a9ebb"/>
  <text x="365" y="101" text-anchor="middle" font-size="10" font-family="sans-serif" fill="#fff">k2</text>
  <rect x="380" y="84" width="150" height="26" rx="4" fill="#999"/>
  <text x="455" y="101" text-anchor="middle" font-size="10" font-family="sans-serif" fill="#fff">GREY</text>
  <rect x="530" y="84" width="30" height="26" rx="4" fill="#4a9ebb"/>
  <text x="545" y="101" text-anchor="middle" font-size="10" font-family="sans-serif" fill="#fff">k3</text>
</svg>

---

## Node: VACE Merge Back

Splices VACE sampler output back into the original full-length video. Connect the original (untrimmed) clip, the VACE sampler output, and the `vace_pipe` from VACE Source Prep. The pipe carries mode, trim bounds, and context frame counts for automatic blending.

Irrelevant widgets are automatically hidden based on the selected blend method.

### Inputs

| Input | Type | Default | Description |
|---|---|---|---|
| `source_clip` | IMAGE | — | Full original video (before any trimming). Same source as VACE Source Prep's source_clip. |
| `vace_output` | IMAGE | — | VACE sampler output. |
| `vace_pipe` | VACE_PIPE | — | Pipe from VACE Source Prep carrying mode, trim bounds, and context counts. |
| `blend_method` | ENUM | `optical_flow` | `none` (hard cut), `alpha` (linear crossfade), or `optical_flow` (motion-compensated). |
| `of_preset` | ENUM | `balanced` | Optical flow quality: `fast`, `balanced`, `quality`, `max`. |
| `source_clip_2` | IMAGE | *(optional)* | Second original clip for Join Extend with two separate clips. |

### Outputs

| Output | Type | Description |
|---|---|---|
| `merged_clip` | IMAGE | Full reconstructed video. |

### Behavior

**Pass-through modes** (Edge Extend, Frame Interpolation, Keyframe, Video Inpaint): returns `vace_output` as-is — the VACE output IS the final result for these modes.

**Splice modes** (End, Pre, Middle, Join, Bidirectional, Replace): reconstructs `source_clip[:trim_start] + vace_output + source_clip[trim_end:]`, then blends across the full context zones at each seam. For two-clip Join Extend, the tail comes from `source_clip_2` instead.

Context frame counts (`left_ctx`, `right_ctx`) are carried in the `vace_pipe` and determined automatically by VACE Source Prep based on the mode and input_left/input_right settings. Blending uses a smooth alpha ramp across the entire context zone. Optical flow blending warps both frames along the motion field before blending, reducing ghosting on moving subjects.

### Example: Middle Extend

```
Original:  274 frames (0–273)
Prep:      split_index=137, input_left=16, input_right=16
           → vace_pipe: trim_start=121, trim_end=153, left_ctx=16, right_ctx=16
Mask Gen:  target_frames=81
           → mask = [BLACK×16] [WHITE×49] [BLACK×16]
VACE out:  81 frames (from sampler)
Merge:     result = original[0:121] + vace[0:81] + original[153:274]
           → 121 + 81 + 121 = 323 frames
           Left blend:  vace[0..15] ↔ original[121..136] (full 16-frame context zone)
           Right blend: vace[65..80] ↔ original[137..152] (full 16-frame context zone)
```

### Wiring Diagram

<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 720 310" style="max-width:720px">
  <!-- Node boxes -->
  <rect x="10" y="10" width="130" height="40" rx="8" fill="#4a7ebb"/>
  <text x="75" y="35" text-anchor="middle" font-size="13" font-family="sans-serif" font-weight="bold" fill="#fff">Load Video</text>
  <rect x="200" y="10" width="160" height="40" rx="8" fill="#4a7ebb"/>
  <text x="280" y="35" text-anchor="middle" font-size="13" font-family="sans-serif" font-weight="bold" fill="#fff">VACE Source Prep</text>
  <rect x="430" y="10" width="130" height="40" rx="8" fill="#4a7ebb"/>
  <text x="495" y="35" text-anchor="middle" font-size="13" font-family="sans-serif" font-weight="bold" fill="#fff">Mask Generator</text>
  <rect x="430" y="120" width="160" height="40" rx="8" fill="#4a7ebb"/>
  <text x="510" y="145" text-anchor="middle" font-size="13" font-family="sans-serif" font-weight="bold" fill="#fff">Sampler / VACE Encode</text>
  <rect x="280" y="240" width="160" height="40" rx="8" fill="#4a7ebb"/>
  <text x="360" y="265" text-anchor="middle" font-size="13" font-family="sans-serif" font-weight="bold" fill="#fff">VACE Merge Back</text>
  <!-- Load Video → Source Prep (source_clip) -->
  <line x1="140" y1="30" x2="200" y2="30" stroke="#666" stroke-width="2" marker-end="url(#arrow)"/>
  <text x="170" y="24" text-anchor="middle" font-size="10" font-family="sans-serif" fill="#888">source_clip</text>
  <!-- Source Prep → Mask Gen (trimmed_clip) -->
  <line x1="360" y1="30" x2="430" y2="30" stroke="#666" stroke-width="2" marker-end="url(#arrow)"/>
  <text x="395" y="24" text-anchor="middle" font-size="10" font-family="sans-serif" fill="#888">trimmed_clip</text>
  <!-- Source Prep → Mask Gen (mode) -->
  <path d="M360,40 Q400,65 430,45" stroke="#666" stroke-width="1.5" fill="none" marker-end="url(#arrow)"/>
  <text x="405" y="58" text-anchor="middle" font-size="10" font-family="sans-serif" fill="#888">mode</text>
  <!-- Mask Gen → Sampler (mask + control_frames) -->
  <line x1="495" y1="50" x2="495" y2="120" stroke="#666" stroke-width="2" marker-end="url(#arrow)"/>
  <text x="520" y="85" font-size="10" font-family="sans-serif" fill="#888">mask</text>
  <text x="520" y="97" font-size="10" font-family="sans-serif" fill="#888">control_frames</text>
  <text x="520" y="109" font-size="10" font-family="sans-serif" fill="#888">target_frames</text>
  <!-- Source Prep → Merge Back (vace_pipe) -->
  <path d="M280,50 L280,260 L280,260" stroke="#666" stroke-width="2" stroke-dasharray="6,3" marker-end="url(#arrow)"/>
  <text x="264" y="155" font-size="10" font-family="sans-serif" fill="#888" transform="rotate(-90,264,155)">vace_pipe</text>
  <!-- Load Video → Merge Back (source_clip) -->
  <path d="M75,50 L75,260 L280,260" stroke="#666" stroke-width="2" marker-end="url(#arrow)"/>
  <text x="59" y="155" font-size="10" font-family="sans-serif" fill="#888" transform="rotate(-90,59,155)">source_clip</text>
  <!-- Sampler → Merge Back (vace_output) -->
  <path d="M510,160 L510,200 L440,260" stroke="#666" stroke-width="2" marker-end="url(#arrow)"/>
  <text x="500" y="215" font-size="10" font-family="sans-serif" fill="#888">vace_output</text>
  <!-- Arrow marker -->
  <defs>
    <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" fill="#666"/>
    </marker>
  </defs>
</svg>

---

## Node: WanVideo Save Merged Model

Saves a WanVideo diffusion model (with merged LoRAs) as a `.safetensors` file. Found under the **WanVideoWrapper** category.

### Inputs

| Input | Type | Default | Description |
|---|---|---|---|
| `model` | WANVIDEOMODEL | — | WanVideo model with merged LoRA from the WanVideo Model Loader. |
| `filename_prefix` | STRING | `merged_wanvideo` | Filename prefix for the saved file. A numeric suffix is appended to avoid overwriting. |
| `save_dtype` | ENUM | `same` | Cast weights before saving: `same`, `bf16`, `fp16`, or `fp32`. Set explicitly if the model was loaded in fp8. |
| `custom_path` | STRING | *(optional)* | Absolute path to save directory. Leave empty to save in `ComfyUI/models/diffusion_models/`. |

### Behavior

- Extracts the diffusion model state dict and saves it in safetensors format.
- Records source model name and merged LoRA details (names + strengths) in file metadata for traceability.
- Clones all tensors before saving to handle shared/aliased weights safely.
- Automatically avoids overwriting existing files by appending `_1`, `_2`, etc.

---

## Node: Save Latent (Absolute Path)

Saves a LATENT to an absolute file path as `.latent` (safetensors format). Found under the **latent** category.

### Inputs

| Input | Type | Default | Description |
|---|---|---|---|
| `samples` | LATENT | — | Latent samples to save. |
| `path` | STRING | `/path/to/latent.latent` | Absolute file path. `.latent` extension is appended if missing. |
| `overwrite` | BOOLEAN | `False` | If false, appends `_1`, `_2`, etc. to avoid overwriting. |

### Outputs

| Output | Description |
|---|---|
| `LATENT` | Pass-through of the input samples (for chaining). |

### Behavior

- Saves all tensor data via safetensors, with device info and non-tensor metadata stored in the file header.
- Creates parent directories automatically.

---

## Node: Load Latent (Absolute Path)

Loads a LATENT from an absolute file path. Found under the **latent** category.

### Inputs

| Input | Type | Default | Description |
|---|---|---|---|
| `path` | STRING | `/path/to/latent.latent` | Absolute path to a `.latent` file previously saved by Save Latent. |

### Outputs

| Output | Description |
|---|---|
| `LATENT` | Restored latent samples with original devices and non-tensor data. |

## Dependencies

- **PyTorch** and **safetensors** — bundled with ComfyUI.
- **OpenCV** (`cv2`) — optional, for optical flow blending in VACE Merge Back. Falls back to alpha blending if unavailable.
