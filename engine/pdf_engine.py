import os
import pprint
from os.path import sep

import cairo
import fitz  # PyMuPDF library
import numpy as np
from pypdf import PageObject, PdfReader
from pypdf.generic import ArrayObject, EncodedStreamObject, IndirectObject

from detectors import question_detectors
from detectors.question_detectors import (
    QuestionDetector,
    enable_detector_dubugging,
)
from engine.pdf_operator import PdfOperator
from models.core_models import SurfaceGapsSegments, Symbol
from models.question import Question

from .engine_state import EngineState
from .pdf_encoding import PdfEncoding as pnc
from .pdf_font import PdfFont
from .pdf_renderer import BaseRenderer
from .pdf_stream_parser import PDFStreamParser
from .pdf_utils import concat_cairo_surfaces, crop_image_surface


class PdfEngine:
    """
    class: PdfEngine Class v0.1
    """

    M_DEBUG_PAGE_STREAM = 1 << 0
    M_DEBUG_XOBJECT_STREAM = 1 << 1
    M_DEBUG_GLYPH_STREAM = 1 << 2
    M_DEBUG_ALL_STREAM = (1 << 0) | (1 << 1) | (1 << 2)
    # __
    M_DEBUG_DETECTOR = 1 << 3
    # __
    M_DEBUG_ORIGINAL_CONTENT = 1 << 4
    # __
    M_DEBUG = M_DEBUG_DETECTOR | M_DEBUG_ALL_STREAM | M_DEBUG_ORIGINAL_CONTENT

    # ________________________________________________________________

    O_CROP_EMPTY_LINES = 1 << 0
    O_CLEAN_DOTS_LINES = 1 << 1
    O_CLEAN_HEADER_FOOTER = 1 << 2

    # ________________________________________________________________
    D_DETECT_QUESTION = 1 << 0
    D_DETECT_LINES = 1 << 1
    D_DETECT_PARAGRAPH = 1 << 2
    D_DETECT_IMAGES = 1 << 3
    D_DETECT_TABLES = 1 << 4

    def __init__(self, scaling=1, clean: int = 0):
        self.scaling = scaling
        self.scaled_page_width = 595 * scaling
        self.scaled_page_height = 842 * scaling
        # self.debug = debug
        self.clean = clean
        self.page_seg_dict: dict[int, SurfaceGapsSegments] = {}
        self.question_list: list[Question] = {}
        self.current_pdf_document = None

    # *******************************************************
    # ****************   Engine API    **********************
    # _______________________________________________________

    def set_files(self, pdf_paths: list[str]):

        self.all_pdf_paths = pdf_paths
        self.all_pdf_count = len(pdf_paths)
        if self.all_pdf_count == 0:
            raise Exception("pdf_paths can't be empty")
        self.current_pdf_index = -1

        # self.proccess_next_pdf_file()

    def proccess_prev_pdf_file(self):

        if self.current_pdf_index <= 0:
            return False
        self.current_pdf_index -= 1
        self.initialize_file(self.all_pdf_paths[self.current_pdf_index])
        self.current_page = 1
        self.page_seg_dict = {}
        self.detection_types = 0
        return True

    def proccess_next_pdf_file(self):
        if self.current_pdf_index >= self.all_pdf_count - 1:
            return False
        self.current_pdf_index += 1
        self.initialize_file(self.all_pdf_paths[self.current_pdf_index])
        self.current_page = 1
        self.page_seg_dict = {}
        self.detection_types = 0
        return True

    # def skip_next_pdf_file(self):
    #     if self.current_pdf_index >= self.all_pdf_count - 1:
    #         return False
    #     self.current_pdf_index += 1
    #     self.current_page = 1
    #     self.page_seg_dict = {}
    #     self.detection_types = 0

    def extract_questions_from_pdf(self, debug=0, clean=2):
        (clean is not None) and self.set_clean(clean)
        (debug is not None) and self.set_debug(debug & self.M_DEBUG_DETECTOR)
        self.page_seg_dict = {}
        self.question_list = []
        self.detection_types = self.D_DETECT_QUESTION
        self.question_detector.on_restart()

        if self.debug & self.M_DEBUG_DETECTOR:
            enable_detector_dubugging(self.current_pdf_document)

        for page_nr in range(1, len(self.pages) + 1):
            # if page_nr in self.page_seg_dict:
            #     continue
            surface = self.render_pdf_page(page_nr, debug=None, clean=None)
            self.page_seg_dict[page_nr] = SurfaceGapsSegments(
                surface, gap_factor=0.1, scale=self.scaling
            )

        self.question_detector.on_finish()
        q_list = self.question_detector.get_question_list(self.pdf_path)
        if len(q_list) == 0:
            raise Exception("no question found on pdf !!", self.pdf_path)

        self.question_list = q_list
        return q_list

    def render_pdf_page(self, page_number, debug=0, clean=0):
        """page_number start from 1"""
        (clean is not None) and self.set_clean(clean)
        (debug is not None) and self.set_debug(
            debug & (self.M_DEBUG_ALL_STREAM | self.M_DEBUG_ORIGINAL_CONTENT)
        )

        self.current_page = page_number
        self.load_page_content(page_number)
        if self.debug & self.M_DEBUG_ORIGINAL_CONTENT:
            self.debug_original_stream()

        # if page_number in self.page_seg_dict:
        #     surface = self.page_seg_dict[page_number].surface
        # else:
        self.execute_page_stream()
        if False:
            self.doc_page: fitz = self.doc.load_page(page_number - 1)
            # zoom = 300 / 72
            # mat = fitz.Matrix(zoom, zoom)
            pix = self.doc_page.get_pixmap(
                dpi=round(72 * self.scaling), alpha=False
            )  # matrix=mat
            # np_array = (
            #     np.frombuffer(pix.samples, dtype=np.uint8)
            #     .reshape(pix.height, pix.width, 4)
            #     .copy()
            # )
            # np_array[:, :, [0, 2]] = np_array[:, :, [2, 0]]
            source_bytes = pix.samples
            width, height = pix.width, pix.height
            rgb_array = np.frombuffer(source_bytes, dtype=np.uint8).reshape(
                (height, width, 3)
            )
            bgra_array = np.zeros((height, width, 4), dtype=np.uint8)
            bgra_array[:, :, 0] = rgb_array[:, :, 2]  # Blue
            bgra_array[:, :, 1] = rgb_array[:, :, 1]  # Green
            bgra_array[:, :, 2] = rgb_array[:, :, 0]  # Red
            bgra_array[:, :, 3] = 255  # Alpha (fully opaque)
            surface = cairo.ImageSurface.create_for_data(
                bgra_array, cairo.FORMAT_ARGB32, pix.width, pix.height
            )

            self.renderer.surface = surface
        else:
            surface = self.renderer.surface
        if not self.detection_types and (self.clean & self.O_CROP_EMPTY_LINES):
            print("calling wrong function")
            surface = self.remove_empty_lines_from_current_page(surface)

        return surface

    def render_a_question(self, q_nr, devide=False):
        if not self.question_list:
            raise Exception("there is no detected Question on this exam")
        if 0 > q_nr > len(self.question_list):
            raise Exception(f"question nr {q_nr}, index out of valid range")

        q: Question = self.question_list[q_nr - 1]
        ren = self.renderer
        surf_res = q.draw_question_on_image_surface(
            self.page_seg_dict,
            ren.header_y,
            ren.footer_y,
            self.scaling,
            devide=True,
        )
        if devide:
            return surf_res
        else:
            return concat_cairo_surfaces(surf_res)

    # *******************************************************
    # **************** initialization  **********************
    # _______________________________________________________

    def initialize_file(self, pdf_path):
        self.current_stream: str | None = None
        self.pdf_path = pdf_path[1]
        self.current_pdf_document = self.pdf_path
        self.pdf_name = pdf_path[0]
        self.reader: PdfReader = PdfReader(self.pdf_path)
        self.doc = fitz.open(self.pdf_path)
        first_page: PageObject = self.reader.pages[0]
        self.scaled_page_width: float = (
            float(first_page.mediabox.width) * self.scaling
        )
        self.scaled_page_height: float = (
            float(first_page.mediabox.height) * self.scaling
        )
        self.d0 = self.scaled_page_height * 0.01
        self.line_height = (
            Symbol.LINE_HEIGHT_FACTOR * self.d0
        )  # * self.scaling

        self.font_map: dict[str, PdfFont] | None = None

        self.question_detector: QuestionDetector = QuestionDetector(
            self.D_DETECT_QUESTION, self.scaling
        )
        self.ALL_DETECTORS = [self.question_detector]

        self.state: EngineState | None = None
        self.renderer: BaseRenderer | None = None
        self.pages = self.reader.pages

    # *******************************************************
    # **************** Parsing Stream  **********************
    # _______________________________________________________

    def load_page_content(self, page_number: int):
        """
        prepare the page_number of pdf for rendering and detection
        load the following from current page object:
            - Fonts
            - xObject
            - external graphics state
            - color-space
            - main stream : containing the drawing commands
        this function also create the following class-object:
            - EngineState manager
            - renderer
            - configer the detector for this current page
        """

        if page_number < 1 or page_number > len(self.reader.pages):
            raise ValueError("Invalid page number")
        self.current_page = page_number
        page = self.reader.pages[page_number - 1]
        res = page.get("/Resources")
        if isinstance(res, IndirectObject):
            res = self.reader.get_object(res)
        self.res = res

        self.exgtate = self.get_external_g_state(res)
        self.xobject = self.get_x_object(res)
        # print(self.xobject)

        self.scaled_page_width = page.mediabox.width * self.scaling
        self.scaled_page_height = page.mediabox.height * self.scaling

        self.color_map = self.get_color_space_map(self.res)

        streams_data: list[bytes] = self.get_page_stream_data(page)

        for i, b in enumerate(streams_data):
            if b == 54:
                pass
        if len(streams_data) == 0:
            self.current_stream = pnc.bytes_to_string(
                self.reader.stream.read()
            )
            raise Exception(
                "no data found in this pdf !!!",
                self.pdf_path,
                ":",
                self.current_page,
            )
        streams_data = pnc.bytes_to_string(streams_data, unicode_excape=True)
        self.current_stream = streams_data

        self.debug_original_stream()
        self.font_map = self.get_fonts(self.res, 0)
        return self

    def get_page_stream_data(self, page):

        contents = page.get("/Contents")
        # return contents.get_data()
        streams_data = []
        if contents is None:
            raise ValueError("No content found in the page")

        if hasattr(contents, "get_object"):
            contents = contents.get_object()
        if isinstance(contents, EncodedStreamObject):
            data = contents.get_data()
            if data:
                streams_data.append(data)
        elif isinstance(contents, ArrayObject):
            for c in contents:
                if hasattr(c, "get_object"):
                    c = c.get_object()
                if isinstance(c, EncodedStreamObject):
                    data = c.get_data()
                    if data:
                        streams_data.append(data)
        return b"".join(streams_data)

    # *******************************************************
    # **************** Debugging ++    **********************
    # _______________________________________________________

    def debug_original_stream(
        self, filename=f"output{sep}original_stream.txt"
    ):
        # print("saving debug info into file")
        with open(filename, "w", encoding="utf-8") as f:
            f.write("# FileName: " + os.path.basename(self.pdf_path) + "\n\n")
            f.write("# page number " + str(self.current_page) + "\n\n")
            pprint.pprint(self.pages[self.current_page - 1], f)

            res = self.res

            f.write("\n\n### Resource:\n")
            pprint.pprint(res, f)

            f.write("\n\n### XObject:\n")
            pprint.pprint(self.get_x_object(res), f)
            self.print_fonts(f, res)
            self.print_external_g_state(f, res)
            self.print_color_space(f, res)
            f.write(self.current_stream)
        return self

    def debug_x_stream(
        self, xres: dict, xstream: str, filename=f"output{sep}xobj_stream.txt"
    ):
        # print("saving debug info into file")
        with open(filename, "w", encoding="utf-8") as f:
            f.write("# page number " + str(self.current_page) + "\n\n")
            # pprint.pprint(self.pages[self.current_page - 0], f)
            # page = self.pages[self.current_page - 0]
            # res = self.res
            self.print_fonts(f, xres)
            self.print_external_g_state(f, xres)
            self.print_color_space(f, xres)
            f.write(xstream)

    def print_color_space(self, f, res):

        colorSpace = self.get_color_space_map(res)
        f.write("\n\n### Color Space\n")
        pprint.pprint(colorSpace, f)

    def print_external_g_state(self, f, res):
        if not self.exgtate:
            self.exgtate = self.get_external_g_state(res)
        f.write("\n\n### External Graphics State\n")
        pprint.pprint(self.exgtate, f)

    def print_fonts(self, f, res):
        reader = self.reader
        f.write("\n\n### Fonts\n")
        output_dict = {}
        for font_name, indir_obj in res.get("/Font").items():
            obj = reader.get_object(indir_obj)
            output_dict[font_name] = {}
            for key, value in obj.items():
                if isinstance(value, list):
                    for v in value:
                        self.update_sub_obj(key, v, output_dict, font_name)
                else:
                    self.update_sub_obj(key, value, output_dict, font_name)
        f.write("\n```python\n")
        pprint.pprint(output_dict, f)
        f.write("\n```\n")

    # *******************************************************
    # **************** Helper Mehtods  **********************
    # _______________________________________________________

    def set_clean(self, clean):
        self.clean = clean

    def set_debug(self, debug):
        self.debug = debug

    def get_num_pages(
        self,
    ):
        return len(self.pages)

    def get_current_file_path(self):
        return self.current_pdf_document

    def get_color_space_map(self, res):
        colorSpace = {}
        cs = res.get("/ColorSpace")
        if isinstance(cs, IndirectObject):
            cs = self.reader.get_object(cs)
        if not cs:
            return
        for key, value in cs.items():
            # if self.color_map and self.color_map.get(key):
            #     colorSpace[key] = self.color_map[key]

            if isinstance(value, IndirectObject):
                value = self.reader.get_object(value)
            obj = value
            if isinstance(obj, list):
                new_list = []
                for o in obj:
                    if isinstance(o, IndirectObject):
                        o = self.reader.get_object(o)
                    new_list.append(o)

                colorSpace[key] = new_list
                pass
            else:
                colorSpace[key] = obj

        return colorSpace

    def get_fonts(self, res: dict, depth=0) -> dict:
        fonts = {}
        resources = res
        if resources and resources.get("/Font"):
            for font_name, font_object in resources.get("/Font").items():
                if font_name not in fonts:
                    # if self.font_map and font_name in self.font_map:
                    #     fonts[font_name] = self.font_map[font_name]
                    # else:
                    fonts[font_name] = PdfFont(
                        font_name,
                        self.reader.get_object(font_object),
                        self.reader,
                        self.execute_glyph_stream,
                        depth,
                    )
        return fonts

    def get_external_g_state(self, res):
        exgtate = {}
        ext = res.get("/ExtGState")
        if not ext:
            return {}
        if isinstance(ext, IndirectObject):
            ext = self.reader.get_object(ext)
        for key, value in ext.items():
            obj = self.reader.get_object(value)
            exgtate[key] = obj
        return exgtate

    def get_x_object(self, res):
        x_obj = res.get("/XObject", {})
        if isinstance(x_obj, IndirectObject):
            x_obj = self.reader.get_object(x_obj)

        return x_obj

    def update_sub_obj(self, key, value, output_dict, font_name):
        if isinstance(value, IndirectObject):
            new_value = self.reader.get_object(value)
            output_dict[font_name][key] = {}
            for key2, value2 in new_value.items():
                if isinstance(value2, IndirectObject):
                    # print("Indirect Object")
                    output_dict[font_name][key][key2] = self.reader.get_object(
                        value2
                    )
                else:
                    output_dict[font_name][key][key2] = value2
        else:
            output_dict[font_name][key] = value

    # *******************************************************
    # **************** Excecute Stream **********************
    # _______________________________________________________

    def execute_page_stream(self, max_show: int | None = None) -> int:
        # if (
        #     self.font_map is None
        #     or self.current_stream is None
        # ):
        #     raise ValueError("Engine not initialized properly")

        self.max_show = max_show
        self.counter = 0

        # ********************* Initialize renderer and State ********

        self.state = EngineState(
            self.font_map,
            self.color_map,
            self.res,
            self.exgtate,
            self.xobject,
            None,
            self.execute_xobject_stream,
            "MAIN",
            None,
            self.scaling,
            self.scaled_page_height,
            self.debug,
        )
        used_detectors = []
        for detect in self.ALL_DETECTORS:
            (detect.id & self.D_DETECT_QUESTION) and used_detectors.append(
                self.question_detector
            )
        self.renderer = BaseRenderer(self.state, used_detectors, self.clean)

        self.state.draw_image = self.renderer.draw_inline_image

        self.renderer.initialize(
            int(self.scaled_page_width),
            int(self.scaled_page_height),
            self.current_page,
        )
        self.state.ctx = self.renderer.ctx

        # ****************** create Parser ************************

        self.parser = PDFStreamParser()

        # ************* configer DEBUGGING *********************

        debugging = (
            # not self.detection_types and
            self.debug
            & self.M_DEBUG_PAGE_STREAM
        )
        f = None
        if debugging:
            f = open(f"output{sep}output.md", "w", encoding="utf-8")
        self.renderer.output = f
        self.output_file = f
        if debugging:
            f.write("FILE: " + os.path.basename(self.pdf_path) + "\n")
            f.write("PAGE: " + str(self.current_page) + "\n\n\n")

        # ************* start Execution loop *********************

        for cmd in self.parser.parse_stream(self.current_stream).iterate():
            debugging and f.write(f"{cmd}\n")
            explanation, ok = self.state.execute_command(cmd)

            # if debugging and explanation:
            #     f.write(f"{explanation}\n")

            debugging and explanation and f.write(f"{explanation}\n")
            explanation2, ok2 = self.renderer.execute_command(cmd)

            if debugging and explanation2:
                f.write(f"{explanation2}\n")

            if cmd.name in ["Tj", "TJ", "'", '"']:
                self.counter += 1
                if debugging:
                    f.write(f"counter={self.counter}\n\n")

            if max_show and self.counter > max_show:
                break

            if debugging and not ok and not ok2:
                print("CMD:", cmd)
                s = f"{cmd.name} was not handled \n"
                s += f"args : {cmd.args}\n"
                raise Exception("Incomplete Implementaion\n" + s)

        if debugging:
            f.flush()
            f.close()

    def execute_xobject_stream(
        self,
        data_stream: str,
        initial_state: dict,
        xres: dict,
        depth: int,
        stream_name,
    ):

        x_stream = data_stream
        debugging = (
            # not self.detection_types and
            self.debug
            & self.M_DEBUG_XOBJECT_STREAM
        )

        if debugging:
            self.debug_x_stream(xres, x_stream)
        x_font_map = self.get_fonts(xres, depth)
        x_state: EngineState | None = None
        x_exgtate = self.get_external_g_state(xres)
        x_xobject = self.get_x_object(xres)

        x_state = EngineState(
            x_font_map,
            self.color_map,
            xres,
            x_exgtate,
            x_xobject,
            initial_state,
            self.execute_xobject_stream,
            stream_name,
            self.renderer.draw_inline_image,
            self.scaling,
            self.scaled_page_height,
            debugging,
            depth,
        )
        old_state = self.renderer.state
        self.renderer.state = x_state

        if x_font_map is None or x_stream is None:
            raise ValueError("Engine not initialized properly")

        x_state.ctx = self.renderer.ctx

        x_parser = PDFStreamParser()
        f = None
        if debugging:
            if not self.output_file:
                self.output_file = open(
                    f"output{sep}output.md", "w", encoding="utf-8"
                )
            f = self.output_file
            f.write("\n\n\n")
            f.write(f"X_Stream[{depth}]: {stream_name}" + "\n")
            f.write("Enter: " + "\n\n\n")

        for cmd in x_parser.parse_stream(x_stream).iterate():
            debugging and f.write(f"{cmd}\n")
            explanation, ok = x_state.execute_command(cmd)
            if debugging and explanation:
                f.write(f"{explanation}\n")
            explanation2, ok2 = self.renderer.execute_command(cmd)

            (debugging and explanation2) and f.write(f"{explanation}\n")
            if cmd.name in ["Tj", "TJ", "'", '"']:
                self.counter += 1
                debugging and f.write("\n\n")

            if self.max_show and self.counter > self.max_show:
                break

            if not ok and not ok2:
                print("X_CMD:", cmd)
                print("Inside XFORM :")
                s = f"{cmd.name} was not handled \n"
                s += f"args : {cmd.args}\n"
                raise Exception("Incomplete Implementaion\n" + s)

        if debugging:
            f.write("\n\n")
            f.write(f"X_Stream[{depth}]: " + "\n")
            f.write("Exit: " + "\n\n\n")
        # print("\nExit X_FORM\n\n")
        self.renderer.state = old_state

    def execute_glyph_stream(
        self, stream: str, ctx: cairo.Context, char_name: str, font_matrix
    ):

        debugging = (
            # not self.detection_types and
            self.debug
            & self.M_DEBUG_GLYPH_STREAM
        )
        if debugging:
            with open(
                f"output{sep}font_stream.txt", "w", encoding="utf-8"
            ) as f:
                f.write("# page number " + str(self.current_page) + "\n\n")
                f.write(stream)

        font_state = EngineState(
            font_map=self.font_map,
            color_map=self.color_map,
            resources=self.res,
            exgstat=None,
            xobj=None,
            initial_state=None,
            execute_xobject_stream=self.execute_xobject_stream,
            stream_name=char_name,
            draw_image=self.renderer.draw_inline_image,
            scale=self.scaling,
            scaled_screen_height=self.scaled_page_height,
            debug=debugging,
            depth=self.state.depth,
        )
        m: cairo.Matrix = font_matrix
        cairo.Matrix()
        font_state.set_ctm(
            PdfOperator("cm", [m.xx, m.yx, m.xy, m.yy, m.x0, m.y0])
        )
        old_state = self.renderer.state
        old_ctx = self.renderer.ctx

        self.renderer.state = font_state
        self.renderer.ctx = ctx
        font_state.ctx = ctx

        if stream is None:
            raise ValueError("Font stream is None")

        x_parser = PDFStreamParser()

        f = None
        if debugging:
            if not self.output_file:
                self.output_file = open(
                    f"output{sep}output.md", "w", encoding="utf-8"
                )
            f = self.output_file
            f.write("\n\n\n")
            f.write(f"Font_Stream[{self.state.depth}]: {char_name}" + "\n")
            f.write("Enter: " + "\n\n\n")
        print("\n\nEnter Font_Stream\n")
        for cmd in x_parser.parse_stream(stream).iterate():
            debugging and f.write(f"{cmd}\n")
            explanation, ok = font_state.execute_command(cmd)
            if debugging and explanation:
                f.write(f"{explanation}\n")
            explanation2, ok2 = self.renderer.execute_command(cmd)
            if debugging and explanation2:
                f.write(f"{explanation}\n")
            if cmd.name in ["Tj", "TJ", "'", '"']:
                debugging and f.write("\n\n")
                self.counter += 1

            if not ok and not ok2:
                print("Font_CMD:", cmd)
                print("Inside Font_State :")
                s = f"{cmd.name} was not handled \n"
                s += f"args : {cmd.args}\n"
                raise Exception("Incomplete Implementaion\n" + s)

        if debugging:
            f.write("\n\n")
            f.write(f"Font_Stream[{self.state.depth}]: " + "\n")
            f.write("Exit: " + "\n\n\n")
        self.renderer.state = old_state
        self.renderer.ctx = old_ctx

    # **********************************************************
    # *************+ Proccess ImageSurface *********************
    # ************** and Segments ....     *********************
    # __________________________________________________________

    def remove_empty_lines_from_current_page(
        self, page_surf: cairo.ImageSurface
    ):
        """this should only be called after self.execute_page_stream()
        it will raise Exception if the PageSurface is empty !!!"""

        # if page_number > len(self.pages):
        #     raise Exception("page number out of index ,nr=", page_number)
        page_number = self.current_page
        # if page_number in self.page_seg_dict:
        #     page_seg_obj = self.page_seg_dict[page_number]
        # else:
        page_seg_obj = SurfaceGapsSegments(page_surf, scale=self.scaling)
        net_height = page_seg_obj.net_height
        if net_height <= 0:
            raise Exception("Total Height = 0")
        seg = page_seg_obj.non_empty_segments

        out_ctx = None
        out_surf = None
        # self.default_d0 = None
        out_surf = cairo.ImageSurface(
            cairo.FORMAT_ARGB32,
            int(self.scaled_page_width),
            int(self.scaled_page_height),
        )
        out_ctx = cairo.Context(out_surf)
        out_ctx.set_source_rgb(1, 1, 1)  # White
        out_ctx.paint()
        out_ctx.set_source_rgb(0, 0, 0)  # Black

        if not seg or len(seg) == 0:
            raise Exception(f"WARN: page {page_number}, no Segments found")
        start_y = 0
        last_y = page_seg_obj.clip_segments_from_surface_into_contex(
            out_ctx, start_y, self.scaling
        )

        if last_y == 0:
            raise Exception(
                f"WARN: page {page_number}, no Segments could be drawn"
            )

        padding = 2 * (page_seg_obj.d0)
        return crop_image_surface(out_surf, start_y, last_y, padding)


if __name__ == "__main__":
    pdf_path = "9702_m23_qp_12.pdf"
    pdf_engine = PdfEngine(pdf_path)
    data = pdf_engine.load_page_content(3)
    # pdf_engine.execute_stream(stream)
    pass
