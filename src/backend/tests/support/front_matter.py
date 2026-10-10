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


def xmp_packet(*, title=None, creators=(), doi=None, identifier=None, venue=None, cover_date=None):
    """An XMP packet in the shape publishers embed (dc, prism), with only the given fields."""
    parts = []
    if title is not None:
        parts.append(
            f'<dc:title><rdf:Alt><rdf:li xml:lang="x-default">{title}</rdf:li></rdf:Alt></dc:title>'
        )
    if creators:
        names = "".join(f"<rdf:li>{name}</rdf:li>" for name in creators)
        parts.append(f"<dc:creator><rdf:Seq>{names}</rdf:Seq></dc:creator>")
    if identifier is not None:
        parts.append(f"<dc:identifier>{identifier}</dc:identifier>")
    if doi is not None:
        parts.append(f"<prism:doi>{doi}</prism:doi>")
    if venue is not None:
        parts.append(f"<prism:publicationName>{venue}</prism:publicationName>")
    if cover_date is not None:
        parts.append(f"<prism:coverDate>{cover_date}</prism:coverDate>")
    return (
        '<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF '
        'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:prism="http://prismstandard.org/namespaces/basic/2.0/" '
        'xmlns:xmp="http://ns.adobe.com/xap/1.0/">'
        "<xmp:CreateDate>2026-01-02T03:04:05Z</xmp:CreateDate>"
        + "".join(parts)
        + '</rdf:Description></rdf:RDF></x:xmpmeta><?xpacket end="w"?>'
    )


def with_xmp(data: bytes, packet: str) -> bytes:
    document = pymupdf.open(stream=data, filetype="pdf")
    document.set_xml_metadata(packet)
    result = document.tobytes()
    document.close()
    return result
