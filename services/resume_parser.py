import os

def extract_resume_text(file_path):
    """
    Dummy/fallback text extractor for resume files.
    """
    try:
        if not file_path or not os.path.exists(file_path):
            return ""
        with open(file_path, "r", errors="ignore") as f:
            return f.read()
    except Exception:
        return ""

def parse_candidate_info(text):
    """
    Dummy/fallback candidate info parser.
    """
    return {
        "skills": [],
        "education": "",
        "experience": ""
    }
