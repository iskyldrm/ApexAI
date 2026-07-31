"""Multimodal (vision) model support (G.6-G.10).

Wraps vision-capable models (gpt-4o-vision, claude-3-vision) into a
uniform interface so the agent runtime can attach images to prompts.

In dev / tests without a real vision model, ``describe_image`` returns a
deterministic placeholder so the integration code path is testable.
"""
from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from typing import Any


logger = logging.getLogger(__name__)


@dataclass
class ImageInput:
    """A single image input."""

    data: bytes                      # raw image bytes
    mime_type: str = "image/png"     # MIME type
    alt_text: str = ""               # optional caption hint


@dataclass
class VisionResult:
    """Result of a vision model call."""

    content: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    raw: Any = None


class VisionClient:
    """Send images + text to a vision model.

    Supported providers: openai, anthropic. Falls back to a deterministic
    stub when no provider is configured or the call fails.
    """

    def __init__(self, provider: str = "openai", model: str | None = None) -> None:
        self.provider = provider
        # Default model names per provider
        self.model = model or {
            "openai": "gpt-4o-mini",
            "anthropic": "claude-3-5-sonnet-20241022",
        }.get(provider, "gpt-4o-mini")

    async def describe_image(
        self,
        image: ImageInput,
        prompt: str = "Describe this image in detail.",
    ) -> VisionResult:
        """Ask the vision model to describe an image."""
        if self.provider == "openai":
            return await self._openai_describe(image, prompt)
        elif self.provider == "anthropic":
            return await self._anthropic_describe(image, prompt)
        else:
            return self._stub_describe(image, prompt)

    async def describe_images(
        self,
        images: list[ImageInput],
        prompt: str = "Describe these images in detail.",
    ) -> VisionResult:
        """Multi-image call."""
        if self.provider == "openai":
            return await self._openai_describe_multi(images, prompt)
        elif self.provider == "anthropic":
            return await self._anthropic_describe_multi(images, prompt)
        else:
            return self._stub_describe(images[0] if images else ImageInput(data=b""), prompt)

    async def _openai_describe(self, image: ImageInput, prompt: str) -> VisionResult:
        try:
            import litellm

            b64 = base64.b64encode(image.data).decode("ascii")
            data_url = f"data:{image.mime_type};base64,{b64}"
            response = await litellm.acompletion(
                model=f"openai/{self.model}",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": data_url}},
                        ],
                    }
                ],
            )
            content = response.choices[0].message.content or ""
            usage = getattr(response, "usage", None)
            return VisionResult(
                content=content,
                model=self.model,
                input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                output_tokens=getattr(usage, "completion_tokens", 0) or 0,
                raw=response,
            )
        except Exception as e:
            logger.warning("OpenAI vision failed: %s", e)
            return self._stub_describe(image, prompt)

    async def _openai_describe_multi(
        self, images: list[ImageInput], prompt: str
    ) -> VisionResult:
        try:
            import litellm

            content = [{"type": "text", "text": prompt}]
            for img in images:
                b64 = base64.b64encode(img.data).decode("ascii")
                data_url = f"data:{img.mime_type};base64,{b64}"
                content.append({"type": "image_url", "image_url": {"url": data_url}})

            response = await litellm.acompletion(
                model=f"openai/{self.model}",
                messages=[{"role": "user", "content": content}],
            )
            text_out = response.choices[0].message.content or ""
            usage = getattr(response, "usage", None)
            return VisionResult(
                content=text_out,
                model=self.model,
                input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                output_tokens=getattr(usage, "completion_tokens", 0) or 0,
                raw=response,
            )
        except Exception as e:
            logger.warning("OpenAI multi-vision failed: %s", e)
            return self._stub_describe(images[0] if images else ImageInput(data=b""), prompt)

    async def _anthropic_describe(self, image: ImageInput, prompt: str) -> VisionResult:
        try:
            import litellm

            b64 = base64.b64encode(image.data).decode("ascii")
            response = await litellm.acompletion(
                model=f"anthropic/{self.model}",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": image.mime_type,
                                    "data": b64,
                                },
                            },
                        ],
                    }
                ],
            )
            content = response.choices[0].message.content or ""
            usage = getattr(response, "usage", None)
            return VisionResult(
                content=content,
                model=self.model,
                input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                output_tokens=getattr(usage, "completion_tokens", 0) or 0,
                raw=response,
            )
        except Exception as e:
            logger.warning("Anthropic vision failed: %s", e)
            return self._stub_describe(image, prompt)

    async def _anthropic_describe_multi(
        self, images: list[ImageInput], prompt: str
    ) -> VisionResult:
        try:
            import litellm

            content = [{"type": "text", "text": prompt}]
            for img in images:
                b64 = base64.b64encode(img.data).decode("ascii")
                content.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": img.mime_type,
                            "data": b64,
                        },
                    }
                )
            response = await litellm.acompletion(
                model=f"anthropic/{self.model}",
                messages=[{"role": "user", "content": content}],
            )
            text_out = response.choices[0].message.content or ""
            usage = getattr(response, "usage", None)
            return VisionResult(
                content=text_out,
                model=self.model,
                input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                output_tokens=getattr(usage, "completion_tokens", 0) or 0,
                raw=response,
            )
        except Exception as e:
            logger.warning("Anthropic multi-vision failed: %s", e)
            return self._stub_describe(images[0] if images else ImageInput(data=b""), prompt)

    def _stub_describe(self, image: ImageInput, prompt: str) -> VisionResult:
        """Deterministic placeholder used when no provider is configured."""
        size = len(image.data)
        return VisionResult(
            content=f"[stub-vision: {size} bytes, prompt={prompt!r}]",
            model="<stub>",
            input_tokens=0,
            output_tokens=0,
        )