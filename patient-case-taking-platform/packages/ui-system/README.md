# MediKiosk UI System

Accessible, multilingual foundations shared by the patient and clinician applications.

- `styles/medikiosk.css` is the source of truth for primitive, semantic and component tokens.
- Apps may add layout CSS, but colours, type, radii, shadows and component states should resolve through shared tokens.
- Patient controls use a 56px minimum target; clinician controls use 44px.
- Status never relies on colour alone. AI-authored clinical content always carries a visible draft status.

See `../../DESIGN.md` for brand rationale and role-specific behavior.
