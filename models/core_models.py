import json
import os
from collections import defaultdict
from os.path import sep

import cairo
import numpy as np  # speeds things up; pure-Python fallback shown later

from engine.pdf_utils import _surface_as_uint32, all_subjects

# ********************************************************************
# ********************* Detecotr Data-classes


class Box:
    def __init__(self, x, y, w, h):
        self.x = x
        self.y = y
        self.w = w
        self.h = h
        self.box = (x, y, x + w, y + h)
        pass

    def __str__(
        self,
    ):
        c_name = self.__class__.__name__
        label = ""
        if hasattr(self, "label"):
            label = f"label= {self.label}, "
        return f"{self.__class__.__name__}({label}x={self.x}, y={self.y}, w={self.w}, h={self.h})"

    def get_box(self):
        return self.box

    def __set_box__(
        self,
    ):
        self.box = (self.x, self.y, self.x + self.w, self.y + self.h)

    def row_align_with(self, box_other, line_height):
        box_other: Box = box_other
        upper, lower = (
            (box_other, self)
            if box_other.box[-1] < self.box[-1]
            else (self, box_other)
        )

        if (
            abs(lower.box[-1] - upper.box[-1]) < line_height * 0.1
            or abs(lower.box[1] - upper.box[1]) < line_height * 0.1
        ):
            return True
        return lower.box[1] - upper.box[-1] < 0.1 * line_height

        # return (
        #     abs(self.mean[1] - seg_other.mean[1]) < self.threshold_y
        #     or abs(self.box[-1] - seg_other.box[-1]) < self.threshold_y
        #     or abs(self.box[1] - seg_other.box[1]) < self.threshold_y
        # )


class Part(Box):
    def __init__(self, label, x, y, x1, y1) -> None:
        super().__init__(x, y, x1 - x, y1 - y)
        self.label = label
        self.box = [x, y, x1, y1]


class SubPart(Box):
    def __init__(self, label, x, y, x1, y1) -> None:
        super().__init__(x, y, x1 - x, y1 - y)
        self.label = label
        self.box = [x, y, x1, y1]


class Symbol(Box):
    LINE_HEIGHT_FACTOR = 1.3

    def __init__(self, ch, x, y, w, h) -> None:
        super().__init__(x, y, w, h)
        self.ch = ch
        self.threshold_y = 0.45 * h
        self.threshold_x = 0.45 * w
        self.box: tuple | None = None
        self.__set_box__()
        pass

    def __str__(
        self,
    ):
        return f"Smybole({self.ch}, x={self.x}, y={self.y}, w={self.w}, h={self.h})"

    def __set_box__(
        self,
    ):
        self.box = self.x, self.y - self.h, self.x + self.w, self.y

    def is_connected_with(self, s2):
        s2: Symbol = s2
        left_sym = self if self.x < s2.x else s2
        right_sym = s2 if self == left_sym else self
        # diff1 = abs(s2.x + s2.w - self.x)
        # diff2 = abs(s2.x - self.x + self.w)
        inner_diff = right_sym.x - (
            left_sym.x + left_sym.w
        )  # min(diff1, diff2)
        return inner_diff < self.threshold_x or inner_diff < s2.threshold_x

    # def is_horizontal_aligned_with(self, s2):
    #     s2: Symbol = s2


class BoxSegments(Box):

    def __init__(self, segments: list[Box]) -> None:
        if not segments:
            raise Exception("empty segments")
        self.data: list[Box] = segments.copy()
        self.__set_box__()
        # self.threshold_y = 0.3 * (self.box[-1] - self.box[1])
        # self.threshold_x = 0.3 * (self.box[-2] - self.box[0])

    def __getitem__(self, index) -> Symbol:
        return self.data[index]

    def __len__(self):
        return len(self.data)

    def size(self):
        return self.data.__len__()

    def __str__(self) -> str:
        rep = f"{self.__class__.__name__}(lenght={len(self.data)}) =>\n"
        for it in self.data:
            rep += "   " + str(it) + "\n"
        return rep

    def __set_box__(self):
        x0, y0, x1, y1 = self.data[0].get_box()
        for d in self.data[1:]:
            nx0, ny0, nx1, ny1 = d.get_box()
            x0 = min(x0, nx0)
            y0 = min(y0, ny0)
            x1 = max(x1, nx1)
            y1 = max(y1, ny1)
        self.box = (x0, y0, x1, y1)
        self.x = x0
        self.y = y0
        self.w = x1 - x0
        self.h = y1 - y0


