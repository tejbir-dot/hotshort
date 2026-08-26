"""
Rule-based narrative trigger detection (O(n) over transcript segments).
"""

from __future__ import annotations


import os
import json
import logging
import requests
from typing import Dict, List, Any

try:
    from viral_finder.groq_cortex import is_groq_enabled, _get_groq_api_key, _get_groq_model, _get_timeout, parse_groq_json_safely, post_groq_completions
except ImportError:
    def is_groq_enabled(): return False

try:
    from viral_finder.gemini_cortex import is_gemini_enabled, post_gemini_completions, parse_gemini_json_safely
except ImportError:
    def is_gemini_enabled(): return False



# ── English trigger phrases (Creator-Psychology aware) ──────────────────────
# These patterns are used by top creators (Hormozi, Gadzhi, MrBeast editors)
# to stop the scroll and force the brain to keep watching.

_BELIEF_REVERSAL = (
    "most people think",
    "most people miss",
    "everyone thinks",
    "but actually",
    "but the truth is",
    "in reality",
    "however",
    "contrary to what",
    "the opposite is true",
    "you've been lied to",
    "what they don't tell you",
    "nobody talks about this",
    "this is not what you think",
)
_SECRET_REVELATION = (
    "the secret is",
    "what nobody tells you",
    "the real reason",
    "here is the truth",
    "the thing nobody says",
    "what they don't want you to know",
    "the hidden",
    "i discovered",
    "i figured out",
    "the key insight",
    "the one thing",
    "what changed everything",
    "i never told anyone this",
)
_MISTAKE_EXPLANATION = (
    "the biggest mistake",
    "people get this wrong",
    "everyone does this wrong",
    "stop doing",
    "you're doing it wrong",
    "this is killing your",
    "this is why you're failing",
    "if you're still doing",
    "the worst thing you can do",
    "never do this",
    "i wasted years",
    "i lost everything because",
)
_STRONG_CLAIM = (
    "the truth is",
    "the problem is",
    "the reality is",
    "the reason is",
    "here's why",
    "this is why",
    "i'll be honest",
    "let me be real",
    "unpopular opinion",
    "hot take",
    "controversial opinion",
    "no one wants to hear this",
    "this will make you uncomfortable",
)

# ── PATTERN INTERRUPT — Scroll-stopper hooks (Hormozi / Gadzhi style) ──────────
# "If you're X, stop" / "The ONLY reason you haven't Y" — forces identity check
_PATTERN_INTERRUPT = (
    "if you're not doing",
    "if you're still",
    "the only reason you haven't",
    "the reason you're broke",
    "the reason you're stuck",
    "why you keep failing",
    "stop scrolling",
    "pay attention",
    "listen carefully",
    "this changed my life",
    "this will change your life",
    "i wish someone told me this",
    "everything changed when",
    "i went from",
    "from zero to",
    "this is the difference between",
    "what separates",
    "the gap between",
)
_PATTERN_INTERRUPT_HI = (
    "agar tu abhi bhi",
    "agar tu ye nahi kar raha",
    "ye sun le dhyan se",
    "bas ek kaam kar",
    "ye meri zindagi badal di",
    "kash koi mujhe pehle batata",
    "jab se maine ye kiya",
    "meri life tab badli jab",
    "jo fark hota hai woh",
    "iss ek cheez ne sab badal diya",
    "tu broke kyu hai",
    "tu kyun stuck hai",
    "sar uthake sun",
)

# ── CURIOSITY GAP — Open loops that force the brain to keep watching ──────────
# "Here's what nobody tells you..." / "The reason is surprising" — cognitive itch
_CURIOSITY_GAP = (
    "here's the thing",
    "here's what's crazy",
    "here's what most people don't realize",
    "and this is the part that blew my mind",
    "and this is where it gets interesting",
    "but here's the twist",
    "you won't believe",
    "the crazy part is",
    "what shocked me was",
    "what most people don't know",
    "the surprising thing is",
    "what nobody talks about",
    "the part that nobody mentions",
    "here's what changes everything",
    "this is the part that matters",
    "but wait",
)
_CURIOSITY_GAP_HI = (
    "aur ye sun ke tujhe shock lagega",
    "aur yahan pe mazedaar cheez ye hai",
    "ek baat jo koi nahi batata",
    "aur ye wala part sab ignore karte hain",
    "ab yahan twist aata hai",
    "lekin yahan pe sab galat ho jaate hain",
    "ye wali baat sun le",
    "interesting baat ye hai ki",
    "aur yahi cheez sab miss kar dete hain",
    "soch ke dekh",
    "tu sochega nahi",
    "par ye part sabse important hai",
)

# ── BOLD PROMISE — High-value claim upfront (Hormozi offer-first style) ──────
# "I made $1M doing X" / "This one thing tripled my revenue" — proof-backed hook
_BOLD_PROMISE = (
    "this one thing",
    "this single thing",
    "i made",
    "we made",
    "went from",
    "grew from",
    "tripled",
    "doubled",
    "ten x",
    "10x",
    "100x",
    "in just",
    "in 30 days",
    "in 90 days",
    "in one year",
    "without",
    "you don't need",
    "you don't have to",
    "you only need",
    "the simplest way",
    "the fastest way",
    "the easiest way",
)
_BOLD_PROMISE_HI = (
    "maine itne paise kamaye",
    "sirf ek cheez ne",
    "mera revenue double ho gaya",
    "sirf 30 din mein",
    "bina X ke bhi ho sakta hai",
    "tujhe ye nahi chahiye",
    "ye sabse aasaan tarika hai",
    "ye sabse tez tarika hai",
    "ye ek kaam karega",
    "itne log galti karte hain",
)

