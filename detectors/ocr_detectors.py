import cairo
import os
from pathlib import Path
from PIL import Image
import numpy as np
from models.core_models import Box
from models.question import Question


class SpanType:
    Image = "image"
    Table = "table"
    Text = "text"
    InlineEquation = "inline_equation"
    InterlineEquation = "interline_equation"


class BlockType:
    Image = "image"
    ImageBody = "image_body"
    ImageCaption = "image_caption"
    ImageFootnote = "image_footnote"
    Table = "table"
    TableBody = "table_body"
    TableCaption = "table_caption"
    TableFootnote = "table_footnote"
    Text = "text"
    Title = "title"
    InterlineEquation = "interline_equation"
    Footnote = "footnote"
    Discarded = "discarded"
    List = "list"
    Index = "index"
    NestedBlocks = [Image, Table]


class OcrItem(Box):

    OCR_OUTPUT_DIR = os.path.join(".", "output", "question-html")
    OCR_PAGE_WIDTH = 0
    OCR_PAGE_HEIGHT = 0
    OCR_PAGE_SCALING = 0
    OCR_LINE_HEIGHT = 0
    SC = 1

    def __init__(self, json_dict: dict, src_surface: np.ndarray) -> None:
        box = json_dict["bbox"]
        self.__set_box__(box)
        self.np_src_image: np.ndarray = src_surface

    def get_html(self) -> str:
        pass

    def __set_box__(self, box):
        self.x = box[0] * OcrItem.SC[0]
        self.y = box[1] * OcrItem.SC[0]
        self.x1 = box[2] * OcrItem.SC[0]
        self.y1 = box[3] * OcrItem.SC[0]
        self.box = (self.x, self.y, self.x1, self.y1)
        self.w = self.x1 - self.x
        self.h = self.y1 - self.y

        pass

    def get_margin_top(self, prev_item):
        margin_top = 2.0 * OcrItem.OCR_LINE_HEIGHT
        diff = abs(self.y1 - prev_item.y1)
        if diff <= 2.12 * OcrItem.OCR_LINE_HEIGHT:
            margin_top = diff - 0.12 * OcrItem.OCR_LINE_HEIGHT
        return margin_top


class OcrBlock(OcrItem):
    def __init__(self, json_dict: dict, src_image_array) -> None:
        super().__init__(json_dict, src_image_array)
        self.type = json_dict["type"]
        self.html = None
        if self.type in BlockType.NestedBlocks:
            self.is_nested = True
            self.sub_blocks: list[OcrBlock] = []
            for bl_json in json_dict["blocks"]:
                self.sub_blocks.append(OcrBlock(bl_json, src_image_array))
        else:
            self.is_nested = False
            self.sub_blocks = None
            self.lines: list[OcrLine] = []
            for l_json in json_dict["lines"]:
                self.lines.append(OcrLine(l_json, src_image_array))

            pass

    def get_html(self) -> str:
        if self.html:
            return self.html
        if self.is_nested:
            self.html = f"<div class='nested-block {self.type}-block'>\n"
            prev_b = None
            for sub_b in self.sub_blocks:
                if prev_b:
                    self.html += (
                        f"<div class='spacer' style='height:{sub_b.get_margin_top(prev_b)}'>  </div>"
                        + "\n"
                    )
                self.html += sub_b.get_html() + "\n"
                prev_b = sub_b
            self.html += "</div>\n"
        else:
            self.html = f"<div class='block {self.type}-block'>\n"
            prev_l = None
            for line in self.lines:
                if prev_l:
                    self.html += (
                        f"<div class='spacer' style='height:{line.get_margin_top(prev_l)}'>  </div>"
                        + "\n"
                    )
                self.html += line.get_html() + "\n"
                prev_l = line
            self.html += "</div>\n"
        return self.html