class SymSequence(BoxSegments):

    def __init__(self, symboles: list[Symbol]) -> None:
        if not symboles:
            raise Exception("empty Sequence")
        super().__init__(
            sorted(
                symboles,
                key=self.sort_func,
            )
        )
        self.mean = (0, 0)
        self.data: list[Symbol] = self.data
        self.__set_mean__(self.box)
        self.threshold_y = 0.3 * (self.box[-1] - self.box[1])
        self.threshold_x = 0.3 * (self.box[-2] - self.box[0])
        pass

    def sort_func(self, elem: Box):
        return elem.x

    def extend(self, new_syms: list[Symbol]):
        n_data = self.data
        n_data.extend(new_syms)
        # n_data_sorted = sorted(n_data, key=self.sort_func)
        self = SymSequence(n_data)
        return self

    def iterate_split(self, char: str = " "):
        sub = []
        for sym in self.data:
            if sym.ch in char:
                if len(sub) > 0:
                    yield SymSequence(sub)
                sub = []
            else:
                sub.append(sym)

        if len(sub) > 0:
            yield SymSequence(sub)

    def iterate_split_space(
        self,
    ):
        seps: str = " \t"
        sub = []
        for i, sym in enumerate(self.data):
            n_sym = None
            if i + 1 < len(self.data):
                n_sym = self.data[i + 1]
            if (
                sym.ch in seps
            ):  # or (n_sym and not sym.is_connected_with(n_sym)):
                if len(sub) > 0:
                    yield SymSequence(sub)
                sub = []
            elif n_sym and not sym.is_connected_with(n_sym):
                sub.append(sym)
                yield SymSequence(sub)
                sub = []
            else:
                sub.append(sym)

        if len(sub) > 0:
            yield SymSequence(sub)

    def get_text(self, verbose=True, data=None) -> str:
        rep = ""
        if not data:
            data = self.data
        prev = None
        for sym in data:
            if prev and not sym.is_connected_with(prev):
                rep += " "
            rep += sym.ch
            prev = sym
        if verbose:
            return f"Sequence(lenght={len(self.data)}, content={rep}, box={self.box})"
        else:
            return rep

    # def __set_box__(self):
    #     if len(self.box) == 0:
    #         return
    #     x0, y0, x1, y1 = self.data[0].get_box()
    #     for d in self.data[1:]:
    #         nx0, ny0, nx1, ny1 = d.get_box()
    #         x0 = min(x0, nx0)
    #         y0 = min(y0, ny0)
    #         x1 = max(x1, nx1)
    #         y1 = max(y1, ny1)
    #     self.box = (x0, y0, x1, y1)
    #     self.x = x0
    #     self.y = y0
    #     self.w = x1 - x0
    #     self.h = y1 - y0

    def __set_mean__(self, box):
        x0, y0, x1, y1 = box
        self.mean = []
        self.mean.append((x0 + x1) / 2)
        self.mean.append((y0 + y1) / 2)

    def column_align_with(self, seq_other):
        seq_other: SymSequence = seq_other
        return (
            abs(self.mean[0] - seq_other.mean[0]) < self.threshold_x
            or abs(self.box[0] - seq_other.box[0]) < self.threshold_x
        )