# ── SOCIAL PROOF HOOK — Contrast-based credibility (Gadzhi / founder style) ──
# "Every successful person does X" / "People who make $X all have this in common"
_SOCIAL_PROOF_HOOK = (
    "every successful",
    "all successful",
    "people who make",
    "the top 1 percent",
    "the top one percent",
    "billionaires do this",
    "millionaires do this",
    "rich people know",
    "poor people think",
    "successful people all",
    "the common thread",
    "what they all have in common",
    "what winners do",
    "what losers do",
    "the difference is",
)
_SOCIAL_PROOF_HOOK_HI = (
    "jo log successful hain",
    "top log ye karte hain",
    "ameer log ye sochte hain",
    "garib log ye sochte hain",
    "sab successful logo mein ek baat common hai",
    "winner aur loser mein ye fark hota hai",
    "har ek successful banda ye karta hai",
    "jo log paise kamaa rahe hain",
)

# ── Hindi / Hinglish trigger phrases ──────────────────────────────────────────
# Belief Reversal
_BELIEF_REVERSAL_HI = (
    "log sochte hain",
    "log mante hain",
    "lekin sach ye hai",
    "lekin asli baat",
    "asal mein",
    "असल में",
    "लेकिन सच ये है",
    "लोग सोचते हैं",
    "हकीकत ये है",
    "par sach ye hai",
    "but sach ye hai",
    "sabko lagta hai",
    "duniya manti hai",
    "logo ko lagta hai",
    "yeh sach nahi hai",
    "ulta hai asal mein",
)
# Secret Revelation
_SECRET_REVELATION_HI = (
    "raaz ye hai",
    "asli raaz",
    "koi nahi batata",
    "sabse badi baat",
    "ye koi nahi batata",
    "राज़ ये है",
    "असली राज़",
    "कोई नहीं बताता",
    "सबसे बड़ी बात",
    "sach baat ye hai",
    "ye wala secret",
    "asli cheez ye hai",
    "hidden cheez",
    "ye sab se important baat hai",
)
# Mistake Explanation
_MISTAKE_EXPLANATION_HI = (
    "sabse badi galti",
    "log galat karte hain",
    "ye galat hai",
    "galat tarika",
    "सबसे बड़ी गलती",
    "लोग गलत करते हैं",
    "ye sab galat kar rahe hain",
    "isko galat samajhte hain",
    "tune galti ki",
    "yahi galti sab karte hain",
    "band kar ye kaam",
    "tu yahi kar raha hai na",
)
# Strong Claim
_STRONG_CLAIM_HI = (
    "sach ye hai",
    "problem ye hai",
    "asli problem",
    "wajah ye hai",
    "matlab ye hai",
    "सच ये है",
    "समस्या ये है",
    "वजह ये है",
    "seedhi baat",
    "simple baat",
    "main seedha bolunga",
    "sachchi baat ye hai",
    "honest rehna chahta hoon",
)

_PAYOFF = (
    "in conclusion",
    "so basically",
    "the point is",
    "at the end of the day",
    "what this means is",
    "to summarize",
    "the bottom line",
    "what this comes down to",
    "the takeaway is",
    "so what this means for you",
    "here's what to do",
    "so here's the thing",
    "the lesson here",
    "what i want you to take away",
)

_PAYOFF_HI = (
    "iska matlab ye hai",
    "to aakhir mein",
    "kul milakar",
    "baat ye hai ki",
    "iska nateeja",
    "toh tu kya kare",
    "yahi seekhna hai",
    "summary ye hai",
    "short mein bolunga",
    "ek baar aur samajh le",
)

# ── CHAOS / ENTERTAINMENT trigger phrases ─────────────────────────────────────
# These are specifically for streaming, gaming, variety content where the
# viral moment is NOT educational but "WHAT DID I JUST HEAR?" energy.

# chaos_digression: Normal conversation suddenly derails into something bizarre.
_CHAOS_DIGRESSION = (
    "wait what",
    "hold on",
    "that came out of nowhere",
    "how did we get here",
    "bro what are you talking about",
    "where did that come from",
    "this is not related but",
    "okay but randomly",
    "i have a question",
    "actually wait",
)
_CHAOS_DIGRESSION_HI = (
    "yaar ye kya ho gaya",
    "bhai sun",
    "ek second",
    "ye kahan se aaya",
    "bhai baat kahan se kahan pahunch gayi",
    "ruk ruk ruk",
    "ek minute",
    "alag topic pe aao",
    "lekin ye bata",
    "suddenly",
    "suddenly kya",
)

