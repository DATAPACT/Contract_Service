import base64
import io
import json
import os
import random
import re
from copy import deepcopy
from datetime import datetime, date
from decimal import Decimal
# from __future__ import annotations
from typing import Any, Dict, Optional, List
from urllib.parse import urlparse, unquote

from dotenv import load_dotenv
from openai import OpenAI
from rdflib import Graph, URIRef, Literal, BNode, Namespace
from rdflib.namespace import SKOS, RDFS, RDF, XSD, FOAF, DCTERMS, DCAT
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

load_dotenv()
client = OpenAI()

MODEL_NAME = os.getenv("MODEL_NAME")

# directory that contains this script
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
odrldpv_path = os.path.join(
    BASE_DIR, ".", "odrl_vocabulary_des", "ODRL_DPV.rdf")


# json_path_odrl_des = os.path.join(
#     BASE_DIR, ".", "odrl_vocabulary_des", "ODRL22_keyword_des.json"
# )
# json_path_oder_des = os.path.normpath(json_path_odrl_des)
#
# json_path_dpv_des = os.path.join(
#     BASE_DIR, ".", "odrl_vocabulary_des", "dpv_keyword_des.json"
# )
# json_path_dpv_des = os.path.normpath(json_path_dpv_des)
#
# # Reload keyword description files
# with open(json_path_oder_des, "r", encoding="utf-8") as f:
#     odrl_keywords = json.load(f)
#
# with open(json_path_dpv_des, "r", encoding="utf-8") as f:
#     dpv_keywords = json.load(f)

# Merge the two into a single lookup dictionary
# keyword_lookup = {**odrl_keywords, **dpv_keywords}


def _prefer_lang(literals, langs=("en", None)):
    # return the first literal matching preferred languages
    for lang in langs:
        for lit in literals:
            if isinstance(lit, Literal) and lit.language == lang:
                return str(lit)
    # fallback: first literal (any language)
    for lit in literals:
        if isinstance(lit, Literal):
            return str(lit)
    return None


class OdrlDpvObj(object):
    def __init__(self, rdf_path=odrldpv_path):
        self.g = Graph()
        self.g.parse(rdf_path)

    def query_sparql(self, query_str: str):
        # Use this when you pass an actual SPARQL query
        return self.g.query(query_str)

    def describe_uri(self, uri: str):
        # Return all triples about a term (subject = uri)
        s = URIRef(uri)
        return list(self.g.predicate_objects(s))

    def parse_name(self, str_url) -> str:
        """Extract the local name from a URI and return a clean, spaced label.
        Examples:
          ...#Audit_Provision     -> 'Audit Provision'
          .../personalData        -> 'Personal Data'
          .../GDPR_Art6(1)(b)     -> 'GDPR Art 6 1 b'
          .../odrl-aggregate      -> 'Odrl Aggregate'
        """
        if not str_url:
            return ""
        s = str(str_url)

        # 1) local part after last '#' or '/', decode percent-escapes
        local = s.rsplit('#', 1)[-1] if '#' in s else s.rstrip('/').rsplit('/', 1)[-1]
        local = unquote(local)

        # 2) normalize separators to spaces (underscore, dash, dot, colon, plus, etc.)
        #    \W matches non-alphanumerics; include '_' explicitly
        tmp = re.sub(r'[\W_]+', ' ', local)

        # 3) camelCase / PascalCase boundary splits, incl. ACRONYM + Word
        tmp = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', tmp)  # fooBar -> foo Bar, a9B -> a9 B
        tmp = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', tmp)  # GDPRArt -> GDPR Art

        # 4) collapse multiple spaces and title-case while preserving acronyms
        tokens = tmp.split()

        def cap_token(t: str) -> str:
            # preserve acronyms (2+ chars, all upper), else Capitalize
            return t if (len(t) > 1 and t.isupper()) else (t[:1].upper() + t[1:].lower())

        return " ".join(cap_token(t) for t in tokens)

    def parse_url(self, uri: str, langs=("en", None)):
        """
        Return SKOS prefLabel, definition, and notes for a given URI.
        Falls back to RDFS label/comment when SKOS is absent.
        langs: tuple of preferred languages to match (e.g., ('en', None))
        """
        s = URIRef(uri)

        # Primary (SKOS)
        labels = list(self.g.objects(s, SKOS.prefLabel))
        defs = list(self.g.objects(s, SKOS.definition))
        notes = list(self.g.objects(s, SKOS.note))

        # Fallbacks (RDFS) if SKOS not present
        if not labels:
            labels = list(self.g.objects(s, RDFS.label))

        if not defs:
            defs = list(self.g.objects(s, RDFS.comment))

        if len(labels) < 1:
            labels = self.parse_name(uri)
            return {
                "prefLabel": labels,  # str or None
                "definition": None,  # str or None
                "note": None

            }

        # Preferred singletons
        pref_label = _prefer_lang(labels, langs)
        definition = _prefer_lang(defs, langs)
        # Keep all notes (as strings); also offer a preferred note
        preferred_note = _prefer_lang(notes, langs) if notes else None

        return {
            "prefLabel": pref_label,  # str or None
            "definition": definition,  # str or None
            "note": preferred_note,  # str or None (language-preferred)

        }


odrl_dpv_obj = OdrlDpvObj()


def summarize_text(text: str, max_words: int = 500) -> str:
    """Return a concise summary of `text` in ~`max_words` words."""
    prompt = (
        f"Summarize the following text in about {max_words} words. "
        "Be concise, factual, and preserve key numbers, names, and dates.\n\n"
        "For the clause of Policies and Rules, make it more concise, and more detail"
        f"{text}"
    )

    resp = client.responses.create(
        model=MODEL_NAME,  # good, fast, and cost-effective for summarization
        input=prompt,
        # temperature=0.2,  # lower = more concise/consistent
    )
    # Most SDKs expose a convenience property that aggregates all text:
    return resp.output_text


def refinements_odrl_des(content):
    """
    using AI to polish the ODRL-description
    Accepts a dict or JSON string with keys: permission, prohibition, obligation, duty.
    Returns a dict with the SAME structure but legally edited sentences.
    """

    # Normalise input to a Python dict
    if isinstance(content, str):
        try:
            input_obj = json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(f"'content' must be valid JSON. Decode error: {e}")
    elif isinstance(content, dict):
        input_obj = content
    else:
        raise TypeError("'content' must be a dict or a JSON string.")

    # Capture expected order and list lengths (lightweight, inline)
    input_keys = list(input_obj.keys())
    expected_lengths = {k: len(v) for k, v in input_obj.items() if isinstance(v, list)}

    content_text = json.dumps(input_obj, ensure_ascii=False)

    prompt = f"""
            You are a senior legal editor specialising in data-sharing agreements.
            
            TASK
            - Edit the English in the string values of the JSON below to be grammatically correct, precise, and in formal legal style.
            - Keep the EXACT SAME JSON structure: same keys, same list lengths, same item order. Do NOT add, remove, merge, or reorder any items.
            - Edit ONLY the text inside the strings.
            - Preserve the dataset name, party labels ("Party A", "Party B"), and the action terms exactly as written (e.g., "anonymize action", "derive action", "aggregate action", "distribution action").
            - Prefer concise legal phrasing (e.g., "solely for the purpose of …", "shall", "is permitted by").
            - Fix spacing, punctuation, prepositions, and hyphenation where needed (e.g., "apply … to", "maintaining the credit-rating database", "counter-terrorism", "anti-money-laundering").
            - Use UK legal English (en-GB). If a defined term appears US-spelled in an action name, leave it as is.
            
            INPUT JSON
            '''{content_text}'''
            
            OUTPUT
            Return ONLY valid JSON with the same structure (no code fences, no commentary).
            """

    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": "You are an expert document assistant. Return ONLY valid JSON."},
            {"role": "user", "content": prompt},
        ],
        # temperature=0,  # deterministic for editing
        # If supported by your SDK/model, uncomment:
        # response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content.strip()

    # Extract the first JSON object from the model output
    def extract_first_json_object(text: str) -> str:
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
        start = text.find("{")
        if start == -1:
            return text
        depth = 0
        for i in range(start, len(text)):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
        return text  # if unbalanced; will fail JSON parsing

    candidate = extract_first_json_object(raw)

    # Parse JSON -> dict
    try:
        out_obj = json.loads(candidate)
    except json.JSONDecodeError as e:
        raise ValueError(f"Model did not return valid JSON. Parse error: {e}\nRaw output:\n{raw}")

    # Minimal structure checks (inline, no helper)
    if list(out_obj.keys()) != input_keys:
        raise ValueError(f"Output keys/order changed.\nExpected: {input_keys}\nGot: {list(out_obj.keys())}")

    for k, exp_len in expected_lengths.items():
        v = out_obj.get(k)
        if not isinstance(v, list):
            raise ValueError(f'Key "{k}" expected a list, got {type(v).__name__}')
        if len(v) != exp_len:
            raise ValueError(f'List length mismatch for "{k}": expected {exp_len}, got {len(v)}')
        if not all(isinstance(x, str) for x in v):
            raise ValueError(f'Non-string item found in list "{k}".')

    return out_obj


