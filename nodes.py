import torch


VACE_MODES = [
    "End Extend",
    "Pre Extend",
    "Middle Extend",
    "Edge Extend",
    "Join Extend",
    "Bidirectional Extend",
    "Frame Interpolation",
    "Replace/Inpaint",
    "Video Inpaint",
    "Keyframe",
]


def _create_solid_batch(count, height, width, color_value, device="cpu"):
    """Create a batch of solid-color frames (B, H, W, 3). Returns empty tensor if count <= 0."""
    if count <= 0:
        return torch.empty((0, height, width, 3), dtype=torch.float32, device=device)
    return torch.full((count, height, width, 3), color_value, dtype=torch.float32, device=device)


class VACEMaskGenerator:
    CATEGORY = "VACE Tools"
    FUNCTION = "generate"
    RETURN_TYPES = ("IMAGE", "IMAGE", "INT")
    RETURN_NAMES = ("control_frames", "mask", "frames_to_generate")
    OUTPUT_TOOLTIPS = (
        "Visual reference for VACE — source pixels where mask is black, grey (#7f7f7f) fill where mask is white.",
        "Mask sequence — black (0) = keep original, white (1) = generate. Per-frame for most modes; per-pixel for Video Inpaint.",
        "Number of new frames to generate (white/grey frames added).",
    )
    DESCRIPTION = """VACE Mask Generator — builds mask + control_frames sequences for all VACE generation modes.

Modes:
  End Extend          — generate after the clip
  Pre Extend          — generate before the clip
  Middle Extend       — generate between two halves (split at split_index)
  Edge Extend         — generate between end and start edges (looping)
  Join Extend         — heal two halves with edge_frames context each side
  Bidirectional       — generate before AND after the clip
  Frame Interpolation — insert new frames between each source pair
  Replace/Inpaint     — regenerate a range of frames in-place
  Video Inpaint       — regenerate masked spatial regions (requires inpaint_mask)
  Keyframe            — place keyframe images at positions, generate between them

Mask colors: Black = keep original, White = generate new.
Control frames: original pixels where kept, grey (#7f7f7f) where generating.

Parameter usage by mode:
  target_frames      : End, Pre, Middle, Edge, Join, Bidirectional, Keyframe
  split_index        : End, Pre, Middle, Bidirectional, Frame Interpolation, Replace/Inpaint
  edge_frames        : Edge, Join, Replace/Inpaint
  inpaint_mask       : Video Inpaint only
  keyframe_positions : Keyframe only (optional)

Note: source_clip must not exceed target_frames for modes that use it.
If your source is longer, use VACE Source Prep upstream to trim it first."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "source_clip": ("IMAGE", {"description": "Source video frames (B,H,W,C tensor)."}),
                "mode": (
                    VACE_MODES,
                    {
                        "default": "End Extend",
                        "description": "End: generate after clip. Pre: generate before clip. Middle: generate at split point. Edge: generate between reversed edges (looping). Join: generate to heal two halves. Bidirectional: generate before AND after clip. Frame Interpolation: insert generated frames between each source pair. Replace/Inpaint: regenerate a range of frames in-place. Video Inpaint: regenerate masked spatial regions across all frames (requires inpaint_mask). Keyframe: place keyframe images at positions within target_frames, generate between them (optional keyframe_positions for manual placement).",
                    },
                ),
                "target_frames": (
                    "INT",
                    {
                        "default": 81,
                        "min": 1,
                        "max": 10000,
                        "description": "Total output frame count for mask and control_frames. Used by Keyframe to set output length. Unused by Frame Interpolation, Replace/Inpaint, and Video Inpaint.",
                    },
                ),
                "split_index": (
                    "INT",
                    {
                        "default": 0,
                        "min": -10000,
                        "max": 10000,
                        "description": "Where to split the source. Middle: split frame index (0 = auto-middle). Bidirectional: frames before clip (0 = even split). Frame Interpolation: new frames per gap. Replace/Inpaint: start index of replace region. Unused by End/Pre/Edge/Join/Video Inpaint/Keyframe.",
                    },
                ),
                "edge_frames": (
                    "INT",
                    {
                        "default": 8,
                        "min": 1,
                        "max": 10000,
                        "description": "Number of edge frames to use for Edge and Join modes. Unused by End/Pre/Middle/Bidirectional/Frame Interpolation/Video Inpaint/Keyframe. Replace/Inpaint: number of frames to replace.",
                    },
                ),
            },
            "optional": {
                "inpaint_mask": (
                    "MASK",
                    {
                        "description": "Spatial inpaint mask for Video Inpaint mode. White (1.0) = regenerate, Black (0.0) = keep. Single frame broadcasts to all source frames.",
                    },
                ),
                "keyframe_positions": (
                    "STRING",
                    {
                        "default": "",
                        "description": "Comma-separated frame indices for Keyframe mode (e.g. '0,20,50,80'). "
                                       "One position per source_clip frame, sorted ascending, within [0, target_frames-1]. "
                                       "Leave empty or disconnected for even auto-spread.",
                    },
                ),
            },
        }

    def generate(self, source_clip, mode, target_frames, split_index, edge_frames, inpaint_mask=None, keyframe_positions=None):
        B, H, W, C = source_clip.shape
        dev = source_clip.device

        modes_using_target = {"End Extend", "Pre Extend", "Middle Extend", "Edge Extend",
                              "Join Extend", "Bidirectional Extend", "Keyframe"}
        if mode in modes_using_target and B > target_frames:
            raise ValueError(
                f"{mode}: source_clip has {B} frames but target_frames is {target_frames}. "
                "Use VACE Source Prep to trim long clips."
            )

        BLACK = 0.0
        WHITE = 1.0
        GREY = 0.498

        def solid(count, color):
            return _create_solid_batch(count, H, W, color, dev)

        if mode == "End Extend":
            frames_to_generate = target_frames - B
            mask = torch.cat([solid(B, BLACK), solid(frames_to_generate, WHITE)], dim=0)
            control_frames = torch.cat([source_clip, solid(frames_to_generate, GREY)], dim=0)
            return (control_frames, mask, frames_to_generate)

        elif mode == "Pre Extend":
            image_a = source_clip[:split_index]
            a_count = image_a.shape[0]
            frames_to_generate = target_frames - a_count
            mask = torch.cat([solid(frames_to_generate, WHITE), solid(a_count, BLACK)], dim=0)
            control_frames = torch.cat([solid(frames_to_generate, GREY), image_a], dim=0)
            return (control_frames, mask, frames_to_generate)

        elif mode == "Middle Extend":
            if split_index <= 0:
                split_index = B // 2
            if split_index >= B:
                raise ValueError(
                    f"Middle Extend: split_index ({split_index}) is out of range — "
                    f"source_clip only has {B} frames. Use 0 for auto-middle."
                )
            image_a = source_clip[:split_index]
            image_b = source_clip[split_index:]
            a_count = image_a.shape[0]
            b_count = image_b.shape[0]
            frames_to_generate = target_frames - (a_count + b_count)
            mask = torch.cat([solid(a_count, BLACK), solid(frames_to_generate, WHITE), solid(b_count, BLACK)], dim=0)
            control_frames = torch.cat([image_a, solid(frames_to_generate, GREY), image_b], dim=0)
            return (control_frames, mask, frames_to_generate)

        elif mode == "Edge Extend":
            start_seg = source_clip[:edge_frames]
            end_seg = source_clip[-edge_frames:]
            start_count = start_seg.shape[0]
            end_count = end_seg.shape[0]
            frames_to_generate = target_frames - (start_count + end_count)
            mask = torch.cat([solid(end_count, BLACK), solid(frames_to_generate, WHITE), solid(start_count, BLACK)], dim=0)
            control_frames = torch.cat([end_seg, solid(frames_to_generate, GREY), start_seg], dim=0)
            return (control_frames, mask, frames_to_generate)

        elif mode == "Join Extend":
            half = B // 2
            first_half = source_clip[:half]
            second_half = source_clip[half:]
            part_2 = first_half[-edge_frames:]
            part_3 = second_half[:edge_frames]
            p2_count = part_2.shape[0]
            p3_count = part_3.shape[0]
            frames_to_generate = target_frames - (p2_count + p3_count)
            mask = torch.cat([solid(p2_count, BLACK), solid(frames_to_generate, WHITE), solid(p3_count, BLACK)], dim=0)
            control_frames = torch.cat([part_2, solid(frames_to_generate, GREY), part_3], dim=0)
            return (control_frames, mask, frames_to_generate)

        elif mode == "Bidirectional Extend":
            frames_to_generate = max(0, target_frames - B)
            if split_index > 0:
                pre_count = min(split_index, frames_to_generate)
            else:
                pre_count = frames_to_generate // 2
            post_count = frames_to_generate - pre_count
            mask = torch.cat([solid(pre_count, WHITE), solid(B, BLACK), solid(post_count, WHITE)], dim=0)
            control_frames = torch.cat([solid(pre_count, GREY), source_clip, solid(post_count, GREY)], dim=0)
            return (control_frames, mask, frames_to_generate)

        elif mode == "Frame Interpolation":
            step = max(split_index, 1)
            frames_to_generate = (B - 1) * step
            mask_parts = []
            ctrl_parts = []
            for i in range(B):
                mask_parts.append(solid(1, BLACK))
                ctrl_parts.append(source_clip[i:i+1])
                if i < B - 1:
                    mask_parts.append(solid(step, WHITE))
                    ctrl_parts.append(solid(step, GREY))
            mask = torch.cat(mask_parts, dim=0)
            control_frames = torch.cat(ctrl_parts, dim=0)
            return (control_frames, mask, frames_to_generate)

        elif mode == "Replace/Inpaint":
            if split_index >= B:
                raise ValueError(
                    f"Replace/Inpaint: split_index ({split_index}) is out of range — "
                    f"source_clip only has {B} frames."
                )
            start = max(0, min(split_index, B))
            length = max(0, min(edge_frames, B - start))
            end = start + length
            frames_to_generate = length
            before = source_clip[:start]
            after = source_clip[end:]
            mask = torch.cat([solid(before.shape[0], BLACK), solid(length, WHITE), solid(after.shape[0], BLACK)], dim=0)
            control_frames = torch.cat([before, solid(length, GREY), after], dim=0)
            return (control_frames, mask, frames_to_generate)

        elif mode == "Video Inpaint":
            if inpaint_mask is None:
                raise ValueError("Video Inpaint mode requires the inpaint_mask input to be connected.")
            m = inpaint_mask.to(dev)                       # (Bm, Hm, Wm) MASK type
            if m.shape[1] != H or m.shape[2] != W:
                raise ValueError(
                    f"Video Inpaint: inpaint_mask spatial size {m.shape[1]}x{m.shape[2]} "
                    f"doesn't match source_clip {H}x{W}."
                )
            m = m.clamp(0.0, 1.0)
            if m.shape[0] == 1 and B > 1:
                m = m.expand(B, -1, -1)                    # broadcast single mask to all frames
            elif m.shape[0] != B:
                raise ValueError(
                    f"Video Inpaint: inpaint_mask has {m.shape[0]} frames but source_clip has {B}. "
                    "Must match or be 1 frame."
                )
            m3 = m.unsqueeze(-1).expand(-1, -1, -1, 3).contiguous()  # (B,H,W) -> (B,H,W,3)
            mask = m3
            grey = torch.full_like(source_clip, GREY)
            control_frames = source_clip * (1.0 - m3) + grey * m3
            frames_to_generate = B
            return (control_frames, mask, frames_to_generate)

        elif mode == "Keyframe":
            if B > target_frames:
                raise ValueError(
                    f"Keyframe: source_clip has {B} frames but target_frames is only {target_frames}. "
                    "Need at least as many target frames as keyframes."
                )
            if keyframe_positions and keyframe_positions.strip():
                positions = [int(x.strip()) for x in keyframe_positions.split(",")]
                if len(positions) != B:
                    raise ValueError(
                        f"Keyframe: expected {B} positions (one per source frame), got {len(positions)}."
                    )
                if positions != sorted(positions):
                    raise ValueError("Keyframe: positions must be sorted in ascending order.")
                if len(set(positions)) != len(positions):
                    raise ValueError("Keyframe: positions must not contain duplicates.")
                if positions[0] < 0 or positions[-1] >= target_frames:
                    raise ValueError(
                        f"Keyframe: all positions must be in [0, {target_frames - 1}]."
                    )
            else:
                if B == 1:
                    positions = [0]
                else:
                    positions = [round(i * (target_frames - 1) / (B - 1)) for i in range(B)]

            mask_parts, ctrl_parts = [], []
            prev_end = 0
            for i, pos in enumerate(positions):
                gap = pos - prev_end
                if gap > 0:
                    mask_parts.append(solid(gap, WHITE))
                    ctrl_parts.append(solid(gap, GREY))
                mask_parts.append(solid(1, BLACK))
                ctrl_parts.append(source_clip[i:i+1])
                prev_end = pos + 1

            trailing = target_frames - prev_end
            if trailing > 0:
                mask_parts.append(solid(trailing, WHITE))
                ctrl_parts.append(solid(trailing, GREY))

            mask = torch.cat(mask_parts, dim=0)
            control_frames = torch.cat(ctrl_parts, dim=0)
            frames_to_generate = target_frames - B
            return (control_frames, mask, frames_to_generate)

        raise ValueError(f"Unknown mode: {mode}")


class VACESourcePrep:
    CATEGORY = "VACE Tools"
    FUNCTION = "prepare"
    RETURN_TYPES = ("IMAGE", VACE_MODES, "INT", "INT", "MASK", "STRING", "VACE_PIPE")
    RETURN_NAMES = (
        "trimmed_clip", "mode", "split_index", "edge_frames",
        "inpaint_mask", "keyframe_positions", "vace_pipe",
    )
    OUTPUT_TOOLTIPS = (
        "Trimmed source frames — wire to VACE Mask Generator's source_clip.",
        "Selected mode — wire to VACE Mask Generator's mode.",
        "Adjusted split_index for the trimmed clip — wire to VACE Mask Generator.",
        "Adjusted edge_frames — wire to VACE Mask Generator.",
        "Inpaint mask trimmed to match output — wire to VACE Mask Generator.",
        "Keyframe positions pass-through — wire to VACE Mask Generator.",
        "Pipe carrying mode, trim bounds, and context counts — wire to VACE Merge Back.",
    )
    DESCRIPTION = """VACE Source Prep — trims long source clips for VACE Mask Generator.