class Paragraph:
    def __init__(self, lines: list[SymSequence]):
        if not lines:
            raise Exception("empty Paragraph")
        # super().__init__(symboles)
        self.lines: list[SymSequence] = lines

    def __getitem__(self, index) -> Symbol:
        return self.lines[index]

    def __len__(self):
        return len(self.lines)

    def size(self):
        return self.lines.__len__()

    def make_paragraph_with(self, s2, line_height):
        if not s2:
            return False
        threshold = 0.20 * line_height

        # def sort_func(elem: Box):
        #     return elem.box[0]  # + (elem.box[-1] - self.box[1]) / 3

        for i, seg in enumerate(self.lines):
            new_seg: SymSequence = s2
            diff = new_seg.box[-1] - seg.box[-1]
            # if diff < -threshold and i == 0:
            #     self.add_line(new_seg, last=False)
            #     return True
            if diff >= threshold:  # and i == len(self.lines) - 1:
                # new_seg.data = sorted(new_seg.data, key=new_seg.sort_func)
                self.add_line(new_seg)
                return True
            elif abs(diff) <= threshold * 4:
                self.lines[i] = seg.extend(new_seg)
                return True
        return False
        # return diff <= line_height

    def add_line(self, new_syms: list[Symbol], last=True):
        # self.data.extend(new_syms)
        lines = self.lines
        lines.append(new_syms) if last else lines.insert(0, new_syms)
        self = Paragraph(lines)
        # self.lines = lines

    def __str__(self):
        rep = "Paragraph =>\n"
        for i in range(len(self.lines)):
            rep += f"\t\t{i+1}: {self.lines[i].get_text(verbose=False)}\n"
        rep += "\n"
        return rep


