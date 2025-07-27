# src/persona_analyst.py
import os
import json
import sys
import spacy
from collections import defaultdict
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
from datetime import datetime

# Assuming outline_extractor.py is in the same 'src' directory
# Ensure this import path is correct when running locally or in Docker
try:
    from outline_extractor import extract_outline_with_pdfplumber
except ImportError:
    # Fallback for direct script execution if not in a package structure
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    from outline_extractor import extract_outline_with_pdfplumber


# Load a spaCy model. This model must be downloaded locally via 'python -m spacy download en_core_web_md'.
try:
    nlp = spacy.load("en_core_web_md")
    print("spaCy model 'en_core_web_md' loaded successfully.")
except OSError:
    print("spaCy model 'en_core_web_md' not found. Please ensure it's downloaded locally.", file=sys.stderr)
    sys.exit(1)

def get_text_content_for_section(pdf_path, page_number, section_title, next_section_page_number=None, next_section_title=None):
    """
    Extracts text content for a given section from a PDF.
    This function needs robust implementation to accurately capture content
    between headings or until the end of a logical section.
    A more advanced approach would involve iterating through `page.extract_text_lines(layout=True)`
    and collecting lines until a new heading is detected or page ends.
    """
    text_content_parts = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            if page_number > len(pdf.pages):
                return "" # Invalid page number

            # Start collecting text from the page where the section title appears
            for current_p_idx in range(page_number - 1, len(pdf.pages)):
                page = pdf.pages[current_p_idx]
                lines = page.extract_text_lines(layout=True, strip=True)
                
                found_title = False
                for line_data in lines:
                    cleaned_line_text = line_data['text'].strip()
                    
                    if not found_title:
                        # Find the actual start of the section by matching the title
                        if section_title in cleaned_line_text:
                            found_title = True
                            # If title is found, start collecting from this point
                            text_content_parts.append(cleaned_line_text)
                            continue # Continue to next line
                        else:
                            continue # Skip lines before the section title
                    
                    # If we found the title, now check for the next section
                    if next_section_page_number and next_section_title:
                        if current_p_idx == (next_section_page_number - 1): # If next section is on current page
                            if next_section_title in cleaned_line_text:
                                # Stop collecting if we hit the next section's title
                                break
                    
                    text_content_parts.append(cleaned_line_text)
                
                # If we've reached the page of the next section, or the end of the document
                # and still haven't broken, stop here.
                if next_section_page_number and current_p_idx >= (next_section_page_number - 1):
                    break


    except Exception as e:
        print(f"Error extracting content for section '{section_title}' from '{pdf_path}': {e}", file=sys.stderr)
    
    # Simple post-processing: join lines, remove excessive whitespace
    full_text = " ".join(text_content_parts)
    return re.sub(r'\s+', ' ', full_text).strip()


