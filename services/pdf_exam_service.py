import re
import io
import logging
from typing import Dict, Any, List, Tuple
import PyPDF2

logger = logging.getLogger(__name__)

def extract_text_from_pdf(pdf_source) -> str:
    """
    Extracts raw text from a PDF file path or file-like object / BytesIO using PyPDF2.
    """
    raw_text = ""
    try:
        if isinstance(pdf_source, (str, bytes)):
            if isinstance(pdf_source, bytes):
                pdf_file = io.BytesIO(pdf_source)
            else:
                pdf_file = open(pdf_source, "rb")
        else:
            pdf_file = pdf_source

        reader = PyPDF2.PdfReader(pdf_file)
        pages_text = []
        for idx, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            if text.strip():
                pages_text.append(text)
        
        raw_text = "\n".join(pages_text)
    except Exception as e:
        logger.error("Error extracting text from PDF: %s", e)
        raw_text = ""
    return raw_text


def parse_exam_pdf_text(raw_text: str) -> Dict[str, Any]:
    """
    Parses PDF text containing MCQs into structured question records.
    Handles variations in question numbering, option labeling, answer formats, marks, and categories.
    """
    questions: List[Dict[str, Any]] = []
    
    if not raw_text or not raw_text.strip():
        return {
            "questions": [],
            "total_count": 0,
            "valid_count": 0,
            "review_count": 0,
            "error_message": "Could not extract readable text from PDF file."
        }

    # Normalize line breaks and spaces
    lines = [l.strip() for l in raw_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    
    # Split text into question blocks based on common question header patterns:
    # e.g. "Question 1.", "Q1.", "Q1:", "1.", "1)" at the start of a line
    q_start_regex = re.compile(r'^(?:Question\s*\d+|Q\s*\d+|\d+)[\.\:\)]\s*', re.IGNORECASE)
    
    blocks: List[List[str]] = []
    current_block: List[str] = []
    has_started_questions = False

    for line in lines:
        if not line:
            continue
        if q_start_regex.match(line):
            if current_block and has_started_questions:
                blocks.append(current_block)
                current_block = []
            has_started_questions = True

        if has_started_questions:
            current_block.append(line)

    if current_block and has_started_questions:
        blocks.append(current_block)

    # If q_start_regex didn't split (e.g., formatting differs), try alternative block splitter
    if len(blocks) <= 1:
        # Try matching any line starting with a number followed by dot or space
        alt_blocks = []
        cur_b = []
        alt_regex = re.compile(r'^\d+[\.\)]\s+')
        for l in lines:
            if not l:
                continue
            if alt_regex.match(l):
                if cur_b:
                    alt_blocks.append(cur_b)
                    cur_b = []
            cur_b.append(l)
        if cur_b:
            alt_blocks.append(cur_b)
        if len(alt_blocks) > 1:
            blocks = alt_blocks

    total_count = len(blocks)
    valid_count = 0
    review_count = 0

    seen_texts = set()

    for idx, b in enumerate(blocks, start=1):
        block_str = "\n".join(b)
        
        # Regex patterns for options and metadata
        q_item: Dict[str, Any] = {
            "question_number": idx,
            "question_text": "",
            "option_a": "",
            "option_b": "",
            "option_c": "",
            "option_d": "",
            "correct_answer": "",
            "marks": 1.0,
            "negative_marks": 0.0,
            "category": "Aptitude",
            "difficulty": "Medium",
            "warnings": [],
            "requires_review": False
        }

        # Extract correct answer if present
        # e.g., "Correct Answer: B", "Answer: B", "Correct: B", "Answer: Option B", "Ans: B", "Key: B", "[B]"
        ans_match = re.search(r'(?:Correct(?:\s*Answer)?|Answer|Ans|Key)\s*[\:\-\=]?\s*(?:Option\s*)?([A-D])\b', block_str, re.IGNORECASE)
        if ans_match:
            q_item["correct_answer"] = ans_match.group(1).upper()
        else:
            # Fallback: check for standalone [A], [B], [C], [D] at end of block
            bracket_ans = re.search(r'\[([A-D])\]\s*$', block_str, re.IGNORECASE)
            if bracket_ans:
                q_item["correct_answer"] = bracket_ans.group(1).upper()

        # Extract marks if present
        marks_match = re.search(r'(?:Marks?|Score)\s*[\:\=]?\s*(\d+(?:\.\d+)?)', block_str, re.IGNORECASE)
        if marks_match:
            try:
                q_item["marks"] = float(marks_match.group(1))
            except ValueError:
                pass

        # Extract negative marks if present
        neg_match = re.search(r'(?:Negative\s*Marks?|Penalty)\s*[\:\=]?\s*(\d+(?:\.\d+)?)', block_str, re.IGNORECASE)
        if neg_match:
            try:
                q_item["negative_marks"] = float(neg_match.group(1))
            except ValueError:
                pass

        # Extract category if present
        cat_match = re.search(r'(?:Category|Topic)\s*[\:\=]?\s*([A-Za-z0-9\s]+?)(?=\n|$)', block_str, re.IGNORECASE)
        if cat_match:
            cat_val = cat_match.group(1).strip()
            if cat_val and len(cat_val) < 50:
                q_item["category"] = cat_val

        # Extract difficulty if present
        diff_match = re.search(r'(?:Difficulty|Level)\s*[\:\=]?\s*(Easy|Medium|Hard)', block_str, re.IGNORECASE)
        if diff_match:
            q_item["difficulty"] = diff_match.group(1).capitalize()

        def clean_pdf_string(s: str) -> str:
            if not s:
                return ""
            # Strip page header/footer noise like Page 1 of 5
            cleaned = re.sub(r'Page\s*\d+\s*(?:of\s*\d+)?', '', s, flags=re.IGNORECASE)
            # Normalize whitespace/newlines
            lines = [line.strip() for line in cleaned.split("\n") if line.strip()]
            return " ".join(lines).strip()

        # Parse Question Text and Options
        # Extract Option A, B, C, D lines or inline markers
        opt_patterns = {
            "A": re.compile(r'(?:^|\n|\s)(?:A[\.\)]|\(A\)|\[A\])\s+(.*?)(?=(?:\n|\s)(?:B[\.\)]|\(B\)|\[B\])|$)', re.DOTALL | re.IGNORECASE),
            "B": re.compile(r'(?:^|\n|\s)(?:B[\.\)]|\(B\)|\[B\])\s+(.*?)(?=(?:\n|\s)(?:C[\.\)]|\(C\)|\[C\])|$)', re.DOTALL | re.IGNORECASE),
            "C": re.compile(r'(?:^|\n|\s)(?:C[\.\)]|\(C\)|\[C\])\s+(.*?)(?=(?:\n|\s)(?:D[\.\)]|\(D\)|\[D\])|$)', re.DOTALL | re.IGNORECASE),
            "D": re.compile(r'(?:^|\n|\s)(?:D[\.\)]|\(D\)|\[D\])\s+(.*?)(?=(?:Correct\s*Answer|Answer|Ans|Key|Marks|Category|Difficulty|\n\n|$))', re.DOTALL | re.IGNORECASE),
        }

        # Parse text before first option as question_text
        opt_a_pos = re.search(r'(?:^|\n|\s)(?:A[\.\)]|\(A\)|\[A\])\s+', block_str, re.IGNORECASE)
        if opt_a_pos:
            q_text_raw = block_str[:opt_a_pos.start()].strip()
        else:
            q_text_raw = block_str.strip()

        # Clean header prefixes like "Question 1.", "1."
        q_text_clean = re.sub(r'^(?:Question\s*\d+|Q\s*\d+|\d+)[\.\:\)]\s*', '', q_text_raw, flags=re.IGNORECASE).strip()
        q_item["question_text"] = clean_pdf_string(q_text_clean)

        # Extract Option Values
        for opt_key in ["A", "B", "C", "D"]:
            match = opt_patterns[opt_key].search(block_str)
            if match:
                opt_val = match.group(1).strip()
                # Clean answer footer if trailing
                opt_val = re.sub(r'\n*(?:Correct\s*Answer|Answer|Ans|Key|Marks|Category|Difficulty)[\:\-].*$', '', opt_val, flags=re.DOTALL | re.IGNORECASE).strip()
                # Strip leading option prefixes like A., A), (A), [A] if present
                opt_val = re.sub(r'^(?:[A-D][\.\:\)]|\([A-D]\)|\[[A-D]\])\s*', '', opt_val, flags=re.IGNORECASE).strip()
                q_item[f"option_{opt_key.lower()}"] = clean_pdf_string(opt_val)

        # Validation Checks & Warning Flags
        if not q_item["question_text"]:
            q_item["warnings"].append("Question text is empty or missing.")
            q_item["requires_review"] = True

        missing_opts = [opt for opt in ["a", "b", "c", "d"] if not q_item[f"option_{opt}"]]
        if missing_opts:
            q_item["warnings"].append(f"Missing option(s): {', '.join([o.upper() for o in missing_opts])}")
            q_item["requires_review"] = True

        if not q_item["correct_answer"] or q_item["correct_answer"] not in ["A", "B", "C", "D"]:
            q_item["warnings"].append("Correct answer is missing or invalid.")
            q_item["requires_review"] = True

        clean_q_key = re.sub(r'\s+', ' ', q_item["question_text"].lower())
        if clean_q_key and clean_q_key in seen_texts:
            logger.info("Skipping duplicate question in PDF: %s", q_item["question_text"])
            review_count += 1
            continue
        elif clean_q_key:
            seen_texts.add(clean_q_key)

        if q_item["requires_review"]:
            review_count += 1
        else:
            valid_count += 1

        questions.append(q_item)

    return {
        "questions": questions,
        "total_count": total_count,
        "valid_count": valid_count,
        "review_count": review_count,
        "error_message": None
    }


def parse_exam_pdf_file(pdf_source) -> Dict[str, Any]:
    """
    Helper function to extract text and parse questions from PDF source.
    """
    raw_text = extract_text_from_pdf(pdf_source)
    return parse_exam_pdf_text(raw_text)
