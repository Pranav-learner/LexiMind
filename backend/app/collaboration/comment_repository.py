"""Data-access layer for the Comment table."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select, update, func
from sqlalchemy.orm import Session

from app.collaboration.models import Comment


class CommentRepository:

    @staticmethod
    def create(db: Session, comment: Comment) -> Comment:
        db.add(comment)
        db.flush()
        return comment

    @staticmethod
    def get_by_id(db: Session, comment_id: str) -> Optional[Comment]:
        return db.scalar(
            select(Comment).where(
                Comment.id == comment_id,
                Comment.deleted_at.is_(None),
            )
        )

    @staticmethod
    def list_for_target(
        db: Session,
        workspace_id: str,
        target_type: str,
        target_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Comment]:
        return list(
            db.scalars(
                select(Comment)
                .where(
                    Comment.workspace_id == workspace_id,
                    Comment.target_type == target_type,
                    Comment.target_id == target_id,
                    Comment.deleted_at.is_(None),
                )
                .order_by(Comment.created_at)
                .limit(limit)
                .offset(offset)
            )
        )

    @staticmethod
    def list_for_workspace(
        db: Session,
        workspace_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Comment]:
        return list(
            db.scalars(
                select(Comment)
                .where(
                    Comment.workspace_id == workspace_id,
                    Comment.deleted_at.is_(None),
                )
                .order_by(Comment.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        )

    @staticmethod
    def list_replies(db: Session, parent_id: str) -> list[Comment]:
        return list(
            db.scalars(
                select(Comment)
                .where(
                    Comment.parent_comment_id == parent_id,
                    Comment.deleted_at.is_(None),
                )
                .order_by(Comment.created_at)
            )
        )

    @staticmethod
    def update_content(db: Session, comment: Comment, content: str) -> Comment:
        comment.content = content
        comment.is_edited = True
        comment.edit_count += 1
        db.flush()
        return comment

    @staticmethod
    def soft_delete(db: Session, comment: Comment) -> None:
        from datetime import datetime, timezone
        comment.deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.flush()

    @staticmethod
    def resolve(db: Session, comment: Comment, resolver_id: str) -> Comment:
        from datetime import datetime, timezone
        comment.is_resolved = True
        comment.resolved_by = resolver_id
        comment.resolved_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.flush()
        return comment

    @staticmethod
    def unresolve(db: Session, comment: Comment) -> Comment:
        comment.is_resolved = False
        comment.resolved_by = None
        comment.resolved_at = None
        db.flush()
        return comment

    @staticmethod
    def increment_reply_count(db: Session, comment_id: str, delta: int = 1) -> None:
        db.execute(
            update(Comment)
            .where(Comment.id == comment_id)
            .values(reply_count=Comment.reply_count + delta)
        )
        db.flush()

    @staticmethod
    def count_for_target(
        db: Session,
        workspace_id: str,
        target_type: str,
        target_id: str,
    ) -> int:
        return db.scalar(
            select(func.count()).select_from(Comment).where(
                Comment.workspace_id == workspace_id,
                Comment.target_type == target_type,
                Comment.target_id == target_id,
                Comment.deleted_at.is_(None),
            )
        ) or 0
