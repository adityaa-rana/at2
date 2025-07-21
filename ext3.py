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
    and removing consecutive duplicate characters from OCR/extraction errors.
    """
    # Fix for garbled text like "R...F...P..." -> "RFP"
    text = ''.join(c for c, _ in itertools.groupby(text))
    return re.sub(r'\s+', ' ', text).strip()

def analyze_document_styles(pdf):
    """
    Analyzes the entire document to find the most common font size (body text)
    and a ranked list of larger font sizes (potential headings).
    """
    font_sizes = defaultdict(int)
    for page in pdf.pages:
        # Use extract_words to get font size info, which is more reliable than chars
        words = page.extract_words(x_tolerance=2, y_tolerance=2)
        for word in words:
            # Round the size to handle minor floating point variations
            size = round(word.get('size', 0))
            font_sizes[size] += 1
    
    if not font_sizes:
        return 0, []

    # Find the most frequent font size, which is almost always the body text.
    body_size = max(font_sizes, key=font_sizes.get)
    
    # Identify heading sizes as those that are significantly larger than the body text.
    # A +1 buffer helps avoid minor font variations being misclassified.
    heading_sizes = sorted([size for size in font_sizes if size > body_size + 1], reverse=True)
    
    return body_size, heading_sizes

def extract_outline_with_pdfplumber(pdf_path):
    """
    Extracts title and hierarchical headings from a PDF using a refined,
    context-aware version of the pdfplumber approach.
    """
    try:
        with pdfplumber.open(pdf_path) as pdf:
            if not pdf.pages:
                return {"title": "Empty Document", "outline": []}

            # --- Phase 1: Analyze document-wide font styles ---
            body_size, heading_sizes = analyze_document_styles(pdf)
            
            # Create a mapping from a font size to its heading level (H1, H2, etc.)
            level_map = {size: f"H{i+1}" for i, size in enumerate(heading_sizes)}

            # --- Phase 2: Title Extraction (Restored and Improved) ---
            title = "Untitled Document"
            if heading_sizes:
                max_heading_size = heading_sizes[0]
                first_page = pdf.pages[0]
                
                potential_titles = []
                # Find all words on the first page that match the largest heading font size
                for word in first_page.extract_words(y_tolerance=3):
                    if round(word.get('size', 0)) == max_heading_size:
                        potential_titles.append(word)
                
                if potential_titles:
                    # Group title words by their line (y-coordinate) to handle multi-line titles
                    title_lines = defaultdict(list)
                    for word in potential_titles:
                        y0 = round(word.get('y0', 0))
                        title_lines[y0].append(word['text'])
                    
                    if title_lines:
                        # Join the top-most lines that share the max font size
                        sorted_y = sorted(title_lines.keys())
                        # Combine the text from all detected title lines
                        full_title = " ".join([" ".join(title_lines[y]) for y in sorted_y])
                        cleaned_title = clean_text(full_title)
                        if cleaned_title: # Ensure the title is not empty after cleaning
                            title = cleaned_title


            # --- Phase 3: Outline Extraction with Stricter, More Precise Filtering ---
            outline = []
            for page_num, page in enumerate(pdf.pages, 1):
                words = page.extract_words(x_tolerance=2, y_tolerance=2)
                
                lines = defaultdict(list)
                for word in words:
                    y0 = round(word.get('y0', 0))
                    lines[y0].append(word)

                sorted_y_coords = sorted(lines.keys())

                for y in sorted_y_coords:
                    line_words = sorted(lines[y], key=lambda w: w.get('x0', 0))
                    if not line_words: continue

                    line_text = clean_text(" ".join([w['text'] for w in line_words]))
                    first_word = line_words[0]
                    font_size = round(first_word.get('size', 0))
                    font_name = first_word.get('fontname', '').lower()
                    is_bold = 'bold' in font_name or 'black' in font_name or 'heavy' in font_name

                    # --- ADVANCED FILTERING LOGIC ---
                    # Rule 1: Must have a font size that was pre-identified as a heading size.
                    if font_size not in heading_sizes:
                        continue
                    
                    # Rule 2: Must be bold OR all caps. This is a strong indicator for headings.
                    if not is_bold and not line_text.isupper():
                        continue

                    # Rule 3: Filter out Table of Contents lines with leader dots.
                    if re.search(r'\.{3,}\s*\d+$', line_text):
                        continue
                        
                    # Rule 4: Filter out Revision History table data from file02.pdf (e.g., "0.1 18 JUNE...")
                    if re.match(r'^\d\.\d\s', line_text):
                        continue

                    # Rule 5: THIS IS THE KEY IMPROVEMENT. Distinguish headings from list items.
                    # A real heading is concise. A list item is often a full sentence.
                    # If a line starts with a number pattern but is long, it's a list item, not a heading.
                    if re.match(r'^\d+(\.\d+)*\s', line_text) and len(line_words) > 8:
                        continue

                    # Rule 6: General conciseness check for all other potential headings.
                    if len(line_words) > 12:
                        continue

                    # If all checks pass, it's very likely a real heading.
                    level = level_map.get(font_size, "H4") # Default to H4 if size somehow missed
                    outline.append({
                        "level": level,
                        "text": line_text,
                        "page": page_num
                    })

            # --- Final Deduplication ---
            final_outline = []
            seen = set()
            for item in outline:
                identifier = (item['text'].lower(), item['page'])
                if identifier not in seen:
                    final_outline.append(item)
                    seen.add(identifier)
            
            return {"title": title, "outline": final_outline}

    except Exception as e:
        print(f"Error processing PDF '{pdf_path}': {e}", file=sys.stderr)
        return {"title": "Error Processing Document", "outline": []}

if __name__ == "__main__":
    # Ensure you have installed pdfplumber: pip install pdfplumber
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