# cursed_escalation: One harmless comment starts a chain leading somewhere bizarre.
_CURSED_ESCALATION = (
    "it keeps getting worse",
    "and then he said",
    "and it gets worse",
    "and then",
    "okay so then",
    "but then get this",
    "now hear me out",
    "wait it gets better",
    "no no no listen",
    "okay okay okay",
)
_CURSED_ESCALATION_HI = (
    "aur phir kya hua",
    "phir bolta hai",
    "phir us ne bola",
    "aur bhai sun",
    "aur mazedaar baat",
    "abhi toh aur suno",
    "iske aage sunoge toh",
    "no no sun",
    "abhi batata hoon",
    "woh toh kuch aur hi bola",
)

# absurd_banter: Outrageous, shocking, or wildly inappropriate jokes between people.
_ABSURD_BANTER = (
    "i'm not gonna lie",
    "bro that's crazy",
    "you're actually insane",
    "that's wild",
    "no way",
    "you're cooked",
    "bro is cooked",
    "you're cooked bro",
    "bro what",
    "that's actually terrible",
    "i can't believe",
    "did he actually",
    "he really said",
    "the audacity",
    "chat is he serious",
)
_ABSURD_BANTER_HI = (
    "pagal hai tu",
    "teri toh",
    "bhai ye kya kar raha hai",
    "seriously yaar",
    "tu normal nahi hai",
    "bhai seedha bol",
    "chat dekho",
    "iska dimag kharab hai",
    "bhai ye banda",
    "ye log pagal hain",
    "kya bol raha hai bhai",
    "genuine mein",
    "yaar sun toh",
    "iska scene kya hai",
    "bhai ye toh gayi baat",
)

# uncontrollable_reaction: Someone loses composure — laughing, screaming, wheezing.
_UNCONTROLLABLE_REACTION = (
    "[laughing]",
    "[screaming]",
    "[wheezing]",
    "[gasping]",
    "[moaning]",
    "[crying]",
    "[dying]",
    "i can't",
    "i'm dead",
    "i'm dying",
    "i'm crying",
    "stop stop stop",
    "bro i'm dead",
    "chat he's dead",
    "he's crying",
    "i can't breathe",
    "i'm wheezing",
    "i lost it",
    "bro i lost it",
)
_UNCONTROLLABLE_REACTION_HI = (
    "[hansi]",
    "[cheekh]",
    "bhai ruk",
    "yaar band kar",
    "bhai hasi aa rahi hai",
    "ruk yaar",
    "nahi nahi nahi",
    "bhai mujhe hasi aa rahi hai",
    "yaar mujhe ro raha hai hasi se",
    "band karo yaar",
    "bhai ye toh limit ho gayi",
)

# out_of_context_statement: A random line that sounds completely insane alone.
_OUT_OF_CONTEXT = (
    "out of context",
    "context aside",
    "without context",
    "that sounds so wrong out of context",
    "okay without context",
    "clip that",
    "someone clip that",
    "that's a clip",
    "chat clip that",
    "please don't clip that",
    "that's going on twitter",
    "i know how that sounds",
    "that came out wrong",
)
_OUT_OF_CONTEXT_HI = (
    "ye clip karo",
    "bhai ye clip ho gaya",
    "context nahi pata isko",
    "ye toh context ke bahar hai",
    "bhai ye sun ke kuch aur lagta hai",
    "twitter pe daal do",
    "clip ho gaya",
    "ye mat daalna kahi",
    "bhai galat lagta hai",
)

# recurring_bit: A strange nickname / rumor / theory that keeps returning.
_RECURRING_BIT = (
    "not this again",
    "here we go again",
    "he's doing it again",
    "every time",
    "this guy again",
    "not him again",
    "back to this",
    "the legend",
    "the infamous",
    "as always",
    "the usual",
    "bring it back",
    "we talked about this",
    "not again bro",
)
_RECURRING_BIT_HI = (
    "phir wahi baat",
    "ye banda phir",
    "phir se ye shuru",
    "ye toh hamesha aisa karta hai",
    "ek baar phir",
    "arey phir se",
    "ye wala topic phir aaya",
    "bhai ye toh classic hai",
    "isko toh pata hi tha",
    "ye toh guaranteed tha",
)

_TRIGGER_MAP = {
    "belief_reversal":        _BELIEF_REVERSAL      + _BELIEF_REVERSAL_HI,
    "secret_revelation":      _SECRET_REVELATION    + _SECRET_REVELATION_HI,
    "mistake_explanation":    _MISTAKE_EXPLANATION  + _MISTAKE_EXPLANATION_HI,
    "strong_claim":           _STRONG_CLAIM         + _STRONG_CLAIM_HI,
    "payoff":                 _PAYOFF               + _PAYOFF_HI,
    # ── Creator-Psychology Hooks (Hormozi / Gadzhi / top creator patterns) ────
    "pattern_interrupt":      _PATTERN_INTERRUPT    + _PATTERN_INTERRUPT_HI,
    "curiosity_gap":          _CURIOSITY_GAP        + _CURIOSITY_GAP_HI,
    "bold_promise":           _BOLD_PROMISE         + _BOLD_PROMISE_HI,
    "social_proof_hook":      _SOCIAL_PROOF_HOOK    + _SOCIAL_PROOF_HOOK_HI,
    # ── Chaos / Entertainment triggers ──────────────────────────────────────
    "chaos_digression":       _CHAOS_DIGRESSION     + _CHAOS_DIGRESSION_HI,
    "cursed_escalation":      _CURSED_ESCALATION    + _CURSED_ESCALATION_HI,
    "absurd_banter":          _ABSURD_BANTER        + _ABSURD_BANTER_HI,
    "uncontrollable_reaction":_UNCONTROLLABLE_REACTION + _UNCONTROLLABLE_REACTION_HI,
    "out_of_context_statement":_OUT_OF_CONTEXT      + _OUT_OF_CONTEXT_HI,
    "recurring_bit":          _RECURRING_BIT        + _RECURRING_BIT_HI,
}

