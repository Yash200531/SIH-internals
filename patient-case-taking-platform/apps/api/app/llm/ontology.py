"""Small, clinician-reviewable ontology used by the deterministic mock provider."""

SOCRATES_DOMAINS = (
    "site",
    "onset",
    "character",
    "radiation",
    "associated_symptoms",
    "timing",
    "exacerbating_relieving_factors",
    "severity",
)

SOCRATES_QUESTIONS = {
    "en": {
        "site": "Where exactly do you feel the problem?",
        "onset": "When did it begin, and did it start suddenly or gradually?",
        "character": "How would you describe what it feels like?",
        "radiation": "Does it spread anywhere else?",
        "associated_symptoms": "What other symptoms are you having with it?",
        "timing": "Is it constant, or does it come and go?",
        "exacerbating_relieving_factors": "What makes it better or worse?",
        "severity": "On a scale from 0 to 10, how severe is it?",
    },
    "hi": {
        "site": "समस्या या दर्द ठीक कहाँ महसूस हो रहा है?",
        "onset": "यह कब शुरू हुआ, अचानक या धीरे-धीरे?",
        "character": "यह कैसा महसूस होता है? अपने शब्दों में बताइए।",
        "radiation": "क्या दर्द या तकलीफ शरीर के किसी और हिस्से में फैलती है?",
        "associated_symptoms": "इसके साथ और कौन-से लक्षण हो रहे हैं?",
        "timing": "यह लगातार रहता है या बीच-बीच में होता है?",
        "exacerbating_relieving_factors": "किस चीज़ से यह बढ़ता या कम होता है?",
        "severity": "0 से 10 तक, तकलीफ कितनी गंभीर है?",
    },
}
