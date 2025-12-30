import enum
from os.path import sep
from typing import Sequence
from models.core_models import Paragraph, Part, SubPart, Symbol, SymSequence
from models.question import QuestionBase
from models.question import Question
from .utils import get_next_label, checkIfRomanNumeral
from .core_detectors import BaseDetector


cosole_print = print
file = None


def enable_detector_dubugging(pdf_path: str):
    global file
    file = open(f"output{sep}detector_output.md", "w", encoding="utf-8")
    print("## Pdf:", pdf_path, "\n")


def print(*args):
    global file
    if not file:
        return
    args = [str(a) for a in args]
    file.write(" ".join(args) + "\n")
    file.flush()


UNKNOWN = 0
NUMERIC = 1
ALPHAPET = 2
ROMAN = 3
EITHER_OR = 4

FIRST_MAP = {
    UNKNOWN: "0",
    NUMERIC: "1",
    ALPHAPET: "(a)",
    ROMAN: "(i)",
    EITHER_OR: "EITHER",
}

FACTORS = [1, 2, 5]

LEVEL_QUESTION = 0
LEVEL_PART = 1
LEVEL_SUBPART = 2

TITLE_DICT = ["Question", "PART", "SUBPART"]


class QuestionDetectorBase(BaseDetector):
    def __init__(self, id: int) -> None:
        super().__init__(id)
        self.allowed_skip_chars = [
            " ",
            "\u0008",
            "\u2002",
            "[",
            "",
            "]",
            # ".",
        ]

        # "(",
        # ")",
        self.allowed_chars_startup = ["1", "(a)", "(i)"]

        # main attributes
        self.question_list: list[QuestionBase] = []
        self.left_most_x: list[int] = [0] * 3
        self.current_question: list[QuestionBase] = [None, None, None]
        self.type: list[int] = [UNKNOWN, UNKNOWN, UNKNOWN]

        # Constants
        self.MINIMAL_X = 0
        self.MAXIMAL_X = [0] * 3
        self.tolerance = 20
        self.is_first_detection_in_page = True

        pass

    def on_restart(self):

        self.question_list: list[QuestionBase] = []
        self.left_most_x: list[int] = [0] * 3
        self.current_question: list[QuestionBase] = [None, None, None]
        self.type: list[int] = [UNKNOWN, UNKNOWN, UNKNOWN]

        # Constants
        self.MINIMAL_X = 0
        self.MAXIMAL_X = [0] * 3
        self.tolerance = 20
        self.is_first_detection_in_page = True
        pass

    # ***********************************************
    # validate sequence and candidates ++++++++++++++
    # _______________________________________________

    def get_question_type(self, q: QuestionBase):
        n_type = ALPHAPET
        if type(q.label) is int or q.label.isdigit():
            n_type = NUMERIC
        elif checkIfRomanNumeral(q.label.strip(")()")):
            n_type = ROMAN
        elif len(q.label.strip(")()")) == 1:
            n_type = ALPHAPET
        elif q.label in ["EITHER", "OR"]:
            n_type = EITHER_OR
        else:
            raise Exception("Invalid question label")
        return n_type

    def get_allowed_startup_chars(self, level: int):
        used = None
        if level == LEVEL_QUESTION:  # WARN:
            """this work only for cambrdige IGCSE ..."""
            return "1"
        else:
            used = FIRST_MAP[self.type[level - 1]]
        res = [i for i in self.allowed_chars_startup if i != used]
        if level == LEVEL_PART:
            res.append("EITHER")
        main_q = self.current_question[LEVEL_QUESTION]
        if level == LEVEL_SUBPART and main_q and int(main_q.label) == 10:
            print(used, res)
        return res

    def get_alternative_allowed(self, level):
        # TODO: fix this
        n_type = self.type[level]
        curr: QuestionBase = self.current_question[level]
        """we can assume that this function will only be called if curr is already set
        following condition can be commented (if everything else is logically correct)
        I will leave it for debugging purposes uncommented"""
        if n_type == UNKNOWN and curr is not None:
            raise Exception("non sense : debug")

        if n_type == UNKNOWN or curr.label in self.allowed_chars_startup:
            return self.get_allowed_startup_chars(level)
        return str(curr.label)

    def get_next_allowed(self, level):
        n_type = self.type[level]
        curr = self.current_question[level]
        if n_type == UNKNOWN and curr is not None:
            raise Exception("non sense : debug")
        if n_type == UNKNOWN:
            return self.get_allowed_startup_chars(level)
        if n_type == EITHER_OR:
            return ["OR"]
        n_label = get_next_label(curr.label.strip("(").strip(")"), n_type)
        if level > 0 and n_type != EITHER_OR:
            return f"({n_label})"
        else:
            return n_label

    def is_char_valid_as_next(self, char, level, strict=False):
        next = self.get_next_allowed(level)
        if not isinstance(next, list):
            next = [next]
        for n in next:
            n = str(n)
            if strict and n == char:
                return True
            elif not strict and n.startswith(char):
                return True
        return False

    def is_char_valid_as_alternative(self, char, level, strict=False):
        # TODO: fix this
        """this is a dummy implementation, real implementation should allow rolling back
        into any breakpoint (prev question/part) in the past and continue from there,
        but here for simplicity we only allow rolling back one step , or completly discard
        everything ( logic in other code place )"""
        alternatives = self.get_alternative_allowed(level)
        if isinstance(alternatives, list):
            return char in alternatives
        alternatives = str(alternatives)
        if strict:
            return alternatives == char
        return alternatives.startswith(char)

    def is_char_x_weak_enough_to_ignore(self, diff, level):
        return diff > FACTORS[level] * self.tolerance

    def is_char_x_strong_enough_to_override(self, diff, level):
        return diff < FACTORS[level] * -self.tolerance

    def is_char_x_close_enough_to_append(self, diff, level):
        return abs(diff) <= FACTORS[level] * self.tolerance

    def is_char_skip(self, sym: Symbol, level):
        char = sym.ch
        # if sym.x < self.MINIMAL_X:
        #     return True
        """I commented following very dangerous code"""
        # if level > 0:
        #     if char in self.current[level - 1].label:
        #         return True
        return not char or char in self.allowed_skip_chars

    def is_valid_neighbours(self, sym: Symbol, n_sym: Symbol):
        return sym.is_connected_with(n_sym)

    # ***********************************************
    # Resseting internal state
    # _______________________________________________

    def reset_left_most(self, level=0):

        self.left_most_x[level:] = self.MAXIMAL_X[level:]
        return
        # if level:
        #     [self.width / 4] *  (3 - level)
        # else:
        #     self.left_most_x = [self.width / 4] * 3

    def reset_types(self, level):
        self.type[level:] = [UNKNOWN] * (3 - level)

    def reset_current(self, level):
        self.current_question[level:] = [None] * (3 - level)

    def reset(
        self,
        level: int,
    ):
        self.reset_left_most(level)
        self.reset_types(level)

        if level == LEVEL_QUESTION:
            self.question_list = []
        elif level == LEVEL_PART and self.current_question[LEVEL_QUESTION]:
            self.current_question[LEVEL_QUESTION].parts = []
        elif level == LEVEL_SUBPART and self.current_question[LEVEL_PART]:
            self.current_question[LEVEL_PART].parts = []

        self.current_question[level:] = [None] * (3 - level)
        self.reset_current(level)

    # ***********************************************************
    # ************** other Helper and utils
    # ___________________________________________________________

    def append_if_not_exist(self, a_list: list, a_number: int):
        if a_number not in a_list:
            a_list.append(a_number)

    def set_page_number_for_first_detection(self, level):
        if self.is_first_detection_in_page:
            self.is_first_detection_in_page = False
            if level == LEVEL_SUBPART:
                cur = self.current_question[LEVEL_SUBPART]
                if cur:
                    self.append_if_not_exist(cur.pages, self.curr_page)
                self.append_if_not_exist(
                    self.current_question[LEVEL_PART].pages, self.curr_page
                )
            elif level == LEVEL_PART:
                cur = self.current_question[LEVEL_PART]
                if cur:
                    self.append_if_not_exist(cur.pages, self.curr_page)
                    if cur.parts:
                        self.append_if_not_exist(
                            cur.parts[-1].pages, self.curr_page
                        )
            elif level == LEVEL_QUESTION:
                cur = self.current_question[LEVEL_QUESTION]
                if cur:
                    self.append_if_not_exist(cur.pages, self.curr_page)
                    if cur.parts:
                        self.append_if_not_exist(
                            cur.parts[-1].pages, self.curr_page
                        )
                        if cur.parts[-1].parts:
                            self.append_if_not_exist(
                                cur.parts[-1].parts[-1].pages, self.curr_page
                            )

            if level in [LEVEL_SUBPART, LEVEL_PART]:
                self.append_if_not_exist(
                    self.current_question[LEVEL_QUESTION].pages, self.curr_page
                )

            # old_cur = self.current_question[LEVEL_QUESTION]
            # if old_cur and old_cur.parts:
            #     old_cur.parts[-1].pages.append(self.curr_page)
            #     if old_cur.parts[-1].parts:
            #         old_cur.parts[-1].parts[-1].pages.append(self.curr_page)

    def get_question_list(self, pdf_file_name_or_path) -> list[Question]:
        q_list = []
        for i, q in enumerate(self.question_list):
            q_list.append(Question.from_base(q, pdf_file_name_or_path))
        return q_list


