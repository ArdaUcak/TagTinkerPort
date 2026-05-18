"""Tag profile database.

Direct port of the profile_table in protocol/tagtinker_proto.c — maps a
17-character barcode's 4-digit "type code" to display geometry and color.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class TagKind(Enum):
    UNKNOWN = 0
    DOT_MATRIX = 1
    SEGMENT = 2


class TagColor(Enum):
    MONO = 0
    RED = 1
    YELLOW = 2


@dataclass(frozen=True)
class TagProfile:
    type_code: int
    width: int
    height: int
    kind: TagKind
    color: TagColor
    model_name: str
    pl_bit_def: int = 0

    @property
    def supports_accent(self) -> bool:
        return self.color in (TagColor.RED, TagColor.YELLOW)


# Multiple type_codes mapping to the same model_name (e.g. 1317/1322, or
# 1328/1370/1627/1628) are intentional — they mirror the upstream profile
# table where different production SKUs share a display panel. Do not
# deduplicate without cross-checking tagtinker_proto.c.
_PROFILE_TABLE: tuple[TagProfile, ...] = (
    TagProfile(1206, 0, 0, TagKind.SEGMENT, TagColor.MONO, "Continuum E2 HCS", 0),
    TagProfile(1207, 0, 0, TagKind.SEGMENT, TagColor.MONO, "Continuum E2 HCN", 4),
    TagProfile(1217, 0, 0, TagKind.SEGMENT, TagColor.MONO, "Continuum E5 HCS", 2),
    TagProfile(1219, 0, 0, TagKind.SEGMENT, TagColor.MONO, "Continuum E5 HCN", 1),
    TagProfile(1240, 0, 0, TagKind.SEGMENT, TagColor.MONO, "Continuum E4 HCS", 3),
    TagProfile(1241, 0, 0, TagKind.SEGMENT, TagColor.MONO, "Continuum E4 HCN", 0),
    TagProfile(1242, 0, 0, TagKind.SEGMENT, TagColor.MONO, "Continuum E4 HCN FZ", 0),
    TagProfile(1243, 0, 0, TagKind.SEGMENT, TagColor.MONO, "Continuum E4 HCW", 0),
    TagProfile(1265, 0, 0, TagKind.SEGMENT, TagColor.MONO, "Continuum E5 HCS", 2),
    TagProfile(1275, 320, 192, TagKind.DOT_MATRIX, TagColor.MONO, "DM110", 0),
    TagProfile(1276, 320, 140, TagKind.DOT_MATRIX, TagColor.MONO, "DM90", 0),
    TagProfile(1291, 0, 0, TagKind.SEGMENT, TagColor.MONO, "FVL Promoline 3-16", 0),
    TagProfile(1300, 172, 72, TagKind.DOT_MATRIX, TagColor.MONO, "DM3370", 0),
    TagProfile(1314, 400, 300, TagKind.DOT_MATRIX, TagColor.MONO, "SmartTag HD110", 0),
    TagProfile(1315, 296, 128, TagKind.DOT_MATRIX, TagColor.MONO, "SmartTag HD L", 0),
    TagProfile(1317, 152, 152, TagKind.DOT_MATRIX, TagColor.MONO, "SmartTag HD S", 0),
    TagProfile(1318, 208, 112, TagKind.DOT_MATRIX, TagColor.MONO, "SmartTag HD M", 0),
    TagProfile(1319, 800, 480, TagKind.DOT_MATRIX, TagColor.MONO, "SmartTag HD200", 0),
    TagProfile(1322, 152, 152, TagKind.DOT_MATRIX, TagColor.MONO, "SmartTag HD S", 0),
    TagProfile(1324, 208, 112, TagKind.DOT_MATRIX, TagColor.MONO, "SmartTag HD M FZ", 0),
    TagProfile(1327, 208, 112, TagKind.DOT_MATRIX, TagColor.RED, "SmartTag HD M Red", 0),
    TagProfile(1328, 296, 128, TagKind.DOT_MATRIX, TagColor.RED, "SmartTag HD L Red", 0),
    TagProfile(1336, 400, 300, TagKind.DOT_MATRIX, TagColor.RED, "SmartTag HD110 Red", 0),
    TagProfile(1339, 152, 152, TagKind.DOT_MATRIX, TagColor.RED, "SmartTag HD S Red", 0),
    TagProfile(1340, 800, 480, TagKind.DOT_MATRIX, TagColor.RED, "SmartTag HD200 Red", 0),
    TagProfile(1344, 296, 128, TagKind.DOT_MATRIX, TagColor.YELLOW, "SmartTag HD L Yellow", 0),
    TagProfile(1346, 800, 480, TagKind.DOT_MATRIX, TagColor.YELLOW, "SmartTag HD200 Yellow", 0),
    TagProfile(1348, 264, 176, TagKind.DOT_MATRIX, TagColor.RED, "SmartTag HD T Red", 0),
    TagProfile(1349, 264, 176, TagKind.DOT_MATRIX, TagColor.YELLOW, "SmartTag HD T Yellow", 0),
    TagProfile(1351, 648, 480, TagKind.DOT_MATRIX, TagColor.MONO, "SmartTag HD150", 0),
    TagProfile(1353, 648, 480, TagKind.DOT_MATRIX, TagColor.RED, "SmartTag HD150 Red", 0),
    TagProfile(1354, 648, 480, TagKind.DOT_MATRIX, TagColor.RED, "SmartTag HD150 Red", 0),
    TagProfile(1370, 296, 128, TagKind.DOT_MATRIX, TagColor.RED, "SmartTag HD L Red (2021)", 0),
    TagProfile(1371, 648, 480, TagKind.DOT_MATRIX, TagColor.RED, "SmartTag HD150 Red (2021)", 0),
    TagProfile(1510, 0, 0, TagKind.SEGMENT, TagColor.MONO, "SmartTag E5 M", 1),
    TagProfile(1627, 296, 128, TagKind.DOT_MATRIX, TagColor.RED, "SmartTag HD L Red", 0),
    TagProfile(1628, 296, 128, TagKind.DOT_MATRIX, TagColor.RED, "SmartTag HD L Red", 0),
    TagProfile(1639, 152, 152, TagKind.DOT_MATRIX, TagColor.RED, "SmartTag HD S Red", 0),
)

_BY_TYPE: dict[int, TagProfile] = {p.type_code: p for p in _PROFILE_TABLE}


def lookup_profile(type_code: int) -> Optional[TagProfile]:
    return _BY_TYPE.get(type_code)


def all_profiles() -> tuple[TagProfile, ...]:
    return _PROFILE_TABLE