# ---------------- Font registration (Arial if available, else Helvetica) ----------------
def _register_arial_family():
    """
    Try to register Arial TTFs if the system has them.
    Returns (regular, italic, bold) font names to use.
    Fallback: ('Helvetica', 'Helvetica-Oblique', 'Helvetica-Bold')
    """
    candidates = [
        # Windows
        (r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\ariali.ttf", r"C:\Windows\Fonts\arialbd.ttf"),
        # macOS
        ("/Library/Fonts/Arial.ttf", "/Library/Fonts/Arial Italic.ttf", "/Library/Fonts/Arial Bold.ttf"),
        # Common Linux packs
        ("/usr/share/fonts/truetype/msttcorefonts/arial.ttf",
         "/usr/share/fonts/truetype/msttcorefonts/ariali.ttf",
         "/usr/share/fonts/truetype/msttcorefonts/arialbd.ttf"),
        ("/usr/share/fonts/truetype/msttcorefonts/Arial.ttf",
         "/usr/share/fonts/truetype/msttcorefonts/Arial_Italic.ttf",
         "/usr/share/fonts/truetype/msttcorefonts/Arial_Bold.ttf"),
    ]
    for reg, ita, bld in candidates:
        try:
            pdfmetrics.registerFont(TTFont("Arial", reg))
            pdfmetrics.registerFont(TTFont("Arial-Italic", ita))
            pdfmetrics.registerFont(TTFont("Arial-Bold", bld))
            return ("Arial", "Arial-Italic", "Arial-Bold")
        except Exception:
            continue
    return ("Helvetica", "Helvetica-Oblique", "Helvetica-Bold")


# ---------------- Numbered canvas without double-render ----------------
class NumberedCanvas(canvas.Canvas):
    """
    Defers page output until save(), so we can stamp 'Page X of Y' once.
    """

    def __init__(self, *args, footer_y=28, page_center_x=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []
        self._footer_y = footer_y
        self._page_center_x = page_center_x or (self._pagesize[0] / 2.0)
        self._footer_font = ("Helvetica", 9)

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def draw_page_number(self, page_count):
        self.setFont(*self._footer_font)
        self.drawCentredString(self._page_center_x, self._footer_y, f"Page {self._pageNumber} of {page_count}")

    def save(self):
        self._saved_page_states.append(dict(self.__dict__))
        total = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_number(total)
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)


# ---------------- helpers ----------------
def data_url_to_imagereader(data_or_path):
    """Accept data URL / base64 / bytes / filepath; return ImageReader or None."""
    if data_or_path is None:
        return None
    if isinstance(data_or_path, bytes):
        return ImageReader(io.BytesIO(data_or_path))
    s = str(data_or_path)
    if s.startswith("data:"):
        try:
            _, b64 = s.split(",", 1)
            return ImageReader(io.BytesIO(base64.b64decode(b64)))
        except Exception:
            return None
    if re.fullmatch(r"[A-Za-z0-9+/=\s]+", s[:120] or "") and len(s) > 120:
        try:
            return ImageReader(io.BytesIO(base64.b64decode(s)))
        except Exception:
            pass
    try:
        return ImageReader(s)
    except Exception:
        return None


# ---------------- main renderer ----------------
def text_to_pdf_bytes(
        text,
        contract_id,
        negotiation_id,
        consumer_signature=None,  # kept for compatibility, not used
        consumer_signature_date=None,  # kept for compatibility, not used
        provider_signature=None,  # kept for compatibility, not used
        provider_signature_date=None,  # kept for compatibility, not used
        contract_type="dsa",
        add_signature_block: bool = False,  # default FALSE: do not add our own signature area
) -> io.BytesIO:
    """
    Formal PDF:
      - Header (title+IDs), footer rule, 'Page X of Y'
      - Arial font (fallback to Helvetica), leading = 1.5
      - Extra space BEFORE and AFTER section titles
      - Big centered title 'DATA SHARING CONTRACT' on the first page
      - **No auto-generated signature block**; signatures are taken from the input text
      - Table of Contents caption is BOLD; all ToC items are NOT bold (incl. 'Preamble' in ToC)
      - Body heading 'Preamble' is BOLD (H1)
    """

    # -------- 1) Preprocess & split --------
    text = (text or "").replace("\u25A0", "").expandtabs(4)
    lines = text.splitlines()
    print("contract_type", contract_type)
    is_dsa = contract_type == "dsa"
    is_consent = contract_type in {"consent_contract", "pda"}
    signature_images = {
        "provider": data_url_to_imagereader(provider_signature),
        "consumer": data_url_to_imagereader(consumer_signature),
    }

    def _format_sig_date(val):
        if isinstance(val, datetime):
            return val.strftime("%Y-%m-%d")
        if isinstance(val, date):
            return val.strftime("%Y-%m-%d")
        return str(val) if val not in (None, "") else ""

    signature_dates = {
        "provider": _format_sig_date(provider_signature_date),
        "consumer": _format_sig_date(consumer_signature_date),
    }
    # Remove top duplicate title; header + big title will handle it
    if is_dsa:
        if lines and lines[0].strip().upper() == "DATA SHARING AGREEMENT":
            lines = lines[1:]
    elif is_consent:
        if lines and lines[0].strip().upper() == "DATA CONSENT AGREEMENT":
            lines = lines[1:]
    else:
        if lines and lines[0].strip().upper() == "DATA AGREEMENT":
            lines = lines[1:]

    # IMPORTANT: Do NOT strip any signature tables from the text anymore.
    # We keep the 'Signatures' section exactly as provided.

    # Split at last "X. Appendix" so we ensure appendix starts on a fresh page
    app_hdr_re = re.compile(r"^\s*\d+\.\s*Appendix", flags=re.I)
    app_indices = [i for i, ln in enumerate(lines) if app_hdr_re.match(ln)]
    if app_indices:
        appendix_idx = app_indices[-1]
        body_lines = lines[:appendix_idx]
        appendix_lines = lines[appendix_idx:]
    else:
        body_lines = lines
        appendix_lines = []

    # -------- 2) Canvas & fonts --------
    buf = io.BytesIO()
    width, height = A4

    left_margin, right_margin = 50, 50
    top_margin, bottom_margin = 70, 70
    max_width = width - left_margin - right_margin

    page_num_y = bottom_margin - 28
    page_center_x = width / 2

    c = NumberedCanvas(
        buf,
        pagesize=A4,
        footer_y=page_num_y,
        page_center_x=page_center_x,
    )

    # Metadata
    if is_dsa:
        c.setTitle("Data Sharing Agreement")
    elif is_consent:
        c.setTitle("Data Consent Agreement")
    else:
        c.setTitle("Data Agreement")

    c.setAuthor("UPCAST Negotiation Software")

    if not negotiation_id:
        c.setSubject(f"Contract ID {contract_id}")
    else:
        c.setSubject(f"Contract ID {contract_id} / Negotiation ID {negotiation_id}")

    # Fonts (Arial if possible)
    FONT_BODY, FONT_ITAL, FONT_BOLD = _register_arial_family()

    size_body = 11
    size_h1 = 15
    size_h2 = 13
    leading = int(size_body * 1.5)  # airier layout (1.5)

    heading_pre_gap_lines = 1
    heading_post_gap_lines = 1

    # -------- page decor --------
    def draw_header():
        c.setFont(FONT_BOLD, 11)

        if is_dsa:
            c.drawString(left_margin, height - top_margin + 30, "DATA SHARING AGREEMENT")
        elif is_consent:
            c.drawString(left_margin, height - top_margin + 30, "DATA CONSENT AGREEMENT")
        else:
            c.drawString(left_margin, height - top_margin + 30, "DATA AGREEMENT")

        c.setFont(FONT_BODY, 9)

        if not negotiation_id:

            hdr_right = f"CON-ID: {contract_id}"
        else:
            hdr_right = f"CON-ID: {contract_id} | NEGO-ID: {negotiation_id}"

        c.drawRightString(width - right_margin, height - top_margin + 30, hdr_right)
        c.setStrokeColor(colors.black)
        c.setLineWidth(0.5)
        c.line(left_margin, height - top_margin + 24, width - right_margin, height - top_margin + 24)

    def draw_footer_rule():
        c.setStrokeColor(colors.black)
        c.setLineWidth(0.5)
        c.line(left_margin, bottom_margin - 16, width - right_margin, bottom_margin - 16)

    page_idx = 0  # 0-based

    def draw_doc_title():
        c.setFont(FONT_BOLD, 20)

        if is_dsa:
            c.drawCentredString(width / 2, height - top_margin - 12, "DATA SHARING AGREEMENT")
        elif is_consent:
            c.drawCentredString(width / 2, height - top_margin - 12, "DATA CONSENT AGREEMENT")
        else:
            c.drawCentredString(width / 2, height - top_margin - 12, "DATA AGREEMENT")

    def begin_page():
        nonlocal page_idx
        draw_header()  # watermark intentionally removed
        if page_idx == 0:
            draw_doc_title()

    def end_page():
        nonlocal page_idx
        draw_footer_rule()
        c.showPage()
        page_idx += 1

    # -------- 3) Text block renderer (ToC caption bold, items normal; body 'Preamble' bold) --------
    def _draw_text_block(lines_to_draw, start_y, is_first_page=False, *, enable_signatures=False):
        """
        - Uses body font with leading=1.5 (set outside).
        - 'Table of Contents' CAPTION is bold; all ToC items are NOT bold.
        - Inserts one blank line AFTER the ToC block.
        - Body heading 'Preamble' (any case; optional '.' or ':') is bold like H1.
        - Extra blank line BEFORE and AFTER headings (controlled by heading_*_gap_lines).
        """
        import re

        y = start_y
        txt = c.beginText(x=left_margin, y=y)
        txt.setFont(FONT_BODY, size_body)
        txt.setLeading(leading)

        def write_line(line, font=FONT_BODY, size=size_body):
            txt.setFont(font, size)
            txt.textLine(line)

        signature_ctx = {
            "next_party_index": 0,
            "current_party": None,
            "waiting_sig_dots": False,
            "waiting_date_label": False,
            "waiting_date_dots": False,
        } if enable_signatures else None
        signature_layout = {
            "img_x_extra": 25,
            "img_vertical_bias": 0.5,
            "img_width": 230,
            "img_max_height": 90,
            "date_x_extra": 20,
            "date_y_offset": -2,
        } if enable_signatures else None

        def _reset_signature_flow():
            if signature_ctx is None:
                return
            signature_ctx["current_party"] = None
            signature_ctx["waiting_sig_dots"] = False
            signature_ctx["waiting_date_label"] = False
            signature_ctx["waiting_date_dots"] = False

        def _flush_and_resume(resume_y):
            nonlocal txt, wrote_any_on_page
            c.drawText(txt)
            txt = c.beginText(x=left_margin, y=resume_y)
            txt.setLeading(leading)
            txt.setFont(FONT_BODY, size_body)
            wrote_any_on_page = True

        def _overlay_signature(party, baseline_y, resume_y, indent_width):
            if not enable_signatures:
                return
            img = signature_images.get(party)
            if not img:
                return
            _flush_and_resume(resume_y)
            try:
                img_w, img_h = img.getSize()
            except Exception:
                img_w, img_h = (400, 160)
            target_w = signature_layout["img_width"]
            aspect = (img_h / img_w) if img_w else 0
            target_h = min(signature_layout["img_max_height"], target_w * aspect) if aspect else 50
            img_x = left_margin + indent_width + signature_layout["img_x_extra"]
            img_y = baseline_y - (target_h * signature_layout["img_vertical_bias"])
            c.drawImage(
                img,
                img_x,
                img_y,
                width=target_w,
                height=target_h,
                preserveAspectRatio=True,
                mask='auto'
            )

        def _overlay_signature_date(party, baseline_y, resume_y, indent_width):
            if not enable_signatures:
                return
            date_val = signature_dates.get(party)
            if not date_val:
                return
            _flush_and_resume(resume_y)
            c.setFont(FONT_BODY, 10)
            date_x = left_margin + indent_width + signature_layout["date_x_extra"]
            date_y = baseline_y + signature_layout["date_y_offset"]
            c.drawString(date_x, date_y, str(date_val))

        # Headings (outside ToC)
        pat_h1 = re.compile(r"^\s*\d+\.\s.+$")  # 1., 2., ...
        pat_h2 = re.compile(r"^\s*(A\d+\.\s.+|\d+\.\d+(\.\d+)?\s.+)$")  # A1., 4.1., 4.1.1
        pat_bullet = re.compile(r"^\s*•\s+")
        pat_warn = re.compile(r"^\s*The definition does not exist", re.I)
        preamble_body_re = re.compile(r"^\s*Preamble\s*[:.]?\s*$", re.I)

        # ToC detection
        toc_item_re = re.compile(r"^\s*((\d+(\.\d+)*)|A\d+)(\.\s|\s)")
        TOC_PREAMBLE = "preamble"  # ToC line 'Preamble'

        toc_open = False
        just_left_toc = False
        wrote_any_on_page = False

        for raw in lines_to_draw:
            if raw is None:
                raw = ""
            raw = raw.rstrip("\r")
            indent = len(raw) - len(raw.lstrip(" "))
            indent_str = " " * indent
            line = raw.lstrip(" ")
            line_clean = line.strip()

            # Start ToC on caption
            if line.strip().lower() == "table of contents":
                # Ensure enough room; if not, new page
                if txt.getY() < bottom_margin + leading:
                    c.drawText(txt);
                    end_page();
                    begin_page()
                    txt = c.beginText(x=left_margin, y=height - top_margin)
                    txt.setLeading(leading)
                    wrote_any_on_page = False
                # Bold caption
                write_line("Table of Contents", font=FONT_BOLD, size=size_body)
                wrote_any_on_page = True
                toc_open = True
                continue

            # If currently in ToC, keep writing items in normal weight until a non-ToC line appears
            if toc_open:
                # Keep blank lines inside ToC
                if line.strip() == "":
                    if txt.getY() < bottom_margin + leading:
                        c.drawText(txt);
                        end_page();
                        begin_page()
                        txt = c.beginText(x=left_margin, y=height - top_margin)
                        txt.setLeading(leading)
                        wrote_any_on_page = False
                    write_line("")
                    wrote_any_on_page = True
                    continue

                # Accept numeric items or 'Preamble' (any case) as ToC items
                if toc_item_re.match(line) or line.strip().lower() == TOC_PREAMBLE:
                    font_name, font_size = FONT_BODY, size_body
                    space_w = pdfmetrics.stringWidth(indent_str, font_name, font_size)
                    available = max_width - space_w
                    chunks = [indent_str + ln for ln in simpleSplit(line, font_name, font_size, available)]
                    for chunk in chunks:
                        if txt.getY() < bottom_margin + leading:
                            c.drawText(txt);
                            end_page();
                            begin_page()
                            txt = c.beginText(x=left_margin, y=height - top_margin)
                            txt.setLeading(leading)
                            wrote_any_on_page = False
                        write_line(chunk, font=font_name, size=font_size)
                        wrote_any_on_page = True
                    continue
                else:
                    # ToC ended; insert a blank line before the next content
                    toc_open = False
                    just_left_toc = True

            # Insert a blank line AFTER ToC once
            if just_left_toc:
                if txt.getY() < bottom_margin + leading:
                    c.drawText(txt);
                    end_page();
                    begin_page()
                    txt = c.beginText(x=left_margin, y=height - top_margin)
                    txt.setLeading(leading)
                    wrote_any_on_page = False
                write_line("")
                wrote_any_on_page = True
                just_left_toc = False

            # Preserve explicit blank lines in body
            if line.strip() == "":
                if txt.getY() < bottom_margin + leading:
                    c.drawText(txt);
                    end_page();
                    begin_page()
                    txt = c.beginText(x=left_margin, y=height - top_margin)
                    txt.setLeading(leading)
                    wrote_any_on_page = False
                write_line("")
                wrote_any_on_page = True
                continue

            # Choose style for body
            font_name, font_size = FONT_BODY, size_body
            is_heading = False
            signature_mode = enable_signatures and signature_ctx is not None and not toc_open

            # Body 'Preamble' heading as bold H1
            if preamble_body_re.match(line):
                font_name, font_size, is_heading = FONT_BOLD, size_h1, True
            elif pat_h2.match(line):
                font_name, font_size, is_heading = FONT_BOLD, size_h2, True
            elif pat_h1.match(line):
                font_name, font_size, is_heading = FONT_BOLD, size_h1, True
            elif pat_bullet.match(line):
                font_name, font_size = FONT_BODY, size_body
            elif pat_warn.match(line):
                font_name, font_size = FONT_ITAL, size_body

            if signature_mode and line_clean:
                upper_clean = line_clean.upper()
                lower_clean = line_clean.lower()
                if upper_clean.startswith("SIGNED BY"):
                    party = "provider" if signature_ctx["next_party_index"] == 0 else "consumer"
                    signature_ctx["next_party_index"] = min(signature_ctx["next_party_index"] + 1, 2)
                    signature_ctx["current_party"] = party
                    signature_ctx["waiting_sig_dots"] = False
                    signature_ctx["waiting_date_label"] = False
                    signature_ctx["waiting_date_dots"] = False
                elif signature_ctx["current_party"] and lower_clean.startswith("signature") and not signature_ctx["waiting_sig_dots"]:
                    signature_ctx["waiting_sig_dots"] = True
                elif signature_ctx["current_party"] and signature_ctx["waiting_date_label"] and lower_clean.startswith("date"):
                    signature_ctx["waiting_date_label"] = False
                    signature_ctx["waiting_date_dots"] = True

            # Pre-gap for headings (if we've already written something on the page)
            if is_heading and wrote_any_on_page:
                for _ in range(heading_pre_gap_lines):
                    if txt.getY() < bottom_margin + leading:
                        c.drawText(txt);
                        end_page();
                        begin_page()
                        txt = c.beginText(x=left_margin, y=height - top_margin)
                        txt.setLeading(leading)
                        wrote_any_on_page = False
                    write_line("")

            # Wrap with indent
            space_w = pdfmetrics.stringWidth(indent_str, font_name, font_size)
            available = max_width - space_w
            chunks = [indent_str + ln for ln in simpleSplit(line, font_name, font_size, available)]
            is_dotted_line = bool(line) and bool(re.fullmatch(r"[.\s]+", line))
            line_baseline = txt.getY()
            indent_width = pdfmetrics.stringWidth(indent_str, FONT_BODY, size_body)

            for chunk in chunks:
                if txt.getY() < bottom_margin + leading:
                    c.drawText(txt);
                    end_page();
                    begin_page()
                    txt = c.beginText(x=left_margin, y=height - top_margin)
                    txt.setLeading(leading)
                    txt.setFont(font_name, font_size)
                    wrote_any_on_page = False
                write_line(chunk, font=font_name, size=font_size)
                wrote_any_on_page = True

            if signature_mode and signature_ctx["current_party"]:
                if signature_ctx["waiting_sig_dots"] and is_dotted_line:
                    signature_ctx["waiting_sig_dots"] = False
                    signature_ctx["waiting_date_label"] = True
                    resume_y = txt.getY()
                    _overlay_signature(signature_ctx["current_party"], line_baseline, resume_y, indent_width)
                elif signature_ctx["waiting_date_dots"] and is_dotted_line:
                    signature_ctx["waiting_date_dots"] = False
                    resume_y = txt.getY()
                    _overlay_signature_date(signature_ctx["current_party"], line_baseline, resume_y, indent_width)
                    _reset_signature_flow()

            # Post-gap for headings
            if is_heading:
                for _ in range(heading_post_gap_lines):
                    if txt.getY() < bottom_margin + leading:
                        c.drawText(txt);
                        end_page();
                        begin_page()
                        txt = c.beginText(x=left_margin, y=height - top_margin)
                        txt.setLeading(leading)
                        wrote_any_on_page = False
                    write_line("")
                    wrote_any_on_page = True

        c.drawText(txt)
        return txt.getY()

    # -------- 4) Render main body --------
    begin_page()
    first_page_start_y = (height - top_margin - 36) if page_idx == 0 else (height - top_margin)
    last_y = _draw_text_block(
        body_lines,
        first_page_start_y,
        is_first_page=(page_idx == 0),
        enable_signatures=True,
    )

    # -------- 5) Appendix --------
    if appendix_lines:
        end_page();
        begin_page()
        _draw_text_block(appendix_lines, height - top_margin, enable_signatures=False)

    # Footer rule on last page (page number added at save-time)
    draw_footer_rule()

    # -------- 6) Finalize & save --------
    c.save()
    buf.seek(0)

    os.makedirs('./download_contract', exist_ok=True)
    safe_cid = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(contract_id))
    safe_nid = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(negotiation_id))
    out_path = f"./download_contract/contract_id-{safe_cid}_negotiation_id-{safe_nid}.pdf"
    with open(out_path, "wb") as fp:
        fp.write(buf.getvalue())

    return buf


