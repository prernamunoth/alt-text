from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Callable, Dict, List, Optional, Union

import click
import shutil
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE, PP_PLACEHOLDER
from pptx.enum.text import PP_ALIGN
from pptx.oxml.xmlchemy import OxmlElement
from pptx.shapes.placeholder import PlaceholderPicture
from pptx.util import Inches, Pt

from alt_text.model import AltTextModel


PICTURE_TYPES = {
    MSO_SHAPE_TYPE.PICTURE,
    MSO_SHAPE_TYPE.MEDIA,
    MSO_SHAPE_TYPE.LINKED_PICTURE,
}

EMBEDDED_OBJECT_TYPES = {
    MSO_SHAPE_TYPE.EMBEDDED_OLE_OBJECT,
    MSO_SHAPE_TYPE.LINKED_OLE_OBJECT,
    MSO_SHAPE_TYPE.OLE_CONTROL_OBJECT,
}

DIAGRAM_TYPES = {
    MSO_SHAPE_TYPE.AUTO_SHAPE,
    MSO_SHAPE_TYPE.CALLOUT,
    MSO_SHAPE_TYPE.DIAGRAM,
    MSO_SHAPE_TYPE.EMBEDDED_OLE_OBJECT,
    MSO_SHAPE_TYPE.FREEFORM,
    MSO_SHAPE_TYPE.GROUP,
    MSO_SHAPE_TYPE.IGX_GRAPHIC,
    MSO_SHAPE_TYPE.LINE,
    MSO_SHAPE_TYPE.LINKED_OLE_OBJECT,
    MSO_SHAPE_TYPE.OLE_CONTROL_OBJECT,
    MSO_SHAPE_TYPE.TEXT_BOX,
}


@dataclass
class DiagramNode:
    shape: object
    left: int
    top: int
    right: int
    bottom: int
    text: str
    type_label: str
    equation_text: str

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


@dataclass
class TitleTemplate:
    left: int
    top: int
    width: int
    height: int
    font_size: Optional[int]
    bold: Optional[bool]
    placeholder_type: str = "title"
    placeholder_idx: Optional[int] = None


def _shape_bounds(shape) -> tuple[int, int, int, int]:
    return shape.left, shape.top, shape.left + shape.width, shape.top + shape.height


def _set_shape_frame(shape, left: int, top: int, width: int, height: int) -> None:
    shape.left = left
    shape.top = top
    shape.width = width
    shape.height = height

    try:
        sp_pr = shape._element.spPr
        xfrm = getattr(sp_pr, "xfrm", None)
        if xfrm is None:
            xfrm = OxmlElement("a:xfrm")
            sp_pr.insert(0, xfrm)

        off = getattr(xfrm, "off", None)
        if off is None:
            off = OxmlElement("a:off")
            xfrm.append(off)
        off.set("x", str(left))
        off.set("y", str(top))

        ext = getattr(xfrm, "ext", None)
        if ext is None:
            ext = OxmlElement("a:ext")
            xfrm.append(ext)
        ext.set("cx", str(width))
        ext.set("cy", str(height))
    except Exception:
        pass


def _shape_has_placeholder_type(shape, placeholder_type) -> bool:
    try:
        return shape.is_placeholder and shape.placeholder_format.type == placeholder_type
    except Exception:
        return False


def _placeholder_type_name(placeholder_type) -> str:
    if placeholder_type == PP_PLACEHOLDER.CENTER_TITLE:
        return "ctrTitle"
    return "title"


def _extract_alt_text(shape) -> str:
    alt_text = getattr(shape, "alt_text", "") or ""
    if alt_text:
        return alt_text.strip()

    if hasattr(shape, "_element"):
        nodes = shape._element.xpath(".//*[local-name()='cNvPr'][1]")
        if nodes:
            return (nodes[0].get("descr") or "").strip()

    return ""


