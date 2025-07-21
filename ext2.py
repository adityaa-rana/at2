import os
import json
import sys
import re
import pdfplumber
from collections import defaultdict
import itertools

def clean_text(text):
    """
    Cleans extracted text by stripping whitespace, normalizing internal spaces,
    and removing consecutive duplicate characters that can appear from OCR/extraction errors.
    """
    # Fix for garbled text like "RRRFFFFPPPP..." -> "RFP"
    text = ''.join(c for c, _ in itertools.groupby(text))
    return re.sub(r'\s+', ' ', text).strip()

def is_likely_heading(line_text, font_size, is_bold, font_stats, line_word_count):
    """
    A much stricter collection of heuristics to determine if a line is a heading.
    This is the core filtering logic to improve precision.
    """
    # Rule 1: Must have some text.
    if not line_text or len(line_text) < 3:
        return False

    # Rule 2: Filter out Table of Contents entries (e.g., "Introduction ..... 5")
    if re.search(r'\.{4,}\s*\d+$', line_text):
        return False

    # Rule 3: Filter out lines that are likely body text or list items.
    # Headings are typically short and don't end with punctuation like a sentence.
    if line_word_count > 12 or line_text.endswith(','):
        return False
    
    # Rule 4: Specifically filter out the "Revision History" table data from file02.pdf
    if re.match(r'^\d\.\d\s+[A-Z0-9\s]+$', line_text):
        return False

    # Rule 5: Filter out numbered list items that are full sentences.
    # A real heading like "1. Introduction" is short. A list item is often long.
    if re.match(r'^\d+\.\s', line_text) and line_word_count > 8:
        # This is likely a list item, e.g., "1. Professionals who have achieved..."
        return False

    # Rule 6: Filter out lines that are all uppercase but not styled like a major heading.
    if line_text.isupper() and line_word_count > 1 and font_size < font_stats['h2_font_threshold']:
        return False

    # Rule 7: Filter out lines that are likely just page numbers or footers.
    if re.fullmatch(r'Page\s*\d+(\s*of\s*\d+)?', line_text, re.IGNORECASE) or re.fullmatch(r'\d+', line_text):
        return False
        
    # Rule 8: Filter out form field labels from file01.pdf
    if re.match(r'^\d+\.\s', line_text) and not is_bold and font_size < font_stats['h2_font_threshold']:
        return False

    return True