def create_odrl_decription(odrl_dic, definitions):
    odrl_policy = odrl_dic
    rule_summary = {
        "permission": extract_rules(
            odrl_policy.get("permission", []),
            rule_key="permission",
            definitions=definitions,
        ),
        "prohibition": extract_rules(
            odrl_policy.get("prohibition", []),
            rule_key="prohibition",
            definitions=definitions,
        ),
        "obligation": extract_rules(
            odrl_policy.get("obligation", []),
            rule_key="obligation",
            definitions=definitions,
        ),
        "duty": extract_rules(
            odrl_policy.get("duty", []),
            rule_key="duty",
            definitions=definitions,
        ),
    }

    # print("\n\n\nODRL Summary: ", rule_summary)

    # !!
    # print("before the gpt", rule_summary)
    # rule_summary = refinements_odrl_des(rule_summary)
    # print("after the gpt", rule_summary)

    return rule_summary


def scrub_definitions(definitions):
    """
    Remove specific GDPR-like terms from a `definitions` dict, case-insensitively.
    Handles UPPER/Title case, extra/multiple spaces, and smart quotes.

    Args:
        definitions: The dictionary of definitions.
        in_place: If True, modify `definitions` in place and return the list of removed keys.
                  If False, return (new_dict, removed_keys) without mutating the input.
    Returns:
        If in_place=True: list[str] of original keys removed.
        If in_place=False: (new_dict: dict, removed_keys: list[str])
    """
    import re
    import unicodedata

    # Terms to remove (do not add quotes here; normalization handles them in keys)
    terms_to_remove = {
        "personal data",
        "data subject",
        "processing",
        "data controller",
        "data processor",
        "third party",
        "consent",
        "data breach",
        "security incident",
        "supervisory authority",
    }

    def _norm(s: str) -> str:
        # Unicode normalize, collapse spaces, strip ends, and casefold
        s = unicodedata.normalize("NFKC", str(s))
        s = re.sub(r"\s+", " ", s).strip()
        return s.casefold()

    targets = {_norm(t) for t in terms_to_remove}

    new_dict, removed = {}, []
    for k, v in definitions.items():
        if _norm(k) in targets:
            removed.append(k)
        else:
            new_dict[k] = v
    # print("removed: ", removed)
    return new_dict


