# MediKiosk Design Direction

## Concept: The Calm Courtyard

Indian clinics are busy; MediKiosk should feel like the shaded courtyard beside them: ordered, breathable and welcoming. Rounded arch silhouettes, warm paper surfaces and precise clinical typography provide warmth without weakening clinical seriousness.

## Brand

- **Wordmark:** text-only “MediKiosk” until an original logo is supplied.
- **Voice:** short, respectful, direct and reassuring. Hindi and English carry equal visual weight.
- **Colour:** indigo establishes trust, tulsi green confirms safe progress, marigold guides attention, sindoor red is reserved for urgent clinical states, and warm paper replaces sterile white.
- **Typography:** Charter/Palatino-style headings provide a human editorial voice; Trebuchet with Nirmala UI provides legible Latin and Devanagari body text.

## Token model

The source of truth is `packages/ui-system/styles/medikiosk.css`.

1. Primitive tokens define raw colour, type, spacing, radius and shadow values.
2. Semantic tokens name purpose: canvas, surface, ink, brand, success, warning and danger.
3. Component tokens tune buttons, cards, pills and focus rings.

## Role expression

- **Patient:** spacious, centered, bilingual and voice-led; large controls and minimal decisions.
- **Nurse:** operational density with a queue-first reading order, visible vitals and handoff ownership.
- **Doctor:** evidence-first composition with a patient summary rail, editable draft and sign-off boundary.

## Interaction and accessibility

- Minimum patient touch target: 56px. Minimum clinician target: 44px.
- Focus is always visible and does not rely on colour alone.
- Urgency includes a text label and rule explanation.
- Motion is limited to a single soft entrance and listening pulse, and is disabled by reduced-motion preferences.
- Layouts collapse to one column without hiding clinical status or primary actions.