Use this node BEFORE VACE Mask Generator when your source clip is longer than target_frames.
It selects the relevant frames based on mode, input_left, and input_right, then outputs
adjusted parameters to wire directly into the mask generator.

input_left / input_right (0 = use all available):
  End Extend:          input_left = trailing context frames to keep
  Pre Extend:          input_right = leading reference frames to keep
  Middle Extend:       input_left/input_right = frames each side of split
  Edge Extend:         input_left/input_right = start/end edge size (overrides edge_frames)
  Join Extend:         input_left/input_right = edge context from each half (or each clip if source_clip_2 connected)
  Bidirectional:       input_left = trailing context frames to keep
  Frame Interpolation: pass-through (no trimming)
  Replace/Inpaint:     input_left/input_right = context frames around replace region
  Video Inpaint:       pass-through (no trimming)
  Keyframe:            pass-through (no trimming)"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "source_clip": ("IMAGE", {"description": "Full source video frames (B,H,W,C tensor)."}),
                "mode": (
                    VACE_MODES,
                    {
                        "default": "End Extend",
                        "description": "Generation mode — must match VACE Mask Generator's mode.",
                    },
                ),
                "split_index": (
                    "INT",
                    {
                        "default": 0,
                        "min": -10000,
                        "max": 10000,
                        "description": "Split position in the full source video (0 = auto-middle for Middle Extend). Same meaning as mask generator's split_index.",
                    },
                ),
                "input_left": (
                    "INT",
                    {
                        "default": 0,
                        "min": 0,
                        "max": 10000,
                        "description": "Frames from the left side of the split point to keep (0 = all available). "
                                       "End: trailing context. Middle: frames before split. Edge/Join: start edge size. "
                                       "Bidirectional: trailing context. Replace: context before region.",
                    },
                ),
                "input_right": (
                    "INT",
                    {
                        "default": 0,
                        "min": 0,
                        "max": 10000,
                        "description": "Frames from the right side of the split point to keep (0 = all available). "
                                       "Pre: leading reference. Middle: frames after split. Edge/Join: end edge size. "
                                       "Replace: context after region.",
                    },
                ),
                "edge_frames": (
                    "INT",
                    {
                        "default": 8,
                        "min": 1,
                        "max": 10000,
                        "description": "Default edge size for Edge/Join modes (overridden by input_left/input_right if non-zero). "
                                       "Replace/Inpaint: number of frames to replace.",
                    },
                ),
            },
            "optional": {
                "source_clip_2": (
                    "IMAGE",
                    {
                        "description": "Second clip for Join Extend — join two separate clips instead of splitting one in half.",
                    },
                ),
                "inpaint_mask": (
                    "MASK",
                    {
                        "description": "Spatial inpaint mask — trimmed to match output frames for Video Inpaint mode.",
                    },
                ),
                "keyframe_positions": (
                    "STRING",
                    {
                        "default": "",
                        "description": "Keyframe positions pass-through for Keyframe mode.",
                    },
                ),
            },
        }

    def prepare(self, source_clip, mode, split_index, input_left, input_right, edge_frames, source_clip_2=None, inpaint_mask=None, keyframe_positions=None):
        B, H, W, C = source_clip.shape
        dev = source_clip.device

        def mask_ph():
            return torch.zeros((1, H, W), dtype=torch.float32, device=dev)

        def trim_mask(start, end):
            if inpaint_mask is None:
                return mask_ph()
            m = inpaint_mask.to(dev)
            if m.shape[0] == 1:
                return m
            actual_end = min(end, m.shape[0])
            actual_start = min(start, actual_end)
            trimmed = m[actual_start:actual_end]
            if trimmed.shape[0] == 0:
                return mask_ph()
            return trimmed

        kp_out = keyframe_positions if keyframe_positions else ""

        if mode == "End Extend":
            if input_left > 0:
                start = max(0, B - input_left)
                output = source_clip[start:]
            else:
                output = source_clip
                start = 0
            pipe = {"mode": mode, "trim_start": start, "trim_end": B, "left_ctx": output.shape[0], "right_ctx": 0}
            return (output, mode, 0, edge_frames, trim_mask(start, B), kp_out, pipe)

        elif mode == "Pre Extend":
            if input_right > 0:
                end = min(B, input_right)
                output = source_clip[:end]
            else:
                output = source_clip
                end = B
            pipe = {"mode": mode, "trim_start": 0, "trim_end": end, "left_ctx": 0, "right_ctx": output.shape[0]}
            return (output, mode, output.shape[0], edge_frames, trim_mask(0, end), kp_out, pipe)

        elif mode == "Middle Extend":
            if split_index <= 0:
                split_index = B // 2
            if split_index >= B:
                raise ValueError(
                    f"Middle Extend: split_index ({split_index}) is out of range — "
                    f"source_clip only has {B} frames. Use 0 for auto-middle."
                )
            left_start = max(0, split_index - input_left) if input_left > 0 else 0
            right_end = min(B, split_index + input_right) if input_right > 0 else B
            output = source_clip[left_start:right_end]
            out_split = split_index - left_start
            part_a = source_clip[left_start:split_index]
            part_b = source_clip[split_index:right_end]
            pipe = {"mode": mode, "trim_start": left_start, "trim_end": right_end, "left_ctx": out_split, "right_ctx": part_b.shape[0]}
            return (output, mode, out_split, edge_frames, trim_mask(left_start, right_end), kp_out, pipe)

        elif mode == "Edge Extend":
            eff_left = min(input_left if input_left > 0 else edge_frames, B)
            eff_right = min(input_right if input_right > 0 else edge_frames, B)
            sym = min(eff_left, eff_right)
            start_seg = source_clip[:sym]
            end_seg = source_clip[-sym:] if sym > 0 else source_clip[:0]
            output = torch.cat([start_seg, end_seg], dim=0)
            pipe = {"mode": mode, "trim_start": 0, "trim_end": B, "left_ctx": 0, "right_ctx": 0}
            return (output, mode, 0, sym, mask_ph(), kp_out, pipe)

        elif mode == "Join Extend":
            if source_clip_2 is not None:
                first_half = source_clip
                second_half = source_clip_2
            else:
                half = B // 2
                first_half = source_clip[:half]
                second_half = source_clip[half:]
            eff_left = input_left if input_left > 0 else edge_frames
            eff_right = input_right if input_right > 0 else edge_frames
            eff_left = min(eff_left, first_half.shape[0])
            eff_right = min(eff_right, second_half.shape[0])
            sym = min(eff_left, eff_right)
            part_2 = first_half[-sym:]
            part_3 = second_half[:sym]
            output = torch.cat([part_2, part_3], dim=0)
            two_clip = source_clip_2 is not None
            if two_clip:
                trim_start = first_half.shape[0] - sym
                trim_end = sym
            else:
                trim_start = half - sym
                trim_end = half + sym
            pipe = {"mode": mode, "trim_start": trim_start, "trim_end": trim_end, "left_ctx": sym, "right_ctx": sym, "two_clip": two_clip}
            return (output, mode, 0, sym, mask_ph(), kp_out, pipe)

        elif mode == "Bidirectional Extend":
            if input_left > 0:
                start = max(0, B - input_left)
                output = source_clip[start:]
            else:
                output = source_clip
                start = 0
            pipe = {"mode": mode, "trim_start": start, "trim_end": B, "left_ctx": 0, "right_ctx": 0}
            return (output, mode, split_index, edge_frames, trim_mask(start, B), kp_out, pipe)

        elif mode == "Frame Interpolation":
            pipe = {"mode": mode, "trim_start": 0, "trim_end": B, "left_ctx": 0, "right_ctx": 0}
            return (source_clip, mode, split_index, edge_frames, trim_mask(0, B), kp_out, pipe)

        elif mode == "Replace/Inpaint":
            if split_index >= B:
                raise ValueError(
                    f"Replace/Inpaint: split_index ({split_index}) is out of range — "
                    f"source_clip only has {B} frames."
                )
            start = max(0, min(split_index, B))
            end_idx = min(start + edge_frames, B)
            length = end_idx - start
            ctx_start = max(0, start - input_left) if input_left > 0 else 0
            ctx_end = min(B, end_idx + input_right) if input_right > 0 else B
            before = source_clip[ctx_start:start]
            replace_region = source_clip[start:end_idx]
            after = source_clip[end_idx:ctx_end]
            output = torch.cat([before, replace_region, after], dim=0)
            out_split = before.shape[0]
            out_edge = length
            pipe = {"mode": mode, "trim_start": ctx_start, "trim_end": ctx_end, "left_ctx": before.shape[0], "right_ctx": after.shape[0]}
            return (output, mode, out_split, out_edge, trim_mask(ctx_start, ctx_end), kp_out, pipe)

        elif mode == "Video Inpaint":
            out_mask = inpaint_mask.to(dev) if inpaint_mask is not None else mask_ph()
            pipe = {"mode": mode, "trim_start": 0, "trim_end": B, "left_ctx": 0, "right_ctx": 0}
            return (source_clip, mode, split_index, edge_frames, out_mask, kp_out, pipe)

        elif mode == "Keyframe":
            pipe = {"mode": mode, "trim_start": 0, "trim_end": B, "left_ctx": 0, "right_ctx": 0}
            return (source_clip, mode, split_index, edge_frames, mask_ph(), kp_out, pipe)

        raise ValueError(f"Unknown mode: {mode}")


NODE_CLASS_MAPPINGS = {
    "VACEMaskGenerator": VACEMaskGenerator,
    "VACESourcePrep": VACESourcePrep,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "VACEMaskGenerator": "VACE Mask Generator",
    "VACESourcePrep": "VACE Source Prep",
}
