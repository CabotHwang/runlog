import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

SCHEMA_VERSION = 1
_RECORD_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")


def validate_record_id(record_id: str) -> None:
    """Validate the record identifier."""
    if not isinstance(record_id, str) or not _RECORD_ID.fullmatch(record_id):
        raise ValueError(
            "record_id must start with a letter or digit and contain "
            "1–64 letters, digits, underscores, dots or hyphens"
        )


@dataclass(frozen=True)
class Channel:
    name: str
    unit: str

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name or self.name == "time":
            raise ValueError('channel name must be non-empty and must not be "time"')
        if not isinstance(self.unit, str) or not self.unit.strip():
            raise ValueError("channel unit must be a non-empty string")


@dataclass(frozen=True)
class RecordMeta:
    record_id: str
    channels: tuple[Channel, ...]
    attrs: dict[str, int | float | str | bool]
    source: str
    n_samples: int
    sha256: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        validate_record_id(self.record_id)
        if type(self.schema_version) is not int or self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported schema_version")
        if not isinstance(self.channels, tuple) or not all(
            isinstance(channel, Channel) for channel in self.channels
        ):
            raise ValueError("channels must be a tuple of Channel objects")
        names = [channel.name for channel in self.channels]
        if len(names) != len(set(names)):
            raise ValueError("channel names must be unique")
        if not isinstance(self.attrs, dict) or any(
            not isinstance(key, str) or type(value) not in (int, float, str, bool)
            for key, value in self.attrs.items()
        ):
            raise ValueError("attrs must map string keys to scalar values")
        if (
            not isinstance(self.source, str)
            or not self.source
            or any(separator in self.source for separator in ("/", "\\"))
            or self.source in (".", "..")
        ):
            raise ValueError("source must be a file name only")
        if type(self.n_samples) is not int or self.n_samples < 0:
            raise ValueError("n_samples must be a non-negative integer")
        if not isinstance(self.sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise ValueError("sha256 must contain 64 lowercase hexadecimal digits")

    def to_json(self, path: str | Path) -> None:
        """Write the record sidecar as JSON."""
        Path(path).write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")

    @classmethod
    def from_json(cls, path: str | Path) -> "RecordMeta":
        """Read and validate a record sidecar."""
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            if "schema_version" not in data:
                raise ValueError("sidecar must contain schema_version")
            data["channels"] = tuple(Channel(**channel) for channel in data["channels"])
            return cls(**data)
        except (TypeError, KeyError, json.JSONDecodeError) as exc:
            raise ValueError("invalid record sidecar") from exc