class QuestionDetector(QuestionDetectorBase):

    def __init__(self, id: int, scale: None) -> None:
        super().__init__(id)
        self.current_paragraph: Paragraph | None = None
        self.scale = scale

        pass

    # ***********************************************************
    # **************     Base Methods     ***********************
    # ___________________________________________________________

    def attach(self, page_width, page_height, page: int):
        if page > 1 and self.bufferd_line:
            self.handle_sequence(None, -1)
        self.add_curr_paragraph_to_current_question()
        super().attach(page_width, page_height, page)
        self.MINIMAL_X = 0.081 * page_width
        self.MAXIMAL_X = [i * page_width for i in [0.1, 0.19, 0.27]]
        self.header_y = page_height * 0.065
        self.footer_y = page_height * 0.93

        if len(self.question_list) == 0:
            self.reset_left_most()

        self.print_internal_status("Befor:")
        print(
            f"\n***************** page {page} ({self.width},{self.height})**********************\n"
        )
        self.curr_page = page
        self.width
        self.is_first_detection_in_page = True
        if len(self.question_list) == 0:
            self.reset(LEVEL_QUESTION)
        self.reset_left_most(1)
        self.print_internal_status("After:")
        self.prev_first_char = None
        self.line_height = (
            0.01 * page_height * Symbol.LINE_HEIGHT_FACTOR  # * self.scale
        )
        self.bufferd_line: SymSequence | None = None

    def on_finish(
        self,
    ):
        """call this function after all pages has beeing prcessed"""
        if self.bufferd_line:
            self.handle_sequence(None, -1)
        self.add_curr_paragraph_to_current_question()
        last = self.current_question[LEVEL_QUESTION]
        if not last:
            return
        self.curr_page = last.pages[-1]
        self.updata_last_y1(last, self.height)
        # last.y1 = self.height

        if len(last.parts) < 2:
            last.parts = []
        if last.parts and len(last.parts[-1].parts) < 2:
            last.parts[-1].parts = []

    def handle_sequence(self, seg: SymSequence, page: int):
        if seg:
            if seg.y >= self.footer_y or seg.y <= self.header_y:
                return
        if not self.bufferd_line:
            self.bufferd_line = seg
            return

        if seg and self.bufferd_line.row_align_with(seg, self.line_height):
            self.bufferd_line.extend(seg.data)
        else:
            # print(
            #     "exec buffered Line", self.bufferd_line.get_text(verbose=False)
            # )
            starting_j = 0
            for level in range(3):
                for j, sub_seq in enumerate(
                    self.bufferd_line.iterate_split_space()
                ):
                    if j > level:
                        break
                    elif j < starting_j:
                        continue
                    # print("subline ", sub_seq.get_text(verbose=False))
                    found = self.__handle_sequence(sub_seq, level)
                    if found:
                        starting_j += 1
                        break
                if self.current_question[level] is None:
                    break

            if (
                not self.current_paragraph
                or not self.current_paragraph.make_paragraph_with(
                    self.bufferd_line, self.line_height
                )
            ):
                # self.current_paragraph.add_line(self.bufferd_line)
                # else:

                print("saving Paragraph to Question content")
                print(self.current_paragraph)
                self.add_curr_paragraph_to_current_question()

                self.current_paragraph = (
                    Paragraph([self.bufferd_line])
                    if self.bufferd_line
                    else None
                )

            self.bufferd_line = seg

    def add_curr_paragraph_to_current_question(
        self,
    ):
        if self.current_question[LEVEL_QUESTION] and self.current_paragraph:
            self.current_question[LEVEL_QUESTION].contents.append(
                self.current_paragraph
            )
        self.current_paragraph = None

    # ***********************************************************
    # ************* the 3 Core Methods    ***********************
    # ___________________________________________________________

    def __handle_sequence(self, seq: SymSequence, level: int):
        # first_valid : Symbol | None = None

        prev_valid: Symbol | None = None
        is_next_candidate = False
        is_alternative_candidate = False
        is_overwrite_and_reset = False

        char_all = ""
        char, x, y, symbole_height, diff = "", 0, 0, 0, None

        can_append, can_overwrite = None, None
        last_sym = None

        for _, sym in enumerate(seq):
            sym: Symbol = sym
            char = sym.ch
            if self.is_char_skip(sym, level):
                continue
            if sym.x < self.MINIMAL_X:
                break

            if prev_valid and not self.is_valid_neighbours(sym, prev_valid):
                break

            prev_valid = sym

            if diff is None:
                x, y, x1, y1 = sym.get_box()
                symbole_height = y1 - y
                self.tolerance = x1 - x
                diff = x - self.left_most_x[level]

                if self.is_char_x_weak_enough_to_ignore(diff, level):
                    return False

                can_append = self.is_char_x_close_enough_to_append(diff, level)
                can_overwrite = self.is_char_x_strong_enough_to_override(
                    diff, level
                )

            valid_as_next = self.is_char_valid_as_next(char_all + char, level)
            valid_as_alt = self.is_char_valid_as_alternative(
                char_all + char, level
            )

            if valid_as_next:
                char_all += char
                last_sym = sym
                is_next_candidate = True
                continue

            elif valid_as_alt:
                char_all += char
                last_sym = sym
                is_alternative_candidate = True
                continue

            elif can_overwrite:
                print(
                    f"\nP{self.curr_page}-L{level}: Ignored 'OVERRIDE' char:(charall={char_all},char={char}) "
                    + seq.get_text()
                )
                pass
                # TODO: only adjust left_most_x , but don't set any thing new
                # if diff < -self.tolerance:  # and diff_upper > 0:
                #     self.reset(level)
                #     self.left_most_x[level] = x
            elif can_append:
                print(
                    f"\nP{self.curr_page}-L{level}: Ignored 'APPEND' Seq: "
                    + seq.get_text()
                )
            elif valid_as_next or valid_as_alt:
                pass

            is_next_candidate = is_alternative_candidate = False
            return False

        if is_overwrite_and_reset:
            print(
                f"\nP{self.curr_page}-L{level}: Found OVERRIDE_AND_RESET =>\n"
                + seq.get_text(verbose=False)
            )
            self.reset(LEVEL_QUESTION)  # current level == 0
            new_q = QuestionBase(
                "1",
                self.curr_page,
                level,
                x,
                y,
                self.width,
                self.height,
                2 * symbole_height,
            )
            self.add_question(new_q, level, label_y1=last_sym.box[-1])
            return True

        elif is_next_candidate and self.is_char_valid_as_next(
            char_all, level, strict=True
        ):

            print(
                f"\nP{self.curr_page}-L{level}: Found Next Candidate =>\n"
                + seq.get_text(verbose=False)
            )
            new_q = QuestionBase(
                char_all,
                self.curr_page,
                level,
                x,
                y,
                self.width,
                self.height,
                2 * symbole_height,
            )
            self.add_question(new_q, level, label_y1=last_sym.box[-1])
            return True

        elif is_alternative_candidate and self.is_char_valid_as_alternative(
            char_all, level, strict=True
        ):

            print(
                f"\nP{self.curr_page}-L{level}: Found Alternative Candidate =>\n"
                + seq.get_text()
            )
            new_q = QuestionBase(
                char_all,
                self.curr_page,
                level,
                x,
                y,
                self.width,
                self.height,
                2 * symbole_height,
            )
            self.replace_question(new_q, level, label_y1=last_sym.box[-1])
            return True

        else:
            return False

    def replace_question(self, q: QuestionBase, level: int, label_y1: float):
        old_curr = self.current_question[level]
        if old_curr and len(old_curr.parts) > 1:
            print(
                "Can not replace old question because it already has detected 2+ parts"
            )
            return
        elif (
            old_curr
            and len(old_curr.parts) > 0
            and len(old_curr.parts[0].parts) > 1
        ):

            print(
                "Can not replace old question because it already has detected a part with 2+ sub-parts"
            )
            return
        elif not old_curr:
            self.add_question(q, level, label_y1=label_y1)
            return

        print(
            f"\nP{self.curr_page}-L{level}: trying to replace old question (label = {q.label})"
        )

        self.set_page_number_for_first_detection(level)
        if level < 2:
            self.reset(level + 1)
        # if level < 2:
        #     self.current[level + 1 :] = [None] * (3 - level + 1)
        #     self.type[level + 1 :] = [UNKNOWN] * (3 - level)
        print("new_question => \n", q)
        print("old_question => \n", old_curr)
        print([str(f) for f in self.question_list])

        part_or_subpart = None
        if level == LEVEL_QUESTION:
            self.question_list[-1] = q
        elif level == LEVEL_PART and self.current_question[LEVEL_QUESTION]:
            part_or_subpart = Part(
                q.label, q.x, q.y, label_y1, q.y + self.line_height
            )
            self.current_question[LEVEL_QUESTION].parts[-1] = q
        elif level == LEVEL_SUBPART and self.current_question[LEVEL_PART]:

            part_or_subpart = SubPart(
                q.label, q.x, q.y, label_y1, q.y + self.line_height
            )
            self.current_question[LEVEL_PART].parts[-1] = q

        else:
            raise Exception

        if part_or_subpart:
            self.current_question[LEVEL_QUESTION].contents.append(
                part_or_subpart
            )

        # print(q)
        # print([f.get_title() for f in self.question_list])

        n_type = self.get_question_type(q)
        self.type[level] = n_type
        self.left_most_x[level] = q.x
        self.current_question[level] = q

    def updata_last_y1(self, old_cur: QuestionBase, new_y_start):
        last_y1 = (
            (new_y_start - 0.2 * self.line_height)
            if self.curr_page in old_cur.pages
            else self.height
        )
        old_cur.y1 = last_y1
        if old_cur.parts:
            old_cur.parts[-1].y1 = last_y1
            if old_cur.parts[-1].parts:
                old_cur.parts[-1].parts[-1].y1 = last_y1

    def add_question(self, q: QuestionBase, level: int, label_y1):
        print(
            f"\nP{self.curr_page}-L{level}: trying to add question ..(label = {q.label})"
        )
        self.set_page_number_for_first_detection(level)
        old_cur = self.current_question[level]
        if old_cur:
            if len(old_cur.parts) < 2:
                self.reset(level + 1)
            self.updata_last_y1(old_cur, q.y)

        if level < LEVEL_SUBPART:
            self.reset_current(level + 1)
            self.reset_types(level + 1)

        part_or_subpart = None

        self.add_curr_paragraph_to_current_question()
        if level == LEVEL_QUESTION:
            self.question_list.append(q)
            self.current_question[LEVEL_QUESTION] = q
        elif level == LEVEL_PART and self.current_question[LEVEL_QUESTION]:
            part_or_subpart = Part(
                q.label, q.x, q.y, label_y1, q.y + self.line_height
            )
            print("adding [sub]partts to main questino !")
            self.current_question[LEVEL_QUESTION].parts.append(q)
            self.current_question[LEVEL_PART] = q
        elif level == LEVEL_SUBPART and self.current_question[1]:
            part_or_subpart = SubPart(
                q.label, q.x, q.y, label_y1, q.y + self.line_height
            )
            self.current_question[LEVEL_PART].parts.append(q)
            self.current_question[LEVEL_SUBPART] = q
        else:
            raise Exception

        if part_or_subpart:
            self.current_question[LEVEL_QUESTION].contents.append(
                part_or_subpart
            )

        print("new_question =>\n", q)
        print([f.get_title() for f in self.question_list])

        n_type = self.get_question_type(q)
        self.type[level] = n_type
        self.left_most_x[level] = q.x

    # ***********************************************************
    # ************** Printing & Debugging ***********************
    # ___________________________________________________________

    def print_final_results(self, curr_file):
        print = cosole_print
        print("\n\n")
        print("****************** Final Result ********************\n")
        if len(self.question_list) == 0:
            print(f"No question found on this exam ({curr_file}) ")
        else:
            print(
                f"found the following questions on pdf {curr_file} "  # [{self.current_page}]"
            )
            for q in self.question_list:
                print(q)

    def print_internal_status(self, title):
        print(title)
        print("current left most = ", self.left_most_x)
        print("current types = ", self.type)
        print(
            "current types = ",
            [self.get_next_allowed(lev) for lev in range(3)],
        )


if __name__ == "__main__":
    syms = SymSequence()
    for i in range(10):
        syms.append(Symbol(chr(i + 65), 0, 0, 10, 10))

    print(syms.size())
    print(syms[:6])
