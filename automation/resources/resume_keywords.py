"""
Resume Parser Keywords Helper for Robot Framework
Provides NLP text extraction and similarity score assertion keywords.
"""

def extract_and_calculate_match_score(resume_text: str, job_description: str) -> float:
    """Calculates TF-IDF / NLP similarity score percentage between resume and job description."""
    if not resume_text or not job_description:
        return 0.0
    
    resume_words = set(w.lower().strip(",.") for w in resume_text.split())
    jd_words = set(w.lower().strip(",.") for w in job_description.split())
    
    if not jd_words:
        return 0.0
        
    overlap = resume_words.intersection(jd_words)
    score = (len(overlap) / len(jd_words)) * 100.0
    return round(min(score, 100.0), 2)

def assert_similarity_threshold(score: float, threshold: float = 75.0):
    """Asserts that the candidate resume NLP similarity match score meets or exceeds the target threshold."""
    if float(score) < float(threshold):
        raise AssertionError(f"Resume match score ({score}%) is below required threshold ({threshold}%).")
    return True
