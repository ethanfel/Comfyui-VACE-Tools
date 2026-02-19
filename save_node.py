import os
import json
import logging
import torch
import folder_paths
from safetensors.torch import save_file
from comfy.utils import ProgressBar

log = logging.getLogger("ComfyUI-WanVideoSaveMerged")


class WanVideoSaveMergedModel:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "model": ("WANVIDEOMODEL", {"tooltip": "WanVideo model with merged LoRA from the WanVideo Model Loader"}),
                "filename_prefix": ("STRING", {"default": "merged_wanvideo", "tooltip": "Filename prefix for the saved model"}),
            },
            "optional": {
                "save_dtype": (["same", "bf16", "fp16", "fp32"], {
                    "default": "same",
                    "tooltip": "Cast weights to this dtype before saving. 'same' keeps the current dtype of each tensor. Recommended to set explicitly if model was loaded in fp8."
                }),
                "custom_path": ("STRING", {
                    "default": "",
                    "tooltip": "Absolute path to save directory. Leave empty to save in ComfyUI/models/diffusion_models/"
                }),
            },
        }

    RETURN_TYPES = ()
    FUNCTION = "save_model"
    CATEGORY = "WanVideoWrapper"
    OUTPUT_NODE = True
    DESCRIPTION = "Saves the WanVideo diffusion model (including merged LoRAs) as a safetensors file"

    def save_model(self, model, filename_prefix, save_dtype="same", custom_path=""):
        dtype_map = {
            "bf16": torch.bfloat16,
            "fp16": torch.float16,
            "fp32": torch.float32,
        }

        # Build output directory
        if custom_path and os.path.isabs(custom_path):
            output_dir = custom_path
        else:
            output_dir = os.path.join(folder_paths.models_dir, "diffusion_models")
        os.makedirs(output_dir, exist_ok=True)

        # Build filename, avoid overwriting
        filename = f"{filename_prefix}.safetensors"
        output_path = os.path.join(output_dir, filename)
        counter = 1
        while os.path.exists(output_path):
            filename = f"{filename_prefix}_{counter}.safetensors"
            output_path = os.path.join(output_dir, filename)
            counter += 1

        # Gather metadata about the merge for traceability
        metadata = {}
        model_name = model.model.pipeline.get("model_name", "unknown")
        metadata["source_model"] = str(model_name)
        lora_info = model.model.pipeline.get("lora")
        if lora_info is not None:
            lora_entries = []
            for l in lora_info:
                lora_entries.append({
                    "name": l.get("name", "unknown"),
                    "strength": l.get("strength", 1.0),
                })
            metadata["merged_loras"] = json.dumps(lora_entries)
        metadata["save_dtype"] = save_dtype

        # Extract state dict from the diffusion model (keys are already bare,
        # e.g. "blocks.0.self_attn.k.weight" — matching original checkpoint format)
        diffusion_model = model.model.diffusion_model
        state_dict = diffusion_model.state_dict()

        target_dtype = dtype_map.get(save_dtype)
        pbar = ProgressBar(len(state_dict))

        clean_sd = {}
        for k, v in state_dict.items():
            tensor = v.cpu()
            if target_dtype is not None:
                tensor = tensor.to(target_dtype)
            # Clone to break shared memory between aliased tensors
            # (e.g. patch_embedding / expanded_patch_embedding / original_patch_embedding)
            # safetensors save_file doesn't handle shared tensors, and save_model
            # deduplicates keys which breaks compatibility with ComfyUI's load_file
            clean_sd[k] = tensor.clone()
            pbar.update(1)

        log.info(f"Saving merged WanVideo model to: {output_path}")
        log.info(f"Number of tensors: {len(clean_sd)}")

        save_file(clean_sd, output_path, metadata=metadata)

        log.info(f"Model saved successfully: {filename}")
        del clean_sd

        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        return ()


NODE_CLASS_MAPPINGS = {
    "WanVideoSaveMergedModel": WanVideoSaveMergedModel,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "WanVideoSaveMergedModel": "WanVideo Save Merged Model",
}