def extract_rules(rule_list, rule_key, definitions: dict = None):
    """
    Generate human-readable sentences for ODRL rules.
    - Purpose is taken from rule['purpose'] (string or {source, refinement}) and
      any explicit 'purpose' constraint is removed from the rule-level clause.
    - Constraints are verbalized into a cleaner clause:
        ", and it applies only if the <left> <op> <right> and ..."
    - Refinements on action/assignee/target/purpose are supported.
    """
    if definitions is None:
        definitions = {}

    # Map rule key to modal verb
    modal_map = {
        "permission": " is permitted by ",
        "obligation": " is obliged to ",
        "duty": " is duty-bound to ",
        "prohibition": " is prohibited by "
    }
    modal_verb = modal_map.get(rule_key, "is responsible for")

    def is_uri(x: str) -> bool:
        return isinstance(x, str) and (x.startswith("http://") or x.startswith("https://") or x.startswith("urn:"))

    def get_name(uri: str) -> str:
        """Extract local name from a URI (after # or last /) and split CamelCase."""
        if uri is None:
            return ""
        if not isinstance(uri, str):
            uri = str(uri)
        name = uri.rsplit('#', 1)[-1] if '#' in uri else uri.rstrip('/').rsplit('/', 1)[-1]
        label = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', name)
        return label

    def humanize_value(v):
        """Return a readable value: if URI use local name; else return as-is."""
        if is_uri(v):
            return get_name(v)
        return str(v)

    def norm_left(left: str) -> str:
        """Tidy common leftOperand labels."""
        key = get_name(left).lower()
        # Optional pretty-mapping for nicer output
        pretties = {
            "datetime": "date/time",
            "language": "language",
            "event": "event",
            "purpose": "purpose"
        }
        return pretties.get(key, key)

    def norm_op(op: str) -> str:
        """Normalise operator URI/code to a human phrase."""
        if not op:
            return ""
        key = op.rsplit('#', 1)[-1].rsplit('/', 1)[-1]
        relations = {
            "eq": "is",
            "neq": "is not",
            "lt": "is less than",
            "gt": "is greater than",
            "gteq": "is greater than or equal to",
            "lteq": "is less than or equal to",
            "hasPart": "has part",
            "isA": "is",
            "isAllOf": "is all of",
            "isAnyOf": "is any of",
            "isNoneOf": "is none of",
            "isPartOf": "is part of",
        }
        return relations.get(key, key)

    def fmt_triplet(left, op, right) -> str:
        """Format a single condition/refinement triplet; returns '' if ill-formed."""
        if not op or left is None or right is None:
            return ""
        l = norm_left(left)
        o = norm_op(op)
        r = humanize_value(right)
        # Add article "the" before common attributes for smoother reading
        if l and not l.startswith(("a ", "an ", "the ")):
            l = f"the {l}"
        return f"{l} {o} {r}"

    def flatten_constraints(items):
        """
        Accepts rule['constraint'] list that may contain:
          - simple dicts with leftOperand/operator/rightOperand
          - dicts with 'and': [ ... ] (possibly nested)
          - dicts with 'or':  [ ... ] (possibly nested)
        Returns a flat list of simple dicts and preserves 'or' groups as sublists.
        """
        if not items:
            return []

        flat = []

        def _walk(obj):
            if isinstance(obj, dict):
                if all(k in obj for k in ("leftOperand", "operator", "rightOperand")):
                    flat.append({
                        "leftOperand": obj["leftOperand"],
                        "operator": obj["operator"],
                        "rightOperand": obj["rightOperand"],
                    })
                else:
                    if "and" in obj and isinstance(obj["and"], list):
                        for x in obj["and"]:
                            _walk(x)
                    if "or" in obj and isinstance(obj["or"], list):
                        # keep 'or' as a grouped list of formatted triplets
                        group = []
                        for x in obj["or"]:
                            if isinstance(x, dict) and all(k in x for k in ("leftOperand", "operator", "rightOperand")):
                                group.append(x)
                            else:
                                # Recurse any nested structure inside 'or'
                                sub_before = len(flat)
                                _walk(x)
                                # Pull newly added at tail into this group if they are simple
                                new_simple = flat[sub_before:]
                                del flat[sub_before:]
                                group.extend(new_simple)
                        if group:
                            flat.append(group)  # mark as OR group
            elif isinstance(obj, list):
                for x in obj:
                    _walk(x)

        _walk(items)
        return flat

    def get_source_and_refinements(x):
        """
        Handles string or object with 'source' and optional 'refinement' list.
        Returns (source_uri:str, refinements_formatted_list:list[str]).
        """
        if isinstance(x, str) or x is None:
            return x, []
        source = x.get("source") or x.get("@id") or x.get("id")
        refs = x.get("refinement") or []
        formatted = []
        for r in refs if isinstance(refs, list) else []:
            t = fmt_triplet(r.get("leftOperand"), r.get("operator"), r.get("rightOperand"))
            if t:
                formatted.append(t)
        return source, formatted

    def choose_purpose(rule, constraints_flat):
        """
        Prefer top-level purpose; if absent, infer from the first constraint whose leftOperand is 'purpose'.
        When the purpose is expressed as a constraint, also collect related refinements (e.g. purposeEnhancedProperty)
        and mark all purpose-related constraints so they can be removed from the general constraint clause.
        Returns (purpose_url, purpose_refinements, skip_ids:set[int])
        """
        purpose_field = rule.get("purpose")
        purpose_url = None
        purpose_refinements = []
        skip_ids = set()

        if isinstance(purpose_field, str):
            purpose_url = purpose_field
        elif isinstance(purpose_field, dict):
            purpose_url, purpose_refinements = get_source_and_refinements(purpose_field)

        def _handle_constraint(obj):
            nonlocal purpose_url, purpose_refinements
            if not isinstance(obj, dict):
                return
            left = str(obj.get("leftOperand") or "")
            left_key = left.rsplit('#', 1)[-1].rsplit('/', 1)[-1].lower()
            if not left_key:
                return
            if left_key == "purpose":
                if not purpose_url:
                    purpose_url = obj.get("rightOperand")
                else:
                    ref = fmt_triplet(obj.get("leftOperand"), obj.get("operator"), obj.get("rightOperand"))
                    if ref:
                        purpose_refinements.append(ref)
                skip_ids.add(id(obj))
            elif "purpose" in left_key:
                ref = fmt_triplet(obj.get("leftOperand"), obj.get("operator"), obj.get("rightOperand"))
                if ref:
                    purpose_refinements.append(ref)
                skip_ids.add(id(obj))

        for entry in constraints_flat or []:
            if isinstance(entry, list):
                for item in entry:
                    _handle_constraint(item)
            else:
                _handle_constraint(entry)

        return purpose_url, purpose_refinements, skip_ids

    def build_constraint_clause(constraints_flat, skip_ids):
        """
        Create a clean English clause from constraints.
        - Removes constraints whose ids are present in skip_ids (purpose and related refinements).
        - Supports simple 'and' lists and grouped 'or' lists.
        """
        parts = []

        for c in constraints_flat or []:
            if isinstance(c, list):  # OR group
                or_bits = []
                for x in c:
                    if id(x) in skip_ids:
                        continue
                    or_bits.append(fmt_triplet(x.get("leftOperand"), x.get("operator"), x.get("rightOperand")))
                or_bits = [b for b in or_bits if b]
                if or_bits:
                    parts.append("(" + " or ".join(or_bits) + ")")
            else:
                if id(c) in skip_ids:
                    continue
                t = fmt_triplet(c.get("leftOperand"), c.get("operator"), c.get("rightOperand"))
                if t:
                    parts.append(t)

        if not parts:
            return ""
        return ". This clause shall apply only under the following constraints: " + " and ".join(parts)

    # verb_list = ['exercise', 'invoke', 'apply', 'carry out', 'perform']
    # exclusively_list = ['solely', 'only', 'specifically', 'exclusively', 'strictly']

    verb_list = ['apply']
    exclusively_list = ['specifically']

    sentences = []
    for rule in rule_list or []:
        # Extract action/assignee/target
        action_src, action_refs = get_source_and_refinements(rule.get("action"))
        assignee_src, actor_refs = get_source_and_refinements(rule.get("assignee"))
        target_src, target_refs = get_source_and_refinements(rule.get("target"))

        constraints_flat = flatten_constraints(rule.get("constraint", []))

        # Purpose extraction & removal from constraints if it appeared there
        purpose_url, purpose_refs, skip_ids = choose_purpose(rule, constraints_flat)

        assignee_name, assignee_def = describe_entity(assignee_src)
        action_name, action_def = describe_entity(action_src)
        if purpose_url:
            purpose_name, purpose_def = describe_entity(purpose_url)
        else:
            purpose_name = ""
            purpose_def = ""
        target_name, target_def = describe_entity(target_src)

        # Local names (for prose)

        # print("\n\n----------Current Running---------------")
        # print("\n----------refs:---------------\n")
        # print("action_ref: ", action_refs)
        # print("actor_ref: ", actor_refs)
        # print("target_ref: ", target_refs)
        # print("purpose_ref: ", purpose_refs)
        #
        # print("\n----------urls:---------------\n")
        # print("action_src: ", action_src)
        # print("assignee_src: ", assignee_src)
        # print("target_src: ", target_src)
        # print("purpose_url: ", purpose_url)
        #
        # print("----------lable:---------------\n")
        # print("action_name: ", action_name)
        # print("assignee_name: ", assignee_name)
        # print("target_name: ", target_name)
        # print("purpose_name: ", purpose_name)
        #
        # print("----------definition:---------------\n")
        # print("action_def: ", action_def)
        # print("assignee_def: ", assignee_def)
        # print("target_def: ", target_def)
        # print("purpose_def: ", purpose_def)

        # Update definitions dict
        if assignee_name and assignee_def:
            definitions[str(assignee_name)] = (f"{assignee_def} (Please refer to {assignee_src} for more details.)\n"
                                               if assignee_def else
                                               f"The definition  does not exist in  {assignee_src}. Please insert the definition.\n")
        if action_name and action_def:
            definitions[str(action_name)] = (f"{action_def} (Please refer to {action_src} for more details.)\n"
                                             if action_def else
                                             f"The definition does not exist in  {action_src}. Please insert the definition.\n")

        if purpose_name and purpose_def:
            definitions[str(purpose_name)] = (f"{purpose_def} (Please refer to {purpose_url} for more details.)\n"
                                              if purpose_def else
                                              f"The definition does not exist in {purpose_url}. Please insert the definition.\n")
        if target_name and target_def:
            definitions[str(target_name)] = (f"{target_def} (Please refer to {target_src} for more details.)\n"
                                             if target_def else
                                             f"The definition does not exist in {target_src}. Please insert the definition.\n")

        # Lowercase for sentence body
        assignee_name = assignee_name.lower()
        action_name = action_name.lower()
        target_name = target_name.lower()
        purpose_name = purpose_name.lower()

        # rule_key_index =  ("-").join([rule_key,assignee_name,action_name,target_name,purpose_name])+ "###"
        rule_key_index = ""

        # Build refinement phrases
        def join_refs(refs, prefix):
            refs = [r for r in refs if r]
            return (f" {prefix} " + " and ".join(refs)) if refs else ""

        actionrefinements = join_refs(action_refs, "with")
        actorrefinements = join_refs(actor_refs, "who")
        targetrefinements = join_refs(target_refs, "with")
        purposerefinements = join_refs(purpose_refs, "refined such that")

        # Build improved constraint clause
        constraint_clause = build_constraint_clause(constraints_flat, skip_ids)

        sentence = ""
        guidance = ""

        if rule_key == "permission":
            sentence = (
                f"{rule_key_index}Party B{(', ' + actorrefinements + ',') if actorrefinements else ''} {modal_verb}Party A "
                f"to {random.choice(verb_list)} the {action_name} action{actionrefinements}, on the {target_name} dataset{targetrefinements}, "
                f"{random.choice(exclusively_list)} for the purpose of {purpose_name}{(', ' + purposerefinements) if purposerefinements else ''}"
                f"{constraint_clause}."
            )
            guidance = (
                f" Party B shall ensure all {action_name} methods comply with applicable data-protection standards "
                f"and shall retain documentation of the techniques applied."
            )
        elif rule_key == "prohibition":
            sentence = (
                f"{rule_key_index}Party B{(', ' + actorrefinements + ',') if actorrefinements else ''} {modal_verb}Party A "
                f"to {random.choice(verb_list)} the {action_name} action{actionrefinements} on the {target_name} dataset{targetrefinements}, "
                f"{random.choice(exclusively_list)} for the purpose of {purpose_name}{(', ' + purposerefinements) if purposerefinements else ''}"
                f"{constraint_clause}."
            )
            guidance = (
                f" Party B must enforce this prohibition in all agreements with its agents "
                f"and immediately report any attempted contravention to Party A."
            )
        elif rule_key == "obligation":
            sentence = (
                f"{rule_key_index}Party B{(', ' + actorrefinements + ',') if actorrefinements else ''} {modal_verb}Party A "
                f"to {random.choice(verb_list)} the {action_name} action{actionrefinements} on the {target_name} dataset{targetrefinements}, "
                f"{random.choice(exclusively_list)} for the purpose of {purpose_name}{(', ' + purposerefinements) if purposerefinements else ''}"
                f"{constraint_clause}."
            )
            guidance = (
                f" Party B shall follow all relevant standards and ensure proper execution of the {action_name} action."
            )
        elif rule_key == "duty":
            sentence = (
                f"{rule_key_index}Party B{(', ' + actorrefinements + ',') if actorrefinements else ''} {modal_verb}Party A "
                f"to {random.choice(verb_list)} the {action_name} action{actionrefinements} on the {target_name} dataset{targetrefinements}, "
                f"{random.choice(exclusively_list)} for the purpose of {purpose_name}{(' ' + purposerefinements) if purposerefinements else ''}"
                f"{constraint_clause}."
            )
            guidance = (
                f" Party B shall confirm execution of the {action_name} action by providing certification or proof upon request."
            )
        else:
            sentence = ""
            guidance = ""

        if sentence:
            sentences.append(sentence + guidance)

    return sentences


