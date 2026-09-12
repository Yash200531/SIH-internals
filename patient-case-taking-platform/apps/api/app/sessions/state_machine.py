"""Redis-backed session state machine.
Sessions are short-lived, facility-scoped, and auto-expire."""
import time
from dataclasses import dataclass
from enum import Enum
from uuid import UUID, uuid4

from app.audit.emitter import audit_emitter


class SessionType(str, Enum):
    KIOSK = "kiosk"
    PWA = "pwa"
    STAFF = "staff"
    ASSISTED = "assisted"


class SessionState(str, Enum):
    INITIALIZING = "initializing"  # session created, not yet active
    ACTIVE = "active"  # user is interacting
    IDLE = "idle"  # no activity for threshold
    EXPIRING = "expiring"  # approaching timeout, show warning
    EXPIRED = "expired"  # timed out, data wiped
    WIPE_SCHEDULED = "wipe_scheduled"  # manual expiry requested
    WIPED = "wiped"  # all PHI wiped


# State transitions
VALID_TRANSITIONS = {
    SessionState.INITIALIZING: [SessionState.ACTIVE, SessionState.EXPIRED],
    SessionState.ACTIVE: [SessionState.IDLE, SessionState.EXPIRING, SessionState.EXPIRED, SessionState.WIPE_SCHEDULED],
    SessionState.IDLE: [SessionState.ACTIVE, SessionState.EXPIRING, SessionState.EXPIRED, SessionState.WIPE_SCHEDULED],
    SessionState.EXPIRING: [SessionState.ACTIVE, SessionState.EXPIRED, SessionState.WIPE_SCHEDULED],
    SessionState.EXPIRED: [SessionState.WIPED],
    SessionState.WIPE_SCHEDULED: [SessionState.EXPIRED, SessionState.WIPED],
    SessionState.WIPED: [],  # terminal
}


# Timeout defaults (seconds)
TIMEOUTS = {
    SessionType.KIOSK: 300,  # 5 minutes
    SessionType.ASSISTED: 600,  # 10 minutes
    SessionType.PWA: 1800,  # 30 minutes
    SessionType.STAFF: 3600,  # 1 hour
}

IDLE_THRESHOLDS = {
    SessionType.KIOSK: 60,  # 1 minute
    SessionType.ASSISTED: 120,  # 2 minutes
    SessionType.PWA: 300,  # 5 minutes
    SessionType.STAFF: 600,  # 10 minutes
}


@dataclass
class Session:
    session_id: UUID
    session_type: SessionType
    facility_id: UUID
    state: SessionState
    user_id: UUID | None
    device_id: str | None
    language: str
    created_at: float
    last_activity_at: float
    expires_at: float
    wiped_at: float | None
    metadata: dict


class SessionManager:
    """In-memory session manager (replace with Redis in production)."""

    def __init__(self):
        self._sessions: dict[str, Session] = {}

    def create_session(self, session_type: SessionType, facility_id: UUID, device_id: str | None = None, language: str = "hi") -> Session:
        """Create a new session with auto-expiry."""
        now = time.time()
        timeout = TIMEOUTS[session_type]
        session = Session(
            session_id=uuid4(),
            session_type=session_type,
            facility_id=facility_id,
            state=SessionState.INITIALIZING,
            user_id=None,
            device_id=device_id,
            language=language,
            created_at=now,
            last_activity_at=now,
            expires_at=now + timeout,
            wiped_at=None,
            metadata={},
        )
        self._sessions[str(session.session_id)] = session

        audit_emitter.emit(
            tenant_id=UUID(int=0),  # sessions don't have tenant_id directly; use facility lookup
            actor_id=None,
            actor_type="kiosk",
            actor_role=None,
            action="session_create",
            resource_type="session",
            resource_id=session.session_id,
            audit_metadata={"session_type": session_type, "facility_id": str(facility_id)},
        )

        return session

    def get_session(self, session_id: UUID) -> Session | None:
        session = self._sessions.get(str(session_id))
        if session and self._is_expired(session):
            self._expire_session(session)
        return session

    def transition(self, session_id: UUID, target_state: SessionState) -> Session | None:
        """Transition session to new state."""
        session = self._sessions.get(str(session_id))
        if not session:
            return None

        if target_state not in VALID_TRANSITIONS.get(session.state, []):
            raise ValueError(f"Invalid transition: {session.state} → {target_state}")

        session.state = target_state
        session.last_activity_at = time.time()

        if target_state == SessionState.WIPED:
            session.wiped_at = time.time()

        return session

    def touch(self, session_id: UUID) -> Session | None:
        """Update last activity time. Returns session or None if expired."""
        session = self._sessions.get(str(session_id))
        if not session:
            return None
        if self._is_expired(session):
            self._expire_session(session)
            return None
        session.last_activity_at = time.time()
        session.state = SessionState.ACTIVE
        return session

    def expire_all_for_facility(self, facility_id: UUID) -> int:
        """Expire all active sessions for a facility (security incident)."""
        count = 0
        for session in self._sessions.values():
            if session.facility_id == facility_id and session.state not in (SessionState.EXPIRED, SessionState.WIPED):
                self._expire_session(session)
                count += 1
        return count

    def wipe_session(self, session_id: UUID) -> bool:
        """Immediately wipe a session."""
        session = self._sessions.get(str(session_id))
        if not session:
            return False
        self.transition(session_id, SessionState.WIPE_SCHEDULED)
        self.transition(session_id, SessionState.EXPIRED)
        self.transition(session_id, SessionState.WIPED)

        audit_emitter.emit(
            tenant_id=UUID(int=0),
            actor_id=None,
            actor_type="system",
            actor_role=None,
            action="session_wipe",
            resource_type="session",
            resource_id=session_id,
        )

        return True

    def list_active_sessions(self, facility_id: UUID | None = None) -> list[Session]:
        """List active sessions, optionally filtered by facility."""
        results = []
        for session in self._sessions.values():
            if session.state in (SessionState.EXPIRED, SessionState.WIPED):
                continue
            if facility_id and session.facility_id != facility_id:
                continue
            results.append(session)
        return results

    def _is_expired(self, session: Session) -> bool:
        return time.time() > session.expires_at

    def _expire_session(self, session: Session):
        """Auto-expire a session and wipe PHI."""
        session.state = SessionState.EXPIRED
        session.wiped_at = time.time()

        audit_emitter.emit(
            tenant_id=UUID(int=0),
            actor_id=None,
            actor_type="system",
            actor_role=None,
            action="session_expire",
            resource_type="session",
            resource_id=session.session_id,
            audit_metadata={"reason": "timeout"},
        )


# Singleton
session_manager = SessionManager()
