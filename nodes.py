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
        "Black/white mask sequence (target_frames long). Black = keep original, White = generate new.",
        "Source frames composited with grey (#7f7f7f) fill (target_frames long). Fed to VACE as visual reference.",
        "First clip segment. Contents depend on mode.",
        "Second clip segment. Placeholder if unused by the current mode.",
        "Third clip segment. Placeholder if unused by the current mode.",
        "Fourth clip segment. Placeholder if unused by the current mode.",
        "Number of new frames to generate (white/grey frames added).",
    )

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
                    ],
                    {
                        "default": "End Extend",
                        "description": "End: generate after clip. Pre: generate before clip. Middle: generate at split point. Edge: generate between reversed edges (looping). Join: generate to heal two halves.",
                    },
                ),
                "target_frames": (
                    "INT",
                    {
                        "default": 81,
                        "min": 1,
                        "max": 10000,
                        "description": "Total output frame count for mask and control_frames.",
                    },
                ),
                "split_index": (
                    "INT",
                    {
                        "default": 0,
                        "min": -10000,
                        "max": 10000,
                        "description": "Where to split the source. End: trim from end (e.g. -16). Pre: reference frames from start (e.g. 24). Middle: split frame index. Unused by Edge/Join.",
                    },
                ),
                "edge_frames": (
                    "INT",
                    {
                        "default": 8,
                        "min": 1,
                        "max": 10000,
                        "description": "Number of edge frames to use for Edge and Join modes. Unused by End/Pre/Middle.",
                    },
                ),
            }
        }

    def generate(self, source_clip, mode, target_frames, split_index, edge_frames):
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

        raise ValueError(f"Unknown mode: {mode}")


NODE_CLASS_MAPPINGS = {
    "VACEMaskGenerator": VACEMaskGenerator,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "VACEMaskGenerator": "VACE Mask Generator",
}