def describe_entity(url):
    if not url:
        return "", ""

    info = odrl_dpv_obj.parse_url(url)

    if info["definition"]:

        if info["note"]:

            des = info["definition"] + " " + info["note"]
        else:
            des = info["definition"]

        return info["prefLabel"], des

    else:
        return info["prefLabel"], ""


# def describe_entity(url):
#     keyword = extract_keyword(url)
#     description = keyword_lookup.get(keyword)
#
#     if description:
#         type_ = description.get("type", "Unknown")
#         definition = description.get("definition")
#         note = description.get("note")
#
#         label = description.get("label", description.get("prefLabel", keyword))
#
#         sentence = ""
#         if definition:
#             sentence += f"{definition}"
#         if note:
#             sentence += f". {note}\n"
#         return sentence.strip()
#
#     else:
#         # return "Please refer to: " + url  # fallback if not found
#         return ""


def extract_keyword(uri):
    parsed = urlparse(uri)
    if parsed.fragment:
        return parsed.fragment
    path = parsed.path.rstrip("/").split("/")
    last = path[-1] if path else ""

    res = re.compile(r"[0-9]+?")
    if bool(re.match(res, last)):
        print("Warning: Found a numeric last part in the URL, using full URL instead.")
        print(f"Original URL: {uri}")
        return uri
    return last


