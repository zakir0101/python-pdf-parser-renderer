from sys import exc_info
import numpy as np
import cairo
import subprocess
import os
from os.path import sep


if os.name == "nt":  # Windows
    d_drive = "D:"
else:
    d_drive = "/mnt/d"
if os.environ.get("IGCSE_PATH"):
    igcse_path = os.environ["IGCSE_PATH"]
else:
    igcse_path = f"{d_drive}{sep}Drive{sep}IGCSE-NEW"


all_subjects = [
    f
    for f in os.listdir(igcse_path)
    if os.path.isdir(igcse_path + sep + f) and f.isdigit()
]

# ************************************************************************
# ********************** Page Segmentation *******************************
# ************************************************************************


def _surface_as_uint32(surface: cairo.ImageSurface, y0, y1):
    """
    Return a (h, stride//4) view where each element is one ARGB32 pixel
    exactly as Cairo stores it (premultiplied, native endian).
    """
    surface.flush()  # make sure the C side is done
    h, stride = surface.get_height(), surface.get_stride()
    buf = surface.get_data()  # Python buffer -> zero-copy
    array = np.frombuffer(buf, dtype=np.uint32).reshape(h, stride // 4)
    if y1 is None:
        y1 = len(array) - 1
    return array[y0:y1]


def concat_cairo_surfaces(surf_dict: dict[str, cairo.ImageSurface]):
    height = sum([s.get_height() for s in surf_dict.values()])
    width = max([s.get_width() for s in surf_dict.values()])

    out_surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    out_ctx = cairo.Context(out_surf)
    y_out = 0
    for id, surf in surf_dict.items():
        out_ctx.set_source_surface(surf, 0, y_out)
        out_ctx.paint()
        y_out += surf.get_height()

    return out_surf


def crop_image_surface(out_surf: cairo.ImageSurface, y_start, y_end, padding):
    # print("dest_y", self.dest_y)

    o = out_surf
    s = round(y_start if y_start <= padding else y_start - padding)
    e = round(
        y_end + padding if y_end < (out_surf.get_height() - padding) else y_end
    )
    #     e = round(y_end + padding if y_end < (out_surf.get_height() - padding) else y_end)

    s_index = s * o.get_stride()
    e_index = e * o.get_stride()

    surf_width = out_surf.get_width()
    surf_height = e - s
    data = o.get_data()[s_index:e_index]
    # print(surf_height, "vs", (e_index - s_index) // o.get_stride())
    # print("full_data_len", len(o.get_data()))
    # print(len(data), "vs", surf_height * surf_width * 4)
    out_surf = cairo.ImageSurface.create_for_data(
        data,
        cairo.FORMAT_ARGB32,
        surf_width,
        surf_height,
        o.get_stride(),
    )
    return out_surf


# *********************************************************
# *****************++ Numeric, Roman and Alphabet numbering
# ******************* Handler :


def get_alphabet(number):
    # index = ord('a') + (number - 1 )
    return chr(number - 1 + 97)


def get_roman(number):
    num = [1, 4, 5, 9, 10, 40, 50, 90, 100, 400, 500, 900, 1000]
    sym = [
        "I",
        "IV",
        "V",
        "IX",
        "X",
        "XL",
        "L",
        "XC",
        "C",
        "CD",
        "D",
        "CM",
        "M",
    ]
    i = 12
    # number = number + 1
    result = ""
    while number:
        div = number // num[i]
        number %= num[i]

        while div:
            result += sym[i]
            div -= 1
        i -= 1

    return result.lower()


def checkIfRomanNumeral(numeral: str):
    """Controls that the userinput only contains valid roman numerals"""
    numeral = numeral.upper()
    validRomanNumerals = ["X", "V", "I"]
    valid = True
    for letters in numeral:
        if letters not in validRomanNumerals:
            valid = False
            break
    return valid


def value(r):
    if r == "I":
        return 1
    if r == "V":
        return 5
    if r == "X":
        return 10
    if r == "L":
        return 50
    if r == "C":
        return 100
    if r == "D":
        return 500
    if r == "M":
        return 1000
    return -1


def romanToDecimal(str):
    res = 0
    i = 0

    while i < len(str):
        # Getting value of symbol s[i]
        s1 = value(str[i])

        if i + 1 < len(str):
            # Getting value of symbol s[i + 1]
            s2 = value(str[i + 1])

            # Comparing both values
            if s1 >= s2:
                # Value of current symbol is greater
                # or equal to the next symbol
                res = res + s1
                i = i + 1
            else:
                # Value of current symbol is greater
                # or equal to the next symbol
                res = res + s2 - s1
                i = i + 2
        else:
            res = res + s1
            i = i + 1

    return res


def alpha_roman_to_decimal(charac):
    """
    convert alpha / roman number to decimals , starting from 0 == a or i
    """
    is_roman = checkIfRomanNumeral(charac)
    if is_roman:
        num = romanToDecimal(charac.upper())
    elif len(charac) == 1:
        num = ord(charac) - 96
    else:
        raise Exception
    return num - 1


def get_next_label_old(prev: str):
    is_roman = checkIfRomanNumeral(prev)
    if is_roman:
        num = romanToDecimal(prev.upper())
        next = get_roman(num + 1)
    elif len(prev) == 1:
        num = ord(prev)
        next = get_alphabet(num - 96 + 1)
    else:
        raise Exception
    return next


NUMERIC = 1
ALPHAPET = 2
ROMAN = 3


def get_next_label(prev, system):
    prev = str(prev)
    if prev.isdigit() and system == NUMERIC:
        prev = int(prev)
        prev += 1
        return prev
    elif type(prev) is str and system == ROMAN:
        num = romanToDecimal(prev.upper())
        return get_roman(num + 1)
    elif type(prev) is str and len(prev) == 1 and system == ALPHAPET:
        num = ord(prev)
        return get_alphabet(num - 96 + 1)
    else:
        raise Exception


def is_first_label(input: str):
    return input == "i" or input == "a"


SEP = os.path.sep


# *********************************************************************
# *********************+ open Files using system apps *****************
# ********************** ^^^^^^^^^^^^^^^^^^^^^^^^^^^^ *****************


def open_pdf_using_sumatra(pdf_full_path):
    if os.name != "nt":  # Windows
        png_full_path = pdf_full_path.replace("/mnt/d", "D:")
    subprocess.Popen(
        args=[
            "SumatraPDF-3.5.2-64.exe",
            png_full_path,
        ],
        start_new_session=True,
        stdout=None,
        stderr=None,
        stdin=None,
    )


def open_files_in_nvim(files: list[str]):
    print(files)
    subprocess.run(
        args=[
            "nvim",
            "-p10",
            *files,
        ],
        check=False,
        # start_new_session=True,
        # stdout=None,
        # stderr=None,
        # stdin=None,
    )


def open_image_in_irfan(img_path):
    c_prefix = "C:" if os.name == "nt" else "/mnt/c"
    png_full_path = "\\\\wsl.localhost\\Ubuntu" + os.path.abspath(img_path)
    if os.name != "nt":  # Windows
        png_full_path = png_full_path.replace("/", "\\")
    subprocess.Popen(
        args=[
            f"{c_prefix}{SEP}Program Files{SEP}IrfanView{SEP}i_view64.exe",
            png_full_path,
        ],
        start_new_session=True,
        stdout=None,
        stderr=None,
        stdin=None,
    )


def kill_with_taskkill():
    """Use Windows’ native taskkill (works from Windows or WSL)."""
    TARGET = "i_view64.exe"
    TARGET2 = "SumatraPDF-3.5.2-64.exe"
    cmd = ["taskkill.exe", "/IM", TARGET, "/F"]
    cmd = ["taskkill", "/IM", TARGET2, "/F"]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def in_wsl() -> bool:
    """True if running under Windows Subsystem for Linux."""
    return os.name == "posix" and (
        "WSL_DISTRO_NAME" in os.environ or "WSL_INTEROP" in os.environ
    )


if __name__ == "__main__":
    roman = get_roman(1)
    alpha = get_alphabet(1)
    for i in range(1, 9):
        print(roman, alpha)
        print(alpha_roman_to_decimal(roman), alpha_roman_to_decimal(alpha))
        roman = get_next_label(roman)
        alpha = get_next_label(alpha)
