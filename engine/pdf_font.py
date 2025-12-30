from math import isnan
from pathlib import Path
import os
import platform
import re
import subprocess
from .pdf_encoding import PdfEncoding as pnc
from typing import Callable, Tuple
import cairo
import json
from pypdf.generic import PdfObject, IndirectObject
from pypdf._codecs import charset_encoding
from pypdf import PdfReader

from .pdf_utils import open_image_in_irfan, kill_with_taskkill
from engine import winansi
from .create_cairo_font import create_cairo_font_face_for_file
import pprint

# from fontTools.ttLib import TTFont
from os.path import sep
from fontTools.agl import UV2AGL, AGL2UV, toUnicode
import freetype

from .winansi import winansi_encoding

UNIC = freetype.FT_ENCODINGS.get("FT_ENCODING_UNICODE")
ADBC = freetype.FT_ENCODINGS.get("FT_ENCODING_ADOBE_CUSTOM")
ADBS = freetype.FT_ENCODINGS.get("FT_ENCODING_ADOBE_STANDARD")
ADBE = freetype.FT_ENCODINGS.get("FT_ENCODING_ADOBE_EXPERT")
ADBL = freetype.FT_ENCODINGS.get("FT_ENCODING_ADOBE_LATIN1")

ENC_LIST = [
    UNIC,
    # ADBC,
    # ADBS,
    # ADBE,
    # ADBL,
]


if os.name == "nt":  # Windows
    ansi = "ansi"
else:
    ansi = "iso_8859_1"