import validate
from odrl_format_conversion import custom_convert_odrl_policy, filter_dicts_with_none_values, \
    convert_list_to_odrl_jsonld_no_user


def odrl_formate_convert(request_body):
    if not isinstance(request_body, dict):
        raise TypeError(f"request_body must be dict, got {type(request_body).__name__}")

    body = deepcopy(request_body)

    if "odrl" not in body:
        raise ValueError("Missing 'odrl' in request body.")

    cactus_format = body["odrl"]

    if cactus_format is None:
        raise ValueError("'odrl' must not be null.")

    # Accept stringified JSON
    if isinstance(cactus_format, str):
        try:
            cactus_format = json.loads(cactus_format)
        except json.JSONDecodeError as e:
            raise ValueError(f"'odrl' is a string but not valid JSON: {e}") from e

    if not isinstance(cactus_format, dict):
        raise TypeError(f"'odrl' must be a dict (or JSON string), got {type(cactus_format).__name__}")

    # --- Validate (be flexible about validator's return shape) ---
    try:
        ok = validate.diagnose_ODRL(cactus_format)
        print("\n\n ok:", ok)
    except Exception as e:
        raise RuntimeError(f"ODRL validator raised an exception: {e}") from e

    if not ok:
        raise ValueError(f"ODRL validation failed")

    # --- Convert -> Filter -> Reformat ---
    try:
        custom_format = custom_convert_odrl_policy(cactus_format)
    except Exception as e:
        raise RuntimeError(f"custom_convert_odrl_policy() failed: {e}") from e

    try:
        filtered_data = filter_dicts_with_none_values(custom_format)
    except Exception as e:
        raise RuntimeError(f"filter_dicts_with_none_values() failed: {e}") from e

    try:
        new_odrl_format = convert_list_to_odrl_jsonld_no_user(filtered_data)
    except Exception as e:
        raise RuntimeError(f"convert_list_to_odrl_jsonld_no_user() failed: {e}") from e

    if not isinstance(new_odrl_format, dict):
        raise TypeError(
            f"Converted ODRL must be a dict, got {type(new_odrl_format).__name__}"
        )

    body["odrl"] = new_odrl_format
    return body


# ---------- Turtle Conversion Utilities ----------

def _slugify_for_uri(value: Optional[str], fallback: str) -> str:
    if not value or not isinstance(value, str):
        return fallback
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", value.strip()).strip("-").lower()
    return cleaned or fallback


