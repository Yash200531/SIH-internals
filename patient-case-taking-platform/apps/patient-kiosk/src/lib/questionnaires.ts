export interface Question {
  id: string;
  type: "single_select" | "multi_select" | "yes_no" | "text" | "number" | "scale";
  label: { en: string; hi: string };
  audio: { en: string; hi: string };
  options?: { value: string; label: { en: string; hi: string }; icon?: string }[];
  required: boolean;
  next?: (answer: string | string[]) => string; // conditional navigation
}

export interface QuestionnaireSection {
  id: string;
  title: { en: string; hi: string };
  icon: string;
  questions: Question[];
}

export interface Questionnaire {
  id: string;
  type: "allopathic" | "ayush";
  title: { en: string; hi: string };
  sections: QuestionnaireSection[];
}

/** Preserve the meaning of confirmed choices rather than submitting opaque option codes. */
export function describeAnswers(
  questionnaire: Questionnaire | null,
  answers: Record<string, string | string[]>,
  language: "en" | "hi",
): Record<string, string> {
  const questions = questionnaire?.sections.flatMap((section) => section.questions) || [];
  return Object.fromEntries(Object.entries(answers).map(([key, value]) => {
    const question = questions.find((item) => item.id === key);
    const describe = (answer: string) => question?.options?.find((option) => option.value === answer)?.label[language] || answer;
    return [key, Array.isArray(value) ? value.map(describe).join(", ") : describe(value)];
  }));
}