class PdfFont:

    TYPE0 = ["/Type0"]
    TYPE1 = ["/Type1", "/TrueType"]
    TYPE3 = ["/Type3"]
    SUPPORTED_TYPES = ["/Type0", "/Type1", "/TrueType", "/Type3"]
    FONT_DIR = Path(f".{sep}Fonts")
    SYSTEM_FONTS = None

    def __init__(
        self,
        font_name: str,
        font_object: PdfObject | None,
        reader: PdfReader,
        process_glyph_stream: Callable,
        depth: int,
    ) -> None:

        if font_object is None:
            raise ValueError("Font object is None")

        self.font_type: str = str(font_object.get("/Subtype"))
        if self.font_type not in self.SUPPORTED_TYPES:
            raise Exception(
                f"font type {self.font_type} is NOT supported yet !!"
            )

        self.is_type0, self.is_type3 = False, False
        font_dict = self.create_font_dict(font_object, reader)
        self.font_dict = font_dict

        # ************ GENERALL *****************
        # ------------

        self.font_object = font_dict
        self.font_name: str = font_name
        self.depth = depth
        self.base_font: str = str(font_dict.get("/BaseFont", "/UnkownBase"))
        self.first_char: int = int(font_dict.get("/FirstChar", 1))
        self.last_char: int = int(font_dict.get("/LastChar", -1))
        self.process_glyph_stream = process_glyph_stream
        self.should_skip_rendering = False
        self.scaling_factor = None
        self.use_toy_font = False
        self.use_system_font = False
        self.adjust_glyph_width = False

        # ************* DiFF map ***********************
        # ---------

        self.encoding = font_dict.get("/Encoding")
        self.char_set = None
        self.cid_to_name = None
        self.cid_to_char = None
        if not self.is_type0:
            if isinstance(self.encoding, str):
                self.cid_to_char = charset_encoding[self.encoding]
            elif self.encoding:
                if "/BaseEncoding" in self.encoding:
                    self.cid_to_char = charset_encoding[
                        self.encoding["/BaseEncoding"]
                    ]
                if "/Differences" in self.encoding:
                    self.cid_to_name = self.create_diff_map_dict(font_dict)

        # print(self.diff_map)

        # ************* ToUnicode Map *******************
        # ----------
        self.cmap_data = None
        self.valid_ranges = None
        self.cid_to_unicode = {}

        self.cid_to_unicode, self.valid_ranges = (
            self.create_tounicode_map_dict(font_dict)
        )

        # ************* Width Map *******************
        # ----------
        self.width = self.create_width_map(font_dict)

        # ************ FONT DATA VARS *********************
        # ------------ TYPE0 , TYPE1
        self.font_face = None
        self.ft_encoding, self.ft_face = None, None
        self.has_char_map = False
        self.font_path = None
        self.cid_to_gid = {}
        self.char_to_gid = {}
        self.symbol_to_gid = {}
        self.font_desc = font_dict.get("/FontDescriptor")
        # ------------ TYPE3
        self.char_procs = font_dict.get("/CharProcs", {})
        self.font_matrix = cairo.Matrix(
            *font_dict.get("/FontMatrix", [0.001, 0, 0, 0.001, 0, 0])
        )
        self.glyph_cache = {}
        # ------------ Embeded Font File ----------------------------
        # for :  typ1,type0,TrueType,OpenType
        # -------------

        if (
            self.font_type
            in [
                *self.TYPE1,
                *self.TYPE0,
            ]
            # and "/FontDescriptor" in font_dict
        ):  # "/FontDescriptor" in font_dict:
            self.char_set = []
            self.load_type1_type0_font_data(font_dict, reader)
            # print(self.char_set)
        # -------------- Font glyph Stream ---------------------
        # only: for TYPE3 fonts
        # -------------------
        elif self.font_type in self.TYPE3:  # "/CharProcs" in font_dict:
            self.is_type3 = True
            self.load_type3_font_data(font_dict)

        if self.use_system_font:
            self.load_font_from_system_fonts()

        # WARN: DEPRECATED , toy font should be avoided
        if self.use_toy_font:
            self.use_system_font = False
            self.font_family = "Sans"
            self.font_style = None
            self.set_font_style_and_family()
            self.slant = cairo.FONT_SLANT_NORMAL
            self.weight = cairo.FONT_WEIGHT_NORMAL
            self.setup_cairo_toy_font()

    # ******************************************************
    # ************* FONT initialization method *************
    # ------------------------------------------------------

    def create_font_dict(self, font_object: PdfObject, reader):
        font_dict = {
            key: (
                value
                if not isinstance(value, IndirectObject)
                else reader.get_object(value)
            )
            for key, value in font_object.items()
            if not key.startswith("_")
        }
        if "/DescendantFonts" in font_dict:
            self.is_type0 = True
            des_list = font_dict.get("/DescendantFonts")
            for desc_i in des_list:
                if desc_i and isinstance(desc_i, IndirectObject):
                    desc_i = reader.get_object(desc_i)
                desc_i = {
                    key: (
                        value
                        if not isinstance(value, IndirectObject)
                        else reader.get_object(value)
                    )
                    for key, value in desc_i.items()
                    if not key.startswith("_")
                }
                font_dict.update(desc_i)
        return font_dict

    # **************************************************************
    # ****************** Type1,Type0,TrueType **********************
    # --------------------------------------------------------------

    def load_type1_type0_font_data(self, font_dict, reader):
        # print(font_dict)
        font_desc = self.font_desc
        if "/CharSet" in font_desc:
            char_set = font_desc["/CharSet"]
            self.char_set = [f for f in char_set.split("/") if f]
        not_found = True
        for font_file_key in ["/FontFile", "/FontFile2", "/FontFile3"]:
            if font_file_key in font_desc:
                not_found = False
                # ************* initilize dir *****************
                # -----------

                font_file = self.font_desc[font_file_key]
                font_path = self.save_embeded_font_to_file(font_file, reader)
                ft_face = freetype.Face(font_path)
                self.font_path = font_path
                self.ft_face = ft_face
                if not self.is_type0:
                    self.select_char_map_for_font()
                if self.has_char_map:
                    (
                        self.cid_to_gid,
                        self.char_to_gid,
                        self.symbol_to_gid,
                    ) = self.create_glyph_map_dicts(font_path)

        if not_found:

            self.use_system_font = True
            self.adjust_glyph_width = True

    # *************************************************
    # ************ Toy FONT ***************************
    # WARN: DEPRICATED, in favor of system fonts

    def set_font_style_and_family(
        self,
    ):
        parts = self.base_font.lstrip("/").split("+", 1)
        if len(parts) == 2:
            prefix, font_name = parts
        else:
            font_name = parts[0]
        font_parts = font_name.split(",")
        if len(font_parts) > 1:
            self.family = font_parts[0]
        self.style = font_parts[1:] if len(font_parts) > 1 else font_parts
        self.style = list(map(str.lower, self.style))

    def setup_cairo_toy_font(self):
        for style_part in self.style:
            style = style_part.lower()
            if "italic" in style:
                self.slant = cairo.FONT_SLANT_ITALIC
            elif "oblique" in style:
                self.slant = cairo.FONT_SLANT_OBLIQUE
            if "bold" in style:
                self.weight = cairo.FONT_WEIGHT_BOLD

    # ******************** UTILS ***********************
    # *************** Helper Methods *******************
    # --------------------------------------------------

    def save_embeded_font_to_file(self, font_file, reader):
        temp_dir = "temp"
        font_path = (
            temp_dir + sep + self.font_name + "_" + str(self.depth) + ".ttf"
        )
        if not os.path.exists(temp_dir):
            os.mkdir(temp_dir)
        elif os.path.exists(font_path):
            os.remove(font_path)

        if isinstance(font_file, IndirectObject):
            font_file = reader.get_object(font_file)
        font_data = font_file.get_data()
        file = open(font_path, "bw")
        file.write(font_data)
        file.flush()
        file.close()
        return font_path

    def select_char_map_for_font(self):
        if not self.is_type0 and len(self.ft_face.charmaps) > 0:
            try:
                self.ft_face.select_charmap(UNIC)
                self.ft_encoding = UNIC
            except Exception as e:
                # print(e)
                try:
                    cmap = self.ft_face.charmaps[0]
                    # print(
                    #     f"could not select Unicode cmap for font {self.font_name} \nfalling back to {cmap.encoding_name}",
                    # )
                    self.ft_face.set_charmap(cmap)
                    self.ft_encoding = cmap.encoding
                except Exception as e:
                    raise Exception(e)

        else:
            self.ft_encoding = None

    def is_char_code_valid(self, cid):
        if self.valid_ranges is None:
            if self.default_width or self.missing_width:
                return True  # just for safty

        for start, end in self.valid_ranges:
            if start <= cid <= end:
                return True
        return False

    def get_cairo_font_face(self):
        """Get a Cairo font face from the embedded font if available"""
        self.font_face = create_cairo_font_face_for_file(
            self.font_path, encoding=self.ft_encoding
        )
        return self.font_face

    #
    # **************************************************************
    # **************** Create some Usefull Dict ********************
    # UnicodeMapping , Cid_to_Gid_Mapping , CharName_to_Gid_Mapping,
    # DifferenceMapping ( from /Encoding['/Difference'] )
    # WidthMapping ( from /Font['/Width' or '/W']
    # --------------------------------------------------------------

    def create_width_map(self, font_dict: dict):
        self.widths = None
        if self.font_type in [*self.TYPE1, *self.TYPE3]:  # not self.is_type0:
            self.default_width = font_dict.get("/FontDescriptor", {}).get(
                "/MissingWidth", None
            )
            widths = font_dict.get("/Widths")
            # if isinstance(widths, IndirectObject):
            #     widths = reader.get_object(widths)
            if isinstance(widths, list):
                if len(widths) > 1:
                    self.widths: list[int] = [int(x) for x in widths]
                else:
                    self.widths = widths[0]
            elif isinstance(widths, (int, float, str)):
                self.widths = widths
            else:  # if self.widths is None:
                raise Exception("Width is None or has different format !!")
        elif self.font_type in self.TYPE0:
            self.default_width = font_dict.get("/DW", 1000)
            widths = font_dict.get("/W", [])
            # if isinstance(widths, IndirectObject):
            #     widths = reader.get_object(widths)
            self.widths = {}
            i = 0
            while i < len(widths) - 1:
                el = int(widths[i])
                n_el = widths[i + 1]
                if isinstance(n_el, list):
                    for j in range(len(n_el)):
                        self.widths[el + j] = n_el[j]
                    i = i + 2
                elif i + 2 < len(widths):
                    n_el = int(n_el)
                    n2_el = widths[i + 2]
                    if isinstance(n2_el, list):
                        if len(n2_el) == 1:
                            n2_el = n2_el[0]
                        else:
                            raise Exception
                    for j in range(el, n_el + 1):
                        self.widths[j] = n2_el
                    i = i + 3
        else:

            raise Exception(
                f"font type {self.font_type} is NOT supported yet !!"
            )

        return self.widths

    def create_tounicode_map_dict(self, font_dict):

        if "/ToUnicode" not in font_dict:
            return {}, None
        tounicode = font_dict["/ToUnicode"]
        data = tounicode.get_data().decode("utf-8")
        # print(data, "\n\n")
        self.cmap_data = data
        tokens = self.tokenize_cmap(data)

        cid_map = {}
        codespace_ranges = []
        i = 0
        while i < len(tokens):
            token = tokens[i]
            if token == "begincodespacerange":
                count = int(tokens[i - 1]) if i > 0 else 0
                i += 1
                for _ in range(count):
                    # Parse <start> <end> pairs
                    start = int(tokens[i + 1], 16)
                    end = int(tokens[i + 4], 16)
                    codespace_ranges.append((start, end))
                    i += 6  # Skip past '<', start, '>', '<', end, '>'
                # Skip past "endcodespacerange"
                while i < len(tokens) and tokens[i] != "endcodespacerange":
                    i += 1
                i += 1
            elif token == "beginbfchar":
                count = int(tokens[i - 1]) if i > 0 else 0
                i += 1
                for _ in range(count):
                    cid = int(tokens[i + 1], 16)
                    uni_token = tokens[i + 4]
                    unicode_char = ""
                    for j in range(0, len(uni_token), 4):
                        unicode_char += chr(int(uni_token[j : j + 4], 16))
                    cid_map[cid] = unicode_char
                    i += 6  # Skip '<', cid, '>', '<', unicode, '>'
            elif token == "beginbfrange":
                count = int(tokens[i - 1]) if i > 0 else 0
                i += 1
                for _ in range(count):
                    cid_start = int(tokens[i + 1], 16)
                    cid_end = int(tokens[i + 4], 16)

                    # Check the format of the unicode mapping
                    if i + 6 < len(tokens) and tokens[i + 6] == "[":
                        # Format 2: range to array [ <unicode1> <unicode2> ... ]
                        i += 7  # Skip past '<', start, '>', '<', end, '>', '['
                        for offset in range(cid_end - cid_start + 1):
                            if i < len(tokens) and tokens[i] == "<":
                                unicode_hex = tokens[i + 1]
                                cid = cid_start + offset
                                cid_map[cid] = self._parse_unicode_hex(
                                    unicode_hex
                                )
                                i += 3  # Skip '<', hex, '>'
                            else:
                                break
                        # Skip past the closing ']'
                        while i < len(tokens) and tokens[i] != "]":
                            i += 1
                        i += 1  # Skip the ']'

                    else:
                        # Format 1: range to range <cidStart> <cidEnd> <unicodeStart>
                        # Make sure we have enough tokens and the next token is a hex number
                        if (
                            i + 6 < len(tokens)
                            and tokens[i + 6] == "<"
                            and i + 7 < len(tokens)
                        ):
                            uni_start = int(tokens[i + 7], 16)
                            for offset in range(cid_end - cid_start + 1):
                                cid = cid_start + offset
                                cid_map[cid] = chr(uni_start + offset)
                            i += 9  # Skip '<', start, '>', '<', end, '>', '<', uni_start, '>'
                        else:
                            # Unexpected format, skip this entry
                            i += 6  # Skip past the CID range only
                            # Try to find the end of this bfrange entry
                            while i < len(tokens) and tokens[i] not in [
                                "<",
                                ">",
                                "]",
                                "beginbfrange",
                                "endbfrange",
                            ]:
                                i += 1
            i += 1

        return cid_map, codespace_ranges or None

    def tokenize_cmap(self, data):
        tokens = []
        current = []
        in_comment = False
        for char in data:
            if char == "%":
                in_comment = True
            if in_comment:
                if char == "\n":
                    in_comment = False
                continue
            if char.isspace():
                if current:
                    tokens.append("".join(current))
                    current = []
            elif char in "<>":
                if current:
                    tokens.append("".join(current))
                    current = []
                tokens.append(char)
            else:
                current.append(char)
        if current:
            tokens.append("".join(current))
        return tokens

    def _parse_unicode_hex(self, hex_str):
        """Parse a hexadecimal string into a Unicode character"""
        if len(hex_str) % 4 == 0:
            # Handle surrogate pairs and multi-byte Unicode
            chars = []
            for j in range(0, len(hex_str), 4):
                chars.append(chr(int(hex_str[j : j + 4], 16)))
            return "".join(chars)
        else:
            # Single character
            return chr(int(hex_str, 16))

    def create_glyph_map_dicts(self, font_path):
        char_to_gid = {}
        symbol_to_gid = {}
        code_to_gid = {}

        for (
            cp,
            raw_gid,
        ) in self.ft_face.get_chars():  # iterate the cmap

            if raw_gid == 0:
                continue

            gname = None
            code_to_gid[cp] = raw_gid
            if self.cid_to_name:
                gname = self.cid_to_name.get(cp, "").replace("/", "")

            if not gname and self.ft_face._has_glyph_names():
                try:
                    gname = self.ft_face.get_glyph_name(raw_gid)
                    gname = pnc.bytes_to_string(gname)
                except Exception:
                    gname = ""
            if not gname:
                gname = self.get_symbol_name_from_char_code(cp)

            if gname and gname != ".notdef":
                symbol_to_gid[gname] = raw_gid

        return code_to_gid, char_to_gid, symbol_to_gid

    def create_diff_map_dict(self, font_dict: dict, debug=False):
        # if (
        #     "/Differences" not in self.encoding
        # ):  # isinstance(self.encoding, IndirectObject):
        #     return {}
        font_diff: PdfObject = self.encoding.get("/Differences")
        current_index = 1
        diff_map = {}
        for symbole in font_diff:
            sym = symbole
            if isinstance(sym, int):
                current_index = sym  # if int(sym) > 0 else 1
            else:
                diff_map[current_index] = sym
                current_index += 1
        if debug:
            print(diff_map)
        return diff_map

    #
    #
    # *****************************************************
    # ++++++++++++++++ get Glyph Info *********************
    # _______________ used_by_the_renderer ________________
    #
    def get_char_code_from_match(self, char: str) -> Tuple[int, int]:
        if not self.is_type0:
            char_code = pnc.char_to_int(char)
        else:
            if len(char) != 2:
                raise Exception("missing prev symbol in composite font")
            high_byte = pnc.char_to_int(char[0])
            low_byte = pnc.char_to_int(char[1])
            char_code = (high_byte << 8) | low_byte
        return char_code

    def get_char_width_from_code(self, char_code: int):
        if isinstance(self.widths, (int, float)):
            return self.widths
        if not self.is_type0:  # type1,type3 has width as list
            if char_code >= self.first_char and char_code <= self.last_char:
                width = self.widths[char_code - self.first_char]
                return width if (width is not None) else self.default_width

            else:
                return None
                raise Exception(
                    f"char code {char_code}, for char {chr(char_code)} , does not have width mapping"
                )

        else:
            width = self.widths.get(char_code)
            if width is None and self.is_char_code_valid(char_code):
                width = self.default_width
            return width

    def get_glyph_id_from_char_code(self, char_code: int, depth=0):
        latin_code = char_code
        glyph_id, name = None, None
        if self.is_type0 or self.is_type3 or self.use_toy_font:
            glyph_id = char_code
            name = f"\\{char_code}"  # dummy name
        else:
            if self.cid_to_name is not None:
                name = (
                    self.cid_to_name.get(char_code, "").replace("/", "")
                    or None
                )
            if name:
                glyph_id = self.ft_face.get_name_index(name.encode("latin1"))
                if glyph_id:
                    return glyph_id, name
            if not glyph_id and self.cid_to_char is not None:
                char = self.cid_to_char[char_code]
                if self.ft_encoding == UNIC:
                    char_code = ord(char)
                    # print(char_code, "is unicode", char_code)
                else:
                    char_code = char_code
                glyph_id = self.ft_face.get_char_index(char_code)
                name = UV2AGL.get(char_code)
            if glyph_id:
                return glyph_id, name

            if name:
                glyph_id = self.ft_face.get_name_index(name.encode("latin1"))
                if glyph_id:
                    return glyph_id, name

            if (
                len(self.char_set) + self.first_char
                > latin_code
                >= self.first_char
            ):
                name = self.char_set[latin_code - self.first_char]

            if name:
                glyph_id = self.ft_face.get_name_index(name.encode("latin1"))
                if glyph_id:
                    return glyph_id, name

            if not glyph_id:
                glyph_id = self.handle_corropted_font(latin_code, name)

            if not glyph_id:
                if char_code in [127, 129]:
                    return self.get_glyph_id_from_char_code(183)
                if glyph_id == 0 and char_code in [32]:
                    return glyph_id, name
                print(
                    "ERROR: glph_id not found ... for char=",
                    char,
                    chr(char_code),
                    "char_code",
                    char_code,
                    "latin1_code",
                    latin_code,
                    "name",
                    name,
                    "len charMaps",
                    len(self.ft_face.charmaps),
                    "GLYPH_ID",
                    glyph_id,
                    "chars",
                    [i for i in self.ft_face.get_chars()],
                )
                raise Exception()
        return glyph_id, name

    def handle_corropted_font(self, char_code, name):
        curr_cmap = self.ft_face.charmap
        for cmap in self.ft_face.charmaps:
            if cmap == curr_cmap:
                continue
            self.ft_face.set_charmap(cmap)
            glyph_id = self.ft_face.get_char_index(char_code)
            if glyph_id:
                return glyph_id

    def get_symbol_name_from_char_code(self, char_code):
        symbol = UV2AGL.get(char_code, None)
        if not symbol and char_code < len(winansi_encoding):
            symbol = winansi_encoding[char_code]
        if symbol:
            return symbol.lstrip("/")
        else:
            return "<unavailable>"

    #
    #
    # ***********************************************
    # ********* Handling Type3 fonts ****************
    # +++++++ Incomplete "buggy" implementation *****
    # -----------------------------------------------

    def load_type3_font_data(self, font_dict):
        proc = self.char_procs
        self.base_font = "/Type3"
        if len(proc.keys()) > 1 or "/space" not in proc:
            """for testing purposes"""
            print(proc)
            # raise Exception("None-Empty Type3 font")

    def render_glyph_for_type3_font(self, char_name, fill_color):
        # char_name = self.get_symbol_name_from_char_code(char_code)
        stream_bytes = self.char_procs[char_name].get_data()
        stream = pnc.bytes_to_string(stream_bytes, unicode_excape=True)
        bbox = self.font_dict.get("/FontBBox", [0, 0, 1000, 1000])
        print("bbox", bbox)
        print("font_matrix", self.font_matrix)
        # for key in self.char_procs.keys():
        #     print("key", key)
        # print(len(self.char_procs.keys()))
        rect = cairo.Rectangle(*bbox)
        # recorder = cairo.RecordingSurface(cairo.CONTENT_COLOR_ALPHA, None)
        sur_scale = 1000
        recorder = cairo.ImageSurface(
            cairo.FORMAT_ARGB32, bbox[2] * sur_scale, abs(bbox[3]) * sur_scale
        )
        ctx = cairo.Context(recorder)
        ctx.set_source_rgb(*[1, 1, 1])
        ctx.paint()
        ctx.set_source_rgb(*[0, 0, 0])
        # ctx.move_to(0, 0)
        # ctx.scale(100, 100)
        self.font_matrix = cairo.Matrix()
        self.font_matrix.translate(0, 200)
        self.font_matrix.scale(300, 200)
        self.process_glyph_stream(stream, ctx, char_name, self.font_matrix)
        imp = f"output{sep}recorded_surface.png"
        recorder.write_to_png(imp)
        open_image_in_irfan(imp)
        input("waiting !!")
        return recorder

    def get_glyph_for_type3(self, char_code, fill_color):
        raise Exception("curently not fully implemented !!")

        if char_code in self.glyph_cache:
            return self.glyph_cache[char_code]
        # char_name = self.diff_map.get(char_code, ".notdef")
        print("char_code is ", char_code)
        char_name = self.cid_to_name.get(char_code)
        if not char_name:
            raise Exception("char_name not found in diff_map")
        # if char_name[1] != "/":
        #     char_name = "/" + char_name
        if not char_name or char_name not in self.char_procs:
            print(f"error: char_code: {char_code}, char_name: {char_name}")
            raise Exception("char name for type3 font not found")
            return None

        path = self.render_glyph_for_type3_font(char_name, fill_color)
        self.glyph_cache[char_code] = path  # (path, width)
        return self.glyph_cache[char_code]

    # ************************************************
    # ************* Attention  ***********************
    # xxxxxxxxxxxx DONT DELETE CODE BELOW xxxxxxxxxxxx

    def load_font_from_system_fonts(self):
        """
        the following code is basis for the futer implementation where we:
        1- detect all missing font files from all exam
        2- find a free similar font that match each missing font file
        3- collect all the found similar font in the Fonts dir ..
        4- create a table that map each "missing" pdf font to a free one
        5- use the free font .

        Note:
            currently we will uses cairo toy font instead !!

        """
        if self.base_font not in self.FONT_SUBSTITUTION_MAP:
            raise Exception(
                f"No alternative found for font {self.base_font},{self.font_name}\n"
                + f"font:{self.font_dict}"
            )

        self.base_font = self.FONT_SUBSTITUTION_MAP[self.base_font]
        self.font_path = f"Fonts{sep}{self.base_font}"
        if not os.path.exists(self.font_path):
            raise Exception("System Font not found on Path")

        ft_face = freetype.Face(self.font_path)
        self.ft_face = ft_face
        if not self.is_type0:
            self.select_char_map_for_font()
        if self.has_char_map:
            (
                self.cid_to_gid,
                self.char_to_gid,
                self.symbol_to_gid,
            ) = self.create_glyph_map_dicts(self.font_path)
        pass

    FONT_SUBSTITUTION_MAP = {
        # Times Family -> Liberation Serif
        "/TimesNewRomanPSMT": "LiberationSerif-Regular.ttf",
        "/Times-Roman": "LiberationSerif-Regular.ttf",
        "/TimesNewRomanPS-ItalicMT": "LiberationSerif-Italic.ttf",
        "/Times-Italic": "LiberationSerif-Italic.ttf",
        "/TimesNewRomanPS-BoldMT": "LiberationSerif-Bold.ttf",
        "/Times-Bold": "LiberationSerif-Bold.ttf",
        "/TimesNewRomanPS-BoldItalicMT": "LiberationSerif-BoldItalic.ttf",
        "/Times-BoldItalic": "LiberationSerif-BoldItalic.ttf",
        # Helvetica Family -> Liberation Sans
        "/Helvetica": "LiberationSans-Regular.ttf",
        "/Helvetica-Bold": "LiberationSans-Bold.ttf",
        "/Helvetica-Oblique": "LiberationSans-Italic.ttf",  # Using Italic for Oblique
        # Arial Family -> Liberation Sans
        "/ArialMT": "LiberationSans-Regular.ttf",
        "/Arial": "LiberationSans-Regular.ttf",  # Explicitly adding /Arial
        "/Arial-ItalicMT": "LiberationSans-Italic.ttf",
        "/Arial-BoldMT": "LiberationSans-Bold.ttf",
        # Courier Family -> Liberation Mono
        "/CourierNewPSMT": "LiberationMono-Regular.ttf",
        # Verdana Family -> DejaVu Sans
        "/Verdana": "DejaVuSans.ttf",  # Or DejaVuSans-Book.ttf; the base TTF should work.
        "/Verdana-Italic": "DejaVuSans-Oblique.ttf",  # Or the Italic style within DejaVuSans.ttf
        # Symbol Family -> OpenSymbol
        "/Symbol": "OpenSymbol.ttf",
    }

    # #################################################
    # +++++++++++++++ Debug Font ++++++++++++++++++++++
    # -------------------------------------------------

    def debug_font(self):
        if self.font_name != "/C2_0":
            return
        print(f"\n\n****************** {self.font_name} ******************")
        print(f"               ****************** ")
        print("to_unicode :", self.cid_to_unicode, "\n")

        font_size = 20
        width = 500
        height = 700  # y + 50
        for cmap in self.ft_face.charmaps:
            self.ft_face.set_charmap(cmap)
            print(f"\n*********** {cmap.encoding_name} *****************")
            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
            ctx = cairo.Context(surface)
            ctx.set_source_rgb(1, 1, 1)
            ctx.paint()  # white bg
            ctx.set_source_rgb(0, 0, 0)  # black text
            ctx.set_font_size(font_size / 2)

            pen_x, glyphs = 20, []
            cid_glyphs = []
            y = 30
            counter = 0

            (
                self.cid_to_gid,
                self.char_to_gid,
                self.symbol_to_gid,
            ) = self.create_glyph_map_dicts(self.font_path)

            curr_dict = (
                self.cid_to_gid if not self.is_type0 else self.cid_to_unicode
            )

            items = list(sorted(curr_dict.items(), key=lambda x: x[0]))
            for cid, gid_or_unic in items:
                # if not
                #     continue
                prefix = ""
                if counter % 12 == 0:
                    y = y + 50
                    pen_x = 20
                    prefix = "\n"
                if y > 1000:
                    break
                if self.is_type0:
                    if gid_or_unic == " ":
                        gid_or_unic = "Space"
                    print(f"{prefix}{gid_or_unic:7}", end=" ")
                    gid = cid
                    print(cid)
                    code = pnc.byte_to_octal(int.to_bytes(cid))
                    ctx.move_to(pen_x, y - 19)

                else:
                    o = chr(cid)
                    if o == " ":
                        o = "Space"
                    print(f"{prefix}{o:>7}", end=" ")
                    gid = gid_or_unic  # self.cid_to_gid[cid]
                    code = str(cid)
                    ctx.move_to(pen_x + 10, y - 14)

                glyphs.append(cairo.Glyph(gid, pen_x, y))
                ctx.show_text(code)

                pen_x += 50
                counter += 1
            if counter == 0:
                pprint.pprint(self.cmap_data)
                pprint.pprint(self.cid_to_unicode)
            face_cairo = self.get_cairo_font_face()

            ctx.move_to(0, 0)
            ctx.set_font_face(face_cairo)
            ctx.set_font_size(font_size)
            ctx.show_glyphs(glyphs)

            ctx.show_glyphs(cid_glyphs)

            out_png = f"output{sep}output.png"
            surface.write_to_png(out_png)
            open_image_in_irfan(out_png)
            a = input("\n\npress any key to continue")
            kill_with_taskkill()
