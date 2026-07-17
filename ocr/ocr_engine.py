"""Pluggable OCR wrapper supporting EasyOCR (default) or Tesseract."""
from __future__ import annotations

from typing import List, Optional

import numpy as np


class OCREngine:
    def __init__(self, engine: str = "easyocr", languages: Optional[List[str]] = None, tesseract_cmd: Optional[str] = None):
        self.engine = engine
        self.languages = languages or ["en"]
        self._reader = None

        if engine == "easyocr":
            import easyocr

            self._reader = easyocr.Reader(self.languages, gpu=False)
        elif engine == "tesseract":
            import pytesseract

            if tesseract_cmd:
                pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
            self._reader = pytesseract
        else:
            raise ValueError(f"Unknown OCR engine: {engine}")

    def extract_text(self, image: np.ndarray) -> str:
        if self.engine == "easyocr":
            results = self._reader.readtext(image, detail=0)
            return "\n".join(results)
        else:
            return self._reader.image_to_string(image)

    def extract_with_boxes(self, image: np.ndarray) -> list:
        """Returns list of (text, confidence, bbox) tuples where available."""
        if self.engine == "easyocr":
            raw = self._reader.readtext(image, detail=1)
            return [(text, conf, bbox) for bbox, text, conf in raw]
        else:
            data = self._reader.image_to_data(image, output_type=self._reader.Output.DICT)
            out = []
            for i, text in enumerate(data["text"]):
                if not text.strip():
                    continue
                bbox = (data["left"][i], data["top"][i], data["width"][i], data["height"][i])
                conf = float(data["conf"][i]) if data["conf"][i] != "-1" else 0.0
                out.append((text, conf, bbox))
            return out

    def _top_y(self, bbox) -> float:
        """Smallest y-coordinate of a bbox, in either the 4-point (EasyOCR) or (left, top, w, h) (Tesseract) form."""
        if self.engine == "easyocr":
            return min(point[1] for point in bbox)
        return bbox[1]

    def extract_text_with_title(self, image: np.ndarray) -> tuple[str, str]:
        """Runs OCR once and returns (full_text, title).

        `title` is the topmost detected line of text on the screenshot — in
        practice a window title bar, page header, or other parent/section
        heading — since headers sit above the body content they label. Used
        to give each logged screenshot entry a human-readable label instead
        of just a wall of extracted text.
        """
        boxes = self.extract_with_boxes(image)
        lines = [text for text, _, _ in boxes if text.strip()]
        full_text = "\n".join(lines)
        if not boxes:
            return full_text, ""
        title = min(boxes, key=lambda b: self._top_y(b[2]))[0].strip()
        return full_text, title
