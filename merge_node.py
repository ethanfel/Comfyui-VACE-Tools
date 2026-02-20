import torch
import numpy as np


OPTICAL_FLOW_PRESETS = {
    'fast':     {'levels': 2, 'winsize': 11, 'iterations': 2, 'poly_n': 5, 'poly_sigma': 1.1},
    'balanced': {'levels': 3, 'winsize': 15, 'iterations': 3, 'poly_n': 5, 'poly_sigma': 1.2},
    'quality':  {'levels': 5, 'winsize': 21, 'iterations': 5, 'poly_n': 7, 'poly_sigma': 1.5},
    'max':      {'levels': 7, 'winsize': 31, 'iterations': 10, 'poly_n': 7, 'poly_sigma': 1.5},
}

PASS_THROUGH_MODES = {"Edge Extend", "Frame Interpolation", "Keyframe", "Video Inpaint"}



def _alpha_blend(frame_a, frame_b, alpha):
    """Simple linear crossfade between two frames (H,W,3 tensors)."""
    return frame_a * (1.0 - alpha) + frame_b * alpha


def _optical_flow_blend(frame_a, frame_b, alpha, preset):
    """Motion-compensated blend using Farneback optical flow."""
    try:
        import cv2
    except ImportError:
        return _alpha_blend(frame_a, frame_b, alpha)

    params = OPTICAL_FLOW_PRESETS[preset]

    arr_a = (frame_a.cpu().numpy() * 255).clip(0, 255).astype(np.uint8)
    arr_b = (frame_b.cpu().numpy() * 255).clip(0, 255).astype(np.uint8)

    gray_a = cv2.cvtColor(arr_a, cv2.COLOR_RGB2GRAY)
    gray_b = cv2.cvtColor(arr_b, cv2.COLOR_RGB2GRAY)
    flow = cv2.calcOpticalFlowFarneback(
        gray_a, gray_b, None,
        pyr_scale=0.5,
        levels=params['levels'],
        winsize=params['winsize'],
        iterations=params['iterations'],
        poly_n=params['poly_n'],
        poly_sigma=params['poly_sigma'],
        flags=0,
    )

    h, w = flow.shape[:2]
    x_coords = np.tile(np.arange(w), (h, 1)).astype(np.float32)
    y_coords = np.tile(np.arange(h), (w, 1)).T.astype(np.float32)

    # Warp A forward by alpha * flow
    flow_fwd = flow * alpha
    warped_a = cv2.remap(
        arr_a,
        x_coords + flow_fwd[..., 0],
        y_coords + flow_fwd[..., 1],
        cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REPLICATE,
    )

    # Warp B backward by -(1-alpha) * flow
    flow_back = -flow * (1 - alpha)
    warped_b = cv2.remap(
        arr_b,
        x_coords + flow_back[..., 0],
        y_coords + flow_back[..., 1],
        cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REPLICATE,
    )

    result = cv2.addWeighted(warped_a, 1 - alpha, warped_b, alpha, 0)
    return torch.from_numpy(result.astype(np.float32) / 255.0).to(frame_a.device)


class VACEMergeBack:
    CATEGORY = "VACE Tools"
    FUNCTION = "merge"
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("merged_clip",)
    OUTPUT_TOOLTIPS = (
        "Full reconstructed video with VACE output spliced back into the original clip.",
    )
    DESCRIPTION = """VACE Merge Back — splices VACE sampler output back into the original full-length video.

Connect the original (untrimmed) clip, the VACE sampler output, and the vace_pipe from VACE Source Prep.
The pipe carries mode, trim bounds, and context frame counts for automatic blending.

Pass-through modes (Edge Extend, Frame Interpolation, Keyframe, Video Inpaint):
  Returns vace_output as-is — the VACE output IS the final result.

Splice modes (End, Pre, Middle, Join, Bidirectional, Replace):
  Reconstructs original[:trim_start] + vace_output + original[trim_end:]
  with automatic blending across the full context zones.
  For two-clip Join Extend, connect original_clip_2 — the tail comes from the second clip.

Blend methods:
  none          — Hard cut at seams (fastest)
  alpha         — Simple linear crossfade
  optical_flow  — Motion-compensated blend using Farneback dense optical flow"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "original_clip": ("IMAGE", {"description": "Full original video (before any trimming)."}),
                "vace_output": ("IMAGE", {"description": "VACE sampler output."}),
                "vace_pipe": ("VACE_PIPE", {"description": "Pipe from VACE Source Prep carrying mode, trim bounds, and context counts."}),
                "blend_method": (["optical_flow", "alpha", "none"], {"default": "optical_flow", "description": "Blending method at seams."}),
                "of_preset": (["fast", "balanced", "quality", "max"], {"default": "balanced", "description": "Optical flow quality preset."}),
            },
            "optional": {
                "original_clip_2": ("IMAGE", {"description": "Second original clip for Join Extend with two separate clips."}),
            },
        }

    def merge(self, original_clip, vace_output, vace_pipe, blend_method, of_preset, original_clip_2=None):
        mode = vace_pipe["mode"]
        trim_start = vace_pipe["trim_start"]
        trim_end = vace_pipe["trim_end"]
        left_ctx = vace_pipe["left_ctx"]
        right_ctx = vace_pipe["right_ctx"]

        # Pass-through modes: VACE output IS the final result
        if mode in PASS_THROUGH_MODES:
            return (vace_output,)

        # Splice modes: reconstruct full video
        two_clip = vace_pipe.get("two_clip", False)
        V = vace_output.shape[0]
        head = original_clip[:trim_start]
        if two_clip and original_clip_2 is not None:
            tail = original_clip_2[trim_end:]
            right_orig = original_clip_2
        else:
            tail = original_clip[trim_end:]
            right_orig = original_clip
        result = torch.cat([head, vace_output, tail], dim=0)

        if blend_method == "none" or (left_ctx == 0 and right_ctx == 0):
            return (result,)

        def blend_frame(orig, vace, alpha):
            if blend_method == "optical_flow":
                return _optical_flow_blend(orig, vace, alpha, of_preset)
            return _alpha_blend(orig, vace, alpha)

        # Blend across full left context zone
        for j in range(left_ctx):
            alpha = (j + 1) / (left_ctx + 1)
            result[trim_start + j] = blend_frame(original_clip[trim_start + j], vace_output[j], alpha)

        # Blend across full right context zone
        for j in range(right_ctx):
            alpha = 1.0 - (j + 1) / (right_ctx + 1)
            frame_idx = V - right_ctx + j
            result[trim_start + frame_idx] = blend_frame(right_orig[trim_end - right_ctx + j], vace_output[frame_idx], alpha)

        return (result,)


NODE_CLASS_MAPPINGS = {
    "VACEMergeBack": VACEMergeBack,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "VACEMergeBack": "VACE Merge Back",
}
