# ComfyUI-VACE-Tools

ComfyUI custom nodes for WanVideo/VACE workflows — mask/control-frame generation and model saving.

## Installation

```bash
cd ComfyUI/custom_nodes/
git clone https://github.com/ethanfel/Comfyui-VACE-Tools.git
```

Restart ComfyUI. Nodes appear under the **VACE Tools** and **WanVideoWrapper** categories.

## Node: VACE Mask Generator

### Inputs

| Input | Type | Default | Description |
|---|---|---|---|
| `source_clip` | IMAGE | — | Source video frames (B, H, W, C tensor) |
| `mode` | ENUM | `End Extend` | Generation mode (see below). 10 modes available. |
| `target_frames` | INT | `81` | Total output frame count for mask and control_frames (1–10000). Used by Keyframe to set output length. Unused by Frame Interpolation, Replace/Inpaint, and Video Inpaint. |
| `split_index` | INT | `0` | Where to split the source. Meaning varies by mode. Unused by Edge/Join/Keyframe. Bidirectional: frames before clip (0 = even split). Frame Interpolation: new frames per gap. Replace/Inpaint: start index of replace region. |
| `edge_frames` | INT | `8` | Number of edge frames for Edge and Join modes. Replace/Inpaint: number of frames to replace. Unused by End/Pre/Middle/Bidirectional/Frame Interpolation/Video Inpaint/Keyframe. |
| `inpaint_mask` | MASK | *(optional)* | Spatial inpaint mask for Video Inpaint mode (B, H, W). White (1.0) = regenerate, Black (0.0) = keep. Single frame broadcasts to all source frames. |
| `keyframe_positions` | STRING | *(optional)* | Comma-separated frame indices for Keyframe mode (e.g. `0,20,50,80`). One position per source frame, sorted ascending, within [0, target_frames-1]. Leave empty for even auto-spread. |

### Outputs

| Output | Description |
|---|---|
| `mask` | Black/white frame sequence (`target_frames` long). Black = keep, White = generate. |
| `control_frames` | Source frames composited with grey (`#7f7f7f`) fill (`target_frames` long). Fed to VACE as visual reference. |
| `segment_1`–`segment_4` | Clip segments whose contents depend on the mode (see below). Unused segments are 1-frame black placeholders. |
| `frames_to_generate` | INT — number of new frames the model needs to produce (the white/grey region). |

## Mode Reference

All diagrams show the `mask` and `control_frames` layout left-to-right (frame 0 → frame N).

---

### End Extend

Generate new frames **after** the source clip.

- **`split_index`** — optional trim: `0` keeps the full clip; a negative value (e.g. `-16`) drops that many frames from the end before extending.
- **`frames_to_generate`** = `target_frames − source_frames`

```
mask:           [ BLACK × source ][ WHITE × generated ]
control_frames: [ source clip    ][ GREY  × generated ]
```

| Segment | Content |
|---|---|
| `segment_1` | Source frames (trimmed if `split_index ≠ 0`) |
| `segment_2`–`4` | Placeholder |

---

### Pre Extend

Generate new frames **before** a reference portion of the source clip.

- **`split_index`** — how many frames from the start to keep as the reference tail (e.g. `24`).
- **`frames_to_generate`** = `target_frames − split_index`

```
mask:           [ WHITE × generated ][ BLACK × reference ]
control_frames: [ GREY  × generated ][ reference frames  ]
```

| Segment | Content |
|---|---|
| `segment_1` | Remaining frames after the reference (source[split_index:]) |
| `segment_2`–`4` | Placeholder |

---

### Middle Extend

Generate new frames **between** two halves of the source clip, split at `split_index`.

- **`split_index`** — frame index where the source is split.
- **`frames_to_generate`** = `target_frames − source_frames`

```
mask:           [ BLACK × part_a ][ WHITE × generated ][ BLACK × part_b ]
control_frames: [ part_a         ][ GREY  × generated ][ part_b         ]
```

| Segment | Content |
|---|---|
| `segment_1` | Part A — source[:split_index] |
| `segment_2` | Part B — source[split_index:] |
| `segment_3`–`4` | Placeholder |

---

### Edge Extend

Generate a transition **between the end and start** of a clip (useful for looping).

- **`edge_frames`** — number of frames taken from each edge.
- **`split_index`** — unused.
- **`frames_to_generate`** = `target_frames − (2 × edge_frames)`

The end segment is placed first, then the generated gap, then the start segment — so the model learns to connect the clip's end back to its beginning.

```
mask:           [ BLACK × end_seg ][ WHITE × generated ][ BLACK × start_seg ]
control_frames: [ end_seg         ][ GREY  × generated ][ start_seg         ]
```

| Segment | Content |
|---|---|
| `segment_1` | Start edge — source[:edge_frames] |
| `segment_2` | Middle remainder — source[edge_frames:−edge_frames] |
| `segment_3` | End edge — source[−edge_frames:] |
| `segment_4` | Placeholder |

---

### Join Extend

Heal/blend **two halves** of a clip together. The source is split in half; `edge_frames` from each side of the split form the context.

