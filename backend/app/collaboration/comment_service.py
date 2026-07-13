"""Unified commenting engine.

Comments can be attached to any artifact type via (target_type, target_id). Supports
threading (parent_comment_id), @mentions, and resolution workflows.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.collaboration.comment_repository import CommentRepository
from app.collaboration.errors import CommentNotFound, CommentNotOwned
from app.collaboration.models import Comment
from app.collaboration.validation import validate_comment_content


class CommentService:

    def __init__(self, repo: CommentRepository | None = None):
        self.repo = repo or CommentRepository()

    def create(
        self,
        db: Session,
        *,
        workspace_id: str,
        author_id: str,
        target_type: str,
        target_id: str,
        content: str,
        parent_comment_id: str | None = None,
        mentions: list[str] | None = None,
    ) -> Comment:
        content = validate_comment_content(content)

        # Validate parent exists (if threading).
        if parent_comment_id:
            parent = self.repo.get_by_id(db, parent_comment_id)
            if parent is None:
                raise CommentNotFound(parent_comment_id)

        comment = Comment(
            workspace_id=workspace_id,
            author_id=author_id,
            target_type=target_type,
            target_id=target_id,
            content=content,
            parent_comment_id=parent_comment_id,
            mentions=mentions,
        )
        self.repo.create(db, comment)

        # Update parent's reply count.
        if parent_comment_id:
            self.repo.increment_reply_count(db, parent_comment_id)

        db.commit()
        return comment

    def get(self, db: Session, comment_id: str) -> Comment:
        comment = self.repo.get_by_id(db, comment_id)
        if comment is None:
            raise CommentNotFound(comment_id)
        return comment

    def list_for_target(
        self,
        db: Session,
        workspace_id: str,
        target_type: str,
        target_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Comment]:
        return self.repo.list_for_target(
            db, workspace_id, target_type, target_id, limit=limit, offset=offset
        )

    def list_for_workspace(
        self,
        db: Session,
        workspace_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Comment]:
        return self.repo.list_for_workspace(db, workspace_id, limit=limit, offset=offset)

    def edit(
        self,
        db: Session,
        comment_id: str,
        *,
        actor_id: str,
        content: str,
    ) -> Comment:
        comment = self.get(db, comment_id)
        if comment.author_id != actor_id:
            raise CommentNotOwned()
        content = validate_comment_content(content)
        self.repo.update_content(db, comment, content)
        db.commit()
        return comment

    def delete(
        self,
        db: Session,
        comment_id: str,
        *,
        actor_id: str,
    ) -> None:
        comment = self.get(db, comment_id)
        if comment.author_id != actor_id:
            raise CommentNotOwned()
        self.repo.soft_delete(db, comment)

        # Decrement parent reply count.
        if comment.parent_comment_id:
            self.repo.increment_reply_count(db, comment.parent_comment_id, -1)

        db.commit()

    def resolve(
        self,
        db: Session,
        comment_id: str,
        *,
        resolver_id: str,
    ) -> Comment:
        comment = self.get(db, comment_id)
        self.repo.resolve(db, comment, resolver_id)
        db.commit()
        return comment

    def unresolve(self, db: Session, comment_id: str) -> Comment:
        comment = self.get(db, comment_id)
        self.repo.unresolve(db, comment)
        db.commit()
        return comment