class OcrLine(OcrItem):
    def __init__(self, json_dict: dict, src_image_array) -> None:
        super().__init__(json_dict, src_image_array)
        self.spans: list[OcrSpan] = []
        self.html = None
        for sp_json in json_dict["spans"]:
            self.spans.append(OcrSpan(sp_json, src_image_array))

    def get_html(self) -> str:
        if self.html:
            return self.html
        self.html = "<div class='line'>\n"
        for sp in self.spans:
            self.html += sp.get_html() + "\n"
        self.html += "</div>\n"
        return self.html


class OcrSpan(OcrItem):

    def __init__(self, json_dict: dict, src_image_array) -> None:
        super().__init__(json_dict, src_image_array)
        self.type = json_dict["type"]
        self.score = json_dict.get("score")
        self.html = None

        self.__initialize_vars__()

        if self.type == SpanType.Image:
            self.image_path = json_dict["image_path"]
            self.image_surf = self.crop_and_save_image_span()

        elif self.type == SpanType.Table:
            self.image_path = json_dict["image_path"].split(".")[0] + ".png"
            self.table_html = json_dict["html"]
        else:
            self.is_latex = self.type != SpanType.Text
            self.content = json_dict["content"]

    def get_html(self) -> str:

        if self.html:
            return self.html

        if self.type == SpanType.Image:
            img_uri = self.crop_and_save_image_span()
            self.html = (
                # "<span class='span image-span'>\n"
                "<img  "
                + f"src='{img_uri}' alt='{img_uri}'"
                + f"width='{round(self.w//OcrItem.OCR_PAGE_SCALING * 2)}' height='{round(self.h//OcrItem.OCR_PAGE_SCALING * 2)}'"
                + ">"
                # + "</span>\n"
            )
        elif self.type == SpanType.Table:
            self.html = self.table_html
        elif self.is_latex:
            delim1, delim2, cclass = (
                ("\\(", "\\)", "span inline-span")
                if self.type == SpanType.InlineEquation
                else ("\\[", "\\]", "span display-span")
            )
            self.html = (
                f"<span class='{cclass}'>"
                + f"{delim1} {self.validate_latex()} {delim2}"
                + "</span>\n"
            )
        else:
            self.html = (
                "<span class='span text-span'>"
                + f"{self.content}"
                + "</span>\n"
            )
        return self.html

    def validate_latex(self):
        # TODO:
        return self.content

    def __initialize_vars__(self):
        self.image_path = None
        self.table_html = None
        self.content = None
        self.is_latex = False
        self.html = ""

    def crop_and_save_image_span(self):
        array = self.np_src_image

        scale = 2  # OcrItem.OCR_SCALE
        # --
        sy = round(self.y)  # * o.get_stride()
        ey = round(self.y1)  # * o.get_stride()
        out_height = ey - sy

        # --
        sx = round(self.x)
        ex = round(self.x1)
        out_width = ex - sx

        # ----
        croped_array = array[sy:ey, sx:ex, :]

        stride = 4 * out_width  # WARN:

        pil_image = Image.frombytes(
            "RGBA",
            (out_width, out_height),
            croped_array.tobytes(),
            # bytes(croped_list),
            "raw",
            "BGRA",
            stride,
        )
        absoulte_img_path = os.path.join(
            OcrItem.OCR_OUTPUT_DIR, self.image_path
        )
        pil_image.save(absoulte_img_path, format="png")

        # bytes_png = io.BytesIO()
        # out_surf = cairo.ImageSurface.create_for_data(
        #     croped_array,
        #     cairo.FORMAT_ARGB32,
        #     out_width,
        #     out_height,
        #     o.get_stride(),
        # )
        image_uri = Path(absoulte_img_path).resolve().as_uri()
        return image_uri