- **`edge_frames`** — context frames taken from each side of the midpoint.
- **`split_index`** — unused.
- **`frames_to_generate`** = `target_frames − (2 × edge_frames)`

```
source layout:  [ part_1 ][ part_2 | part_3 ][ part_4 ]
                           ← edge →  ← edge →

mask:           [ BLACK × part_2 ][ WHITE × generated ][ BLACK × part_3 ]
control_frames: [ part_2         ][ GREY  × generated ][ part_3         ]
```

| Segment | Content |
|---|---|
| `segment_1` | Part 1 — first half minus its trailing edge |
| `segment_2` | Part 2 — trailing edge of first half |
| `segment_3` | Part 3 — leading edge of second half |
| `segment_4` | Part 4 — second half minus its leading edge |

---

### Bidirectional Extend

Generate new frames **both before and after** the source clip.

- **`split_index`** — number of generated frames to place before the clip. `0` = even split (half before, half after).
- **`target_frames`** — total output frame count.
- **`frames_to_generate`** = `target_frames − source_frames`

```
mask:           [ WHITE × pre ][ BLACK × source ][ WHITE × post ]
control_frames: [ GREY  × pre ][ source clip    ][ GREY  × post ]
```

| Segment | Content |
|---|---|
| `segment_1` | Full source clip |
| `segment_2`–`4` | Placeholder |

---

### Frame Interpolation

Insert generated frames **between each consecutive pair** of source frames.

- **`split_index`** — number of new frames to insert per gap (min 1). `target_frames` is unused.
- **`frames_to_generate`** = `(source_frames − 1) × split_index`
- **Total output** = `source_frames + frames_to_generate`

```
mask:           [ B ][ W×step ][ B ][ W×step ][ B ] ...
control_frames: [ f0][ GREY   ][ f1][ GREY   ][ f2] ...
```

| Segment | Content |
|---|---|
| `segment_1` | Full source clip |
| `segment_2`–`4` | Placeholder |

---

### Replace/Inpaint

Regenerate a range of frames **in-place** within the source clip.

- **`split_index`** — start index of the region to replace (clamped to source length).
- **`edge_frames`** — number of frames to replace (clamped to remaining frames after start).
- **`frames_to_generate`** = `edge_frames` (after clamping). `target_frames` is unused.
- **Total output** = `source_frames` (same length — in-place replacement).

```
mask:           [ BLACK × before ][ WHITE × replace ][ BLACK × after ]
control_frames: [ before frames  ][ GREY  × replace ][ after frames  ]
```

| Segment | Content |
|---|---|
| `segment_1` | Before — source[:start] |
| `segment_2` | Original replaced frames — source[start:start+length] |
| `segment_3` | After — source[start+length:] |
| `segment_4` | Placeholder |

---

### Video Inpaint

Regenerate **spatial regions** within frames using a per-pixel mask. Unlike other modes that work at the frame level (entire frames kept or generated), Video Inpaint operates at the pixel level — masked regions are regenerated while the rest of each frame is preserved.

- **`inpaint_mask`** *(required)* — a `MASK` (B, H, W) where white (1.0) marks regions to regenerate and black (0.0) marks regions to keep. A single-frame mask is automatically broadcast to all source frames; a multi-frame mask must have the same frame count as `source_clip`.
- **`target_frames`**, **`split_index`**, **`edge_frames`** — unused.
- **`frames_to_generate`** = `source_frames` (all frames are partially regenerated).
- **Total output** = `source_frames` (same length — in-place spatial replacement).

Compositing formula per pixel:

```
control_frames = source × (1 − mask) + grey × mask
```

```
mask:           [ per-pixel mask broadcast to (B, H, W, 3)        ]
control_frames: [ source pixels where mask=0, grey where mask=1   ]
```

| Segment | Content |
|---|---|
| `segment_1` | Full source clip |
| `segment_2`–`4` | Placeholder |

---

### Keyframe

Place keyframe images at specific positions within a `target_frames`-length output, and generate everything between them.

- **`source_clip`** — a small batch of keyframe images (e.g. 4 frames).
- **`target_frames`** — total output frame count.
- **`keyframe_positions`** *(optional)* — comma-separated frame indices (e.g. `"0,20,50,80"`). Must have one value per source frame, sorted ascending, no duplicates, all within [0, target_frames-1]. Leave empty for **auto-spread** (first keyframe at frame 0, last at `target_frames-1`, others evenly distributed).
- **`split_index`**, **`edge_frames`** — unused.
- **`frames_to_generate`** = `target_frames − source_frames`
- **Total output** = `target_frames`

```
Example: 4 keyframes, target_frames=81, positions auto-spread to 0,27,53,80

mask:           [ B ][ W×26 ][ B ][ W×25 ][ B ][ W×26 ][ B ]
control_frames: [ k0][ GREY ][ k1][ GREY ][ k2][ GREY ][ k3]
```

| Segment | Content |
|---|---|
| `segment_1` | Full source clip (keyframe images) |
| `segment_2`–`4` | Placeholder |

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

## Dependencies

PyTorch and safetensors, both bundled with ComfyUI.