# Contrast markers — English + Hindi Devanagari + Hinglish romanized
_CONTRAST_MARKERS = (
    "but", "however", "instead", "yet", "in reality", "actually",
    "lekin", "parantu", "magar", "par",  # Hinglish
    "लेकिन", "परंतु", "मगर", "पर",       # Devanagari
)
_NEG_WORDS = (
    "not", "never", "wrong", "can't", "dont", "don't", "no",
    "nahi", "galat", "mat",  # Hinglish
    "नहीं", "गलत", "मत",     # Devanagari
)
_POS_WORDS = (
    "best", "right", "works", "truth", "real", "clear",
    "sahi", "sach", "asli",  # Hinglish
    "सही", "सच", "असली",     # Devanagari
)


def _sentiment_proxy_shift(text: str) -> float:
    t = str(text or "").lower()
    pos = sum(1 for w in _POS_WORDS if w in t)
    neg = sum(1 for w in _NEG_WORDS if w in t)
    # normalized polarity shift proxy in [0, 1]
    if pos == 0 and neg == 0:
        return 0.0
    return min(1.0, abs(pos - neg) / float(max(1, pos + neg)))


def _confidence_for_phrase(text_lower: str, phrase: str) -> float:
    score = 0.4  # phrase match
    if any(m in text_lower for m in _CONTRAST_MARKERS):
        score += 0.3
    score += 0.3 * _sentiment_proxy_shift(text_lower)
    return max(0.0, min(1.0, score))



def _run_sliding_window_detection(transcript_segments: List[Dict], log: logging.Logger) -> List[Dict]:
    import uuid
    triggers: List[Dict] = []
    total_phrases_checked = 0
    total_segments = len(transcript_segments or [])
    
    # Pre-compile regexes for flexibility (ignore punctuation/spacing between words)
    import re
    compiled_patterns = {}
    for t_type, phrases in _TRIGGER_MAP.items():
        compiled_patterns[t_type] = []
        for p in phrases:
            # allow optional spaces, commas, or filler words
            regex_str = r'\b' + p.replace(' ', r'(?:\s+|,|\bu\b|\buh\b|\bum\b|\bhi\b)+') + r'\b'
            compiled_patterns[t_type].append((p, re.compile(regex_str, re.IGNORECASE)))

    # Window size of 3 segments (approx 5-10 seconds of speech)
    WINDOW_SIZE = 3
    
    for i in range(total_segments):
        window = transcript_segments[i:i+WINDOW_SIZE]
        if not window:
            continue
            
        combined_text = " ".join(str(s.get("text", "")).strip() for s in window).lower()
        if not combined_text.strip():
            continue
            
        start = float(window[0].get("start", 0.0))
        end = float(window[-1].get("end", start))
        if end <= start:
            continue
            
        for trigger_type, patterns in compiled_patterns.items():
            for original_phrase, pattern in patterns:
                total_phrases_checked += 1
                if pattern.search(combined_text) or original_phrase in combined_text:
                    conf = _confidence_for_phrase(combined_text, original_phrase)
                    
                    # Avoid duplicate overlapping triggers
                    if triggers and triggers[-1]["type"] == trigger_type and abs(triggers[-1]["start"] - start) < 10.0:
                        continue
                        
                    log.info(f"[TRIGGER_FORENSIC_SLIDING] MATCH! Phrase: '{original_phrase}' (Type: {trigger_type}) | Conf: {conf:.2f} | Text: '{combined_text[:60]}...'")
                    triggers.append({
                        "id": uuid.uuid4().hex,
                        "start": start,
                        "end": end,
                        "type": trigger_type,
                        "confidence": round(float(conf), 4),
                        "text": combined_text,
                        "phrase": original_phrase,
                        "span": {"start": start, "end": end},
                    })
                    break
    
    if not triggers:
        log.warning(f"[TRIGGER_FORENSIC_SLIDING] ZERO triggers found. Evaluated {total_phrases_checked} combinations in windows.")
    return triggers

