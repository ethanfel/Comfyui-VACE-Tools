import torch


def _create_solid_batch(count, height, width, color_value, device="cpu"):
    """Create a batch of solid-color frames (B, H, W, 3). Returns empty tensor if count <= 0."""
    if count <= 0:
        return torch.empty((0, height, width, 3), dtype=torch.float32, device=device)
    return torch.full((count, height, width, 3), color_value, dtype=torch.float32, device=device)


def _placeholder(height, width, device="cpu"):
    """Create a single-frame black placeholder (1, H, W, 3)."""
    return torch.zeros((1, height, width, 3), dtype=torch.float32, device=device)


def _ensure_nonempty(tensor, height, width, device="cpu"):
    """Replace a 0-frame tensor with a 1-frame black placeholder."""
    if tensor.shape[0] == 0:
        return _placeholder(height, width, device)
    return tensor


class VACEMaskGenerator:
    CATEGORY = "VACE Tools"
    FUNCTION = "generate"
    RETURN_TYPES = ("IMAGE", "IMAGE", "IMAGE", "IMAGE", "IMAGE", "IMAGE", "INT")
    RETURN_NAMES = (
        "mask",
        "control_frames",
        "segment_1",
        "segment_2",
        "segment_3",
        "segment_4",
        "frames_to_generate",
    )
    OUTPUT_TOOLTIPS = (
        "Mask sequence — black (0) = keep original, white (1) = generate. Per-frame for most modes; per-pixel for Video Inpaint.",
        "Visual reference for VACE — source pixels where mask is black, grey (#7f7f7f) fill where mask is white.",
        "Segment 1: source/context frames. End/Pre/Bidirectional/Frame Interpolation/Video Inpaint/Keyframe: full clip. Middle: part A. Edge: start edge. Join: part 1. Replace/Inpaint: frames before replaced region.",
        "Segment 2: secondary context. Middle: part B. Edge: middle remainder. Join: part 2. Replace/Inpaint: original replaced frames. Others: placeholder.",
        "Segment 3: Edge: end edge. Join: part 3. Replace/Inpaint: frames after replaced region. Others: placeholder.",
        "Segment 4: Join: part 4. Others: placeholder.",
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
  keyframe_positions : Keyframe only (optional)"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "source_clip": ("IMAGE", {"description": "Source video frames (B,H,W,C tensor)."}),
                "mode": (
                    [
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
                    ],
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
                        "description": "Where to split the source. End: trim from end (e.g. -16). Pre: reference frames from start (e.g. 24). Middle: split frame index. Unused by Edge/Join. Bidirectional: frames before clip (0 = even split). Frame Interpolation: new frames per gap. Replace/Inpaint: start index of replace region. Unused by Video Inpaint and Keyframe.",
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
        BLACK = 0.0
        WHITE = 1.0
        GREY = 0.498

        def solid(count, color):
            return _create_solid_batch(count, H, W, color, dev)

        def ph():
            return _placeholder(H, W, dev)

        def safe(t):
            return _ensure_nonempty(t, H, W, dev)

        if mode == "End Extend":
            frames_to_generate = target_frames - B
            mask = torch.cat([solid(B, BLACK), solid(frames_to_generate, WHITE)], dim=0)
            control_frames = torch.cat([source_clip, solid(frames_to_generate, GREY)], dim=0)
            segment_1 = source_clip[:split_index] if split_index != 0 else source_clip
            return (mask, control_frames, safe(segment_1), ph(), ph(), ph(), frames_to_generate)

        elif mode == "Pre Extend":
            image_a = source_clip[:split_index]
            image_b = source_clip[split_index:]
            a_count = image_a.shape[0]
            frames_to_generate = target_frames - a_count
            mask = torch.cat([solid(frames_to_generate, WHITE), solid(a_count, BLACK)], dim=0)
            control_frames = torch.cat([solid(frames_to_generate, GREY), image_a], dim=0)
            return (mask, control_frames, safe(image_b), ph(), ph(), ph(), frames_to_generate)

        elif mode == "Middle Extend":
            image_a = source_clip[:split_index]
            image_b = source_clip[split_index:]
            a_count = image_a.shape[0]
            b_count = image_b.shape[0]
            frames_to_generate = target_frames - (a_count + b_count)
            mask = torch.cat([solid(a_count, BLACK), solid(frames_to_generate, WHITE), solid(b_count, BLACK)], dim=0)
            control_frames = torch.cat([image_a, solid(frames_to_generate, GREY), image_b], dim=0)
            return (mask, control_frames, safe(image_a), safe(image_b), ph(), ph(), frames_to_generate)

        elif mode == "Edge Extend":
            start_seg = source_clip[:edge_frames]
            end_seg = source_clip[-edge_frames:]
            mid_seg = source_clip[edge_frames:-edge_frames]
            start_count = start_seg.shape[0]
            end_count = end_seg.shape[0]
            frames_to_generate = target_frames - (start_count + end_count)
            mask = torch.cat([solid(end_count, BLACK), solid(frames_to_generate, WHITE), solid(start_count, BLACK)], dim=0)
            control_frames = torch.cat([end_seg, solid(frames_to_generate, GREY), start_seg], dim=0)
            return (mask, control_frames, start_seg, safe(mid_seg), end_seg, ph(), frames_to_generate)

        elif mode == "Join Extend":
            half = B // 2
            first_half = source_clip[:half]
            second_half = source_clip[half:]
            part_1 = first_half[:-edge_frames]
            part_2 = first_half[-edge_frames:]
            part_3 = second_half[:edge_frames]
            part_4 = second_half[edge_frames:]
            p2_count = part_2.shape[0]
            p3_count = part_3.shape[0]
            frames_to_generate = target_frames - (p2_count + p3_count)
            mask = torch.cat([solid(p2_count, BLACK), solid(frames_to_generate, WHITE), solid(p3_count, BLACK)], dim=0)
            control_frames = torch.cat([part_2, solid(frames_to_generate, GREY), part_3], dim=0)
            return (mask, control_frames, safe(part_1), safe(part_2), safe(part_3), safe(part_4), frames_to_generate)

        elif mode == "Bidirectional Extend":
            frames_to_generate = max(0, target_frames - B)
            if split_index > 0:
                pre_count = min(split_index, frames_to_generate)
            else:
                pre_count = frames_to_generate // 2
            post_count = frames_to_generate - pre_count
            mask = torch.cat([solid(pre_count, WHITE), solid(B, BLACK), solid(post_count, WHITE)], dim=0)
            control_frames = torch.cat([solid(pre_count, GREY), source_clip, solid(post_count, GREY)], dim=0)
            return (mask, control_frames, source_clip, ph(), ph(), ph(), frames_to_generate)

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
            return (mask, control_frames, source_clip, ph(), ph(), ph(), frames_to_generate)

        elif mode == "Replace/Inpaint":
            start = max(0, min(split_index, B))
            length = max(0, min(edge_frames, B - start))
            end = start + length
            frames_to_generate = length
            before = source_clip[:start]
            after = source_clip[end:]
            mask = torch.cat([solid(before.shape[0], BLACK), solid(length, WHITE), solid(after.shape[0], BLACK)], dim=0)
            control_frames = torch.cat([before, solid(length, GREY), after], dim=0)
            return (mask, control_frames, safe(before), safe(source_clip[start:end]), safe(after), ph(), frames_to_generate)

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
            return (mask, control_frames, source_clip, ph(), ph(), ph(), frames_to_generate)

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
            return (mask, control_frames, source_clip, ph(), ph(), ph(), frames_to_generate)

        raise ValueError(f"Unknown mode: {mode}")


NODE_CLASS_MAPPINGS = {
    "VACEMaskGenerator": VACEMaskGenerator,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "VACEMaskGenerator": "VACE Mask Generator",
}
