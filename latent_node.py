import os
import json
import torch
import safetensors.torch


class SaveLatentAbsolute:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "samples": ("LATENT",),
                "path": ("STRING", {"default": "/path/to/latent.latent"}),
            },
            "optional": {
                "overwrite": ("BOOLEAN", {"default": False}),
            }
        }

    RETURN_TYPES = ("LATENT",)
    FUNCTION = "save"
    CATEGORY = "latent"
    OUTPUT_NODE = True

    def save(self, samples, path, overwrite=False):
        path = os.path.expanduser(path)
        if not path.endswith(".latent"):
            path += ".latent"
        os.makedirs(os.path.dirname(path), exist_ok=True)

        if not overwrite and os.path.exists(path):
            base, ext = os.path.splitext(path)
            counter = 1
            while os.path.exists(f"{base}_{counter}{ext}"):
                counter += 1
            path = f"{base}_{counter}{ext}"

        tensors = {}
        non_tensors = {}
        devices = {}
        for key, value in samples.items():
            if isinstance(value, torch.Tensor):
                devices[key] = str(value.device)
                tensors[key] = value.contiguous()
            else:
                non_tensors[key] = value

        metadata = {"devices": json.dumps(devices)}
        if non_tensors:
            metadata["non_tensor_data"] = json.dumps(non_tensors)

        safetensors.torch.save_file(tensors, path, metadata=metadata)
        return (samples,)


class LoadLatentAbsolute:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "path": ("STRING", {"default": "/path/to/latent.latent"}),
            }
        }

    RETURN_TYPES = ("LATENT",)
    FUNCTION = "load"
    CATEGORY = "latent"

    def load(self, path):
        path = os.path.expanduser(path)

        samples = safetensors.torch.load_file(path, device="cpu")

        with safetensors.safe_open(path, framework="pt") as f:
            meta = f.metadata()

        # Restore original devices
        if meta and "devices" in meta:
            devices = json.loads(meta["devices"])
            for key, device in devices.items():
                if key in samples:
                    samples[key] = samples[key].to(device)

        # Restore non-tensor data
        if meta and "non_tensor_data" in meta:
            non_tensors = json.loads(meta["non_tensor_data"])
            samples.update(non_tensors)

        return (samples,)


NODE_CLASS_MAPPINGS = {
    "SaveLatentAbsolute": SaveLatentAbsolute,
    "LoadLatentAbsolute": LoadLatentAbsolute,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SaveLatentAbsolute": "Save Latent (Absolute Path)",
    "LoadLatentAbsolute": "Load Latent (Absolute Path)",
}