def _run_llm_detection(transcript_segments: List[Dict], log: logging.Logger) -> List[Dict]:
    api_key = _get_groq_api_key()
    gemini_enabled = is_gemini_enabled()
    
    if not api_key and not gemini_enabled:
        log.warning("No API keys found for Trigger LLM. Falling back to sliding window.")
        return _run_sliding_window_detection(transcript_segments, log)

    # Chunk transcript into max 4-minute chunks to avoid massive token limits
    # and provide start/end times clearly.
    chunks = []
    current_chunk = []
    current_duration = 0
    for seg in transcript_segments:
        dur = seg.get("end", 0) - seg.get("start", 0)
        current_chunk.append(seg)
        current_duration += dur
        if current_duration > 240: # 4 mins
            chunks.append(current_chunk)
            current_chunk = []
            current_duration = 0
    if current_chunk:
        chunks.append(current_chunk)

    from viral_finder.cognition import TriggerArtifact
    import uuid
    import time as _time

    all_triggers = []
    failed_chunks: list[int] = []  # track which chunk indices fully failed
    MAX_CHUNK_RETRIES = 3

    for chunk_idx, segs_to_use in enumerate(chunks):
        if chunk_idx > 0:
            if not gemini_enabled:
                log.info(f"[TRIGGER_FORENSIC_LLM] Waiting 8 seconds before chunk {chunk_idx+1}/{len(chunks)} to respect TPM limits...")
                _time.sleep(8.0)
            else:
                log.info(f"[TRIGGER_FORENSIC_LLM] Preparing chunk {chunk_idx+1}/{len(chunks)} for Gemini...")

        transcript_text = ""
        for s in segs_to_use:
            transcript_text += f"[{s.get('start', 0):.1f}-{s.get('end', 0):.1f}] {s.get('text', '')}\n"

        prompt = f"""You are an expert short-form content editor with the combined instincts of Alex Hormozi's offer team, Iman Gadzhi's retention engineers, and a MrBeast editor.
Your job: find "Narrative Triggers" — moments where the brain STOPS scrolling and locks in.

You think like a CONTENT CREATOR, not an academic. You know what hooks people, what creates open loops, what makes someone stop mid-scroll and say "wait, I need to hear this."

Find triggers in two categories:

CATEGORY A — INFORMATIONAL / CREATOR HOOKS (education, podcast, founder, self-improvement content):
These are the patterns top creators use to hijack attention:

1. "belief_reversal": Challenges what the viewer already believes. The brain MUST resolve the contradiction.
   Examples: "most people think X... but actually Y", "everyone says X, but I made millions doing the opposite", "you've been lied to about X"

2. "secret_revelation": Reveals hidden information the viewer feels they should have known. Creates FOMO.
   Examples: "the real reason X isn't working for you", "what nobody tells you", "the thing they don't want you to know", "I discovered something that changed everything"

3. "mistake_explanation": Makes the viewer realize they are doing something wrong RIGHT NOW. Immediate stakes.
   Examples: "this is why you're failing", "stop doing X", "the worst thing you can do is X (and everyone does it)", "I wasted years doing this wrong"

4. "strong_claim": A bold, definitive, often controversial statement that demands attention.
   Examples: "unpopular opinion", "I'll be real with you", "no one wants to hear this but", "this will make you uncomfortable"

5. "payoff": The resolution, takeaway, or reward the viewer has been waiting for.
   Examples: "so basically", "the takeaway is", "here's what to do", "the bottom line"

6. "complete_thought": A self-contained idea that stands alone as a clip.

7. "pattern_interrupt": An identity challenge that makes the viewer check themselves. Forces self-reflection.
   HORMOZI FORMULA: "If you're [identity] and you're not doing [X], you are leaving [Y] on the table."
   Examples: "if you're still doing X", "the only reason you haven't Y yet is", "this is the difference between winners and losers", "I went from 0 to $1M and here's the ONE thing", "i wish someone told me this"

8. "curiosity_gap": Creates an open loop the brain CANNOT close without watching more. Cognitive itch.
   GADZHI FORMULA: Name the thing, then withhold HOW — the brain must stay to resolve it.
   Examples: "here's the thing nobody mentions", "and this is where it gets crazy", "but here's the twist", "you won't believe what happened", "the crazy part is", "but wait"

9. "bold_promise": A specific, measurable, results-driven claim backed by proof. High-contrast value delivery.
   HORMOZI OFFER FRAMEWORK: Specificity (numbers) + Timeline + Without (objection removal)
   Examples: "I made X in Y days doing exactly this", "this one thing tripled my revenue", "in 30 days without X", "you don't need money/connections/experience to do this"

10. "social_proof_hook": Uses contrast between successful and unsuccessful people to trigger identity anxiety.
    Examples: "every successful person does this one thing", "rich people know X, poor people think Y", "what winners do vs what losers do", "the common thread among all self-made millionaires"

CATEGORY B — CHAOS / ENTERTAINMENT (streaming, gaming, variety content):
These are NOT educational. They go viral purely because they are bizarre, cursed, or absurd:

11. "chaos_digression": Normal conversation suddenly derails into something completely bizarre ("wait what", "ruk ruk ruk", "bhai sun", "yaar ye kya ho gaya")
12. "cursed_escalation": One harmless comment starts a chain that keeps getting more unhinged ("and then he said", "it gets worse", "abhi toh aur suno")
13. "absurd_banter": Outrageous roasting or jokes that make you say "WHAT?" ("pagal hai tu", "you're actually insane", "bro that's crazy")
14. "uncontrollable_reaction": Someone completely loses composure ("[laughing]", "[screaming]", "i'm dead", "bhai hasi aa rahi hai")
15. "out_of_context_statement": A line that sounds completely insane without context ("clip that", "ye clip karo", "that came out wrong")
16. "recurring_bit": A strange nickname/theory/accusation that keeps returning ("here we go again", "phir wahi baat")

The transcript is in English, Hindi, or Hinglish. It may be from any content type.
Identify the exact timestamps where these triggers occur — BOTH creator hooks and chaos triggers.

CRITICAL INSTRUCTION: For every trigger you find, you MUST provide psychological metrics (0.0 to 100.0):

For INFORMATIONAL / CREATOR triggers (types 1-10):
- stop_scroll: How hard does this STOP the scroll? (Think: would you stop mid-swipe?)
- curiosity: How strong is the open loop? (Is the brain forced to keep watching to resolve it?)
- memorability: Will this phrase stick in someone's head hours later?
- shareability: Would someone send this to a friend saying "bro watch this"?
- novelty: Is this genuinely surprising or counterintuitive?
- hook_strength: How powerful is this as a SHORT-FORM HOOK specifically? (Hormozi test: does it make you stop?)
- identity_challenge: Does this make the viewer question their current identity or choices?
- belief_reversal: How strongly does this challenge a common belief?
- emotional_charge: How much emotion (urgency, fear, hope, anger) does this evoke?

For CHAOS triggers (types 11-16), score INSTEAD:
- stop_scroll, chaos_score, quotability, reaction_energy, escalation_wildness, out_of_context_shock, emotional_charge, shareability

CRITICAL RULE FOR CREATOR HOOKS: The strongest clips have a hook that creates TENSION (the viewer doesn't have the answer yet) and a payoff that RESOLVES it. Flag both. Don't just find hooks — find the matching payoff too.
CRITICAL RULE FOR CHAOS: The chaos IS the payoff. No educational value needed.
CRITICAL INSTRUCTION: Provide a "reason" — 1 sentence explaining exactly why this is a powerful trigger.

Return ONLY valid JSON:
{{
    "content_mode": "informational" or "entertainment_chaos" or "mixed",
    "triggers": [
        {{
            "type": "pattern_interrupt",
            "start": 12.5,
            "end": 15.0,
            "phrase": "the exact phrase from transcript",
            "confidence": 0.0_to_100.0,
            "psychology": {{
                "stop_scroll": 0.0_to_100.0,
                "curiosity": 0.0_to_100.0,
                "memorability": 0.0_to_100.0,
                "shareability": 0.0_to_100.0,
                "novelty": 0.0_to_100.0,
                "hook_strength": 0.0_to_100.0,
                "identity_challenge": 0.0_to_100.0,
                "belief_reversal": 0.0_to_100.0,
                "emotional_charge": 0.0_to_100.0,
                "chaos_score": 0.0_to_100.0,
                "quotability": 0.0_to_100.0,
                "reaction_energy": 0.0_to_100.0,
                "escalation_wildness": 0.0_to_100.0,
                "out_of_context_shock": 0.0_to_100.0
            }},
            "reason": "1-sentence explanation of why this is a powerful trigger — be specific, not generic"
        }}
    ]
}}

IMPORTANT: Each trigger MUST have different psychology scores based on the actual content. Do NOT copy-paste scores from one trigger to another.

Transcript:
{transcript_text}
"""

        chunk_succeeded = False
        last_exc: Exception | None = None

        for attempt in range(1, MAX_CHUNK_RETRIES + 1):
            try:
                if gemini_enabled:
                    raw_resp_text = post_gemini_completions(prompt=prompt, response_format_schema={"type": "json_object"})
                    data = parse_gemini_json_safely(raw_resp_text)
                else:
                    resp = post_groq_completions(
                        payload={
                            "model": _get_groq_model(),
                            "messages": [{"role": "user", "content": prompt}],
                            "temperature": 0.1,
                            "response_format": {"type": "json_object"}
                        },
                        timeout=_get_timeout(),
                        max_retries=3
                    )
                    if not resp.ok:
                        raise requests.exceptions.HTTPError(f"{resp.status_code} Client Error: {resp.text}")
                    data = parse_groq_json_safely(resp.json()["choices"][0]["message"]["content"])
                    
                raw_triggers = data.get("triggers", [])
                found_in_chunk = 0
                for t in raw_triggers:
                    # Normalize 0-100 values back to 0.0-1.0 for downstream math
                    raw_conf = float(t.get("confidence", 0.8))
                    conf = raw_conf / 100.0 if raw_conf > 1.0 else raw_conf
                    t["confidence"] = conf
                    
                    psy = t.get("psychology", {})
                    for k, v in psy.items():
                        try:
                            val = float(v)
                            psy[k] = val / 100.0 if val > 1.0 else val
                        except (ValueError, TypeError):
                            psy[k] = 0.0
                            
                    log.info(
                        f"[TRIGGER_FORENSIC_LLM] MATCH"
                        f" | type={t.get('type')}"
                        f" | conf={conf:.2f}"
                        f" | time={t.get('start'):.1f}-{t.get('end'):.1f}s"
                        f" | stop_scroll={psy.get('stop_scroll', 0.0):.2f}"
                        f" hook_strength={psy.get('hook_strength', 0.0):.2f}"
                        f" identity_challenge={psy.get('identity_challenge', 0.0):.2f}"
                        f" curiosity={psy.get('curiosity', 0.0):.2f}"
                        f" memorability={psy.get('memorability', 0.0):.2f}"
                        f" shareability={psy.get('shareability', 0.0):.2f}"
                        f" belief_reversal={psy.get('belief_reversal', 0.0):.2f}"
                        f" emotional_charge={psy.get('emotional_charge', 0.0):.2f}"
                        f" chaos_score={psy.get('chaos_score', 0.0):.2f}"
                        f" quotability={psy.get('quotability', 0.0):.2f}"
                        f" | reason='{t.get('reason', '')}'"
                        f" | phrase='{t.get('phrase', '')[:80]}'"
                    )

                    artifact = TriggerArtifact(
                        trigger_type=str(t.get("type", "unknown")),
                        psychology=psy,
                        reason=str(t.get("reason", "")),
                        confidence=conf,
                        trace_id=str(uuid.uuid4())
                    )

                    all_triggers.append({
                        "id": uuid.uuid4().hex,
                        "start": float(t.get("start", 0)),
                        "end": float(t.get("end", 0)),
                        "type": artifact.trigger_type.lower().strip(),
                        "confidence": artifact.confidence,
                        "text": str(t.get("phrase", "")),
                        "phrase": str(t.get("phrase", "")),
                        "psychology": psy,
                        "span": {"start": float(t.get("start", 0)), "end": float(t.get("end", 0))},
                        "artifact": artifact
                    })
                    found_in_chunk += 1
                log.info(f"[TRIGGER_FORENSIC_LLM] Chunk {chunk_idx+1} complete: {found_in_chunk} triggers found.")
                chunk_succeeded = True
                break  # success — stop retrying this chunk

            except Exception as e:
                last_exc = e
                backoff = 2 ** attempt  # 2s, 4s, 8s
                log.warning(
                    f"[TRIGGER_FORENSIC_LLM] Chunk {chunk_idx+1} attempt {attempt}/{MAX_CHUNK_RETRIES} FAILED: {e}. "
                    f"{'Retrying in ' + str(backoff) + 's...' if attempt < MAX_CHUNK_RETRIES else 'All retries exhausted.'}"
                )
                if attempt < MAX_CHUNK_RETRIES:
                    _time.sleep(backoff)

        if not chunk_succeeded:
            failed_chunks.append(chunk_idx)
            log.error(
                f"[TRIGGER_FORENSIC_LLM] ⚠️ CHUNK {chunk_idx+1}/{len(chunks)} PERMANENTLY FAILED after {MAX_CHUNK_RETRIES} attempts. "
                f"Last error: {last_exc}. "
                f"Segs {segs_to_use[0].get('start', 0):.1f}s–{segs_to_use[-1].get('end', 0):.1f}s will have NO trigger analysis."
            )

    # ── Coverage audit: emit a loud WARNING if any chunks were lost ───────────────────
    if failed_chunks:
        total_chunks = len(chunks)
        failed_count = len(failed_chunks)
        failed_segs = sum(len(chunks[i]) for i in failed_chunks)
        total_segs = len(transcript_segments)
        pct_unanalyzed = (failed_segs / total_segs * 100) if total_segs else 0
        failed_chunk_labels = ", ".join(str(i + 1) for i in failed_chunks)
        log.warning(
            f"[TRIGGER_FORENSIC_LLM] ⚠️ COVERAGE ALERT: {failed_count}/{total_chunks} chunks failed "
            f"(chunks: {failed_chunk_labels}). "
            f"{failed_segs}/{total_segs} segments unanalyzed = {pct_unanalyzed:.1f}% of transcript "
            f"has NO trigger intelligence. Downstream clip quality will be degraded."
        )

    # Fallback to sliding window if LLM found 0 (it might have failed or hallucinated)
    if not all_triggers:
        log.warning("[TRIGGER_FORENSIC_LLM] LLM returned 0 triggers. Falling back to Sliding Window.")
        return _run_sliding_window_detection(transcript_segments, log)

    return all_triggers



