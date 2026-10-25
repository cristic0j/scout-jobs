"""Guess seniority, work mode and posting language from a job's text."""
import re

from .http import strip_html
from .matching import keyword_pattern

LEVELS = ["internship", "junior", "medior", "senior"]
WORK_MODES = ["on-site", "hybrid", "remote"]

# Checked in this order; anything unmatched is "medior".
LEVEL_WORDS = [
    ("internship", keyword_pattern([r"re:\bintern(ship)?s?\b", r"re:\bstage\b", "stagiair", "werkstudent",
                                    "working student", "afstudeer"])),
    ("junior", keyword_pattern(["junior", "jr", "graduate", "entry level", "entry-level", "trainee", "starter"])),
    ("senior", keyword_pattern(["senior", "sr", "staff", "principal", r"re:\blead\b", "head of", "director",
                                "architect", "vp", "chief", "expert"])),
]


def level(title):
    for name, pattern in LEVEL_WORDS:
        if pattern.search(title):
            return name
    return "medior"


HYBRID_PLACE = re.compile(r"\bhybride?\b", re.I)
# In descriptions "hybrid" must be about working ("hybrid work", "werken is hybride"), not "hybrid cloud".
HYBRID_TEXT = re.compile(
    r"\bhybride?\b[,:]?\s*(?:work|working|werk|werken|model|role|position|set-?up|schedule|policy|"
    r"way of working|from home|office|functie|werkplek|te werken|\()"
    r"|\b(?:work|working|werk|werken|werkt|role|position|job)\s+(?:is\s+|fully\s+|op\s+)?hybride?\b"
    r"|\d (?:days?|dagen) (?:per week )?(?:in|at|on|op) (?:the|ons|het)? ?(?:office|kantoor)", re.I)
REMOTE_PLACE = re.compile(r"\bremote\b", re.I)
REMOTE_TEXT = re.compile(r"fully remote|100% remote|remote[- ]first|work from anywhere|volledig remote", re.I)


def work_mode(job):
    """Title/location wording first (LinkedIn's own work-mode tags are often wrong), then the source's
    field, then hybrid/remote wording in the description; "" if unknown."""
    place = f"{job.title} {job.location}"
    if HYBRID_PLACE.search(place):
        return "hybrid"
    if REMOTE_PLACE.search(place):
        return "remote"
    if job.work_mode in WORK_MODES:  # sources also send values like "unspecified"
        return job.work_mode
    desc = strip_html(job.desc)
    if HYBRID_TEXT.search(desc):
        return "hybrid"
    if REMOTE_TEXT.search(desc):
        return "remote"
    return ""


NL_WORDS = re.compile(r"\b(de|het|een|en|van|je|jij|wij|we|voor|met|bij|zijn|ons|onze|wat|als|ook|"
                      r"naar|werk|ervaring|functie)\b", re.I)
EN_WORDS = re.compile(r"\b(the|and|to|of|you|we|for|with|our|your|is|are|will|experience|role)\b", re.I)
NEEDS_DUTCH = re.compile(r"(fluent|native|proficient|proficiency|excellent|good|strong|business|"
                         r"professional|full)[^.\n]{0,40}\bdutch\b|\bdutch\b[^.\n]{0,40}(required|"
                         r"is a must|mandatory|essential|speaking|fluency|proficiency|native|"
                         r"written and spoken|spoken and written)|nederlandstalig|"
                         r"(goede|uitstekende) beheersing van de nederlandse|vloeiend nederlands", re.I)
OPTIONAL = re.compile(r"plus|nice to have|bonus|advantage|preferred|not required|no dutch|"
                      r"not a must|don't need|do not need|optional", re.I)


def language(title, desc):
    """'Dutch' (posting written in Dutch), 'Dutch required', 'English', or '?' (no text)."""
    text = strip_html(desc)
    if not text:
        return "Dutch" if re.search(r"ontwikkelaar|medewerker|\bbij\b|programmeur", title, re.I) else "?"
    if len(NL_WORDS.findall(text)) > 1.2 * len(EN_WORDS.findall(text)):
        return "Dutch"
    for sentence in re.split(r"(?<=[.!?•\n])\s+", text):
        if NEEDS_DUTCH.search(sentence) and not OPTIONAL.search(sentence):
            return "Dutch required"
    return "English"
