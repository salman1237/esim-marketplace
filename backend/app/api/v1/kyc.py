import uuid
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.models.kyc import KYCSubmission, KYCStatus

router = APIRouter(prefix="/kyc", tags=["KYC Verification"])

KYC_UPLOAD_DIR = Path(settings.KYC_UPLOADS_DIR)
KYC_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

KYC_CONTENT_TYPES = {
    "image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "application/pdf": ".pdf",
}
MAX_KYC_UPLOAD_BYTES = 5 * 1024 * 1024  # 5MB - ID scans can be larger than a logo


async def _save_kyc_file(file: UploadFile) -> str:
    ext = KYC_CONTENT_TYPES.get(file.content_type)
    if not ext:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {file.content_type}")
    contents = await file.read()
    if len(contents) > MAX_KYC_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="File too large (max 5MB)")
    filename = f"{uuid.uuid4().hex}{ext}"
    (KYC_UPLOAD_DIR / filename).write_bytes(contents)
    return filename


@router.post("/submit")
async def submit_kyc(
    nid_number: str = Form(...),
    document_front: UploadFile = File(...),
    document_back: UploadFile | None = File(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    front_filename = await _save_kyc_file(document_front)
    back_filename = await _save_kyc_file(document_back) if document_back else None

    res = await db.execute(select(KYCSubmission).where(KYCSubmission.user_id == current_user.id))
    submission = res.scalar_one_or_none()
    if submission:
        # Resubmission (e.g. after a rejection) - always resets to PENDING
        # for another review pass, and clears any prior rejection reason.
        submission.nid_number = nid_number
        submission.document_front_filename = front_filename
        submission.document_back_filename = back_filename
        submission.status = KYCStatus.PENDING
        submission.rejection_reason = None
        submission.reviewed_by_id = None
        submission.reviewed_at = None
    else:
        submission = KYCSubmission(
            user_id=current_user.id,
            nid_number=nid_number,
            document_front_filename=front_filename,
            document_back_filename=back_filename,
        )
        db.add(submission)

    await db.commit()
    return {"status": "success", "submission_status": "PENDING"}


@router.get("/me")
async def get_my_kyc(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(KYCSubmission).where(KYCSubmission.user_id == current_user.id))
    submission = res.scalar_one_or_none()
    if not submission:
        return {"submitted": False, "status": None}
    return {
        "submitted": True,
        "status": submission.status.value,
        "rejection_reason": submission.rejection_reason,
        "submitted_at": submission.submitted_at,
    }