def contract_to_turtle(contract: Dict[str, Any], include_contract_node: bool = False) -> str:
    if not isinstance(contract, dict):
        raise ValueError("Contract payload must be a dictionary")

    contract_id = contract.get("contractid") or contract.get("_id")
    if not contract_id:
        raise ValueError("Contract payload is missing 'contractid'")

    base_iri = "http://upcast-project.eu"

    upcast_ns = Namespace("https://www.upcast-project.eu/upcast-vocab/1.0/")
    idsa_ns = Namespace("https://w3id.org/idsa/core/")
    odrl_ns = Namespace("http://www.w3.org/ns/odrl/2/")
    wmo_ns = Namespace("http://www.ict-abovo.eu/ontologies/WorkflowModel#")
    schema_ns = Namespace("http://schema.org/")
    dpv_ns = Namespace("https://w3id.org/dpv/owl#")

    graph = Graph()
    graph.bind("upcast", upcast_ns)
    graph.bind("idsa-core", idsa_ns)
    graph.bind("dcat", DCAT)
    graph.bind("dct", DCTERMS)
    graph.bind("foaf", FOAF)
    graph.bind("odrl", odrl_ns)
    graph.bind("xsd", XSD)
    graph.bind("wmo", wmo_ns)
    graph.bind("schema", schema_ns)
    graph.bind("dpv", dpv_ns)

    contract_uri = URIRef(f"{base_iri}/contract/{contract_id}")
    graph.add((contract_uri, RDF.type, upcast_ns.Contract))
    graph.add((contract_uri, RDF.type, idsa_ns.Contract))

    # Contract metadata
    nlp_text = contract.get("nlp")
    if nlp_text:
        graph.add((contract_uri, upcast_ns.hasNLP, Literal(nlp_text)))

    # Operational metadata such as negotiation IDs or validity periods are
    # omitted to match the external reference TTL shared by the partner.

    # Contacts
    contacts = contract.get("contacts") or {}
    for role in ("consumer", "provider"):
        party = contacts.get(role) or {}
        if not party:
            continue
        slug = _slugify_for_uri(party.get("organization") or party.get("name"), f"{role}-{contract_id}")
        party_uri = URIRef(f"{base_iri}/{role}/{slug}")
        graph.add((party_uri, RDF.type, FOAF.Agent))
        if party.get("organization"):
            graph.add((party_uri, RDF.type, FOAF.Organization))
            graph.add((party_uri, FOAF.name, Literal(party["organization"])))
        elif party.get("name"):
            graph.add((party_uri, FOAF.name, Literal(party["name"])))
        if party.get("username_email"):
            email = party["username_email"].strip()
            graph.add((party_uri, FOAF.mbox, URIRef(f"mailto:{email}")))
        if party.get("phone"):
            phone = re.sub(r"\s+", "", party["phone"])
            graph.add((party_uri, FOAF.phone, URIRef(f"tel:{phone}")))
        if party.get("address"):
            graph.add((party_uri, schema_ns.address, Literal(party["address"])))
        if party.get("position_title"):
            graph.add((party_uri, schema_ns.jobTitle, Literal(party["position_title"])))
        party_predicate = idsa_ns.Consumer if role == "consumer" else idsa_ns.Provider
        graph.add((contract_uri, party_predicate, party_uri))

    # Dataset description
    resource_desc = contract.get("resource_description") or {}
    dataset_slug = _slugify_for_uri(resource_desc.get("title"), f"dataset-{contract_id}")
    dataset_uri = URIRef(f"{base_iri}/dataset/{dataset_slug}")
    graph.add((dataset_uri, RDF.type, DCAT.Dataset))
    graph.add((contract_uri, upcast_ns.refersTo, dataset_uri))

    if resource_desc.get("title"):
        graph.add((dataset_uri, DCTERMS.title, Literal(resource_desc["title"])))
    if resource_desc.get("description"):
        graph.add((dataset_uri, DCTERMS.description, Literal(resource_desc["description"])))
    if resource_desc.get("tags"):
        for tag in re.split(r"[,;]", resource_desc["tags"]):
            tag_clean = tag.strip()
            if tag_clean:
                graph.add((dataset_uri, DCAT.keyword, Literal(tag_clean)))
    if resource_desc.get("type_of_data"):
        graph.add((dataset_uri, DCTERMS.type, Literal(resource_desc["type_of_data"])))
    if resource_desc.get("uri"):
        graph.add((dataset_uri, DCTERMS.identifier, Literal(resource_desc["uri"])))
    if resource_desc.get("policy_url"):
        graph.add((dataset_uri, DCTERMS.source, URIRef(resource_desc["policy_url"])))

    price_value = resource_desc.get("price")
    if price_value not in (None, ""):
        decimal_price = None
        try:
            decimal_price = Decimal(str(price_value))
        except Exception:
            decimal_price = None
        if decimal_price is not None:
            graph.add((dataset_uri, upcast_ns.price, Literal(decimal_price, datatype=XSD.decimal)))
        else:
            graph.add((dataset_uri, upcast_ns.price, Literal(str(price_value))))

    price_unit = (
            resource_desc.get("price_unit")
            or resource_desc.get("priceUnit")
            or resource_desc.get("priceCurrency")
            or resource_desc.get("currency")
    )
    if price_unit:
        graph.add((dataset_uri, upcast_ns.priceUnit, Literal(price_unit)))

    distribution_uri = URIRef(f"{str(dataset_uri).rstrip('/')}/distribution/main")
    graph.add((dataset_uri, DCAT.distribution, distribution_uri))
    graph.add((distribution_uri, RDF.type, DCAT.Distribution))

    if resource_desc.get("data_format"):
        graph.add((distribution_uri, DCTERMS.format, Literal(resource_desc["data_format"])))
    if resource_desc.get("data_size"):
        graph.add((distribution_uri, DCAT.byteSize, Literal(resource_desc["data_size"])))
    # Additional distribution pricing is not emitted in the reference TTL.

    # Skip definitions block to align with shared example.

    # Agreement and ODRL rules
    agreement_uri = URIRef(f"http://upcast-project.eu/agreement/{contract_id}")
    graph.add((agreement_uri, RDF.type, odrl_ns.Agreement))
    graph.add((contract_uri, upcast_ns.hasAgreement, agreement_uri))
    odrl_ns_prefix = {
        "odrl": str(odrl_ns),
        "dpv": str(dpv_ns),
        "dcat": str(DCAT),
        "dct": str(DCTERMS),
        "schema": str(schema_ns),
        "wmo": str(wmo_ns),
        "foaf": str(FOAF),
        "upcast": str(upcast_ns),
        "idsa": str(idsa_ns),
        "xsd": str(XSD),
    }

    def _expand_curie(value: str, default_ns=odrl_ns) -> Optional[URIRef]:
        if not value:
            return None
        value = value.strip()
        if value.startswith(("http://", "https://")):
            return URIRef(value)
        if ":" in value:
            prefix, suffix = value.split(":", 1)
            base = odrl_ns_prefix.get(prefix)
            if base:
                return URIRef(f"{base}{suffix}")
        if default_ns is None:
            return None
        cleaned = re.sub(r"\s+", "", value)
        return URIRef(f"{str(default_ns)}{cleaned}")

    def _value_to_term(val: Any):
        if isinstance(val, str):
            uri = _expand_curie(val, default_ns=None)
            return uri if uri else Literal(val)
        if isinstance(val, (int, float)):
            return Literal(val)
        return Literal(json.dumps(val, ensure_ascii=False))

    def _coerce_numeric_literal(raw: Any, datatype=XSD.integer):
        try:
            if isinstance(raw, (int, float)):
                value = int(raw)
            elif isinstance(raw, str):
                match = re.search(r"-?\d+", raw)
                if not match:
                    return None
                value = int(match.group())
            else:
                return None
            return Literal(value, datatype=datatype)
        except Exception:
            return None

    def _coerce_datetime_literal(raw: Any):
        if raw is None:
            return None
        text = str(raw).strip()
        if not text:
            return None
        return Literal(text, datatype=XSD.dateTime)

    def _convert_right_operand(left_uri: Optional[URIRef], raw_value: Any):
        if left_uri == odrl_ns.count:
            coerced = _coerce_numeric_literal(raw_value, datatype=XSD.integer)
            if coerced is not None:
                return coerced
        if left_uri == odrl_ns.dateTime:
            coerced = _coerce_datetime_literal(raw_value)
            if coerced is not None:
                return coerced
        return _value_to_term(raw_value)

    def _add_constraints(parent: URIRef | BNode, items: List[Dict[str, Any]], link_predicate) -> None:
        if not items:
            return
        for constraint in items:
            entries = constraint.get("and", []) if isinstance(constraint, dict) and "and" in constraint else [
                constraint]

            for entry in entries:
                if not isinstance(entry, dict):
                    continue

                node = BNode()
                graph.add((parent, link_predicate, node))

                left_uri = None
                left = entry.get("leftOperand") or entry.get("type")
                if left:
                    left_uri = _expand_curie(str(left))
                    if left_uri:
                        graph.add((node, odrl_ns.leftOperand, left_uri))

                op_uri = None
                operator = entry.get("operator")
                if operator:
                    op_uri = _expand_curie(str(operator))

                if left_uri == odrl_ns.count:
                    allowed_ops = {odrl_ns.eq, odrl_ns.lteq, odrl_ns.gteq, odrl_ns.gt, odrl_ns.lt}
                    if op_uri not in allowed_ops:
                        op_uri = odrl_ns.eq

                if op_uri:
                    graph.add((node, odrl_ns.operator, op_uri))

                values = entry.get("rightOperand")
                if values is None:
                    values = entry.get("value")
                if values is None:
                    continue
                if not isinstance(values, list):
                    values = [values]

                for val in values:
                    term = _convert_right_operand(left_uri, val)
                    graph.add((node, odrl_ns.rightOperand, term))

    def _add_action(parent: URIRef | BNode, action_value: Any) -> None:
        if isinstance(action_value, str):
            action_uri = _expand_curie(action_value)
            graph.add((parent, odrl_ns.action, action_uri or Literal(action_value)))
            return
        if isinstance(action_value, dict):
            node = BNode()
            graph.add((parent, odrl_ns.action, node))
            source = action_value.get("source")
            if source:
                src = _expand_curie(source)
                graph.add((node, odrl_ns.source, src or Literal(source)))
            _add_constraints(node, action_value.get("refinement"), odrl_ns.refinement)

    def _add_party(parent: URIRef | BNode, predicate, party_value: Any) -> None:
        if isinstance(party_value, str):
            target = _expand_curie(party_value)
            graph.add((parent, predicate, target or Literal(party_value)))
            return
        if isinstance(party_value, dict):
            node = BNode()
            graph.add((parent, predicate, node))
            node_type = party_value.get("@type")
            if node_type:
                type_uri = _expand_curie(node_type)
                if type_uri:
                    graph.add((node, RDF.type, type_uri))
            source = party_value.get("source")
            if source:
                src_uri = _expand_curie(source)
                graph.add((node, odrl_ns.source, src_uri or Literal(source)))
            _add_constraints(node, party_value.get("refinement"), odrl_ns.refinement)

    def _populate_rule(rule_node: BNode, rule_payload: Dict[str, Any]) -> None:
        if not isinstance(rule_payload, dict):
            return
        for key, predicate in (("assignee", odrl_ns.assignee), ("assigner", odrl_ns.assigner),
                               ("target", odrl_ns.target)):
            if key in rule_payload:
                _add_party(rule_node, predicate, rule_payload[key])
        if "action" in rule_payload:
            _add_action(rule_node, rule_payload["action"])
        _add_constraints(rule_node, rule_payload.get("constraint"), odrl_ns.constraint)
        _add_constraints(rule_node, rule_payload.get("refinement"), odrl_ns.refinement)

    def _add_rule_collection(collection: List[Dict[str, Any]], predicate, rule_class, holder: URIRef | BNode) -> None:
        if not collection:
            return
        for item in collection:
            if not isinstance(item, dict):
                continue
            node = BNode()
            graph.add((holder, predicate, node))
            graph.add((node, RDF.type, rule_class))
            _populate_rule(node, item)

    odrl_data = contract.get("odrl")
    if isinstance(odrl_data, dict) and odrl_data:
        client_info = contract.get("client_optional_info") or {}
        negotiation_pid = client_info.get("client_pid")
        policy_pid = client_info.get("policy_id")

        manual_policy_iri = None
        if negotiation_pid and policy_pid:
            manual_policy_iri = (
                f"http://upcast-project.eu/policy/negoid-{negotiation_pid}-policyid-{policy_pid}"
            )

        odrl_uid = odrl_data.get("uid")
        policy_identifier = manual_policy_iri or odrl_uid or (
            f"http://upcast-project.eu/policy/agreement/{contract_id}"
        )
        policy_uri = URIRef(policy_identifier)

        policy_type = odrl_data.get("@type")
        type_uri = _expand_curie(policy_type) if policy_type else None
        graph.add((policy_uri, RDF.type, type_uri or odrl_ns.Policy))
        graph.add((policy_uri, RDF.type, odrl_ns.Policy))
        graph.add((policy_uri, odrl_ns.uid, Literal(policy_identifier)))

        _add_rule_collection(odrl_data.get("permission"), odrl_ns.permission, odrl_ns.Permission, policy_uri)
        _add_rule_collection(odrl_data.get("prohibition"), odrl_ns.prohibition, odrl_ns.Prohibition, policy_uri)
        _add_rule_collection(odrl_data.get("obligation"), odrl_ns.obligation, odrl_ns.Obligation, policy_uri)
        _add_rule_collection(odrl_data.get("duty"), odrl_ns.duty, odrl_ns.Duty, policy_uri)

        graph.add((agreement_uri, odrl_ns.hasPolicy, policy_uri))
        graph.add((dataset_uri, odrl_ns.hasPolicy, policy_uri))

    # DPW workflow (JSON-LD)
    dpw_data = contract.get("dpw")
    if isinstance(dpw_data, dict) and dpw_data:
        try:
            dpw_graph = Graph()
            dpw_graph.parse(data=json.dumps(dpw_data), format="json-ld")
            graph += dpw_graph
            for workflow in dpw_graph.subjects(RDF.type, wmo_ns.Workflow):
                graph.add((contract_uri, upcast_ns.hasDPW, workflow))
        except Exception as exc:
            raise RuntimeError(f"Failed to parse DPW JSON-LD: {exc}") from exc

    ttl = graph.serialize(format="turtle")
    if isinstance(ttl, bytes):
        ttl = ttl.decode("utf-8")

    return ttl