def detect_narrative_triggers(transcript_segments: List[Dict]) -> List[Dict]:
    import logging
    log = logging.getLogger(__name__)
    
    if is_groq_enabled():
        log.info("[TRIGGER_FORENSIC] Using LLM Intelligence Dataset for trigger detection.")
        return _run_llm_detection(transcript_segments, log)
    else:
        log.info("[TRIGGER_FORENSIC] Using Sliding Window exact/regex detection.")
        return _run_sliding_window_detection(transcript_segments, log)


def build_narrative_contracts(triggers: List[Dict]) -> List[Any]:
    """
    Narrative Contract Engine (Priority 1).
    
    Pairs every debt-creating trigger (hook) with the best debt-resolving
    trigger (payoff) within a 10-180s window. Returns NarrativeContract objects.
    
    Trigger classification:
      Debt-creators (HOOKS):  strong_claim, belief_reversal, secret_revelation,
                              mistake_explanation
      Debt-resolvers (PAYOFFS): payoff, complete_thought
      Both roles:             complete_thought (can open AND close)
    
    Pairing algorithm:
      - For each hook, find the highest-scoring payoff trigger within [10s, 180s]
      - A payoff can only resolve ONE hook (greedy: best contract_score wins)
      - Unresolved hooks: contract stored with resolution_score=0.0 → penalized in UVS
    """
    import uuid
    import logging
    log = logging.getLogger(__name__)

    try:
        from viral_finder.cognition import NarrativeContract
    except ImportError:
        log.warning("[NCE] NarrativeContract not importable — skipping contract engine")
        return []

    if not triggers:
        return []

    HOOK_TYPES = {"strong_claim", "belief_reversal", "secret_revelation", "mistake_explanation", "complete_thought"}
    PAYOFF_TYPES = {"payoff", "complete_thought"}
    # Maximum gap between hook end and payoff start
    MIN_GAP_S = 5.0
    MAX_GAP_S = 180.0

    # Compute a composite psychology score for a trigger
    def _psych_score(tr: dict) -> float:
        psy = tr.get("psychology", {}) or {}
        conf = float(tr.get("confidence", 0.5))
        stop = float(psy.get("stop_scroll", 0.0))
        cur  = float(psy.get("curiosity", 0.0))
        mem  = float(psy.get("memorability", 0.0))
        sha  = float(psy.get("shareability", 0.0))
        # Weighted average of psychology + base confidence
        raw = (0.30 * stop + 0.30 * cur + 0.25 * mem + 0.15 * sha)
        return max(conf * 0.4 + raw * 0.6, conf * 0.5)

    # Separate into hooks and payoffs (case-insensitive)
    hooks   = [t for t in triggers if t.get("type", "").lower().strip() in HOOK_TYPES]
    payoffs = [t for t in triggers if t.get("type", "").lower().strip() in PAYOFF_TYPES]

    hooks.sort(key=lambda t: float(t.get("start", 0.0)))
    payoffs.sort(key=lambda t: float(t.get("start", 0.0)))

    # Generate all valid (hook, payoff) candidate pairs
    all_candidates = []
    for h_idx, hook in enumerate(hooks):
        h_start = float(hook.get("start", 0.0))
        h_end   = float(hook.get("end", h_start))
        hook_score = _psych_score(hook)

        for p_idx, p in enumerate(payoffs):
            p_start = float(p.get("start", 0.0))
            gap = p_start - h_end
            if gap < MIN_GAP_S or gap > MAX_GAP_S:
                continue

            payoff_score = _psych_score(p)
            # Score this pairing: hook × payoff psychology × proximity bonus
            proximity_bonus = max(0.0, 1.0 - (gap / MAX_GAP_S))  # 1.0 at 0s gap, 0.0 at 180s
            pair_score = hook_score * payoff_score * (0.7 + 0.3 * proximity_bonus)
            
            all_candidates.append({
                "h_idx": h_idx,
                "p_idx": p_idx,
                "hook": hook,
                "payoff": p,
                "pair_score": pair_score,
                "hook_score": hook_score,
                "payoff_score": payoff_score
            })

    # Sort ALL candidates globally by pair_score descending
    # This prevents "chronological shadowing" where a weak early hook steals the best payoff
    all_candidates.sort(key=lambda c: c["pair_score"], reverse=True)

    used_hooks = set()
    used_payoffs = set()
    contracts = []

    # Greedily lock in the absolute strongest pairs first
    for cand in all_candidates:
        if cand["h_idx"] in used_hooks or cand["p_idx"] in used_payoffs:
            continue

        used_hooks.add(cand["h_idx"])
        used_payoffs.add(cand["p_idx"])
        
        hook = cand["hook"]
        best_payoff = cand["payoff"]
        
        contract = NarrativeContract(
            hook_trigger=hook,
            payoff_trigger=best_payoff,
            hook_start=float(hook.get("start", 0.0)),
            payoff_end=float(best_payoff.get("end", 0.0)),
            debt_score=round(cand["hook_score"], 4),
            resolution_score=round(cand["payoff_score"], 4),
            contract_score=round(cand["pair_score"], 4),
            hook_type=str(hook.get("type", "unknown")).lower().strip(),
            payoff_type=str(best_payoff.get("type", "unknown")).lower().strip(),
            trace_id=str(uuid.uuid4()),
        )
        log.info(
            f"[NCE] CONTRACT: {contract.hook_type}@{contract.hook_start:.1f}s → "
            f"{contract.payoff_type}@{float(best_payoff.get('start', 0)):.1f}s | "
            f"debt={contract.debt_score:.3f} resolution={contract.resolution_score:.3f} "
            f"score={contract.contract_score:.3f}"
        )
        contracts.append(contract)

    # Any hooks that didn't get a payoff become unresolved contracts
    for h_idx, hook in enumerate(hooks):
        if h_idx not in used_hooks:
            h_start = float(hook.get("start", 0.0))
            h_end   = float(hook.get("end", h_start))
            hook_score = _psych_score(hook)
            
            contract = NarrativeContract(
                hook_trigger=hook,
                payoff_trigger={},
                hook_start=h_start,
                payoff_end=h_end,
                debt_score=round(hook_score, 4),
                resolution_score=0.0,
                contract_score=0.0,
                hook_type=str(hook.get("type", "unknown")).lower().strip(),
                payoff_type="none",
                trace_id=str(uuid.uuid4()),
            )
            log.info(
                f"[NCE] UNRESOLVED HOOK: {contract.hook_type}@{h_start:.1f}s "
                f"debt={contract.debt_score:.3f} — no payoff found within {MAX_GAP_S}s"
            )
            contracts.append(contract)

    log.info(f"[NCE] Built {len(contracts)} contracts: "
             f"{sum(1 for c in contracts if c.resolution_score > 0)} resolved, "
             f"{sum(1 for c in contracts if c.resolution_score == 0)} unresolved hooks")
    return contracts

