from .nodes import VACE_MODES


class VACEModeSelect:
    """Select a VACE mode by integer index (0-9)."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "index": ("INT", {"default": 0, "min": 0, "max": len(VACE_MODES) - 1, "step": 1}),
            },
        }

    RETURN_TYPES = (VACE_MODES,)
    RETURN_NAMES = ("mode",)
    FUNCTION = "select"
    CATEGORY = "VACE Tools"

    def select(self, index):
        index = max(0, min(index, len(VACE_MODES) - 1))
        return (VACE_MODES[index],)


NODE_CLASS_MAPPINGS = {
    "VACEModeSelect": VACEModeSelect,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "VACEModeSelect": "VACE Mode Select",
}
