import pprint
import re
from .pdf_operator import PdfOperator
import string
import os
from .pdf_encoding import PdfEncoding as pnc


class PDFStreamParser:

    def __init__(self):
        OR = "|"
        NOT_ESCAPE = (
            r"(?:[^\\]|[^\\](?:\\{2})+|[\\](?=\)\]\s*TJ)|[\\](?=\)\s*Tj))"
        )

        self.HEX_REGEX = r"<(?P<hex>[0-9a-fA-F]+)>"
        self.NAME_REGEX = r"(?P<name>/\w+)"
        self.STRING_REGEX = (
            r"(?:\((?P<string>(?:.*?" + NOT_ESCAPE + r"))(?:\)))"
        )
        self.EMPTY_STRING_REGEX = r"\((?P<stringO>)(?:\))"
        self.BOOL_REGEX = r"(?P<bool>true|false)"
        #  r"(?:\((?P<string>(?:.*?[^\\]))(?=\)))|"
        self.NUMBER_REGEX = r"(?:(?:(?<=[^_\-\n\d\.\w])|^)(?P<number>[\d.]+))|(?P<numberO>-[\d.]+)"
        self.IMAGE_REGEX = r"(?P<image>ID[\s\S]*?)(?=EI)"
        self.INLINE_IMAGE_OP_REGEX = (
            r"(?P<inline>\/(?:W|H|IM|BPC|CS|D|F|DP))(?=\W|$)"  # (?: |^)
        )

        """
    <(?P<hex>[0-9a-fA-F]+)>|(?P<name>/\w+)|\((?P<stringO>)(?:\))|(?:\((?P<string>(?:.*?(?:[^\\]|[^\\](?:\\{2})+)))(?:\)))|(?:(?:(?<=[^_\-\n\d\.])|^)(?P<number>(?:-)?[\d.]+))|(?<=ID)(?P<image>[\s\S]*?)(?=EI)
        """
        self.PRIMATIVE_REGEX = (
            self.HEX_REGEX
            # + OR
            # + self.INLINE_IMAGE_OP_REGEX
            + OR
            + self.NAME_REGEX
            + OR
            + self.STRING_REGEX
            + OR
            + self.EMPTY_STRING_REGEX
            + OR
            + self.BOOL_REGEX
            + OR
            + self.NUMBER_REGEX
            + OR
            + self.IMAGE_REGEX
        )
        self.ARRAY_REGEX = (
            r"(?:(?:(?<=[^\\])|^)\[(?P<array>[\s\S]*?(?:[^\\]|\\{2})?)\])"
        )

        # r"(?:(?:(?<=[^\\])|^)\[(?P<array>.*?(?:[^\\]|\\{2})?)\])"
        # r"(?:(?:(?<=[^\\])|^)\[(?P<array>(?:.*[^\\]))\])"
        # r"^[^(]*(?:(?:(?<=[^\\])|^)(?P<array>\[(?:.*[^\\])?\]))"

        self.DICT_REGEX = r"\s*<<(?P<obj>.*?)>>"  # (?P<name>/\w+)?
        self.DICT_CONTENT = (
            self.NAME_REGEX.replace("name", "key")
            + r"\s*(?:"
            + self.ARRAY_REGEX
            + OR
            + self.PRIMATIVE_REGEX
            + ")"
        )
        self.TYPES_MAP = {
            "number": float,
            "hex": str,
            "image": str,
            "string": str,
            "name": str,
            "inline": str,
            "binary": str,
            "bool": lambda v: True if v == "true" else False,
        }
        self.SPLIT_REGEX = r"\s+"  # r"(?:\r\n)|\n| |\s"
        self.ID_REGEX = r"ARRAY___\d+|DICT___\d+|NUMBER___\d+|STRING___\d+|NAME___\d+|BOOL___\d+|BINARY___\d+|HEX___\d+|IMAGE___\d+"
        self.INLINE_ID_REGEX = r"INLINE___\d+"
        self.TRUNCATED_HEX = r"<[0-9a-fA-F]+\s(?=[0-9a-fA-F]+>)"

        # self.INVALID_ESCAPE = re.compile(
        #     r"(?:[^\\]|^)\\(?![()\\rntb0-7])", re.MULTILINE | re.DOTALL  # f
        # )

        self.primatives_counter = 0
        self.arrays_counter = 0
        self.dict_counter = 0
        self.variables_dict = {}
        self.data: str = ""
        self.tokens = []

    def iterate(self):
        if not self.tokens:
            raise ValueError("No tokens to parse")

        arguements = []
        ignore_next = False

        inline_image = False
        for idx, token in enumerate(self.tokens):
            if not token:  # or token == ")":
                continue
            if ignore_next:
                ignore_next = False
                continue
            if re.match(self.ID_REGEX, token):
                data = self.variables_dict[token]

                if (
                    "NAME" in token
                    and inline_image
                    and re.match(self.INLINE_IMAGE_OP_REGEX, data)
                ):
                    if len(arguements) > 0:
                        print("args = ", arguements)
                        raise Exception("unhandled args")
                    cmd = self.variables_dict[token]
                    args = self.variables_dict[self.tokens[idx + 1]]
                    command = PdfOperator(cmd, [args])
                    ignore_next = True
                    yield command
                else:
                    if token.startswith("IMAGE"):
                        img_data = data.lstrip("\n ")[2:].strip("\r\n")
                        command = PdfOperator("ID", [img_data])
                        yield command
                    else:
                        arguements.append(data)
            elif token in PdfOperator.OPERTORS_SET:  # .lstrip() in

                cmd = token  # .lstrip(")")
                # if cmd == "Tf":
                #     print(self.tokens[: idx + 3])
                if cmd == "BI":
                    inline_image = True
                elif cmd == "EI" or cmd == "ID":
                    inline_image = False
                command = PdfOperator(cmd, arguements)
                arguements = []
                yield command
            else:
                print("----", token)
                mi = max(idx - 10, 0)
                ma = min(idx + 10, len(self.tokens))
                token_range = self.tokens[mi:ma]
                token_resolved = [
                    (self.variables_dict.get(s) or s) for s in token_range
                ]
                print("prev_token", token_resolved)
                raise Exception("----" + token)
        self.tokens = []

    def parse_stream(self, stream_content: str):
        self.variables_dict = {}
        self.arrays_counter = 0
        self.dict_counter = 0
        self.primatives_counter = 0
        stream_content = stream_content.replace("\\\r", "")
        stream_content = re.sub(
            self.TRUNCATED_HEX,
            lambda m: m.group(0).strip("\n"),  # \r
            stream_content,
            flags=re.DOTALL | re.MULTILINE,
        )

        def replace_primatives_v2(match: re.Match):
            for p_type, p_value in match.groupdict().items():
                if p_value is None:
                    continue

                self.primatives_counter += 1
                p_type = p_type.replace("O", "")
                value = self.TYPES_MAP[p_type](p_value)

                if p_type.startswith("string"):
                    value = value.replace("\\(", "(").replace("\\)", ")")
                    value = re.sub(
                        r"\\([1234567]{3})",
                        lambda m: pnc.octal_to_char(m.group(1)),
                        value,
                        flags=re.DOTALL | re.MULTILINE,
                    )
                elif p_type == "hex":
                    value = re.sub(
                        r"([0-9a-fA-F]{2})",
                        lambda m: pnc.hex_to_char(m.group(1)),
                        value,
                        flags=re.DOTALL | re.MULTILINE,
                    )

                primative_id = (
                    f"{p_type.upper()}___{self.primatives_counter:06}"
                )
                self.variables_dict[primative_id] = value
                return f" {primative_id} "
            return " "

        def replace_array_v2(match: re.Match):
            p_value = match.group("array")
            if p_value is None:
                return ""  # WARN: potential bug

            self.arrays_counter += 1
            array = []
            for prim_key in p_value.replace("\n", "").split(" "):
                if prim_key:  # WARN:
                    if prim_key in self.variables_dict:
                        prim_value = self.variables_dict.pop(prim_key)
                        array.append(prim_value)
                    else:
                        print("match = ", match.group("array"))
                        print("error_key =", prim_key)
                        raise Exception
            # print(array)
            array_id = f"ARRAY___{self.arrays_counter}"
            self.variables_dict[array_id] = array
            return f" {array_id} "

        def replace_dict_v2(match: re.Match):
            p_value = match.group("obj")
            if p_value is None:
                return ""  # WARN: potential bug
            # print(match.group(0))
            self.dict_counter += 1
            dict_obj = {}
            current_Key = None
            for prim_key in p_value.replace("\n", "").split(" "):
                if not prim_key:
                    continue
                if prim_key not in self.variables_dict:
                    print("match = ", match.group("obj"))
                    print("error_key =", prim_key)
                    raise Exception
                if current_Key:
                    dict_obj[current_Key] = self.variables_dict.pop(prim_key)
                    current_Key = None
                else:
                    current_Key = self.variables_dict.pop(prim_key)

            dict_id = f"DICT___{self.dict_counter}"
            self.variables_dict[dict_id] = dict_obj
            return f" {dict_id} "

        stream_content = re.sub(
            self.PRIMATIVE_REGEX,
            replace_primatives_v2,
            stream_content,
            flags=re.DOTALL | re.MULTILINE,
        )

        # print(stream_content)
        # print("\n" * 4)
        stream_content = re.sub(
            self.ARRAY_REGEX,
            replace_array_v2,
            stream_content,
            flags=re.DOTALL | re.MULTILINE,
        )

        # print(stream_content)

        stream_content = re.sub(
            self.DICT_REGEX,
            replace_dict_v2,
            stream_content,
            flags=re.DOTALL | re.MULTILINE,
        )

        self.tokens.extend(
            re.split(
                self.SPLIT_REGEX,
                stream_content,
                flags=re.MULTILINE | re.DOTALL,
            )
        )
        return self