def analyze_document_collection(pdf_file_paths, persona_definition, job_to_be_done):
    """
    Analyzes a collection of documents based on a persona and job-to-be-done.
    """
    all_extracted_sections = []
    metadata = {
        "input_documents": [os.path.basename(f) for f in pdf_file_paths],
        "persona": persona_definition,
        "job_to_be_done": job_to_be_done,
        "processing_timestamp": datetime.now().isoformat()
    }

    # Step 1: Extract outlines and gather all potential sections from all PDFs
    for pdf_file_path in pdf_file_paths:
        print(f"Extracting outline for {os.path.basename(pdf_file_path)}...")
        outline_result = extract_outline_with_pdfplumber(pdf_file_path)
        
        # Create a list of section boundaries for accurate text extraction
        # This helps in knowing when a section ends and the next begins.
        section_boundaries = []
        for i, entry in enumerate(outline_result['outline']):
            section_boundaries.append({
                "title": entry['text'],
                "page": entry['page'],
                "doc_path": pdf_file_path,
                "next_title": outline_result['outline'][i+1]['text'] if i+1 < len(outline_result['outline']) else None,
                "next_page": outline_result['outline'][i+1]['page'] if i+1 < len(outline_result['outline']) else None
            })

        for section_info in section_boundaries:
            section_content = get_text_content_for_section(
                section_info['doc_path'],
                section_info['page'],
                section_info['title'],
                section_info['next_page'],
                section_info['next_title']
            )
            
            all_extracted_sections.append({
                "document": os.path.basename(section_info['doc_path']),
                "page_number": section_info['page'],
                "section_title": section_info['title'],
                "full_text_content": section_content, # Store full content for analysis
                "importance_rank": 0 # Placeholder for now
            })

    if not all_extracted_sections:
        return {"metadata": metadata, "extracted_sections": [], "sub_section_analysis": []}

    # Step 2: Semantic Analysis and Ranking
    # Combine persona and job-to-be-done for a query vector
    query_text = f"Persona: {persona_definition}. Job: {job_to_be_done}"
    query_doc = nlp(query_text)

    # Prepare texts for TF-IDF vectorization
    section_texts = [sec["full_text_content"] for sec in all_extracted_sections]
    
    # Add query text to the corpus for consistent vectorization
    corpus = section_texts + [query_text]

    # Use TF-IDF for basic keyword importance and cosine similarity
    vectorizer = TfidfVectorizer(stop_words='english', max_features=5000) # Limit features for smaller model footprint
    tfidf_matrix = vectorizer.fit_transform(corpus)

    # The last vector in tfidf_matrix is for the query
    query_vector = tfidf_matrix[-1]
    section_vectors = tfidf_matrix[:-1]

    # Calculate cosine similarity between query and each section
    similarities = cosine_similarity(query_vector, section_vectors).flatten()

    # Assign rank based on similarity
    ranked_sections = []
    for i, section in enumerate(all_extracted_sections):
        section["importance_rank"] = float(similarities[i]) # Store as float for JSON
        ranked_sections.append(section)

    # Sort sections by importance rank in descending order
    ranked_sections.sort(key=lambda x: x["importance_rank"], reverse=True)

    # Step 3: Sub-Section Analysis (Refinement)
    sub_section_analysis = []
    # Analyze top N most relevant sections based on initial ranking.
    top_n_sections_for_sub_analysis = 5 # As per prompt examples, refine top relevant
    
    # Define keywords for refined text extraction: using spaCy's lemma for robustness
    query_keywords = [token.lemma_ for token in query_doc if token.is_alpha and not token.is_stop and not token.is_punct]
    
    for i, section in enumerate(ranked_sections):
        if i >= top_n_sections_for_sub_analysis:
            break

        if not section["full_text_content"]:
            continue

        doc = nlp(section["full_text_content"])
        relevant_sentences = []
        
        for sent in doc.sents:
            sent_keywords = [token.lemma_ for token in sent if token.is_alpha and not token.is_stop and not token.is_punct]
            
            # Use Jaccard similarity or simple keyword overlap for sentence relevance
            intersection = len(set(query_keywords) & set(sent_keywords))
            union = len(set(query_keywords) | set(sent_keywords))
            
            if union > 0: # Avoid division by zero
                jaccard_similarity = intersection / union
                if jaccard_similarity > 0.05: # Threshold for considering a sentence relevant
                    relevant_sentences.append(sent.text.strip())
            
            # Implement a character limit for refined text
            current_refined_text_length = sum(len(s) for s in relevant_sentences)
            if current_refined_text_length > 1000: # Example limit for refined text block
                break

        if relevant_sentences:
            sub_section_analysis.append({
                "document": section["document"],
                "page_number": section["page_number"],
                "refined_text": " ".join(relevant_sentences) # Join all relevant sentences
            })
            
    # Remove 'full_text_content' from main sections for final output to match format
    final_extracted_sections = [{k: v for k, v in sec.items() if k != 'full_text_content'} for sec in ranked_sections]

    return {
        "metadata": metadata,
        "extracted_sections": final_extracted_sections,
        "sub_section_analysis": sub_section_analysis
    }

if __name__ == "__main__":
    # This script is designed to be called by run_local.py for local testing.
    # It expects: <pdf_file_paths> <persona_definition> <job_to_be_done> <output_json_path>
    # Note: pdf_file_paths should be a comma-separated string for simplicity in CLI.

    if len(sys.argv) < 5:
        print("Usage: python src/persona_analyst.py <comma_separated_pdf_paths> <persona_definition_str> <job_to_be_done_str> <output_json_path>")
        print("Example: python src/persona_analyst.py \"input_data/scenario1/doc1.pdf,input_data/scenario1/doc2.pdf\" \"PhD Researcher\" \"Comprehensive literature review\" output_results/scenario1_output.json")
        sys.exit(1)

    pdf_paths_str = sys.argv[1]
    persona_def = sys.argv[2]
    job_def = sys.argv[3]
    output_json_path = sys.argv[4]

    pdf_files = [p.strip() for p in pdf_paths_str.split(',') if p.strip()]
    if not pdf_files:
        print("Error: No PDF file paths provided.", file=sys.stderr)
        sys.exit(1)

    for p_file in pdf_files:
        if not os.path.exists(p_file):
            print(f"Error: PDF file not found at '{p_file}'. Please check path.", file=sys.stderr)
            sys.exit(1)

    # Ensure output directory exists
    output_dir = os.path.dirname(output_json_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)

    print(f"Starting analysis for scenario:")
    print(f"  PDFs: {[os.path.basename(f) for f in pdf_files]}")
    print(f"  Persona: '{persona_def}'")
    print(f"  Job: '{job_def}'")

    result = analyze_document_collection(pdf_files, persona_def, job_def)

    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=4, ensure_ascii=False)

    print(f"Analysis complete. Output saved to '{output_json_path}'")