class SurfaceGapsSegments(BoxSegments):

    def __init__(
        self, surface: cairo.ImageSurface, gap_factor: float = 0.5, scale=None
    ) -> None:
        """factor: a float number which will multiply (0.01 * page_height ) and be used
        as min empty gap (gap = number of sequencially empty/white rows of pixel) that should be skipped ...
        factor == 0     => then every line will be in its own seqment
        factor == 100   => the whole page will be treated as one segment
        """
        self.surface = surface
        s_height = surface.get_height()
        self.net_height = s_height
        self.empty_segments: list[Box] = []
        self.non_empty_segments: list[Box] = []
        self.gap_factor = gap_factor
        self.d0 = s_height * 0.01
        self.MIN_GAP_HEIGHT = self.gap_factor * self.d0
        self.scale = scale

        self.find_empty_gaps(0)
        self.non_empty_segments, self.net_height = self.get_non_empty_gaps(
            0, s_height
        )

        if not self.non_empty_segments:
            raise Exception("THe Page is completly Empty !!")

        self.data = self.non_empty_segments
        self.__set_box__()

        # segments = get_segments( 0, s_height, d0, factor=gap_factor)
        # out_height += sum(seg_h + 2 * d2 for _, seg_h, d2 in segments)

    def find_empty_gaps(self, min_y=0):
        surface = self.surface
        mask = self.build_blank_mask(surface)
        gaps: list[Box] = []
        h_px = len(mask)
        MIN_COUNT = round(0.1 * self.d0)
        start = None
        not_blanck_count = 0
        blanck_count = 0
        is_blank_mode = True
        start = min_y
        for y, blank in enumerate(mask):
            if blank:
                blanck_count += 1
                not_blanck_count = 0
            else:
                not_blanck_count += 1
                blanck_count = 0

            if blanck_count > MIN_COUNT:
                is_blank_mode = True
            elif not_blanck_count > MIN_COUNT:
                is_blank_mode = False

            if is_blank_mode and start is None:
                start = y
            elif not is_blank_mode and start is not None:
                gaps.append(Box(0, start, surface.get_width(), y - start))
                start = None
        if start is not None:  # ran off bottom still in blank
            gaps.append(Box(0, start, surface.get_width(), h_px - start))

        fgaps = [
            box
            for box in gaps
            if box.h > self.MIN_GAP_HEIGHT and box.y >= min_y
        ]
        self.empty_segments = fgaps

    def get_non_empty_gaps(self, min_y, max_y):
        segments = []
        cursor = min_y
        net_height = 0
        for box in self.empty_segments:
            gy, gh = box.y, box.h
            if gy > cursor:
                h_curr = gy - cursor
                segments.append(
                    Box(0, cursor, self.surface.get_width(), h_curr)
                )
                net_height += h_curr
            cursor = gy + gh

        if cursor < max_y:  # rows after the last gap
            h_curr = max_y - cursor
            segments.append(Box(0, cursor, self.surface.get_width(), h_curr))
            net_height += h_curr

        if net_height < self.surface.get_height() - 2 * self.d0:
            net_height += 2 * self.d0

        return segments, net_height

    def filter_question_segments(self, min_y, max_y, page_range, curr_page):
        q_segs = []
        q_y_min, q_y_max = 0, self.surface.get_height()
        if page_range[0] == curr_page:
            q_y_min = min_y  # - 40 * self.d0  # q.h
        if page_range[-1] == curr_page:
            q_y_max = max_y  # - 1.5 * self.d0  # q.h
            print("COMPARE", max_y, q_y_max)
        # print(y0, "   ", y1, "for debugging")
        # print("seq length = ", len(segments))
        line_height = Symbol.LINE_HEIGHT_FACTOR * self.d0  # * self.scale
        for box in self.non_empty_segments:
            box_min, box_max, d0 = box.y, box.h + box.y, self.d0
            # if not self.default_d0 and d0:
            #     self.default_d0 = d0
            part_inside = min(box_max, q_y_max) - max(box_min, q_y_min)
            # assert part_inside > 0
            part_before = -1000000
            if box_min < q_y_min:
                part_before = min(box_max, q_y_max) - box_min

            part_after = -1000000
            if box_max > q_y_max:
                part_after = box_max - max(box_min, q_y_min)

            if part_after > part_inside:
                continue
            if part_before > 0 and -1 * part_inside > 0.2 * line_height:
                continue

            q_segs.append(box)

            # if (
            #     q_y_min <= box_min < (q_y_max)
            #     and box_max <= q_y_max  # + 2.4 * self.MIN_GAP_HEIGHT
            # ) or (
            #     (q_y_min + self.MIN_GAP_HEIGHT) <= box_max <= q_y_max
            #     and box_min >= q_y_min - 5.4 * self.MIN_GAP_HEIGHT
            # ):
            #     q_segs.append(box)
        ###: create a GapSegment obj
        # q_segs_obj: SurfaceGapsSegments = somefunction(q_segs)  # TODO:

        return q_segs

    def build_blank_mask(self, surface, y0=0, y1=None):
        pix = _surface_as_uint32(surface, y0, y1)
        w = surface.get_width()
        return np.fromiter(
            (self.row_is_blank(r, w) for r in pix),
            dtype=bool,
            count=pix.shape[0],
        )

    OPAQUE_WHITE = 0xFFFFFFFF
    ANY_ALPHA0_WHITE = 0x00FFFFFF  # alpha 0 + white RGB

    def row_is_blank(
        self, row, usable_cols, white=OPAQUE_WHITE, twhite=ANY_ALPHA0_WHITE
    ):
        part = row[:usable_cols]
        f1 = 0.15
        s_left = round(f1 * usable_cols)
        s_right = round((1 - f1) * usable_cols)
        middle = part[:s_right]
        sides = part[s_right:]
        # np.concatenate((part[:s_left], part[s_right:]), axis=0)
        is_side_almost_empty = (
            np.count_nonzero((sides == white) | (sides == twhite)) / len(sides)
        ) > 0.94
        is_middle_completly_empyty = np.all(
            (middle == white) | (middle == twhite)
        )

        return is_middle_completly_empyty and is_side_almost_empty

    # def is_data_white_only(self,surf:cairo.ImageSurface,y0,y1):
    #     surf.flush()
    #     y0 = round(y0)
    #     y1 = round(y1)
    #     surf.get_data()[]
    #     self.row_is_blank()

    def clip_segments_from_surface_into_contex(
        self,
        out_ctx: cairo.Context,
        out_y_start: float,
        scale: int,
        segments: list[Box] | None = None,
        q_part: Box = None,
    ):
        """return (y_after) the y-location after drawing the segments into the output Context"""
        if not segments:
            """use the whole page segments"""
            segments = self.non_empty_segments

        segments: SurfaceGapsSegments = segments
        input_surf: cairo.ImageSurface = self.surface

        # TODO: FIX ME FOR FULL PAGE RENDERING , the line_height is independent of page_height , following line should be change
        # for instande by adding a char_height (d0) to Box class
        # if not line_height:
        line_height = self.d0 * Symbol.LINE_HEIGHT_FACTOR  # * self.scale

        image_counter = 0
        trim_start_x = 0
        trim_factor = 0
        for i, box in enumerate(segments):

            # box : Box = box
            src_y, seg_h = box.y, box.h
            src_x, src_w = box.x, box.w
            next_box: Box = segments[i + 1] if i + 1 < len(segments) else None
            """subtract 0.20 , why ?? 0.1 for shifting by 0.1 * h0 pixel , because the detecting 
            has some delayed response by this ammount , and +0.1 for padding"""
            y0 = round(src_y - 0.12 * line_height)
            """only the 0.2 correspond to the padding , so in practice we shift up by 0.1 and padd by 0.1 from up and down"""
            h0 = round(seg_h + 0.12 * line_height)  # + factor * d0
            # print(y0, y1, d0)

            """Read the doc string below : this is for padding the top most line from above"""

            is_first = False

            if q_part and abs(q_part.y - src_y) < 0.5 * line_height:
                print(
                    "is_first is True",
                    "line_height =",
                    line_height,
                    "for label ",
                    q_part.label,
                )
                is_first = True
                trim_start_x = q_part.x
                trim_factor = 2.5 * line_height
                out_y_start = 1.0 * line_height

            """handle case: seg is Image/diagram"""

            if h0 > line_height * 2.0:
                image_counter += 1

            sub = input_surf.create_for_rectangle(
                0 + trim_start_x - trim_factor,
                y0,
                input_surf.get_width() + trim_start_x - trim_factor,
                h0,
            )
            out_ctx.set_source_surface(sub, 0, out_y_start)
            out_ctx.paint()

            if is_first:
                cover_surf = cairo.ImageSurface(
                    cairo.FORMAT_ARGB32,
                    round(q_part.x + line_height * 1.60),
                    round(line_height * 2.2),
                )
                temp_ctx = cairo.Context(cover_surf)

                temp_ctx.set_source_rgb(1, 1, 1)
                temp_ctx.paint()
                if False:
                    temp_ctx.set_source_rgb(0, 0, 0)
                    temp_ctx.save()
                    temp_ctx.set_font_size(10 * scale)
                    temp_ctx.get_font_matrix().scale(scale, scale)
                    temp_ctx.move_to(
                        q_part.x - 1.5 * line_height, line_height * 0.8
                    )
                    temp_ctx.show_text(f"{q_part.label} -")

                    temp_ctx.restore()

                # ---------------------------------------------

                out_ctx.set_source_surface(
                    cover_surf,
                    -1 * trim_start_x + trim_factor,  # src_x
                    out_y_start,
                )
                out_ctx.paint()

                if False:
                    out_surf: cairo.ImageSurface = out_ctx.get_target()
                    y_temp_0 = round(out_y_start)
                    y_temp_1 = round(out_y_start + h0)
                    array = self.build_blank_mask(out_surf, y_temp_0, y_temp_1)
                    if np.count_nonzero(array) >= len(array) - 1:
                        print("found empty line")
                        continue

            """this 0.25 is for spacing between lines, it require the surface to
            be paint white at beginning"""
            """if the space between 2 line is really small , then keep using its actual value  without trimming , other wise trim and add this approximated value """
            padding_after = 2.0 * line_height  # approximated value
            if next_box is not None:
                diff = next_box.y - (y0 + h0)
                # assert diff > 0
                # print("diff vs line_height ", diff, line_height)
                if diff <= 2.12 * line_height:
                    padding_after = diff - 0.12 * line_height
            out_y_start += h0 + padding_after

        return out_y_start