def _normalize_alt_text(text: str) -> str:
    text = " ".join(text.split()).strip()
    if not text:
        return ""

    sentence_pattern = re.compile(r"(.+?[.!?])(?:\s+\1)+", re.IGNORECASE)
    while True:
        collapsed = sentence_pattern.sub(r"\1", text)
        if collapsed == text:
            break
        text = collapsed.strip()

    # Fallback for repeated fragments without punctuation at the end.
    words = text.split()
    for size in range(3, max(3, len(words) // 2) + 1):
        if len(words) % size != 0:
            continue
        chunk = words[:size]
        repeats = len(words) // size
        if repeats > 1 and chunk * repeats == words:
            return " ".join(chunk)

    return text


def _looks_like_filename(text: str) -> bool:
    normalized = text.strip().lower()
    return bool(
        re.fullmatch(r"[^\\/\s]+\.(png|jpe?g|gif|bmp|tiff?|wmf|emf|svg|webp)", normalized)
    )


def _looks_like_url(text: str) -> bool:
    normalized = text.strip().lower()
    return normalized.startswith(("http://", "https://", "www."))


def _is_placeholder_alt_text(text: str) -> bool:
    normalized = text.strip().lower()
    generic_labels = {
        "image",
        "picture",
        "photo",
        "graphic",
        "logo",
        "icon",
        "screenshot",
        "chart",
        "diagram",
        "figure",
        "clipart",
        "pasted-image",
    }
    if normalized in generic_labels:
        return True
    if re.fullmatch(r"(image|picture|photo|graphic|figure)\s*\d*", normalized):
        return True
    if re.fullmatch(r"(fig|figure|img|image|chart|graph|plot|photo|pic)[-_]?\d+(?:[-_]\d+)?", normalized):
        return True
    if re.fullmatch(r"[a-z]{1,6}\d{1,4}[a-z0-9_-]*", normalized):
        return True
    return False


def _alt_text_is_usable(text: str) -> bool:
    normalized = _normalize_alt_text(text)
    if not normalized:
        return False
    if _looks_like_url(normalized):
        return False
    if _looks_like_filename(normalized):
        return False
    if _is_placeholder_alt_text(normalized):
        return False
    if len(normalized) < 4:
        return False
    return True


def _alt_text_needs_refresh(text: str) -> bool:
    normalized = _normalize_alt_text(text)
    if not _alt_text_is_usable(normalized):
        return True

    weak_prefixes = (
        "diagram composed of related shapes and connectors",
        "diagram with related shapes and labels",
        "embedded object related to the surrounding slide content",
        "embedded instructional object related to:",
        "equation:",
    )
    if normalized.lower().startswith(weak_prefixes):
        return True

    if len(normalized.split()) < 5:
        return True

    return False


def _set_alt_text(shape, alt_text: str) -> bool:
    alt_text = _normalize_alt_text(alt_text)
    updated = False

    try:
        shape.alt_text = alt_text
        updated = True
    except Exception:
        pass

    if hasattr(shape, "_element"):
        nodes = shape._element.xpath(".//*[local-name()='cNvPr'][1]")
        if nodes:
            nodes[0].set("descr", alt_text)
            updated = True

    return updated


def _shape_text(shape) -> str:
    if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
        child_text = [_shape_text(child) for child in shape.shapes]
        return " | ".join(text for text in child_text if text).strip()

    if getattr(shape, "has_text_frame", False):
        parts: List[str] = []
        for paragraph in shape.text_frame.paragraphs:
            paragraph_text = "".join(run.text for run in paragraph.runs).strip()
            if paragraph_text:
                parts.append(paragraph_text)
        return " | ".join(parts).strip()

    return ""


def _extract_equation_text(shape) -> str:
    if not hasattr(shape, "_element"):
        return ""

    try:
        math_nodes = shape._element.xpath(
            ".//*[local-name()='oMath' or local-name()='oMathPara']"
        )
    except Exception:
        return ""

    parts: List[str] = []
    for node in math_nodes:
        text = " ".join(segment.strip() for segment in node.itertext() if segment.strip())
        text = re.sub(r"\s+", " ", text).strip()
        if text and text not in parts:
            parts.append(text)

    return " | ".join(parts)


def _is_equation_like_text(text: str) -> bool:
    normalized = text.strip()
    if not normalized:
        return False

    math_markers = ["=", "≈", "≠", "≤", "≥", "∑", "∫", "√", "π", "∞", "^", "/", "→", "←", "↔"]
    if any(marker in normalized for marker in math_markers):
        return True

    if re.search(r"\b(sin|cos|tan|log|ln|max|min|argmax|argmin|cov|var)\b", normalized, re.IGNORECASE):
        return True

    if re.search(r"[A-Za-z]\s*=\s*[^=]", normalized):
        return True

    return False


def _line_direction(shape) -> str:
    left, top, right, bottom = _shape_bounds(shape)
    delta_x = right - left
    delta_y = bottom - top

    if abs(delta_x) <= max(1, abs(delta_y) * 0.3):
        return "top to bottom" if delta_y >= 0 else "bottom to top"
    if abs(delta_y) <= max(1, abs(delta_x) * 0.3):
        return "left to right" if delta_x >= 0 else "right to left"
    if delta_x >= 0 and delta_y >= 0:
        return "top-left to bottom-right"
    if delta_x >= 0 and delta_y < 0:
        return "bottom-left to top-right"
    if delta_x < 0 and delta_y >= 0:
        return "top-right to bottom-left"
    return "bottom-right to top-left"


def _node_detail(node: DiagramNode) -> str:
    if node.equation_text:
        return f"equation='{node.equation_text}'"

    if _is_equation_like_text(node.text):
        return f"equation='{node.text}'"

    if node.text:
        return f"text='{node.text}'"

    if node.shape.shape_type == MSO_SHAPE_TYPE.LINE or "arrow" in node.type_label:
        return f"direction={_line_direction(node.shape)}"

    if node.shape.shape_type in EMBEDDED_OBJECT_TYPES:
        return "embedded object"

    return "no text"


def _shape_is_structural_title(shape) -> bool:
    return _shape_has_placeholder_type(shape, PP_PLACEHOLDER.TITLE) or _shape_has_placeholder_type(shape, PP_PLACEHOLDER.CENTER_TITLE)


def _shape_type_label(shape) -> str:
    try:
        auto_shape = shape.auto_shape_type
    except Exception:
        auto_shape = None

    if auto_shape is not None:
        return str(auto_shape).replace("_", " ").lower()

    shape_name = str(shape.shape_type).split(" ")[0]
    return shape_name.replace("_", " ").lower()


def _looks_like_title_or_footer(shape, slide_width: int, slide_height: int) -> bool:
    text = _shape_text(shape)
    if not text:
        return False

    left, top, right, bottom = _shape_bounds(shape)
    width = right - left
    height = bottom - top

    is_title = top < slide_height * 0.12 and width > slide_width * 0.45 and height < slide_height * 0.18
    is_footer = top > slide_height * 0.88 and height < slide_height * 0.08
    is_slide_number = top > slide_height * 0.88 and left > slide_width * 0.9 and len(text) <= 5
    return bool(is_title or is_footer or is_slide_number)


def _looks_like_title_text(shape, slide_width: int, slide_height: int) -> bool:
    text = _shape_text(shape)
    if not text:
        return False

    left, top, right, bottom = _shape_bounds(shape)
    width = right - left
    height = bottom - top
    word_count = len(text.split())

    if top > slide_height * 0.16:
        return False
    if left > slide_width * 0.18:
        return False
    if width < slide_width * 0.22 or width > slide_width * 0.92:
        return False
    if height > slide_height * 0.16:
        return False
    if word_count > 14:
        return False

    return shape.shape_type in {
        MSO_SHAPE_TYPE.TEXT_BOX,
        MSO_SHAPE_TYPE.AUTO_SHAPE,
        MSO_SHAPE_TYPE.PLACEHOLDER,
    }


def _find_existing_title_shape(slide, slide_width: int, slide_height: int):
    try:
        if slide.shapes.title and _shape_text(slide.shapes.title):
            return slide.shapes.title
    except Exception:
        pass

    if _slide_layout_supports_title(slide):
        for shape in slide.shapes:
            if _shape_is_structural_title(shape) and _shape_text(shape):
                return shape
        return None

    for shape in slide.shapes:
        if _looks_like_title_text(shape, slide_width, slide_height) and _shape_text(shape):
            return shape

    return None


def _find_empty_title_placeholder(slide):
    try:
        title_shape = slide.shapes.title
        if title_shape is not None and _shape_is_structural_title(title_shape):
            return title_shape
    except Exception:
        pass

    for shape in slide.shapes:
        if _shape_is_structural_title(shape):
            return shape
    return None


def _next_shape_id(slide) -> int:
    max_shape_id = 1
    for shape in slide.shapes:
        try:
            max_shape_id = max(max_shape_id, shape.shape_id)
        except Exception:
            continue
    return max_shape_id + 1


def _instantiate_title_placeholder(slide) -> object | None:
    title_layout_shape = None
    try:
        for shape in slide.slide_layout.placeholders:
            if _shape_is_structural_title(shape):
                title_layout_shape = shape
                break
    except Exception:
        return None

    if title_layout_shape is None:
        return None

    new_shape_elm = deepcopy(title_layout_shape._element)
    c_nv_pr = new_shape_elm.xpath("./*[local-name()='nvSpPr']/*[local-name()='cNvPr']")
    if c_nv_pr:
        c_nv_pr = c_nv_pr[0]
        c_nv_pr.set("id", str(_next_shape_id(slide)))
        c_nv_pr.set("name", "Title 1")

    tx_body = new_shape_elm.xpath("./*[local-name()='txBody']")
    if tx_body:
        tx_body = tx_body[0]
        for child in list(tx_body):
            tx_body.remove(child)
        body_pr = OxmlElement("a:bodyPr")
        lst_style = OxmlElement("a:lstStyle")
        paragraph = OxmlElement("a:p")
        tx_body.append(body_pr)
        tx_body.append(lst_style)
        tx_body.append(paragraph)

    sp_tree = slide.shapes._spTree
    ext_lst = getattr(sp_tree, "extLst", None)
    if ext_lst is not None:
        sp_tree.insert(sp_tree.index(ext_lst), new_shape_elm)
    else:
        sp_tree.append(new_shape_elm)

    new_id = int(c_nv_pr.get("id")) if c_nv_pr is not None else None
    for shape in slide.shapes:
        try:
            if shape.shape_id == new_id:
                return shape
        except Exception:
            continue
    return None


def _is_footer_like_shape(shape, slide_width: int, slide_height: int) -> bool:
    return _looks_like_title_or_footer(shape, slide_width, slide_height) and not _shape_is_structural_title(shape)


def _move_shapes_below_title(slide, title_shape, slide_width: int, slide_height: int) -> None:
    title_bottom = title_shape.top + title_shape.height
    min_body_top = title_bottom + Inches(0.15)

    for shape in slide.shapes:
        if shape == title_shape:
            continue
        if _shape_is_structural_title(shape):
            continue
        if _is_footer_like_shape(shape, slide_width, slide_height):
            continue

        try:
            if shape.top < min_body_top:
                shape.top = min_body_top
        except Exception:
            continue


def _scale_text_in_shape(shape, scale: float) -> None:
    if scale >= 0.999:
        return
    if not getattr(shape, "has_text_frame", False):
        return

    try:
        for paragraph in shape.text_frame.paragraphs:
            for run in paragraph.runs:
                if run.font.size:
                    new_size = max(Pt(10), int(run.font.size * scale))
                    run.font.size = new_size
    except Exception:
        pass


def _fit_shapes_within_slide(slide, title_shape, slide_width: int, slide_height: int) -> None:
    content_shapes = []
    for shape in slide.shapes:
        if shape == title_shape:
            continue
        if _shape_is_structural_title(shape):
            continue
        if _is_footer_like_shape(shape, slide_width, slide_height):
            continue
        try:
            content_shapes.append(shape)
        except Exception:
            continue

    if not content_shapes:
        return

    content_top = min(shape.top for shape in content_shapes)
    content_bottom = max(shape.top + shape.height for shape in content_shapes)
    available_top = title_shape.top + title_shape.height + Inches(0.15)
    available_bottom = int(slide_height * 0.88)
    available_height = available_bottom - available_top
    content_height = content_bottom - content_top

    if content_height <= 0 or available_height <= 0:
        return

    if content_height <= available_height:
        return

    scale = max(0.65, available_height / content_height)

    for shape in content_shapes:
        try:
            rel_top = shape.top - content_top
            new_top = available_top + int(rel_top * scale)
            new_height = max(int(shape.height * scale), Inches(0.2))
            new_left = shape.left
            new_width = shape.width
            _set_shape_frame(shape, new_left, new_top, new_width, new_height)
            _scale_text_in_shape(shape, scale)
        except Exception:
            continue


def _slide_layout_supports_title(slide) -> bool:
    try:
        for placeholder in slide.slide_layout.placeholders:
            if placeholder.placeholder_format.type in {PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE}:
                return True
    except Exception:
        pass
    return False


def _layout_supports_title(slide_layout) -> bool:
    try:
        for placeholder in slide_layout.placeholders:
            if placeholder.placeholder_format.type in {PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE}:
                return True
    except Exception:
        pass
    return False


def _find_title_layout(prs):
    preferred_layout = None
    fallback_layout = None

    for layout in prs.slide_layouts:
        if not _layout_supports_title(layout):
            continue

        if fallback_layout is None:
            fallback_layout = layout

        name = (layout.name or "").strip().lower()
        if name == "title only":
            return layout

        has_body = False
        try:
            for placeholder in layout.placeholders:
                if placeholder.placeholder_format.type in {
                    PP_PLACEHOLDER.BODY,
                    PP_PLACEHOLDER.OBJECT,
                    PP_PLACEHOLDER.PICTURE,
                    PP_PLACEHOLDER.SUBTITLE,
                }:
                    has_body = True
                    break
        except Exception:
            pass

        if not has_body and preferred_layout is None:
            preferred_layout = layout

    return preferred_layout or fallback_layout


def _rebind_slide_to_title_layout(slide, prs) -> bool:
    if _slide_layout_supports_title(slide):
        return False

    target_layout = _find_title_layout(prs)
    if target_layout is None:
        return False

    for rel in slide.part.rels.values():
        if rel.reltype.endswith("/slideLayout"):
            rel._target = target_layout.part
            click.echo(f"Rebound slide {slide.slide_id} to title-capable layout '{target_layout.name}'")
            return True

    return False


def _title_template_from_shape(shape) -> TitleTemplate:
    font_size = None
    bold = None
    if getattr(shape, "has_text_frame", False):
        for paragraph in shape.text_frame.paragraphs:
            for run in paragraph.runs:
                if run.font.size:
                    font_size = run.font.size
                if run.font.bold is not None:
                    bold = run.font.bold
                if font_size is not None or bold is not None:
                    break
            if font_size is not None or bold is not None:
                break

    placeholder_type = "title"
    placeholder_idx = None
    try:
        placeholder_type = _placeholder_type_name(shape.placeholder_format.type)
        placeholder_idx = shape.placeholder_format.idx
    except Exception:
        pass

    return TitleTemplate(
        left=shape.left,
        top=shape.top,
        width=shape.width,
        height=shape.height,
        font_size=font_size,
        bold=bold,
        placeholder_type=placeholder_type,
        placeholder_idx=placeholder_idx,
    )


def _title_template_from_layout(slide_layout) -> TitleTemplate | None:
    preferred = None
    fallback = None

    try:
        for placeholder in slide_layout.placeholders:
            ph_type = placeholder.placeholder_format.type
            if ph_type == PP_PLACEHOLDER.TITLE:
                preferred = _title_template_from_shape(placeholder)
                break
            if ph_type == PP_PLACEHOLDER.CENTER_TITLE and fallback is None:
                fallback = _title_template_from_shape(placeholder)
    except Exception:
        return None

    return preferred or fallback


def _infer_title_template(prs) -> TitleTemplate:
    for layout in prs.slide_layouts:
        template = _title_template_from_layout(layout)
        if template and template.placeholder_type == "title":
            return template

    for layout in prs.slide_layouts:
        template = _title_template_from_layout(layout)
        if template:
            return template

    for slide in prs.slides:
        slide_width = prs.slide_width
        slide_height = prs.slide_height
        title_shape = _find_existing_title_shape(slide, slide_width, slide_height)
        if title_shape is None:
            continue
        return _title_template_from_shape(title_shape)

    return TitleTemplate(
        left=Inches(0.6),
        top=Inches(0.3),
        width=Inches(11.5),
        height=Inches(0.8),
        font_size=Pt(28),
        bold=True,
    )


def _title_template_for_slide(slide, fallback_template: TitleTemplate) -> TitleTemplate:
    template = _title_template_from_layout(slide.slide_layout)
    if template is not None:
        return template
    return fallback_template


def _collect_slide_summary(slide, slide_width: int, slide_height: int) -> str:
    texts: List[str] = []
    for shape in sorted(slide.shapes, key=lambda item: (item.top, item.left)):
        if _shape_is_structural_title(shape):
            continue
        if not _slide_layout_supports_title(slide) and _looks_like_title_text(shape, slide_width, slide_height):
            continue
        text = _shape_text(shape)
        if text and text not in texts:
            texts.append(text)
        if len(texts) >= 10:
            break

    if texts:
        return " | ".join(texts)

    return "Untitled slide with no readable body text."


def _collect_existing_titles(prs) -> List[str]:
    titles: List[str] = []
    for slide in prs.slides:
        slide_width = prs.slide_width
        slide_height = prs.slide_height
        title_shape = _find_existing_title_shape(slide, slide_width, slide_height)
        if title_shape is None:
            continue
        title_text = _normalize_title_text(_shape_text(title_shape))
        if title_text and title_text not in titles:
            titles.append(title_text)
    return titles


def _reference_titles_for_slide(prs, slide_index: int, dynamic_titles: List[str]) -> List[str]:
    references: List[str] = []

    for title in dynamic_titles:
        if title and title not in references:
            references.append(title)

    for idx, slide in enumerate(prs.slides):
        if idx == slide_index:
            continue
        title_shape = _find_existing_title_shape(slide, prs.slide_width, prs.slide_height)
        if title_shape is None:
            continue
        title_text = _normalize_title_text(_shape_text(title_shape))
        if title_text and title_text not in references:
            references.append(title_text)

    return references[:20]


def _derive_title_from_slide_text(slide, slide_width: int, slide_height: int) -> str:
    candidates: List[tuple[int, int, str]] = []
    for shape in slide.shapes:
        if _shape_is_structural_title(shape):
            continue
        if not _slide_layout_supports_title(slide) and _looks_like_title_text(shape, slide_width, slide_height):
            continue

        text = _shape_text(shape)
        if not text:
            continue

        first_line = text.split("|")[0].strip()
        first_line = re.sub(r"\s+", " ", first_line)
        first_line = first_line.strip("\"'").strip()
        if not first_line:
            continue
        if len(first_line) > 80:
            continue
        if len(first_line.split()) > 12:
            continue

        candidates.append((shape.top, shape.left, first_line))

    if not candidates:
        return ""

    candidates.sort()
    return candidates[0][2]


def _normalize_title_text(text: str) -> str:
    text = _normalize_alt_text(text)
    text = text.strip().strip("\"'").strip()
    text = re.sub(r"[.!?]+$", "", text).strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _assign_title_placeholder_metadata(shape, title_template: TitleTemplate) -> None:
    try:
        nv_sp_pr = shape._element.nvSpPr
    except Exception:
        return

    c_nv_pr = getattr(nv_sp_pr, "cNvPr", None)
    if c_nv_pr is not None:
        c_nv_pr.set("name", "Title 1")

    nv_pr = getattr(nv_sp_pr, "nvPr", None)
    if nv_pr is None:
        return

    existing = nv_pr.xpath("./*[local-name()='ph']")
    for node in existing:
        nv_pr.remove(node)

    ph = OxmlElement("p:ph")
    ph.set("type", title_template.placeholder_type)
    if title_template.placeholder_idx is not None:
        ph.set("idx", str(title_template.placeholder_idx))
    nv_pr.append(ph)


def _ensure_slide_title(slide, slide_number: int, prs, model: AltTextModel, title_template: TitleTemplate, reference_titles: List[str]) -> str | None:
    if not _slide_layout_supports_title(slide):
        _rebind_slide_to_title_layout(slide, prs)

    title_template = _title_template_for_slide(slide, title_template)

    slide_width = prs.slide_width
    slide_height = prs.slide_height
    if _find_existing_title_shape(slide, slide_width, slide_height) is not None:
        return None

    local_hint = _normalize_title_text(_derive_title_from_slide_text(slide, slide_width, slide_height))
    slide_summary = _collect_slide_summary(slide, slide_width, slide_height)
    generated_title = _normalize_title_text(
        model.generate_slide_title(
            slide_summary,
            reference_titles=reference_titles,
            local_hint=local_hint or None,
        )
    )
    if not generated_title and local_hint:
        generated_title = local_hint
    if not generated_title:
        generated_title = f"Slide {slide_number}"
    if not generated_title:
        generated_title = "Untitled Slide"

    title_shape = _find_empty_title_placeholder(slide)
    if title_shape is None and _slide_layout_supports_title(slide):
        title_shape = _instantiate_title_placeholder(slide)

    if title_shape is not None and getattr(title_shape, "has_text_frame", False):
        click.echo(f"Using title placeholder for slide {slide_number}")
    else:
        title_shape = slide.shapes.add_textbox(
            title_template.left,
            title_template.top,
            title_template.width,
            title_template.height,
        )
        title_shape.name = f"Generated Title {slide_number}"
        try:
            title_shape.fill.background()
            title_shape.line.fill.background()
        except Exception:
            pass
        _assign_title_placeholder_metadata(title_shape, title_template)
        click.echo(f"Using generated title textbox for slide {slide_number}")

    if not getattr(title_shape, "has_text_frame", False):
        click.echo(f"Could not add a title to slide {slide_number}: shape has no text frame")
        return None

    _set_shape_frame(
        title_shape,
        title_template.left,
        title_template.top,
        title_template.width,
        title_template.height,
    )

    text_frame = title_shape.text_frame
    text_frame.clear()
    text_frame.word_wrap = True
    paragraph = text_frame.paragraphs[0]
    paragraph.text = generated_title
    paragraph.alignment = PP_ALIGN.LEFT

    if paragraph.runs:
        run = paragraph.runs[0]
        run.font.size = title_template.font_size or Pt(28)
        if title_template.bold is not None:
            run.font.bold = title_template.bold
        else:
            run.font.bold = True

    _move_shapes_below_title(slide, title_shape, slide_width, slide_height)
    _fit_shapes_within_slide(slide, title_shape, slide_width, slide_height)

    click.echo(f"Added missing title to slide {slide_number}: '{generated_title}'")
    return generated_title


def _is_picture_shape(shape) -> bool:
    return shape.shape_type in PICTURE_TYPES or isinstance(shape, PlaceholderPicture)


def _is_embedded_object_shape(shape) -> bool:
    return shape.shape_type in EMBEDDED_OBJECT_TYPES


def _collect_nearby_shape_text(slide, target_shape, radius: int = 914400) -> str:
    target_left, target_top, target_right, target_bottom = _shape_bounds(target_shape)
    nearby: List[str] = []

    for shape in slide.shapes:
        if shape == target_shape:
            continue

        text = _extract_equation_text(shape) or _shape_text(shape)
        if not text:
            continue

        left, top, right, bottom = _shape_bounds(shape)
        overlaps_horizontally = not (right < target_left - radius or left > target_right + radius)
        overlaps_vertically = not (bottom < target_top - radius or top > target_bottom + radius)
        if not overlaps_horizontally and not overlaps_vertically:
            continue

        if text not in nearby:
            nearby.append(text)

    return " | ".join(nearby[:10])


def _is_diagram_candidate(shape, slide_width: int, slide_height: int) -> bool:
    if _is_picture_shape(shape):
        return False

    if shape.shape_type not in DIAGRAM_TYPES:
        return False

    if getattr(shape, "is_placeholder", False):
        return False

    if _looks_like_title_or_footer(shape, slide_width, slide_height):
        return False

    return True


def _build_diagram_nodes(slide, slide_width: int, slide_height: int) -> List[DiagramNode]:
    nodes: List[DiagramNode] = []
    for shape in slide.shapes:
        if not _is_diagram_candidate(shape, slide_width, slide_height):
            continue

        left, top, right, bottom = _shape_bounds(shape)
        nodes.append(
            DiagramNode(
                shape=shape,
                left=left,
                top=top,
                right=right,
                bottom=bottom,
                text=_shape_text(shape),
                type_label=_shape_type_label(shape),
                equation_text=_extract_equation_text(shape),
            )
        )

    return nodes


def _boxes_are_related(node_a: DiagramNode, node_b: DiagramNode, proximity: int) -> bool:
    return not (
        node_a.right + proximity < node_b.left
        or node_b.right + proximity < node_a.left
        or node_a.bottom + proximity < node_b.top
        or node_b.bottom + proximity < node_a.top
    )


def _cluster_nodes(nodes: List[DiagramNode], proximity: int) -> List[List[DiagramNode]]:
    if not nodes:
        return []

    parent = list(range(len(nodes)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left_index: int, right_index: int) -> None:
        left_root = find(left_index)
        right_root = find(right_index)
        if left_root != right_root:
            parent[right_root] = left_root

    for left_index in range(len(nodes)):
        for right_index in range(left_index + 1, len(nodes)):
            if _boxes_are_related(nodes[left_index], nodes[right_index], proximity):
                union(left_index, right_index)

    grouped: Dict[int, List[DiagramNode]] = {}
    for index, node in enumerate(nodes):
        grouped.setdefault(find(index), []).append(node)

    clusters = list(grouped.values())
    clusters.sort(key=lambda cluster: min((node.top, node.left) for node in cluster))
    return clusters


def _cluster_alt_text(cluster: List[DiagramNode]) -> str:
    existing = [_normalize_alt_text(_extract_alt_text(node.shape)) for node in cluster]
    non_empty = [text for text in existing if text]
    if not non_empty or len(non_empty) != len(existing):
        return ""
    if any(not _alt_text_is_usable(text) for text in non_empty):
        return ""

    unique_texts: List[str] = []
    for text in non_empty:
        if text not in unique_texts:
            unique_texts.append(text)

    if len(unique_texts) == 1:
        return unique_texts[0]

    return " | ".join(unique_texts).strip()


def _cluster_has_repeated_alt_text(cluster: List[DiagramNode]) -> bool:
    for node in cluster:
        original = _extract_alt_text(node.shape)
        normalized = _normalize_alt_text(original)
        if original and normalized != original.strip():
            return True
    return False


def _relative_position(node: DiagramNode, bounds: tuple[int, int, int, int]) -> str:
    left, top, right, bottom = bounds
    width = max(right - left, 1)
    height = max(bottom - top, 1)

    center_x = node.left + node.width / 2
    center_y = node.top + node.height / 2

    if center_x < left + width / 3:
        horizontal = "left"
    elif center_x > left + (2 * width) / 3:
        horizontal = "right"
    else:
        horizontal = "center"

    if center_y < top + height / 3:
        vertical = "top"
    elif center_y > top + (2 * height) / 3:
        vertical = "bottom"
    else:
        vertical = "middle"

    return f"{vertical}-{horizontal}"


def _summarize_cluster(cluster: List[DiagramNode]) -> str:
    left = min(node.left for node in cluster)
    top = min(node.top for node in cluster)
    right = max(node.right for node in cluster)
    bottom = max(node.bottom for node in cluster)
    bounds = (left, top, right, bottom)

    ordered_cluster = sorted(cluster, key=lambda node: (node.top, node.left))
    lines = [f"Diagram cluster with {len(cluster)} shapes."]
    for node in ordered_cluster:
        lines.append(
            f"- {node.type_label} at {_relative_position(node, bounds)} with {_node_detail(node)}"
        )
    return "\n".join(lines)


def _fallback_diagram_alt_text(cluster: List[DiagramNode]) -> str:
    texts = [node.equation_text or node.text for node in cluster if node.equation_text or node.text]
    if texts:
        joined = ", ".join(texts)
        return f"Diagram with related shapes and labels: {joined}."
    return "Diagram composed of related shapes and connectors."


def _process_equation_shapes(
    slide,
    slide_number: int,
    model: AltTextModel,
    force_reprocess: bool = False,
) -> bool:
    updated = False

    for shape in slide.shapes:
        equation_text = _extract_equation_text(shape)
        if not equation_text and not _is_equation_like_text(_shape_text(shape)):
            continue

        existing_alt_text = _extract_alt_text(shape)
        if not _alt_text_needs_refresh(existing_alt_text) and (not force_reprocess or _alt_text_is_usable(existing_alt_text)):
            continue

        source_text = equation_text or _shape_text(shape)
        click.echo(f"\nEquation found in slide {slide_number}: {source_text}")
        generated = model.generate_equation_alt_text(source_text) or f"Equation: {source_text}"
        click.echo(f"Generated equation alt text: '{generated}'")
        if _set_alt_text(shape, generated):
            updated = True
            click.echo("Successfully set equation alt text")

    return updated


def _process_embedded_object_shapes(
    slide,
    slide_number: int,
    model: AltTextModel,
    slide_summary: str,
    force_reprocess: bool = False,
) -> bool:
    updated = False

    for shape in slide.shapes:
        if not _is_embedded_object_shape(shape):
            continue

        existing_alt_text = _extract_alt_text(shape)
        if not _alt_text_needs_refresh(existing_alt_text) and (not force_reprocess or _alt_text_is_usable(existing_alt_text)):
            continue

        nearby_text = _collect_nearby_shape_text(slide, shape)
        object_summary = (
            f"Slide {slide_number} embedded object.\n"
            f"Slide summary: {slide_summary}\n"
            f"Nearby labels or equations: {nearby_text or 'None'}\n"
            f"Object name: {shape.name}\n"
            f"Object dimensions: width={shape.width}, height={shape.height}"
        )

        click.echo(f"\nEmbedded object found in slide {slide_number}: {shape.name}")
        generated = model.generate_object_alt_text(object_summary)
        if not generated and nearby_text:
            generated = f"Embedded instructional object related to: {nearby_text}"
        if not generated:
            generated = "Embedded object related to the surrounding slide content."

        click.echo(f"Generated object alt text: '{generated}'")
        if _set_alt_text(shape, generated):
            updated = True
            click.echo("Successfully set embedded object alt text")

    return updated


def _save_picture(shape, slide_number: int, images_dir: Path) -> Optional[Path]:
    try:
        if not hasattr(shape, "image"):
            return None

        ext = getattr(shape.image, "ext", "png") or "png"
        shape_token = getattr(shape.image, "sha1", None) or shape.name
        image_filename = f"slide{slide_number}_{shape_token}.{ext}"
        image_path = images_dir / image_filename

        if not image_path.exists():
            with open(image_path, "wb") as file_handle:
                file_handle.write(shape.image.blob)

        click.echo(f"Saved image to: {image_path}")
        return image_path
    except Exception as exc:
        click.echo(f"Could not save image: {exc}")
        return None


def check_alt_text(
    pptx_path: Union[str, Path],
    model: AltTextModel,
    progress_callback: Callable[[int, int], None] = None,
    fast_mode: bool = False,
    force_reprocess: bool = False,
    images_dir: Optional[Path] = None,
) -> Dict:
    """Check alt text for images and diagram-like shapes in a PowerPoint presentation."""
    try:
        path = Path(pptx_path) if isinstance(pptx_path, str) else pptx_path
        images_dir = Path(images_dir) if images_dir is not None else Path("images")
        images_dir.mkdir(parents=True, exist_ok=True)

        prs = Presentation(path)

        total_images = 0
        images_without_alt = 0
        total_diagrams = 0
        diagrams_without_alt = 0
        titles_added = 0
        modified = False
        total_slides = len(prs.slides)
        output_path = None
        slide_width = prs.slide_width
        slide_height = prs.slide_height
        title_template = _infer_title_template(prs)
        known_titles = _collect_existing_titles(prs)

        for slide_index, slide in enumerate(prs.slides):
            slide_number = slide_index + 1
            if progress_callback:
                progress_callback(slide_number, total_slides)

            click.echo(f"\nChecking Slide {slide_number}:")
            slide_summary = _collect_slide_summary(slide, slide_width, slide_height)

            if not fast_mode:
                reference_titles = _reference_titles_for_slide(prs, slide_index, known_titles)
                generated_title = _ensure_slide_title(slide, slide_number, prs, model, title_template, reference_titles)
                if generated_title:
                    modified = True
                    titles_added += 1
                    if generated_title not in known_titles:
                        known_titles.append(generated_title)

            for shape in slide.shapes:
                if not _is_picture_shape(shape):
                    continue

                total_images += 1
                alt_text = _extract_alt_text(shape)
                usable_alt_text = _alt_text_is_usable(alt_text)
                needs_refresh = _alt_text_needs_refresh(alt_text)

                click.echo(f"\nImage found in slide {slide_number}:")
                click.echo(f"Shape type: {shape.shape_type}")
                click.echo(f"Shape name: {shape.name}")

                if needs_refresh:
                    images_without_alt += 1
                    image_path = _save_picture(shape, slide_number, images_dir)
                    if not image_path:
                        click.echo("Could not extract image for alt text generation")
                        continue
                    click.echo("Generating alt text for this image...")
                    generated = model.generate_alt_text(str(image_path))
                    if generated:
                        click.echo(f"Generated alt text: '{generated}'")
                        if _set_alt_text(shape, generated):
                            modified = True
                            click.echo("Successfully set alt text")
                    else:
                        click.echo("Error generating alt text for image")
                else:
                    click.echo(f"Existing alt text: '{alt_text}'")

            if _process_equation_shapes(slide, slide_number, model, force_reprocess=force_reprocess):
                modified = True

            if _process_embedded_object_shapes(
                slide,
                slide_number,
                model,
                slide_summary,
                force_reprocess=force_reprocess,
            ):
                modified = True

            if not fast_mode:
                diagram_nodes = _build_diagram_nodes(slide, slide_width, slide_height)
                proximity = int(max(slide_width, slide_height) * 0.04)
                clusters = _cluster_nodes(diagram_nodes, proximity)

                for cluster_index, cluster in enumerate(clusters, 1):
                    total_diagrams += 1
                    existing_alt_text = _cluster_alt_text(cluster)
                    has_repeated_alt_text = _cluster_has_repeated_alt_text(cluster)

                    click.echo(f"\nDiagram cluster found in slide {slide_number}, cluster {cluster_index}:")
                    for node in sorted(cluster, key=lambda item: (item.top, item.left)):
                        click.echo(f"- {node.shape.name} ({node.type_label}) text='{node.text}'")

                    if existing_alt_text and not has_repeated_alt_text and not _alt_text_needs_refresh(existing_alt_text):
                        click.echo(f"Existing alt text: '{existing_alt_text}'")
                        continue

                    if existing_alt_text and has_repeated_alt_text and not force_reprocess:
                        click.echo(f"Repairing repeated diagram alt text: '{existing_alt_text}'")
                        cluster_updated = False
                        for node in cluster:
                            cluster_updated = _set_alt_text(node.shape, existing_alt_text) or cluster_updated
                        if cluster_updated:
                            modified = True
                        continue

                    diagrams_without_alt += 1
                    click.echo("Generating combined alt text for this diagram...")
                    summary = _summarize_cluster(cluster)
                    generated = model.generate_diagram_alt_text(summary) or _fallback_diagram_alt_text(cluster)
                    click.echo(f"Generated diagram alt text: '{generated}'")

                    cluster_updated = False
                    for node in cluster:
                        cluster_updated = _set_alt_text(node.shape, generated) or cluster_updated

                    if cluster_updated:
                        modified = True
                        click.echo("Successfully set alt text for diagram cluster")

        if modified:
            output_path = path.parent / f"updated_{path.name}"
            try:
                prs.save(output_path)
                if output_path.exists():
                    click.echo(f"\nSaved updated presentation to: {output_path}")
                else:
                    click.echo("Warning: File save may have failed")
            except Exception as save_error:
                click.echo(f"Error saving presentation: {save_error}")

        return {
            "total_slides": total_slides,
            "total_images": total_images,
            "images_without_alt": images_without_alt,
            "images_with_alt": total_images - images_without_alt,
            "total_diagrams": total_diagrams,
            "diagrams_without_alt": diagrams_without_alt,
            "diagrams_with_alt": total_diagrams - diagrams_without_alt,
            "titles_added": titles_added,
            "modified": modified,
            "output_path": str(output_path) if modified else None,
        }
    except Exception as exc:
        click.echo(f"Error processing file: {exc}")
        return None


@click.command()
@click.argument("pptx_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--output", "-o", type=click.Path(dir_okay=False), help="Output file path (optional)")
def main(pptx_path: str, output: str = None) -> None:
    """Process a PowerPoint file to add alt text to images and diagrams."""
    try:
        model = AltTextModel.load()
        stats = check_alt_text(pptx_path, model=model)

        if stats and stats["modified"]:
            if output:
                input_path = Path(pptx_path)
                output_path = Path(output)
                if output_path.parent != input_path.parent:
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(input_path.parent / f"updated_{input_path.name}", output_path)
                click.echo(f"\nCopied updated file to: {output_path}")

            click.echo("\n=== Summary ===")
            click.echo(f"Total slides: {stats['total_slides']}")
            click.echo(f"Total images found: {stats['total_images']}")
            click.echo(f"Images without alt text: {stats['images_without_alt']}")
            click.echo(f"Images with alt text: {stats['images_with_alt']}")
            click.echo(f"Diagram groups found: {stats['total_diagrams']}")
            click.echo(f"Diagram groups without alt text: {stats['diagrams_without_alt']}")
            click.echo(f"Diagram groups with alt text: {stats['diagrams_with_alt']}")
            click.echo(f"Titles added: {stats['titles_added']}")
    except Exception as exc:
        click.echo(f"Error: {exc}")
        raise click.Abort()


if __name__ == "__main__":
    main()