export const ALLOPATHIC_HISTORY: Questionnaire = {
  id: "allopathic_history",
  type: "allopathic",
  title: { en: "Medical History", hi: "चिकित्सा इतिहास" },
  sections: [
    {
      id: "chief_complaint",
      title: { en: "Chief Complaint", hi: "मुख्य शिकायत" },
      icon: "🩺",
      questions: [
        {
          id: "cc_main",
          type: "single_select",
          label: { en: "What is your main problem today?", hi: "आज आपकी मुख्य समस्या क्या है?" },
          audio: { en: "What is your main problem today?", hi: "आज आपकी मुख्य समस्या क्या है?" },
          options: [
            { value: "fever", label: { en: "Fever", hi: "बुखार" }, icon: "🌡️" },
            { value: "cough", label: { en: "Cough", hi: "खांसी" }, icon: "😷" },
            { value: "headache", label: { en: "Headache", hi: "सिरदर्द" }, icon: "🤕" },
            { value: "stomach_pain", label: { en: "Stomach Pain", hi: "पेट दर्द" }, icon: "🤰" },
            { value: "body_pain", label: { en: "Body Pain", hi: "शरीर में दर्द" }, icon: "💪" },
            { value: "breathing", label: { en: "Breathing Difficulty", hi: "सांस लेने में तकलीफ" }, icon: "🫁" },
            { value: "skin", label: { en: "Skin Problem", hi: "त्वचा की समस्या" }, icon: "🖐️" },
            { value: "other", label: { en: "Other", hi: "अन्य" }, icon: "📝" },
          ],
          required: true,
        },
        {
          id: "cc_duration",
          type: "single_select",
          label: { en: "How long have you had this problem?", hi: "यह समस्या कितने दिनों से है?" },
          audio: { en: "How long have you had this problem?", hi: "यह समस्या कितने दिनों से है?" },
          options: [
            { value: "today", label: { en: "Today", hi: "आज" } },
            { value: "2-3_days", label: { en: "2-3 days", hi: "2-3 दिन" } },
            { value: "week", label: { en: "About a week", hi: "लगभग एक हफ्ता" } },
            { value: "months", label: { en: "More than a month", hi: "एक महीने से ज्यादा" } },
            { value: "years", label: { en: "Years", hi: "कई साल" } },
          ],
          required: true,
        },
        {
          id: "cc_severity",
          type: "scale",
          label: { en: "How bad is the pain? (1 = mild, 10 = worst)", hi: "दर्द कितना है? (1 = हल्का, 10 = बहुत ज्यादा)" },
          audio: { en: "How bad is the pain? 1 is mild, 10 is worst.", hi: "दर्द कितना है? 1 हल्का है, 10 बहुत ज्यादा है।" },
          required: false,
        },
      ],
    },
    {
      id: "past_history",
      title: { en: "Past Medical History", hi: "पिछला चिकित्सा इतिहास" },
      icon: "📋",
      questions: [
        {
          id: "ph_diabetes",
          type: "yes_no",
          label: { en: "Do you have diabetes?", hi: "क्या आपको मधुमेह है?" },
          audio: { en: "Do you have diabetes?", hi: "क्या आपको मधुमेह है?" },
          required: true,
        },
        {
          id: "ph_blood_pressure",
          type: "yes_no",
          label: { en: "Do you have high blood pressure?", hi: "क्या आपका ब्लड प्रेशर बढ़ा हुआ है?" },
          audio: { en: "Do you have high blood pressure?", hi: "क्या आपका ब्लड प्रेशर बढ़ा हुआ है?" },
          required: true,
        },
        {
          id: "ph_heart",
          type: "yes_no",
          label: { en: "Do you have any heart problem?", hi: "क्या आपको कोई हृदय रोग है?" },
          audio: { en: "Do you have any heart problem?", hi: "क्या आपको कोई हृदय रोग है?" },
          required: true,
        },
        {
          id: "ph_surgeries",
          type: "multi_select",
          label: { en: "Have you had any surgeries?", hi: "क्या आपकी कोई सर्जरी हुई है?" },
          audio: { en: "Have you had any surgeries?", hi: "क्या आपकी कोई सर्जरी हुई है?" },
          options: [
            { value: "none", label: { en: "No surgeries", hi: "कोई सर्जरी नहीं" } },
            { value: "appendix", label: { en: "Appendix", hi: "एपेंडिक्स" } },
            { value: "hernia", label: { en: "Hernia", hi: "हर्निया" } },
            { value: "gallbladder", label: { en: "Gallbladder", hi: "पित्ताशय" } },
            { value: "cesarean", label: { en: "C-Section", hi: "सिजेरियन" } },
            { value: "other", label: { en: "Other", hi: "अन्य" } },
          ],
          required: true,
        },
      ],
    },
    {
      id: "medications",
      title: { en: "Current Medications", hi: "वर्तमान दवाइयां" },
      icon: "💊",
      questions: [
        {
          id: "med_current",
          type: "yes_no",
          label: { en: "Are you currently taking any medicines?", hi: "क्या आप अभी कोई दवाइयां ले रहे हैं?" },
          audio: { en: "Are you currently taking any medicines?", hi: "क्या आप अभी कोई दवाइयां ले रहे हैं?" },
          required: true,
        },
        {
          id: "med_names",
          type: "multi_select",
          label: { en: "Which medicines?", hi: "कौन सी दवाइयां?" },
          audio: { en: "Which medicines are you taking?", hi: "आप कौन सी दवाइयां ले रहे हैं?" },
          options: [
            { value: "none", label: { en: "No medicines", hi: "कोई दवाइयां नहीं" } },
            { value: "bp_medicine", label: { en: "BP medicine", hi: "बीपी की दवा" } },
            { value: "sugar_medicine", label: { en: "Sugar/Diabetes medicine", hi: "शुगर की दवा" } },
            { value: "thyroid_medicine", label: { en: "Thyroid medicine", hi: "थायरॉयड की दवा" } },
            { value: "pain_killers", label: { en: "Pain killers", hi: "दर्द की दवा" } },
            { value: "antibiotics", label: { en: "Antibiotics", hi: "एंटीबायोटिक" } },
            { value: "other", label: { en: "Other", hi: "अन्य" } },
          ],
          required: false,
        },
      ],
    },
    {
      id: "allergies",
      title: { en: "Allergies", hi: "एलर्जी" },
      icon: "⚠️",
      questions: [
        {
          id: "al_any",
          type: "yes_no",
          label: { en: "Do you have any allergies?", hi: "क्या आपको कोई एलर्जी है?" },
          audio: { en: "Do you have any allergies?", hi: "क्या आपको कोई एलर्जी है?" },
          required: true,
        },
        {
          id: "al_type",
          type: "multi_select",
          label: { en: "What are you allergic to?", hi: "आपको किस चीज़ से एलर्जी है?" },
          audio: { en: "What are you allergic to?", hi: "आपको किस चीज़ से एलर्जी है?" },
          options: [
            { value: "none", label: { en: "No allergies", hi: "कोई एलर्जी नहीं" } },
            { value: "medicine", label: { en: "Medicines", hi: "दवाइयों से" } },
            { value: "food", label: { en: "Food", hi: "खाने से" } },
            { value: "dust", label: { en: "Dust", hi: "धूल से" } },
            { value: "pollen", label: { en: "Pollen/Flowers", hi: "फूलों से" } },
            { value: "other", label: { en: "Other", hi: "अन्य" } },
          ],
          required: false,
        },
      ],
    },
    {
      id: "family_history",
      title: { en: "Family History", hi: "पारिवारिक इतिहास" },
      icon: "👨‍👩‍👧",
      questions: [
        {
          id: "fh_diabetes",
          type: "yes_no",
          label: { en: "Does anyone in your family have diabetes?", hi: "क्या आपके परिवार में किसी को मधुमेह है?" },
          audio: { en: "Does anyone in your family have diabetes?", hi: "क्या आपके परिवार में किसी को मधुमेह है?" },
          required: true,
        },
        {
          id: "fh_bp",
          type: "yes_no",
          label: { en: "Does anyone in your family have high blood pressure?", hi: "क्या आपके परिवार में किसी को ब्लड प्रेशर है?" },
          audio: { en: "Does anyone in your family have high blood pressure?", hi: "क्या आपके परिवार में किसी को ब्लड प्रेशर है?" },
          required: true,
        },
        {
          id: "fh_heart",
          type: "yes_no",
          label: { en: "Does anyone in your family have heart disease?", hi: "क्या आपके परिवार में किसी को हृदय रोग है?" },
          audio: { en: "Does anyone in your family have heart disease?", hi: "क्या आपके परिवार में किसी को हृदय रोग है?" },
          required: true,
        },
      ],
    },
    {
      id: "personal_history",
      title: { en: "Personal History", hi: "व्यक्तिगत इतिहास" },
      icon: "🏠",
      questions: [
        {
          id: "ph_smoking",
          type: "single_select",
          label: { en: "Do you smoke?", hi: "क्या आप धूम्रपान करते हैं?" },
          audio: { en: "Do you smoke?", hi: "क्या आप धूम्रपान करते हैं?" },
          options: [
            { value: "never", label: { en: "Never", hi: "कभी नहीं" } },
            { value: "former", label: { en: "Stopped", hi: "छोड़ दिया" } },
            { value: "current", label: { en: "Yes", hi: "हां" } },
          ],
          required: true,
        },
        {
          id: "ph_alcohol",
          type: "single_select",
          label: { en: "Do you drink alcohol?", hi: "क्या आप शराब पीते हैं?" },
          audio: { en: "Do you drink alcohol?", hi: "क्या आप शराब पीते हैं?" },
          options: [
            { value: "never", label: { en: "Never", hi: "कभी नहीं" } },
            { value: "occasional", label: { en: "Sometimes", hi: "कभी-कभी" } },
            { value: "regular", label: { en: "Regularly", hi: "रोज़" } },
          ],
          required: true,
        },
      ],
    },
  ],
};

