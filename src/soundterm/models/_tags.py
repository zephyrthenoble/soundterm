from __future__ import annotations
from sqlmodel import SQLModel, Relationship, Field, String
from soundterm.utils import random_color


class ParentTagLink(SQLModel, table=True):
    parent_tag_id: int = Field(foreign_key="tag.id", primary_key=True)
    child_tag_id: int = Field(foreign_key="tag.id", primary_key=True)


class GroupTagLink(SQLModel, table=True):
    group_id: int = Field(foreign_key="taggroup.id", primary_key=True)
    tag_id: int = Field(foreign_key="tag.id", primary_key=True)


class Tag(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(
        default=None,
        unique=True,
        sa_column_kwargs={"type_": String(collation="NOCASE")},
        description="The name of the tag (case-insensitive unique)",
    )
    parent_tags: set["Tag"] = Relationship(
        back_populates="child_tags", link_model=ParentTagLink
    )
    child_tags: set["Tag"] = Relationship(
        back_populates="parent_tags", link_model=ParentTagLink
    )
    group: "TagGroup" = Relationship(back_populates="tags", link_model=GroupTagLink)

    def get_all_child_tags(
        self: "Tag", child_tags: set["Tag"] | None = None
    ) -> set["Tag"]:
        if child_tags is None:
            child_tags: set[Tag] = set()
        for child_tag in self.child_tags:
            child_tags.add(child_tag)
            child_tags.update(child_tag.get_all_child_tags(child_tags))
        return child_tags

    def get_all_parent_tags(
        self: "Tag", parent_tags: set["Tag"] | None = None
    ) -> set["Tag"]:
        if parent_tags is None:
            parent_tags: set[Tag] = set()
        for parent_tag in self.parent_tags:
            parent_tags.add(parent_tag)
            parent_tags.update(parent_tag.get_all_parent_tags(parent_tags))
        return parent_tags


class TagGroup(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True)
    color: str = Field(default_factory=random_color)
    tags: set[Tag] = Relationship(back_populates="group", link_model=GroupTagLink)
