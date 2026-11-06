"""SQLAlchemy ORM models for the Circle recommendations schema."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class UTCDateTime(TypeDecorator):
    """Store datetimes in UTC and always return timezone-aware values.

    SQLite has no native timezone type; without this wrapper, round-tripped
    values can become naive and break aware/naive comparisons in later phases.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(
        self, value: datetime | None, dialect: Dialect
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(
        self, value: datetime | None, dialect: Dialect
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class Topic(Base):
    __tablename__ = "topics"
    __table_args__ = (UniqueConstraint("slug", name="uq_topics_slug"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(128), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    domain: Mapped[str] = mapped_column(String(64), nullable=False)

    users: Mapped[list[User]] = relationship(
        secondary="user_interests",
        back_populates="interests",
        viewonly=True,
    )
    circles: Mapped[list[Circle]] = relationship(back_populates="primary_topic")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "profile_completeness >= 0 AND profile_completeness <= 1",
            name="ck_users_profile_completeness",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    first_name: Mapped[str] = mapped_column(String(128), nullable=False)
    last_name: Mapped[str] = mapped_column(String(128), nullable=False)
    has_photo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    joined_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    profile_completeness: Mapped[float] = mapped_column(Float, nullable=False)

    interests: Mapped[list[Topic]] = relationship(
        secondary="user_interests",
        back_populates="users",
        viewonly=True,
    )
    user_interests: Mapped[list[UserInterest]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    memberships: Mapped[list[Membership]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    activity_posts: Mapped[list[Activity]] = relationship(back_populates="author")


class Circle(Base):
    __tablename__ = "circles"
    __table_args__ = (
        CheckConstraint("member_count >= 0", name="ck_circles_member_count_nonneg"),
        CheckConstraint(
            "max_members IS NULL OR max_members >= 0",
            name="ck_circles_max_members_nonneg",
        ),
        CheckConstraint("feed_posts_30d >= 0", name="ck_circles_feed_posts_nonneg"),
        CheckConstraint("chat_messages_30d >= 0", name="ck_circles_chat_messages_nonneg"),
        CheckConstraint(
            "format IN ('in_person', 'virtual', 'hybrid')",
            name="ck_circles_format",
        ),
        CheckConstraint(
            "access IN ('public', 'unlisted')",
            name="ck_circles_access",
        ),
        CheckConstraint(
            "join_policy IN ('open', 'request')",
            name="ck_circles_join_policy",
        ),
        Index("ix_circles_primary_topic_id", "primary_topic_id"),
        UniqueConstraint("slug", name="uq_circles_slug"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    primary_topic_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("topics.id"),
        nullable=True,
    )
    cover_image_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    format: Mapped[str] = mapped_column(String(32), nullable=False)
    access: Mapped[str] = mapped_column(String(32), nullable=False)
    join_policy: Mapped[str] = mapped_column(String(32), nullable=False)
    max_members: Mapped[int | None] = mapped_column(Integer, nullable=True)
    member_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    last_activity_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    feed_posts_30d: Mapped[int] = mapped_column(Integer, nullable=False)
    chat_messages_30d: Mapped[int] = mapped_column(Integer, nullable=False)

    primary_topic: Mapped[Topic | None] = relationship(back_populates="circles")
    tags: Mapped[list[CircleTag]] = relationship(
        back_populates="circle",
        cascade="all, delete-orphan",
    )
    memberships: Mapped[list[Membership]] = relationship(
        back_populates="circle",
        cascade="all, delete-orphan",
    )
    activity_posts: Mapped[list[Activity]] = relationship(
        back_populates="circle",
        cascade="all, delete-orphan",
    )


class UserInterest(Base):
    __tablename__ = "user_interests"

    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    topic_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("topics.id", ondelete="CASCADE"),
        primary_key=True,
    )

    user: Mapped[User] = relationship(back_populates="user_interests")
    topic: Mapped[Topic] = relationship()


class CircleTag(Base):
    __tablename__ = "circle_tags"

    circle_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("circles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tag: Mapped[str] = mapped_column(String(128), primary_key=True)

    circle: Mapped[Circle] = relationship(back_populates="tags")


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        CheckConstraint("role IN ('member', 'leader')", name="ck_memberships_role"),
        Index("ix_memberships_circle_id", "circle_id"),
    )

    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    circle_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("circles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    joined_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)

    user: Mapped[User] = relationship(back_populates="memberships")
    circle: Mapped[Circle] = relationship(back_populates="memberships")


class Activity(Base):
    __tablename__ = "activity"
    __table_args__ = (
        CheckConstraint("reaction_count >= 0", name="ck_activity_reaction_nonneg"),
        CheckConstraint("comment_count >= 0", name="ck_activity_comment_nonneg"),
        CheckConstraint("save_count >= 0", name="ck_activity_save_nonneg"),
        Index("ix_activity_circle_id_created_at", "circle_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    circle_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("circles.id", ondelete="CASCADE"),
        nullable=False,
    )
    author_user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    reaction_count: Mapped[int] = mapped_column(Integer, nullable=False)
    comment_count: Mapped[int] = mapped_column(Integer, nullable=False)
    save_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)

    circle: Mapped[Circle] = relationship(back_populates="activity_posts")
    author: Mapped[User] = relationship(back_populates="activity_posts")
