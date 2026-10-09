"""Synthetic first pages that reproduce real PDF metadata problems (ARA-086).

`toolchain_pdf` mirrors the USENIX paper whose Info title was `paper.dvi`: a LaTeX/dvips
Info dictionary, a rotated arXiv-style margin stamp in large type, a two-line title in the
largest horizontal font and an author line below it. Nothing here comes from a real paper.
"""

import pymupdf

TITLE = "A Bad Dream: Subverting Trusted Platform Module While You Are Sleeping"
AUTHORS = "Seunghun Han, Wook Shin, Jun-Hyeok Park, and HyoungChun Kim"


def toolchain_pdf(
    *,
    info_title="paper.dvi",
    info_author="",
    subject="",
    stamp="arXiv:1706.03762v7 [cs.CR] 2 Aug 2018",
    title_lines=("A Bad Dream: Subverting Trusted Platform", "Module While You Are Sleeping"),
    body="Abstract\nThis synthetic paper studies sleep states and measured boot.\n",
    second_page="References\n[1] An unrelated reference, doi:10.9999/unrelated.ref",
) -> bytes:
    document = pymupdf.open()
    document.set_metadata(
        {
            "title": info_title,
            "author": info_author,
            "subject": subject,
            "creator": "dvips(k) 5.997 Copyright 2017 Radical Eye Software",
        }
    )
    page = document.new_page(width=612, height=792)
    if stamp:
        # arXiv stamps the left margin vertically in 20 pt type, larger than most titles.
        page.insert_text((30, 600), stamp, fontsize=20, fontname="tiro", rotate=90)
    y = 140
    for line in title_lines:
        page.insert_text((90, y), line, fontsize=17, fontname="hebo")
        y += 22
    page.insert_text((90, y + 14), AUTHORS, fontsize=11, fontname="helv")
    page.insert_text((90, y + 30), "National Security Research Institute", fontsize=10)
    page.insert_textbox(pymupdf.Rect(90, y + 60, 540, 760), body, fontsize=10, fontname="tiro")
    if second_page:
        document.new_page(width=612, height=792).insert_textbox(
            pymupdf.Rect(72, 72, 540, 760), second_page, fontsize=10, fontname="tiro"
        )
    data = document.tobytes()
    document.close()
    return data
