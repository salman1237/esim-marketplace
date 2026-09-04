import uuid
import enum
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Enum, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.core.database import Base


class KYCStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class KYCSubmission(Base):
    __tablename__ = "kyc_submissions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    nid_number = Column(String(100), nullable=False)
    # Filenames only (not full paths, not public URLs) - resolved against
    # settings.KYC_UPLOADS_DIR by the authenticated document endpoint.
    # Deliberately not served by the public /api/v1/uploads static mount
    # used for branding assets - these are national ID documents.
    document_front_filename = Column(String(255), nullable=False)
    document_back_filename = Column(String(255), nullable=True)
    status = Column(Enum(KYCStatus), default=KYCStatus.PENDING, nullable=False)
    rejection_reason = Column(Text, nullable=True)
    reviewed_by_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    submitted_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    user = relationship("User", foreign_keys=[user_id])
    reviewer = relationship("User", foreign_keys=[reviewed_by_id])
