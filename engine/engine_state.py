import io
from os import sep
from pprint import pprint
from typing import Any
import cairo
import string

from PIL import Image
from pypdf.generic import DictionaryObject

from engine.pdf_utils import kill_with_taskkill, open_image_in_irfan
from .pdf_operator import PdfOperator
from .pdf_font import PdfFont
from pypdf.filters import (
    ASCII85Decode,
    ASCIIHexDecode,
    LZWDecode,
    # DCTDecode,
    decompress,
    FlateDecode,
    CCITTFaxDecode,
)
from cairo import Matrix
from .pdf_encoding import PdfEncoding as pnc
import copy


class EngineState:

    INLINE_DECODER_MAP = {
        "/LZW": "decode_lzw",
        "/RL": "decode_run_length",
        "/DCT": "decode_dct",
        "/A85": "decode_ascii85",
        "/AHx": "decode_ascii_hex",
        "/Flate": "decode_flat_decompress",
        "/CCF": "decode_cff_image",
    }

    PRINTABLE = string.ascii_letters + string.digits + string.punctuation + " "
    MAX_X_DEPTH = 100

    DEVICE_CS = ["/DeviceGray", "/DeviceRGB", "/DeviceCMYK"]
    CIE_CS = ["/CalGray", "/CalRGB", "/Lab", "/ICCBased"]
    SPECIAL_CS = ["/Indexed", "/Separation", "/DeviceN", "/Pattern"]
    ALL_COLOR_SPACES = [*DEVICE_CS, *CIE_CS, *SPECIAL_CS]

    FALLBACK_CS = "/Unsupported"

    SUPPORTED_CS = [*DEVICE_CS, FALLBACK_CS]

    DEFAULT_COLORS = {
        "/DeviceGray": [0, 0, 0],
        "/DeviceRGB": [0, 0, 0],
        "/DeviceCMYK": [0, 0, 0],
        FALLBACK_CS: [0, 0, 0],
    }

    def __init__(
        self,
        font_map: dict[str, PdfFont],
        color_map: dict,
        resources: dict,
        exgstat: dict[str, Any],
        xobj: dict[str, Any],
        initial_state: dict | None,
        execute_xobject_stream: callable,
        stream_name: str,
        draw_image: callable,
        scale: int,
        scaled_screen_height: int = 0,
        debug: bool = False,
        depth: int = 0,
    ):
        """"""
        # *************** Begin Variables ******************
        # **********
        # *****
        # **
        # *

        # ***************** function args variables ****************
        self.font_map = font_map
        self.color_map = color_map or {}
        self.res = resources
        self.exgstate = exgstat
        self.xobj = xobj
        self.execute_xobject_stream = execute_xobject_stream
        self.stream_name = stream_name
        self.draw_image = draw_image
        self.scale = scale
        self.screen_height = scaled_screen_height
        self.debug = debug
        self.depth = depth
        self.ctx: cairo.Context = None

        # *************** location tracking variables ******************
        CTM = [scale, 0.0, 0.0, scale, 0.0, 0.0]
        text_matrix = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
        self.cm_matrix = Matrix(*CTM)
        self.tm_matrix = Matrix(*text_matrix)  # for text
        self.text_position = [0.0, 0.0]  # for text
        self.position = [0.0, 0.0]  # for shapes

        # ************ font/text related variables ****************
        self.in_text_block = False
        self.font: PdfFont | None = None

        # for key, value in self.font_map.items():
        #     self.font: PdfFont | None = value
        #     break
        self.font_size = 0
        self.character_spacing = 0.0
        self.word_spacing = 0.0
        self.leading = 0.0
        self.text_rize = 0.0
        self.horizontal_scaling = 100.0

        # ************* color related variables **************
        self.color_space_stroke = None
        self.color_space_fill = None
        self.stroke_color = [0.0, 0.0, 0.0]
        self.fill_color = [0.0, 0.0, 0.0]

        # ************* drawing/shapes variables *****************
        self.line_width: float = 1.0
        self.dash_pattern = []
        self.line_cap = cairo.LINE_CAP_BUTT
        self.line_join = cairo.LINE_JOIN_MITER
        self.miter_limit = 10.0
        self.state_stack: list[dict] = []

        self.inline_image_width = 0
        self.inline_image_height = 0
        self.inline_image_bits_per_component = 0
        self.inline_image_mask = False
        self.inline_image_filter = []
        self.inline_image_color_space = None
        self.inline_image_data: bytes = b""

        # ************** EXTstate variables ********************
        self._stroke_alpha = 1
        self._fill_alpha = 1
        self.overprint_stroke = False
        self.overprint_fill = False
        self.overprint_mode = 0  # 0=PDF v1, 1=PDF v3+
        self.blend_mode = None
        self.soft_mask = None
        self.stroke_adjustment = False

        # ************** OTHERS *********************
        self.text_rendering_mode = 0  # Default: Fill text
        # ************** Debuging *******************
        self.missing_font_count = 0

        # *
        # **
        # *****
        # **********
        # *************** END Variables ******************

        if initial_state:
            self.restore_state(None, initial_state)

        self.functions_map = {
            # generall
            "q": self.save_state,
            "Q": self.restore_state,
            "BT": self.begin_text,
            "ET": self.end_text,
            "gs": self.set_graphics_state,
            "Tr": self.set_text_rendering_mode,
            "Do": self.handle_Do,
            ## Positioning
            "cm": self.set_ctm,
            "Tm": self.set_text_matrix,
            "Td": self.set_text_position,
            "TD": self.set_text_position_and_leading,
            "T*": self.move_with_leading,
            "TJ": self.clear_text_position_after_tj,
            "Tj": self.updata_missing_font_count,
            "'": self.move_with_leading,
            '"': self.move_with_leading_and_spacing,
            # font and text
            "Tc": self.set_character_spacing,
            "Tw": self.set_word_spacing,
            "Tz": self.set_horizontal_scaling,
            "TL": self.set_leading,
            "Tf": self.set_font,
            "Ts": self.set_text_rize,
            # graphics state operators
            "w": self.set_line_width,
            "d": self.set_dash_pattern,
            "J": self.set_line_cap,
            "j": self.set_line_join,
            "M": self.set_meter_limit,
            # -------------------
            # inline image operators
            "BI": self.begin_inline_image,
            "/W": self.set_inline_image_width,
            "/H": self.set_inline_image_height,
            "/BPC": self.set_inline_image_bits_per_component,
            "/CS": lambda x: self.set_color_space(x, False, True),
            "/F": self.set_inline_image_filter,
            # "/F": self.set_inline_image_dcode_filter,
            "/IM": self.set_inline_image_mask,
            "/DP": self.set_inline_image_decode_params,
            "/D": lambda x: ("", True),
            "ID": self.decode_inline_image,
            "EI": self.end_inline_image,  # lambda _: (None, True),
            # -------------------
            # Color Operators
            "cs": lambda x: self.set_color_space(x, True),
            "CS": lambda x: self.set_color_space(x, False),
            "k": lambda x: self.set_color(x, True, "/DeviceCMYK"),
            "K": lambda x: self.set_color(x, False, "/DeviceCMYK"),
            "g": lambda x: self.set_color(x, True, "/DeviceGray"),
            "G": lambda x: self.set_color(x, False, "/DeviceGray"),
            "rg": lambda x: self.set_color(x, True, "/DeviceRGB"),
            "RG": lambda x: self.set_color(x, False, "/DeviceRGB"),
            "sc": lambda x: self.set_color(x, True, None),
            "SC": lambda x: self.set_color(x, False, None),
            "scn": lambda x: self.set_color(x, True, None),
            "SCN": lambda x: self.set_color(x, False, None),
            # ---- ---------
            # Unkown Operatorso
            "BX": lambda x: ("", True),
            "EX": lambda x: ("", True),
            "sh": self.handle_sh_operator,
            "d0": lambda x: ("", True),
            "d1": lambda x: ("", True),
            # ---- ---------
            # Path  Construction
            # cairo only
            # "m" : self.move_position,
            # "l" : self.draw_line_to
            # "S" : self.stroke_path,
            # "h": self.close_path,
            # "c": self.curve_to,
        }

    def handle_sh_operator(self, command: PdfOperator):
        return "", True

    def set_color_space(
        self, command: PdfOperator, is_fill: bool, is_image: bool = False
    ):
        space = command.args[0]
        # if self.color_map.get(space):
        #     alternatives = self.get_alternative_color_space(
        #         self.color_map.get(space)
        #     )
        self.inline_image_color_space
        dest_space = (
            "color_space_fill"
            if is_fill
            else (
                "inline_image_color_space"
                if is_image
                else "color_space_stroke"
            )
        )
        dest_color = (
            "fill_color" if is_fill else (None if is_image else "stroke_color")
        )

        if space not in self.SUPPORTED_CS:
            # print(
            #     f"Color Space {space}, is cuurently not implemented !!, fallback to black"
            # )
            space = self.FALLBACK_CS
            # raise Exception(
            #     f"Color Space {space}, is cuurently not implemented !!"
            # )

        self.__setattr__(dest_space, space)
        if dest_color:
            self.__setattr__(dest_color, self.DEFAULT_COLORS[space])

        return "", True

    def set_color(
        self, cmd: PdfOperator, is_fill: bool, color_space: str | None = None
    ):
        state_cs = "color_space_fill" if is_fill else "color_space_stroke"
        if color_space:
            self.__setattr__(state_cs, color_space)
        elif self.__getattribute__(state_cs):
            color_space = self.__getattribute__(state_cs)
        else:
            raise Exception(
                "Color space was neither provieded nor Existing is current state !"
            )
        if color_space in self.DEVICE_CS:
            components = [float(arg) for arg in cmd.args]
        else:
            components = None

        state_color = "fill_color" if is_fill else "stroke_color"

        if color_space == "/DeviceGray":
            gray = components[0]
            self.__setattr__(state_color, [gray, gray, gray])
        elif color_space == "/DeviceRGB":
            self.__setattr__(state_color, components[:3])
        elif color_space == "/DeviceCMYK":
            c, m, y, k = components
            r = (1 - c) * (1 - k)
            g = (1 - m) * (1 - k)
            b = (1 - y) * (1 - k)
            self.__setattr__(state_color, [r, g, b])
        # elif color_space == "/Pattern":
        #     raise Exception("pattern color not yet implemented !")
        elif color_space == self.FALLBACK_CS:
            pass
            # self.__setattr__(dest_color, self.DEFAULT_COLORS[space])
        else:
            raise Exception(f"Unsupported color space: {color_space}")

        # Apply alpha from graphics state
        # self.fill_color.append(self.fill_alpha)
        return "", True

    def set_stroke_color_gray(self, command: PdfOperator):
        grayscale = float(command.args[0]) * 255
        self.stroke_color = [grayscale, grayscale, grayscale]
        if self.debug:
            return None, True
        return "", True

    def set_fill_color_gray(self, command: PdfOperator):
        grayscale = float(command.args[0]) * 255
        self.fill_color = [grayscale, grayscale, grayscale]
        if self.debug:
            return None, True
        return "", True

    def set_cmyk_color(self, cmd: PdfOperator, is_fill):
        """k operator - Set CMYK color for filling"""
        c, m, y, k = cmd.args
        # Convert CMYK to RGB (simplified conversion)
        r = (1 - c) * (1 - k)
        g = (1 - m) * (1 - k)
        b = (1 - y) * (1 - k)
        if is_fill:
            self.fill_color = [r, g, b]
        else:
            self.stroke_color = [r, g, b]
        if self.debug:
            return [c, m, y, k], True
        return "", True

    def handle_Do(self, cmd: PdfOperator):
        xobj_name = cmd.args[0]
        xobjs = self.xobj

        if xobj_name not in xobjs:
            print(f"XObject {xobj_name} not found")
            return "", False

        xobj = xobjs[xobj_name]
        subtype = xobj.get("/Subtype")

        if subtype == "/Image":
            return "", True
            self._draw_image_xobject(xobj)
        elif subtype == "/Form":
            # if xobj_name == self.stream_name:
            # print("not skipping (== handling ) recursive xobject stream !")
            # return "", True
            self._draw_form_xobject(xobj, xobj_name)
        else:
            print(f"Unsupported XObject type: {subtype}")

        return "", True

    def _merge_resources(self, form_resources):
        # Convert PDF dictionaries to normal dicts
        parent_res = {k: v for k, v in self.res.items()}
        form_res = {k: v for k, v in form_resources.items()}
        # print("parent_res")
        # pprint(parent_res)
        # print("form_res")
        # pprint(form_res)

        merged = {}

        # PDF resource categories (Section 7.8.3 PDF 32000-1:2008)
        categories = [
            "/ExtGState",
            "/ColorSpace",
            "/Pattern",
            "/Shading",
            "/Font",
            "/XObject",
            "/Properties",
            "/ProcSet",
        ]

        for category in categories:
            parent_items = parent_res.get(category, {}).copy()
            form_items = form_res.get(category, {}).copy()

            # if category == "/Font":
            #     print(form_items)
            #     merged[category] = form_items
            #     continue

            if isinstance(parent_items, (dict, DictionaryObject)):

                parent_items = {k: v for k, v in parent_items.items()}
                form_items = {k: v for k, v in form_items.items()}

                merged[category] = {
                    **parent_items,
                    **form_items,
                }
            elif form_items:
                merged[category] = form_items
            elif parent_items:
                merged[category] = parent_items

        if "/ProcSet" not in form_res:
            merged["/ProcSet"] = parent_res.get("/ProcSet", ["/PDF"])

        # print("*************** merged_res")
        # pprint(merged)
        return merged

    def _copy_matrix(self, m: Matrix):
        return Matrix(m.xx, m.yx, m.xy, m.yy, m.x0, m.y0)

    def _draw_form_xobject(self, xobj, xobj_name):
        # Save graphics state

        new_depth = self.depth + 1
        if new_depth > self.MAX_X_DEPTH:
            print(f"WARNING: Ignoring xform with depth = {new_depth}")
            return

        self.ctx.save()
        # self.save_state(None)

        # Apply form matrix (default: identity)
        form_matrix = Matrix(*xobj.get("/Matrix", [1, 0, 0, 1, 0, 0]))  #
        # print
        curr_cm = self.cm_matrix
        form_matrix = curr_cm.multiply(form_matrix)
        # self.ctx.transform(Matrix(*form_matrix))

        initial_state = self.dump_dict()
        initial_state["cm_matrix"] = form_matrix

        form_resources = xobj.get("/Resources", {})
        merged_resources = self._merge_resources(form_resources)

        # Process form content stream
        # filters = xobj.get("/Filter", [])
        data = xobj.get_data()
        stream = (
            pnc.bytes_to_string(data).encode("latin1").decode("unicode_escape")
        )
        self.execute_xobject_stream(
            stream, initial_state, merged_resources, new_depth, xobj_name
        )

        self.ctx.restore()
        # self.restore_state(None)

    def _draw_image_xobject(self, xobj):

        # self.ctx.save()
        # self.save_state(None)

        self.inline_image_width = int(xobj["/Width"])
        self.inline_image_height = int(xobj["/Height"])
        self.inline_image_color_space = xobj.get("/ColorSpace", "/DeviceRGB")
        original_bits_per_component = int(xobj.get("/BitsPerComponent", 8))
        self.inline_image_decoder_param = xobj.get("/DecodeParms", {})
        self.inline_image_bits_per_component = original_bits_per_component
        self.inline_image_mask = False

        self.inline_image_filter = xobj.get("/Filter", [])
        if not isinstance(self.inline_image_filter, list):
            self.inline_image_filter = [self.inline_image_filter]
        data = xobj.get_data()
        self.decode_inline_image(None, data)

        if not self.inline_image_data:
            return

        if self.inline_image_bits_per_component % 8 == 0:
            soll_pixel_count = (
                self.inline_image_height * self.inline_image_width
            )
            bytes_per_component = self.inline_image_bits_per_component // 8
            ist_pixel_count = (
                len(self.inline_image_data) // bytes_per_component
            )

            # print(f"soll-ist : {soll_pixel_count} vs {ist_pixel_count}")
            if soll_pixel_count != ist_pixel_count:
                raise Exception("This image is not OK")
            cs = self.inline_image_color_space
            if cs == "/DeviceRGB" and bytes_per_component != 3:
                raise Exception("image values for RGB are not devidable by 3")
                pass
            elif cs == "/DeviceCMYK":
                raise Exception("image values for CMYK are not devidable by 4")
                pass
        elif self.inline_image_bits_per_component != 1:
            raise Exception(
                "sub-deviding a single byte require using shifts '<<'\nwhich is currently not implemented"
            )

        self.draw_image(None)
        # self.ctx.restore()
        return

    def begin_text(self, _: PdfOperator):

        self.in_text_block = True
        self.tm_matrix = Matrix(1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        self.text_position = [0, 0]
        return "", True

    def end_text(self, _: PdfOperator):
        self.in_text_block = False
        return "", True

    def get_current_matrix(
        self,
    ):
        """Get the appropriate transformation matrix based on context"""

        cc0 = cairo.Matrix(1, 0, 0, -1, 0, self.screen_height)
        cm = self.cm_matrix
        if self.in_text_block:
            tm = self.tm_matrix
            cc1 = cairo.Matrix(1, 0, 0, -1, 0, 0)
            # fz = self.font_size
            # tm_pre_matrix = Matrix(
            #     fz * self.horizontal_scaling * 1,
            #     0,
            #     0,
            #     fz * -1,
            #     0,
            #     self.text_rize,
            # )
            return cc1.multiply(tm.multiply(cm.multiply(cc0)))
        else:
            cc1 = cairo.Matrix(1, 0, 0, 1, 0, 0)
            return cc1.multiply(cm.multiply(cc0))

    def decode_lzw(self, data: bytes):
        return LZWDecode.decode(data)

    def decode_run_length(self, data: bytes):
        return decompress(data)

    def decode_flat_decompress(self, data: bytes):
        # print("trying to decode flat decode")
        return FlateDecode.decode(data, self.inline_image_decoder_param)

    def decode_cff_image(self, data: bytes):
        param = self.inline_image_decoder_param

        class CDict(dict):
            def get_object(
                self,
            ):
                return self

            def __init__(self, dict2):
                for key, value in dict2.items():
                    self.__dict__[key] = value

        param_dict = CDict(param)
        decoeded = CCITTFaxDecode.decode(
            data=data,
            decode_parms=param_dict,
        )
        print("decoded_img_ccf =", decoeded)

        # self.inline_image_bits_per_component = 8
        # self.inline_image_color_space = "/DeviceRGB"
        return decoeded

    def cmyk_to_bgrx(cmyk_data, width, height):
        """Convert CMYK to Cairo's BGRx format"""
        img = Image.frombytes("CMYK", (width, height), cmyk_data)
        img = img.convert("RGB")
        bgrx = bytearray()
        for r, g, b in img.getdata():
            bgrx.extend([b, g, r, 0])  # BGRx format

        return bytes(bgrx)

    def test_play_image(self, img):
        img_path = f"output{sep}temp-image.png"
        img.save(img_path)
        open_image_in_irfan(img_path)
        input("waiting")
        kill_with_taskkill()

    def decode_dct(self, data: bytes):
        img = Image.open(io.BytesIO(data))
        # if img.has_transparency_data:
        #     input("the image has transparency data")
        img = img.convert("RGB")
        width, height = img.size
        bgrx_data = bytearray()
        # rgb_data = bytearray()
        for r, g, b in img.getdata():
            bgrx_data.extend([b, g, r])  # 0 = unused alpha
            # max_byte = max(r, g, b)
            # f = 255 // max_byte
            # rgb_data.extend([r * f, g * f, b * f])
        # img2 = Image.frombytes("RGB", size=img.size, data=rgb_data)
        # self.test_play_image(img2)
        self.inline_image_bits_per_component = 24
        self.inline_image_color_space = "/DeviceRGB"

        return bytes(bgrx_data)

    def decode_ascii85(self, data: bytes):
        return ASCII85Decode.decode(data)

    def decode_ascii_hex(self, data: bytes):
        decoded_str = ASCIIHexDecode.decode(data.decode("ascii"))
        return decoded_str.encode("ascii")

    def hex_escape(self, s):
        return "".join(
            (c if c in EngineState.PRINTABLE else r"\x{0:02x}".format(ord(c)))
            for c in s
        )

    # def set_inline_image_dcode_filter(self, cmd: PdfOperator):
    #     filter = cmd.args[0]
    #     self.inline_image_filter = [filter]
    #     print("inline image filter =", filter)
    #     return "", True

    def set_inline_image_decode_params(self, cmd: PdfOperator):
        param = cmd.args[0]
        self.inline_image_decoder_param = param
        print("inline image decode params=", type(param), param)
        return "", True

    def decode_inline_image(self, operator: PdfOperator, data=None):
        if operator and len(operator.args) == 0:
            raise ValueError("No image data found in inline image")
        if not data:
            data = operator.args[0]
        if isinstance(data, str):
            data = pnc.string_to_bytes(data)

        decoded_data = data
        for filter_name in self.inline_image_filter:
            filter_name = filter_name.replace("Decode", "")
            decoder_method_name = self.INLINE_DECODER_MAP.get(filter_name)
            if decoder_method_name:
                decoder = getattr(self, decoder_method_name)
                try:
                    decoded_data = decoder(decoded_data)
                except Exception as e:
                    print(f"Could not decode Image using {filter_name}")
                    decoded_data = None
                    raise Exception(e)
        self.inline_image_data = decoded_data
        return "", True

    def begin_inline_image(self, _: PdfOperator):
        # self.ctx.save()
        # self.save_state(None)
        self.inline_image_width = 0
        self.inline_image_height = 0
        self.inline_image_bits_per_component = 0
        self.inline_image_color_space = None
        self.inline_image_mask = False
        return "", True

    def end_inline_image(self, cmd: PdfOperator):
        """this function should only called from renderer
        after finishing the drawing of the image"""
        # self.ctx.restore()
        # self.restore_state()
        return "", True

    def set_inline_image_width(self, command: PdfOperator):
        self.inline_image_width = int(command.args[0])
        return "", True

    def set_inline_image_height(self, command: PdfOperator):
        self.inline_image_height = int(command.args[0])
        return "", True

    def set_inline_image_bits_per_component(self, command: PdfOperator):
        bpc = int(command.args[0])
        self.inline_image_bits_per_component = bpc
        return "", True

    def set_inline_image_mask(self, command: PdfOperator):
        self.inline_image_mask = bool(command.args[0])
        return "", True

    def set_inline_image_filter(self, command: PdfOperator):
        filter = command.args[0]
        if isinstance(filter, str):
            filter = [filter]
        self.inline_image_filter = filter
        return "", True

    def set_inline_image_color_space(self, command: PdfOperator):
        self.inline_image_color_space = command

    def dump_dict(self):
        m1 = self.cm_matrix
        m2 = self.tm_matrix
        return {
            # "CTM": copy.copy(self.CTM),
            # "text_matrix": copy.copy(self.text_matrix),
            "cm_matrix": copy.copy([m1.xx, m1.yx, m1.xy, m1.yy, m1.x0, m1.y0]),
            "tm_matrix": copy.copy([m2.xx, m2.yx, m2.xy, m2.yy, m2.x0, m2.y0]),
            "text_position": copy.copy(self.text_position),
            "character_spacing": copy.copy(self.character_spacing),
            "word_spacing": copy.copy(self.word_spacing),
            "horizontal_scaling": copy.copy(self.horizontal_scaling),
            "leading": copy.copy(self.leading),
            "font_name": copy.copy(self.font.font_name) if self.font else None,
            "font_size": copy.copy(self.font_size),
            "text_rize": copy.copy(self.text_rize),
            "line_width": copy.copy(self.line_width),
            "position": copy.copy(self.position),
            "dash_pattern": copy.copy(self.dash_pattern),
            "stroke_color": copy.copy(self.stroke_color),
            "fill_color": copy.copy(self.fill_color),
            "color_space_stroke ": copy.copy(self.color_space_stroke),
            "color_space_fill": copy.copy(self.color_space_fill),
            "_stroke_alpha": copy.copy(self.stroke_alpha),
            "_fill_alpha ": copy.copy(self.fill_alpha),
            "miter_limit": copy.copy(self.miter_limit),
            "line_cap": copy.copy(self.line_cap),
            "line_join": copy.copy(self.line_join),
            # inline image
            "inline_image_width": copy.copy(self.inline_image_width),
            "inline_image_height": copy.copy(self.inline_image_height),
            "inline_image_bits_per_component": copy.copy(
                self.inline_image_bits_per_component
            ),
            "inline_image_mask": copy.copy(self.inline_image_mask),
            "text_rendering_mode": copy.copy(self.text_rendering_mode),
        }

    def save_state(self, _: PdfOperator):
        # print("saving state")
        self.state_stack.append(self.dump_dict())
        return "", True

    def restore_state(
        self, _: PdfOperator | None = None, dump: dict | None = None
    ):
        if not dump and len(self.state_stack) == 0:
            # raise Exception("stack is empty")
            return None
        # print("restoring state")
        if not dump:
            state = self.state_stack.pop()
        else:
            state = dump
        for key, value in state.items():
            if key == "cm_matrix" or key == "tm_matrix":
                setattr(self, key, Matrix(*value))
            elif key == "font_name":
                if value:
                    self.font = self.font_map[value]  # if value else
                else:
                    self.font = None
                    # raise Exception(
                    #     f"font ({value}) can not be found on depth {self.depth}"
                    # )

            else:
                setattr(self, key, value)

        # print(self.cm_matrix)
        return "", True

    def set_line_width(self, command: PdfOperator):
        self.line_width = float(command.args[0])
        if self.debug:
            cm = self.cm_matrix
            return [cm.transform_distance(self.line_width, 0)[0]], True
        return "", True

    def set_dash_pattern(self, command: PdfOperator):
        self.dash_pattern = command.args[0]
        if self.debug:
            return None, True
        return "", True

    def set_line_cap(self, command: PdfOperator):
        value = int(command.args[0])
        if value == 0:
            self.line_cap = cairo.LINE_CAP_BUTT
        elif value == 1:
            self.line_cap = cairo.LINE_CAP_ROUND
        elif value == 2:
            self.line_cap = cairo.LINE_CAP_SQUARE

        if self.debug:
            return None, True
        return "", True

    def set_line_join(self, command: PdfOperator):
        value = int(command.args[0])
        if value == 0:
            self.line_join = cairo.LINE_JOIN_MITER
        elif value == 1:
            self.line_join = cairo.LINE_JOIN_ROUND
        elif value == 2:
            self.line_join = cairo.LINE_JOIN_BEVEL

        if self.debug:
            return None, True
        return "", True

    def set_meter_limit(self, command: PdfOperator):
        self.miter_limit = float(command.args[0])
        if self.debug:
            return None, True
        return "", True

    def set_font(self, command: PdfOperator):
        fontname, font_size = command.args
        self.font = self.font_map[fontname]
        self.font_size = float(font_size)
        if self.debug:
            return "", True
        return "", True

    # ========================================
    # ============ NEED REVISION =============
    # ============== BELOW  ==================
    def is_matrix_invertible(self, matrix: cairo.Matrix) -> bool:
        """Check if matrix can be inverted (determinant != 0)"""
        determinant = matrix.xx * matrix.yy - matrix.xy * matrix.yx
        return abs(determinant) > 1e-6  # Account for floating-point precision

    def set_ctm(self, command: PdfOperator):
        """
        Modifies the CTM by concatenating the specified matrix. Although the operands
        specify a matrix, they are passed as six numbers, not an array
        multiply old ctm with new one
        """

        # if not self.is_matrix_invertible(updated_matrix):
        #     print("skipping not-invertable matrix")
        #     return "", True

        # args[0] = args[0] or 1
        # args[3] = args[3] or 1

        args = command.args

        if args[0] == 0.0:  # and args[1] == 0:
            args[0] = 0.000000001  # self.scale  #
        if args[3] == 0.0:  # and args[2] == 0:
            args[3] = 0.0000000001  # self.scale

        new_ctm_matrix = Matrix(*args)
        updated_matrix = new_ctm_matrix.multiply(self.cm_matrix)
        self.cm_matrix = updated_matrix

        if self.debug:
            return self.get_current_position_for_debuging(), True
        return "", True

    def set_text_matrix(self, command: PdfOperator):
        # if not self.in_text_block:
        #     return  # Ignore text matrix operations outside text blocks
        args = command.args
        # if args[0] == 0.0:
        #     args[0] = 0.000000001  # self.scale  #
        # if args[3] == 0.0:
        #     args[3] = 0.0000000001  # self.scale
        self.tm_matrix = Matrix(*args)
        self.text_position = [0.0, 0.0]
        # self.text_position = [self.tm_matrix.x0, self.tm_matrix.y0]
        if self.debug:
            return self.get_current_position_for_debuging(), True
        return "", True

    def set_text_position(self, command: PdfOperator):
        """
        set position offset from text-space origin
        """
        x, y = [*command.args]
        # self.tm_matrix.translate(x0, y0)
        self.tm_matrix.translate(x, y)
        # self.tm_matrix = Matrix(1, 0, 0, 1, x, y).multiply(self.tm_matrix)
        self.text_position = [0.0, 0.0]
        if self.debug:
            return self.get_current_position_for_debuging(), True

        return "", True

    def set_leading(self, command: PdfOperator):
        self.leading = float(command.args[0])
        if self.debug:
            return self.get_current_position_for_debuging(), True
        return "", True

    def set_text_position_and_leading(self, command: PdfOperator):
        x, y = [*command.args]
        self.leading = -float(y)
        self.tm_matrix.translate(x, y)
        # self.tm_matrix = Matrix(1, 0, 0, 1, x, y).multiply(self.tm_matrix)
        self.text_position = [0.0, 0.0]
        if self.debug:
            return self.get_current_position_for_debuging(), True
        return "", True

    def get_current_position_for_debuging(
        self, screen_width=None, screen_height=None
    ):
        m = (
            self.get_current_matrix()
        )  # self.tm_matrix.multiply(self.cm_matrix)
        x, y = m.transform_point(0, 0)
        x = f"{x/screen_width*100:.3f}%" if screen_width else x
        y = f"{y/screen_height*100:.3f}%" if screen_height else y
        return (x, y)

    def move_with_leading(self, _: PdfOperator):
        self.tm_matrix.translate(0, -self.leading)
        self.text_position = [0, 0]
        self.updata_missing_font_count()
        if self.debug:
            return None, True
        return "", True

    def move_with_leading_and_spacing(self, command: PdfOperator):
        sw, sc = command.args
        self.character_spacing = float(sc)
        self.word_spacing = float(sw)
        self.tm_matrix.translate(0, self.leading)
        self.text_position = [0, 0]
        self.updata_missing_font_count()
        if self.debug:
            return self.get_current_position_for_debuging(), True
        return "", True

    def set_character_spacing(self, command: PdfOperator):
        self.character_spacing = float(command.args[0])

        if self.debug:
            return self.get_current_position_for_debuging(), True
        return "", True

    def set_word_spacing(self, command: PdfOperator):
        self.word_spacing = float(command.args[0])
        if self.debug:
            return self.get_current_position_for_debuging(), True
        return "", True

    def set_horizontal_scaling(self, command: PdfOperator):
        self.horizontal_scaling = command.args[0]
        # self.cm_matrix.scale(self.horizontal_scaling / 100.0, 1)
        if self.debug:
            return None, True
        return "", True

    def updata_missing_font_count(self, cmd: PdfOperator | None = None):
        if self.font.use_system_font:
            self.missing_font_count += 1
        return "", None

    def list_all_missing_font(self):
        return [
            f.base_font
            for (n, f) in self.font_map.items()
            if f.use_system_font
        ]

    def clear_text_position_after_tj(self, _: PdfOperator):
        # WARN:
        """WARN:NEVER clear txt position after tj !!!1"""

        # WARN: following line is WRONG
        # self.text_position = [0, 0]
        self.updata_missing_font_count()

        return "", True
        pass

    def set_text_rize(self, command: PdfOperator):
        self.set_text_rize = command.args[0]
        # self.tm_matrix.translate(0, self.text_rize)
        if self.debug:
            return self.get_current_position_for_debuging(), True
        return "", True

    def convert_em_to_ts(self, em: float):
        return em / 1000 * self.font_size

    def execute_command(self, command: PdfOperator):
        func = self.functions_map.get(command.name)
        if func:
            args_scaled, ok = func(command)
            if args_scaled:
                return f"current position = {args_scaled}", True
            return "", True
        else:
            return "", False
        return "", False

    def set_graphics_state(self, cmd: PdfOperator):
        gstate_name = cmd.args[0]
        if gstate_name not in self.exgstate:
            return "", True

        return "", True
        gs_dict = self.exgstate[gstate_name]  # .resolve().get_object()

        # Map ExtGState parameters to existing functions/state variables
        ext_state_handlers = {
            # Line styles
            "/LW": (self.set_line_width, lambda v: [float(v)]),
            "/LC": (self.set_line_cap, lambda v: [int(v)]),
            "/LJ": (self.set_line_join, lambda v: [int(v)]),
            "/ML": (self.set_meter_limit, lambda v: [float(v)]),
            "/D": (self.set_dash_pattern, lambda v: [v[0], float(v[1])]),
            # Color/transparency
            "/CA": (self._set_stroke_alpha, lambda v: [float(v)]),
            "/ca": (self._set_fill_alpha, lambda v: [float(v)]),
            "/BM": (self._set_blend_mode, lambda v: [v]),
            "/SMask": (self._set_soft_mask, lambda v: [v]),
            # Text state (deprecated but handled)
            "/Font": (self.set_font, lambda v: [v[0], float(v[1])]),
            # Add to ext_state_handlers mapping
            "/OP": (self._set_overprint_stroke, lambda v: [bool(v)]),
            "/op": (self._set_overprint_fill, lambda v: [bool(v)]),
            "/OPM": (self._set_overprint_mode, lambda v: [int(v)]),
            "/SA": (self._set_stroke_adjustment, lambda v: [bool(v)]),
        }
        ignore_list = [
            "/Type",
            "/AIS",
            "/SM",
            "/SM2",
            "/UCR2",
            "/BG2",
            "/TR2",
            "/HT2",
        ]
        for key, value in gs_dict.items():
            if key in ignore_list:
                continue
            elif key in ext_state_handlers:
                handler, arg_processor = ext_state_handlers[key]
                try:
                    processed_args = arg_processor(value)
                    handler(PdfOperator(key, processed_args))  # Dummy operator
                except Exception as e:
                    print(f"Error processing {key}: {e}")
            else:
                print(f"Unsupported ExtGState key: {key}")

        return "", True

    # New handler methods
    def _set_overprint_stroke(self, cmd: PdfOperator):
        self.overprint_stroke = cmd.args[0]

    def _set_overprint_fill(self, cmd: PdfOperator):
        self.overprint_fill = cmd.args[0]

    def _set_overprint_mode(self, cmd: PdfOperator):
        print("setting opm to ", cmd.args)
        self.overprint_mode = cmd.args[0]

    # New state variables and handlers

    # New handler method
    def _set_stroke_adjustment(self, cmd: PdfOperator):
        self.stroke_adjustment = cmd.args[0]

    def _handle_overprint(self, is_stroke):
        """currently not implemented/used at all"""
        if is_stroke and not self.overprint_stroke:
            self.ctx.set_operator(cairo.Operator.CLEAR)
        elif not is_stroke and not self.overprint_fill:
            self.ctx.set_operator(cairo.Operator.CLEAR)
        else:
            self.ctx.set_operator(cairo.Operator.OVER)

    @property
    def stroke_alpha(self):
        return self._stroke_alpha if hasattr(self, "_stroke_alpha") else 1.0

    @stroke_alpha.setter
    def stroke_alpha(self, value):
        self._stroke_alpha = max(0.0, min(1.0, float(value)))

    @property
    def fill_alpha(self):
        return self._fill_alpha if hasattr(self, "_fill_alpha") else 1.0

    @fill_alpha.setter
    def fill_alpha(self, value):
        self._fill_alpha = max(0.0, min(1.0, float(value)))

    def _set_stroke_alpha(self, cmd: PdfOperator):
        self.stroke_alpha = cmd.args[0]
        # self.ctx.set_source_rgba(*self.fill_color, self.stroke_alpha)

    def _set_fill_alpha(self, cmd: PdfOperator):
        self.fill_alpha = cmd.args[0]
        # self.ctx.set_source_rgba(*self.fill_color, self.fill_alpha)

    def _set_blend_mode(self, cmd: PdfOperator):
        mode = str(cmd.args[0])
        # (
        # cmd.args[0].name
        # if isinstance(cmd.args[0], PdfName)
        # else str(cmd.args[0])
        # )
        self.blend_mode = mode
        # Map to Cairo operators
        cairo_operators = {
            "/Normal": cairo.Operator.OVER,
            "/Multiply": cairo.Operator.MULTIPLY,
            "/Screen": cairo.Operator.SCREEN,
            # Add more mappings as needed
        }
        self.ctx.set_operator(cairo_operators.get(mode, cairo.Operator.OVER))

    def _set_soft_mask(self, cmd: PdfOperator):
        mask_def = cmd.args[0]
        if mask_def == "/None":
            return
        print(mask_def)
        raise Exception("Not implemented yet")
        # Simplified soft mask implementation
        if mask_def.get("/S") == "/Alpha":
            self.soft_mask = self._create_alpha_mask(mask_def)
        elif mask_def.get("/S") == "/Luminosity":
            self.soft_mask = self._create_luminosity_mask(mask_def)
        else:
            print(f"Unsupported soft mask type: {mask_def.get('/S')}")
        self._apply_soft_mask()

    def _create_alpha_mask(self, mask_def):
        # Create mask surface using existing image handling
        width = mask_def.get("/W", 0)
        height = mask_def.get("/H", 0)
        data = self._decode_image_data(mask_def)

        mask_surface = cairo.ImageSurface.create_for_data(
            data, cairo.FORMAT_A8, width, height
        )
        return mask_surface

    def _create_luminosity_mask(self, mask_def):
        pass

    # Modified rendering methods to use new state variables
    def _apply_graphic_state_before_drawing(self):
        """Call this before any stroke/fill operations"""
        # Apply alpha values

        # Apply line style properties
        self.ctx.set_line_width(self.line_width)
        self.ctx.set_line_cap(self.line_cap)
        self.ctx.set_line_join(self.line_join)
        self.ctx.set_miter_limit(self.miter_limit)

        # Apply dash pattern
        if self.dash_pattern:
            self.ctx.set_dash(self.dash_pattern[0], self.dash_pattern[1])

    def _apply_soft_mask(self):
        """Apply soft mask using Cairo's push/pop group"""
        self.ctx.push_group()
        # Draw mask content
        self.ctx.mask_surface(self.soft_mask, 0, 0)
        mask_pattern = self.ctx.pop_group()
        self.ctx.set_source(mask_pattern)
        # Update state stack handling

    def set_text_rendering_mode(self, cmd: PdfOperator):
        mode = int(cmd.args[0])
        if 0 <= mode <= 7:
            self.text_rendering_mode = mode
        else:
            print(f"Invalid text rendering mode: {mode}")

        return "", True

    # def close_path(self, _: PdfOperator):
    #     """h operator - Close the current subpath"""
    #     # This will be handled by the renderer
    #     return "", True

    # def curve_to(self, cmd: PdfOperator):
    #     """c operator - Cubic Bezier curve"""
    #     x1, y1, x2, y2, x3, y3 = cmd.args
    #     # Store control points and endpoint for renderer
    #     self.position = [x3, y3]
    #     if self.debug:
    #         return [x1, y1, x2, y2, x3, y3], True
    #     return "", True