class OcrQuestion:
    def __init__(
        self,
        page_width: float,
        page_height: float,
        line_height: float,
        page_scaling,
    ) -> None:
        OcrItem.OCR_PAGE_WIDTH = page_width
        OcrItem.OCR_PAGE_HEIGHT = page_height
        OcrItem.OCR_LINE_HEIGHT = line_height
        OcrItem.OCR_PAGE_SCALING = page_scaling

        os.makedirs(OcrItem.OCR_OUTPUT_DIR, exist_ok=True)
        self.block_dict: dict[str, OcrBlock] = None
        self.html = ""
        pass

    def set_question(
        self, q: Question, ocr_result_dict: dict, surf_dict: dict, scale: dict
    ):
        # OcrItem.SC = scale
        self.scale = scale
        self.content_list = ocr_result_dict["content-list"]
        self.para_blocks = ocr_result_dict["middle-json"]
        self.surf_dict = surf_dict
        self.question = q
        self.html = None
        main_q_blocks_json = self.para_blocks.get(q.id, [])
        main_q_surface: cairo.ImageSurface = surf_dict.get(q.id, None)
        self.block_dict = {}
        self.handle_question_part(
            q,
            main_q_blocks_json,
            main_q_surface,
        )
        self.dump_question_to_html()

        pass

    def handle_question_part(
        self,
        p: Question,
        part_blocks_list_json: list[dict],
        surface: cairo.ImageSurface,
    ):

        scale = self.scale.get(
            p.id, (OcrItem.OCR_PAGE_WIDTH, OcrItem.OCR_PAGE_HEIGHT)
        )
        w_scale = OcrItem.OCR_PAGE_WIDTH / scale[0]
        h_scale = OcrItem.OCR_PAGE_HEIGHT / scale[1]
        OcrItem.SC = (w_scale, h_scale)

        print("OcrItem.SC", OcrItem.SC)
        nparray_src = (
            self.get_nparray_from_surface(surface) if surface else None
        )
        part_blocks = []
        for block_json in part_blocks_list_json:
            part_blocks.append(OcrBlock(block_json, nparray_src))
        self.block_dict[p.id] = part_blocks

        for part in p.parts:
            p_blocks_json = self.para_blocks.get(part.id, [])
            p_surface: cairo.ImageSurface = self.surf_dict.get(part.id, None)
            self.handle_question_part(part, p_blocks_json, p_surface)

    def dump_question_to_html(self, q: Question | None = None) -> str:

        if not q:
            q = self.question

        lev = q.level
        # lev_name = ["question", "part", "subpart", None][lev + 1]
        if lev == 0:
            if self.html:
                return self.html
            self.html = ""

        cclass = ["question", "part", "subpart"][lev]
        label = f"Q({q.label})" if lev == 0 else f"({q.label})"
        self.html += f"<div class='container {cclass}'>\n\n"
        self.html += f"<span class='label'>{label}</span>"
        # **************** Question Begin ********************
        self.html += f"\n<div class='content'>\n"
        blocks: list[OcrBlock] = self.block_dict[q.id]
        has_pre = blocks and q.parts
        self.html += f"<div class='{'pre-blocks-container' if has_pre else 'main-blocks-container'}'>\n"
        prev_b = None
        for block in blocks:
            if prev_b:
                self.html += (
                    f"<div class='spacer' style='height:{block.get_margin_top(prev_b)}'>  </div>"
                    + "\n"
                )
            self.html += block.get_html() + "\n"
            prev_b = block

        if has_pre:
            self.html += "</div>\n"  # end pre
            self.html += "<div class='children-container'>\n"  # start-main

        prev_part = None
        for part in q.parts:
            if prev_part:
                self.html += f"<div class='spacer'>  </div>" + "\n"

            self.dump_question_to_html(part)
            prev_part = part
            pass

        self.html += "</div>\n"  # end pre or main
        self.html += "\n</div>\n"  # end question
        # **************** Question End *********************
        self.html += "\n</div>\n\n"  # end question-container

    def get_nparray_from_surface(self, surface: cairo.ImageSurface):
        h, stride = surface.get_height(), surface.get_stride()
        surface.flush()
        buf = surface.get_data()
        return np.frombuffer(buf, dtype=np.int8).reshape(h, stride // 4, 4)

    #
    # def handle_nested_block(self, b):
    #     pass
    #
    # def handle_block(self, b):
    #     pass
    #
    # def handle_line(self, l):
    #     pass
    #
    # def handle_span(self, s):
    #     pass
