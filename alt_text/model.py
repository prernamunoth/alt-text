from transformers import Qwen3VLForConditionalGeneration, AutoProcessor, Qwen3VLProcessor
from transformers import AutoModelForImageTextToText, AutoProcessor
from pydantic import BaseModel
from PIL import Image
from qwen_vl_utils import process_vision_info

class AltTextModel(BaseModel):
    """Singleton model for generating alt text for images."""
    processor: Qwen3VLProcessor | None = None
    model: Qwen3VLForConditionalGeneration | None = None
    
    class Config:
        arbitrary_types_allowed = True
    
    
    @classmethod
    def load(cls) -> "AltTextModel":
        """Initialize the model and processor."""
        model_name = "Qwen/Qwen3-VL-4B-Instruct"
        processor = AutoProcessor.from_pretrained(model_name)
        model = AutoModelForImageTextToText.from_pretrained(
            model_name,
            dtype="auto",
            device_map="auto",
            attn_implementation="eager"
        ).eval()
        return cls(processor=processor, model=model)
    
    def generate_alt_text(self, image_path: str) -> str:
        """Generate alt text for a given image.
        
        Args:
            image_path: Path to the image file
            
        Returns:
            Generated alt text as a string
        """
        try:
            if not self.model or not self.processor:
                raise ValueError("Model or processor not initialized")
            
            # Load and preprocess the image
            image = Image.open(image_path).convert('RGB')
            
            # Resize image if it's too large
            max_size = 1024
            if max(image.size) > max_size:
                ratio = max_size / max(image.size)
                new_size = tuple(int(dim * ratio) for dim in image.size)
                image = image.resize(new_size, Image.Resampling.LANCZOS)
            
            # Create messages for the model
            messages = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "image": str(image_path)
                        },
                        {
                            "type": "text",
                            "text": "Please provide a detailed description of this image for accessibility purposes. Include visual details, spatial relationships, text if present, and context. Focus on elements that would be important for someone who cannot see the image. Do not miss any details. If the image contains table and code or text, explain both. Do not leave the sentence midway."
                        }
                    ]
                }
            ]
            
            # Prepare inputs for inference
            text = self.processor.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True
            )
            
            image_inputs, video_inputs = process_vision_info(messages, image_patch_size=16)
            
            inputs = self.processor(
                text=[text],
                images=image_inputs,
                videos=video_inputs,
                padding=True,
                return_tensors="pt"
            )
            
            # Move inputs to the same device as the model
            inputs = inputs.to(self.model.device)
            
            # Generate response
            generated_ids = self.model.generate(
                **inputs,
                max_new_tokens=512,
                pad_token_id=self.processor.tokenizer.pad_token_id,
                eos_token_id=self.processor.tokenizer.eos_token_id
            )
            
            generated_ids_trimmed = [
                out_ids[len(in_ids):] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
            ]
            
            return self.processor.batch_decode(
                generated_ids_trimmed,
                skip_special_tokens=True,
                clean_up_tokenization_spaces=False
            )[0].strip()
            
        except Exception as e:
            print(f"Error generating alt text: {e}")
            return "" 