# ---------- Contract Search Utilities ----------
TEXT_FIELDS = [
    # existing
    "base_info.resource_description.title",
    "base_info.resource_description.description",
    "base_info.resource_description.tags",
    "base_info.policy_id",
    "base_info.negotiation_id",
    "base_info.consumer_id",
    "base_info.provider_id",
    "nlp",
    "odrl_policy_summary.permission",
    "odrl_policy_summary.obligation",
    "odrl_policy_summary.duty",
    "odrl_policy_summary.Data Sharing Rules",

    # contacts – consumer
    "base_info.contacts.consumer._id",
    "base_info.contacts.consumer.name",
    "base_info.contacts.consumer.organization",
    "base_info.contacts.consumer.distinctive_title",
    "base_info.contacts.consumer.username_email",
    "base_info.contacts.consumer.legal_representative",
    "base_info.contacts.consumer.contact_person",
    "base_info.contacts.consumer.role",
    "base_info.contacts.consumer.phone",
    "base_info.contacts.consumer.incorporation",
    "base_info.contacts.consumer.registered_address",
    "base_info.contacts.consumer.address",
    "base_info.contacts.consumer.vat_no",

    # contacts – provider
    "base_info.contacts.provider._id",
    "base_info.contacts.provider.name",
    "base_info.contacts.provider.organization",
    "base_info.contacts.provider.distinctive_title",
    "base_info.contacts.provider.username_email",
    "base_info.contacts.provider.legal_representative",
    "base_info.contacts.provider.contact_person",
    "base_info.contacts.provider.role",
    "base_info.contacts.provider.phone",
    "base_info.contacts.provider.incorporation",
    "base_info.contacts.provider.registered_address",
    "base_info.contacts.provider.address",
    "base_info.contacts.provider.vat_no",
]


def regex_or_query(q: str):
    """Case-insensitive regex OR across key string fields."""
    rx = re.compile(re.escape(q), re.IGNORECASE)
    return {"$or": [{f: rx} for f in TEXT_FIELDS]}


def _to_bytes(obj) -> bytes:
    """Serialize mp_json to UTF-8 bytes, handling common shapes gracefully."""
    try:
        if isinstance(obj, bytes):
            return obj
        if isinstance(obj, str):
            # assume it's a JSON string already
            return obj.encode("utf-8")
        # Pydantic v2 BaseModel
        if hasattr(obj, "model_dump"):
            return json.dumps(obj.model_dump(), ensure_ascii=False, indent=2).encode("utf-8")
        # Pydantic v1 BaseModel
        if hasattr(obj, "dict"):
            return json.dumps(obj.dict(), ensure_ascii=False, indent=2).encode("utf-8")
        # dict / list / other JSON-serializable
        return json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
    except Exception:
        # Last-resort fallback: string-coerce
        return str(obj).encode("utf-8")