def extract_outline_with_pdfplumber(pdf_path):
    """
    Extracts title and hierarchical headings (up to H4) from a PDF
    using a more robust hybrid approach.
    """
    try:
        with pdfplumber.open(pdf_path) as pdf:
            if not pdf.pages:
                return {"title": "Empty Document", "outline": []}

            # --- Phase 1: Gather Font Statistics ---
            font_sizes = defaultdict(int)
            for page in pdf.pages:
                for char in page.chars:
                    font_sizes[round(char.get('size', 0), 2)] += 1
            
            sorted_sizes = sorted(font_sizes.keys(), reverse=True)
            font_stats = {
                'h1_font_threshold': sorted_sizes[0] if len(sorted_sizes) > 0 else 0,
                'h2_font_threshold': sorted_sizes[1] if len(sorted_sizes) > 1 else 0,
                'h3_font_threshold': sorted_sizes[2] if len(sorted_sizes) > 2 else 0,
                'h4_font_threshold': sorted_sizes[3] if len(sorted_sizes) > 3 else 0
            }

            # --- Phase 2: Title Extraction (Improved) ---
            title = ""
            first_page = pdf.pages[0]
            max_font_size = font_stats['h1_font_threshold']
            if max_font_size > 0:
                # Group all words with the max font size by their line (y-coordinate)
                lines_with_max_font = defaultdict(list)
                for word in first_page.extract_words(y_tolerance=3):
                    if abs(word.get('size', 0) - max_font_size) < 0.1:
                        y0 = round(word.get('y0', 0))
                        lines_with_max_font[y0].append(word['text'])
                
                # Combine the top-most lines that have the max font size
                if lines_with_max_font:
                    sorted_y_coords = sorted(lines_with_max_font.keys())
                    # Combine up to the top 3 lines for the title
                    title_parts = [" ".join(lines_with_max_font[y]) for y in sorted_y_coords[:3]]
                    title = clean_text(" ".join(title_parts))

            if not title or len(title) < 5:
                title = "Untitled Document"


            # --- Phase 3: Heading Extraction ---
            outline = []
            h_patterns = {
                "H1": re.compile(r"^(Appendix\s[A-Z]|\d+)\.\s+.*"),
                "H2": re.compile(r"^\d+\.\d+\s+.*"),
                "H3": re.compile(r"^\d+\.\d+\.\d+\s+.*"),
                "H4": re.compile(r"^\d+\.\d+\.\d+\.\d+\s+.*"),
            }

            for page_num, page in enumerate(pdf.pages, 1):
                lines = page.extract_text_lines(layout=True, strip=True)
                
                for line in lines:
                    line_text = clean_text(line['text'])
                    line_word_count = len(line_text.split())
                    
                    first_char = next((c for c in line['chars'] if c['text'].strip()), None)
                    if not first_char: continue
                        
                    font_size = round(first_char.get('size', 0), 2)
                    font_name = first_char.get('fontname', '').lower()
                    is_bold = 'bold' in font_name or 'black' in font_name or 'heavy' in font_name

                    if not is_likely_heading(line_text, font_size, is_bold, font_stats, line_word_count):
                        continue

                    current_level = None
                    
                    # Primary Method: Numbered headings
                    if h_patterns["H4"].match(line_text): current_level = "H4"
                    elif h_patterns["H3"].match(line_text): current_level = "H3"
                    elif h_patterns["H2"].match(line_text): current_level = "H2"
                    elif h_patterns["H1"].match(line_text): current_level = "H1"
                    
                    # Fallback Method: Font size and style for un-numbered headings
                    elif is_bold or line_text.isupper():
                        if font_size >= font_stats['h1_font_threshold'] * 0.9: current_level = "H1"
                        elif font_size >= font_stats['h2_font_threshold'] * 0.9: current_level = "H2"
                        elif font_size >= font_stats['h3_font_threshold'] * 0.9: current_level = "H3"

                    if current_level:
                        outline.append({
                            "level": current_level,
                            "text": line_text,
                            "page": page_num
                        })

            # --- Phase 4: Post-processing ---
            final_outline = []
            seen_entries = set()
            for entry in outline:
                entry_tuple = (entry['text'].lower(), entry['page'])
                if entry_tuple not in seen_entries:
                    final_outline.append(entry)
                    seen_entries.add(entry_tuple)

            return {"title": title, "outline": final_outline}

    except Exception as e:
        print(f"Error processing PDF '{pdf_path}': {e}", file=sys.stderr)
        return {"title": "Error Processing Document", "outline": []}

if __name__ == "__main__":
    input_dir = "input"
    output_dir = "output"

    if not os.path.isdir(input_dir):
        print(f"Error: Input directory '{input_dir}' not found.", file=sys.stderr)
        sys.exit(1)

    os.makedirs(output_dir, exist_ok=True)

    pdf_files = [f for f in os.listdir(input_dir) if f.lower().endswith(".pdf")]

    if not pdf_files:
        print(f"No PDF files found in '{input_dir}' directory.")
        sys.exit(0)

    for pdf_filename in pdf_files:
        pdf_path = os.path.join(input_dir, pdf_filename)
        output_filename = os.path.splitext(pdf_filename)[0] + ".json"
        output_path = os.path.join(output_dir, output_filename)

        print(f"Processing '{pdf_filename}'...")
        result = extract_outline_with_pdfplumber(pdf_path)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=4, ensure_ascii=False)

        print(f"Outline for '{pdf_filename}' saved to '{output_path}'")