# **************************************************************************
# ***********************  Gui/api Classes


class Chapter:
    def __init__(
        self,
        name: str,
        nr: int,
        description: str,
        embd: list[int] | None = None,
    ) -> None:
        self.name = name
        self.number = nr
        self.description = description
        self.embd = embd
        pass


class Paper:
    def __init__(self, name: str, nr: int, chapters: list[Chapter]) -> None:
        self.chapters = chapters
        self.name = name
        self.number = nr
        pass


class Subject:
    def __init__(self, id: str) -> None:
        if id not in all_subjects:
            raise Exception(f"Unsupported subject {id}")
        self.name: str = ""
        self.id = id
        self.papers: dict[int, Paper] = {}
        sub_path = f".{sep}resources{sep}syllabuses-files{sep}{id}.json"
        if not os.path.exists(sub_path):
            raise Exception(
                "somehow syllabus files for subject {id} could not be found !!"
            )
        self.load_subject_from_file(sub_path)

        pass

    def load_subject_from_file(self, file_path: str):
        f = open(file_path, "r", encoding="utf-8")
        content = f.read()
        raw_json = json.loads(content)
        # NOTE: remove me later
        if not isinstance(raw_json, list):
            raise Exception(f"Invalid subject file {file_path}")

        paper_to_chapters_dict: dict[int, list] = defaultdict(list)
        paper_to_pnames_dict: dict[int, str] = defaultdict(str)
        for item in raw_json:
            paper_to_key: dict[str, list[str]] = item["paper_to_key"]
            all_papers_numbers: list[int] = item["papers"]
            g_name = item.get("name", "")
            for p in all_papers_numbers:
                paper_to_pnames_dict[p] += g_name
            chapters: list[dict] = item["chapters"]
            for chap in chapters:
                chap_name: str = chap["name"]
                chap_nr: int = chap["number"]
                for nr_str, identifier_str_list in paper_to_key.items():
                    chap_paper_nrs = list(map(int, nr_str.split(",")))
                    description = self.__resolve_description_from_chapter(
                        identifier_str_list, chap
                    )
                    chapter_obj = Chapter(chap_name, chap_nr, description)
                    for paper_nr in chap_paper_nrs:
                        paper_to_chapters_dict[paper_nr].append(chapter_obj)

        for p_nr, chps in sorted(
            paper_to_chapters_dict.items(), key=lambda x: x[0]
        ):
            self.papers[p_nr] = Paper(paper_to_pnames_dict[p_nr], p_nr, chps)

    def __resolve_description_from_chapter(
        self, identifier_str_list: list[str], chap: dict
    ) -> str:
        # do something , combin
        description = ""
        for identifier_str in identifier_str_list:
            ident_split = identifier_str.split(".")
            last_key_names = ident_split[-1]
            nested_keys = ident_split[:-1]
            description += self.__resolve_description_from_list_of_keys(
                nested_keys, last_key_names, chap
            )
        return description

    def __resolve_description_from_list_of_keys(
        self, nested_keys: list[str], last_key_names: str, chap: dict, depth=0
    ):
        desc = ""
        if nested_keys:
            for i, nested in enumerate(nested_keys):
                if not chap.get(nested, []):
                    continue
                for sub_chap in chap[nested]:
                    desc += self.__resolve_description_from_list_of_keys(
                        nested_keys[i + 1 :],
                        last_key_names,
                        sub_chap,
                        depth + 1,
                    )
        else:
            desc += self.__resolve_description_from_chapter_last_key(
                last_key_names, chap, depth
            )

        return desc

    def __resolve_description_from_chapter_last_key(
        self, last_keys: str, chap: dict, depth=0
    ):
        desc = ""
        for key in last_keys.split(","):
            if not chap.get(key, ""):
                continue
            name = key
            if key != "examples":
                name = (
                    chap.get("name") + f"({key})"
                    if (depth > 0 and "name" in chap)
                    else key
                )
            desc += f"\n\n**{name}**:\n\n" + chap.get(key, "")
        return desc