export const AYUSH_QUESTIONNAIRE: Questionnaire = {
  id: "ayush_assessment",
  type: "ayush",
  title: { en: "AYUSH Assessment", hi: "आयुष मूल्यांकन" },
  sections: [
    {
      id: "prakriti",
      title: { en: "Constitution (Prakriti)", hi: "प्रकृति" },
      icon: "🧘",
      questions: [
        {
          id: "pr_body_frame",
          type: "single_select",
          label: { en: "How would you describe your body frame?", hi: "आप अपने शरीर की बनावट कैसे वर्णित करेंगे?" },
          audio: { en: "How would you describe your body frame?", hi: "आप अपने शरीर की बनावट कैसे वर्णित करेंगे?" },
          options: [
            { value: "thin", label: { en: "Thin, light", hi: "पतला, हल्का" }, icon: "🏃" },
            { value: "medium", label: { en: "Medium, muscular", hi: "मध्यम, मांसपेशीदार" }, icon: "⚖️" },
            { value: "heavy", label: { en: "Heavy, broad", hi: "भारी, चौड़ा" }, icon: "🐻" },
          ],
          required: true,
        },
        {
          id: "pr_skin_type",
          type: "single_select",
          label: { en: "How is your skin?", hi: "आपकी त्वचा कैसी है?" },
          audio: { en: "How is your skin?", hi: "आपकी त्वचा कैसी है?" },
          options: [
            { value: "dry", label: { en: "Dry, rough", hi: "शुष्क, खुरदरी" }, icon: "🌵" },
            { value: "oily", label: { en: "Oily, warm", hi: "तैलीय, गर्म" }, icon: "💧" },
            { value: "thick", label: { en: "Thick, cool", hi: "मोटी, ठंडी" }, icon: "🧊" },
          ],
          required: true,
        },
        {
          id: "pr_appetite",
          type: "single_select",
          label: { en: "How is your appetite?", hi: "आपकी भूख कैसी है?" },
          audio: { en: "How is your appetite?", hi: "आपकी भूख कैसी है?" },
          options: [
            { value: "variable", label: { en: "Variable", hi: "बदलती रहती है" }, icon: "📉" },
            { value: "strong", label: { en: "Strong, gets irritable if hungry", hi: "तेज़, भूख लगने पर चिड़चिड़ा" }, icon: "🔥" },
            { value: "steady", label: { en: "Steady, can skip meals", hi: "स्थिर, खाना छोड़ सकते हैं" }, icon: "🪨" },
          ],
          required: true,
        },
      ],
    },
    {
      id: "vikriti",
      title: { en: "Current Imbalance (Vikriti)", hi: "वर्तमान असंतुलन (विकृति)" },
      icon: "⚖️",
      questions: [
        {
          id: "vi_energy",
          type: "single_select",
          label: { en: "How is your energy level today?", hi: "आज आपकी ऊर्जा कैसी है?" },
          audio: { en: "How is your energy level today?", hi: "आज आपकी ऊर्जा कैसी है?" },
          options: [
            { value: "restless", label: { en: "Restless, scattered", hi: "बेचैन, बिखरा हुआ" }, icon: "⚡" },
            { value: "intense", label: { en: "Intense, burning", hi: "तीव्र, जलता हुआ" }, icon: "🔥" },
            { value: "lethargic", label: { en: "Slow, heavy", hi: "धीमा, भारी" }, icon: "🐌" },
          ],
          required: true,
        },
        {
          id: "vi_sleep",
          type: "single_select",
          label: { en: "How is your sleep?", hi: "आपकी नींद कैसी है?" },
          audio: { en: "How is your sleep?", hi: "आपकी नींद कैसी है?" },
          options: [
            { value: "light", label: { en: "Light, wakes easily", hi: "हल्की, आसानी से उठ जाते हैं" }, icon: "👂" },
            { value: "moderate", label: { en: "Moderate, 6-8 hours", hi: "मध्यम, 6-8 घंटे" }, icon: "😴" },
            { value: "deep", label: { en: "Deep, hard to wake", hi: "गहरी, उठना मुश्किल" }, icon: "💤" },
          ],
          required: true,
        },
      ],
    },
    {
      id: "agisha",
      title: { en: "Digestive Fire (Agni)", hi: "पाचन अग्नि" },
      icon: "🔥",
      questions: [
        {
          id: "ag_digestion",
          type: "single_select",
          label: { en: "How is your digestion?", hi: "आपका पाचन कैसा है?" },
          audio: { en: "How is your digestion?", hi: "आपका पाचन कैसा है?" },
          options: [
            { value: "variable", label: { en: "Variable, gas/bloating", hi: "बदलता, गैस/पेट फूलना" }, icon: "💨" },
            { value: "strong", label: { en: "Strong, hungry often", hi: "मजबूत, बार-बार भूख" }, icon: "⚡" },
            { value: "slow", label: { en: "Slow, feels heavy after eating", hi: "धीमा, खाने के बाद भारी" }, icon: "🐢" },
          ],
          required: true,
        },
      ],
    },
    {
      id: "lifestyle",
      title: { en: "Lifestyle (Ahara-Vihara)", hi: "जीवनशैली" },
      icon: "🏃",
      questions: [
        {
          id: "ls_exercise",
          type: "single_select",
          label: { en: "How much do you exercise?", hi: "आप कितना व्यायाम करते हैं?" },
          audio: { en: "How much do you exercise?", hi: "आप कितना व्यायाम करते हैं?" },
          options: [
            { value: "minimal", label: { en: "Rarely exercise", hi: "शायद ही कभी" }, icon: "🛋️" },
            { value: "moderate", label: { en: "Walk/yoga regularly", hi: "नियमित चलना/योग" }, icon: "🚶" },
            { value: "intense", label: { en: "Intense daily exercise", hi: "रोज़ कठोर व्यायाम" }, icon: "🏋️" },
          ],
          required: true,
        },
      ],
    },
  ],
};

export function getQuestionnaire(type: "allopathic" | "ayush"): Questionnaire {
  return type === "ayush" ? AYUSH_QUESTIONNAIRE : ALLOPATHIC_HISTORY;
}

export function getAllQuestions(q: Questionnaire): Question[] {
  return q.sections.flatMap((s) => s.questions);
}
