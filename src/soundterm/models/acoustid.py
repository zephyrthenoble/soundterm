from sqlmodel import Field, SQLModel
from pydantic import ConfigDict, model_validator


class AcoustIDAPIModel(SQLModel):
    # populate_by_name: allows us to use the alias (e.g. "type") when creating the model, even though the field name is different (e.g. "primary_type")
    # extra="ignore": allows us to ignore any extra fields that are not defined in the model, which is useful when dealing with APIs that may return additional data we don't care about
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class AcoustIDSongArtist(AcoustIDAPIModel):
    id: str
    name: str


class AcoustIDSongReleaseGroupType(AcoustIDAPIModel):
    primary_type: str | None = Field(default=None, alias="type")
    secondary_types: list[str] = Field(default_factory=list, alias="secondarytypes")


class AcoustIDSongReleaseGroup(AcoustIDAPIModel):
    id: str
    title: str | None = None
    artists: list[AcoustIDSongArtist] = Field(default_factory=list)
    release_group_type: AcoustIDSongReleaseGroupType | None = None

    @model_validator(mode="before")
    @classmethod
    def build_release_group_type(cls, data: object) -> object:
        if isinstance(data, dict):
            if "release_group_type" not in data and (
                "type" in data or "secondarytypes" in data
            ):
                data = {
                    **data,
                    "release_group_type": AcoustIDSongReleaseGroupType.model_validate(
                        data
                    ),
                }
        return data


class AcoustIDSongRecordings(AcoustIDAPIModel):
    id: str
    duration: float
    title: str
    artists: list[AcoustIDSongArtist] = Field(default_factory=list)


class AcoustIDSongMetadata(AcoustIDAPIModel):
    id: str
    releasegroups: list[AcoustIDSongReleaseGroup] = Field(default_factory=list)
    recordings: list[AcoustIDSongRecordings] = Field(default_factory=list)


class AcoustIDSongMetadataResults(AcoustIDAPIModel):
    id: str
    recordings: list[AcoustIDSongMetadata] = Field(default_factory=list)
