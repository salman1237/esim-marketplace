from sqlalchemy.ext.asyncio import AsyncSession
from app.models.audit import AuditLog

class AuditService:
    @staticmethod
    async def log_action(
        db: AsyncSession,
        actor_id: str,
        actor_role: str,
        action: str,
        ip_address: str = None,
        user_agent: str = None,
        before_state: dict = None,
        after_state: dict = None
    ):
        log = AuditLog(
            actor_id=actor_id,
            actor_role=actor_role,
            action=action,
            ip_address=ip_address,
            user_agent=user_agent,
            before_state=before_state,
            after_state=after_state
        )
        db.add(log)
        await db.commit()
